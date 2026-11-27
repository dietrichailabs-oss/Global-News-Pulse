"""A passive translated-headline repaint must not wait for collector SQLite.

Real Qt, a persisted canonical selected event and a worker-held Store RLock.
This is bounded hosted testing, not proof of physical Windows11 smoothness.
"""
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _close(app, window, controller):
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


def _real_event(controller):
    when = datetime.now(timezone.utc).isoformat()
    events = controller.store.ingest([{
        "id": "idle-headline-change-report",
        "event_key": "offline-idle-headline-change",
        "title": "Synthetic English headline for Qt idle signal",
        "summary": "Offline fixture; not a real-world finding",
        "source_id": "offline-qt-test", "publisher": "Offline fixture",
        "url": "https://example.invalid/offline-qt-test",
        "published_at": when, "retrieved_at": when,
        "region": "Global", "category": "News", "synthetic": True,
        "severity": "unassessed",
    }])
    assert len(events) == 1
    return events[0]


@pytest.mark.parametrize("saved,english", [(True, True), (False, False)])
def test_passive_headline_signal_does_not_reopen_store_for_rows_or_selection(
        tmp_path, saved, english):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    release, held = threading.Event(), threading.Event()
    worker = None
    try:
        selected = _real_event(controller)
        identity = str(selected["id"])
        controller.store.set_situation_saved(identity, saved)
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        window._workspace_warm_timer.stop()
        window._evidence_refresh_timer.stop()
        window._collection_refresh_timer.stop()

        # The selected canonical event is in the revision-checked visible feed.
        # Other rows exercise the former per-row preference read path.
        additional = [
            dict(selected, id=f"offline-headline-aux-{index}",
                 title=f"Original synthetic English headline {index}")
            for index in range(24)
        ]
        window._events = [selected] + additional
        window._selected_id = identity
        window._feed_explicitly_cleared = False
        window._populate_feed(
            saved_ids={identity} if saved else set(), english_enabled=english)
        assert window.feed_list.count() == 25

        def hold_lock():
            with controller.store._lock:
                held.set()
                release.wait(timeout=5)

        worker = threading.Thread(target=hold_lock, daemon=True)
        worker.start()
        assert held.wait(timeout=2)
        with patch.object(controller, "get_setting",
                          side_effect=AssertionError("Qt headline setting read")), \
             patch.object(controller, "event",
                          side_effect=AssertionError("Qt selected-event SQL read")), \
             patch.object(controller.store, "situation_state",
                          side_effect=AssertionError("Qt Star SQL read")):
            started = time.monotonic()
            window._refresh_translated_headlines()
            elapsed = time.monotonic() - started
        assert elapsed < 0.75, f"Passive GUI callback stalled {elapsed:.3f}s"
        assert window.save_button.property("event_id") == identity
        assert window.save_button.isChecked() is saved
        assert window.save_button.isEnabled()
        first = window.feed_list.item(0).data(Qt.ItemDataRole.UserRole)
        assert first["_situation_starred"] is saved
        assert first["_translation_label"] == (
            "Original English headline" if english else "Original headline")
    finally:
        release.set()
        if worker is not None:
            worker.join(timeout=5)
            assert not worker.is_alive()
        _close(app, window, controller)


def test_passive_star_display_cannot_authorize_write_to_missing_event(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        window._selected_id = "not-an-archived-event"
        window._sync_situation_star({"id": window._selected_id},
                                    saved_override=True)
        assert window.save_button.isChecked()
        # Actual click never trusts the display hint. Its Store guard must
        # reject an absent canonical event and disable the stale action.
        window._toggle_selected_situation(False)
        assert not window.save_button.isEnabled()
        assert controller.store.situation_state(window._selected_id) is None
    finally:
        _close(app, window, controller)
