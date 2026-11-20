"""R20 owner's digital radio layout and bounded offline station/SDR tests."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from global_pulse.internet_radio import (
    BROADCAST_CATEGORIES,
    OWNER_TEST_WEBDR_ORIGIN,
    STATIONS,
    RadioPanel,
    station,
)
from global_pulse.sdr_directory import parse_directory


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app):
    radio = RadioPanel(confirm=lambda: False)
    yield radio
    radio.shutdown()
    radio.deleteLater()
    app.processEvents()


def test_broadcast_has_separate_tab_and_truthful_frequencies(panel):
    assert panel.radio_tabs.count() == 2
    assert "AM / FM" in panel.radio_tabs.tabText(0)
    assert "HAM" in panel.radio_tabs.tabText(1)
    assert panel.frequency_display.text() == "FM · 93.9 MHz"
    assert station("wnyc_am")["dial"] == "AM · 820 kHz"
    assert station("fip")["dial"] == "INTERNET STREAM"
    assert "requested" in panel.ham_frequency_display.accessibleName().lower()
    assert len(STATIONS) >= 18
    assert len({row["id"] for row in STATIONS}) == len(STATIONS)
    assert all(row["category"] in BROADCAST_CATEGORIES for row in STATIONS)
    assert all(row["url"].startswith("https://") for row in STATIONS)
    assert all(row["documentation"].startswith("https://") for row in STATIONS)


def test_broadcast_genre_filter_and_real_previous_next_buttons(panel):
    genre_index = panel.broadcast_category.findData("Music")
    panel.broadcast_category.setCurrentIndex(genre_index)
    assert panel.selector.count() >= 3
    assert all(station(panel.selector.itemData(i))["category"] == "Music"
               for i in range(panel.selector.count()))
    assert panel.frequency_display.text() == "INTERNET STREAM"
    first_id = panel.selector.currentData()
    panel.next.click()
    assert panel.selector.currentData() != first_id
    panel.previous.click()
    assert panel.selector.currentData() == first_id
    assert panel.status.text() == "OFF"
    assert panel._session is None


def test_preset_recalls_station_hidden_by_current_filter(panel):
    panel.presets[0] = "wqxr"
    panel.broadcast_category.setCurrentIndex(
        panel.broadcast_category.findData("News & Talk")
    )
    assert panel.selector.findData("wqxr") == -1
    assert panel.recall_preset(0)
    assert panel.broadcast_category.currentData() == "All stations"
    assert panel.selector.currentData() == "wqxr"
    assert panel.frequency_display.text() == "FM · 105.9 MHz"
    assert panel.status.text() == "OFF"


def test_ham_step_keys_change_exact_requested_frequency_without_auto_connect(panel, monkeypatch):
    panel._select_na5b_test()
    assert panel.receiver_url.text() == OWNER_TEST_WEBDR_ORIGIN
    assert panel.sdr_state == "OFF"
    assert not panel.receiver_connected
    assert panel.ham_frequency_display.text() == "7.100 MHz"
    assert "NA5B" in panel.ham_bands.text()
    target_values = []

    def capture_requested_tune(target):
        target_values.append(target)
        panel.frequency.setText(f"{target:g}")
        return True

    monkeypatch.setattr(panel, "tune_receiver", capture_requested_tune)
    panel.ham_forward.click()
    assert target_values == [7105.0]
    assert panel.ham_frequency_display.text() == "7.105 MHz"
    assert "7105 kHz" in panel.ham_frequency_detail.text()
    panel.ham_back.click()
    assert target_values == [7105.0, 7100.0]
    assert panel.ham_frequency_display.text() == "7.100 MHz"
    assert "7100 kHz" in panel.ham_frequency_detail.text()
    assert panel.sdr_state == "OFF"
    assert not panel.receiver_connected


def test_fractional_ham_tune_preserves_exact_requested_dial_and_provider_url(panel):
    panel._select_na5b_test()
    panel.frequency.setText("7100.123")
    assert panel.ham_frequency_display.text() == "7.100123 MHz"
    assert "7100.123 kHz" in panel.ham_frequency_detail.text()
    url, _ = panel._tuned_receiver_url()
    assert url.endswith("?tune=7100.123usb"), url
    panel.receiver_type.setCurrentIndex(panel.receiver_type.findData("kiwi"))
    panel.receiver_url.setText("https://radio.example.org/")
    kiwi_url, _ = panel._tuned_receiver_url()
    assert kiwi_url.endswith("?f=7100.123usb&vol=40"), kiwi_url
    assert not panel.receiver_connected


def test_operator_bands_are_only_reported_when_directory_supplies_them(panel):
    data = json.dumps({"receivers": [
        {"url": "https://radio.example.org/", "name": "Example SDR",
         "bands": ["20 m", "40 m", "6 m", "20 m", "\nUnsafe"]},
    ]}).encode()
    rows = parse_directory("kiwisdr", data)
    assert len(rows) == 1
    assert rows[0]["bands"] == ["20 m", "40 m", "6 m"]
    panel.sdr_directory_cache["kiwisdr"] = rows
    panel.ham_selector.setCurrentIndex(1)
    panel._change_receiver_directory()
    panel.receiver_picker.setCurrentIndex(1)
    assert panel.ham_receiver_name.text() == "Example SDR"
    assert "20 m · 40 m · 6 m" in panel.ham_bands.text()
    assert "Exact bounds/availability" in panel.ham_bands.text()
    assert not panel.receiver_connected


def test_ham_advanced_scan_starts_hidden_and_stays_explicit(panel):
    assert panel.scan_controls.isHidden()
    assert not panel.scan_timer.isActive()
    panel.advanced_scan.click()
    assert not panel.scan_controls.isHidden()
    assert not panel.scan_timer.isActive()
    panel.advanced_scan.click()
    assert panel.scan_controls.isHidden()


def test_open_directory_warns_about_plaintext_http_and_requires_separate_consent(panel, monkeypatch):
    """Browser-only action must disclose HTTP and do nothing on refusal."""
    prompts, opened = [], []
    decision = [QMessageBox.StandardButton.No]

    def ask(*args, **kwargs):
        prompts.append(args[2])
        return decision[0]

    def open_browser(url):
        opened.append(url.toString())
        return True

    monkeypatch.setattr(QMessageBox, "question", ask)
    monkeypatch.setattr(QDesktopServices, "openUrl", open_browser)
    assert panel.ham_selector.currentData()["id"] == "websdr"
    assert panel.open_ham_directory() is False
    assert "unencrypted HTTP" in prompts[-1]
    assert "Network intermediaries" in prompts[-1]
    assert "IP address" in prompts[-1]
    assert opened == []

    decision[0] = QMessageBox.StandardButton.Yes
    assert panel.open_ham_directory() is True
    assert opened == ["http://www.websdr.org/"]

    panel.ham_selector.setCurrentIndex(panel.ham_selector.findData(
        next(row for row in (panel.ham_selector.itemData(i)
                             for i in range(panel.ham_selector.count()))
             if row["id"] == "kiwisdr")
    ))
    assert panel.open_ham_directory() is True
    assert "uses HTTPS" in prompts[-1]
    assert "unencrypted HTTP" not in prompts[-1]
    assert opened[-1] == "https://kiwisdr.com/public/"


def test_rapid_ham_buttons_coalesce_while_receiver_is_connecting(panel, monkeypatch):
    """Prior same-view load failure must not tear down a newer requested tune."""
    from PySide6.QtCore import QUrl

    class FakePage:
        def setAudioMuted(self, value):
            self.muted = bool(value)

    class FakeView:
        def __init__(self):
            self.loaded = []
            self.stopped = self.deleted = False
            self._page = FakePage()

        def load(self, url):
            self.loaded.append(url.toString())

        def show(self):
            pass

        def page(self):
            return self._page

        def stop(self):
            self.stopped = True

        def setUrl(self, url):
            self.last_url = url.toString()

        def hide(self):
            pass

        def deleteLater(self):
            self.deleted = True

    created = []

    def fake_ensure(host):
        if panel.receiver_view is None:
            panel.receiver_view = FakeView()
            created.append(panel.receiver_view)
        panel.receiver_host = host
        panel.receiver_origin = ("http", 8901, host)

    monkeypatch.setattr(panel, "_ensure_receiver_view", fake_ensure)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    panel._select_na5b_test()
    assert panel.connect_receiver()
    view = created[0]
    assert len(view.loaded) == 1 and view.loaded[0].endswith("?tune=7100usb")

    panel.ham_forward.click()
    panel.ham_forward.click()
    assert panel.frequency.text() == "7110"
    assert panel.sdr_state == "CONNECTING"
    assert len(view.loaded) == 1, "Do not overlap navigation while connecting"
    assert panel._pending_tune[0].endswith("?tune=7110usb")

    # Simulate failure from the first load, then success of the queued final tune.
    panel._sdr_load_finished(False)
    assert panel.sdr_state == "CONNECTING"
    assert panel.receiver_connected
    assert not view.deleted
    assert len(view.loaded) == 2 and view.loaded[-1].endswith("?tune=7110usb")
    assert panel._pending_tune is None
    panel._sdr_load_finished(True)
    assert panel.sdr_state == "ON"
    assert panel.receiver_view is view

    # A queued user tune must be canceled by Stop even if a late load arrives.
    panel.ham_back.click()
    panel.ham_back.click()
    assert panel._pending_tune is not None
    panel.disconnect_receiver()
    assert panel._pending_tune is None and not panel.receiver_connected
    assert view.stopped and view.deleted
    panel._sdr_load_finished(False)
    assert panel.sdr_state == "OFF"


def test_pending_ham_tune_does_not_survive_receiver_change(panel, monkeypatch):
    """Changing a receiver invalidates the prior WebSDR navigation and queue."""
    from urllib.parse import urlsplit

    class FakeView:
        def __init__(self):
            self.loaded = []
            self.deleted = False

        def load(self, url):
            self.loaded.append(url.toString())

        def show(self):
            pass

        def stop(self):
            pass

        def setUrl(self, url):
            pass

        def hide(self):
            pass

        def deleteLater(self):
            self.deleted = True

    views = []

    def fake_ensure(host):
        if panel.receiver_view is None:
            panel.receiver_view = FakeView()
            views.append(panel.receiver_view)
        target, _ = panel._receiver_target()
        origin = urlsplit(target)
        panel.receiver_host = host
        panel.receiver_origin = (origin.scheme, origin.port or 443, host)

    monkeypatch.setattr(panel, "_ensure_receiver_view", fake_ensure)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    panel._select_na5b_test()
    assert panel.connect_receiver()
    panel.ham_forward.click()
    assert panel._pending_tune is not None
    panel.receiver_type.setCurrentIndex(panel.receiver_type.findData("kiwi"))
    panel.receiver_url.setText("https://rx.example.org/")
    assert panel.tune_receiver()
    assert views[0].deleted
    assert panel._pending_tune is None
    assert panel.receiver_host == "rx.example.org"
    assert len(views) == 2 and len(views[1].loaded) == 1
    assert panel.sdr_state == "CONNECTING"


def test_category_change_keeps_active_station_and_hidden_preset_switches_once(panel):
    from PySide6.QtCore import QObject, Signal

    class FakeSession(QObject):
        changed = Signal(str, str)
        instances = []

        def __init__(self, identifier, parent=None):
            super().__init__(parent)
            self.identifier = identifier
            self.stopped = False
            self.__class__.instances.append(self)

        def start(self, volume, muted):
            return True

        def stop(self):
            self.stopped = True

        def set_volume(self, volume):
            pass

        def set_muted(self, muted):
            pass

    panel._factory = FakeSession
    panel._confirm = lambda: True
    panel.power.click()
    assert len(FakeSession.instances) == 1
    old = FakeSession.instances[-1]
    assert old.identifier == "wnyc_fm"
    panel.broadcast_category.setCurrentIndex(
        panel.broadcast_category.findData("News & Talk")
    )
    assert panel.selector.currentData() == "wnyc_fm"
    assert panel._session is old and not old.stopped
    assert len(FakeSession.instances) == 1, "Unchanged station must not restart"

    panel.presets[0] = "wqxr"
    assert panel.recall_preset(0)
    assert panel.broadcast_category.currentData() == "All stations"
    assert panel.selector.currentData() == "wqxr"
    assert len(FakeSession.instances) == 2
    assert old.stopped and FakeSession.instances[-1].identifier == "wqxr"
    assert not FakeSession.instances[-1].stopped


def test_pinned_na5b_preserves_operator_bands_and_truthful_transport(panel):
    raw = json.dumps({"receivers": [{
        "url": OWNER_TEST_WEBDR_ORIGIN,
        "name": "Operator supplied NA5B",
        "bands": ["60m", "6m"],
    }]}).encode()
    rows = parse_directory("websdr", raw)
    assert rows[0]["bands"] == ["60m", "6m"]
    panel.sdr_directory_cache["websdr"] = rows
    panel._change_receiver_directory()
    pinned = panel.receiver_picker.itemData(1)
    assert pinned["name"] == "Operator supplied NA5B"
    assert pinned["bands"] == ["60m", "6m"]
    assert "Browser only" not in pinned["reason"]
    assert "HTTP/8901" in pinned["reason"]
    panel.receiver_picker.setCurrentIndex(1)
    assert "Operator-listed bands: 60m · 6m" in panel.ham_bands.text()
    assert "HTTP/8901" in panel.receiver_list_note.text()
    assert panel.receiver_connect.isEnabled()


def test_directory_malformed_link_deep_json_and_kiwi_proxy_are_isolated():
    html = (b'<a href="https://good.example.org/">Good SDR</a>'
            b'<a href="http://[">Malformed IPv6</a>')
    rows = parse_directory("websdr", html)
    assert [row["host"] for row in rows] == ["good.example.org"]
    assert parse_directory("kiwisdr", b"[" * 10000 + b"]" * 10000) == []
    kiwi = json.dumps({"receivers": [
        {"url": "https://12345.proxy.kiwisdr.com/", "name": "Kiwi proxy HTTPS"},
        {"url": "http://12345.proxy.kiwisdr.com:8073/", "name": "Kiwi proxy HTTP"},
        {"url": "https://www.kiwisdr.com/public/", "name": "Directory, not receiver"},
    ]}).encode()
    parsed = parse_directory("kiwisdr", kiwi)
    assert len(parsed) == 2
    assert parsed[0]["embedded_candidate"] is True
    assert parsed[1]["embedded_candidate"] is False
    assert "Browser only" in parsed[1]["reason"]
