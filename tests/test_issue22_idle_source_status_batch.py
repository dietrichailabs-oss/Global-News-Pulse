"""Real Qt/source-status post-splash work: bounded bulk SQLite reads.

Synthetic provider states only, not physical Windows smoothness acceptance.
"""
import time
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.provider_actions import _existing_source_rows
from global_pulse.source_availability import capability
from global_pulse.ui import MainWindow


def _close(app, window, controller):
    if window is not None:
        window._force_close = True
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer", "search_timer"):
            getattr(window, name).stop()
        window.media.shutdown()
        window.close()
        window.deleteLater()
    controller.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _warm(window):
    window._refresh_source_status_ui()
    window._workspace_warm_timer.stop()
    window._last_navigation_at = time.monotonic() - 3
    window._warm_next_workspace()
    window._workspace_warm_timer.stop()
    assert 3 not in window._dirty_pages


def test_source_health_bulk_400_boundary_and_missing_ids(tmp_path):
    controller = Controller(tmp_path, demo=True)
    try:
        ids = [f"fictional-source-{i}" for i in range(425)]
        for i in (0, 399, 400, 424):
            controller.store.set_source_state(
                ids[i], {"status": "error", "error": f"SYNTHETIC-{i}"})
        states = controller.store.list_source_states(ids + [ids[399]])
        assert set(states) == {ids[i] for i in (0, 399, 400, 424)}
        assert states[ids[400]]["error"] == "SYNTHETIC-400"
        assert ids[401] not in states
        controller.store.set_source_state(ids[399], {"status": "available"})
        assert controller.store.list_source_states([ids[399]])[ids[399]]["status"] == "available"
    finally:
        controller.close()


def test_no_click_hidden_source_warm_uses_single_batch_and_keeps_freshness(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        assert not window._dirty_pages
        sid = next(s["id"] for s in controller.catalog if capability(s)[0])
        old_key = window._source_status_render_key
        controller.store.set_source_state(
            sid, {"status": "error", "error": "SYNTHETIC provider timeout"})
        original = controller.store.list_source_states
        with patch.object(controller.store, "get_source_state",
                          side_effect=AssertionError("per-source SELECT on GUI")):
            with patch.object(controller.store, "list_source_states",
                              wraps=original) as batch:
                _warm(window)
                assert batch.call_count == 1
        row = _existing_source_rows(window.source_table)[sid]
        assert window.source_table.item(row, 3).text() == "Last check failed"
        assert window._source_status_render_key != old_key
        # An unchanged signal still performs no SQLite batch or row reconciliation.
        with patch.object(controller.store, "list_source_states",
                          side_effect=AssertionError("unchanged state queried")):
            _warm(window)
        controller.store.set_source_state(
            sid, {"status": "available",
                  "last_success": "2026-11-18T02:00:00+00:00"})
        _warm(window)
        row = _existing_source_rows(window.source_table)[sid]
        # A successful connection cannot fabricate publication freshness.
        assert window.source_table.item(row, 3).text() == (
            "Last check succeeded; publication freshness unknown")
    finally:
        _close(app, window, controller)
