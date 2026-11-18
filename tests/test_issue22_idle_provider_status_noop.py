"""Issue22 idle provider health: no-change GUI work and actual updates.

Offline Store/Qt contract only. No live publisher probe or physical Windows
performance/playback/release claim.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.provider_actions import populate_sources
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
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_store_batch_provider_status_retains_exact_states_and_missing(tmp_path):
    controller = Controller(tmp_path, demo=True)
    try:
        states = {
            "test-src-000": {"status": "available", "last_success": "2026-11-17T00:00:00Z"},
            "test-src-401": {"status": "denied", "error": "403", "next_poll": "2026-11-18T00:00:00Z"},
        }
        for key, state in states.items():
            controller.store.set_source_state(key, state)
        identities = ["test-src-%03d" % i for i in range(435)]
        bulk = controller.store.list_source_states(identities + ["test-src-401"])
        assert bulk == states
        assert controller.store.list_source_states(["test-src-000", "test-src-000"]) == {
            "test-src-000": states["test-src-000"]}
        assert controller.store.list_source_states([]) == {}
        for key in ("test-src-000", "test-src-401", "test-src-200"):
            assert bulk.get(key, {}) == controller.store.get_source_state(key)
    finally:
        controller.close()


def test_no_change_idle_provider_refresh_skips_qt_layout_but_real_health_updates(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        assert window.prepare_initial_workspaces()
        window._workspace_warm_timer.stop()
        assert window._source_display_values

        table = window.source_table
        model = table.model()
        layout_changes = QSignalSpy(model.layoutChanged)
        item_changes = QSignalSpy(model.dataChanged)
        cache_before = window._source_display_values.copy()
        # This was a 100+-row Qt re-sort/re-layout on every coalesced
        # status signal even when the underlying states had not changed.
        populate_sources(window)
        assert window._source_display_values == cache_before
        assert len(layout_changes) == 0, "Unchanged health must not re-layout source table"
        assert len(item_changes) == 0, "Unchanged health must not repaint source cells"

        sid = next(s["id"] for s in controller.catalog if capability(s)[0])
        row = next(i for i in range(table.rowCount())
                   if (table.item(i, 0).data(Qt.ItemDataRole.UserRole) or {}).get("id") == sid)
        item_before = table.item(row, 0)
        table.selectRow(row)
        at = datetime.now(timezone.utc).isoformat()
        controller.store.set_source_state(sid, {
            "status": "rate_limited",
            "last_success": at, "latest_publication": at, "next_poll": at,
        })
        populate_sources(window)
        actual_row = next(i for i in range(table.rowCount())
                          if (table.item(i, 0).data(Qt.ItemDataRole.UserRole) or {}).get("id") == sid)
        assert table.item(actual_row, 0) is item_before
        assert "Rate limited" in table.item(actual_row, 3).text()
        assert "Rate limited" in window.source_browser.toPlainText()
        assert window._source_display_values[sid] != cache_before[sid]
        new_layout_changes = len(layout_changes)
        new_item_changes = len(item_changes)
        populate_sources(window)
        assert len(layout_changes) == new_layout_changes
        assert len(item_changes) == new_item_changes

        # A genuine transition to a successful provider check must not stay
        # hidden behind the no-op cache, even with an identical catalog.
        controller.store.set_source_state(sid, {
            "status": "available", "last_success": at, "latest_publication": at,
        })
        populate_sources(window)
        actual_row = next(i for i in range(table.rowCount())
                          if (table.item(i, 0).data(Qt.ItemDataRole.UserRole) or {}).get("id") == sid)
        assert "Last check succeeded" in table.item(actual_row, 3).text()
        assert "Last check succeeded" in window.source_browser.toPlainText()
        assert not controller.monitoring
    finally:
        _close(app, window, controller)
