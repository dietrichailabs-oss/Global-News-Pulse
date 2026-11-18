"""Real Qt feed-metadata regression: collector snapshot Star/language reads run off Qt.

This is an offline Source RLock test. It does not establish whole-app or
physical Windows 11 smoothness, live media, or release suitability.
"""
import threading
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _shutdown(app, window, controller):
    if window is not None:
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer"):
            getattr(window, name).stop()
        window._force_close = True
        window.media.shutdown()
        window.close()
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _event():
    return {
        "id": "offline-feed-starring", "title": "Original attributed report",
        "region": "Global", "category": "News", "severity": "unassessed",
        "updated_at": "2026-11-18T00:00:00+00:00",
        "recap": "Synthetic local test; no actual current-event claim",
        "reports": [], "synthetic": True,
    }


def test_source_consistent_feed_metadata_does_not_wait_for_store_lock(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    release = threading.Event()
    worker = None
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        window._workspace_warm_timer.stop()
        window._evidence_refresh_timer.stop()
        window._events = [_event()]
        window._selected_id = ""
        window._feed_explicitly_cleared = False
        held = threading.Event()

        def occupy_store():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        worker = threading.Thread(target=occupy_store, daemon=True)
        worker.start()
        assert held.wait(timeout=2), "Store RLock never became contested"

        # A collector snapshot already holds these two exact-revision values.
        # Neither Settings nor situations may be queried from Qt while the
        # worker holds the Store lock; assertions would catch that regression.
        with patch.object(controller, "get_setting",
                          side_effect=AssertionError("Qt read headline setting")), \
             patch.object(controller.store, "saved_situation_ids",
                          side_effect=AssertionError("Qt read Star IDs")), \
             patch.object(controller, "headline_view",
                          return_value={"title": "Original attributed report",
                                        "original": "Original attributed report",
                                        "label": "Original headline"}):
            began = time.monotonic()
            window._populate_feed(
                saved_ids=("offline-feed-starring",),
                english_enabled=False,
            )
            elapsed = time.monotonic() - began
        assert elapsed < 0.5, f"Qt waited {elapsed:.3f}s for Store lock"
        assert window.feed_list.count() == 1
        row = window.feed_list.item(0).data(Qt.ItemDataRole.UserRole)
        assert row["id"] == "offline-feed-starring"
        assert row["_situation_starred"] is True
        assert window.english_headlines.isChecked() is False
    finally:
        release.set()
        if worker is not None:
            worker.join(timeout=5)
            assert not worker.is_alive()
        _shutdown(app, window, controller)


def test_explicit_feed_refresh_still_reads_current_user_preferences(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        window._events = [_event()]
        window._selected_id = ""
        window._feed_explicitly_cleared = False
        with patch.object(controller, "get_setting", return_value=True) as setting, \
             patch.object(controller.store, "saved_situation_ids",
                          return_value=set()) as stars, \
             patch.object(controller, "headline_view",
                          return_value={"title": "Original attributed report",
                                        "original": "Original attributed report",
                                        "label": "Original headline"}):
            window._populate_feed()
            assert setting.called
            assert stars.called
        row = window.feed_list.item(0).data(Qt.ItemDataRole.UserRole)
        assert row["_situation_starred"] is False
        assert window.english_headlines.isChecked() is True
    finally:
        _shutdown(app, window, controller)
