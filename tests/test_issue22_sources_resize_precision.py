"""Real Qt 512-row Sources table: bounded header measurement, complete evidence.

This checks exact provider row access and a real Store status transition, not
physical Windows 11 smoothness or working publisher counts.
"""
import threading
import time

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView
from unittest.mock import patch

from global_pulse.controller import Controller
from global_pulse.provider_actions import _existing_source_rows
from global_pulse.source_availability import capability
from global_pulse.ui import MainWindow


def test_sources_header_resize_is_bounded_without_losing_tail_rows(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        exemplar = next(source for source in controller.catalog if capability(source)[0])
        controller.catalog = [
            dict(exemplar, id=f"fictional-resize-{i:03d}",
                 name=f"Fictional resize source {i:03d}",
                 attribution="SYNTHETIC SOURCE; NOT A REAL PUBLISHER")
            for i in range(512)
        ]
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        table = window.source_table
        header = table.horizontalHeader()
        assert table.rowCount() == 512
        assert table.columnCount() == 10
        assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
        assert header.resizeContentsPrecision() == 64

        # A tail provider must remain fully readable/selectable even though
        # content-size calculation no longer visits all 512 model rows.
        sid = "fictional-resize-511"
        controller.store.set_source_state(sid, {
            "status": "error", "error": "SYNTHETIC tail provider timeout",
            "next_poll": "2026-11-18T09:00:00+00:00",
        })
        window._dirty_pages.add(3)
        window._last_navigation_at = time.monotonic() - 3
        window._workspace_warm_timer.stop()
        window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        row = _existing_source_rows(table)[sid]
        assert table.item(row, 0).text() == "Fictional resize source 511"
        assert table.item(row, 3).text() == "Last check failed"
        assert table.item(row, 6).text() != "—"
        assert table.item(row, 0).data(Qt.ItemDataRole.UserRole)["id"] == sid

        # Enabling the user's sorting choice must not hide/remove tail rows or
        # resolve the selected detail to another provider after reordering.
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.SortOrder.DescendingOrder)
        row = _existing_source_rows(table)[sid]
        table.setCurrentCell(row, 0)
        window._source_selected()
        assert "Fictional resize source 511" in window.source_browser.toPlainText()
        assert "SYNTHETIC tail provider timeout" in window.source_browser.toPlainText()
        assert header.resizeContentsPrecision() == 64
    finally:
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


def test_evidence_only_idle_does_not_rebuild_sources_or_swallow_status(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        window._workspace_warm_timer.stop()
        assert not window._dirty_pages
        sid = next(source["id"] for source in controller.catalog if capability(source)[0])

        def pump(predicate, seconds=8):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate():
                    return True
                QTest.qWait(25)
            return False

        # The real same-Store worker path (no mock evidence) must apply a new
        # archive snapshot without touching the unrelated Sources Qt table.
        window._last_full_refresh_at = time.monotonic() - 10
        before = window._last_full_refresh_at
        with patch.object(window, "_populate_sources",
                          side_effect=AssertionError("Evidence only rebuilt Sources")):
            window._start_idle_snapshot()
            assert pump(lambda: not window._idle_snapshot_inflight
                        and window._last_full_refresh_at > before)
            window._workspace_warm_timer.stop()
            assert 3 not in window._dirty_pages

        # A real source status update can be queued while another archive
        # snapshot is applied. Do not cancel/drop its status-only timer.
        controller.store.set_source_state(sid, {
            "status": "error", "error": "SYNTHETIC source status failure",
        })
        controller.source_status_changed.emit()
        assert window._collection_refresh_timer.isActive()
        # Hold the timer past the archive apply for a deterministic race.
        window._collection_refresh_timer.start(6000)
        window._last_full_refresh_at = time.monotonic() - 10
        before = window._last_full_refresh_at
        window._start_idle_snapshot()
        assert pump(lambda: not window._idle_snapshot_inflight
                    and window._last_full_refresh_at > before)
        assert window._collection_refresh_timer.isActive(), (
            "Evidence-only refresh swallowed a newer provider status signal")
        window._collection_refresh_timer.stop()
        window._refresh_source_status_ui()
        assert 3 in window._dirty_pages
        # Real idle scheduler prioritizes Situations/Economy before Sources.
        # Honor that scheduling order instead of falsely assuming the first
        # warm callback immediately reaches the provider table.
        for _ in range(6):
            if 3 not in window._dirty_pages:
                break
            window._last_navigation_at = time.monotonic() - 3
            window._workspace_warm_timer.stop()
            window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert 3 not in window._dirty_pages, "Queued provider health was not reached"
        row = _existing_source_rows(window.source_table)[sid]
        assert window.source_table.item(row, 3).text() == "Last check failed"
    finally:
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



def test_no_click_sources_and_snapshot_defer_busy_store_without_losing_status(tmp_path, monkeypatch):
    """A real worker-held SQLite lock must not become a hidden Qt wait."""
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    release = threading.Event()
    locked = threading.Event()
    worker = None
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        window._workspace_warm_timer.stop()
        sid = next(source["id"] for source in controller.catalog
                   if capability(source)[0])
        controller.store.set_source_state(sid, {
            "status": "error", "error": "SYNTHETIC lock-race failure",
            "next_poll": "2026-11-18T09:00:00+00:00",
        })
        revision = controller.store.content_revision()
        snapshot = {
            "generation": window._idle_snapshot_generation,
            "scope": window._archive_scope_key(),
            "revision_before": revision, "revision_after": revision,
            "brief_pending": False,
        }

        def hold_sqlite_lock():
            with controller.store._lock:
                locked.set()
                release.wait(5)

        worker = threading.Thread(target=hold_sqlite_lock, daemon=True)
        worker.start()
        assert locked.wait(5), "The real Store worker never acquired its lock"
        assert controller.store.content_revision_if_available() is None
        window._dirty_pages.clear()
        window._dirty_pages.add(3)
        window._last_navigation_at = time.monotonic() - 3
        with patch.object(window, "_populate_sources",
                          side_effect=AssertionError("Hidden Sources blocked on worker")):
            start = time.perf_counter()
            window._warm_next_workspace()
            elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 100, f"Qt waited {elapsed_ms:.1f} ms for a worker lock"
        assert 3 in window._dirty_pages, "Busy Store dropped a real status update"
        assert window._workspace_warm_timer.isActive()

        applied = []
        with monkeypatch.context() as m:
            m.setattr(window, "refresh_data",
                      lambda *args, **kwargs: applied.append(kwargs))
            start = time.perf_counter()
            window._apply_idle_snapshot(snapshot)
            assert (time.perf_counter() - start) * 1000 < 100, (
                "Idle revision validation blocked on background SQLite")
            assert not applied, "Busy revision was incorrectly accepted as current"
            release.set()
            worker.join(5)
            assert not worker.is_alive()
            # A deferred snapshot is checked again and can only be accepted
            # after the Store lock is released and the revision still matches.
            QTest.qWait(320)
            assert len(applied) == 1
            assert applied[0]["_idle_snapshot"] is snapshot

        window._workspace_warm_timer.stop()
        window._last_navigation_at = time.monotonic() - 3
        window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert 3 not in window._dirty_pages
        row = _existing_source_rows(window.source_table)[sid]
        assert window.source_table.item(row, 3).text() == "Last check failed"
    finally:
        release.set()
        if worker is not None:
            worker.join(5)
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
