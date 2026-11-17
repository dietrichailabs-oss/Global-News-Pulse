"""No-click idle Economy warmup shares the *same* dated source revision as map.

This is a real Qt/SQLite regression, never a claim of physical Windows smoothness.
"""
from __future__ import annotations

import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _observation(number):
    return {
        "indicator": "synthetic_growth",
        "indicator_name": "Synthetic growth test only",
        "country": "Test Country %03d" % number,
        "date": str(2010 + number % 12),
        "value": float(number),
        "source_id": "synthetic-offline",
        "url": "https://example.invalid/economy/%d" % number,
        "synthetic": True,
    }


def _close(app, window, controller):
    if window is not None:
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer"):
            getattr(window, name).stop()
        window._force_close = True
        window.media.shutdown()
        window.close()
        window.deleteLater()
    controller.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_idle_economy_prewarm_uses_once_source_revision_without_second_sqlite(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        assert controller.store.put_observations([_observation(i) for i in range(48)]) == 48
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        window.open_page(0)
        window.refresh_data()
        assert window._deferred_economy_observations is not None
        assert len(window._deferred_economy_observations) == 48

        # A real post-splash deferred warm, not a tab click: the source
        # revision was already read for the map. No second SQLite read.
        window._dirty_pages = {2}
        window._last_navigation_at = time.monotonic() - 3
        with patch.object(controller.store, "list_observations",
                          side_effect=AssertionError("redundant idle SQLite observation scan")):
            window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert len(window._observations) == 48
        assert window._deferred_economy_observations is None
        assert window.economy_model.rowCount() >= 0

        # One-use contract: a later independent activation after new local
        # source evidence MUST query current Store rows, not reuse old cache.
        assert controller.store.put_observations([_observation(999)]) == 1
        with patch.object(controller.store, "list_observations",
                          wraps=controller.store.list_observations) as reads:
            window._populate_economy()
            assert reads.call_count == 1
        assert len(window._observations) == 49
        assert any(o.get("value") == 999.0 for o in window._observations)
    finally:
        _close(app, window, controller)


def test_new_collector_refresh_replaces_unconsumed_idle_observation_snapshot(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        assert controller.store.put_observations([_observation(i) for i in range(7)]) == 7
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        window.open_page(0)
        window.refresh_data()
        assert len(window._deferred_economy_observations) == 7

        # Collector changes the source before the hidden tab is warmed.
        assert controller.store.put_observations([_observation(888)]) == 1
        window.refresh_data()
        assert len(window._deferred_economy_observations) == 8

        window._dirty_pages = {2}
        window._last_navigation_at = time.monotonic() - 3
        with patch.object(controller.store, "list_observations",
                          side_effect=AssertionError("second read after current refresh")):
            window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert len(window._observations) == 8
        assert window._deferred_economy_observations is None
    finally:
        _close(app, window, controller)
