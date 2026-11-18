"""Real Qt: passive Situation Room never waits on collector-held SQLite.

Synthetic offline report only. No claim about physical Win11 or playback.
"""
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _identity(controller):
    stamp = datetime.now(timezone.utc).isoformat()
    rows = controller.store.ingest([{
        "id": "synthetic-situation-race", "event_key": "offline-situation-race",
        "title": "FICTIONAL saved report", "summary": "Not real-world evidence",
        "source_id": "synthetic-fixture", "publisher": "Fictional publisher",
        "url": "https://example.invalid/saved-report",
        "published_at": stamp, "retrieved_at": stamp, "region": "Global",
        "category": "News", "severity": "unassessed", "synthetic": True}])
    assert len(rows) == 1
    return str(rows[0]["id"])


def _ready(window):
    window.show()
    QApplication.processEvents()
    window._background_warm_enabled = True
    window._last_navigation_at = time.monotonic() - 10
    window._workspace_warm_timer.stop()
    window._evidence_refresh_timer.stop()
    window._dirty_pages = {1}


def _close(app, window, controller):
    if window is not None:
        window._force_close = True
        for n in ("_workspace_warm_timer", "_evidence_refresh_timer",
                  "_collection_refresh_timer", "search_timer"):
            getattr(window, n).stop()
        window.media.shutdown()
        window.close()
        window.deleteLater()
    controller.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_hidden_second_lock_probe_never_waits_or_loads_situations_on_qt(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    held, release = threading.Event(), threading.Event()
    locker = None
    try:
        identity = _identity(controller)
        controller.store.set_situation_saved(identity, True)
        window = MainWindow(controller)
        _ready(window)
        rows = controller.store.list_situations()
        assert len(rows) == 1
        window._deferred_situation_rows = rows
        window._deferred_situation_revision = controller.store.content_revision()
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
             patch.object(controller.store, "list_situations",
                          side_effect=AssertionError("Qt situation SQL")), \
             patch.object(controller.store, "content_revision",
                          side_effect=AssertionError("Qt blocking revision")):
            start = time.monotonic()
            window._warm_next_workspace()
            assert time.monotonic() - start < 0.6
            assert probes[0] >= 2
            assert 1 in window._dirty_pages
            assert window._workspace_warm_timer.isActive()
            assert window._deferred_situation_rows is rows
            release.set()
            locker.join(timeout=3)
            assert not locker.is_alive()
            window._workspace_warm_timer.stop()
            window._warm_next_workspace()
            window._workspace_warm_timer.stop()
            assert 1 not in window._dirty_pages
            assert window.situation_list.count() == 1
            assert window.situation_list.item(0).data(Qt.ItemDataRole.UserRole) == identity
            assert window._deferred_situation_rows is None
    finally:
        release.set()
        if locker is not None:
            locker.join(timeout=4)
        _close(app, window, controller)


def test_stale_unstarred_and_empty_worker_rows_never_requery_qt(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        identity = _identity(controller)
        controller.store.set_situation_saved(identity, True)
        window = MainWindow(controller)
        _ready(window)
        previous = controller.store.list_situations()
        window._deferred_situation_rows = previous
        window._deferred_situation_revision = controller.store.content_revision()
        controller.store.set_situation_saved(identity, False)
        calls = []
        with patch.object(window, "_schedule_evidence_refresh",
                          side_effect=lambda: calls.append("worker")), \
             patch.object(controller.store, "list_situations",
                          side_effect=AssertionError("Qt passive query")), \
             patch.object(controller.store, "content_revision",
                          side_effect=AssertionError("Qt blocking revision")):
            assert window._populate_situations(idle=True) is False
            assert calls == ["worker"]
            assert window._deferred_situation_rows is previous
            window._deferred_situation_rows = []
            window._deferred_situation_revision = controller.store.content_revision_if_available()
            assert window._populate_situations(idle=True) is True
            assert window.situation_list.count() == 0
            assert window._populate_situations(idle=True) is False
            assert calls == ["worker", "worker"]
        # Manual selection remains allowed to query current archived identity.
        controller.store.set_situation_saved(identity, True)
        assert window._populate_situations() is True
        assert window.situation_list.count() == 1
    finally:
        _close(app, window, controller)


def test_revision_checked_background_worker_carries_saved_history(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        identity = _identity(controller)
        controller.store.set_situation_saved(identity, True)
        window = MainWindow(controller)
        _ready(window)
        results = []
        window._idle_snapshot_ready.connect(lambda snapshot: results.append(snapshot))
        window._start_idle_snapshot()
        deadline = time.monotonic() + 8
        while not results and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert results, "No real Store worker result"
        result = results[0]
        assert "error" not in result, result.get("error")
        assert result["revision_before"] == result["revision_after"]
        assert len(result["situation_rows"]) == 1
        assert result["situation_rows"][0]["event_id"] == identity
        assert identity in result["saved_situation_ids"]
    finally:
        _close(app, window, controller)
