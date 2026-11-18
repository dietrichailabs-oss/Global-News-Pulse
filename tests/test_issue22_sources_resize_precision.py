"""Real Qt 512-row Sources table: bounded header measurement, complete evidence.

This checks exact provider row access and a real Store status transition, not
physical Windows 11 smoothness or working publisher counts.
"""
import time

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QHeaderView

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
