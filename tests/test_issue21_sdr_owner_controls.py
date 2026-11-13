"""Issue #21: offline receiver discovery, power-state and volume regression tests."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.sdr_directory import parse_directory, public_receiver_url
from global_pulse.internet_radio import RadioPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _cleanup(panel, app):
    panel.shutdown()
    panel.deleteLater()
    app.processEvents()


def test_public_receiver_links_and_port_policy():
    https = public_receiver_url("https://radio.example.org/rx")
    assert https["embedded_candidate"] is True
    http = public_receiver_url("http://radio.example.org:8073/")
    assert http["embedded_candidate"] is False
    assert "Browser only" in http["reason"]
    with pytest.raises(ValueError):
        public_receiver_url("https://localhost:443/")
    with pytest.raises(ValueError):
        public_receiver_url("http://192.168.0.1:8073/")
    with pytest.raises(ValueError):
        public_receiver_url("https://radio.example.org\\@localhost/")
    with pytest.raises(ValueError):
        public_receiver_url("https://user:secret@radio.example.org/")


def test_websdr_directory_html_is_bounded_and_deduplicated():
    html = b"""<html><body>
      <a href="http://sdr1.example.org:8901/">Ontario amateur receiver</a>
      <a href="http://sdr1.example.org:8901/">Duplicate</a>
      <a href="https://radio.example.org/">Europe HF WebSDR</a>
      <a href="http://localhost:8901/">Private reject</a>
      <a href="javascript:alert(1)">Script reject</a>
      <a href="https://websdr.org/faq.html">FAQ reject</a>
      </body></html>"""
    rows = parse_directory("websdr", html)
    assert [r["host"] for r in rows] == ["sdr1.example.org", "radio.example.org"]
    assert rows[0]["embedded_candidate"] is False
    assert rows[1]["embedded_candidate"] is True
    assert rows[0]["name"] == "Ontario amateur receiver"


def test_kiwi_directory_json_and_empty_handling():
    import json
    raw = json.dumps({"receivers": [
        {"url": "https://kiwi.example.org/", "name": "Example Kiwi"},
        {"url": "http://remote.example.org:8073/", "name": "Remote Kiwi"},
        {"url": "https://127.0.0.1/", "name": "Forbidden"}]}).encode()
    rows = parse_directory("kiwisdr", raw)
    assert len(rows) == 2
    assert rows[0]["name"] == "Example Kiwi"
    assert rows[1]["embedded_candidate"] is False
    assert parse_directory("kiwisdr", b"<html><h1>Access gate</h1></html>") == []
    with pytest.raises(ValueError):
        parse_directory("kiwisdr", b"x" * 1_000_001)


def test_receiver_picker_populates_url_and_flags_browser_only(app):
    panel = RadioPanel(confirm=lambda: False)
    try:
        assert panel.receiver_connect.isEnabled() is False
        panel.sdr_directory_cache["websdr"] = [
            dict(public_receiver_url("http://outside.example.org:8901/"),
                 name="Outside receiver", provider="websdr"),
            dict(public_receiver_url("https://online.example.org/"),
                 name="In-app candidate", provider="websdr"),
        ]
        panel._change_receiver_directory()
        assert panel.receiver_picker.count() == 3
        panel.receiver_picker.setCurrentIndex(1)
        assert panel.receiver_url.text().startswith("http://")
        assert panel.receiver_external.isEnabled()
        assert not panel.receiver_connect.isEnabled()
        panel.receiver_picker.setCurrentIndex(2)
        assert panel.receiver_url.text().startswith("https://")
        assert panel.receiver_connect.isEnabled()
        assert panel.receiver_type.currentData() == "websdr"
    finally:
        _cleanup(panel, app)


def test_receiver_state_is_not_green_until_load_success(app):
    panel = RadioPanel(confirm=lambda: False)
    class FakePage:
        def __init__(self):
            self.muted = None
        def setAudioMuted(self, flag):
            self.muted = flag
    class FakeView:
        def __init__(self):
            self._page = FakePage()
        def page(self):
            return self._page
        def stop(self):
            pass
        def setUrl(self, value):
            pass
        def hide(self):
            pass
        def deleteLater(self):
            pass
    try:
        panel.receiver_view = FakeView()
        panel.receiver_connected = True
        panel._sdr_state_change("CONNECTING")
        assert "CONNECTING" in panel.sdr_status.text()
        assert "ON" not in panel.sdr_status.text()
        assert not panel.sdr_mute.isEnabled()
        panel._sdr_load_finished(True)
        assert "ON" in panel.sdr_status.text()
        assert panel.sdr_mute.isEnabled()
        assert panel.sdr_volume.isEnabled()
        panel.sdr_mute.setChecked(True)
        assert panel.receiver_view.page().muted is True
        panel.disconnect_receiver()
        assert "OFF" in panel.sdr_status.text()
        assert not panel.sdr_mute.isEnabled()
    finally:
        _cleanup(panel, app)


def test_kiwi_volume_is_explicit_and_websdr_cannot_fake_volume(app):
    panel = RadioPanel(confirm=lambda: False)
    try:
        panel.receiver_url.setText("https://radio.example.org/")
        assert panel._tuned_receiver_url()[0].endswith("?f=7100usb&vol=40")
        panel.sdr_volume.setValue(25)
        assert panel._tuned_receiver_url()[0].endswith("?f=7100usb&vol=25")
        assert panel.sdr_volume_value.text() == "25%"
        panel.receiver_type.setCurrentIndex(panel.receiver_type.findData("websdr"))
        panel._sdr_state_change("ON")
        assert not panel.sdr_volume.isEnabled()
        assert panel._tuned_receiver_url()[0].endswith("?tune=7100usb")
    finally:
        _cleanup(panel, app)
