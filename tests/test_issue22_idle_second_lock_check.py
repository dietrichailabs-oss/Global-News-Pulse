"""Real Qt regression: idle commit must not re-enter a busy Store lock.

This guards a second read between the snapshot-ready revision probe and the
actual idle UI commit. It is not physical Windows 11 responsiveness approval.
"""
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def test_idle_commit_second_revision_check_is_nonblocking_and_retries(tmp_path):
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
        revision = controller.store.content_revision()

        held = threading.Event()

        def occupy_store():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        worker = threading.Thread(target=occupy_store, daemon=True)
        worker.start()
        assert held.wait(timeout=2), "Real Store lock-holder did not start"
        # The first _apply_idle_snapshot check may have succeeded before this
        # worker grabbed the lock. The second check must NEVER block Qt.
        snapshot = {"revision_after": revision}
        queued = []
        fake_timer = SimpleNamespace(singleShot=lambda ms, callback:
                                     queued.append((ms, callback)))
        started = time.monotonic()
        with patch("global_pulse.ui.QTimer", fake_timer):
            window.refresh_data(_idle_snapshot=snapshot)
        elapsed = time.monotonic() - started
        assert elapsed < 0.5, f"Qt blocked on Store lock for {elapsed:.3f}s"
        assert window._idle_snapshot_inflight, "Single-flight snapshot was lost"
        assert len(queued) == 1 and queued[0][0] == 120
        with patch.object(window, "_apply_idle_snapshot") as retry:
            queued[0][1]()
            retry.assert_called_once_with(snapshot)

        release.set()
        worker.join(timeout=2)
        assert not worker.is_alive(), "Store holder failed to release"
        window._idle_snapshot_inflight = False
        # Once available, an obsolete revision must be invalidated, not
        # painted or treated as a successful collector refresh.
        with patch.object(window, "_schedule_evidence_refresh") as schedule:
            window.refresh_data(_idle_snapshot={"revision_after": (-1, -1)})
            schedule.assert_called_once_with()
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
