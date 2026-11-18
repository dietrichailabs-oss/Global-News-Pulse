"""No-click selection retention must not query collector-owned SQLite on Qt.

An exact source-revision snapshot can carry an older pinned event and its
saved marker, even when the 500-item feed has already evicted that event.
The real Store lock is acquired just after the GUI's nonblocking revision
probe, reproducing a worker/Qt race without bypassing the revision gate.
"""
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def test_idle_snapshot_preserves_pinned_selection_without_qt_store_lookup(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    held = threading.Event()
    release = threading.Event()
    worker = None
    try:
        now = datetime.now(timezone.utc).isoformat()
        saved = controller.store.ingest([{
            "id": "offscreen-older-selected-record",
            "event_key": "offline-older-selected-event",
            "title": "Offline pinned evidence", "summary": "Synthetic test only",
            "source_id": "offline-qt-test", "publisher": "Offline fixture",
            "url": "https://example.invalid/offline",
            "published_at": now, "retrieved_at": now,
            "region": "Global", "category": "News", "synthetic": True,
            "severity": "unassessed",
        }])[0]
        event_id = str(saved["id"])
        controller.store.set_situation_saved(event_id, True)
        # Canonical evidence used by the worker after its source revision read.
        canonical = controller.event(event_id)
        assert canonical is not None
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer"):
            getattr(window, name).stop()
        window._selected_id = event_id
        window._archive_selection_id = event_id
        window._explicit_feed_selection_id = event_id
        scope = window._archive_scope_key()
        window._archive_selection_scope = scope
        window._explicit_feed_selection_scope = scope
        window._feed_explicitly_cleared = False
        filters = window.events_filters()
        revision = controller.store.content_revision()
        snapshot = {
            "revision_before": revision, "revision_after": revision,
            "scope": scope, "generation": window._idle_snapshot_generation,
            "filters": filters, "history_at": None,
            "selected_id": event_id, "archive_pin_id": event_id,
            "explicit_selection_id": event_id, "selected_event": canonical,
            # Event no longer appears in the top-500 feed page.
            "feed": [], "filter_options": controller.event_filter_options(),
            "country_evidence": [], "map_events": [], "observations": [],
            "saved_situation_ids": (event_id,),
            "english_headlines_enabled": True,
            "map_classification": None,
        }
        original_probe = controller.store.content_revision_if_available
        probed = [False]

        def hold_lock():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        def race_probe():
            value = original_probe()
            if value is not None and not probed[0]:
                probed[0] = True
                nonlocal worker
                worker = threading.Thread(target=hold_lock, daemon=True)
                worker.start()
                assert held.wait(timeout=2)
            return value

        with patch.object(controller.store, "content_revision_if_available",
                          side_effect=race_probe), \
             patch.object(controller, "event",
                          side_effect=AssertionError("Qt selected lookup reopened Store")), \
             patch.object(controller.store, "situation_state",
                          side_effect=AssertionError("Qt Star lookup reopened Store")):
            start = time.monotonic()
            window.refresh_data(_idle_snapshot=snapshot)
            elapsed = time.monotonic() - start
        assert probed[0], "The real nonblocking revision probe was not exercised"
        assert elapsed < 0.9, f"No-click pinned refresh blocked {elapsed:.3f}s"
        assert window._selected_id == event_id
        assert window._events and window._events[0]["id"] == event_id
        assert window.save_button.property("event_id") == event_id
        assert window.save_button.isEnabled()
        assert window.save_button.isChecked()
    finally:
        release.set()
        if worker:
            worker.join(timeout=5)
            assert not worker.is_alive()
        if window:
            for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                         "_collection_refresh_timer"):
                getattr(window, name).stop()
            window._force_close = True
            window.media.shutdown()
            window.close()
        controller.close()
        if window:
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_stale_selection_snapshot_is_rejected_without_any_archive_lookup(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        window._selected_id = "new-choice"
        token = {
            "selected_id": "old-choice", "archive_pin_id": "",
            "explicit_selection_id": "", "revision_after": (0, 0),
        }
        with patch.object(controller, "event",
                          side_effect=AssertionError("stale Qt archive lookup")), \
             patch.object(controller.store, "content_revision_if_available",
                          side_effect=AssertionError("stale snapshot revision probe")):
            window.refresh_data(_idle_snapshot=token)
        assert window._selected_id == "new-choice"
    finally:
        if window:
            window._force_close = True
            window.media.shutdown()
            window.close()
        controller.close()
        if window:
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
