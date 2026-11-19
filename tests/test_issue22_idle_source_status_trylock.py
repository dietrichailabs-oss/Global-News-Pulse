"""Real Qt Issue22: idle Sources status must not wait for collector SQLite.

Synthetic provider checkpoints only; hosted GUI heartbeat is not physical
Windows 11, media playback, independent QA or public release acceptance.
"""
import threading
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
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


def _ready(app, window):
    window.show()
    app.processEvents()
    assert window.prepare_initial_workspaces()
    window._background_warm_enabled = True
    window._last_navigation_at = time.monotonic() - 10
    window._dirty_pages = {3}
    window._workspace_warm_timer.stop()


def _source_id(controller):
    return next(s["id"] for s in controller.catalog if capability(s)[0])


def test_sources_second_lock_race_defers_and_real_qt_heartbeat_continues(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    held, release = threading.Event(), threading.Event()
    locker = None
    try:
        window = MainWindow(controller)
        _ready(app, window)
        sid = _source_id(controller)
        controller.store.set_source_state(sid, {
            "status": "error", "error": "SYNTHETIC lock-race timeout"})
        row = _existing_source_rows(window.source_table)[sid]
        previous = window.source_table.item(row, 3).text()
        original_probe = controller.store.content_revision_if_available
        probed = [0]

        def occupy():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        def racing_probe():
            revision = original_probe()
            probed[0] += 1
            if probed[0] == 1:
                nonlocal locker
                locker = threading.Thread(target=occupy, daemon=True)
                locker.start()
                assert held.wait(timeout=2)
            return revision

        with patch.object(controller.store, "content_revision_if_available",
                          side_effect=racing_probe), \
             patch.object(controller.store, "list_source_states",
                          side_effect=AssertionError("Sources SQL waited on Qt")), \
             patch.object(controller.store, "content_revision",
                          side_effect=AssertionError("Qt blocking revision")), \
             patch.object(controller.store, "get_setting",
                          side_effect=AssertionError("Qt blocking preference")):
            started = time.monotonic()
            window._warm_next_workspace()
            elapsed = time.monotonic() - started
            assert elapsed < .6, elapsed
            assert 3 in window._dirty_pages
            assert window._workspace_warm_timer.isActive()
            assert window.source_table.item(row, 3).text() == previous
            # Real Qt timer callbacks, not a fake/mocked heartbeat.
            ticks = []
            timer = QTimer()
            timer.setInterval(20)
            timer.timeout.connect(lambda: ticks.append(time.monotonic()))
            timer.start()
            until = time.monotonic() + .18
            while time.monotonic() < until:
                app.processEvents()
                time.sleep(.005)
            timer.stop()
            assert len(ticks) >= 3, ticks
        release.set()
        locker.join(timeout=3)
        assert not locker.is_alive()
        window._workspace_warm_timer.stop()
        window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert 3 not in window._dirty_pages
        assert window.source_table.item(row, 3).text() == "Last check failed"
    finally:
        release.set()
        if locker is not None:
            locker.join(timeout=4)
        _close(app, window, controller)


def test_idle_status_atomic_settings_and_512_provider_rows(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        source = next(s for s in controller.catalog if capability(s)[0])
        controller.catalog = [dict(source, id=f"synthetic-source-{i:03d}",
                                   name=f"FICTIONAL Source {i:03d}") for i in range(512)]
        sid = "synthetic-source-417"
        controller.store.set_source_state(sid, {
            "status": "error", "error": "SYNTHETIC offline provider error"})
        window = MainWindow(controller)
        _ready(app, window)
        controller.store.set_setting("enabled_sources", [])
        with patch.object(controller.store, "get_setting",
                          side_effect=AssertionError("Qt setting lock")), \
             patch.object(controller.store, "content_revision",
                          side_effect=AssertionError("Qt revision lock")):
            assert window._populate_sources(idle=True) is True
        rows = _existing_source_rows(window.source_table)
        assert len(rows) == 512
        assert window.source_table.item(rows[sid], 3).text() == "Last check failed"
        assert window.source_table.item(rows[sid], 2).text() == "Off"
        assert controller.store.source_status_snapshot_if_available(
            s["id"] for s in controller.catalog)["states"][sid]["status"] == "error"
    finally:
        _close(app, window, controller)


def test_source_checkpoint_write_during_ui_reconcile_keeps_dirty(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        _ready(app, window)
        sid = _source_id(controller)
        controller.store.set_source_state(sid, {
            "status": "error", "error": "SYNTHETIC earlier failure"})
        from global_pulse import provider_actions
        original = provider_actions.health_text
        wrote = [False]

        def concurrent_checkpoint(state):
            if not wrote[0]:
                wrote[0] = True
                controller.store.set_source_state(sid, {
                    "status": "rate_limited",
                    "next_poll": "2026-11-19T05:00:00+00:00"})
            return original(state)

        with patch.object(provider_actions, "health_text",
                          side_effect=concurrent_checkpoint):
            window._warm_next_workspace()
        assert wrote == [True]
        assert 3 in window._dirty_pages, "mixed revision accepted as current"
        assert window._source_status_render_key is None
        window._workspace_warm_timer.stop()
        window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert 3 not in window._dirty_pages
        row = _existing_source_rows(window.source_table)[sid]
        assert window.source_table.item(row, 3).text() == (
            "Rate limited; waiting for provider retry")
    finally:
        _close(app, window, controller)
