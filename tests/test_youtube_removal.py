"""Owner-directed video removal, exercised through actual surviving widgets.

No network, provider playback, Windows installation or account is involved.
Legacy user data stays intact but cannot reconstruct retired launch paths.
"""
from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
import socket
from urllib.parse import urlsplit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

import global_pulse.media_widget as legacy
import global_pulse.single_media as current
from global_pulse.camera_context import camera_catalog
from global_pulse.sources import load_catalog, load_media_catalog, parse_feed


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Retirement regression attempted a network or browser action")
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(QDesktopServices, "openUrl", blocked)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)


def retire(widget, app):
    if hasattr(widget, "shutdown"):
        widget.shutdown()
    elif hasattr(widget, "stop"):
        widget.stop()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_actual_panel_starts_on_radio_and_has_no_retired_controls_or_imports(app):
    panel = current.MediaPanel()
    try:
        assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == ["Radio", "Cameras"]
        assert panel.tabs.currentIndex() == 0
        assert panel.tabs.currentWidget() is panel.radio
        assert panel.tabs.widget(1) is panel.camera_page
        assert panel.tiles == [panel.camera]
        assert not hasattr(panel, "tv")
        assert not hasattr(current, "Television")
        assert not hasattr(legacy, "youtube_id")
        assert not hasattr(legacy, "youtube_player_navigation")
        assert not hasattr(legacy._MediaTile, "_ensure_player")
        assert not hasattr(legacy._MediaTile, "float_player")
        assert importlib.util.find_spec("global_pulse.native_tv") is None
        labels = "\n".join(button.text() + " " + button.accessibleName()
                           for button in panel.findChildren(QPushButton)).casefold()
        for retired in ("youtube", "test tv player", "test your video", "add video", "television"):
            assert retired not in labels
        assert panel.radio._session is None
        assert panel.radio.receiver_view is None
        assert panel.camera.camera is None
    finally:
        retire(panel, app)


def test_old_saved_videos_are_neither_read_erased_nor_restored(app):
    preferences = {
        "single_tv_videos_v1": ["https://www.youtube.com/watch?v=abcdefghijk"],
        "radio_presets": [{"name": "Historical radio preset"}],
    }
    original = copy.deepcopy(preferences)
    reads, writes = [], []
    def get(key, default=None):
        reads.append(key)
        return copy.deepcopy(preferences.get(key, default))
    def put(key, value):
        writes.append(key)
        preferences[key] = copy.deepcopy(value)
    panel = current.MediaPanel()
    try:
        panel.configure_radio_preferences(get, put)
        panel.set_event({"id": "old-event", "media": [{
            "type": "youtube", "url": original["single_tv_videos_v1"][0],
            "title": "Old saved video",
        }]})
        panel.stop()
        assert preferences["single_tv_videos_v1"] == original["single_tv_videos_v1"]
        assert preferences["radio_presets"] == original["radio_presets"]
        assert "single_tv_videos_v1" not in reads
        assert "single_tv_videos_v1" not in writes
        assert all("youtube" not in str(panel.camera.selector.itemData(i)).casefold()
                   for i in range(panel.camera.selector.count()))
        assert panel.radio._session is None
    finally:
        retire(panel, app)


class AudioFixture(QObject):
    changed = Signal(str, str)
    def __init__(self, identifier, parent=None):
        super().__init__(parent)
        self.identifier = identifier
        self.started = self.stopped = False
    def start(self, volume=60, muted=False):
        self.started = True
        self.changed.emit("CONNECTING", "Offline synthetic audio")
        return True
    def stop(self):
        self.stopped = True
        self.changed.emit("OFF", "Stopped")
    def set_volume(self, value):
        pass
    def set_muted(self, value):
        pass


def test_shifted_tabs_stop_previous_media_and_never_restart_on_return(app, monkeypatch):
    monkeypatch.setattr("global_pulse.internet_radio.AudioSession", AudioFixture)
    panel = current.MediaPanel()
    panel.radio._confirm = lambda: True
    try:
        panel.radio.power.click()
        session = panel.radio._session
        assert session is not None and session.started and not session.stopped
        panel.set_event({"id": "news-refresh", "media": [], "reports": []})
        assert panel.radio._session is session and not session.stopped
        panel.tabs.setCurrentIndex(1)
        assert session.stopped and panel.radio._session is None
        assert panel.radio.status.text() == "OFF"
        camera_stops = []
        original_stop = panel.camera.stop
        def stop_camera():
            camera_stops.append(True)
            original_stop()
        monkeypatch.setattr(panel.camera, "stop", stop_camera)
        panel.tabs.setCurrentIndex(0)
        assert camera_stops == [True]
        assert panel.radio._session is None
        panel.shutdown()
        panel.radio.power.click()
        assert panel.radio._session is None
        assert panel.camera.camera is None
    finally:
        retire(panel, app)


@pytest.mark.parametrize("record", [
    {"type": "youtube", "url": "https://example.org/old"},
    {"type": "video", "url": "https://example.org/old"},
    {"type": "link", "url": "https://www.youtube.com/watch?v=abcdefghijk"},
    {"type": "link", "url": "https://youtu.be/abcdefghijk"},
    {"type": "channel", "url": "https://m.youtube.com/@old/live"},
    {"type": "link", "url": "https://www.youtube-nocookie.com/embed/abcdefghijk"},
    {"type": "link", "url": "https://sub.youtube.com./old"},
    {"type": "radio", "url": "https://example.org/radio", "receiver": "https://www.youtube.com/", "frequency": "7100", "mode": "usb"},
    {"type": "link", "url": "https://example.org/link", "original_url": "https://youtu.be/abcdefghijk"},
])
def test_legacy_catalog_event_and_forced_selection_cannot_launch_retired_media(app, monkeypatch, record):
    tile = legacy._MediaTile()
    def forbidden(*args, **kwargs):
        raise AssertionError("A retired selection reached a surviving player")
    monkeypatch.setattr(tile, "_connect_radio_receiver", forbidden)
    monkeypatch.setattr(tile, "connect_camera", forbidden)
    try:
        item = {"title": "Retired saved fixture", **record}
        tile.set_catalog([item])
        tile.set_event({"media": [item], "reports": [{"media": [item]}]})
        assert tile._current() == {}
        assert tile.selector.count() == 1
        # Even corrupt or already-selected legacy data cannot skip admission.
        tile.selector.addItem("Forced stale selection", item)
        tile.selector.setCurrentIndex(tile.selector.count() - 1)
        assert tile.watch() is False
        assert tile.open_original() is False
        assert tile.radio_view is None and tile.radio_profile is None
        assert tile.camera is None
    finally:
        retire(tile, app)


def test_legacy_browser_links_and_reviewed_cameras_still_work_without_video(app, monkeypatch):
    tile = legacy._MediaTile()
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    try:
        tile.set_catalog([{"type": "link", "url": "https://www.bloomberg.com/tv/", "title": "Provider site"}])
        tile.open_original()
        assert opened == ["https://www.bloomberg.com/tv/"]
        assert tile.watch() is False
        tile.set_catalog(camera_catalog())
        assert tile.selector.count() == len(camera_catalog())
        assert tile.connect_camera() is False  # Actual default-No consent.
        assert tile.camera is None
    finally:
        retire(tile, app)


def test_bundled_catalogs_remove_youtube_but_preserve_non_youtube_sources():
    catalog = load_catalog()
    assert not ({"youtube", "tousitv"} & {item["id"] for item in catalog})
    media = load_media_catalog()
    for item in media:
        host = (urlsplit(item["url"]).hostname or "").casefold()
        assert not any(host == domain or host.endswith("." + domain)
                       for domain in ("youtube.com", "youtu.be", "youtube-nocookie.com"))
        assert item["type"] not in {"video", "youtube"}
    indexed = {item["id"]: item for item in media}
    for identifier in ("aljazeera_en", "cna", "africanews", "globalnews_ca",
                       "cbs_news_247", "abc_news_live", "bloomberg_tv", "yahoo_finance",
                       "cnbc_live", "fox_weather", "accuweather_now", "weathernation",
                       "weather_channel", "un_video"):
        assert indexed[identifier]["type"] == "link"
        assert "no in-app video playback" in indexed[identifier]["availability"].lower()
    assert {"websdr", "kiwisdr", "nps_air", "nps_oceans"} <= indexed.keys()
    doj = next(item for item in catalog if "justice.gov/news/rss?" in item.get("url", ""))
    assert "youtube_video" in doj["url"]  # A provider's RSS filter, not a player.


def test_feed_video_metadata_no_longer_constructs_player_but_retains_report():
    source = {
        "id": "retirement-fixture", "name": "Offline public feed",
        "adapter": "rss", "url": "https://example.org/rss", "metadata_only": False,
        "allowed_domains": ["example.org"], "language": "en", "category": "News",
    }
    feed = (b"<rss><channel><item><guid>old1</guid><title>Retained report</title>"
            b"<link>https://example.org/story</link><videoid>abcdefghijk</videoid>"
            b"</item></channel></rss>")
    rows = parse_feed(feed, source, "2026-11-21T20:00:00Z")
    assert len(rows) == 1
    assert rows[0]["title"] == "Retained report"
    assert rows[0]["url"] == "https://example.org/story"
    assert rows[0]["media"] == []


def test_retired_sources_helpers_and_probes_are_absent_from_current_tree():
    for relative in (
        "global_pulse/native_tv.py",
        "global_pulse/resources/tv_playback_verified.json",
        "packaging/tv/NativeTvProgram.cs",
        "packaging/tv/GlobalPulse.TV.csproj",
        "packaging/tv/packages.lock.json",
        "scripts/issue22_youtube_watch_probe.ps1",
        "scripts/issue82_native_embed_probe.py",
    ):
        assert not (ROOT / relative).exists(), relative
