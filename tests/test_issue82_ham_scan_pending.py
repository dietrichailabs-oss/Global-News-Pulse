"""Issue #82: receiver scan must not cancel an asynchronous in-flight tune.

Offline Qt state-machine regressions only. These tests do not establish SDR
network connectivity, audio playback, publisher permission or Win11 stability.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.internet_radio import RadioPanel


def _panel():
    app = QApplication.instance() or QApplication([])
    panel = RadioPanel(confirm=lambda: False)
    panel._select_na5b_test()
    panel.receiver_connected = True
    panel._sdr_state_change("ON", "Earlier page loaded; audio not verified")
    return app, panel


def _dispose(app, panel):
    panel.shutdown()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _armed(panel):
    panel.scan_frequency = 14250.0
    panel.scan_end = 14260.0
    panel.scan_step = 5.0
    panel.scan_direction = 1
    panel.scan_timer.setInterval(1000)
    panel.scan_timer.start()


def test_pending_scan_ticks_do_not_skip_frequency_or_cancel_first_navigation(monkeypatch):
    app, panel = _panel()
    calls = []
    try:
        _armed(panel)

        def reload(frequency=None):
            calls.append(frequency)
            panel._sdr_state_change("CONNECTING", "Page still loading")
            return True

        monkeypatch.setattr(panel, "tune_receiver", reload)
        panel._sdr_state_change("CONNECTING", "Initial scan page pending")
        for _ in range(4):
            panel._scan_next()
        assert panel.scan_frequency == 14250.0
        assert calls == []
        assert panel.scan_timer.isActive()

        # Only after the previous main page finishes may the scanner advance.
        panel._sdr_state_change("ON", "Receiver page loaded; no audio proof")
        panel._scan_next()
        assert calls == [14255.0]
        assert panel.scan_frequency == 14255.0
        assert panel.sdr_state == "CONNECTING"
        panel._scan_next()
        assert calls == [14255.0]
        assert panel.scan_frequency == 14255.0
        panel._sdr_state_change("ON", "Next page loaded")
        panel._scan_next()
        assert calls == [14255.0, 14260.0]
    finally:
        _dispose(app, panel)


def test_error_or_off_scanner_never_reactivates_connection(monkeypatch):
    app, panel = _panel()
    calls = []
    try:
        monkeypatch.setattr(panel, "tune_receiver", lambda *a, **k: calls.append(a) or True)
        for bad_state in ("ERROR", "OFF"):
            _armed(panel)
            panel._sdr_state_change(bad_state, "Receiver unavailable")
            panel._scan_next()
            assert panel.scan_frequency is None
            assert not panel.scan_timer.isActive()
        assert calls == []
    finally:
        _dispose(app, panel)


def test_start_scan_displays_pending_not_already_scanning(monkeypatch):
    app, panel = _panel()
    try:
        panel.scan_start.setText("14250")
        panel.scan_end_edit.setText("14260")
        panel.scan_step_edit.setText("5")
        panel.scan_dwell.setText("1")
        def initial(frequency=None):
            panel._sdr_state_change("CONNECTING", "Waiting for receiver")
            return True
        monkeypatch.setattr(panel, "tune_receiver", initial)
        assert panel.start_scan() is True
        assert panel.sdr_state == "CONNECTING"
        assert panel.scan_timer.isActive()
        assert "SDR SCAN PENDING" in panel.ham_note.text()
        assert "not verified" in panel.ham_note.text().lower()
        assert panel.scan_frequency == 14250.0
    finally:
        _dispose(app, panel)
