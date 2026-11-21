"""On-demand broadcast/HAM radio and a separate reviewed-camera view."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QTabWidget, QMessageBox, QCheckBox,
)

from .media_widget import _MediaTile
from .internet_radio import RadioPanel


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
        self.auto_camera_check = QCheckBox("Auto cameras")
        self.auto_camera_check.toggled.connect(self._toggle_cameras)
        self.camera_status = QLabel("Select an event for reviewed area cameras")
        self.camera_status.setWordWrap(True)
        self.camera_status.setTextFormat(Qt.TextFormat.PlainText)
        self.camera = _MediaTile(self)
        self.camera.set_catalog(self._camera_catalog)
        camera_layout.addWidget(self.auto_camera_check)
        camera_layout.addWidget(self.camera_status)
        camera_layout.addWidget(self.camera, 1)

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
        total = len(self._camera_catalog)
        if self._camera_matches:
            self.camera_status.setText(
                f"{total} reviewed camera(s) available · "
                f"{len(self._camera_matches)} match selected event · area context only"
            )
        else:
            self.camera_status.setText(
                f"{total} reviewed camera(s) available manually · none match selected event"
            )
        # Matching cameras sort first. The reviewed manual camera bank stays
        # available even where no reviewed camera matches the selected event.
        self.camera.media = self._camera_matches
        self.camera.catalog = self._camera_catalog
        self.camera._populate()
        self._apply_camera()
        # A news refresh never changes radio selection or playback.

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
                self, "Automatically connect reviewed area cameras?",
                "While the Cameras tab is selected, connect matching reviewed public cameras "
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
        self.camera.stop()
        from .camera_snapshot import CameraSnapshot
        CameraSnapshot._images.clear()
