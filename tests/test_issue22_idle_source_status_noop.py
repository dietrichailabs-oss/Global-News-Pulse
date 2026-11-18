"""Real Qt regression: status-only collector callbacks must not rebuild idle source rows.

Offline fictional states; this measures work avoided, not physical Win11 smoothness.
"""
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.provider_actions import _existing_source_rows
from global_pulse.source_availability import capability
from global_pulse.ui import MainWindow


def _stop(app, window, controller):
    if window is not None:
        window._force_close = True
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer"):
            getattr(window, name).stop()
        window.media.shutdown()
        window.close()
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _warm_source_status(window):
    window._collection_refresh_timer.stop()
    window._refresh_source_status_ui()
    assert 3 in window._dirty_pages
    window._workspace_warm_timer.stop()
    window._last_navigation_at = time.monotonic() - 3
    window._warm_next_workspace()
    window._workspace_warm_timer.stop()
    assert 3 not in window._dirty_pages


def test_repeated_unchanged_source_status_signals_do_not_reconcile_qt_table(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        assert window._source_status_render_key is not None
        assert not window._dirty_pages
        count = window.source_table.rowCount()
        assert count == len(controller.catalog) > 0

        # This is an actual post-splash, no-click burst of source-status
        # signals, not an unmeasured stub of the idle timer path.
        for _ in range(40):
            controller.source_status_changed.emit()
        # A status-only signal invokes _refresh_source_status_ui and schedules
        # the same idle workspace warm callback used by the real application.
        # If no SQLite mutation occurred, no source table rows should be
        # rescanned, cell widgets recreated, or sorting state toggled.
        with patch("global_pulse.provider_actions._existing_source_rows",
                   side_effect=AssertionError("unchanged 10-column table rebuilt")):
            with patch.object(controller.store, "get_source_state",
                              side_effect=AssertionError("unchanged row read")):
                _warm_source_status(window)
        assert window.source_table.rowCount() == count
        assert window._source_status_render_key is not None
    finally:
        _stop(app, window, controller)


def test_real_source_checkpoint_and_enabled_state_invalidate_idle_fast_path(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        assert not window._dirty_pages
        source = next(s for s in controller.catalog if capability(s)[0])
        sid = source["id"]
        row = _existing_source_rows(window.source_table)[sid]
        assert window.source_table.item(row, 3).text() == "Not checked"

        # A real state mutation must be visible even if only status changed,
        # with no article/observation ingestion and no user tab navigation.
        controller.store.set_source_state(sid, {
            "status": "error", "error": "SYNTHETIC offline provider timeout",
        })
        _warm_source_status(window)
        row = _existing_source_rows(window.source_table)[sid]
        assert window.source_table.item(row, 3).text() == "Last check failed"

        # A second no-op pulse must now be skipped; a new successful check
        # must visibly supersede the error rather than being cached away.
        with patch("global_pulse.provider_actions._existing_source_rows",
                   side_effect=AssertionError("identical state rebuilt")):
            _warm_source_status(window)
        controller.store.set_source_state(sid, {
            "status": "available", "last_success": "2026-11-17T22:00:00+00:00",
            "latest_publication": "2026-11-17T21:00:00+00:00",
        })
        _warm_source_status(window)
        row = _existing_source_rows(window.source_table)[sid]
        assert window.source_table.item(row, 3).text() == "Last check succeeded"
    finally:
        _stop(app, window, controller)
