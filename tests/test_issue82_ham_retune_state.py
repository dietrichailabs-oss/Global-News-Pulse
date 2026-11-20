"""Issue #82: re-tuning a loaded SDR is a new asynchronous receiver load.

These are offline Qt state/dispatch tests. No live NA5B HTTP/8901 connectivity,
radio playback, rights approval, or packaged Win11 behavior is claimed.
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.internet_radio import RadioPanel


def _dispose(panel, app):
    panel.shutdown()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _loaded_na5b_panel():
    app = QApplication.instance() or QApplication([])
    panel = RadioPanel(confirm=lambda: False)
    panel._select_na5b_test()
    panel.receiver_host = "na5b.com"
    panel.receiver_origin = ("http", 8901, "na5b.com")
    panel.receiver_connected = True
    panel._sdr_state_change("ON", "Previous WebSDR page loaded; audio unverified")
    return app, panel


def test_same_origin_tune_routes_via_pending_lifecycle_not_untracked_view_load(monkeypatch):
    app, panel = _loaded_na5b_panel()
    loads = []
    try:
        def pending(url, host, *, require_consent=False):
            loads.append((url, host, require_consent))
            panel._sdr_load_error = ""
            panel._sdr_state_change("CONNECTING", "New receiver request pending")
            return True
        monkeypatch.setattr(panel, "_load_receiver_url", pending)
        assert panel.tune_receiver(14250.0)
        assert len(loads) == 1
        url, host, consent = loads[0]
        assert url.startswith("http://na5b.com:8901/?tune=14250")
        assert host == "na5b.com"
        assert consent is False  # same already-consented origin only
        assert panel.sdr_state == "CONNECTING"
        assert "SDR TUNING" in panel.ham_note.text()
        assert "not yet verified" in panel.ham_note.text().lower()
        assert "SDR TUNED" not in panel.ham_note.text()
        panel._sdr_load_finished(False)
        assert panel.sdr_state == "ERROR"
        assert panel.receiver_connected is False
    finally:
        _dispose(panel, app)


def test_pending_same_origin_retune_must_not_appear_on_before_completion(monkeypatch):
    app, panel = _loaded_na5b_panel()
    try:
        panel._sdr_state_change("CONNECTING")
        calls = []
        def pending(url, host, *, require_consent=False):
            calls.append(url)
            panel._sdr_state_change("CONNECTING")
            return True
        monkeypatch.setattr(panel, "_load_receiver_url", pending)
        assert panel.tune_receiver(14255)
        # R20 must not overlap an already-CONNECTING same-view navigation.
        # The newest user-requested tune is queued for the earlier load's
        # completion; it is not loaded early or reported as playable.
        assert calls == [], "No overlapping receiver navigation"
        assert panel._pending_tune is not None
        url, host = panel._pending_tune
        assert url.startswith("http://na5b.com:8901/?tune=14255")
        assert host == "na5b.com"
        assert panel.sdr_state == "CONNECTING"
        assert "loaded" not in panel.sdr_status.text().lower()
    finally:
        _dispose(panel, app)


def test_retune_failed_to_start_keeps_original_error_and_no_false_tuned(monkeypatch):
    app, panel = _loaded_na5b_panel()
    try:
        def refusal(url, host, *, require_consent=False):
            panel._sdr_state_change("ERROR", "New receiver load could not start")
            return False
        monkeypatch.setattr(panel, "_load_receiver_url", refusal)
        assert panel.tune_receiver(14255) is False
        assert panel.sdr_state == "ERROR"
        assert "New receiver load could not start" in panel.ham_note.text()
        assert "SDR TUNED" not in panel.ham_note.text()
    finally:
        _dispose(panel, app)
