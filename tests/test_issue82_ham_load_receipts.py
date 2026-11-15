"""Issue82: bounded WebEngine SDR load errors and truthful connect receipt.

Offline synthetic Qt tests only. No live receiver, internet audio, HTTP/8901
availability or Windows 11 playback is claimed from these tests.
"""
from __future__ import annotations
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWebEngineCore import QWebEngineLoadingInfo
from PySide6.QtWidgets import QApplication

from global_pulse.internet_radio import RadioPanel


def _cleanup(panel, app):
    panel.shutdown()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


class FakeLoadInfo:
    def __init__(self, status, code=-102):
        self._status = status
        self._code = code

    def status(self):
        return self._status

    def errorDomain(self):
        return SimpleNamespace(name="ConnectionErrorDomain")

    def errorCode(self):
        return self._code


def test_connect_is_connecting_not_false_audio_success(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = RadioPanel(confirm=lambda: False)
    try:
        panel._select_na5b_test()
        def pending_load(url, host, *, require_consent=False):
            assert require_consent is True
            assert url.startswith("http://na5b.com:8901/?tune=")
            assert host == "na5b.com"
            panel.receiver_connected = True
            panel._sdr_state_change("CONNECTING", "Loading")
            return True
        monkeypatch.setattr(panel, "_load_receiver_url", pending_load)
        assert panel.connect_receiver()
        assert panel.sdr_state == "CONNECTING"
        assert "CONNECTING" in panel.ham_note.text()
        assert "audio are not verified" in panel.ham_note.text().lower()
        assert "CONNECTED" not in panel.ham_note.text()
    finally:
        _cleanup(panel, app)


def test_failed_page_records_only_bounded_code_not_url_or_audio_claim():
    app = QApplication.instance() or QApplication([])
    panel = RadioPanel(confirm=lambda: False)
    try:
        panel.receiver_connected = True
        panel._sdr_state_change("CONNECTING")
        panel._sdr_loading_changed(FakeLoadInfo(
            QWebEngineLoadingInfo.LoadStatus.LoadStartedStatus
        ))
        assert panel._sdr_load_error == ""
        panel._sdr_loading_changed(FakeLoadInfo(
            QWebEngineLoadingInfo.LoadStatus.LoadFailedStatus
        ))
        assert panel._sdr_load_error == "ConnectionErrorDomain code -102"
        panel._sdr_load_finished(False)
        assert panel.sdr_state == "ERROR"
        assert "ConnectionErrorDomain code -102" in panel.ham_note.text()
        assert "na5b.com" not in panel.ham_note.text()
        assert "PLAYING" not in panel.ham_note.text()
        assert panel.receiver_connected is False
    finally:
        _cleanup(panel, app)


def test_late_error_after_power_off_cannot_change_off_state():
    app = QApplication.instance() or QApplication([])
    panel = RadioPanel(confirm=lambda: False)
    try:
        panel.receiver_connected = True
        panel._sdr_state_change("CONNECTING")
        panel.disconnect_receiver()
        assert panel.sdr_state == "OFF"
        panel._sdr_loading_changed(FakeLoadInfo(
            QWebEngineLoadingInfo.LoadStatus.LoadFailedStatus
        ))
        panel._sdr_load_finished(False)
        assert panel.sdr_state == "OFF"
        assert panel._sdr_load_error == ""
        assert not panel.receiver_connected
    finally:
        _cleanup(panel, app)
