"""Real Qt no-click alert-history Store contention; offline synthetic fixture only.

Hosted Qt verification is not a physical Windows 11 notification/media test.
"""
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _synthetic_alert(controller):
    stamp = datetime.now(timezone.utc).isoformat()
    rows = controller.store.ingest([{
        "id": "synthetic-alert-idle-race",
        "event_key": "offline-alert-race",
        "title": "FICTIONAL offline alert",
        "summary": "Only a synthetic lock fixture, not real-world news",
        "source_id": "offline-source",
        "publisher": "Fictional publisher",
        "url": "https://example.invalid/alert",
        "published_at": stamp,
        "retrieved_at": stamp,
        "region": "Global",
        "category": "News",
        "severity": "high",
        "synthetic": True,
    }])
    assert len(rows) == 1
    alert = controller.store.add_alert(rows[0], "Synthetic test alert")
    assert alert and alert["id"]
    return alert["id"]


def _ready(window):
    window.show()
    QApplication.processEvents()
    window._background_warm_enabled = True
    window._last_navigation_at = time.monotonic() - 10
    window._workspace_warm_timer.stop()
    window._evidence_refresh_timer.stop()
    window._dirty_pages = {4}


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


def _await_worker(app, window):
    deadline = time.monotonic() + 8
    while window._idle_alerts_inflight and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not window._idle_alerts_inflight, "Real alert-history Store worker did not complete"
    assert window._deferred_alert_rows is not None
    assert window._deferred_alert_revision is not None


def test_alert_only_dirty_refresh_uses_real_worker_without_full_map(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        alert_id = _synthetic_alert(controller)
        window = MainWindow(controller)
        _ready(window)
        assert window._deferred_alert_rows is None
        with patch.object(window, "_schedule_evidence_refresh",
                          side_effect=AssertionError("alert-only forced map read")), \
             patch.object(controller, "events",
                          side_effect=AssertionError("alert-only fetched whole archive")):
            # Notification updates must neither force a full evidence worker
            # nor call Store.list_alerts on Qt while busy.
            window._notification_status_only()
            window._warm_next_workspace()
            assert window._idle_alerts_inflight
            assert 4 in window._dirty_pages
            _await_worker(app, window)
            window._workspace_warm_timer.stop()
            with patch.object(controller.store, "list_alerts",
                              side_effect=AssertionError("Qt alert SQL")):
                assert window._populate_alerts(idle=True) is True
            assert window.alert_list.count() == 1
            assert window.alert_list.item(0).data(Qt.ItemDataRole.UserRole)["id"] == alert_id
        window._workspace_warm_timer.stop()
    finally:
        _close(app, window, controller)


def test_alert_precheck_race_must_defer_without_reloading_qt_sql(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    held, release = threading.Event(), threading.Event()
    locker = None
    try:
        alert_id = _synthetic_alert(controller)
        window = MainWindow(controller)
        _ready(window)
        cached = controller.store.list_alerts()
        assert len(cached) == 1
        window._deferred_alert_rows = cached
        window._deferred_alert_revision = controller.store.content_revision()
        original = controller.store.content_revision_if_available
        probes = [0]

        def occupy():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        def racing_probe():
            result = original()
            probes[0] += 1
            if probes[0] == 1:
                nonlocal locker
                locker = threading.Thread(target=occupy, daemon=True)
                locker.start()
                assert held.wait(timeout=2)
            return result

        with patch.object(controller.store, "content_revision_if_available",
                          side_effect=racing_probe), \
             patch.object(controller.store, "content_revision",
                          side_effect=AssertionError("Qt blocking revision")), \
             patch.object(controller.store, "list_alerts",
                          side_effect=AssertionError("Qt alert SQL")):
            start = time.monotonic()
            window._warm_next_workspace()
            assert time.monotonic() - start < 0.6
            assert probes[0] >= 2
            assert window._workspace_warm_timer.isActive()
            assert 4 in window._dirty_pages
            assert window._deferred_alert_rows is cached
            release.set()
            locker.join(timeout=3)
            assert not locker.is_alive()
            window._workspace_warm_timer.stop()
            window._warm_next_workspace()
            assert 4 not in window._dirty_pages
            assert window.alert_list.count() == 1
            assert window.alert_list.item(0).data(Qt.ItemDataRole.UserRole)["id"] == alert_id
    finally:
        release.set()
        if locker is not None:
            locker.join(timeout=4)
        _close(app, window, controller)


def test_stale_alert_worker_result_never_repaints_previous_history(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        alert_id = _synthetic_alert(controller)
        window = MainWindow(controller)
        _ready(window)
        rows = controller.store.list_alerts()
        revision = controller.store.content_revision()
        # A read marker updates alert body and Store content_revision.
        controller.store.mark_alert_read(alert_id)
        assert controller.store.content_revision() != revision
        window._deferred_alert_rows = rows
        window._deferred_alert_revision = revision
        # Stub only the worker *start* while checking the Qt code path;
        # otherwise a background thread could race this temporary patch and
        # accidentally receive the GUI-only AssertionError.
        requested = []
        with patch.object(controller.store, "list_alerts",
                          side_effect=AssertionError("Qt stale alert SQL")), \
             patch.object(window, "_start_idle_alert_snapshot",
                          side_effect=lambda: requested.append(True)):
            assert window._populate_alerts(idle=True) is False
            assert window.alert_list.count() == 0
        assert requested == [True]
        window._start_idle_alert_snapshot()
        _await_worker(app, window)
        window._workspace_warm_timer.stop()
        with patch.object(controller.store, "list_alerts",
                          side_effect=AssertionError("Qt fresh alert SQL")):
            assert window._populate_alerts(idle=True) is True
        assert window.alert_list.count() == 1
        assert window.alert_list.item(0).data(Qt.ItemDataRole.UserRole)["read"] is True
    finally:
        _close(app, window, controller)


def test_passive_alert_with_own_title_does_not_lookup_every_event_on_qt(tmp_path):
    """Ordinary persisted alerts already carry a title; passive Qt must not
    open the full event record for each row after its nonblocking lock probe."""
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        _synthetic_alert(controller)
        window = MainWindow(controller)
        _ready(window)
        window._start_idle_alert_snapshot()
        _await_worker(app, window)
        window._workspace_warm_timer.stop()
        # Before the fix, _populate_alerts performed controller.event for EVERY
        # row even when row["title"] was populated. This is a genuine SQLite
        # read that could wait for the collector while Qt was idle.
        with patch.object(controller.store, "get_event",
                          side_effect=AssertionError("passive Qt read full event")):
            assert window._populate_alerts(idle=True)
        assert window.alert_list.count() == 1
        assert window.alert_list.item(0).text().startswith("FICTIONAL offline alert")
    finally:
        _close(app, window, controller)


def test_legacy_alert_title_resolves_on_worker_not_qt_and_preserves_body(tmp_path):
    """Historical title-less alerts keep their real event title, but the
    archived-event lookup is off the main thread and never persisted as fact."""
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        _synthetic_alert(controller)
        legacy = dict(controller.store.list_alerts()[0])
        legacy.pop("title")
        original_get_event = controller.store.get_event
        worker_threads = []

        def read_from_worker(identifier):
            worker_threads.append(threading.current_thread().name)
            assert threading.current_thread() is not threading.main_thread()
            return original_get_event(identifier)

        window = MainWindow(controller)
        _ready(window)
        with patch.object(controller.store, "list_alerts", return_value=[legacy), \\
             patch.object(controller.store, "get_event", side_effect=read_from_worker):
            window._start_idle_alert_snapshot()
            _await_worker(app, window)
        assert worker_threads and all(name == "pulse-idle-alerts" for name in worker_threads)
        window._workspace_warm_timer.stop()
        assert window._deferred_alert_rows[0]["_idle_display_title"] == "FICTIONAL offline alert"
        # No SQL/event lookup permitted during Qt rendering after a successful
        # worker result; missing fields cannot silently erase the historic title.
        with patch.object(controller.store, "get_event",
                          side_effect=AssertionError("Qt legacy alert event lookup")):
            assert window._populate_alerts(idle=True)
        assert window.alert_list.item(0).text().startswith("FICTIONAL offline alert")
        assert controller.store.list_alerts()[0].get("title") == "FICTIONAL offline alert"
        assert "_idle_display_title" not in controller.store.list_alerts()[0]
    finally:
        _close(app, window, controller)
