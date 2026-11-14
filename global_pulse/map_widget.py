"""A local, custom Qt map. No remote tile server, browser, or paid map API."""
from __future__ import annotations

import json
import math
import re
import html
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPainterPath, QFont, QTransform, QRadialGradient
from PySide6.QtWidgets import (QWidget, QToolTip, QDialog, QVBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QLabel, QLineEdit, QComboBox)

from .theme import SEVERITY
from .crisis_overlay import build_country_activity, normalize_country
from .map_evidence import incident_country
from .map_area_layer import WarningAreaLayer


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# Country-level source evidence is not precise incident geolocation.
# These distinct category colors are deliberately separate from SEVERITY,
# which remains authoritative for genuine coordinate/area event markers.
CATEGORY_COLORS = {
    "Conflict": "#e77482", "Government": "#b798ee",
    "Economy": "#5ecbbf", "Health": "#68d88f",
    "Humanitarian": "#efb97e", "Infrastructure": "#72adf3",
    "News": "#bec6dc", "Disaster": "#ebbb70",
}
_CATEGORY_PRIORITY = (
    "Conflict", "Government", "Economy", "Health",
    "Humanitarian", "Infrastructure", "News", "Disaster",
)


class WorldMap(QWidget):
    event_selected = Signal(str)
    country_selected = Signal(str)
    global_search_requested = Signal(str)  # Search full archive; no geographic attribution implied
    economic_country_requested = Signal(str)  # Country-only dated measurements -> Economy tab
    view_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Interactive world event map")
        self.setAccessibleDescription("Drag to pan, scroll or plus/minus to zoom. Home resets. Tab moves between controls. Marker color is importance; its ring is evidence status.")
        self.events = []
        self.gdelt_layer = None
        self.evidence_events = []
        self.observations = []
        self.economic_observations = {}
        self._activity_categories = object()
        self.area_layer = WarningAreaLayer(self)
        self.selected_event = ""
        self.selected_country = ""
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.density = False
        self.labels = True
        self.categories = None
        self.crisis_layers = {"conflict": True, "unrest": True, "migration": True}
        self.crisis_overlay_enabled = True
        self.country_activity = {}
        self.country_only_evidence = {}  # Neutral/historical country-only archive
        self.country_category_evidence = {}  # All attributed categories, including current reports
        self._country_badge_hits = []
        self.country_dialog = None
        self._drag = None
        self._moved = False
        self._hits = []
        self.cluster_dialog = None
        self._countries = []
        self._hover_country = ""
        self._load_map()

    def _load_map(self):
        path = Path(__file__).parent / "resources" / "world_countries.geojson"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._map_error = "Offline map asset unavailable"
            return
        self._map_error = ""
        for f in data.get("features", []):
            geom, props = f.get("geometry", {}), f.get("properties", {})
            polygons = geom.get("coordinates", [])
            if geom.get("type") == "Polygon":
                polygons = [polygons]
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)
            for poly in polygons:
                for ring in poly:
                    if not ring:
                        continue
                    last = None
                    for lon, lat, *_ in ring:
                        point = self.normalized(lon, lat)
                        if last is None or abs(lon - last) > 180:
                            path.moveTo(point)
                        else:
                            path.lineTo(point)
                        last = lon
                    path.closeSubpath()
            self._countries.append({"name": props.get("name", "Unknown"), "region": props.get("region", ""),
                                    "code": props.get("code", ""), "label": props.get("label"), "path": path})

    @staticmethod
    def normalized(lon, lat):
        return QPointF((lon + 180.0) / 360.0, (85.0 - lat) / 145.0)

    @property
    def country_names(self):
        return sorted(c["name"] for c in self._countries if c["name"] != "Antarctica")

    def view_state(self):
        return {"zoom": self.zoom, "pan_x": self.pan_x, "pan_y": self.pan_y, "density": self.density, "labels": self.labels,
                "categories": sorted(self.categories) if self.categories is not None else None,
                "crisis_overlay_enabled": self.crisis_overlay_enabled,
                "crisis_layers": dict(self.crisis_layers)}

    def restore_view(self, state):
        if not isinstance(state, dict):
            return
        for name, low, high in (("zoom", 1.0, 20.0), ("pan_x", -0.55, 0.55), ("pan_y", -0.55, 0.55)):
            val = state.get(name)
            if _number(val):
                setattr(self, name, min(high, max(low, float(val))))
        self.density = bool(state.get("density", False))
        self.labels = bool(state.get("labels", True))
        categories=state.get("categories")
        self.categories={str(v) for v in categories[:100]} if isinstance(categories,list) else None
        self.crisis_overlay_enabled = bool(state.get("crisis_overlay_enabled", True))
        layers = state.get("crisis_layers")
        if isinstance(layers, dict):
            for key in ("conflict", "unrest", "migration"):
                if key in layers:
                    self.crisis_layers[key] = bool(layers[key])
        self.update()

    def reset_view(self):
        self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0
        self.selected_country = ""
        self.update()
        self.view_changed.emit()

    def _transform(self):
        return QTransform(self.width() * self.zoom, 0, 0, self.height() * self.zoom,
                          self.width() * (.5 - (.5 + self.pan_x) * self.zoom),
                          self.height() * (.5 - (.5 + self.pan_y) * self.zoom))

    def point(self, lon, lat):
        return self._transform().map(self.normalized(lon, lat))

    def set_events(self, events, *, country_events=None, observations=None):
        self.events = list(events)[:5000]
        self.evidence_events = list(country_events)[:5000] if country_events is not None else list(self.events)
        self.observations = [dict(item) for item in list(observations or [])[:10000] if isinstance(item, dict)]
        self.area_layer.set_events(self.evidence_events)
        self._activity_categories = object()
        self._refresh_country_activity()
        self.update()

    def _refresh_country_activity(self):
        key = None if self.categories is None else frozenset(self.categories)
        if key != self._activity_categories:
            selected = [e for e in self.evidence_events if key is None or e.get("category") in key]
            # Use one evidence-time boundary for both the current crisis layer
            # and neutral archive classification. Local Store refresh time must
            # not make an old report look like a current crisis.
            now = datetime.now(timezone.utc)
            self.country_activity = build_country_activity(selected, now=now)
            # Keep precisely attributed, country-only archives discoverable even
            # when they have no point/area or do not qualify for a current crisis
            # stripe. These are *records*, not new crisis assertions.
            countries = {normalize_country(c["name"]) for c in self._countries}
            self.country_only_evidence = {}
            self.country_category_evidence = {}
            for record in selected:
                if record.get("synthetic"):
                    continue
                country = normalize_country(incident_country(record))
                if not country or country not in countries:
                    continue
                # A country-category circle summarizes attributable SOURCE
                # records, including those separately represented by a real
                # incident point/area or a corroborated current crisis stripe.
                # It NEVER denotes a new incident at the country label.
                category = str(record.get("category") or "News").strip().title()
                category_entry = self.country_category_evidence.setdefault(
                    country, {"count": 0, "events": [], "categories": {}}
                )
                category_entry["count"] += 1
                category_entry["categories"][category] = (
                    category_entry["categories"].get(category, 0) + 1
                )
                category_entry["events"].append(record)
                # Preserve the old neutral/historical country-only index and
                # its no-double-counting contract. Current supported crises
                # stay in the separate stripe, not this neutral archive.
                if self.has_location(record) or record.get("map_areas"):
                    continue
                # The country activity's event_ids are capped at 20 for display:
                # do not use that truncated list to decide what is neutral.
                # Reuse the exact accepted crisis classifier on each *record*,
                # not the country aggregate (which may contain other records).
                # A qualifying current report must not also be counted or
                # drawn as neutral historical country-only evidence.
                if build_country_activity((record,), now=now).get(country):
                    continue
                entry = self.country_only_evidence.setdefault(
                    country, {"count": 0, "events": [], "categories": {}}
                )
                entry["count"] += 1
                category = str(record.get("category") or "News").strip().title()
                entry["categories"][category] = entry["categories"].get(category, 0) + 1
                # Keep all *already bounded* evidence identities (max 5,000).
                # Display remains capped to 30 rows, but queries must search
                # beyond the first 30 or important stories are unreachable.
                entry["events"].append(record)

            # Economic observations are dated measurements, not crisis events.
            # Map them by provider ISO3 code when possible, then by exact
            # country-name identity. They use a separate outline and tooltip.
            self.economic_observations = {}
            if key is None or "Economy" in key:
                code_to_country = {
                    str(c.get("code") or "").upper(): normalize_country(c["name"])
                    for c in self._countries if c.get("code")
                }
                valid_countries = {normalize_country(c["name"]) for c in self._countries}
                for observation in self.observations:
                    code = str(observation.get("country_code") or "").upper()
                    country = code_to_country.get(code) or normalize_country(
                        observation.get("country_name") or observation.get("country")
                    )
                    if not country or country not in valid_countries:
                        continue
                    date = str(observation.get("observation_date") or observation.get("date") or "")
                    if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", date):
                        continue
                    entry = self.economic_observations.setdefault(
                        country, {"count": 0, "latest": "", "indicators": set()}
                    )
                    entry["count"] += 1
                    entry["latest"] = max(entry["latest"], date)
                    indicator = str(observation.get("indicator_name") or observation.get("indicator") or "").strip()
                    if indicator and len(entry["indicators"]) < 8:
                        entry["indicators"].add(indicator)
            self._activity_categories = key

    def coverage_summary(self):
        self._refresh_country_activity()
        selected = [e for e in self.evidence_events if self.categories is None or e.get("category") in self.categories]
        countries = {normalize_country(c["name"]) for c in self._countries}
        unlocated = sum(not self.has_location(e) and not e.get("map_areas") and
                        normalize_country(incident_country(e)) not in countries for e in selected)
        points = sum(self.has_location(e) for e in selected)
        areas = len(self.area_layer.visible())
        activity = sum(country in countries for country in self.country_activity)
        country_only = sum(entry["count"] for entry in self.country_only_evidence.values())
        economic_countries = len(self.economic_observations)
        economic_rows = sum(entry["count"] for entry in self.economic_observations.values())
        suffix = f" · {self.area_layer.omitted} area(s) omitted by geometry/budget checks" if self.area_layer.omitted else ""
        incomplete = sum(area.get("context_only") is True for _path, _event, area in self.area_layer.visible())
        if incomplete:suffix += f" · {incomplete} area(s) have incomplete warning history"
        return (f"{points} points · {areas} warning areas · {activity} countries with activity"
                f" · {country_only} country-only records · {economic_countries} economy countries/{economic_rows} observations"
                f" · {unlocated} unlocated" + suffix)

    def empty_coverage_message(self):
        if self.country_category_evidence or self.economic_observations:
            return "Country-only records or dated economic observations are available; no point or crisis is inferred."
        if self.evidence_events:
            return "Reports collected; no usable geometry or supported current country activity in this view."
        return "No reports match this map view. This does not mean there are no crises."

    def country_evidence_for(self, name):
        """Neutral/historical country-only archive, excluding current stripes."""
        self._refresh_country_activity()
        return self.country_only_evidence.get(normalize_country(name), {})

    def country_category_evidence_for(self, name):
        """All explicitly country-attributed category reports, not location pins."""
        self._refresh_country_activity()
        return self.country_category_evidence.get(normalize_country(name), {})

    @staticmethod
    def _latest_source_publication(event):
        """Show source dates, never ingestion/aggregate updated_at as publication."""
        dates = []
        for report in event.get("reports", []):
            if not isinstance(report, dict) or report.get("future_dated") or report.get("publication_time_known") is False:
                continue
            value = report.get("published_at")
            if not isinstance(value, str):
                continue
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if stamp.tzinfo and stamp.astimezone(timezone.utc) <= datetime.now(timezone.utc):
                    dates.append(stamp.astimezone(timezone.utc))
            except (ValueError, OverflowError):
                continue
        return max(dates).strftime("%Y-%m-%d %H:%M UTC") if dates else "source publication undated"

    def show_country_evidence(self, name, *, include_current=False, initial_category=None):
        """Searchable attributed archive; never infer an incident's location.

        Exactly 30 results are rendered at once, but searches cover the entire
        bounded (max 5,000 identities) country-evidence index. Records lacking
        country evidence must be found via the clearly separate global search.
        """
        entry = (self.country_category_evidence_for(name) if include_current
                 else self.country_evidence_for(name))
        if not entry:
            return False
        if self.country_dialog:
            self.country_dialog.close()
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        title = "Country-attributed source records" if include_current else "Country-only source records"
        dialog.setWindowTitle(f"{title} — {name}")
        dialog.resize(690, 550)
        layout = QVBoxLayout(dialog)
        explainer = QLabel(
            ("Country-level category circles are SOURCE summaries, never incident points. "
             "Some records may separately have valid incident geometry or qualify "
             "for a current activity stripe. Dates and evidence must be inspected. "
             if include_current else
             "Country-attributed source reports, not verified current crises. ")
            + "Publisher headquarters alone do not establish an event location. "
            + "Incident coordinates and warning boundaries are never inferred."
        )
        explainer.setWordWrap(True)
        layout.addWidget(explainer)

        search = QLineEdit(dialog)
        search.setObjectName("country_evidence_search")
        search.setAccessibleName("Search all attributed records for selected country")
        search.setPlaceholderText("Search all country records (e.g., FAA, ground stop, storm)")
        search.setClearButtonEnabled(True)
        layout.addWidget(search)

        categories = QComboBox(dialog)
        categories.setObjectName("country_evidence_categories")
        categories.addItem("All source categories", "")
        kinds = sorted({str(event.get("category") or "Uncategorized").strip().title()
                        for event in entry["events"]})
        for value in kinds:
            categories.addItem(value, value)
        # Country category rings represent a selected category. Open its
        # evidence rather than silently defaulting to unrelated weather/news.
        # Direct country selections without a category retain "All".
        if initial_category:
            index = categories.findData(str(initial_category).strip().title())
            if index >= 0:
                categories.setCurrentIndex(index)
        layout.addWidget(categories)

        listing = QListWidget(dialog)
        listing.setObjectName("country_evidence_results")
        listing.setAccessibleName("Filtered country-only evidence records")
        listing.setUniformItemSizes(True)
        layout.addWidget(listing, 1)
        count_label = QLabel(dialog)
        count_label.setObjectName("country_evidence_count")
        count_label.setWordWrap(True)
        layout.addWidget(count_label)

        # Index only attributed metadata, never private article bodies, generic
        # summaries, publisher country defaults or external content. No network.
        searchable = []
        for record in entry["events"]:
            parts = [str(record.get("title") or ""), str(record.get("category") or "")]
            reports = record.get("reports")
            if isinstance(reports, list):
                for report in reports[:20]:
                    if isinstance(report, dict):
                        parts.extend((str(report.get("title") or ""),
                                      str(report.get("source_id") or "")))
            searchable.append((record, " ".join(parts).casefold()))

        def fill(*_):
            terms = search.text().casefold().split()
            category = categories.currentData() or ""
            matches = [(record, value) for record, value in searchable
                       if (not category or str(record.get("category") or "Uncategorized").strip().title() == category)
                       and all(term in value for term in terms)]
            listing.clear()
            for event, _ in matches[:30]:
                title = str(event.get("title") or "Untitled event")
                date = self._latest_source_publication(event)
                status = str(event.get("status") or "unknown")
                category_name = str(event.get("category") or "Uncategorized")
                row = QListWidgetItem(
                    f"[{category_name}] {title}\nSource: {date} · status: {status}"
                )
                row.setData(Qt.ItemDataRole.UserRole, str(event.get("id") or ""))
                row.setToolTip("Inspect original publisher links, revisions and source evidence")
                listing.addItem(row)
            if listing.count():
                listing.setCurrentRow(0)
                count_label.setText(
                    f"Showing {min(30, len(matches))} of {len(matches)} matching "
                    f"country-attributed records ({entry['count']} total). "
                    "Search covers the full country list, not only its first 30."
                )
            else:
                count_label.setText(
                    "No matching country-attributed records. An aviation story "
                    "may lack independent US incident geography; use Search full news "
                    "archive to search all locally collected headlines."
                )

        search.textChanged.connect(fill)
        categories.currentIndexChanged.connect(fill)
        controls = QHBoxLayout()
        open_button = QPushButton("Inspect selected evidence")
        global_button = QPushButton("Search full news archive")
        global_button.setObjectName("country_search_full_archive")
        global_button.setToolTip(
            "Search all local reports, including unlocated news, without assigning them to this country"
        )
        close_button = QPushButton("Close")

        def choose(*_):
            row = listing.currentItem()
            if row and row.data(Qt.ItemDataRole.UserRole):
                identity = row.data(Qt.ItemDataRole.UserRole)
                self.select_event(identity)
                self.event_selected.emit(identity)
                dialog.close()

        def search_global():
            phrase = search.text().strip()
            if not phrase:
                count_label.setText(
                    "Type a keyword such as FAA or ground stop first. "
                    "Global archive search does not assume an incident location."
                )
                search.setFocus()
                return
            self.global_search_requested.emit(phrase)
            dialog.close()

        open_button.clicked.connect(choose)
        listing.itemActivated.connect(choose)
        global_button.clicked.connect(search_global)
        close_button.clicked.connect(dialog.close)
        controls.addWidget(open_button)
        controls.addWidget(global_button)
        controls.addWidget(close_button)
        layout.addLayout(controls)
        self.country_dialog = dialog
        dialog.destroyed.connect(
            lambda: setattr(self, "country_dialog", None) if self.country_dialog is dialog else None
        )
        fill()
        dialog.show()
        search.setFocus()
        return True

    def set_crisis_layer(self, kind, enabled):
        if kind not in self.crisis_layers:
            raise ValueError("Unknown crisis overlay")
        self.crisis_layers[kind] = bool(enabled)
        self.update()
        self.view_changed.emit()

    def set_crisis_overlay_enabled(self, enabled):
        self.crisis_overlay_enabled = bool(enabled)
        self.update()
        self.view_changed.emit()

    def country_activity_for(self, name):
        self._refresh_country_activity()
        return self.country_activity.get(normalize_country(name), {})

    def select_event(self, event_id, center=False):
        self.selected_event = str(event_id)
        if center:
            event = next((e for e in self.events if str(e.get("id")) == self.selected_event), None)
            if event and self.has_location(event):
                p = self.normalized(event["longitude"], event["latitude"])
                self.pan_x, self.pan_y = p.x() - .5, p.y() - .5
                self.zoom = max(2.0, self.zoom)
        self.update()

    @staticmethod
    def has_location(event):
        return (_number(event.get("latitude")) and _number(event.get("longitude")) and
                -90 <= event["latitude"] <= 90 and -180 <= event["longitude"] <= 180)

    def select_country(self, name):
        country = next((c for c in self._countries if name.casefold() in (c["name"].casefold(), c["code"].casefold())), None)
        if not country:
            return False
        self.selected_country = country["name"]
        bounds = country["path"].boundingRect()
        if bounds.width() < .6:
            self.zoom = min(8.0, max(1.5, min(.65 / max(.02, bounds.width()), .7 / max(.02, bounds.height()))))
            self.pan_x, self.pan_y = bounds.center().x() - .5, bounds.center().y() - .5
        else:
            self.zoom = 1.4
            label = country.get("label")
            if label and all(_number(v) for v in label):
                p = self.normalized(*label)
                self.pan_x, self.pan_y = p.x() - .5, p.y() - .5
        self.country_selected.emit(country["name"])
        self.update()
        self.view_changed.emit()
        return True

    def zoom_by(self, factor, position=None):
        old = self.zoom
        self.zoom = min(20.0, max(1.0, old * factor))
        if position is not None and old != self.zoom:
            nx, ny = position.x() / max(1, self.width()) - .5, position.y() / max(1, self.height()) - .5
            self.pan_x += nx * (1 / old - 1 / self.zoom)
            self.pan_y += ny * (1 / old - 1 / self.zoom)
        if self.zoom == 1.0:
            self.pan_x = self.pan_y = 0.0
        self._clamp()
        self.update()
        self.view_changed.emit()

    def _clamp(self):
        limit = .5 - .5 / self.zoom
        self.pan_x = min(limit, max(-limit, self.pan_x))
        self.pan_y = min(limit, max(-limit, self.pan_y))

    def visible_clusters(self):
        groups = defaultdict(list)
        for event in self.events:
            if not self.has_location(event) or (self.categories is not None and event.get("category") not in self.categories):
                continue
            p = self.point(event["longitude"], event["latitude"])
            if -20 < p.x() < self.width() + 20 and -20 < p.y() < self.height() + 20:
                groups[(round(p.x() / 27), round(p.y() / 27))].append((event, p))
        return list(groups.values())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#292a2d"))
        transform = self._transform()
        painter.setPen(QPen(QColor("#303135"), 1))
        for lon in range(-180, 181, 30):
            a, b = self.point(lon, 85), self.point(lon, -60)
            painter.drawLine(a, b)
        for lat in range(-60, 86, 30):
            painter.drawLine(self.point(-180, lat), self.point(180, lat))
        for c in self._countries:
            if c["name"] == "Antarctica":
                continue
            selected = c["name"] == self.selected_country
            hovered = c["name"] == self._hover_country
            mapped_path = transform.map(c["path"])
            painter.setBrush(QColor("#3a2d50" if selected else "#243149" if hovered else "#161719"))
            painter.setPen(QPen(QColor("#9072b5" if selected else "#45464b"), 1 if selected else .65))
            painter.drawPath(mapped_path)
            # Neutral dashed boundary means archived country-only evidence,
            # never a crisis stripe or a fabricated geographic point.
            country_key = normalize_country(c["name"])
            if country_key in self.country_only_evidence:
                painter.setPen(QPen(QColor("#668192"), 1, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(mapped_path)
            if country_key in self.economic_observations:
                painter.setPen(QPen(QColor("#58a6b8"), 1.4, Qt.PenStyle.DashDotLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(mapped_path)
            if self.crisis_overlay_enabled:
                activity = self.country_activity_for(c["name"])
                stripe_specs = (("conflict", "#d84a52", Qt.BrushStyle.BDiagPattern), ("unrest", "#e3bd4d", Qt.BrushStyle.FDiagPattern), ("migration", "#9a6748", Qt.BrushStyle.HorPattern))
                painter.setPen(Qt.PenStyle.NoPen)
                for kind, color, style in stripe_specs:
                    if self.crisis_layers.get(kind, True) and int(activity.get(kind, 0) or 0) > 0:
                        shade = QColor(color); shade.setAlpha(185)
                        painter.setBrush(QBrush(shade, style)); painter.drawPath(mapped_path)
        if self.gdelt_layer is not None:
            self.gdelt_layer.paint(painter, transform, self._countries)
        if self.labels:
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QColor("#6d7b90"))
            occupied = []
            for c in self._countries:
                label = c.get("label")
                if not label or not all(_number(v) for v in label) or c["name"] == "Antarctica":
                    continue
                bounds = transform.mapRect(c["path"].boundingRect())
                if bounds.width() * bounds.height() < 2300 and self.zoom < 3:
                    continue
                p = self.point(*label)
                name = c["name"].upper()
                text_width = painter.fontMetrics().horizontalAdvance(name)
                rect = QRectF(p.x() - text_width/2, p.y() - 5, text_width, 11)
                if not self.rect().contains(rect.toRect()) or any(rect.intersects(r) for r in occupied):
                    continue
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name)
                occupied.append(rect.adjusted(-5, -3, 5, 3))
        self.area_layer.paint(painter)

        # Country-level category dots make country-attributed politics, economy,
        # health, humanitarian, infrastructure and conflict evidence visible
        # by country regardless of separately justified incident points/areas.
        # They are *not* severity or event pins; their distinct hollow rings
        # and clickable country tooltip express that limitation. No fake
        # centroids or inferred coordinates are added to the event data.
        self._country_badge_hits.clear()
        for c in self._countries:
            key = normalize_country(c["name"])
            evidence = self.country_category_evidence.get(key, {})
            category_counts = dict(evidence.get("categories") or {})
            economy = self.economic_observations.get(key, {})
            if economy and not category_counts.get("Economy"):
                category_counts["Economy"] = 0  # dated observations only
            if not category_counts or c["name"] == "Antarctica":
                continue
            label = c.get("label")
            if not label or not all(_number(v) for v in label):
                continue
            point = self.point(*label)
            if not (-15 < point.x() < self.width()+15 and -15 < point.y() < self.height()+15):
                continue
            # Prioritize diverse non-weather evidence on small country labels.
            kinds = sorted(category_counts,
                           key=lambda cat: (_CATEGORY_PRIORITY.index(cat)
                               if cat in _CATEGORY_PRIORITY else len(_CATEGORY_PRIORITY),
                               cat))[:8]
            count = len(kinds)
            # A marker below the geographic label denotes the country, not a
            # purported incident at the label coordinate.
            start_x = point.x() - (count-1)*6.5
            for index, category in enumerate(kinds):
                center = QPointF(start_x + index*13, point.y()+11)
                if not self.rect().adjusted(5, 5, -5, -5).contains(center.toPoint()):
                    continue
                color = QColor(CATEGORY_COLORS.get(category, "#aebdcf"))
                painter.setPen(QPen(color, 1.7))
                painter.setBrush(QColor("#111721"))
                painter.drawEllipse(center, 5.6, 5.6)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(center, 2.8, 2.8)
                value = int(category_counts.get(category, 0))
                descriptor = (
                    f"{value} country-attributed source record(s)"
                    if value else f"{int(economy.get('count',0))} dated economic observation(s)"
                )
                self._country_badge_hits.append((
                    center, 7.5, c["name"], category, descriptor
                ))

        self._hits.clear()
        for group in self.visible_clusters():
            center = QPointF(sum(p.x() for _, p in group)/len(group), sum(p.y() for _, p in group)/len(group))
            severity_order = {"critical": 4, "high": 3, "moderate": 2, "informational": 1, "unassessed": 0}
            representative = max(group, key=lambda item: severity_order.get(item[0].get("severity"), 0))[0]
            color = QColor(SEVERITY.get(representative.get("severity"), SEVERITY["unassessed"]))
            selected = any(str(e.get("id")) == self.selected_event for e, _ in group)
            if self.density:
                radius = min(55, 21 + len(group)*5)
                gradient = QRadialGradient(center, radius)
                glow = QColor(color); glow.setAlpha(min(100, 30 + len(group)*12))
                gradient.setColorAt(0, glow); gradient.setColorAt(1, QColor(0,0,0,0))
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(gradient)
                painter.drawEllipse(center, radius, radius)
            radius = 6 if len(group) == 1 else min(14, 8 + math.log2(len(group))*2)
            verification = representative.get("verification", "unverified")
            pen = QPen(color, 1.2)
            if verification == "unverified":
                pen.setStyle(Qt.PenStyle.DotLine)
            elif verification == "developing":
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius+3, radius+3)
            if verification == "official":
                # Distinguish official sourcing by another circular ring. A
                # square frame looked like an event box rather than a pin.
                painter.setPen(QPen(QColor("#ede4fd"), 1.5))
                painter.drawEllipse(center, radius+5, radius+5)
            if selected:
                painter.setPen(QPen(QColor("#f1e5ff"), 1.7))
                painter.drawEllipse(center, radius+7, radius+7)
            painter.setPen(QPen(QColor("#0b111b"), 1)); painter.setBrush(color)
            painter.drawEllipse(center, radius, radius)
            if representative.get("geo_precision") in ("approximate", "regional", "country", "region"):
                painter.setPen(QPen(QColor("#131927"), 1.5))
                painter.drawLine(QPointF(center.x()-3, center.y()), QPointF(center.x()+3, center.y()))
            if len(group) > 1:
                painter.setPen(QColor("#0c111b")); painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                painter.drawText(QRectF(center.x()-radius,center.y()-radius,radius*2,radius*2),Qt.AlignmentFlag.AlignCenter,str(len(group)))
            self._hits.append((center, radius+8, group))
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#718099"))
        painter.drawText(QRectF(12, self.height()-22, self.width()-24, 17), Qt.AlignmentFlag.AlignLeft,
                         "OFFLINE BASE MAP  ·  Natural Earth  ·  Boundaries are illustrative")
        mapped = sum(self.has_location(e) for e in self.events)
        painter.drawText(QRectF(12, self.height()-22, self.width()-24, 17), Qt.AlignmentFlag.AlignRight,
                         f"{mapped} points / {len(self.evidence_events)} reports assessed · {len(self.area_layer.visible())} warning areas · {self.zoom:.1f}×")
        if self._map_error:
            painter.setPen(QColor("#ffb1ba"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._map_error)
        elif (not self.events and not self.area_layer.visible()
              and not self.country_activity and not self.country_category_evidence
              and not (self.gdelt_layer and self.gdelt_layer.mapped_count)):
            painter.setPen(QColor("#aab4c5"))
            painter.drawText(QRectF(0,self.height()-66,self.width(),28),Qt.AlignmentFlag.AlignCenter,
                             self.empty_coverage_message())
        painter.end()

    def wheelEvent(self, event):
        self.zoom_by(1.2 if event.angleDelta().y() > 0 else 1/1.2, event.position())
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = (event.position(), self.pan_x, self.pan_y)
            self._moved = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._drag:
            start, px, py = self._drag
            delta = pos - start
            if abs(delta.x()) + abs(delta.y()) > 5:
                self._moved = True
            self.pan_x = px - delta.x() / (max(1,self.width()) * self.zoom)
            self.pan_y = py - delta.y() / (max(1,self.height()) * self.zoom)
            self._clamp(); self.update()
            return
        for center, radius, group in self._hits:
            if (center-pos).manhattanLength() <= radius*1.4:
                QToolTip.showText(event.globalPosition().toPoint(), self.cluster_tooltip(group), self)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                return
        for center, radius, country, category, descriptor in self._country_badge_hits:
            if (center-pos).manhattanLength() <= radius*1.3:
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    "<qt><b>" + html.escape(country) + " · " +
                    html.escape(category) + "</b><br>" + html.escape(descriptor) +
                    "<br>Country-level source/measurement only — NOT an exact incident point. "
                    "Click to inspect attributed records.</qt>", self
                )
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                return
        area_hit = self.area_layer.hit(pos)
        if area_hit:
            record, area = area_hit
            text = "<qt><b>" + html.escape(str(record.get("title", "Warning"))) + "</b><br>" + html.escape(str(area.get("description", ""))) + "<br>Provider warning area; click for evidence.</qt>"
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        inverse, valid = self._transform().inverted()
        name = ""
        if valid:
            p = inverse.map(pos)
            for c in self._countries:
                if c["path"].contains(p):
                    name = c["name"]; break
        if name != self._hover_country:
            self._hover_country = name
            self.update()
        if name:
            activity = self.country_activity_for(name)
            labels = []
            for kind, title in (("conflict", "Conflict/war reporting"), ("unrest", "Protest/unrest"), ("migration", "Migration/displacement")):
                count = int(activity.get(kind, 0) or 0)
                if self.crisis_overlay_enabled and self.crisis_layers.get(kind, True) and count:
                    labels.append(f"{title}: {count} recent sourced event(s)")
            evidence = self.country_category_evidence_for(name)
            if evidence:
                labels.append(
                    f"{evidence['count']} country-attributed source record(s). "
                    "Category circles summarize reports, not coordinates or "
                    "independent declarations of a current crisis.")
            economy = self.economic_observations.get(normalize_country(name))
            if economy:
                indicators = ", ".join(sorted(economy["indicators"])[:3])
                labels.append(
                    f"Economy: {economy['count']} dated observation(s); latest {economy['latest']}. "
                    + (f"{indicators}. " if indicators else "")
                    + "Dated measurements only; no economic crisis inferred.")
            if self.gdelt_layer is not None:
                coded_note = self.gdelt_layer.country_text(name)
                if coded_note: labels.append(coded_note)
            suffix = ("<br>" + "<br>".join(html.escape(item) for item in labels)) if labels else ""
            QToolTip.showText(event.globalPosition().toPoint(),"<qt><b>"+html.escape(name)+"</b>"+suffix+"</qt>",self)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._moved:
            self.view_changed.emit(); return
        pos = event.position()
        for center, radius, group in self._hits:
            if (center-pos).manhattanLength() <= radius*1.4:
                if len(group) > 1:
                    self.show_cluster(group, center)
                else:
                    self.select_event(group[0][0].get("id", ""))
                    self.event_selected.emit(str(group[0][0].get("id", "")))
                return
        for center, radius, country, category, _descriptor in self._country_badge_hits:
            if (center-pos).manhattanLength() <= radius*1.3:
                self.selected_country = country
                self.country_selected.emit(country)
                self.update()
                evidence = self.country_category_evidence_for(country)
                # A circle based *only* on dated economic observations is
                # actionable: navigate to the actual Economy data, not an
                # empty country news dialog. Source-reported Economy events
                # still open their original country evidence instead.
                if (category == "Economy" and
                        self.economic_observations.get(normalize_country(country)) and
                        not evidence.get("categories", {}).get("Economy")):
                    self.economic_country_requested.emit(country)
                elif evidence:
                    self.show_country_evidence(country, include_current=True, initial_category=category)
                return
        area_hit = self.area_layer.hit(pos)
        if area_hit:
            record, _area = area_hit
            self.select_event(record.get("id", ""))
            self.event_selected.emit(str(record.get("id", "")))
            return
        if self._hover_country:
            self.selected_country = self._hover_country
            self.country_selected.emit(self._hover_country)
            self.update()
            if self.country_evidence_for(self._hover_country):
                self.show_country_evidence(self._hover_country)

    @staticmethod
    def sorted_cluster(group):
        order={"critical":4,"high":3,"moderate":2,"informational":1,"unassessed":0}
        return sorted((e for e,_ in group), key=lambda e:(-order.get(e.get("severity"),0),str(e.get("title","")),str(e.get("id",""))))

    @classmethod
    def cluster_tooltip(cls, group):
        events=cls.sorted_cluster(group)
        lines=[f"<b>{len(events)} event(s) — click to choose</b>"]
        for e in events[:8]:
            severity=e.get("severity","unassessed")
            color=SEVERITY.get(severity,SEVERITY["unassessed"])
            lines.append(f"<span style='color:{color}'>{html.escape(str(severity).upper())}</span> · {html.escape(str(e.get('title','Event')))}")
            lines.append(html.escape(str(e.get("verification","unverified")))+" · "+html.escape(str(e.get("updated_at",""))))
            if e.get("map_retention_note"):
                lines.append(html.escape(e["map_retention_note"]))
        if len(events)>8:lines.append(f"{len(events)-8} more — click for the complete list")
        return "<qt>"+"<br>".join(lines)+"</qt>"

    def show_cluster(self, group, center):
        if self.cluster_dialog:
            self.cluster_dialog.close()
        dialog=QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle(f"Events at this location ({len(group)})")
        dialog.resize(580, min(540,180+len(group)*65))
        layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel("Separate events share this marker. Select any event to inspect its evidence."))
        listing=QListWidget(dialog)
        listing.setAccessibleName("All events at this map marker")
        for e in self.sorted_cluster(group):
            severity=e.get("severity","unassessed")
            row=QListWidgetItem(f"{str(severity).upper()} · {e.get('title','Event')}\n{e.get('region','')} · {e.get('verification','unverified')} · {e.get('updated_at','')}")
            row.setForeground(QColor(SEVERITY.get(severity,SEVERITY['unassessed'])))
            row.setData(Qt.ItemDataRole.UserRole,str(e.get('id','')))
            row.setToolTip(str(e.get('recap',''))+"\n"+str(e.get('map_retention_note','')))
            listing.addItem(row)
        listing.setCurrentRow(0);layout.addWidget(listing)
        controls=QHBoxLayout();open_button=QPushButton("Open selected event");zoom_button=QPushButton("Zoom into area");close_button=QPushButton("Close")
        def choose(*_):
            row=listing.currentItem()
            if row:
                identity=row.data(Qt.ItemDataRole.UserRole)
                self.select_event(identity);self.event_selected.emit(identity)
                dialog.close()
        open_button.clicked.connect(choose);listing.itemActivated.connect(choose)
        zoom_button.clicked.connect(lambda:(self.zoom_by(1.8,center),dialog.close()))
        close_button.clicked.connect(dialog.close)
        for control in (open_button,zoom_button,close_button):controls.addWidget(control)
        layout.addLayout(controls)
        self.cluster_dialog=dialog
        dialog.destroyed.connect(lambda:setattr(self,"cluster_dialog",None) if self.cluster_dialog is dialog else None)
        dialog.show();listing.setFocus()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal): self.zoom_by(1.25)
        elif key == Qt.Key.Key_Minus: self.zoom_by(.8)
        elif key == Qt.Key.Key_Home: self.reset_view()
        elif key in (Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Up,Qt.Key.Key_Down):
            step=.08/self.zoom
            self.pan_x += -step if key==Qt.Key.Key_Left else step if key==Qt.Key.Key_Right else 0
            self.pan_y += -step if key==Qt.Key.Key_Up else step if key==Qt.Key.Key_Down else 0
            self._clamp(); self.update(); self.view_changed.emit()
        else: super().keyPressEvent(event)
