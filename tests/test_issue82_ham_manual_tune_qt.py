"""Issue #82: Qt clicked(bool) must not override a manually entered SDR frequency.

Offline real-Qt UI tests only; they do not probe NA5B or certify audio,
WebEngine playback, provider rights, or physical Windows 11 responsiveness.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.internet_radio import RadioPanel


def _panel():
    app = QApplication.instance() or QApplication([])
    panel = RadioPanel(confirm=lambda: False)
    panel._select_na5b_test()
    return app, panel


def _dispose(app, panel):
    panel.shutdown()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_actual_qt_tune_click_uses_input_frequency_not_clicked_checked_flag(monkeypatch):
    app, panel = _panel()
    loads = []
    try:
        panel.frequency.setText("14250.5")
        panel.scan_frequency = 14250.0
        panel.scan_end = 14300.0
        panel.scan_step = 5.0
        panel.scan_timer.setInterval(3000)
        panel.scan_timer.start()

        def fake_load(url, host, *, require_consent=False):
            loads.append((url, host, require_consent))
            panel.receiver_connected = True
            panel._sdr_state_change("CONNECTING", "Loading fixture page; no audio proof")
            return True

        monkeypatch.setattr(panel, "_load_receiver_url", fake_load)
        panel.tune_button.click()  # Qt clicked(bool=False) must NOT mean frequency=False.

        assert len(loads) == 1
        assert loads[0][2] is True
        assert parse_qs(urlsplit(loads[0][0]).query)["tune"] == ["14250.5usb"]
        assert panel.frequency.text() == "14250.5"
        assert panel.sdr_state == "CONNECTING"
        assert "SDR TUNING" in panel.ham_note.text()
        assert "not yet verified" in panel.ham_note.text()
        # Explicit manual Tune must take control from an automatic scan.
        assert panel.scan_frequency is None
        assert panel.scan_end is None
        assert panel.scan_step is None
        assert not panel.scan_timer.isActive()
    finally:
        _dispose(app, panel)


def test_programmatic_scan_tune_still_uses_supplied_frequency(monkeypatch):
    app, panel = _panel()
    loads = []
    try:
        panel.frequency.setText("7100")
        panel.scan_frequency = 14250.0
        panel.scan_end = 14300.0
        panel.scan_step = 5.0
        panel.scan_timer.setInterval(3000)
        panel.scan_timer.start()

        def fake_load(url, host, *, require_consent=False):
            loads.append(url)
            panel.receiver_connected = True
            panel._sdr_state_change("CONNECTING", "Pending fixture")
            return True

        monkeypatch.setattr(panel, "_load_receiver_url", fake_load)
        assert panel.tune_receiver(14255.0) is True
        assert len(loads) == 1
        assert parse_qs(urlsplit(loads[0]).query)["tune"] == ["14255usb"]
        assert panel.frequency.text() == "14255"
        # Internal scan Tune does not call the manual cancellation handler.
        assert panel.scan_frequency == 14250.0
        assert panel.scan_timer.isActive()
    finally:
        _dispose(app, panel)
