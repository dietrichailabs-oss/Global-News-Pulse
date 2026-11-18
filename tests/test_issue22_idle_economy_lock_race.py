"""No-click Economy prewarm must never reacquire a collector-held Store lock.

Synthetic local observation data only. Hosted Qt is not physical Win11 acceptance.
"""
import threading
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _rows(size=64):
    return [
        {"indicator": "synthetic-gdp", "indicator_name": "Fictional test GDP",
         "country_name": f"Fictional Land {i % 8}", "date": "2026-11-01",
         "value": float(i), "source_id": "offline-fixture",
         "description": "Synthetic test only", "attribution": "Fictional publisher",
         "url": "https://example.invalid/fictional"}
        for i in range(size)
    ]


def _stop(app, window, controller):
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


def _ready(window):
    window.show()
    QApplication.processEvents()
    window._background_warm_enabled = True
    window._last_navigation_at = time.monotonic() - 10
    window._workspace_warm_timer.stop()
    window._evidence_refresh_timer.stop()
    window._dirty_pages = {2}


def test_hidden_economy_precheck_race_never_blocks_or_reads_sqlite(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    release, held = threading.Event(), threading.Event()
    locker = None
    try:
        window = MainWindow(controller)
        _ready(window)
        rows = _rows()
        window._deferred_economy_observations = rows
        window._deferred_economy_revision = controller.store.content_revision()
        actual_probe = controller.store.content_revision_if_available
        calls = [0]

        def occupy():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        def probe():
            revision = actual_probe()
            calls[0] += 1
            if calls[0] == 1:
                nonlocal locker
                locker = threading.Thread(target=occupy, daemon=True)
                locker.start()
                assert held.wait(timeout=2)
            return revision

        with patch.object(controller.store, "content_revision_if_available",
                          side_effect=probe), \
             patch.object(controller.store, "content_revision",
                          side_effect=AssertionError("blocking Qt revision read")), \
             patch.object(controller.store, "list_observations",
                          side_effect=AssertionError("Qt must not read observations")):
            started = time.monotonic()
            window._warm_next_workspace()
            elapsed = time.monotonic() - started
            assert elapsed < 0.6, f"Qt hidden Economy warm waited {elapsed:.3f}s"
            assert calls[0] >= 2, "Race after first successful probe was not exercised"
            assert 2 in window._dirty_pages, "Busy Economy snapshot was discarded"
            assert window._workspace_warm_timer.isActive()
            assert window._deferred_economy_observations is rows
            release.set()
            locker.join(timeout=3)
            assert not locker.is_alive()
            window._workspace_warm_timer.stop()
            window._warm_next_workspace()
            window._workspace_warm_timer.stop()
            assert 2 not in window._dirty_pages
            assert window.economy_model.rowCount() == len(rows)
            assert window._deferred_economy_observations is None
    finally:
        release.set()
        if locker is not None:
            locker.join(timeout=4)
        _stop(app, window, controller)


def test_stale_or_missing_hidden_economy_requires_new_worker_without_sql(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        _ready(window)
        rows = _rows(8)
        window._deferred_economy_observations = rows
        window._deferred_economy_revision = controller.store.content_revision()
        # A real local source change invalidates an otherwise convincing
        # cached 8-row dataset; don't display stale/withdrawn observations.
        assert controller.store.put_observations(rows) == len(rows)
        retries = []
        with patch.object(window, "_schedule_evidence_refresh",
                          side_effect=lambda: retries.append("worker")), \
             patch.object(controller.store, "list_observations",
                          side_effect=AssertionError("No Qt observation fallback")), \
             patch.object(controller.store, "content_revision",
                          side_effect=AssertionError("No blocking Qt revision")):
            window._warm_next_workspace()
            assert 2 in window._dirty_pages
            assert retries == ["worker"]
            assert window.economy_model.rowCount() != 8
            window._workspace_warm_timer.stop()
            window._deferred_economy_observations = None
            window._warm_next_workspace()
            assert 2 in window._dirty_pages
            assert retries == ["worker", "worker"]
            window._workspace_warm_timer.stop()
    finally:
        _stop(app, window, controller)


def test_filtered_monitor_snapshot_still_prewarms_unfiltered_economy(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        rows = _rows(16)
        assert controller.store.put_observations(rows) == len(rows)
        window = MainWindow(controller)
        _ready(window)
        # An explicit Monitor region filter suppresses map economy markers,
        # not the independent Economy workspace and its real source values.
        blocked = window.region.blockSignals(True)
        window.region.addItem("Fictional filter region", "fictional-filter")
        window.region.setCurrentIndex(window.region.count() - 1)
        window.region.blockSignals(blocked)
        completed = []
        window._idle_snapshot_ready.connect(lambda result: completed.append(result))
        window._start_idle_snapshot()
        deadline = time.monotonic() + 8
        while not completed and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert completed, "Source-checked worker did not return"
        snapshot = completed[0]
        assert "error" not in snapshot, snapshot.get("error")
        assert snapshot["revision_before"] == snapshot["revision_after"]
        assert snapshot["observations"] == [], "Filtered map must hide economy layer"
        assert len(snapshot["economy_observations"]) == len(rows)
        assert {o["indicator"] for o in snapshot["economy_observations"]} == {"synthetic-gdp"}
    finally:
        _stop(app, window, controller)
