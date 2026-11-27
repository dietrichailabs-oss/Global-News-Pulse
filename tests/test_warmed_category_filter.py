"""Offline Qt regression: warmed category filters never read SQLite in the click slot."""
import threading
import time
from datetime import datetime, timezone
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow

@pytest.fixture
def desktop(tmp_path):
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    stamp=datetime.now(timezone.utc).isoformat()
    ctl.store.ingest([
        dict(id="cat-"+name,event_key="cat-"+name,title="Synthetic "+name,
             summary="Offline regression fixture",publisher="Fixture",
             source_id="fixture",url="https://example.invalid/"+name,
             published_at=stamp,retrieved_at=stamp,category=name,
             region="Europe",country="",synthetic=True)
        for name in ("News","Health","Disaster")])
    w=MainWindow(ctl)
    w.refresh_data()
    assert w.prepare_initial_workspaces()
    w._workspace_warm_timer.stop()
    w._evidence_refresh_timer.stop()
    try:
        yield app,w,ctl
    finally:
        w._force_close=True
        for timer in (w._filter_refresh_timer,w._workspace_warm_timer,
                      w._evidence_refresh_timer,w._collection_refresh_timer,w.search_timer):
            timer.stop()
        w.media.shutdown()
        w.close()
        ctl.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()

def pump(app, predicate, timeout=8):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        app.processEvents()
        if predicate(): return True
        QTest.qWait(15)
    return False

def test_filter_switch_coalesces_and_applies_only_latest_scope(desktop,monkeypatch):
    app,w,c=desktop
    ui=threading.get_ident()
    old=c.events
    calls=[]
    def guarded(**kw):
        assert threading.get_ident()!=ui, "category filter queried archive on GUI"
        calls.append(kw.get("category",""))
        return old(**kw)
    monkeypatch.setattr(c,"events",guarded)
    w.category.setCurrentIndex(w.category.findData("Health"))
    w.category.setCurrentIndex(w.category.findData("Disaster"))
    assert calls==[]
    assert w._filter_refresh_pending and not w.world_map.isEnabled()
    assert "previous results" in w.count_label.text()
    assert pump(app,lambda:not w._filter_refresh_pending)
    assert calls and set(calls)=={"Disaster"}
    assert w._events and all(e["category"]=="Disaster" for e in w._events)
    assert w.world_map.isEnabled()
    assert w.save_button.property("event_id")==w._selected_id

def test_stale_filter_worker_cannot_overwrite_newer_category(desktop,monkeypatch):
    app,w,c=desktop
    old=c.events
    entered,release=threading.Event(),threading.Event()
    def delayed(**kw):
        if kw.get("category")=="Health" and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return old(**kw)
    monkeypatch.setattr(c,"events",delayed)
    try:
        w.category.setCurrentIndex(w.category.findData("Health"))
        assert pump(app,entered.is_set,3)
        w.category.setCurrentIndex(w.category.findData("Disaster"))
        assert w._filter_refresh_pending
        release.set()
        assert pump(app,lambda:not w._filter_refresh_pending)
        assert w._events and all(e["category"]=="Disaster" for e in w._events)
        assert w.save_button.property("event_id")==w._selected_id
    finally:
        release.set()
