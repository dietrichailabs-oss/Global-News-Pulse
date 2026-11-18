"""Qt idle source-consistent headline rendering must not reacquire Store SQLite."""
import threading
import time
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _event():
    title = "Synthetic English source headline"
    return {"id": "offline-headline-source", "title": title,
            "region": "Global", "category": "News", "severity": "unassessed",
            "status": "active", "verification": "unverified",
            "updated_at": "2026-11-18T00:00:00+00:00",
            "recap": "Synthetic local source; no real crisis claim",
            "reports": [{"id": "offline-report", "title": title, "language": "en",
                         "evidence_status": "active", "status": "active",
                         "kind": "report", "url": "https://example.invalid/report",
                         "publisher": "Offline fixture"}], "synthetic": True}


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


def test_collector_headlines_do_not_reopen_qt_store_lock(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    worker = None
    release, held = threading.Event(), threading.Event()
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        window._workspace_warm_timer.stop()
        window._evidence_refresh_timer.stop()
        window._events = [_event()]
        window._selected_id = ""
        window._feed_explicitly_cleared = False

        def hold_store_lock():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        worker = threading.Thread(target=hold_store_lock, daemon=True)
        worker.start()
        assert held.wait(timeout=2)
        # Unlike the older metadata regression, use real headline_view().
        with patch.object(controller, "get_setting",
                          side_effect=AssertionError("Qt read SQLite preference")):
            started = time.monotonic()
            window._populate_feed(saved_ids=(), english_enabled=True)
            assert time.monotonic() - started < 0.5
            assert window.feed_list.count() == 1
            row = window.feed_list.item(0).data(Qt.ItemDataRole.UserRole)
            assert row["_translation_label"] == "Original English headline"
            # Other persisted Star operations are an independent scope.
            with patch.object(window, "_sync_situation_star", return_value=None):
                window._render_event(_event(), update_media=False,
                                     english_enabled=True)
    finally:
        release.set()
        if worker is not None:
            worker.join(timeout=5)
            assert not worker.is_alive()
        _shutdown(app, window, controller)


def test_manual_headline_view_uses_current_preference(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    try:
        with patch.object(controller, "get_setting", return_value=False) as enabled:
            assert controller.headline_view(_event())["label"] == "Original headline"
            assert enabled.call_count == 1
        with patch.object(controller, "get_setting", return_value=True) as enabled:
            assert controller.headline_view(_event())["label"] == "Original English headline"
            assert enabled.call_count == 1
        with patch.object(controller, "get_setting",
                          side_effect=AssertionError("unexpected source read")):
            assert controller.headline_view(
                _event(), enabled_override=True)["label"] == "Original English headline"
    finally:
        controller.close()
