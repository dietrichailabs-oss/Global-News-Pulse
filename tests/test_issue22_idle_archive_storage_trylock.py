"""Real Qt no-click archive status lock race; no network or physical media claim."""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.archive_storage_controls import ArchiveStorageControls
from global_pulse.controller import Controller


def test_passive_hidden_storage_poll_never_blocks_qt_collector_lock(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    panel = None
    acquired = threading.Event()
    release = threading.Event()
    worker_done = threading.Event()
    failure = []

    def collector_holds_store_then_updates_actual_setting():
        try:
            with controller.store._lock:
                acquired.set()
                # Finite safety release; the main test releases much earlier.
                if not release.wait(3):
                    raise AssertionError("The GUI hung behind the Store lock")
                controller.store.set_setting("archive_max_gb", 20)
        except Exception as exc:
            failure.append(exc)
        finally:
            worker_done.set()

    try:
        panel = ArchiveStorageControls(controller)
        original = panel.usage.text()
        assert "30 GB maximum" in original
        assert panel._saved == 30
        assert panel._last_status_text == original
        # The Settings widget is genuinely hidden, as immediately after
        # splash initialization. Its real 5-second status timer and status
        # signals were previously allowed to block Qt in that state.
        assert not panel.isVisible()

        worker = threading.Thread(target=collector_holds_store_then_updates_actual_setting)
        worker.start()
        assert acquired.wait(2)
        assert controller.archive_storage_status(nonblocking=True) is None

        beats = []
        ticker = QTimer()
        ticker.setInterval(16)
        ticker.timeout.connect(lambda: beats.append(time.perf_counter()))
        ticker.start()
        # Force actual periodic hidden-status timer callbacks while the
        # worker owns the RLock, not a mock response to a fake Store.
        panel.timer.start(35)
        start = time.perf_counter()
        panel.refresh()
        direct_ms = (time.perf_counter() - start) * 1000
        QTest.qWait(230)
        ticker.stop()
        intervals = [(b - a) * 1000 for a, b in zip(beats, beats[1:])]

        assert direct_ms < 100, f"Passive Qt status read stalled {direct_ms:.1f} ms"
        assert len(beats) >= 6, f"Qt heartbeat stopped: {len(beats)} callbacks"
        assert max(intervals) < 125, f"Qt blocked while collector owns RLock: {intervals}"
        assert "Archive status pending" in panel.usage.text()
        assert "previous values are not current" in panel.usage.text()
        assert "30 GB maximum" in panel.usage.text()
        assert panel._saved == 30
        assert not panel.clean.isEnabled()
        assert panel._busy_retry_timer.isActive()

        release.set()
        assert worker_done.wait(3)
        worker.join(timeout=3)
        assert not worker.is_alive() and not failure, failure
        # The original persisted state changed under the real Store RLock.
        # BUSY never declared the new setting accepted prematurely; the next
        # real Qt status callback must pick up the fresh exact value.
        QTest.qWait(320)
        assert panel._saved == 20
        assert "20 GB maximum" in panel.usage.text()
        assert "Archive status pending" not in panel.usage.text()
        assert "previous values are not current" not in panel.usage.text()
        assert panel._last_status_text == panel.usage.text()
        print("PULSE_ARCHIVE_STATUS_LOCK_PROFILE=" + str({
            "direct_gui_refresh_ms": round(direct_ms, 3),
            "qt_heartbeat_callbacks": len(beats),
            "max_heartbeat_ms": round(max(intervals), 3),
            "real_storage_change_from_gb": 30,
            "real_storage_change_to_gb": panel._saved,
            "network_or_media": False,
        }), flush=True)
    finally:
        release.set()
        worker_done.wait(3)
        if panel is not None:
            panel.timer.stop()
            panel._busy_retry_timer.stop()
            panel.close()
            panel.deleteLater()
        controller.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
