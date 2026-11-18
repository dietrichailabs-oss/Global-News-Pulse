"""Real Qt regression for hidden Brief worker result, Store lock and source freshness.

This tests GUI callbacks and a real worker-owned Store RLock. It does not
certify physical Windows 11 playback, smoothness or release.
"""
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def test_hidden_brief_result_never_blocks_qt_on_store_lock(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    worker = None
    release = threading.Event()
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        window._workspace_warm_timer.stop()
        window._evidence_refresh_timer.stop()
        source_revision = controller.store.content_revision()
        payload = [{"id": "brief-off-thread-example", "title": "Preserved original"}]
        result = {
            "generation": window._idle_snapshot_generation,
            "period": window.brief_period.currentText().lower(),
            "revision_before": source_revision,
            "revision_after": source_revision,
            "events": payload,
        }
        window._idle_brief_inflight = True
        held = threading.Event()

        def occupy_store():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        worker = threading.Thread(target=occupy_store, daemon=True)
        worker.start()
        assert held.wait(timeout=2), "Real Store RLock holder never started"
        queued = []
        fake_timer = SimpleNamespace(
            singleShot=lambda ms, callback: queued.append((ms, callback))
        )
        with patch("global_pulse.ui.QTimer", fake_timer), patch.object(
                window, "_schedule_workspace_warm") as warm:
            started = time.monotonic()
            window._apply_idle_brief(result)
            elapsed = time.monotonic() - started
            assert elapsed < 0.5, f"Qt blocked on Store lock for {elapsed:.3f}s"
            assert window._idle_brief_inflight, "Pending Brief lost ownership"
            assert window._deferred_brief_events is None, "Busy means NOT accepted"
            assert len(queued) == 1 and queued[0][0] == 120
            warm.assert_not_called()

            release.set()
            worker.join(timeout=2)
            assert not worker.is_alive(), "Store RLock holder failed to exit"
            queued[0][1]()
            assert window._deferred_brief_events is payload
            assert window._deferred_brief_period == result["period"]
            assert window._deferred_brief_revision == source_revision
            assert window._idle_brief_inflight is False
            warm.assert_called_once_with()

            # A subsequent committed mutation must invalidate an otherwise
            # identical completed worker result; no stale brief presentation.
            window._deferred_brief_events = None
            with controller.store._lock:
                controller.store._conn.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS issue22_brief_probe(v INTEGER)")
                controller.store._conn.execute(
                    "INSERT INTO issue22_brief_probe(v) VALUES (1)")
            assert controller.store.content_revision() != source_revision
            window._idle_brief_inflight = True
            window._apply_idle_brief(result)
            assert window._deferred_brief_events is None
            assert window._idle_brief_inflight is False
            assert warm.call_count == 2

            # A changed period or generation cannot revive the old result.
            window._idle_snapshot_generation += 1
            window._idle_brief_inflight = True
            window._apply_idle_brief(result)
            assert window._deferred_brief_events is None
            assert window._idle_brief_inflight is False
            assert warm.call_count == 3
    finally:
        release.set()
        if worker is not None:
            worker.join(timeout=3)
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
