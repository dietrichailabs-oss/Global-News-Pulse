"""Explicitly opened official YouTube player and lawful link directory."""
from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox, QMessageBox, QDialog, QHBoxLayout, QFrame, QSizePolicy, QCheckBox, QLineEdit, QFormLayout, QDialogButtonBox

from .security import safe_url

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id(url):
    try:
        p = urlsplit(safe_url(url))
    except (ValueError, TypeError):
        return None
    host = p.hostname.lower()
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = p.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "www.youtube-nocookie.com", "youtube-nocookie.com"}:
        candidate = parse_qs(p.query).get("v", [""])[0]
        if not candidate and p.path.startswith(("/embed/", "/live/", "/shorts/")):
            candidate = p.path.split("/")[2]
    else:
        return None
    return candidate if VIDEO_ID.fullmatch(candidate) else None


def media_identity(item):
    """Keep separate tuned stations even when they share one public receiver URL."""
    url = str(item.get("url", item.get("original_url", "")))
    receiver = item.get("receiver")
    frequency = item.get("frequency")
    mode = item.get("mode")
    if receiver not in {None, ""} and frequency not in {None, ""} and mode not in {None, ""}:
        return ("station", url, str(receiver), str(frequency), str(mode))
    return ("url", url)


class _MediaTile(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.media = []
        self.catalog = []
        self.view = None
        self.profile = None
        self.radio_view = None
        self.radio_profile = None
        self.radio_interceptor = None
        self.radio_host = ""
        self.floating = None
        self.camera = None
        self.camera_id = None
        self.auto_camera_suspended = False
        self.layout_ = QVBoxLayout(self)
        self.setObjectName("MediaTile")
        self.setMinimumWidth(0)
        self.layout_.setContentsMargins(5, 5, 5, 5)
        self.layout_.setSpacing(4)
        self._items_signature = None
        self.selector = QComboBox()
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selector.setMinimumContentsLength(5)
        self.selector.setMinimumWidth(0)
        self.selector.setAccessibleName("Related media and public listening directory")
        channel_row = QHBoxLayout()
        channel_row.setContentsMargins(0, 0, 0, 0)
        channel_row.setSpacing(2)
        previous_channel = QPushButton("CH ◀")
        previous_channel.setAccessibleName("Previous media channel")
        previous_channel.setToolTip("Select the previous channel in the current channel bank")
        previous_channel.setStyleSheet("font-size:10px;padding:2px 3px;")
        previous_channel.clicked.connect(lambda: self.select_relative(-1))
        next_channel = QPushButton("CH ▶")
        next_channel.setAccessibleName("Next media channel")
        next_channel.setToolTip("Select the next channel in the current channel bank")
        next_channel.setStyleSheet("font-size:10px;padding:2px 3px;")
        next_channel.clicked.connect(lambda: self.select_relative(1))
        channel_row.addWidget(previous_channel)
        channel_row.addWidget(self.selector, 1)
        channel_row.addWidget(next_channel)
        self.layout_.addLayout(channel_row)
        self.note = QLabel("Select an event to explore attributed media. Playback starts only when you choose it.")
        self.note.setWordWrap(False)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.note.setFixedHeight(14)
        self.note.setObjectName("Muted")
        self.note.setMaximumHeight(24)
        self.note.setStyleSheet("font-size:10px;")
        self.layout_.addWidget(self.note)
        self.display = QLabel("PUBLIC MEDIA\n\nNo player connected")
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setMinimumHeight(40)
        self.display.setStyleSheet("background:#10151b; color:#788595; border:1px solid #29303b; border-radius:7px;")
        self.layout_.addWidget(self.display, 1)
        row = QGridLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(2)
        for index, (label, action) in enumerate([("Watch", self.watch), ("Source ↗", self.open_original), ("Float", self.float_player), ("Stop", self.user_stop)]):
            button = QPushButton(label)
            button.clicked.connect(action)
            button.setStyleSheet("font-size:10px;padding:2px 3px;")
            button.setAccessibleName(label + " selected media source")
            row.addWidget(button, 0, index)
        self.layout_.addLayout(row)
        self.selector.currentIndexChanged.connect(self._describe)
        self._populate()

    def set_catalog(self, catalog):
        self.catalog = catalog if isinstance(catalog, list) else catalog.get("sources", catalog.get("entries", []))
        self._populate()

    def set_event(self, event):
        self.media = (event or {}).get("media", [])
        if not self.media:
            self.media = [m for r in (event or {}).get("reports", []) for m in r.get("media", [])]
        self._populate()

    def _populate(self, initial_index=None):
        signature = repr(self.media + self.catalog)
        if signature == self._items_signature:
            return
        self._items_signature = signature
        self.stop()
        self.selector.blockSignals(True)
        self.selector.clear()
        seen = set()
        for item in self.media + self.catalog:
            if isinstance(item, str):
                item = {"url": item, "title": "Original media"}
            url = item.get("url", item.get("original_url", ""))
            identity = media_identity(item)
            if not url or identity in seen:
                continue
            seen.add(identity)
            title = str(item.get("title", item.get("name", "Public source")))
            group = str(item.get("group", "")).strip()
            label = f"[{group.upper()}] {title}" if group else title
            self.selector.addItem(label, item)
        if not self.selector.count():
            self.selector.addItem("No associated media", {})
        if initial_index is not None and self.selector.count():
            self.selector.setCurrentIndex(max(0, min(int(initial_index), self.selector.count() - 1)))
        self.selector.blockSignals(False)
        self._describe()

    def select_relative(self, step):
        """Select the adjacent channel without starting playback automatically."""
        count = self.selector.count()
        if not count:
            return False
        start = self.selector.currentIndex()
        direction = -1 if int(step) < 0 else 1
        for offset in range(1, count + 1):
            index = (start + direction * offset) % count
            if self.selector.itemData(index):
                self.selector.setCurrentIndex(index)
                return True
        return False

    def _current(self):
        return self.selector.currentData() or {}

    def _describe(self, *_):
        self.stop()
        item = self._current()
        details = [str(item[key]) for key in ("provider", "region", "live_status", "availability", "status") if item.get(key)]
        if item.get("last_verified"):
            details.append("Last checked " + str(item["last_verified"]))
        if item.get("rights"):
            details.append(str(item["rights"]))
        description = " · ".join(details) or "Availability unverified · no recording"
        self.note.setText(description)
        self.note.setToolTip(description)
        self.display.setText("ON DEMAND\nNot connected" if item else "No associated source")
        self.display.setWordWrap(True)
        self.selector.setToolTip(str(item.get("title", item.get("name", "No associated media"))))

    def open_original(self):
        item = self._current()
        try:
            QDesktopServices.openUrl(QUrl(safe_url(item.get("url", item.get("original_url", "")))))
        except ValueError as error:
            self.note.setText(str(error))

    def user_stop(self):
        self.auto_camera_suspended=True
        self.stop()

    def connect_camera(self, auto_consented=False):
        from .camera_context import approved_camera
        item=approved_camera(self._current())
        if not item or (auto_consented and self.auto_camera_suspended):return False
        if not auto_consented:self.auto_camera_suspended=False
        if self.camera and self.camera_id==item['id']:return True
        if not auto_consented:
            consent=QMessageBox.question(self,"Connect to public camera?",
                "This connects to the named public provider, which receives your IP address. Images stay in memory. This is area context, not evidence of the incident. Continue?",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if consent!=QMessageBox.StandardButton.Yes:return False
        from .camera_snapshot import CameraSnapshot
        self.stop()
        self.camera=CameraSnapshot(item,self);self.camera_id=item['id']
        self.camera.status_changed.connect(self.note.setText)
        self.layout_.insertWidget(3,self.camera,1);self.display.hide();self.camera.start()
        return True

    def watch(self):
        item = self._current()
        if item.get('snapshot_url'):
            self.connect_camera()
            return
        if str(item.get("type", "")).lower() == "radio" and all(item.get(key) not in {None, ""} for key in ("receiver", "frequency", "mode")):
            try:
                receiver_url = safe_url(item.get("receiver") or item.get("url", item.get("original_url", "")))
            except ValueError as error:
                self.note.setText(str(error))
                return
            consent = QMessageBox.question(
                self,
                "Connect to public radio receiver?",
                "Pulse will load only this exact receiver host over HTTPS/WSS in an isolated, memory-only browser session. "
                "The receiver receives your IP address and requests. Playback still requires a user gesture. "
                "Off or Stop all blanks the receiver page and disconnects the in-app session. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if consent != QMessageBox.StandardButton.Yes:
                return
            try:
                self._connect_radio_receiver(receiver_url)
                self.note.setText(
                    f"Public receiver connected · {item.get('frequency')} {item.get('mode')} · "
                    "provider controls actual tuning · Off disconnects"
                )
            except (ImportError, RuntimeError, ValueError) as error:
                self.note.setText(str(error) + ". The original-source link remains available.")
            return
        video = youtube_id(item.get("url", item.get("original_url", "")))
        if not video:
            self.note.setText("This source supports its original website. Select Original source to open it.")
            return
        consent = QMessageBox.question(self, "Connect to YouTube?", "The official player connects directly to YouTube and its media servers. The provider receives your IP address and player requests. Playback is initially muted. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if consent != QMessageBox.StandardButton.Yes:
            return
        try:
            if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX", "").lower() not in {"", "0", "false"} or "--no-sandbox" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
                raise RuntimeError("The embedded player requires Chromium sandboxing to remain enabled")
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                raise RuntimeError("The sandboxed player requires a standard user session")
            self._ensure_player()
            from PySide6.QtWebEngineCore import QWebEngineHttpRequest
            request = QWebEngineHttpRequest(QUrl(f"https://www.youtube-nocookie.com/embed/{video}?autoplay=0&mute=1&playsinline=1"))
            request.setHeader(b"Referer", b"https://www.dietrichailabs.com/")
            self.view.load(request)
            self.view.show()
            self.display.hide()
            self.note.setText("Official YouTube player · Click Play to begin · initially muted")
        except (ImportError, RuntimeError) as error:
            self.note.setText(str(error) + ". The original-source link remains available.")

    def _connect_radio_receiver(self, receiver_url):
        receiver_url = safe_url(receiver_url)
        if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX", "").lower() not in {"", "0", "false"} or "--no-sandbox" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
            raise RuntimeError("The embedded receiver requires Chromium sandboxing to remain enabled")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise RuntimeError("The sandboxed receiver requires a standard user session")
        self._ensure_radio_player(receiver_url)
        self.radio_view.load(QUrl(receiver_url))
        self.radio_view.show()
        self.display.hide()
        return True

    def _ensure_radio_player(self, receiver_url):
        receiver_url = safe_url(receiver_url)
        host = (urlsplit(receiver_url).hostname or "").lower()
        if not host:
            raise ValueError("A public receiver host is required")
        if self.radio_view and self.radio_host == host:
            return
        if self.radio_view:
            self.radio_view.stop()
            self.radio_view.setUrl(QUrl("about:blank"))
            self.radio_view.hide()
            self.radio_view.deleteLater()
            self.radio_view = None
        if self.radio_profile:
            self.radio_profile.deleteLater()
            self.radio_profile = None
        self.radio_interceptor = None
        self.radio_host = host

        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineUrlRequestInterceptor, QWebEngineSettings

        class ReceiverInterceptor(QWebEngineUrlRequestInterceptor):
            def __init__(self, allowed_host, parent=None):
                super().__init__(parent)
                self.allowed_host = allowed_host

            def interceptRequest(self, info):
                url = info.requestUrl()
                if url.scheme() in {"about", "data", "blob"}:
                    return
                info.block(
                    url.scheme() not in {"https", "wss"}
                    or url.port(443) != 443
                    or url.host().lower() != self.allowed_host
                )

        class ReceiverPage(QWebEnginePage):
            def __init__(self, profile, view, allowed_host):
                super().__init__(profile, view)
                self.allowed_host = allowed_host

            def createWindow(self, _):
                return None

            def acceptNavigationRequest(self, url, kind, main):
                if not main:
                    return True
                return url.scheme() == "about" or (
                    url.scheme() == "https"
                    and url.port(443) == 443
                    and url.host().lower() == self.allowed_host
                )

        self.radio_profile = QWebEngineProfile(self)
        self.radio_profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.radio_profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.radio_profile.setPushServiceEnabled(False)
        self.radio_interceptor = ReceiverInterceptor(host, self.radio_profile)
        self.radio_profile.setUrlRequestInterceptor(self.radio_interceptor)
        self.radio_profile.downloadRequested.connect(lambda download: download.cancel())
        self.radio_view = QWebEngineView(self)
        page = ReceiverPage(self.radio_profile, self.radio_view, host)
        page.permissionRequested.connect(lambda permission: permission.deny())
        page.certificateError.connect(lambda error: error.rejectCertificate())
        self.radio_view.setPage(page)
        settings = page.settings()
        for flag in (
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
        ):
            settings.setAttribute(flag, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, True)
        self.layout_.insertWidget(3, self.radio_view, 1)

    def _ensure_player(self):
        if self.view:
            return
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineUrlRequestInterceptor, QWebEngineSettings

        class Interceptor(QWebEngineUrlRequestInterceptor):
            def interceptRequest(self, info):
                url = info.requestUrl()
                if url.scheme() in {"about", "data", "blob"}:
                    return
                host = url.host().lower()
                allowed = ("youtube-nocookie.com", "youtube.com", "googlevideo.com", "ytimg.com", "gstatic.com", "ggpht.com")
                info.block(url.scheme() != "https" or url.port(443) != 443 or not any(host == x or host.endswith("." + x) for x in allowed))

        class Page(QWebEnginePage):
            def createWindow(self, _):
                return None
            def acceptNavigationRequest(self, url, kind, main):
                return url.scheme() == "about" or (url.scheme() == "https" and url.host() in {"www.youtube-nocookie.com", "www.youtube.com"} and url.path().startswith("/embed/")) or not main

        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.profile.setPushServiceEnabled(False)
        self.interceptor = Interceptor(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        self.view = QWebEngineView(self)
        page = Page(self.profile, self.view)
        page.permissionRequested.connect(lambda permission: permission.deny())
        page.certificateError.connect(lambda error: error.rejectCertificate())
        self.view.setPage(page)
        settings = page.settings()
        for flag in (QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, QWebEngineSettings.WebAttribute.FullScreenSupportEnabled):
            settings.setAttribute(flag, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, True)
        self.layout_.insertWidget(3, self.view, 1)

    def float_player(self):
        if not self.view:
            self.note.setText("Open a permitted video before floating the player.")
            return
        if self.floating:
            self.floating.raise_()
            return
        self.floating = QDialog(self)
        self.floating.setWindowTitle("Global Pulse · Media")
        self.floating.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.floating.resize(520, 330)
        layout = QVBoxLayout(self.floating)
        layout.addWidget(self.view)
        self.floating.finished.connect(self._dock)
        self.floating.show()

    def _dock(self, *_):
        if self.view:
            self.layout_.insertWidget(3, self.view, 1)
        self.floating = None

    def stop(self):
        if self.camera:
            self.camera.stop();self.camera.hide();self.camera.deleteLater()
            self.camera=None;self.camera_id=None
        if self.view:
            self.view.stop()
            self.view.setUrl(QUrl("about:blank"))
            self.view.hide()
        if self.radio_view:
            self.radio_view.stop()
            self.radio_view.setUrl(QUrl("about:blank"))
            self.radio_view.hide()
        if self.floating:
            self.floating.close()
        self.display.show()
        self.note.setText("Media stopped. Source monitoring is controlled separately.")


class MediaPanel(QWidget):
    """Four bounded on-demand tiles; directory entries are never labeled live.

    Changing the event/category stops replaced players. A routine refresh of
    identical entries preserves playback. Every embedded connection still needs
    its tile's explicit consent and maintains the isolated provider profile.
    """
    auto_cameras_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._event = None
        self._camera_matches = []
        self.auto_cameras = False
        self._shutting_down = False
        self.catalog = []
        self.media = []
        self.filter_kind = "All"
        self.channel_bank = "All channels"
        self._setting_getter = None
        self._setting_setter = None
        self.radio_presets = [None] * 5
        self.radio_stations = []
        self.radio_event_bindings = {}
        self.radio_manual_override = False
        self.radio_off_state = True
        self._active_radio_tile = None
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(4)
        tools = QHBoxLayout()
        tools.setSpacing(3)
        self.category_buttons = {}
        for name in ("All", "Video", "Webcams", "Radio"):
            item = QPushButton(name)
            item.setCheckable(True)
            item.setChecked(name == "All")
            item.setStyleSheet("font-size:10px;padding:2px 3px;")
            item.clicked.connect(lambda checked=False, kind=name: self._filter(kind))
            tools.addWidget(item)
            self.category_buttons[name] = item
        self.bank_combo = QComboBox()
        self.bank_combo.addItems(["All channels", "News", "Markets", "Weather", "World", "Public affairs"])
        self.bank_combo.setAccessibleName("TV channel bank")
        self.bank_combo.setToolTip("Filter the TV-style channel lineup by coverage bank")
        self.bank_combo.setStyleSheet("font-size:10px;")
        self.bank_combo.currentTextChanged.connect(self._bank_changed)
        tools.addWidget(self.bank_combo)
        stop = QPushButton("Stop all")
        stop.setStyleSheet("font-size:10px;padding:2px 3px;")
        stop.clicked.connect(self.stop)
        tools.addWidget(stop)
        self.layout_.addLayout(tools)
        follow=QHBoxLayout()
        self.auto_camera_check=QCheckBox("Auto cameras")
        self.auto_camera_check.setToolTip("Follow the selected event with reviewed public area cameras after consent. Limited coverage; never private cameras.")
        self.auto_camera_check.toggled.connect(self._toggle_cameras)
        self.camera_status=QLabel("Select an event for area cameras")
        self.camera_status.setObjectName("Muted");self.camera_status.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        follow.addWidget(self.auto_camera_check);follow.addWidget(self.camera_status,1)
        self.layout_.addLayout(follow)

        radio_controls = QHBoxLayout()
        radio_controls.setSpacing(2)
        self.radio_scan_prev = QPushButton("Scan presets ◀")
        self.radio_scan_prev.setAccessibleName("Scan previous saved radio preset")
        self.radio_scan_prev.clicked.connect(lambda: self._scan_radio_presets(-1))
        self.radio_add = QPushButton("Add station…")
        self.radio_add.setAccessibleName("Add a public radio receiver station")
        self.radio_add.setToolTip("Save an exact public receiver/tune URL with a station name, frequency and mode")
        self.radio_add.clicked.connect(self._add_radio_station_dialog)
        self.radio_link_event = QPushButton("Link event")
        self.radio_link_event.setAccessibleName("Link the current radio station to the selected event")
        self.radio_link_event.setToolTip("Locally associate the current concrete station with this event for Resume auto-tune; no receiver is opened automatically")
        self.radio_link_event.clicked.connect(self.toggle_event_radio_binding)
        self.radio_hold = QPushButton("Hold")
        self.radio_hold.setAccessibleName("Hold current radio station and suspend automatic tuning")
        self.radio_hold.clicked.connect(self.hold_radio)
        self.radio_scan_next = QPushButton("Scan presets ▶")
        self.radio_scan_next.setAccessibleName("Scan next saved radio preset")
        self.radio_scan_next.clicked.connect(lambda: self._scan_radio_presets(1))
        self.radio_resume = QPushButton("Resume auto-tune")
        self.radio_resume.setAccessibleName("Resume automatic event radio tuning")
        self.radio_resume.clicked.connect(self.resume_auto_tune)
        self.radio_off_button = QPushButton("Off")
        self.radio_off_button.setAccessibleName("Turn radio off and disconnect")
        self.radio_off_button.clicked.connect(self.radio_off)
        for control in (self.radio_scan_prev, self.radio_add, self.radio_link_event, self.radio_hold, self.radio_scan_next, self.radio_resume, self.radio_off_button):
            control.setStyleSheet("font-size:10px;padding:2px 3px;")
            radio_controls.addWidget(control)
        self.layout_.addLayout(radio_controls)

        radio_presets = QHBoxLayout()
        radio_presets.setSpacing(2)
        radio_presets.addWidget(QLabel("RADIO PRESETS"))
        self.radio_preset_buttons = []
        for slot in range(5):
            control = QPushButton(str(slot + 1))
            control.setAccessibleName(f"Radio preset {slot + 1}")
            control.setToolTip("Click to recall. Right-click to save the currently tuned receiver/frequency/mode.")
            control.setStyleSheet("font-size:10px;padding:2px 6px;")
            control.clicked.connect(lambda checked=False, index=slot: self.recall_radio_preset(index))
            control.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            control.customContextMenuRequested.connect(lambda _pos, index=slot: self.save_radio_preset(index))
            radio_presets.addWidget(control)
            self.radio_preset_buttons.append(control)
        self.radio_status = QLabel("Radio off · directory receivers use Scan presets")
        self.radio_status.setObjectName("Muted")
        self.radio_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        radio_presets.addWidget(self.radio_status, 1)
        self.layout_.addLayout(radio_presets)

        self.grid = QGridLayout()
        self.grid.setSpacing(5)
        self.tiles = [_MediaTile(self) for _ in range(4)]
        for index, tile in enumerate(self.tiles):
            tile.setAccessibleName(f"On-demand public media tile {index + 1}")
            tile.selector.activated.connect(lambda _index, selected=tile: self._radio_selection_manual(selected))
            self.grid.addWidget(tile, index // 2, index % 2)
        for index in range(2):
            self.grid.setRowStretch(index, 1)
            self.grid.setColumnStretch(index, 1)
        self.layout_.addLayout(self.grid, 1)

    def set_catalog(self, catalog):
        self.catalog = catalog if isinstance(catalog, list) else catalog.get("sources", catalog.get("entries", []))
        self._populate()

    def configure_radio_preferences(self, getter, setter):
        """Load/save five presets plus user-configured public receiver stations."""
        self._setting_getter = getter
        self._setting_setter = setter
        saved = getter("radio_presets", [None] * 5) if callable(getter) else [None] * 5
        if not isinstance(saved, list):
            saved = [None] * 5
        normalized = [dict(item) if isinstance(item, dict) else None for item in saved[:5]]
        self.radio_presets = (normalized + [None] * 5)[:5]

        saved_stations = getter("radio_stations", []) if callable(getter) else []
        self.radio_stations = []
        if isinstance(saved_stations, list):
            for item in saved_stations[:100]:
                if not isinstance(item, dict):
                    continue
                try:
                    station = self._normalize_radio_station(item)
                except ValueError:
                    continue
                if not any(self._same_station(station, existing) for existing in self.radio_stations):
                    self.radio_stations.append(station)

        saved_bindings = getter("radio_event_bindings", {}) if callable(getter) else {}
        self.radio_event_bindings = {}
        if isinstance(saved_bindings, dict):
            for event_id, item in list(saved_bindings.items())[:200]:
                key = self._event_binding_key({"id": event_id})
                if not key or not isinstance(item, dict):
                    continue
                try:
                    self.radio_event_bindings[key] = self._normalize_radio_station(item)
                except ValueError:
                    continue
        self._refresh_radio_preset_labels()
        self._refresh_event_binding_control()
        self._populate()

    def set_event(self, event):
        from .camera_context import associated_cameras
        held_station = None
        if self.radio_manual_override and not self.radio_off_state:
            current = self._radio_current_item()
            if self._station_record(current):
                held_station = dict(current)
        if (event or {}).get('id') != (self._event or {}).get('id'):
            for tile in self.tiles:tile.auto_camera_suspended=False
        self._event=event
        self._refresh_event_binding_control()
        self._camera_matches=associated_cameras(event)
        self.camera_status.setText(f"{len(self._camera_matches)} area camera(s) · not incident proof" if self._camera_matches else "No reviewed camera for this area")
        self.camera_status.setToolTip(self.camera_status.text()+". Starter coverage is limited; unavailable locations are not substituted.")
        self.media = (event or {}).get("media", [])
        if not self.media:
            self.media = [m for r in (event or {}).get("reports", []) for m in r.get("media", [])]
        self._populate()
        # A manual Hold survives event/media repopulation even when the held
        # station came from the prior event rather than the saved station list.
        if held_station:
            self._select_radio_item(held_station)
        # Event-follow uses only an explicitly associated tuned-station record.
        # A directory entry is never guessed into a frequency/mode, and
        # historical/synthetic views never cause receiver navigation.
        if event and not event.get("historical_view") and not event.get("synthetic"):
            station = self._event_radio_station()
            if station:
                self.auto_tune_radio(station)

    @staticmethod
    def _kind(item):
        text = " ".join(str(item.get(k, "")) for k in ("type", "category", "title", "name")).lower()
        if "radio" in text or "sdr" in text:
            return "Radio"
        if "camera" in text or "webcam" in text:
            return "Webcams"
        return "Video"

    @classmethod
    def _group(cls, item):
        group = str(item.get("group", "")).strip()
        if group:
            return group
        kind = cls._kind(item)
        if kind in {"Radio", "Webcams"}:
            return kind
        return "World"

    def _bank_changed(self, bank):
        self.channel_bank = str(bank or "All channels")
        if self.filter_kind != "All":
            self.filter_kind = "All"
            for name, control in self.category_buttons.items():
                control.setChecked(name == "All")
        self._populate()

    def _filter(self, kind):
        self.filter_kind = kind
        for name, control in self.category_buttons.items():
            control.setChecked(name == kind)
        self._populate()

    def _populate(self):
        items, seen = [], set()
        for raw in self._camera_matches + self.media + self.radio_stations + self.catalog:
            item = {"url": raw, "title": "Original media"} if isinstance(raw, str) else raw
            if not isinstance(item, dict):
                continue
            url = item.get("url", item.get("original_url", ""))
            identity = media_identity(item)
            if not url or identity in seen:
                continue
            if self.filter_kind != "All" and self._kind(item) != self.filter_kind:
                continue
            if self.channel_bank != "All channels" and self._group(item) != self.channel_bank:
                continue
            seen.add(identity)
            items.append(item)
        for index, tile in enumerate(self.tiles):
            # Preserve the established four-way contextual-media/camera
            # distribution unless the user explicitly chooses a TV channel
            # bank.  A selected bank is a television-style browsing mode: each
            # tile can channel-surf the complete bank and starts at a different
            # channel.  The default All/type-filter paths retain the prior
            # one-copy-per-item behavior so camera auto-follow never multiplies
            # a single matching camera across all four tiles.
            if self.channel_bank == "All channels":
                tile.media = items[index::4]
                initial = None
            else:
                tile.media = items
                initial = index
            tile.catalog = []
            tile._populate(initial_index=initial)
            if (not self._shutting_down and self.auto_cameras and self._event and not self._event.get("synthetic") and not self._event.get("historical_view")
                    and self._event.get("severity") in {"critical","high","moderate"}
                    and tile._current().get('id') in {m['id'] for m in self._camera_matches}):
                tile.connect_camera(auto_consented=True)
            elif tile.camera:
                tile.stop()

    def _radio_current_item(self):
        if self._active_radio_tile is not None:
            item = self._active_radio_tile._current()
            if item and self._kind(item) == "Radio":
                return item
        for tile in self.tiles:
            item = tile._current()
            if item and self._kind(item) == "Radio":
                return item
        return {}

    @staticmethod
    def _station_record(item):
        receiver = item.get("receiver")
        frequency = item.get("frequency")
        mode = item.get("mode")
        if receiver in {None, ""} or frequency in {None, ""} or mode in {None, ""}:
            return None
        return {
            "receiver": str(receiver),
            "frequency": str(frequency),
            "mode": str(mode),
            "name": str(item.get("name", item.get("title", "")))[:120],
            "id": str(item.get("id", ""))[:120],
            "url": str(item.get("url", item.get("original_url", "")))[:2048],
        }

    @staticmethod
    def _radio_text(value, label, limit):
        text = " ".join(str(value or "").split())
        if not text or len(text) > limit or any(ord(char) < 32 for char in text):
            raise ValueError(f"Invalid {label}")
        return text

    @classmethod
    def _normalize_radio_station(cls, item):
        name = cls._radio_text(item.get("name", item.get("title", "")), "station name", 120)
        frequency = cls._radio_text(item.get("frequency"), "frequency", 40)
        mode = cls._radio_text(item.get("mode"), "mode", 20).upper()
        if not re.fullmatch(r"[A-Za-z0-9 .,+/_-]+", frequency) or not any(char.isdigit() for char in frequency):
            raise ValueError("Frequency must include a numeric value")
        if not re.fullmatch(r"[A-Z0-9 +/_-]+", mode):
            raise ValueError("Invalid radio mode")
        url = safe_url(item.get("url", item.get("receiver", "")))
        identity = hashlib.sha256((url + "\0" + frequency + "\0" + mode).encode("utf-8")).hexdigest()[:20]
        return {
            "id": "user_radio_" + identity,
            "title": name,
            "name": name,
            "provider": "User-configured public receiver",
            "type": "radio",
            "group": "World",
            "region": "User configured",
            "url": url,
            "receiver": url,
            "frequency": frequency,
            "mode": mode,
            "availability": "Exact public receiver/tune URL saved locally; opening it is always an explicit user action.",
            "rights": "Provider terms apply. No recording, retransmission, access-control bypass, private receivers or encrypted communications.",
            "custom": True,
        }

    def _persist_radio_stations(self):
        if callable(self._setting_setter):
            self._setting_setter("radio_stations", [dict(item) for item in self.radio_stations])

    def add_radio_station(self, name, url, frequency, mode):
        """Create/select one truthful local station record backed by a public HTTPS receiver URL."""
        station = self._normalize_radio_station({
            "name": name,
            "url": url,
            "frequency": frequency,
            "mode": mode,
        })
        existing = next((item for item in self.radio_stations if self._same_station(item, station)), None)
        if existing is None:
            self.radio_stations.append(station)
            self._persist_radio_stations()
        else:
            station = existing
        self._populate()
        if not self._select_radio_preset_record(station):
            raise ValueError("Configured station could not be selected")
        self.radio_manual_override = True
        self.radio_off_state = False
        self.radio_status.setText(
            f"Manual tune · {station['frequency']} {station['mode']} · exact public receiver selected · auto-tune suspended"
        )
        return dict(station)

    def _add_radio_station_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add public radio station")
        layout = QVBoxLayout(dialog)
        help_text = QLabel(
            "Save an exact public HTTPS receiver/tune URL plus the frequency and mode you selected on that provider. "
            "Pulse does not scan the air, guess receiver parameters, record audio, or open the receiver until you explicitly choose Watch/Source."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        form = QFormLayout()
        name = QLineEdit()
        name.setPlaceholderText("e.g. Local news receiver")
        receiver_url = QLineEdit()
        receiver_url.setPlaceholderText("https://public-receiver.example/...")
        frequency = QLineEdit()
        frequency.setPlaceholderText("e.g. 7.200 MHz")
        mode = QComboBox()
        mode.setEditable(True)
        mode.addItems(["AM", "FM", "USB", "LSB", "CW", "SAM", "NFM", "WFM"])
        form.addRow("Station name", name)
        form.addRow("Exact receiver/tune URL", receiver_url)
        form.addRow("Frequency", frequency)
        form.addRow("Mode", mode)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            self.add_radio_station(name.text(), receiver_url.text(), frequency.text(), mode.currentText())
        except ValueError as error:
            QMessageBox.warning(self, "Station not saved", str(error))
            return False
        return True

    @staticmethod
    def _event_binding_key(event):
        if not isinstance(event, dict) or event.get("historical_view") or event.get("synthetic"):
            return ""
        key = str(event.get("id", "")).strip()
        if not key or len(key) > 500 or any(ord(char) < 32 for char in key):
            return ""
        return key

    def _persist_radio_event_bindings(self):
        if callable(self._setting_setter):
            self._setting_setter(
                "radio_event_bindings",
                {key: dict(value) for key, value in self.radio_event_bindings.items()},
            )

    def _refresh_event_binding_control(self):
        if not hasattr(self, "radio_link_event"):
            return
        key = self._event_binding_key(self._event)
        linked = bool(key and key in self.radio_event_bindings)
        self.radio_link_event.setText("Unlink event" if linked else "Link event")
        self.radio_link_event.setEnabled(bool(key))
        if linked:
            station = self.radio_event_bindings[key]
            self.radio_link_event.setToolTip(
                f"Remove local event link to {station.get('name') or station.get('frequency', 'station')}"
            )
        elif key:
            self.radio_link_event.setToolTip(
                "Locally associate the current concrete station with this event for Resume auto-tune; no receiver is opened automatically"
            )
        else:
            self.radio_link_event.setToolTip("Select a live event before linking a station")

    def toggle_event_radio_binding(self):
        key = self._event_binding_key(self._event)
        if not key:
            self.radio_status.setText("Event link unavailable · select a live non-synthetic event")
            return False
        if key in self.radio_event_bindings:
            removed = self.radio_event_bindings.pop(key)
            self._persist_radio_event_bindings()
            self._refresh_event_binding_control()
            self.radio_manual_override = True
            self.radio_status.setText(
                f"Event link removed · {removed.get('name') or removed.get('frequency', 'station')} · manual control retained"
            )
            return True

        current = self._radio_current_item()
        record = self._station_record(current)
        if not record:
            self.radio_status.setText("Event link not saved · select a concrete receiver/frequency/mode station")
            return False
        try:
            station = self._normalize_radio_station({
                "name": record.get("name") or current.get("title") or "Event radio station",
                "url": record.get("receiver") or record.get("url"),
                "frequency": record.get("frequency"),
                "mode": record.get("mode"),
            })
        except ValueError as error:
            self.radio_status.setText("Event link not saved · " + str(error))
            return False

        if len(self.radio_event_bindings) >= 200 and key not in self.radio_event_bindings:
            oldest = next(iter(self.radio_event_bindings), None)
            if oldest is not None:
                self.radio_event_bindings.pop(oldest, None)
        self.radio_event_bindings[key] = station
        self._persist_radio_event_bindings()
        self._refresh_event_binding_control()
        self.radio_manual_override = True
        self.radio_off_state = False
        self.radio_status.setText(
            f"Event linked locally · {station['frequency']} {station['mode']} · Resume auto-tune to follow it"
        )
        return True

    def _event_radio_station(self):
        for raw in self.media:
            if isinstance(raw, dict) and self._kind(raw) == "Radio" and self._station_record(raw):
                return raw
        key = self._event_binding_key(self._event)
        if key:
            bound = self.radio_event_bindings.get(key)
            if bound and self._station_record(bound):
                return bound
        return None

    def _refresh_radio_preset_labels(self):
        for index, control in enumerate(self.radio_preset_buttons):
            preset = self.radio_presets[index] if index < len(self.radio_presets) else None
            control.setText(f"{index + 1}*" if preset else str(index + 1))
            if preset:
                name = preset.get("name") or f"{preset.get('frequency', '')} {preset.get('mode', '')}"
                control.setToolTip(f"{name} · click to recall · right-click to replace")
            else:
                control.setToolTip("Empty preset · right-click to save the currently tuned receiver/frequency/mode")

    def _persist_radio_presets(self):
        self._refresh_radio_preset_labels()
        if callable(self._setting_setter):
            self._setting_setter("radio_presets", [dict(item) if item else None for item in self.radio_presets])

    def save_radio_preset(self, slot):
        item = self._radio_current_item()
        record = self._station_record(item)
        if record is None:
            self.radio_status.setText("Preset not saved · select a tuned receiver with receiver/frequency/mode")
            return False
        self.radio_presets[int(slot)] = record
        self._persist_radio_presets()
        self.radio_manual_override = True
        self.radio_off_state = False
        self.radio_status.setText(f"Preset {int(slot) + 1} saved · {record['receiver']} {record['frequency']} {record['mode']}")
        return True

    @staticmethod
    def _same_station(item, preset):
        record = MediaPanel._station_record(item)
        if not record or not preset:
            return False
        return all(str(record.get(key, "")) == str(preset.get(key, "")) for key in ("receiver", "frequency", "mode"))

    def _select_radio_item(self, item):
        if not isinstance(item, dict) or self._kind(item) != "Radio" or not self._station_record(item):
            return False
        # A selected station becomes the primary radio tile. Preserve the rest
        # of the grid, but stop prior in-app media before replacing the tile.
        for existing in self.tiles:
            if self._kind(existing._current()) == "Radio":
                existing.stop()

        self.channel_bank = "All channels"
        self.bank_combo.blockSignals(True)
        self.bank_combo.setCurrentText("All channels")
        self.bank_combo.blockSignals(False)
        self.filter_kind = "Radio"
        for name, control in self.category_buttons.items():
            control.setChecked(name == "Radio")

        tile = self.tiles[0]
        tile.media = [dict(item)]
        tile.catalog = []
        tile._items_signature = None
        tile._populate()
        self._active_radio_tile = tile
        return self._same_station(tile._current(), item)

    def _select_radio_preset_record(self, preset):
        if not preset:
            return False
        candidates = []
        for raw in self.media + self.radio_stations + self.catalog:
            if not isinstance(raw, dict):
                continue
            if self._kind(raw) == "Radio" and self._same_station(raw, preset):
                candidates.append(raw)
        if candidates:
            return self._select_radio_item(candidates[0])

        # Presets are self-contained by design: a station saved from an event
        # must remain recallable after the event/catalog entry disappears or
        # after restart. Reconstruct only through the same public-URL and
        # bounded tuning validation used by Add station.
        try:
            restored = self._normalize_radio_station({
                "name": preset.get("name") or preset.get("frequency") or "Saved radio preset",
                "url": preset.get("receiver") or preset.get("url"),
                "frequency": preset.get("frequency"),
                "mode": preset.get("mode"),
            })
        except (AttributeError, ValueError):
            return False
        return self._select_radio_item(restored)

    def recall_radio_preset(self, slot):
        preset = self.radio_presets[int(slot)] if 0 <= int(slot) < len(self.radio_presets) else None
        if not preset:
            self.radio_status.setText(f"Preset {int(slot) + 1} is empty")
            return False
        if not self._select_radio_preset_record(preset):
            self.radio_status.setText(f"Preset {int(slot) + 1} unavailable in the current reviewed receiver catalog")
            return False
        self.radio_manual_override = True
        self.radio_off_state = False
        self.radio_status.setText(f"Preset {int(slot) + 1} recalled · manual control has priority")
        return True

    def _scan_radio_presets(self, step):
        saved = [index for index, preset in enumerate(self.radio_presets) if preset]
        if not saved:
            self.radio_status.setText("No saved presets to scan · signal scanning is not claimed for directory receivers")
            return False
        current = self._radio_current_item()
        matched = next((index for index in saved if self._same_station(current, self.radio_presets[index])), None)
        if matched is None:
            target = saved[0] if int(step) >= 0 else saved[-1]
        else:
            position = saved.index(matched)
            target = saved[(position + (1 if int(step) >= 0 else -1)) % len(saved)]
        self.radio_manual_override = True
        return self.recall_radio_preset(target)

    def _radio_selection_manual(self, tile):
        item = tile._current()
        if not item or self._kind(item) != "Radio":
            return
        self._active_radio_tile = tile
        self.radio_manual_override = True
        self.radio_off_state = False
        record = self._station_record(item)
        if record:
            self.radio_status.setText(f"Manual tune · {record['receiver']} {record['frequency']} {record['mode']} · auto-tune suspended")
        else:
            self.radio_status.setText("Manual radio source selected · auto-tune suspended · directory source has no signal scan")

    def hold_radio(self):
        self.radio_manual_override = True
        self.radio_status.setText("Hold · manual control has priority until Resume auto-tune")
        return True

    def resume_auto_tune(self):
        self.radio_manual_override = False
        self.radio_off_state = False
        station = self._event_radio_station()
        if self._event and not self._event.get("historical_view") and not self._event.get("synthetic") and station:
            if self.auto_tune_radio(station):
                return True
        self.radio_status.setText("Auto-tune armed · waiting for an event with an explicit tuned-station link · saved presets remain unchanged")
        return True

    def radio_off(self):
        self.radio_manual_override = True
        self.radio_off_state = True
        self._active_radio_tile = None
        for tile in self.tiles:
            if self._kind(tile._current()) == "Radio":
                tile.stop()
        self.radio_status.setText("Radio off · scanning cancelled · event-following cannot reactivate it")
        return True

    def auto_tune_radio(self, item):
        """Production event-follow entry point; never overrides Off/manual control or presets."""
        if self.radio_off_state or self.radio_manual_override:
            return False
        record = self._station_record(item)
        if record is None:
            return False
        before = [dict(preset) if preset else None for preset in self.radio_presets]
        selected = self._select_radio_item(item)
        if self.radio_presets != before:
            raise AssertionError("Automatic radio tuning must never modify saved presets")
        if selected:
            self.radio_status.setText("Auto-tuned for selected event · presets unchanged")
        return selected

    def restore_auto_cameras(self,enabled):
        # Only previously consented local settings call this method.
        self.auto_cameras=bool(enabled)
        self.auto_camera_check.blockSignals(True);self.auto_camera_check.setChecked(self.auto_cameras);self.auto_camera_check.blockSignals(False)

    def _toggle_cameras(self,enabled):
        if enabled:
            answer=QMessageBox.question(self,"Automatically connect area cameras?",
                "When you select an active moderate/high/critical event, connect matching reviewed public landscape cameras automatically?\n\n"
                "Providers receive your IP address. Images are memory-only, silent, and refreshed no faster than every 15 minutes. Coverage is limited; no private cameras, recording or person tracking. This choice is saved. Stop all turns it off.",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            enabled=answer==QMessageBox.StandardButton.Yes
        self.restore_auto_cameras(enabled)
        self.auto_cameras_changed.emit(enabled)
        if enabled:
            for tile in self.tiles:tile.auto_camera_suspended=False
            self._populate()
        else:
            for tile in self.tiles:
                if tile.camera:tile.stop()

    def _stop_players(self):
        for tile in self.tiles:
            tile.stop()
        from .camera_snapshot import CameraSnapshot
        CameraSnapshot._images.clear()

    def shutdown(self):
        """Cancel owned media without revoking the saved Auto cameras choice."""
        self._shutting_down = True
        self._stop_players()

    def stop(self):
        """Explicit Stop all revokes auto-connect until the user enables it."""
        if self.auto_cameras:
            self.restore_auto_cameras(False);self.auto_cameras_changed.emit(False)
        self._stop_players()
