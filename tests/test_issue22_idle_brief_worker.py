"""Real Qt regression for guarded post-splash Daily/Weekly brief prewarm.

Offline fictional events. No API/network/media or physical responsiveness claim.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _report(n, category="Health"):
    at=datetime.now(timezone.utc).isoformat()
    return {
        "id": f"brief-idle-{n}", "event_key": f"brief-idle:{n}",
        "title": f"FICTIONAL brief category {category} record {n}",
        "summary": "Synthetic source evidence, not a real-world incident",
        "source_id": "synthetic-brief-fixture",
        "publisher": "Synthetic fixture",
        "url": f"https://example.invalid/brief/{n}",
        "published_at": at, "retrieved_at": at,
        "country": "", "region": "Global", "category": category,
        "synthetic": True, "severity": "unassessed",
    }


def _pump_until(app, predicate, timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():
            return True
        QTest.qWait(20)
    return False


def _stop(app, window, controller):
    if window is not None:
        window._force_close=True
        for name in ("_evidence_refresh_timer","_workspace_warm_timer",
                     "_collection_refresh_timer","search_timer"):
            getattr(window,name).stop()
        window.media.shutdown()
        window.close()
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def _ready(app, controller):
    window=MainWindow(controller)
    window.show()
    app.processEvents()
    window.refresh_data()
    assert window.prepare_initial_workspaces()
    window.open_page(0)
    window._workspace_warm_timer.stop()
    window._evidence_refresh_timer.stop()
    return window


def _snapshot(app, window):
    window._last_navigation_at=time.monotonic()-10
    window._last_full_refresh_at=time.monotonic()-10
    window._start_idle_snapshot()
    assert _pump_until(app,lambda: not window._idle_snapshot_inflight
                       and window._deferred_brief_events is not None), "worker brief was not applied"
    window._workspace_warm_timer.stop()
    window._evidence_refresh_timer.stop()


def test_post_splash_brief_sql_only_worker_and_hidden_warm_has_no_sql(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        assert controller.store.ingest([_report(i,("Health","Conflict","Economy")[i%3])
                                        for i in range(12)])
        window=_ready(app,controller)
        controller.store.ingest([_report(20,"News")])
        original=controller.brief_events
        owner=threading.get_ident()
        calls=[]

        def guarded_brief(*,since,period="daily"):
            calls.append((threading.get_ident(),period))
            assert threading.get_ident()!=owner, "hidden brief query blocked Qt"
            return original(since=since,period=period)

        monkeypatch.setattr(controller,"brief_events",guarded_brief)
        _snapshot(app,window)
        assert calls and all(thread!=owner for thread,_ in calls),calls
        assert window._deferred_brief_period=="daily"
        assert 5 in window._dirty_pages

        # The normal scheduled idle callback must consume the worker's
        # revision-consistent source evidence; never reread archive on Qt.
        window._dirty_pages={5}
        window._last_navigation_at=time.monotonic()-10
        window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert 5 not in window._dirty_pages
        assert window._deferred_brief_events is None
        assert "FICTIONAL" in window.brief_browser.toPlainText()
        assert all(thread!=owner for thread,_ in calls)
    finally:
        _stop(app,window,controller)


def test_changed_evidence_and_manual_period_reject_stale_brief_cache(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        controller.store.ingest([_report(100,"News")])
        window=_ready(app,controller)
        _snapshot(app,window)
        cached=window._deferred_brief_events
        assert cached is not None

        # A report arriving after worker completion invalidates its snapshot.
        controller.store.ingest([_report(101,"Health")])
        owner=threading.get_ident()
        original=controller.brief_events
        calls=[]

        def watched(*,since,period="daily"):
            calls.append((threading.get_ident(),period))
            return original(since=since,period=period)

        monkeypatch.setattr(controller,"brief_events",watched)
        window._generate_brief()
        assert calls and calls[-1]==(owner,"daily")
        assert window._deferred_brief_events is None
        assert "Health" in window.brief_browser.toPlainText()

        # A fresh matching snapshot also becomes invalid if the user changes
        # Daily to Weekly, without relying on a false cache hit.
        _snapshot(app,window)
        window.brief_period.setCurrentIndex(1)
        window._generate_brief()
        assert calls[-1]==(owner,"weekly")
        assert window._deferred_brief_events is None
    finally:
        _stop(app,window,controller)
