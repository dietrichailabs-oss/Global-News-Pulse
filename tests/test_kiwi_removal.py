"""Offline retirement of KiwiSDR without erasing saved data or WebSDR support."""
from copy import deepcopy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QByteArray, QCoreApplication, QEvent
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from global_pulse import media_widget as legacy
from global_pulse.internet_radio import HAM_DIRECTORIES, RadioPanel
from global_pulse.sdr_directory import (
    DIRECTORY_URLS, curated_websdr_receivers, parse_directory, public_receiver_url,
)
from global_pulse.sources import load_media_catalog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def retire(widget, app):
    if hasattr(widget, "shutdown"):
        widget.shutdown()
    elif hasattr(widget, "stop_all"):
        widget.stop_all()
    else:
        widget.stop()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture
def panel(app):
    widget = RadioPanel(confirm=lambda: False)
    yield widget
    retire(widget, app)


def test_only_websdr_is_supported_on_cold_start_and_settings_never_connect(app, monkeypatch):
    requested = []
    monkeypatch.setattr(QNetworkAccessManager, "get", lambda *args: requested.append(args))
    widget = RadioPanel(confirm=lambda: False)
    try:
        assert list(DIRECTORY_URLS) == ["websdr"]
        assert [item["id"] for item in HAM_DIRECTORIES] == ["websdr"]
        assert widget.ham_selector.count() == widget.receiver_type.count() == 1
        assert widget.receiver_type.currentData() == "websdr"
        assert not any("kiwi" in label.text().casefold() for label in widget.findChildren(QLabel))
        for retired in ("sdr_volume", "sdr_volume_value", "sdr_volume_apply", "_apply_sdr_volume"):
            assert not hasattr(widget, retired)
        writes = []
        widget.configure_preferences(lambda key, default: default,
                                     lambda *args: writes.append(args))
        widget.receiver_picker.setCurrentIndex(1)
        widget.receiver_search.setText("Twente")
        assert requested == writes == []
        assert widget.receiver_view is None and not widget.receiver_connected
        assert widget.sdr_state == "OFF"
        assert "kiwisdr" not in {item["id"] for item in load_media_catalog()}
    finally:
        retire(widget, app)


@pytest.mark.parametrize("provider", ["kiwisdr", "kiwi", "unknown"])
def test_retired_or_unknown_provider_parser_is_not_available(provider):
    with pytest.raises(ValueError):
        parse_directory(provider, b'{"receivers": []}')


@pytest.mark.parametrize("url", [
    "https://kiwisdr.com/public/",
    "https://www.kiwisdr.com/public/",
    "https://12345.proxy.kiwisdr.com/",
    "http://12345.proxy.kiwisdr.com:8073/",
    "https://RX.KIWISDR.COM./",
])
def test_known_retired_hosts_cannot_be_pasted_connected_or_opened(panel, monkeypatch, url):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda value: opened.append(value))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Invalid URL requested consent"))
    with pytest.raises(ValueError):
        public_receiver_url(url)
    panel.receiver_url.setText(url)
    assert not panel.receiver_connect.isEnabled()
    assert not panel.receiver_external.isEnabled()
    assert panel.open_selected_receiver() is False
    assert panel.connect_receiver() is False
    assert opened == [] and panel.receiver_view is None


def test_stale_cache_cannot_restore_a_retired_provider_or_forge_transport(panel):
    valid = dict(public_receiver_url("http://browser.example.org:8901/"),
                 name="Public browser-only receiver", provider="websdr")
    valid["embedded_candidate"] = True  # Stale or tampered flags are revalidated.
    retired = dict(valid, url="https://old-receiver.example.org/", provider="kiwisdr")
    proxy = dict(valid, url="https://12345.proxy.kiwisdr.com/")
    panel.sdr_directory_cache["kiwisdr"] = [retired]
    panel.sdr_directory_cache["websdr"] = [retired, proxy, valid, {"provider": "websdr"}]
    panel._change_receiver_directory()
    rows = [panel.receiver_picker.itemData(i) for i in range(1, panel.receiver_picker.count())]
    assert len(rows) == len(curated_websdr_receivers()) + 1
    assert all(row["provider"] == "websdr" for row in rows)
    assert not any("kiwisdr.com" in row["url"] or "old-receiver" in row["url"] for row in rows)
    assert rows[-1]["embedded_candidate"] is False
    panel.receiver_picker.setCurrentIndex(panel.receiver_picker.count() - 1)
    assert not panel.receiver_connect.isEnabled()
    assert panel.receiver_external.isEnabled()
    assert not panel.receiver_connected


def test_forced_retired_receiver_selection_cannot_update_a_target(panel):
    panel.receiver_picker.addItem("Stale record", {
        "provider": "kiwisdr", "url": "https://old-receiver.example.org/", "name": "Old receiver",
    })
    panel.receiver_picker.setCurrentIndex(panel.receiver_picker.count() - 1)
    assert panel.receiver_url.text() == ""
    assert not panel.receiver_connect.isEnabled()
    assert not panel.receiver_external.isEnabled()
    assert panel.receiver_type.currentData() == "websdr"
    assert "Unsupported" in panel.directory_summary.text()


@pytest.mark.parametrize("state", ["ON", "CONNECTING"])
@pytest.mark.parametrize("entry", [
    {"provider": "kiwisdr", "url": "https://old-receiver.example.org/", "name": "Retired"},
    {"provider": "websdr", "url": "http://localhost:8901/", "name": "Invalid"},
])
def test_forced_bad_selection_retires_old_audio_and_pending_tune(panel, state, entry):
    class View:
        stopped = deleted = hidden = False
        blank = ""
        def stop(self):
            self.stopped = True
        def setUrl(self, url):
            self.blank = url.toString()
        def hide(self):
            self.hidden = True
        def deleteLater(self):
            self.deleted = True

    old = View()
    panel.receiver_view = old
    panel.receiver_connected = True
    panel.receiver_host = "radio.example.org"
    panel.receiver_origin = ("https", 443, "radio.example.org")
    panel._sdr_state_change(state)
    panel._pending_tune = ("https://radio.example.org/?tune=7105usb", "radio.example.org")
    panel.scan_timer.start(1000)
    panel.sdr_load_watch.start(1000)
    panel.receiver_picker.addItem("Forced invalid record", entry)
    panel.receiver_picker.setCurrentIndex(panel.receiver_picker.count() - 1)
    assert old.stopped and old.deleted and old.hidden and old.blank == "about:blank"
    assert panel.receiver_view is None and not panel.receiver_connected
    assert panel._pending_tune is None and panel.receiver_origin is None
    assert not panel.scan_timer.isActive() and not panel.sdr_load_watch.isActive()
    assert panel.sdr_state == "OFF" and panel.receiver_url.text() == ""
    assert not panel.receiver_connect.isEnabled() and not panel.receiver_external.isEnabled()


@pytest.mark.parametrize("provider, changed_selection", [("kiwisdr", False), ("unknown", False), ("websdr", True)])
def test_late_retired_or_wrong_directory_result_is_ignored(panel, monkeypatch, provider, changed_selection):
    class Reply:
        deleted = False
        def readAll(self):
            return QByteArray(json.dumps({"receivers": [
                {"url": "https://old-receiver.example.org/", "name": "Late receiver"},
            ]}).encode())
        def attribute(self, _attribute):
            return 200
        def error(self):
            return QNetworkReply.NetworkError.NoError
        def deleteLater(self):
            self.deleted = True

    if changed_selection:
        panel.ham_selector.addItem("Unsupported", {"id": "kiwisdr", "url": "https://kiwisdr.com/public/"})
        panel.ham_selector.setCurrentIndex(1)
    monkeypatch.setattr("global_pulse.internet_radio.parse_directory",
                        lambda *args: pytest.fail("Retired provider result was parsed"))
    reply = Reply()
    panel.sdr_directory_reply = reply
    panel._sdr_directory_finished(provider, reply)
    assert reply.deleted and panel.sdr_directory_reply is None
    assert panel.sdr_directory_data == bytearray()
    assert panel.sdr_directory_cache == {}
    assert "ignored" in panel.directory_summary.text()
    assert not panel.receiver_connected


@pytest.mark.parametrize("kind", [None, "kiwi", "kiwisdr", "unknown"])
def test_invalid_protocol_has_no_https_or_reviewed_http_authority(panel, monkeypatch, kind):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Unsupported protocol requested consent"))
    if kind is None:
        panel.receiver_type.setCurrentIndex(-1)
    else:
        panel.receiver_type.addItem("Unsupported", kind)
        panel.receiver_type.setCurrentIndex(panel.receiver_type.count() - 1)
    for url in ("https://radio.example.org/", "http://na5b.com:8901/"):
        panel.receiver_url.setText(url)
        assert not panel.receiver_connect.isEnabled()
        with pytest.raises(ValueError, match="Only WebSDR"):
            panel._tuned_receiver_url()
        assert panel.open_selected_receiver() is False


RETIRED_HOST_ALIASES = (
    "https://ｋｉｗｉｓｄｒ.com/",
    "https://rx.proxy.ＫＩＷＩＳＤＲ.com/",
    "https://kiwi\u200bsdr.com/",
)


RETIRED_RECORDS = [
    {"provider": "KiwiSDR"},
    {"provider": "Kiwi SDR public receiver"},
    {"type": "kiwi"},
    {"receiver_type": "kiwi"},
    {"protocol": "kiwisdr"},
    {"id": "kiwisdr"},
    {"id": "saved_kiwisdr_receiver"},
    {"url": "https://12345.proxy.kiwisdr.com/"},
    {"receiver": "https://kiwisdr.com/"},
    {"original_url": "https://rx.kiwisdr.com/"},
] + [{field: url} for field in ("url", "original_url", "receiver")
     for url in RETIRED_HOST_ALIASES]


@pytest.mark.parametrize("retired", RETIRED_RECORDS)
def test_legacy_catalog_event_and_forced_selection_rejects_identifiable_kiwi(app, monkeypatch, retired):
    tile = legacy._MediaTile()
    item = {"title": "Retired fixture", "name": "Retired fixture", "type": "radio",
            "url": "https://old-receiver.example.org/", "receiver": "https://old-receiver.example.org/",
            "frequency": "7100", "mode": "USB", **retired}
    def forbidden(*args, **kwargs):
        pytest.fail("Retired record reached a connection or browser shortcut")
    monkeypatch.setattr(tile, "_connect_radio_receiver", forbidden)
    monkeypatch.setattr(QDesktopServices, "openUrl", forbidden)
    try:
        tile.set_catalog([item])
        tile.set_event({"media": [item], "reports": [{"media": [item]}]})
        assert tile._current() == {}
        tile.selector.addItem("Forced stale selection", item)
        tile.selector.setCurrentIndex(tile.selector.count() - 1)
        assert tile.watch() is False
        assert tile.open_original() is False
        assert tile.radio_view is None
        with pytest.raises(ValueError):
            legacy.MediaPanel._normalize_radio_station(item)
    finally:
        retire(tile, app)


def test_retired_legacy_preferences_are_filtered_in_memory_not_erased(app):
    supported = {"name": "Public WebSDR", "type": "radio", "provider": "WebSDR",
                 "url": "https://radio.example.org/", "receiver": "https://radio.example.org/",
                 "frequency": "7100", "mode": "USB"}
    retired = dict(supported, provider="KiwiSDR", url="https://old-receiver.example.org/",
                   receiver="https://old-receiver.example.org/")
    values = {"radio_presets": [retired, supported],
              "radio_stations": [retired, supported],
              "radio_event_bindings": {"old-event": retired, "good-event": supported},
              "unrelated": "preserve"}
    original = deepcopy(values)
    writes = []
    widget = legacy.MediaPanel()
    try:
        widget.configure_radio_preferences(lambda key, default: values.get(key, default),
                                           lambda *args: writes.append(args))
        assert values == original and writes == []
        assert widget.radio_presets[0] is None
        assert widget.radio_presets[1] == supported
        assert len(widget.radio_stations) == 1
        assert set(widget.radio_event_bindings) == {"good-event"}
        assert widget._select_radio_preset_record(retired) is False
        assert all(tile.radio_view is None for tile in widget.tiles)
    finally:
        retire(widget, app)


def test_unrelated_kiwi_word_or_custom_hostname_is_not_a_provider_identity():
    item = {"title": "Kiwi bird landscape", "name": "Kiwi bird landscape", "provider": "Local operator",
            "type": "radio", "url": "https://kiwi.example.org/", "frequency": "7100", "mode": "USB"}
    assert legacy._supported_media(item)
    assert legacy.MediaPanel._normalize_radio_station(item)["url"] == item["url"]
    assert legacy._supported_media(dict(item, provider="Kiwi", id="kiwi"))
    assert not legacy._retired_receiver_record(dict(item, url="https://kiwisdr.com.example.org/"))


@pytest.mark.parametrize("url", ("https://12345.proxy.kiwisdr.com/",) + RETIRED_HOST_ALIASES)
def test_legacy_direct_player_construction_rejects_retired_known_host(app, url):
    tile = legacy._MediaTile()
    try:
        for method in (tile._connect_radio_receiver, tile._ensure_radio_player):
            with pytest.raises(ValueError, match="supported public radio"):
                method(url)
        assert tile.radio_view is None and tile.radio_profile is None
    finally:
        retire(tile, app)
