"""Exact paging, concurrent source change rejection and warning path equivalence."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import copy
import threading
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainterPath
from PySide6.QtCore import Qt
from global_pulse.core import Store,MapSnapshotChanged
from global_pulse.map_widget import WorldMap
from global_pulse.map_area_layer import prepare_warning_areas
from global_pulse.map_evidence import wrapped_polygons
from test_issue82_batched_map_country_evidence import report
from test_crisis_context_display_cap import report as crisis_report


def test_cooperative_pages_match_atomic_order_evidence_and_retained_projection(tmp_path):
    now=datetime.now(timezone.utc)-timedelta(minutes=3)
    recent=now.isoformat()
    old=(now-timedelta(days=9)).isoformat()
    since=(now-timedelta(days=7)).isoformat()
    with Store(tmp_path/"cooperative.sqlite3",mode="synthetic") as store:
        assert store.ingest([report(900,at=old,severity="critical")],now=old)
        rows=[report(i,at=recent,severity="critical" if i%3==0 else "moderate",
                     category="Disaster" if i%2==0 else "Infrastructure")
              for i in range(340)]
        assert len(store.ingest(rows,now=recent))==340
        for filters in (dict(map_evidence=True,limit=300,since=since,keep_significant=True),
                        dict(map_view=True,limit=101,since=since,keep_significant=True),
                        dict(map_evidence=True,limit=100,category="Disaster",query="fictional"),
                        dict(map_evidence=True,limit=500,before=recent)):
            original=store.list_events(**filters)
            cooperative=store.list_events(**filters,_cooperative_map=True)
            assert cooperative==original
        pages=[]
        original_page=store._map_evidence_page_unlocked
        def observed(page):
            pages.append(len(page))
            return original_page(page)
        with patch.object(store,"_map_evidence_page_unlocked",observed):
            actual=store.list_events(map_evidence=True,limit=300,_cooperative_map=True)
        assert len(actual)==300 and len(pages)>1 and max(pages)<=32


def test_cooperative_page_rejects_concurrent_write_not_mixed_results(tmp_path):
    now=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
    with Store(tmp_path/"cooperative-race.sqlite3",mode="synthetic") as store:
        assert len(store.ingest([report(i,at=now) for i in range(300)],now=now))==300
        started=threading.Event()
        committed=threading.Event()
        errors=[]
        original=store._map_evidence_page_unlocked
        def writer():
            try:
                assert started.wait(5)
                store.ingest([report(9999,at=now)],now=now)
            except Exception as exc:errors.append(exc)
            finally:committed.set()
        thread=threading.Thread(target=writer)
        thread.start()
        real_sleep=__import__("time").sleep
        def yield_after_page(seconds):
            started.set()
            assert committed.wait(5),"writer could not acquire released map lock"
            real_sleep(seconds)
        try:
            with patch("global_pulse.core.time.sleep",side_effect=yield_after_page):
                with pytest.raises(MapSnapshotChanged):
                    store.list_events(map_evidence=True,limit=300,_cooperative_map=True)
        finally:
            started.set()
            thread.join(timeout=5)
        assert not errors and not thread.is_alive()
        assert store.list_events(map_evidence=True,limit=300,_cooperative_map=True)==store.list_events(map_evidence=True,limit=300)


def test_cooperative_crisis_scope_keeps_topical_screen_and_order(tmp_path):
    now=datetime.now(timezone.utc)-timedelta(minutes=2)
    stamp=now.isoformat()
    with Store(tmp_path/"cooperative-crisis.sqlite3",mode="live") as store:
        rows=[crisis_report("a"+str(i),"FICTIONAL armed conflict in Ukraine","Conflict",stamp)
              for i in range(35)]
        rows += [crisis_report("b"+str(i),"FICTIONAL cereal output measure","Economy",stamp)
                 for i in range(60)]
        store.ingest(rows,now=stamp)
        assert store.list_crisis_context(now=now,limit=20,cooperative=True)==store.list_crisis_context(now=now,limit=20)


def test_worker_geometry_keeps_holes_dateline_hits_and_reuses_only_equal_paths():
    app=QApplication.instance() or QApplication([])
    world=WorldMap()
    try:
        geometry={"type":"Polygon","coordinates":[
            [[170,20],[-170,20],[-170,40],[170,40],[170,20]],
            [[175,25],[-175,25],[-175,35],[175,35],[175,25]]]}
        event={"id":"fixture","category":"Disaster","status":"active",
               "severity":"critical","map_areas":[{"geometry":geometry,"report_id":"warning"}]}
        rows=[event]
        result=[]
        t=threading.Thread(target=lambda:result.append(prepare_warning_areas(rows)))
        t.start();t.join(timeout=5)
        assert result and not t.is_alive()
        with patch("global_pulse.map_area_layer.wrapped_polygons",side_effect=AssertionError("GUI reparsed worker geometry")):
            world.area_layer.set_events(rows,prepared=result[0])
        first=world.area_layer.paths[0][0]
        original=QPainterPath()
        original.setFillRule(Qt.FillRule.OddEvenFill)
        for polygon in wrapped_polygons(geometry):
            for ring in polygon:
                original.moveTo(world.normalized(*ring[0]))
                for position in ring[1:]:original.lineTo(world.normalized(*position))
                original.closeSubpath()
        assert first.boundingRect()==original.boundingRect()
        for lon in (169,172,177,-177,-172,-169):
            for lat in (19,23,28,38,41):
                point=world.normalized(lon,lat)
                assert first.contains(point)==original.contains(point)
        revised=copy.deepcopy(event)
        revised["severity"]="high"
        world.area_layer.set_events([revised],prepared=prepare_warning_areas([revised]))
        path,current,area=world.area_layer.paths[0]
        assert path is first and current is revised and area is revised["map_areas"][0]
        changed=copy.deepcopy(revised)
        changed["map_areas"][0]["geometry"]={"type":"Polygon","coordinates":[
            [[10,10],[12,10],[12,12],[10,12],[10,10]]]}
        world.area_layer.set_events([changed],prepared=result[0])
        assert world.area_layer.paths[0][0] is not first
        assert world.area_layer.paths[0][1] is changed
    finally:
        world.close();world.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
