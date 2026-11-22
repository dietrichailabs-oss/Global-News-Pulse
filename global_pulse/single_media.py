"""On-demand broadcast/HAM radio and a separate reviewed-camera view."""
from __future__ import annotations

from html import escape
import unicodedata

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QTabWidget, QMessageBox, QCheckBox,
    QComboBox, QHBoxLayout, QLineEdit,
)

from .media_widget import _MediaTile
from .internet_radio import RadioPanel
from .security import safe_url


def _search_words(value):
    """Accent-insensitive manual search; never used for event association."""
    return unicodedata.normalize("NFKD", str(value).casefold()).encode("ascii", "ignore").decode()


class MediaPanel(QWidget):
    auto_cameras_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shutting_down = False
        self.auto_cameras = False
        self._event = None
        self._camera_matches = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.radio = RadioPanel(self)

        from .camera_context import camera_catalog
        self._camera_catalog = [dict(item) for item in camera_catalog()]
        self.camera_page = QWidget()
        camera_layout = QVBoxLayout(self.camera_page)
        self.auto_camera_check = QCheckBox("Auto cameras (still images)")
        self.auto_camera_check.toggled.connect(self._toggle_cameras)
        self.camera_search = QLineEdit()
        self.camera_search.setPlaceholderText("Search place, country or provider")
        self.camera_search.setAccessibleName("Search reviewed camera bank")
        self.camera_search.setClearButtonEnabled(True)
        self.camera_search.setMaxLength(200)
        self.camera_search.setMinimumWidth(0)
        self.camera_region = QComboBox()
        self.camera_region.setAccessibleName("Filter cameras by continent")
        self.camera_region.addItem("All regions", "")
        for region in sorted({item.get("continent", "") for item in self._camera_catalog} - {""}):
            self.camera_region.addItem(region, region)
        self.camera_region.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.camera_region.setMinimumContentsLength(5)
        self.camera_region.setMinimumWidth(0)
        filters = QHBoxLayout()
        filters.addWidget(self.camera_search, 3)
        filters.addWidget(self.camera_region, 2)
        self.camera_status = QLabel()
        self.camera_status.setWordWrap(True)
        self.camera_status.setTextFormat(Qt.TextFormat.PlainText)
        self.camera_status.setObjectName("Muted")
        self.camera = _MediaTile(self)
        self.camera_attribution = QLabel()
        self.camera_attribution.setWordWrap(True)
        self.camera_attribution.setTextFormat(Qt.TextFormat.RichText)
        self.camera_attribution.setOpenExternalLinks(True)
        self.camera_attribution.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.camera_attribution.setAccessibleName("Selected camera credit, license and review status")
        camera_layout.addWidget(self.auto_camera_check)
        camera_layout.addLayout(filters)
        camera_layout.addWidget(self.camera_status)
        camera_layout.addWidget(self.camera, 1)
        camera_layout.addWidget(self.camera_attribution)
        self.camera.selector.currentIndexChanged.connect(self._update_camera_attribution)
        self.camera_search.textChanged.connect(self._filter_cameras)
        self.camera_region.currentIndexChanged.connect(self._filter_cameras)
        self._refresh_camera_bank()

        self.tabs.addTab(self.radio, "Radio")
        self.tabs.addTab(self.camera_page, "Cameras")
        self._last_page = self.radio
        self.tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self.tabs, 1)
        self.stop_button = QPushButton("Stop all media")
        self.stop_button.clicked.connect(self.stop)
        layout.addWidget(self.stop_button)
        self.tiles = [self.camera]

    def configure_radio_preferences(self, getter, setter):
        # Old saved-video preferences are left untouched, but never restored
        # into a player or used for a connection.
        self.radio.configure_preferences(getter, setter)

    def _tab_changed(self, _index):
        if self._last_page is self.radio:
            self.radio.off()
        elif self._last_page is self.camera_page:
            self.camera.stop()
        self._last_page = self.tabs.currentWidget()
        if self._last_page is self.camera_page:
            self._apply_camera()

    def set_event(self, event):
        from .camera_context import associated_cameras
        if (event or {}).get("id") != (self._event or {}).get("id"):
            self.camera.auto_camera_suspended = False
        self._event = event
        self._camera_matches = associated_cameras(event)
        # Matching cameras sort first. The reviewed manual camera bank stays
        # available even where no reviewed camera matches the selected event.
        self._refresh_camera_bank()
        self._apply_camera()
        # A news refresh never changes radio selection or playback.

    def _filter_cameras(self, *_):
        # Filtering or selecting another camera never grants network consent,
        # even when automatic event cameras were enabled earlier.
        self._refresh_camera_bank(preserve_selection=True)

    def _refresh_camera_bank(self, *, preserve_selection=False):
        region = self.camera_region.currentData() or ""
        words = _search_words(self.camera_search.text()).split()

        def visible(item):
            haystack = _search_words(" ".join(
                str(item.get(key, ""))
                for key in ("title", "provider", "region", "country", "continent")
            ))
            return (not region or item.get("continent") == region) and all(word in haystack for word in words)

        # Keep known-unavailable legacy entries reachable, but do not put one
        # immediately after the first working camera in normal manual browsing.
        catalog = sorted((item for item in self._camera_catalog if visible(item)),
                         key=lambda item: item.get("review_status") == "unavailable_at_review")
        matches = [item for item in self._camera_matches if visible(item)]
        selected_id = self.camera._current().get("id") if preserve_selection else None
        ordered = list({item["id"]: item for item in matches + catalog}.values())
        initial_index = next((i for i, item in enumerate(ordered) if item["id"] == selected_id), 0)
        self.camera.media = matches
        self.camera.catalog = catalog
        self.camera._populate(initial_index=initial_index)
        reviewed = sum(item.get("review_status") == "recent_image_verified" for item in self._camera_catalog)
        unavailable = sum(item.get("review_status") == "unavailable_at_review" for item in self._camera_catalog)
        live_count = sum(item.get("playback") == "live_video" for item in self._camera_catalog)
        snapshot_count = sum(bool(item.get("snapshot_url")) for item in self._camera_catalog)
        relation = (f"{len(matches)} match selected event; area context only"
                    if matches else "none match selected event")
        self.camera_status.setText(
            f"{len(catalog)} / {len(self._camera_catalog)} reviewed entries available manually · {relation}\n"
            f"{live_count} manual live-video choices; {snapshot_count} still-image views. "
            f"{reviewed} responded at the dated review; {unavailable} unavailable. "
            "Still images are not continuous video; 15-minute minimum refresh."
        )
        self._update_camera_attribution()

    def _update_camera_attribution(self, *_):
        from .camera_context import approved_camera
        # Only trusted registry metadata may create source/license links.
        item = approved_camera(self.camera._current())
        if item is None:
            self.camera_attribution.setText("No reviewed camera matches these filters.")
            self.camera_attribution.setToolTip("")
            return

        def link(label, url):
            try:
                return f'<a href="{escape(safe_url(url), quote=True)}">{escape(label)}</a>'
            except (TypeError, ValueError):
                return escape(label)

        credit = link(str(item.get("attribution", item.get("provider", "Source"))), item.get("url", ""))
        license_text = str(item.get("license", "See source terms"))
        license_link = link(license_text, item.get("license_url", item.get("rights_url", "")))
        checked = str(item.get("last_verified", "Not checked")).replace("T", " ").replace("Z", " UTC")
        state = ("Manual live video on the original provider page; Windows playback unverified"
                 if item.get("playback") == "live_video"
                 else "Unavailable at review — try Source" if item.get("review_status") == "unavailable_at_review"
                 else "Image responded at review; availability may change")
        self.camera_attribution.setText(
            f"{credit} · {license_link}<br>{escape(state)} · Checked {escape(checked)}"
        )
        self.camera_attribution.setToolTip(str(item.get("availability", "")) + "\n" + str(item.get("rights", "")))

    def _apply_camera(self):
        event = self._event or {}
        if (self._shutting_down or not self.auto_cameras
                or self.tabs.currentWidget() is not self.camera_page
                or event.get("synthetic") or event.get("historical_view")
                or event.get("severity") not in {"critical", "high", "moderate"}):
            return
        if self.camera._current().get("id") in {item["id"] for item in self._camera_matches}:
            self.camera.connect_camera(auto_consented=True)

    def restore_auto_cameras(self, enabled):
        self.auto_cameras = enabled is True
        self.auto_camera_check.blockSignals(True)
        self.auto_camera_check.setChecked(self.auto_cameras)
        self.auto_camera_check.blockSignals(False)

    def _toggle_cameras(self, enabled):
        if enabled:
            enabled = QMessageBox.question(
                self, "Automatically connect reviewed area snapshots?",
                "While the Cameras tab is selected, connect matching reviewed public still-image cameras "
                "for active events? Providers receive your IP address. Images remain in memory, "
                "not recordings. Coverage is limited.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
        self.restore_auto_cameras(enabled)
        self.auto_cameras_changed.emit(enabled)
        if enabled:
            self.camera.auto_camera_suspended = False
            self._apply_camera()
        else:
            self.camera.stop()

    def radio_off(self):
        self.radio.off()
        return True

    def stop(self):
        if self.auto_cameras:
            self.restore_auto_cameras(False)
            self.auto_cameras_changed.emit(False)
        self.radio.off()
        self.camera.user_stop()
        from .camera_snapshot import CameraSnapshot
        CameraSnapshot._images.clear()

    def shutdown(self):
        self._shutting_down = True
        self.radio.shutdown()
        self.camera.shutdown()
        from .camera_snapshot import CameraSnapshot
        CameraSnapshot._images.clear()

    def hideEvent(self, event):
        self.radio.off()
        self.camera.stop()
        super().hideEvent(event)
