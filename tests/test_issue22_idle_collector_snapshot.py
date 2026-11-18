"""Exact post-splash idle SQLite snapshot behavior under a real Qt event loop.

Offline fictional source records only. The tests assert thread ownership,
source revision freshness, and selected-UI correctness, not physical Win11
smoothness, live radio, or YouTube playback.
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _report(i):
    from datetime import datetime, timezone
    at = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"async-idle-{i}", "event_key": f"async-idle:{i}",
        "title": f"FICTIONAL idle test record {i}", "summary": "Not a real event",
        "source_id": "offline-fixture", "publisher": "Offline Fixture",
        "url": f"https://example.invalid/idle/{i}",
        "published_at": at, "retrieved_at": at,
        "country": "", "region": "Global", "category": "News", "synthetic": True,
    }


def _pump_until(app, predicate, timeout=6):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():
            return True
        QTest.qWait(25)
    return False


def _shutdown(app, window, controller):
    if window is not None:
        window._force_close=True
        for key in ("_evidence_refresh_timer","_workspace_warm_timer",
                    "_collection_refresh_timer","search_timer"):
            getattr(window,key).stop()
        window.media.shutdown()
        window.close()
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_collector_post_splash_queries_only_worker_and_renders_on_gui(tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path, demo=True)
    window=None
    try:
        controller.store.ingest([_report(i) for i in range(35)])
        window=MainWindow(controller)
        window.refresh_data()
        assert window.prepare_initial_workspaces()
        window._workspace_warm_timer.stop()
        owner=threading.get_ident()
        reads=[]
        original=controller.events

        def watched(**filters):
            reads.append(threading.get_ident())
            return original(**filters)

        monkeypatch.setattr(controller,"events",watched)
        window._last_navigation_at=time.monotonic()-5
        window._last_full_refresh_at=time.monotonic()-10
        controller.evidence_changed.emit()
        assert _pump_until(app,lambda: len(reads)>=3 and not window._idle_snapshot_inflight
                           and not window._evidence_refresh_timer.isActive()), reads
        assert reads and all(thread!=owner for thread in reads), reads
        assert len(window._events)==35
        assert all(e.get("id") for e in window._events)
        assert not controller.monitoring
    finally:
        _shutdown(app,window,controller)


def test_collector_snapshot_discards_change_during_worker_read(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path, demo=True)
    window=None
    release=threading.Event()
    try:
        controller.store.ingest([_report(100)])
        window=MainWindow(controller)
        window.refresh_data()
        assert window.prepare_initial_workspaces()
        window._workspace_warm_timer.stop()
        original=controller.events
        entered=threading.Event()
        read_once=threading.Event()

        def slow_worker(**filters):
            if threading.get_ident()!=threading.main_thread().ident and not read_once.is_set():
                read_once.set()
                entered.set()
                release.wait(timeout=4)
            return original(**filters)

        monkeypatch.setattr(controller,"events",slow_worker)
        window._last_navigation_at=time.monotonic()-5
        window._last_full_refresh_at=time.monotonic()-10
        window._start_idle_snapshot()
        assert entered.wait(2), "Worker did not start"
        controller.store.ingest([_report(101)])
        release.set()
        # An old revision cannot commit even if the report changes between
        # the first and last distinct Store read.
        assert _pump_until(app,lambda: not window._idle_snapshot_inflight), "Worker result stalled"
        assert {e["id"] for e in window._events}=={"async-idle:100"} or len(window._events)==1
        window._last_navigation_at=time.monotonic()-5
        window._last_full_refresh_at=time.monotonic()-10
        assert _pump_until(app,lambda: len(window._events)==2,timeout=7)
        assert len({e["id"] for e in window._events})==2
    finally:
        release.set()
        _shutdown(app,window,controller)
