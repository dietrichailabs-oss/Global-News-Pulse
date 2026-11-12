"""One-time, exact-blob guarded map correction; never run by the application."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'global_pulse/core.py': 'c0cf72931f4deea7999828ef464a926d7db1c3ec',
    'global_pulse/sources.py': 'ca82811f5da5eb5305f5ce46b27ad64d485c05b9',
    'global_pulse/map_widget.py': '582a2e18488331248509ab6fda3735e3334818b0',
    'global_pulse/ui.py': 'daf04f9636e8458fc6eedacce31e646d46f28484',
    'global_pulse/crisis_overlay.py': 'efc5b7830c37b42c4aa2ab0663e09cbf9dc30cdb',
}


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Patch anchor is not unique: ' + old[:90])
    return text.replace(old, new, 1)


def main():
    texts = {}
    for name, expected in EXPECTED.items():
        data = (ROOT / name).read_bytes()
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if digest != expected:
            raise ValueError('Source changed; reconcile before patching: ' + name)
        texts[name] = data.decode('utf-8')

    name = 'global_pulse/core.py'
    text = texts[name]
    text = replace(text, 'from uuid import UUID, uuid4, uuid5\n', 'from uuid import UUID, uuid4, uuid5\n\nfrom .map_evidence import normalize_map_fields, event_areas\n')
    text = replace(text, '    normalize_lifecycle(raw, result, stamp)\n', '    result.update(normalize_map_fields(raw))\n    normalize_lifecycle(raw, result, stamp)\n')
    text = replace(text, '    seen_media = set()\n', '    event["map_areas"] = event_areas(active)\n    seen_media = set()\n')
    text = replace(text, '                    map_view: bool = False, keep_significant: bool = False) -> list[dict]:', '                    map_view: bool = False, keep_significant: bool = False,\n                    map_evidence: bool = False) -> list[dict]:')
    text = replace(text, '        # Map membership is independent of the bounded text-feed page.', '        map_view = bool(map_view or map_evidence)\n        # map_evidence retains country/area/unlocated records without inventing points.\n        # Map membership is independent of the bounded text-feed page.')
    text = replace(text, '''                    filtered = [e for e in filtered if e.get("latitude") is not None
                                and e.get("longitude") is not None and e.get("status") == "active"]''', '''                    filtered = [e for e in filtered if e.get("status") == "active" and
                                (map_evidence or (e.get("latitude") is not None and e.get("longitude") is not None))]''')
    text = replace(text, '''                where.extend(["json_extract(body,'$.latitude') IS NOT NULL",
                              "json_extract(body,'$.longitude') IS NOT NULL",
                              "json_extract(body,'$.status')='active'"])''', '''                where.append("json_extract(body,'$.status')='active'")
                if not map_evidence:
                    where.extend(["json_extract(body,'$.latitude') IS NOT NULL",
                                  "json_extract(body,'$.longitude') IS NOT NULL"])''')
    texts[name] = text

    name = 'global_pulse/sources.py'
    text = texts[name]
    text = replace(text, 'from .lifecycle import provider_id, scope_identifier\n', 'from .lifecycle import provider_id, scope_identifier\nfrom .map_evidence import nws_map_fields\n')
    text = replace(text, '            "country": source.get("country", ""), "category": source.get("category", "News"),', '            "country": source.get("country", ""), "category": source.get("category", "News"),\n            "source_country": source.get("country", ""), "country_basis": "publisher_coverage",')
    text = replace(text, '            report["country"] = plain(_child(node, "country"), 100)\n', '            report["country"] = plain(_child(node, "country"), 100)\n            report["country_basis"] = "provider_incident"\n')
    text = replace(text, '        r["geo_precision"] = "area_unspecified"\n', '        r["geo_precision"] = "area_unspecified"\n        r.update(nws_map_fields(f, p))\n')
    texts[name] = text

    name = 'global_pulse/crisis_overlay.py'
    text = texts[name]
    text = replace(text, 'from typing import Iterable\n', 'from typing import Iterable\n\nfrom .map_evidence import incident_country\n')
    text = replace(text, '        country = normalize_country(event.get("country") or event.get("region"))', '        country = normalize_country(incident_country(event))')
    texts[name] = text

    name = 'global_pulse/map_widget.py'
    text = texts[name]
    text = replace(text, 'from .crisis_overlay import build_country_activity, normalize_country\n', 'from .crisis_overlay import build_country_activity, normalize_country\nfrom .map_evidence import incident_country\nfrom .map_area_layer import WarningAreaLayer\n')
    text = replace(text, '        self.events = []\n', '        self.events = []\n        self.evidence_events = []\n        self._activity_categories = object()\n        self.area_layer = WarningAreaLayer(self)\n')
    text = replace(text, '''    def set_events(self, events):
        self.events = list(events)[:5000]
        self.country_activity = build_country_activity(self.events)
        self.update()
''', '''    def set_events(self, events, *, country_events=None):
        self.events = list(events)[:5000]
        self.evidence_events = list(country_events)[:5000] if country_events is not None else list(self.events)
        self.area_layer.set_events(self.evidence_events)
        self._activity_categories = object()
        self._refresh_country_activity()
        self.update()

    def _refresh_country_activity(self):
        key = None if self.categories is None else frozenset(self.categories)
        if key != self._activity_categories:
            selected = [e for e in self.evidence_events if key is None or e.get("category") in key]
            self.country_activity = build_country_activity(selected)
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
        suffix = f" · {self.area_layer.omitted} area(s) omitted by geometry/budget checks" if self.area_layer.omitted else ""
        return f"{points} points · {areas} warning areas · {activity} countries with activity · {unlocated} unlocated" + suffix

    def empty_coverage_message(self):
        if self.evidence_events:
            return "Reports collected; no usable geometry or supported current country activity in this view."
        return "No reports match this map view. This does not mean there are no crises."
''')
    text = replace(text, '    def country_activity_for(self, name):\n        return', '    def country_activity_for(self, name):\n        self._refresh_country_activity()\n        return')
    text = replace(text, '        self._hits.clear()\n', '        self.area_layer.paint(painter)\n        self._hits.clear()\n')
    text = replace(text, '                         f"{mapped} located / {len(self.events)} events   ·   {self.zoom:.1f}×")', '                         f"{mapped} points / {len(self.evidence_events)} reports assessed · {len(self.area_layer.visible())} warning areas · {self.zoom:.1f}×")')
    text = replace(text, '        elif not self.events:\n', '        elif not self.events and not self.area_layer.visible() and not self.country_activity:\n')
    text = replace(text, '                             "No events in this view. Your offline map remains available.")', '                             self.empty_coverage_message())')
    text = replace(text, '        self.setCursor(Qt.CursorShape.OpenHandCursor)\n        inverse, valid', '''        area_hit = self.area_layer.hit(pos)
        if area_hit:
            record, area = area_hit
            text = "<qt><b>" + html.escape(str(record.get("title", "Warning"))) + "</b><br>" + html.escape(str(area.get("description", ""))) + "<br>Provider warning area; click for evidence.</qt>"
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        inverse, valid''')
    text = replace(text, '        if self._hover_country:\n            self.selected_country', '''        area_hit = self.area_layer.hit(pos)
        if area_hit:
            record, _area = area_hit
            self.select_event(record.get("id", ""))
            self.event_selected.emit(str(record.get("id", "")))
            return
        if self._hover_country:
            self.selected_country''')
    texts[name] = text

    name = 'global_pulse/ui.py'
    text = texts[name]
    text = replace(text, '            self.world_map.set_events(self.controller.events(**map_filters))', '            country_evidence=self.controller.events(**dict(map_filters,map_evidence=True))\n            self.world_map.set_events(self.controller.events(**map_filters),country_events=country_evidence)')
    text = replace(text, '            self.count_label.setText(f"{count} feed events · {len(self.world_map.events)} mapped"+suffix+cap)', '            self.count_label.setText(f"{count} feed events · "+self.world_map.coverage_summary()+suffix+cap)')
    texts[name] = text

    # Validate every replacement before modifying any source file.
    for name, text in texts.items():
        compile(text, name, 'exec')
    for name, text in texts.items():
        (ROOT / name).write_text(text, encoding='utf-8', newline='\n')
        print('GP_MAP_PATCH ' + name)


if __name__ == '__main__':
    main()
