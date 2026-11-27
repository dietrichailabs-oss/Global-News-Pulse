"""Issue22 no-click map classification: pure worker, exact Qt state.

Fictional offline source reports only. These tests do not certify physical
Windows 11 frame times, in-app YouTube playback, or release permission.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse import crisis_overlay, map_widget
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _report(i, category="Conflict"):
    at=datetime.now(timezone.utc).isoformat()
    return {
        "id":f"map-worker-{i}", "event_key":f"map-worker:{i}",
        "title":f"FICTIONAL source-shaped {category} report {i}",
        "summary":"Fictional offline test, not a live situation",
        "country":"Ukraine", "country_basis":"explicit_record",
        "source_id":"offline-map-worker", "publisher":"Offline test",
        "url":f"https://example.invalid/worker/{i}",
        "published_at":at, "retrieved_at":at,
        "region":"Europe", "category":category, "synthetic":True,
    }


def _drain(app,done,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.processEvents()
        if done():return True
        QTest.qWait(25)
    return False


def test_idle_map_classification_runs_on_store_worker_without_widget_classification(tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        controller.store.ingest([_report(i) for i in range(55)])
        window=MainWindow(controller)
        window.refresh_data()
        assert window.prepare_initial_workspaces()
        window._workspace_warm_timer.stop()
        gui_id=threading.get_ident()
        worker_threads=[]
        gui_calls=[]
        original=crisis_overlay.build_country_activity

        def worker_classifier(*args,**kwargs):
            worker_threads.append(threading.get_ident())
            return original(*args,**kwargs)

        def gui_classifier(*args,**kwargs):
            gui_calls.append(threading.get_ident())
            return original(*args,**kwargs)

        monkeypatch.setattr(crisis_overlay,"build_country_activity",worker_classifier)
        monkeypatch.setattr(map_widget,"build_country_activity",gui_classifier)
        window._last_navigation_at=time.monotonic()-5
        window._last_full_refresh_at=time.monotonic()-10
        window._start_idle_snapshot()
        assert _drain(app,lambda:bool(worker_threads) and
                      not window._idle_snapshot_inflight)
        assert all(t!=gui_id for t in worker_threads),worker_threads
        assert not gui_calls,"GUI reran source classifier after worker snapshot"
        assert len(window.world_map.evidence_events)==55
        assert len(window._events)==55
        assert not controller.monitoring
    finally:
        if window is not None:
            window._force_close=True
            for name in ("_workspace_warm_timer","_evidence_refresh_timer",
                         "_collection_refresh_timer","search_timer"):
                getattr(window,name).stop()
            window.media.shutdown()
            window.close()
        controller.close()
        if window is not None:
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_map_preclassification_fails_closed_for_different_category_or_object(monkeypatch):
    app=QApplication.instance() or QApplication([])
    widget=map_widget.WorldMap()
    original=map_widget.build_country_activity
    fallback=[]
    def tracked(*args,**kwargs):
        fallback.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(map_widget,"build_country_activity",tracked)
    records=[_report(i,"Conflict") for i in range(3)]
    prepared={
        "category_key":None,
        "record_ids":tuple(id(record) for record in records),
        "activity":{}, "credits":set(),
    }
    widget.set_events(records,country_events=records,preclassified_country=prepared)
    assert fallback==[],"Identical source/category should use worker result"
    widget.categories={"Health"}
    widget.set_events(records,country_events=records,preclassified_country=prepared)
    assert len(fallback)==1,"Changed map category must reclassify"
    widget.categories=None
    copied=[dict(record) for record in records]
    widget.set_events(copied,country_events=copied,preclassified_country=prepared)
    assert len(fallback)==2,"Copied source records cannot inherit old credits"
    assert widget._pending_preclassified_country is None
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()
