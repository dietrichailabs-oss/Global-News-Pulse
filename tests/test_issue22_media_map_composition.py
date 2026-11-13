"""Issue #22 composed desktop evidence: single media plus retained source/map path.
Offline only. Engineering regression, not independent QA or playback proof.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import pytest
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.map_widget import WorldMap
from global_pulse.single_media import MediaPanel
from global_pulse.internet_radio import RadioPanel


def _desktop(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = MainWindow(controller)
    return app, controller, window


def _close(app, controller, window):
    window.media.shutdown()
    window._force_close = True
    window.close()
    controller.close()
    window.deleteLater()
    app.processEvents()


def test_main_window_uses_single_tv_radio_and_real_world_map(tmp_path):
    app, controller, window = _desktop(tmp_path)
    try:
        assert isinstance(window.media, MediaPanel)
        assert isinstance(window.world_map, WorldMap)
        assert len(window.media.tiles) == 1
        assert window.media.tiles[0] is window.media.tv
        assert isinstance(window.media.radio, RadioPanel)
        assert [window.media.tabs.tabText(i) for i in range(3)] == ["TV", "Radio", "Cameras"]
        assert window.media.tv._builtins == []
        assert window.media.tv.tv_status.text() == "OFF"
        assert window.media.radio.status.text() == "OFF"
        assert window.media.radio._session is None
    finally:
        _close(app, controller, window)


def test_map_navigation_refresh_cannot_activate_off_radio(tmp_path):
    app, controller, window = _desktop(tmp_path)
    try:
        assert window.world_map.select_country("Ukraine")
        window.media.tabs.setCurrentIndex(1)
        window.media.radio.selector.setCurrentIndex(1)
        controller.data_changed.emit()
        app.processEvents()
        assert window.world_map.selected_country == "Ukraine"
        assert window.media.radio.status.text() == "OFF"
        assert window.media.radio._session is None
        assert not window.media.radio.power.isChecked()
        window.media.stop()
        assert window.media.radio.status.text() == "OFF"
    finally:
        _close(app, controller, window)

def test_startup_initializer_is_visible_until_real_desktop_is_ready(tmp_path):
    """A painted initialization notice precedes Store/UI loading, then closes.

    This checks the actual Qt display/lifecycle in offscreen mode, not physical
    Windows 11 responsiveness or whether a long Store migration can still stall.
    """
    from global_pulse.__main__ import show_initialization_splash

    app = QApplication.instance() or QApplication([])
    splash = show_initialization_splash(app)
    assert splash.isVisible()
    assert splash.accessibleName() == "Global Pulse initializing"
    assert "INITIALIZING GLOBAL PULSE" in splash.message()
    assert "local archive" in splash.message()
    # Qt's default QSplashScreen closes on a click; that would falsely show an
    # apparently stuck/blank app while its Store and map are still initializing.
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    QTest.mouseClick(splash, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert splash.isVisible()

    controller = None
    window = None
    try:
        controller = Controller(tmp_path, demo=True)
        window = MainWindow(controller)
        assert splash.isVisible(), "Do not expose partially initialized controls"
        window.show()
        splash.finish(window)
        app.processEvents()
        assert not splash.isVisible()
        assert window.isVisible()
        assert isinstance(window.world_map, WorldMap)
    finally:
        splash.close()
        if window is not None:
            _close(app, controller, window)
        elif controller is not None:
            controller.close()


def test_failed_startup_releases_controller_sqlite_lock_and_splash(tmp_path, monkeypatch):
    """A real constructed Controller must close when MainWindow construction fails."""
    from global_pulse.__main__ import (
        _NonDismissableStartupSplash, construct_startup_desktop
    )
    from global_pulse.single_instance import SingleInstance
    from global_pulse import controller as controller_module
    from global_pulse import ui as ui_module

    app = QApplication.instance() or QApplication([])
    first = SingleInstance(tmp_path)
    assert first.acquire()
    created = []
    original = controller_module.Controller

    class TrackedController(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    def fail_window(_controller):
        raise RuntimeError("injected dashboard constructor failure")

    monkeypatch.setattr(controller_module, "Controller", TrackedController)
    monkeypatch.setattr(ui_module, "MainWindow", fail_window)
    with pytest.raises(RuntimeError, match="injected dashboard"):
        construct_startup_desktop(app, tmp_path, first, demo=True)

    assert len(created) == 1
    assert created[0]._store_closed
    assert created[0]._closed
    assert not first.owner
    app.processEvents()
    assert not any(
        isinstance(widget, _NonDismissableStartupSplash) and widget.isVisible()
        for widget in app.topLevelWidgets()
    )
    # If the original lock or local IPC server were stranded, this admission
    # would instead route an activation to the failed first process.
    next_instance = SingleInstance(tmp_path)
    try:
        assert next_instance.acquire()
        assert next_instance.owner
    finally:
        next_instance.close()


def test_failed_store_constructor_still_releases_single_instance(tmp_path, monkeypatch):
    """Failure before controller assignment also cleans up the owned IPC lock."""
    from global_pulse.__main__ import (
        _NonDismissableStartupSplash, construct_startup_desktop
    )
    from global_pulse.single_instance import SingleInstance
    from global_pulse import controller as controller_module

    app = QApplication.instance() or QApplication([])
    first = SingleInstance(tmp_path)
    assert first.acquire()

    def fail_store(*_args, **_kwargs):
        raise RuntimeError("injected local store constructor failure")

    monkeypatch.setattr(controller_module, "Controller", fail_store)
    with pytest.raises(RuntimeError, match="injected local store"):
        construct_startup_desktop(app, tmp_path, first, demo=True)
    assert not first.owner
    app.processEvents()
    assert not any(
        isinstance(widget, _NonDismissableStartupSplash) and widget.isVisible()
        for widget in app.topLevelWidgets()
    )
    second = SingleInstance(tmp_path)
    try:
        assert second.acquire()
    finally:
        second.close()


def test_controller_catalog_failure_releases_open_sqlite_store(tmp_path, monkeypatch):
    """A fault after Store opens but before Controller assignment must not leak it."""
    from global_pulse import controller as controller_module
    from global_pulse.core import Store

    app = QApplication.instance() or QApplication([])
    closed = []

    class TrackedStore(Store):
        def close(self):
            super().close()
            closed.append(self)

    def catalog_failure():
        raise ValueError("injected catalog decode failure")

    monkeypatch.setattr(controller_module, "Store", TrackedStore)
    monkeypatch.setattr(controller_module, "load_catalog", catalog_failure)
    with pytest.raises(ValueError, match="injected catalog"):
        controller_module.Controller(tmp_path, demo=True)

    assert len(closed) == 1
    assert closed[0]._closed
    # Reopening the same directory is a real SQLite lifecycle operation; no
    # process exit or GC is needed to release the provisional Store.
    with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as reopened:
        assert reopened.stats()["events"] == 0
    app.processEvents()


def test_controller_late_gdelt_failure_rolls_back_workers_scheduler_and_sqlite(
    tmp_path, monkeypatch
):
    """Even the final startup component may fail after workers and timers exist."""
    from global_pulse import controller as controller_module
    from global_pulse import gdelt_service as gdelt_module
    from global_pulse.core import Store

    app = QApplication.instance() or QApplication([])
    calls = []
    original_store_close = controller_module.Store.close
    original_worker_close = controller_module.TranslationProcess.close
    original_stop = controller_module.Scheduler.stop

    def store_close(self):
        calls.append("store")
        return original_store_close(self)

    def worker_close(self):
        calls.append("workers")
        return original_worker_close(self)

    def scheduler_stop(self):
        calls.append("scheduler")
        return original_stop(self)

    def fail_gdelt(*_args, **_kwargs):
        raise RuntimeError("injected GDELT constructor failure")

    monkeypatch.setattr(controller_module.Store, "close", store_close)
    monkeypatch.setattr(controller_module.TranslationProcess, "close", worker_close)
    monkeypatch.setattr(controller_module.Scheduler, "stop", scheduler_stop)
    monkeypatch.setattr(gdelt_module, "GdeltService", fail_gdelt)
    with pytest.raises(RuntimeError, match="injected GDELT constructor"):
        controller_module.Controller(tmp_path, demo=True)

    assert calls.count("workers") == 1
    assert calls.count("scheduler") == 1
    assert calls.count("store") == 1
    assert calls.index("store") > calls.index("workers")
    assert calls.index("store") > calls.index("scheduler")
    with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as reopened:
        assert reopened.stats()["events"] == 0
    app.processEvents()


def test_controller_failed_rollback_preserves_original_exception(tmp_path, monkeypatch):
    """A secondary cleanup error is logged, not substituted for the first fault."""
    from global_pulse import controller as controller_module
    from global_pulse.core import Store

    app = QApplication.instance() or QApplication([])
    original_close = controller_module.Store.close

    def close_then_error(self):
        original_close(self)
        raise RuntimeError("injected cleanup log-only error")

    def initial_failure():
        raise ValueError("original bad source catalog")

    monkeypatch.setattr(controller_module.Store, "close", close_then_error)
    monkeypatch.setattr(controller_module, "load_catalog", initial_failure)
    with pytest.raises(ValueError, match="original bad source catalog"):
        controller_module.Controller(tmp_path, demo=True)
    reopened = Store(tmp_path / "synthetic.sqlite3", mode="synthetic")
    try:
        assert reopened.stats()["events"] == 0
    finally:
        # The injected close exception is for failure-path observation only.
        original_close(reopened)
    app.processEvents()


def test_shutdown_keeps_sqlite_cleanup_and_retries_live_worker(tmp_path, monkeypatch):
    """A worker refusal must not strand SQLite or falsely finish shutdown."""
    from global_pulse.core import Store

    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    original_close = controller._workers.close
    attempts = []

    def worker_refuses_once():
        attempts.append("worker")
        if len(attempts) == 1:
            raise RuntimeError("injected translation process still running")
        return original_close()

    monkeypatch.setattr(controller._workers, "close", worker_refuses_once)
    with pytest.raises(RuntimeError, match="translation worker"):
        controller.close()
    assert controller._closed
    assert controller._store_closed
    assert not controller._shutdown_complete
    with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as reopened:
        assert reopened.stats()["events"] == 0
    controller.close()
    assert attempts == ["worker", "worker"]
    assert controller._shutdown_complete
    controller.close()
    assert len(attempts) == 2
    app.processEvents()


def test_shutdown_gdelt_refusal_does_not_skip_other_teardown(tmp_path, monkeypatch):
    """Retry a refused GDELT process without skipping remaining cleanup."""
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    original_close = controller._gdelt.close
    calls = []

    def refuse_once():
        calls.append("GDELT")
        if len(calls) == 1:
            raise RuntimeError("injected GDELT process still running")
        return original_close()

    monkeypatch.setattr(controller._gdelt, "close", refuse_once)
    with pytest.raises(RuntimeError, match="GDELT worker"):
        controller.close()
    assert controller._store_closed
    assert not controller._shutdown_complete
    assert controller._workers._closed
    controller.close()
    assert controller._shutdown_complete
    assert calls == ["GDELT", "GDELT"]
    app.processEvents()


def test_shutdown_can_retry_sqlite_close_without_false_success(tmp_path, monkeypatch):
    """A transient SQLite close failure must not be considered a full exit."""
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    original_close = controller.store.close
    calls = []

    def fail_once():
        calls.append("SQLite")
        if len(calls) == 1:
            raise RuntimeError("injected checkpoint refusal")
        return original_close()

    monkeypatch.setattr(controller.store, "close", fail_once)
    with pytest.raises(RuntimeError, match="SQLite archive"):
        controller.close()
    assert not controller._store_closed
    assert not controller._shutdown_complete
    controller.close()
    assert controller._store_closed
    assert controller._shutdown_complete
    assert calls == ["SQLite", "SQLite"]
    app.processEvents()


def test_shutdown_retry_does_not_repeat_completed_worker_and_scheduler_stops(tmp_path, monkeypatch):
    """After GDELT refusal, only the refused native worker is retried."""
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    attempts = {"gdelt": 0, "translator": 0, "scheduler": 0}
    gdelt_close = controller._gdelt.close
    translation_close = controller._workers.close
    scheduler_stop = controller.scheduler.stop

    def gdelt_refuses_once():
        attempts["gdelt"] += 1
        if attempts["gdelt"] == 1:
            raise RuntimeError("injected live GDELT worker refused to stop")
        gdelt_close()

    def close_translation_once():
        attempts["translator"] += 1
        if attempts["translator"] > 1:
            raise RuntimeError("already destroyed translation QProcess")
        translation_close()

    def stop_scheduler_once():
        attempts["scheduler"] += 1
        if attempts["scheduler"] > 1:
            raise RuntimeError("scheduler already destroyed")
        scheduler_stop()

    monkeypatch.setattr(controller._gdelt, "close", gdelt_refuses_once)
    monkeypatch.setattr(controller._workers, "close", close_translation_once)
    monkeypatch.setattr(controller.scheduler, "stop", stop_scheduler_once)
    with pytest.raises(RuntimeError, match="GDELT worker"):
        controller.close()
    assert controller._store_closed
    assert not controller._shutdown_complete
    assert attempts == {"gdelt": 1, "translator": 1, "scheduler": 1}
    controller.close()
    assert controller._shutdown_complete
    assert attempts == {"gdelt": 2, "translator": 1, "scheduler": 1}
    app.processEvents()


def test_shutdown_sqlite_retry_does_not_reclose_destroyed_translation_process(tmp_path, monkeypatch):
    """A transient SQLite close failure must not re-close a reaped QProcess."""
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    worker_close = controller._workers.close
    store_close = controller.store.close
    attempts = {"worker": 0, "store": 0}

    def worker_must_close_once():
        attempts["worker"] += 1
        if attempts["worker"] > 1:
            raise RuntimeError("already reaped native translation process")
        worker_close()

    def store_refuses_once():
        attempts["store"] += 1
        if attempts["store"] == 1:
            raise RuntimeError("SQLite checkpoint transient refusal")
        store_close()

    monkeypatch.setattr(controller._workers, "close", worker_must_close_once)
    monkeypatch.setattr(controller.store, "close", store_refuses_once)
    with pytest.raises(RuntimeError, match="SQLite archive"):
        controller.close()
    assert controller._shutdown_steps_complete.issuperset(
        {"GDELT worker", "translation worker", "source scheduler"}
    )
    assert not controller._shutdown_complete
    controller.close()
    assert controller._shutdown_complete
    assert attempts == {"worker": 1, "store": 2}
    app.processEvents()


def test_source_status_burst_coalesces_full_map_archive_refresh(tmp_path, monkeypatch):
    """Collector status chatter cannot redraw the entire map once per source.

    Real offscreen Qt timer and real SQLite-backed desktop; does not assert
    physical Windows 11 performance or independent QA acceptance.
    """
    from PySide6.QtTest import QTest

    app, controller, window = _desktop(tmp_path)
    calls = []
    original = window.world_map.set_events

    def count_map_updates(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(window.world_map, "set_events", count_map_updates)
    try:
        for _ in range(180):
            controller._on_source_status("sample_source", {"status": "available"})
        assert window._collection_refresh_timer.isActive()
        assert not calls, "Collector burst must not synchronously requery/map 180 times"

        QTest.qWait(350)
        assert len(calls) == 1, "One pending burst is one Store/map redraw"
        assert not window._collection_refresh_timer.isActive()

        for _ in range(20):
            controller._on_source_status("sample_source", {"status": "available"})
        assert window._collection_refresh_timer.isActive()
        # User-driven filter action must see the latest archive immediately
        # and cancel the now-redundant delayed collector refresh.
        controller.data_changed.emit()  # an actual evidence/user signal is immediate
        assert len(calls) == 2
        assert not window._collection_refresh_timer.isActive()
        QTest.qWait(260)
        assert len(calls) == 2
    finally:
        _close(app, controller, window)


def test_continuous_collector_events_cannot_starve_desktop_refresh(tmp_path, monkeypatch):
    """The first due timer must fire even if new source statuses keep arriving."""
    from PySide6.QtTest import QTest

    app, controller, window = _desktop(tmp_path)
    calls = []
    original = window.world_map.set_events

    def count_map_updates(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(window.world_map, "set_events", count_map_updates)
    try:
        for _ in range(6):
            controller._on_source_status("sample_source", {"status": "available"})
            QTest.qWait(65)
        assert calls, "Repeated statuses must not indefinitely restart the timer"
        assert len(calls) <= 3, "Only a bounded number of full refreshes may occur"
    finally:
        _close(app, controller, window)


def test_real_scheduler_thread_status_is_marshaled_to_gui_refresh(tmp_path, monkeypatch):
    """A collector thread must never start its UI-owned QTimer itself."""
    import threading
    from PySide6.QtTest import QTest

    app, controller, window = _desktop(tmp_path)
    calls = []
    original = window.world_map.set_events

    def count_map_updates(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(window.world_map, "set_events", count_map_updates)
    try:
        worker = threading.Thread(
            target=lambda: controller._on_source_status(
                "sample_source", {"status": "available", "last_success": "2026-11-13T23:00:00Z"}
            ),
            name="test-provider-status", daemon=True
        )
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        # No Qt event processing has occurred on the UI thread yet.
        assert not window._collection_refresh_timer.isActive()
        app.processEvents()
        assert window._collection_refresh_timer.isActive()
        QTest.qWait(300)
        assert len(calls) == 1
        assert controller.last_collection == "2026-11-13T23:00:00Z"
    finally:
        _close(app, controller, window)
