"""One native broadcast-radio connection plus an explicit in-app public SDR receiver.

Only publisher-documented MP3 addresses can be passed to the native audio backend.
A user may explicitly connect one specific public HTTPS WebSDR/KiwiSDR receiver
inside an isolated memory-only WebEngine session. Feed/event content and saved
settings cannot silently supply playback or receiver URLs. No recording: decoded
audio buffers are counted for liveness, never retained.
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSlider, QMessageBox, QLineEdit, QTabWidget,
)
from .security import safe_url
from .sdr_directory import (
    DIRECTORY_URLS, MAX_DIRECTORY_BYTES, parse_directory, public_receiver_url,
)

STATIONS = (
    # Deliberately finite publisher-documented HTTPS MP3 streams, not arbitrary
    # URLs supplied by a community aggregator. Stream availability, user region,
    # broadcaster redistribution rights and native codec support require QA.
    # The dial labels ONLY a publisher-advertised broadcast RF frequency.
    {"id":"wnyc_fm","name":"WNYC 93.9 FM","category":"News & Talk","dial":"FM · 93.9 MHz","language":"English","url":"https://fm939.wnyc.org/wnycfm","documentation":"https://prod.wnyc.org/audio-other-formats/"},
    {"id":"wnyc_am","name":"WNYC 820 AM","category":"News & Talk","dial":"AM · 820 kHz","language":"English","url":"https://am820.wnyc.org/wnycam","documentation":"https://prod.wnyc.org/audio-other-formats/"},
    {"id":"wqxr","name":"WQXR 105.9 FM","category":"Classical","dial":"FM · 105.9 MHz","language":"English","url":"https://stream.wqxr.org/wqxr","documentation":"https://prod.wnyc.org/audio-other-formats/"},
    {"id":"new_sounds","name":"New Sounds","category":"Music","dial":"INTERNET STREAM","language":"English","url":"https://q2stream.wqxr.org/q2","documentation":"https://prod.wnyc.org/audio-other-formats/"},
    {"id":"operavore","name":"Operavore","category":"Classical","dial":"INTERNET STREAM","language":"English","url":"https://opera-stream.wqxr.org/operavore","documentation":"https://prod.wnyc.org/audio-other-formats/"},
    {"id":"new_standards","name":"New Standards","category":"Music","dial":"INTERNET STREAM","language":"English","url":"https://tjc.wnyc.org/js-stream","documentation":"https://prod.wnyc.org/audio-other-formats/"},
    {"id":"deutschlandfunk","name":"Deutschlandfunk","category":"News & Talk","dial":"INTERNET STREAM","language":"German","url":"https://st01.sslstream.dlf.de/dlf/01/128/mp3/stream.mp3","documentation":"https://www.deutschlandradio.de/streamingdienste-100.html"},
    {"id":"deutschlandfunk_kultur","name":"Deutschlandfunk Kultur","category":"Culture","dial":"INTERNET STREAM","language":"German","url":"https://st02.sslstream.dlf.de/dlf/02/128/mp3/stream.mp3","documentation":"https://www.deutschlandradio.de/streamingdienste-100.html"},
    {"id":"deutschlandfunk_nova","name":"Deutschlandfunk Nova","category":"News & Talk","dial":"INTERNET STREAM","language":"German","url":"https://st03.sslstream.dlf.de/dlf/03/128/mp3/stream.mp3","documentation":"https://www.deutschlandradio.de/streamingdienste-100.html"},
    {"id":"deutschlandfunk_debatten","name":"Deutschlandfunk Dokumente & Debatten","category":"News & Talk","dial":"INTERNET STREAM","language":"German","url":"https://st04.sslstream.dlf.de/dlf/04/128/mp3/stream.mp3","documentation":"https://www.deutschlandradio.de/streamingdienste-100.html"},
    {"id":"france_inter","name":"France Inter","category":"News & Talk","dial":"INTERNET STREAM","language":"French","url":"https://icecast.radiofrance.fr/franceinter-midfi.mp3?id=openapi","documentation":"https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-brands"},
    {"id":"france_info","name":"franceinfo","category":"News & Talk","dial":"INTERNET STREAM","language":"French","url":"https://icecast.radiofrance.fr/franceinfo-midfi.mp3?id=openapi","documentation":"https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-brands"},
    {"id":"france_culture","name":"France Culture","category":"Culture","dial":"INTERNET STREAM","language":"French","url":"https://icecast.radiofrance.fr/franceculture-lofi.mp3?id=openapi","documentation":"https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-brands"},
    {"id":"france_musique","name":"France Musique","category":"Classical","dial":"INTERNET STREAM","language":"French","url":"https://icecast.radiofrance.fr/francemusique-midfi.mp3?id=openapi","documentation":"https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-brands"},
    {"id":"fip","name":"FIP","category":"Music","dial":"INTERNET STREAM","language":"French","url":"https://icecast.radiofrance.fr/fip-midfi.mp3?id=openapi","documentation":"https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-locals-and-webradios"},
    {"id":"fip_rock","name":"FIP Rock","category":"Music","dial":"INTERNET STREAM","language":"French","url":"https://icecast.radiofrance.fr/fiprock-midfi.mp3?id_station=71","documentation":"https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-locals-and-webradios"},
    {"id":"fip_electro","name":"FIP Electro","category":"Music","dial":"INTERNET STREAM","language":"French","url":"https://icecast.radiofrance.fr/fipelectro-midfi.mp3?id=openapi","documentation":"https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-locals-and-webradios"},
    {"id":"fip_metal","name":"FIP Metal","category":"Music","dial":"INTERNET STREAM","language":"French","url":"https://icecast.radiofrance.fr/fipmetal-midfi.mp3?id=openapi","documentation":"https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-locals-and-webradios"},
)
BROADCAST_CATEGORIES = ("All stations", "News & Talk", "Music", "Classical", "Culture")

# The owner tested this public WebSDR on its operator's original HTTP/8901
# endpoint. It is a legacy *unencrypted* service; only this exact origin is
# admitted for private in-app testing after a separate consent prompt. No
# general-purpose HTTP/any-port WebEngine access is enabled.
OWNER_TEST_WEBDR_ORIGIN = "http://na5b.com:8901/"

def _owner_legacy_websdr(info, kind):
    if kind != "websdr":
        return False
    from urllib.parse import urlsplit
    url=urlsplit(str((info or {}).get("url") or ""))
    return (url.scheme == "http" and url.hostname == "na5b.com"
            and url.port == 8901 and not url.username and not url.password)

def _receiver_origin_matches(url, host, scheme, ws_scheme, port, *, main=False):
    """Compare actual URL scheme/host/effective port, not QUrl's caller default.

    QUrl.port(default_port) returns the *supplied* default for absent ports,
    which previously accepted implicit HTTP/80 or WS/80 as though they
    explicitly targeted owner-consented NA5B HTTP/8901. HTTPS/WSS default
    to 443; only the exact reviewed origin is allowed for each protocol.
    """
    actual_scheme = str(url.scheme()).lower()
    if actual_scheme not in ({scheme} if main else {scheme, ws_scheme}):
        return False
    explicit_port = url.port(-1)
    effective_port = (explicit_port if explicit_port != -1 else
                      443 if actual_scheme in {"https", "wss"} else 80)
    return effective_port == port and url.host().lower().rstrip(".") == host


HAM_DIRECTORIES = (
    {"id":"websdr","name":"WebSDR public receivers","url":"http://www.websdr.org/","note":"The provider documents an HTTP-only public directory; no automatic connection."},
    {"id":"kiwisdr","name":"KiwiSDR public receivers","url":"https://kiwisdr.com/public/","note":"Manual ham/shortwave tuning on public receiver pages; provider controls availability."},
)


def station(identifier):
    if not isinstance(identifier, str):
        raise ValueError("Choose a documented radio station")
    selected = next((item for item in STATIONS if item["id"] == identifier), None)
    if selected is None:
        raise ValueError("Station is not in the documented stream catalog")
    return dict(selected)


def valid_presets(value):
    ids = {item["id"] for item in STATIONS}
    rows = value[:5] if isinstance(value, list) else []
    return [(item if isinstance(item, str) and item in ids else None) for item in (rows + [None]*5)[:5]]


class AudioSession(QObject):
    """Owned native decoder; Stop clears source and invalidates late callbacks."""
    changed = Signal(str, str)
    def __init__(self, station_id, parent=None):
        super().__init__(parent)
        self.station = station(station_id)
        self.player = self.output = self.probe = None
        self.active = False
        self.closed = False
        self.frames = 0
        self.buffers = 0
        self.started = self.last_frame = 0.0
        self.state = "OFF"
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(1000)
        self.watchdog.timeout.connect(self._watch)

    def _emit(self, state, detail):
        if state != self.state:
            self.state = state
            self.changed.emit(state, detail)

    def start(self, volume=60, muted=False):
        if self.active or self.closed:
            return False
        from PySide6.QtMultimedia import QAudioOutput, QAudioBufferOutput, QMediaPlayer
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.probe = QAudioBufferOutput(parent=self)
        self.player.setAudioOutput(self.output)
        self.player.setAudioBufferOutput(self.probe)
        self.probe.audioBufferReceived.connect(self._buffer)
        self.player.errorOccurred.connect(self._error)
        self.player.mediaStatusChanged.connect(self._status)
        self.set_volume(volume)
        self.set_muted(muted)
        self.active = True
        self.started = time.monotonic()
        self._emit("CONNECTING", "Opening the broadcaster's direct MP3 stream")
        self.watchdog.start()
        self.player.setSource(QUrl(self.station["url"]))
        self.player.play()
        return True

    def set_volume(self, value):
        if self.output:
            self.output.setVolume(max(0, min(100, int(value))) / 100.0)

    def set_muted(self, value):
        if self.output:
            self.output.setMuted(value is True)

    def _buffer(self, buffer):
        if not self.active or not buffer.isValid() or buffer.frameCount() <= 0:
            return
        self.frames += buffer.frameCount()
        self.buffers += 1
        self.last_frame = time.monotonic()
        # These are decoded frames, not merely an HTTP/page-load callback.
        from PySide6.QtMultimedia import QMediaDevices
        detail = "Direct Internet audio · broadcaster terms apply"
        if QMediaDevices.defaultAudioOutput().isNull():
            detail = "Audio is decoding, but no system audio-output device is available"
        self._emit("PLAYING", detail)

    def _status(self, status):
        if not self.active:
            return
        from PySide6.QtMultimedia import QMediaPlayer
        if status in {QMediaPlayer.MediaStatus.BufferingMedia, QMediaPlayer.MediaStatus.StalledMedia}:
            self._emit("BUFFERING", "Waiting for audio data")
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.fail("The broadcaster ended this stream. Select a station and press Power to reconnect.")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.fail("This stream could not be opened or decoded. No automatic retries are running.")

    def _error(self, *_):
        if self.active:
            # Never copy provider redirect/session URLs or raw native errors to saved UI logs.
            self.fail("Stream unavailable, blocked, or unsupported. No automatic retries are running.")

    def _watch(self):
        if not self.active:
            return
        age = time.monotonic() - (self.last_frame or self.started)
        if age >= 30:
            self.fail("No decoded audio arrived within 30 seconds; the connection was stopped.")
        elif age >= 10:
            self._emit("BUFFERING", "No recent decoded audio; waiting briefly before stopping")

    def fail(self, message):
        self._release()
        self._emit("ERROR", message)

    def _release(self):
        self.active = False
        self.closed = True
        self.watchdog.stop()
        if self.output:
            self.output.setMuted(True)
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())

    def stop(self):
        self._release()
        self._emit("OFF", "Disconnected · event selection cannot turn the radio back on")


class RadioPanel(QWidget):
    """One radio face, one connection, five ID-only presets and explicit power."""
    def __init__(self, parent=None, *, session_factory=None, confirm=None):
        super().__init__(parent)
        self._factory = session_factory or AudioSession
        self._confirm = confirm
        self._session = None
        self._epoch = 0
        self._consented = False
        self._closed = False
        self._setter = None
        self.presets = [None]*5
        self.receiver_view = None
        self.receiver_profile = None
        self.receiver_interceptor = None
        self.receiver_host = ""
        self.receiver_origin = None
        self.receiver_connected = False
        # Read-only, origin-neutral WebEngine failure code for owner diagnosis.
        # Never save page URLs, credentials, contents or player activity.
        self._sdr_load_error = ""
        self.sdr_state = "OFF"
        self.sdr_directory_cache = {}
        self.sdr_directory_reply = None
        self.sdr_directory_data = bytearray()
        self.sdr_network = QNetworkAccessManager(self)
        self.sdr_load_watch = QTimer(self)
        self.sdr_load_watch.setSingleShot(True)
        self.sdr_load_watch.timeout.connect(self._sdr_load_timed_out)
        self.sdr_volume_apply = QTimer(self)
        self.sdr_volume_apply.setSingleShot(True)
        self.sdr_volume_apply.timeout.connect(self._apply_sdr_volume)
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self._scan_next)
        self.scan_frequency = None
        self.scan_end = None
        self.scan_step = None
        self.scan_direction = 1
        self.setObjectName("InternetRadio")
        root = QVBoxLayout(self)
        root.setContentsMargins(8,8,8,8)
        self.radio_tabs = QTabWidget(self)
        self.radio_tabs.setAccessibleName("Choose broadcast radio or HAM SDR tuner")
        broadcast_tab=QWidget(self.radio_tabs)
        ham_tab=QWidget(self.radio_tabs)
        self.radio_tabs.addTab(broadcast_tab,"AM / FM / INTERNET RADIO")
        self.radio_tabs.addTab(ham_tab,"HAM / SDR")
        root.addWidget(self.radio_tabs)
        layout = QVBoxLayout(broadcast_tab)
        layout.setContentsMargins(8,8,8,8)
        title = QLabel("BROADCAST RADIO — DIRECT INTERNET STREAMS")
        title.setObjectName("Eyebrow")
        layout.addWidget(title)
        category_row=QHBoxLayout()
        category_row.addWidget(QLabel("Genre"))
        self.broadcast_category=QComboBox()
        self.broadcast_category.setAccessibleName("Broadcast radio station genre")
        for category in BROADCAST_CATEGORIES:
            self.broadcast_category.addItem(category,category)
        category_row.addWidget(self.broadcast_category,1)
        self.broadcast_count=QLabel(f"{len(STATIONS)} documented streams")
        category_row.addWidget(self.broadcast_count)
        layout.addLayout(category_row)
        tuning = QHBoxLayout()
        self.previous = QPushButton("◀ PREV")
        self.previous.setAccessibleName("Previous radio station")
        self.previous.clicked.connect(lambda:self.select_relative(-1))
        self.selector = QComboBox()
        self.selector.setAccessibleName("Internet radio station")
        self.selector.setMinimumWidth(0)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for item in STATIONS:
            self.selector.addItem(item["name"], item["id"])
        self.broadcast_category.currentIndexChanged.connect(self._category_changed)
        self.next = QPushButton("NEXT ▶")
        self.next.setAccessibleName("Next radio station")
        self.next.clicked.connect(lambda:self.select_relative(1))
        tuning.addWidget(self.previous);tuning.addWidget(self.selector,1);tuning.addWidget(self.next)
        layout.addLayout(tuning)
        self.frequency_display=QLabel()
        self.frequency_display.setTextFormat(Qt.TextFormat.PlainText)
        self.frequency_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frequency_display.setAccessibleName("Exact published AM FM frequency or internet-only stream")
        self.frequency_display.setStyleSheet(
            "font-family:Consolas,monospace;font-size:30px;font-weight:800;padding:8px;background:#101818;"
            "color:#86f5c7;border:1px solid #407b67;border-radius:8px;"
        )
        layout.addWidget(self.frequency_display)
        self.display = QLabel()
        self.display.setTextFormat(Qt.TextFormat.PlainText)
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setWordWrap(True)
        self.display.setMinimumHeight(75)
        self.display.setStyleSheet("font-size:19px;font-weight:600;padding:10px;background:#151619;border:1px solid #494052;border-radius:8px;")
        layout.addWidget(self.display)
        self.status = QLabel("OFF")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAccessibleName("Radio playback state")
        layout.addWidget(self.status)
        self.detail = QLabel("Disconnected · press Power to listen")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.detail)
        controls = QHBoxLayout()
        self.power = QPushButton("Power")
        self.power.setCheckable(True)
        self.power.setAccessibleName("Radio power on or off")
        self.power.toggled.connect(self._power)
        self.mute = QPushButton("Mute")
        self.mute.setCheckable(True)
        self.mute.setAccessibleName("Mute radio audio")
        self.mute.toggled.connect(self._mute)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0,100);self.volume.setValue(60)
        self.volume.setAccessibleName("Radio volume")
        self.volume.valueChanged.connect(self._volume)
        controls.addWidget(self.power);controls.addWidget(self.mute);controls.addWidget(self.volume,1)
        layout.addLayout(controls)
        saved = QHBoxLayout()
        self.preset_buttons=[]
        for index in range(5):
            control=QPushButton(str(index+1))
            control.setAccessibleName(f"Radio preset {index+1}")
            control.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            control.clicked.connect(lambda checked=False,i=index:self.recall_preset(i))
            control.customContextMenuRequested.connect(lambda pos,i=index:self.save_preset(i))
            saved.addWidget(control);self.preset_buttons.append(control)
        layout.addLayout(saved)
        help_text=QLabel("Preset: click to recall, right-click to save. Streams connect directly to their broadcasters; no recording.")
        help_text.setWordWrap(True)
        help_text.setObjectName("Muted")
        layout.addWidget(help_text)
        more_row=QHBoxLayout()
        self.browse_radio=QPushButton("Explore more radio stations")
        self.browse_radio.setAccessibleName("Open community radio directory in browser")
        self.browse_radio.clicked.connect(self._browse_radio_directory)
        more_row.addWidget(self.browse_radio)
        more_row.addStretch()
        layout.addLayout(more_row)
        disclaimer=QLabel(
            "Only publisher-documented HTTPS MP3 streams play inside Pulse. "
            "Some stations have no fixed AM/FM frequency. The external community "
            "directory is for discovery, not a claim of tested playback or reuse rights."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setObjectName("Muted")
        layout.addWidget(disclaimer)
        layout.addStretch(1)

        layout=QVBoxLayout(ham_tab)
        self.ham_layout=layout
        layout.setContentsMargins(8,8,8,8)
        ham_title=QLabel("HAM / SDR RECEIVERS")
        ham_title.setObjectName("Eyebrow")
        layout.addWidget(ham_title)
        self.ham_receiver_name=QLabel("Choose a public receiver")
        self.ham_receiver_name.setTextFormat(Qt.TextFormat.PlainText)
        self.ham_receiver_name.setWordWrap(True)
        self.ham_receiver_name.setStyleSheet("font-size:17px;font-weight:700;color:#b9e8ee;")
        layout.addWidget(self.ham_receiver_name)
        self.ham_frequency_display=QLabel("7.100 MHz")
        self.ham_frequency_display.setAccessibleName("Pulse requested HAM frequency and mode, not verified on operator")
        self.ham_frequency_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ham_frequency_display.setTextFormat(Qt.TextFormat.PlainText)
        self.ham_frequency_display.setStyleSheet(
            "font-family:Consolas,monospace;font-size:34px;font-weight:800;color:#86f5c7;background:#101818;"
            "padding:10px;border:1px solid #407b67;border-radius:8px;"
        )
        layout.addWidget(self.ham_frequency_display)
        self.ham_frequency_detail=QLabel("7100 kHz · USB · Pulse requested setting")
        self.ham_frequency_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ham_frequency_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.ham_frequency_detail.setWordWrap(True)
        self.ham_frequency_detail.setAccessibleName("Exact requested kilohertz and mode; operator playback unverified")
        layout.addWidget(self.ham_frequency_detail)
        self.ham_bands=QLabel(
            "Available bands: choose a receiver. Only operator-supplied bands are shown."
        )
        self.ham_bands.setTextFormat(Qt.TextFormat.PlainText)
        self.ham_bands.setWordWrap(True)
        self.ham_bands.setAccessibleName("Bands reported for selected SDR receiver")
        layout.addWidget(self.ham_bands)
        ham_row=QHBoxLayout()
        self.ham_selector=QComboBox()
        self.ham_selector.setAccessibleName("Public ham and SDR receiver directory")
        for item in HAM_DIRECTORIES:
            self.ham_selector.addItem(item["name"],dict(item))
        self.ham_open=QPushButton("Open directory")
        self.ham_open.setAccessibleName("Open selected public ham receiver directory")
        self.ham_open.clicked.connect(self.open_ham_directory)
        ham_row.addWidget(self.ham_selector,1);ham_row.addWidget(self.ham_open)
        layout.addLayout(ham_row)

        discovery_row=QHBoxLayout()
        self.receiver_picker=QComboBox()
        self.receiver_picker.setAccessibleName("Discovered public SDR receiver")
        self.receiver_picker.setMinimumWidth(0)
        self.receiver_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.receiver_picker.setEditable(True)
        self.receiver_picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.receiver_picker.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.receiver_picker.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.receiver_picker.addItem("Select a receiver — Refresh list",None)
        self.receiver_picker.currentIndexChanged.connect(self._select_discovered_receiver)
        self.receiver_refresh=QPushButton("Refresh list")
        self.receiver_refresh.clicked.connect(self.refresh_receiver_directory)
        self.receiver_external=QPushButton("Open receiver in browser")
        self.receiver_external.clicked.connect(self.open_selected_receiver)
        self.receiver_external.setEnabled(False)
        discovery_row.addWidget(self.receiver_picker,1)
        discovery_row.addWidget(self.receiver_refresh)
        discovery_row.addWidget(self.receiver_external)
        layout.addLayout(discovery_row)
        self.receiver_list_note=QLabel(
            "No list loaded. Refresh retrieves public directory links on request; receiver status is unverified."
        )
        self.receiver_list_note.setWordWrap(True)
        self.receiver_list_note.setObjectName("Muted")
        layout.addWidget(self.receiver_list_note)
        self.ham_selector.currentIndexChanged.connect(self._change_receiver_directory)

        receiver_row=QHBoxLayout()
        self.receiver_url=QLineEdit()
        self.receiver_url.setPlaceholderText("Specific public HTTPS WebSDR/KiwiSDR receiver URL")
        self.receiver_url.setAccessibleName("Specific public SDR receiver URL")
        self.receiver_connect=QPushButton("Connect in Pulse")
        self.receiver_connect.setAccessibleName("Connect selected public SDR receiver inside Global Pulse")
        self.receiver_connect.clicked.connect(self.connect_receiver)
        self.receiver_connect.setEnabled(False)
        self.receiver_url.textChanged.connect(self._receiver_url_changed)
        self.receiver_off=QPushButton("Receiver Off")
        self.receiver_off.setAccessibleName("Disconnect in-app public SDR receiver")
        self.receiver_off.clicked.connect(self.disconnect_receiver)
        receiver_row.addWidget(self.receiver_url,1)
        receiver_row.addWidget(self.receiver_connect)
        receiver_row.addWidget(self.receiver_off)
        layout.addLayout(receiver_row)
        legacy_row=QHBoxLayout()
        self.na5b_test=QPushButton("Test NA5B WebSDR (HTTP/8901)")
        self.na5b_test.setAccessibleName(
            "Select official NA5B public WebSDR on its HTTP port 8901"
        )
        self.na5b_test.clicked.connect(self._select_na5b_test)
        legacy_row.addWidget(self.na5b_test)
        legacy_row.addStretch()
        layout.addLayout(legacy_row)
        self.sdr_status=QLabel("● OFF — No receiver connected")
        self.sdr_status.setTextFormat(Qt.TextFormat.PlainText)
        self.sdr_status.setAccessibleName("HAM SDR connection status")
        self.sdr_status.setStyleSheet("color:#b9c0cc;font-weight:700;")
        layout.addWidget(self.sdr_status)
        audio_row=QHBoxLayout()
        self.sdr_mute=QPushButton("Mute SDR")
        self.sdr_mute.setCheckable(True)
        self.sdr_mute.setEnabled(False)
        self.sdr_mute.setAccessibleName("Mute HAM SDR receiver only")
        self.sdr_mute.toggled.connect(self._sdr_mute_changed)
        self.sdr_volume=QSlider(Qt.Orientation.Horizontal)
        self.sdr_volume.setRange(0,100)
        self.sdr_volume.setValue(40)
        self.sdr_volume.setEnabled(False)
        self.sdr_volume.setAccessibleName("HAM SDR volume for KiwiSDR receivers")
        self.sdr_volume.valueChanged.connect(self._sdr_volume_changed)
        self.sdr_volume.sliderReleased.connect(self._apply_sdr_volume)
        self.sdr_volume_value=QLabel("40%")
        self.sdr_volume_help=QLabel("Kiwi volume reloads receiver; WebSDR uses its own volume slider")
        self.sdr_volume_help.setWordWrap(True)
        self.sdr_volume_help.setObjectName("Muted")
        audio_row.addWidget(self.sdr_mute)
        audio_row.addWidget(QLabel("SDR volume"))
        audio_row.addWidget(self.sdr_volume,1)
        audio_row.addWidget(self.sdr_volume_value)
        layout.addLayout(audio_row)
        layout.addWidget(self.sdr_volume_help)

        tuner_row=QHBoxLayout()
        self.receiver_type=QComboBox()
        self.receiver_type.addItem("KiwiSDR","kiwi")
        self.receiver_type.addItem("WebSDR","websdr")
        self.receiver_type.setAccessibleName("SDR receiver type")
        self.receiver_type.currentIndexChanged.connect(
            lambda _index: self._receiver_url_changed(self.receiver_url.text())
        )
        self.frequency=QLineEdit("7100")
        self.frequency.setPlaceholderText("Frequency kHz")
        self.frequency.setAccessibleName("SDR frequency in kilohertz")
        self.mode=QComboBox()
        for label,value in (("USB","usb"),("LSB","lsb"),("AM","am"),("CW","cw")):
            self.mode.addItem(label,value)
        self.tune_button=QPushButton("Tune")
        self.tune_button.clicked.connect(self._manual_tune)
        self.frequency.textChanged.connect(lambda _value:self._update_ham_dial())
        self.mode.currentIndexChanged.connect(lambda _index:self._update_ham_dial())
        tuner_row.addWidget(self.receiver_type)
        tuner_row.addWidget(QLabel("kHz"))
        tuner_row.addWidget(self.frequency,1)
        tuner_row.addWidget(self.mode)
        tuner_row.addWidget(self.tune_button)
        layout.addLayout(tuner_row)
        stepping=QHBoxLayout()
        self.ham_back=QPushButton("◀ LOWER")
        self.ham_back.setAccessibleName("Tune lower by selected kilohertz step")
        self.ham_back.clicked.connect(lambda:self.step_receiver(-1))
        self.ham_step=QComboBox()
        self.ham_step.setAccessibleName("HAM tuning increment in kilohertz")
        for step in (1,5,10,25,100):
            self.ham_step.addItem(f"{step} kHz step",step)
        self.ham_step.setCurrentIndex(1)
        self.ham_forward=QPushButton("HIGHER ▶")
        self.ham_forward.setAccessibleName("Tune higher by selected kilohertz step")
        self.ham_forward.clicked.connect(lambda:self.step_receiver(1))
        stepping.addWidget(self.ham_back)
        stepping.addWidget(self.ham_step,1)
        stepping.addWidget(self.ham_forward)
        layout.addLayout(stepping)

        scan_row=QHBoxLayout()
        self.scan_start=QLineEdit("7000")
        self.scan_end_edit=QLineEdit("7300")
        self.scan_step_edit=QLineEdit("5")
        self.scan_dwell=QLineEdit("3")
        for widget,name in (
            (self.scan_start,"Scan start kHz"),(self.scan_end_edit,"Scan end kHz"),
            (self.scan_step_edit,"Scan step kHz"),(self.scan_dwell,"Scan dwell seconds")
        ):
            widget.setAccessibleName(name)
        self.scan_button=QPushButton("Scan frequencies")
        self.scan_button.clicked.connect(self.start_scan)
        self.scan_stop=QPushButton("Stop scan")
        self.scan_stop.clicked.connect(self.stop_scan)
        scan_row.addWidget(QLabel("Start"));scan_row.addWidget(self.scan_start)
        scan_row.addWidget(QLabel("End"));scan_row.addWidget(self.scan_end_edit)
        scan_row.addWidget(QLabel("Step"));scan_row.addWidget(self.scan_step_edit)
        scan_row.addWidget(QLabel("Dwell s"));scan_row.addWidget(self.scan_dwell)
        scan_row.addWidget(self.scan_button);scan_row.addWidget(self.scan_stop)
        self.scan_controls=QWidget(ham_tab)
        self.scan_controls.setLayout(scan_row)
        self.scan_controls.hide()
        self.advanced_scan=QPushButton("Advanced frequency scan ▸")
        self.advanced_scan.setCheckable(True)
        self.advanced_scan.setAccessibleName("Show or hide advanced HAM frequency scan")
        self.advanced_scan.toggled.connect(self._advanced_scan_toggled)
        layout.addWidget(self.advanced_scan)
        layout.addWidget(self.scan_controls)

        self.ham_note=QLabel(
            "Receiver screen/waterfall is the public provider's own embedded UI. Tune sets the receiver URL frequency/mode. "
            "Scan is bounded frequency stepping, not automatic signal detection. No transmit, recording, downloads, popups, "
            "permissions or cross-host navigation."
        )
        self.ham_note.setWordWrap(True);self.ham_note.setObjectName("Muted")
        layout.addWidget(self.ham_note)

        self.selector.currentIndexChanged.connect(self._station_changed)
        self._station_changed()
        self._preset_labels()
        self._update_ham_dial()
        self._change_receiver_directory()

    def configure_preferences(self, getter, setter):
        self._setter = setter
        self.presets = valid_presets(getter("internet_radio_presets_v1",[None]*5))
        self._preset_labels()
        # Legacy receiver/frequency presets are deliberately not overwritten.

    def _category_changed(self, *_):
        """Filter only our publisher-documented streams; never auto-fetch media."""
        category=self.broadcast_category.currentData()
        selected=self.selector.currentData()
        matches=[s for s in STATIONS if category=="All stations" or s["category"]==category]
        self.selector.blockSignals(True)
        try:
            self.selector.clear()
            for item in matches:
                self.selector.addItem(item["name"],item["id"])
            index=self.selector.findData(selected)
            if index>=0:
                self.selector.setCurrentIndex(index)
        finally:
            self.selector.blockSignals(False)
        self.broadcast_count.setText(f"{len(matches)} documented streams")
        if matches:
            self._station_changed()

    def _browse_radio_directory(self):
        """Unvetted community links remain in the user's external browser."""
        if self._closed:
            return False
        approved=QMessageBox.question(
            self,"Explore additional radio stations?",
            "Open the public Radio Browser community directory in your default "
            "browser? Its catalog is not vetted for safe in-app playback, "
            "publisher redistribution rights or actual availability. Continue?",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )==QMessageBox.StandardButton.Yes
        return bool(approved and QDesktopServices.openUrl(
            QUrl("https://www.radio-browser.info/")
        ))

    def _advanced_scan_toggled(self, shown):
        self.scan_controls.setVisible(bool(shown))
        self.advanced_scan.setText(
            "Advanced frequency scan ▾" if shown else
            "Advanced frequency scan ▸"
        )

    def _update_ham_dial(self):
        """Display the exact requested frequency, never assert RF/audio lock."""
        try:
            khz=self._frequency_value(self.frequency.text())
            display=f"{khz / 1000:.9f}"
            integral,fraction=display.split(".")
            fraction=fraction.rstrip("0").ljust(3,"0")
            self.ham_frequency_display.setText(f"{integral}.{fraction} MHz")
            self.ham_frequency_detail.setText(
                f"{self._format_khz(khz)} kHz · {self.mode.currentText()} · "
                "Pulse requested setting; receiver audio unverified"
            )
        except (ValueError,TypeError):
            self.ham_frequency_display.setText("— MHz")
            self.ham_frequency_detail.setText(
                "Enter a valid requested frequency in kHz"
            )

    def step_receiver(self, direction):
        """Real button-driven tuning, bounded to valid user-requested kHz."""
        if direction not in (-1,1) or self._closed:
            return False
        try:
            previous=self._frequency_value(self.frequency.text())
            delta=int(self.ham_step.currentData())*direction
            target=self._frequency_value(round(previous+delta,6))
        except (ValueError,TypeError,OverflowError):
            self.ham_note.setText("Frequency step is outside the supported dial range.")
            return False
        self.stop_scan()
        return self.tune_receiver(target)

    def _selected_receiver_bands(self, receiver=None):
        info=receiver if isinstance(receiver,dict) else {}
        bands=info.get("bands")
        if isinstance(bands,list):
            labels=[str(item)[:30] for item in bands[:24]
                    if isinstance(item,str) and item.strip()]
        else:
            labels=[]
        if labels:
            self.ham_bands.setText(
                "Operator-listed bands: "+" · ".join(labels)
                +". Exact bounds/availability are not live verified."
            )
        elif self.receiver_url.text().startswith(OWNER_TEST_WEBDR_ORIGIN):
            # Only the labels visibly reported by the owner's NA5B screenshot.
            # Never infer MHz limits, availability or a universal band plan.
            self.ham_bands.setText(
                "NA5B band labels seen on owner's receiver page: "
                "MW–160 · 80m · 40m · 30m · 25m · 20m · 15m · 10m. "
                "Operator controls exact coverage."
            )
        else:
            self.ham_bands.setText(
                "Receiver band list unavailable from this directory entry. "
                "Use the operator's receiver page to see actual coverage."
            )

    def _preset_labels(self):
        for i,control in enumerate(self.preset_buttons):
            identifier=self.presets[i]
            control.setText(str(i+1)+(" ★" if identifier else ""))
            control.setToolTip((station(identifier)["name"] if identifier else "Empty preset")+" · right-click to save")

    def save_preset(self, index):
        if type(index) is not int or not 0<=index<5:
            return False
        updated=list(self.presets);updated[index]=self.selector.currentData()
        try:
            if callable(self._setter):self._setter("internet_radio_presets_v1",updated)
        except (ValueError,RuntimeError,OSError):
            self.detail.setText("Preset was not saved. Your previous presets are unchanged.")
            return False
        self.presets=updated;self._preset_labels();return True

    def recall_preset(self,index):
        if type(index) is not int or not 0<=index<5 or not self.presets[index]:return False
        selected=self.selector.findData(self.presets[index])
        if selected<0:
            # A saved station may be hidden by the current genre filter.
            # Restore the full documented catalog before recalling it.
            self.broadcast_category.setCurrentIndex(0)
            selected=self.selector.findData(self.presets[index])
        if selected<0:return False
        self.selector.setCurrentIndex(selected)
        return True

    def select_relative(self,step):
        if self.selector.count():
            self.selector.setCurrentIndex(
                (self.selector.currentIndex()+(-1 if step<0 else 1))%self.selector.count()
            )

    def _sdr_state_change(self, state, message=""):
        """Visual state reflects the receiver page load, never the Connect click."""
        self.sdr_state = state
        labels = {"OFF": "● OFF — SDR receiver disconnected",
                  "CONNECTING": "◌ CONNECTING — loading receiver",
                  "ON": "● ON — SDR receiver page loaded",
                  "ERROR": "● ERROR — SDR receiver unavailable"}
        colors = {"OFF": "#aeb7c5", "CONNECTING": "#f0bd72",
                  "ON": "#6fedaa", "ERROR": "#ff929f"}
        self.sdr_status.setText(labels.get(state, state))
        self.sdr_status.setStyleSheet(
            "color:" + colors.get(state, "#aeb7c5") + ";font-weight:700;"
        )
        self.sdr_mute.setEnabled(state == "ON")
        self.sdr_volume.setEnabled(
            state == "ON" and self.receiver_type.currentData() == "kiwi"
        )
        if message:
            self.ham_note.setText(message)

    def _select_na5b_test(self):
        """Select known owner-supplied public receiver; never auto-connect."""
        self.receiver_type.setCurrentIndex(
            self.receiver_type.findData("websdr")
        )
        self.receiver_url.setText(OWNER_TEST_WEBDR_ORIGIN)
        self.ham_receiver_name.setText("NA5B · WebSDR public receiver")
        self._selected_receiver_bands()
        self.receiver_list_note.setText(
            "NA5B selected: public operator HTTP/8901 WebSDR. "
            "Connection is unencrypted and will require explicit consent; "
            "its in-app compatibility and audio remain unverified."
        )
        return True

    def _receiver_url_changed(self, text):
        try:
            item = public_receiver_url(str(text).strip())
        except ValueError:
            self.receiver_connect.setEnabled(False)
            self.receiver_external.setEnabled(False)
            self.ham_receiver_name.setText("Enter a public receiver URL")
            self._selected_receiver_bands()
            return
        if item["url"].startswith(OWNER_TEST_WEBDR_ORIGIN):
            self.ham_receiver_name.setText("NA5B · WebSDR public receiver")
        else:
            self.ham_receiver_name.setText("Selected receiver · "+item["host"])
        self._selected_receiver_bands()
        legacy = _owner_legacy_websdr(item, self.receiver_type.currentData())
        self.receiver_connect.setEnabled(item["embedded_candidate"] or legacy)
        self.receiver_external.setEnabled(True)
        if legacy:
            self.receiver_list_note.setText(
                "NA5B operator HTTP/8901 test: an unencrypted in-app "
                "connection is available after explicit consent. "
                "Use the receiver's own Audio start control."
            )
        elif not item["embedded_candidate"]:
            self.receiver_list_note.setText(
                "Browser-only receiver (HTTP/custom port). "
                "Only the explicitly reviewed NA5B legacy origin is admitted "
                "for in-app HTTP tests. Open other receivers in your browser."
            )

    def _change_receiver_directory(self, *_):
        item = self.ham_selector.currentData() or {}
        provider = item.get("id", "")
        cached = list(self.sdr_directory_cache.get(provider, []))
        if provider == "websdr":
            # The owner-tested fallback is known by exact identity, not a
            # claim that the official directory fetched or that audio is live.
            pinned=dict(public_receiver_url(OWNER_TEST_WEBDR_ORIGIN))
            pinned.update(name="NA5B · owner-tested link",provider="websdr")
            cached=[pinned]+[r for r in cached if r["url"]!=pinned["url"]]
        self.receiver_picker.blockSignals(True)
        self.receiver_picker.clear()
        self.receiver_picker.addItem("Choose receiver — or enter URL manually", None)
        for row in cached:
            self.receiver_picker.addItem(row["name"] + " — " + row["host"], dict(row))
        self.receiver_picker.blockSignals(False)
        if self.sdr_directory_cache.get(provider):
            self.receiver_list_note.setText(
                f"{len(cached)} public receiver choices, including any pinned owner-test link. "
                "Directory labels are unverified until the operator is opened."
            )
        else:
            self.receiver_list_note.setText(
                "No live directory loaded. Refresh requests the selected public "
                "operator directory; WebSDR's documented endpoint uses unencrypted HTTP. "
                "The NA5B owner-test link remains selectable when that site is down."
            )

    def _select_discovered_receiver(self, *_):
        item = self.receiver_picker.currentData()
        if not isinstance(item, dict):
            return
        self.receiver_url.setText(item["url"])
        index = self.receiver_type.findData(
            "websdr" if item["provider"] == "websdr" else "kiwi"
        )
        if index >= 0:
            self.receiver_type.setCurrentIndex(index)
        self.ham_receiver_name.setText(item["name"])
        self._selected_receiver_bands(item)
        self.receiver_list_note.setText(
            f"{item['name']} — {item['reason']}. The directory does not verify availability."
        )

    def refresh_receiver_directory(self):
        """One bounded, on-demand request to an official directory, never receivers."""
        if self._closed or self.sdr_directory_reply is not None:
            return False
        item = self.ham_selector.currentData() or {}
        provider = item.get("id")
        url = DIRECTORY_URLS.get(provider)
        if not url:
            return False
        if provider == "websdr":
            approved=QMessageBox.question(
                self,"Refresh WebSDR directory over HTTP?",
                "The WebSDR operator documents an unencrypted HTTP directory. "
                "Network intermediaries could change the list. Pulse validates "
                "each public candidate and does not auto-connect. Continue?",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
            if not approved:
                return False
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
        )
        request.setTransferTimeout(12000)
        self.sdr_directory_data = bytearray()
        self.receiver_refresh.setEnabled(False)
        self.ham_selector.setEnabled(False)
        self.receiver_list_note.setText(
            "Loading public receiver directory — this sends a request to the directory operator…"
        )
        reply = self.sdr_network.get(request)
        self.sdr_directory_reply = reply
        reply.readyRead.connect(lambda r=reply: self._sdr_directory_chunk(r))
        reply.finished.connect(
            lambda p=provider, r=reply: self._sdr_directory_finished(p, r)
        )
        return True

    def _sdr_directory_chunk(self, reply):
        if reply is not self.sdr_directory_reply:
            return
        incoming = bytes(reply.readAll())
        if len(self.sdr_directory_data) + len(incoming) > MAX_DIRECTORY_BYTES:
            self.sdr_directory_data = bytearray()
            reply.abort()
            return
        self.sdr_directory_data.extend(incoming)

    def _sdr_directory_finished(self, provider, reply):
        if reply is not self.sdr_directory_reply:
            reply.deleteLater()
            return
        self._sdr_directory_chunk(reply)
        self.sdr_directory_reply = None
        self.receiver_refresh.setEnabled(not self._closed)
        self.ham_selector.setEnabled(not self._closed)
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = reply.error()
        reply.deleteLater()
        if self._closed:
            return
        if error != QNetworkReply.NetworkError.NoError or status != 200:
            self.receiver_list_note.setText(
                "Directory unavailable/redirected or too large. Use Open directory to choose manually."
            )
            return
        try:
            rows = parse_directory(provider, bytes(self.sdr_directory_data))
        except (ValueError, TypeError):
            rows = []
        if not rows:
            self.receiver_list_note.setText(
                "No validated public receiver links found; directory format or access may have changed."
            )
            return
        self.sdr_directory_cache[provider] = rows
        self._change_receiver_directory()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.receiver_list_note.setText(
            f"{len(rows)} receiver links listed at {stamp}; connectivity is unverified."
        )

    def open_selected_receiver(self):
        raw = self.receiver_url.text().strip()
        try:
            info = public_receiver_url(raw)
        except ValueError:
            self.receiver_list_note.setText("Select or paste a valid public receiver URL first.")
            return False
        approved = QMessageBox.question(
            self, "Open public receiver in browser?",
            "Open the selected public receiver in your default browser? "
            "The receiver receives your IP address and browser requests. "
            "Follow that operator's access rules. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes
        if not approved:
            return False
        result = QDesktopServices.openUrl(QUrl(info["url"]))
        self.receiver_list_note.setText(
            "Opened receiver in external browser." if result else "Receiver browser could not be opened."
        )
        return bool(result)

    def _sdr_loading_changed(self, info):
        """Record the bounded *main-page* Chromium load failure only.

        Page-load failure does not establish a network ban, audio incompatibility
        or operator outage. Do not report paths or raw error strings; they may
        include user-supplied query parameters or other private information.
        """
        if self._closed or not self.receiver_connected or self.sdr_state != "CONNECTING":
            return
        from PySide6.QtWebEngineCore import QWebEngineLoadingInfo
        if info.status() != QWebEngineLoadingInfo.LoadStatus.LoadFailedStatus:
            return
        # Keep the error-domain/code receipt finite, without user-entered URLs.
        domain = getattr(info.errorDomain(), "name", "UnknownErrorDomain")
        domain = "".join(c for c in str(domain) if c.isalnum())[:40]
        self._sdr_load_error = f"{domain or 'UnknownErrorDomain'} code {int(info.errorCode())}"

    def _sdr_load_finished(self, ok):
        if self._closed or not self.receiver_connected or self.sdr_state != "CONNECTING":
            return
        sender = self.sender()
        if sender is not None and sender is not self.receiver_view:
            return
        self.sdr_load_watch.stop()
        if not ok:
            reason = self._sdr_load_error
            self._destroy_receiver()
            self._sdr_state_change(
                "ERROR", "Receiver page failed to load"
                + (f" ({reason})" if reason else "")
                + ". Check the receiver in a normal browser; port 8901,"
                " provider availability and network restrictions may differ."
            )
            return
        self._sdr_state_change(
            "ON",
            "Receiver WEB PAGE loaded; audio and signal have NOT been verified. "
            "Press Audio start/Play in the operator's interface. "
            "If the waterfall or audio doesn't work, use Open receiver in browser."
        )
        if self.receiver_view:
            self.receiver_view.page().setAudioMuted(self.sdr_mute.isChecked())

    def _sdr_load_timed_out(self):
        if self.sdr_state == "CONNECTING":
            self._destroy_receiver()
            self._sdr_state_change(
                "ERROR", "Receiver page timed out. Try the external browser or another public receiver."
            )

    def _sdr_mute_changed(self, muted):
        self.sdr_mute.setText("Unmute SDR" if muted else "Mute SDR")
        if self.receiver_view is not None:
            self.receiver_view.page().setAudioMuted(bool(muted))

    def _sdr_volume_changed(self, value):
        self.sdr_volume_value.setText(f"{value}%")
        if self.sdr_state == "ON" and self.receiver_type.currentData() == "kiwi":
            self.sdr_volume_apply.start(600)

    def _apply_sdr_volume(self):
        """KiwiSDR documents vol= URL control; reload once after slider settles."""
        self.sdr_volume_apply.stop()
        if self.sdr_state != "ON" or self.receiver_type.currentData() != "kiwi":
            return
        try:
            url, host = self._tuned_receiver_url()
            if host == self.receiver_host:
                self._load_receiver_url(url, host)
                self.ham_note.setText(
                    "Applying KiwiSDR volume by reloading receiver; audio may need Play again."
                )
        except (ImportError, RuntimeError, ValueError, OSError) as exc:
            self.ham_note.setText("Volume could not be applied: " + str(exc)[:100])

    def open_ham_directory(self):
        item=self.ham_selector.currentData() or {}
        url=str(item.get("url",""))
        if url not in {entry["url"] for entry in HAM_DIRECTORIES}:
            self.ham_note.setText("Receiver directory is not in the reviewed list.")
            return False
        transport_warning = (
            "This WebSDR directory uses unencrypted HTTP. Network intermediaries "
            "may read or alter its page. "
            if url.startswith("http://") else "This directory uses HTTPS. "
        )
        approved=QMessageBox.question(
            self,"Open public ham receiver directory?",
            transport_warning
            + "Open the selected public WebSDR/KiwiSDR directory in your browser to choose a receiver? "
            "The directory provider receives your IP address. Copy one specific public HTTPS receiver URL back into Pulse "
            "to use the in-app receiver. Global Pulse does not record, retransmit, or bypass access controls.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )==QMessageBox.StandardButton.Yes
        if not approved:
            return False
        opened=QDesktopServices.openUrl(QUrl(url))
        self.ham_note.setText(
            item.get("note","Public receiver directory opened.")
            + (" Copy a specific HTTPS receiver URL into the in-app field." if opened else " Directory could not be opened.")
        )
        return bool(opened)

    def _receiver_target(self):
        item=public_receiver_url(self.receiver_url.text().strip())
        value=item["url"]
        parsed=urlsplit(value)
        host=item["host"]
        legacy=_owner_legacy_websdr(item,self.receiver_type.currentData())
        if not item["embedded_candidate"] and not legacy:
            raise ValueError(
                "In-app SDR requires public HTTPS/443, except explicit "
                "owner-test NA5B HTTP/8901 with WebSDR selected"
            )
        return value,host

    @staticmethod
    def _frequency_value(value):
        try:
            number=float(str(value).strip())
        except (TypeError,ValueError):
            raise ValueError("Frequency must be a number in kHz")
        if not (0.1 <= number <= 500000):
            raise ValueError("Frequency must be between 0.1 and 500000 kHz")
        return number

    @staticmethod
    def _format_khz(value):
        """Preserve fine manual tuning instead of the six-significant-digit g default."""
        return f"{value:.6f}".rstrip("0").rstrip(".")

    def _tuned_receiver_url(self,frequency=None,mode=None):
        base,host=self._receiver_target()
        frequency=self._frequency_value(self.frequency.text() if frequency is None else frequency)
        mode=str(mode or self.mode.currentData() or "usb").lower()
        if mode not in {"usb","lsb","am","cw"}:
            raise ValueError("Unsupported SDR mode")
        parsed=urlsplit(base)
        params=dict(parse_qsl(parsed.query,keep_blank_values=True))
        if self.receiver_type.currentData()=="websdr":
            params["tune"]=f"{self._format_khz(frequency)}{mode}"
            params.pop("f",None)
        else:
            params["f"]=f"{self._format_khz(frequency)}{mode}"
            params["vol"]=str(self.sdr_volume.value())
            params.pop("tune",None)
        return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urlencode(params),parsed.fragment)),host

    def _load_receiver_url(self,url,host, *, require_consent=False):
        if require_consent:
            info=public_receiver_url(url)
            legacy=_owner_legacy_websdr(info,self.receiver_type.currentData())
            warning=(
                " WARNING: NA5B uses unencrypted HTTP on port 8901; "
                "other network parties can observe and alter the receiver page. "
                "Use only this public operator origin, not sensitive credentials."
                if legacy else ""
            )
            approved=QMessageBox.question(
                self,"Connect public SDR inside Pulse?",
                "Load this exact public receiver host inside Global Pulse? "
                "The operator receives your IP address and browser requests. "
                "Pulse uses an ephemeral browser profile and denies downloads, "
                "popups, permissions and cross-host navigation. "
                "Provider audio must be started manually." + warning +
                " Continue?",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )==QMessageBox.StandardButton.Yes
            if not approved:
                return False
        self._ensure_receiver_view(host)
        self._sdr_load_error = ""
        self._sdr_state_change("CONNECTING", "Connecting to public SDR receiver…")
        self.sdr_load_watch.start(20000)
        self.receiver_connected=True
        self.receiver_view.load(QUrl(url))
        self.receiver_view.show()
        return True

    def _manual_tune(self):
        """A Qt clicked(bool) is not an SDR frequency; manual Tune owns the scan."""
        self.stop_scan()
        return self.tune_receiver()

    def tune_receiver(self,frequency=None):
        if self._closed:
            return False
        try:
            url,host=self._tuned_receiver_url(frequency)
            if not self.receiver_connected:
                if not self._load_receiver_url(url,host,require_consent=True):
                    return False
            else:
                parts=urlsplit(url)
                origin=(parts.scheme,parts.port or 443,host)
                if host != self.receiver_host or origin != self.receiver_origin:
                    self._destroy_receiver()
                    if not self._load_receiver_url(url,host,require_consent=True):
                        return False
                else:
                    # A same-origin Tune is still a new asynchronous page load.
                    # Route it through the same pending/error/timeout lifecycle as
                    # initial Connect, rather than leaving ON while a fresh
                    # receiver navigation may fail silently.
                    if not self._load_receiver_url(url, host):
                        return False
            value=self._frequency_value(self.frequency.text() if frequency is None else frequency)
            self.frequency.setText(self._format_khz(value))
            self.ham_note.setText(
                f"SDR TUNING · {self._format_khz(value)} kHz {str(self.mode.currentText())} · "
                "receiver page and audio not yet verified; Off ends the session"
            )
            return True
        except (ImportError,RuntimeError,ValueError,OSError) as error:
            self.stop_scan()
            self.ham_note.setText(str(error)[:180] or "The SDR receiver could not tune.")
            return False

    def start_scan(self):
        try:
            start=self._frequency_value(self.scan_start.text())
            end=self._frequency_value(self.scan_end_edit.text())
            step=self._frequency_value(self.scan_step_edit.text())
            dwell=float(self.scan_dwell.text().strip())
            if not 1 <= dwell <= 60:
                raise ValueError("Scan dwell must be between 1 and 60 seconds")
            span=abs(end-start)
            count=int(span/step)+1
            if count > 2000:
                raise ValueError("Scan range is too large; use a larger step")
        except (TypeError,ValueError) as error:
            self.ham_note.setText(str(error))
            return False
        self.stop_scan()
        self.scan_frequency=start
        self.scan_end=end
        self.scan_step=step
        self.scan_direction=1 if end>=start else -1
        self.scan_timer.setInterval(max(1000,int(dwell*1000)))
        if not self.tune_receiver(start):
            self.scan_frequency=None
            return False
        self.scan_timer.start()
        self.ham_note.setText(
            f"SDR SCAN PENDING · {start:g} to {end:g} kHz · step {step:g} · dwell {dwell:g}s · "
            "waiting for the receiver page; audio and signal are not verified"
        )
        return True

    def _scan_next(self):
        if self.scan_frequency is None or self.scan_end is None or self.scan_step is None:
            self.stop_scan();return
        # A page load may exceed the user-selected dwell interval. Do not
        # interrupt a pending tune with another Chromium navigation: canceled
        # requests can report a failure and obscure the new tune's receipt.
        # Hold the frequency until the page finishes or its watchdog fails.
        if self.sdr_state == "CONNECTING":
            return
        if self.sdr_state != "ON" or not self.receiver_connected:
            self.stop_scan()
            return
        value=self.scan_frequency+self.scan_direction*self.scan_step
        if ((self.scan_direction>0 and value>self.scan_end+1e-9)
                or (self.scan_direction<0 and value<self.scan_end-1e-9)):
            self.stop_scan()
            self.ham_note.setText("SDR SCAN COMPLETE · receiver remains on the last frequency")
            return
        self.scan_frequency=value
        if not self.tune_receiver(value):
            self.stop_scan()

    def stop_scan(self):
        self.scan_timer.stop()
        self.scan_frequency=self.scan_end=self.scan_step=None
        return True

    def connect_receiver(self):
        if self._closed:
            return False
        try:
            url,host=self._tuned_receiver_url()
            if not self._load_receiver_url(url,host,require_consent=True):
                return False
            self.ham_note.setText(
                "SDR CONNECTING · waiting for operator page. "
                "Waterfall and audio are not verified; use receiver Audio start after load."
            )
            return True
        except (ImportError,RuntimeError,ValueError,OSError) as error:
            self._destroy_receiver()
            self._sdr_state_change("ERROR", str(error)[:180] or "The in-app SDR receiver could not start.")
            return False

    def _ensure_receiver_view(self,host):
        if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX","").lower() not in {"","0","false"} or "--no-sandbox" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS",""):
            raise RuntimeError("The embedded receiver requires Chromium sandboxing")
        if hasattr(os,"geteuid") and os.geteuid()==0:
            raise RuntimeError("The embedded receiver requires a standard user session")
        target, _ = self._receiver_target()
        origin_parts = urlsplit(target)
        origin = (origin_parts.scheme, origin_parts.port or 443, host)
        if (self.receiver_view is not None and
                self.receiver_host==host and self.receiver_origin==origin):
            return

        self._destroy_receiver()
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage,QWebEngineUrlRequestInterceptor,QWebEngineSettings

        # Bind the embedded session to exactly one reviewed scheme+host+port.
        # HTTP custom ports are NOT generally admitted: only NA5B:8901,
        # prevalidated above by _receiver_target.
        target, _ = self._receiver_target()
        parsed=urlsplit(target)
        legacy=(parsed.scheme=="http")
        allowed_scheme="http" if legacy else "https"
        allowed_ws_scheme="ws" if legacy else "wss"
        allowed_port=parsed.port or 443

        class ReceiverInterceptor(QWebEngineUrlRequestInterceptor):
            def __init__(self,allowed_host,scheme,ws_scheme,port,parent=None):
                super().__init__(parent)
                self.allowed_host=allowed_host
                self.scheme=scheme
                self.ws_scheme=ws_scheme
                self.port=port
            def interceptRequest(self,info):
                url=info.requestUrl()
                if url.scheme() in {"about","data","blob"}:
                    return
                info.block(not _receiver_origin_matches(
                    url, self.allowed_host, self.scheme, self.ws_scheme, self.port
                ))

        class ReceiverPage(QWebEnginePage):
            def __init__(self,profile,view,allowed_host,scheme,port):
                super().__init__(profile,view)
                self.allowed_host=allowed_host
                self.scheme=scheme
                self.port=port
            def createWindow(self,_):
                return None
            def acceptNavigationRequest(self,url,kind,main):
                if not main:return True
                return url.scheme()=="about" or _receiver_origin_matches(
                    url, self.allowed_host, self.scheme, "", self.port, main=True
                )

        self.receiver_host=host
        self.receiver_origin=origin
        self.receiver_profile=QWebEngineProfile(self)
        self.receiver_profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.receiver_profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.receiver_profile.setPushServiceEnabled(False)
        self.receiver_interceptor=ReceiverInterceptor(
            host,allowed_scheme,allowed_ws_scheme,allowed_port,
            self.receiver_profile
        )
        self.receiver_profile.setUrlRequestInterceptor(self.receiver_interceptor)
        self.receiver_profile.downloadRequested.connect(lambda download:download.cancel())

        self.receiver_view=QWebEngineView(self)
        page=ReceiverPage(
            self.receiver_profile,self.receiver_view,host,
            allowed_scheme,allowed_port
        )
        page.permissionRequested.connect(lambda permission:permission.deny())
        page.certificateError.connect(lambda error:error.rejectCertificate())
        self.receiver_view.setPage(page)
        self.receiver_view.loadFinished.connect(self._sdr_load_finished)
        page.loadingChanged.connect(self._sdr_loading_changed)
        settings=page.settings()
        for flag in (
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
        ):
            settings.setAttribute(flag,False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,True)
        self.ham_layout.addWidget(self.receiver_view,2)

    def _destroy_receiver(self):
        self.stop_scan()
        self.sdr_load_watch.stop()
        self.sdr_volume_apply.stop()
        self.receiver_connected=False
        self._sdr_load_error = ""
        self._sdr_state_change("OFF")
        if self.receiver_view:
            self.receiver_view.stop()
            self.receiver_view.setUrl(QUrl("about:blank"))
            self.receiver_view.hide()
            self.receiver_view.deleteLater()
            self.receiver_view=None
        if self.receiver_profile:
            self.receiver_profile.deleteLater()
            self.receiver_profile=None
        self.receiver_interceptor=None
        self.receiver_host=""
        self.receiver_origin=None

    def disconnect_receiver(self):
        self._destroy_receiver()
        self.ham_note.setText("SDR OFF · receiver browser destroyed · no background receiver connection")
        return True

    def _station_changed(self,*_):
        item=station(self.selector.currentData())
        self.frequency_display.setText(item["dial"])
        self.display.setText(
            item["name"]+"\n"+item["language"]+" · "+item["category"]
            +" · publisher-documented MP3"
        )
        if self.power.isChecked():self._start_current()

    def _power(self,on):
        if not on:self.off();return
        if self._closed:self.off();return
        if not self._consented:
            approved = self._confirm() if callable(self._confirm) else QMessageBox.question(self,"Play Internet radio?",
                "Connect directly to the selected broadcaster? It receives your IP address and streaming requests. "
                "Audio is played in memory, not recorded. Changing stations while powered on switches that connection. "
                "Power off or Stop all disconnects. Continue?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
            if approved is not True:self.off();return
            self._consented=True
        self._start_current()

    def _detach(self):
        self._epoch+=1
        current,self._session=self._session,None
        if current is not None:
            current.stop();current.deleteLater()

    def _start_current(self):
        self._detach()
        if self._closed or not self.power.isChecked():return
        epoch=self._epoch
        self.status.setText("CONNECTING")
        self.detail.setText("Opening the selected direct audio stream")
        try:
            session=self._factory(self.selector.currentData(),self)
            self._session=session
            session.changed.connect(lambda state,detail,e=epoch:self._receive(e,state,detail))
            session.start(self.volume.value(),self.mute.isChecked())
        except (ImportError,RuntimeError,ValueError,OSError):
            self._detach()
            self._receive(self._epoch,"ERROR","The audio backend could not start. This build may be missing a multimedia component.")

    def _receive(self,epoch,state,detail):
        if epoch!=self._epoch or self._closed or not self.power.isChecked():return
        if state not in {"CONNECTING","BUFFERING","PLAYING","ERROR","OFF"}:return
        self.status.setText(state);self.detail.setText(detail)
        if state=="ERROR":
            self._detach()
            self.power.blockSignals(True);self.power.setChecked(False);self.power.blockSignals(False)

    def _volume(self,value):
        if self._session:self._session.set_volume(value)

    def _mute(self,value):
        if self._session:self._session.set_muted(value)

    def off(self):
        self._detach()
        self._destroy_receiver()
        self.power.blockSignals(True);self.power.setChecked(False);self.power.blockSignals(False)
        self.status.setText("OFF");self.detail.setText("Disconnected · event selection cannot turn the radio back on")

    def shutdown(self):
        self._closed=True
        if self.sdr_directory_reply is not None:
            self.sdr_directory_reply.abort()
        self.off()
