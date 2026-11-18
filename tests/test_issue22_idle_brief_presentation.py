"""Real Qt regression: hidden Brief presentation never re-enters a collector-held Store lock.

All source inputs are fictional/offline. Hosted Qt timings do not prove
physical Windows 11 responsiveness, live media, or rights/release acceptance.
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _stop(app, window, controller):
    if window is not None:
        window._force_close = True
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer", "search_timer"):
            getattr(window, name).stop()
        window.media.shutdown()
        window.close()
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _fixture():
    at = datetime.now(timezone.utc).isoformat()
    return {
        "id": "brief-presentation-race", "event_key": "offline-brief-race",
        "title": "FICTIONAL offline source verification", "summary": "No real incident",
        "source_id": "offline-brief-test", "publisher": "Fictional test publisher",
        "url": "https://example.invalid/brief", "published_at": at,
        "retrieved_at": at, "country": "", "region": "Global",
        "category": "News", "severity": "unassessed", "synthetic": True,
    }


def test_hidden_brief_precheck_race_preserves_cache_and_never_blocks_qt(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    release, held = threading.Event(), threading.Event()
    locker = None
    try:
        controller.store.ingest([_fixture()])
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        window._workspace_warm_timer.stop()
        window._evidence_refresh_timer.stop()
        window._background_warm_enabled = True
        window._last_navigation_at = time.monotonic() - 10
        window._dirty_pages = {5}
        period = window.brief_period.currentText().lower()
        cached = controller.brief_events(
            since=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),
            period=period)
        assert cached, "Offline synthetic brief fixture must be present"
        revision = controller.store.content_revision()
        window._deferred_brief_events = cached
        window._deferred_brief_revision = revision
        window._deferred_brief_period = period
        window._idle_brief_inflight = False
        probe = controller.store.content_revision_if_available
        probes = [0]

        def occupy_store():
            with controller.store._lock:
                held.set()
                release.wait(timeout=4)

        def racing_probe():
            value = probe()
            probes[0] += 1
            if probes[0] == 1:
                nonlocal locker
                locker = threading.Thread(target=occupy_store, daemon=True)
                locker.start()
                assert held.wait(timeout=2), "Store lock holder not admitted"
            return value

        with patch.object(controller.store, "content_revision_if_available",
                          side_effect=racing_probe), \
             patch.object(controller, "brief_events",
                          side_effect=AssertionError("Idle Brief SQL on Qt")):
            started = time.monotonic()
            window._warm_next_workspace()
            elapsed = time.monotonic() - started
            assert elapsed < 0.6, f"Hidden Brief warm blocked Qt for {elapsed:.3f}s"
            assert probes[0] >= 2, "Second nonblocking revision probe was not made"
            assert 5 in window._dirty_pages, "Pending Brief warm was dropped"
            assert window._deferred_brief_events is cached, "Busy worker cache was discarded"
            assert window._workspace_warm_timer.isActive()
            release.set()
            locker.join(timeout=3)
            assert not locker.is_alive()
            window._workspace_warm_timer.stop()
            window._warm_next_workspace()
            window._workspace_warm_timer.stop()
            assert 5 not in window._dirty_pages
            assert window._deferred_brief_events is None
            assert "FICTIONAL" in window.brief_browser.toPlainText()
    finally:
        release.set()
        if locker is not None:
            locker.join(timeout=4)
        _stop(app, window, controller)


def test_missing_or_stale_idle_brief_never_falls_back_to_qt_sql(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        controller.store.ingest([_fixture()])
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        window._workspace_warm_timer.stop()
        window._evidence_refresh_timer.stop()
        calls = []
        with patch.object(window, "_schedule_evidence_refresh",
                          side_effect=lambda: calls.append("new worker")), \
             patch.object(controller, "brief_events",
                          side_effect=AssertionError("Passive SQL fallback")):
            assert window._generate_brief(idle=True) is False
            assert calls == ["new worker"]
            revision = controller.store.content_revision()
            window._deferred_brief_events = [{"id": "old", "title": "Stale brief"}]
            window._deferred_brief_revision = revision
            window._deferred_brief_period = window.brief_period.currentText().lower()
            controller.store.ingest([dict(_fixture(), id="brief-after-revision",
                                          event_key="offline-new-revision")])
            assert window._generate_brief(idle=True) is False
            assert window._deferred_brief_events is None
            assert calls == ["new worker", "new worker"]
            assert "Stale brief" not in window.brief_browser.toPlainText()
        # Deliberate manual refresh continues to query current source.
        assert window._generate_brief() is True
        assert "FICTIONAL" in window.brief_browser.toPlainText()
    finally:
        _stop(app, window, controller)
