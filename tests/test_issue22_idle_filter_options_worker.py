"""No-click post-splash selector metadata stays off the Qt thread.

Offline fictional evidence, real Store/Qt widgets, no assertion about physical
Windows 11 smoothness, playback, public rights, or native installer acceptance.
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _report(i, category, region):
    from datetime import datetime, timezone
    at = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"selector-worker-{i}", "event_key": f"selector-worker:{i}",
        "title": f"FICTIONAL source record {i}",
        "summary": "Synthetic offline test, not an actual event",
        "source_id": "synthetic-fixture", "publisher": "Synthetic Fixture",
        "url": f"https://example.invalid/filter/{i}",
        "published_at": at, "retrieved_at": at,
        "country": "", "region": region, "category": category, "synthetic": True,
    }


def _pump_until(app, predicate, timeout=7):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        QTest.qWait(20)
    return False


def _stop(app, window, controller):
    if window is not None:
        window._force_close = True
        for name in ("_evidence_refresh_timer", "_workspace_warm_timer",
                     "_collection_refresh_timer", "search_timer"):
            getattr(window, name).stop()
        window.media.shutdown()
        window.close()
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _window(app, controller):
    window = MainWindow(controller)
    window.show()
    app.processEvents()
    window.refresh_data()
    assert window.prepare_initial_workspaces()
    window._workspace_warm_timer.stop()
    window._evidence_refresh_timer.stop()
    return window


def test_no_click_filter_options_sql_only_in_revision_checked_worker(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        controller.store.ingest([_report(1, "News", "Old region")])
        window = _window(app, controller)
        # User-selected category disappears from archive: keep the explicit
        # choice, rather than silently selecting All on a newer snapshot.
        blocked = window.category.blockSignals(True)
        try:
            window.category.addItem("Retired topic", "Retired topic")
            window.category.setCurrentIndex(window.category.findData("Retired topic"))
        finally:
            window.category.blockSignals(blocked)
        controller.store.ingest([_report(2, "Health", "New region")])
        original = controller.event_filter_options
        ui_thread = threading.get_ident()
        seen = []

        def guarded_options():
            thread = threading.get_ident()
            seen.append(thread)
            assert thread != ui_thread, "idle selector SQL ran on Qt main thread"
            return original()

        monkeypatch.setattr(controller, "event_filter_options", guarded_options)
        window._last_navigation_at = time.monotonic() - 10
        window._last_full_refresh_at = time.monotonic() - 10
        window._start_idle_snapshot()
        assert _pump_until(
            app,
            lambda: (bool(seen) and not window._idle_snapshot_inflight
                     and window.category.findData("Health") >= 0
                     and window.region.findData("New region") >= 0),
        ), "idle worker selector metadata was not applied"
        assert all(thread != ui_thread for thread in seen)
        assert window.category.currentData() == "Retired topic"
        assert window.category.findData("Retired topic") >= 0
        assert window.category.findData("News") >= 0

        # An explicit user-triggered refresh retains original synchronous
        # semantics, unlike background collector notifications.
        monkeypatch.setattr(controller, "event_filter_options", original)
        window.refresh_data()
        assert window.category.currentData() == "Retired topic"
    finally:
        _stop(app, window, controller)


def test_mixed_revision_worker_selector_options_never_commit(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    entered = threading.Event()
    release = threading.Event()
    try:
        controller.store.ingest([_report(10, "News", "Old region")])
        window = _window(app, controller)
        assert window.category.findData("Health") < 0
        original_events = controller.events
        worker_ident = threading.get_ident()

        def delayed_events(**filters):
            if threading.get_ident() != worker_ident and not entered.is_set():
                entered.set()
                release.wait(4)
            return original_events(**filters)

        monkeypatch.setattr(controller, "events", delayed_events)
        window._last_navigation_at = time.monotonic() - 10
        window._last_full_refresh_at = time.monotonic() - 10
        window._start_idle_snapshot()
        assert entered.wait(2), "worker never started"
        # Options were read before worker paused, so this mutation invalidates
        # the whole result rather than painting stale selector metadata.
        controller.store.ingest([_report(11, "Health", "New region")])
        release.set()
        assert _pump_until(app, lambda: not window._idle_snapshot_inflight)
        window._evidence_refresh_timer.stop()
        assert window.category.findData("Health") < 0
        monkeypatch.setattr(controller, "events", original_events)
        window.refresh_data()
        assert window.category.findData("Health") >= 0
        assert window.region.findData("New region") >= 0
    finally:
        release.set()
        _stop(app, window, controller)
