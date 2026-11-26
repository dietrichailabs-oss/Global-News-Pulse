"""Matched offline Store/Qt stress probe. No real sources or physical acceptance.

Run on both the candidate and exact predecessor using the same fixtures.
Candidate must preserve all canonical red IDs. Baseline records any mismatch
without turning a predecessor finding into a shipping acceptance.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
import threading
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QCoreApplication,QEvent,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from global_pulse.brief_selection import critical_alerts,overview_evidence_candidates,overview_html
from global_pulse.controller import Controller
from global_pulse.hazards import HAZARD_KEYS
from global_pulse.ui import MainWindow

class RecordingLock:
    def __init__(self,lock):
        self.backing=lock
        self.owners={}
        self.sections=[]
    def acquire(self,blocking=True,timeout=-1):
        ok=self.backing.acquire(blocking,timeout)
        if ok:
            who=threading.get_ident()
            start,depth=self.owners.get(who,(time.perf_counter(),0))
            self.owners[who]=(start,depth+1)
        return ok
    def release(self):
        who=threading.get_ident()
        start,depth=self.owners[who]
        if depth==1:
            self.sections.append((time.perf_counter()-start)*1000)
            del self.owners[who]
        else:self.owners[who]=(start,depth-1)
        self.backing.release()
    def __enter__(self):
        self.acquire()
        return self
    def __exit__(self,*args):
        self.release()

def stats(values):
    if not values:return {"count":0}
    values=sorted(values)
    return {"count":len(values),"median_ms":round(statistics.median(values),3),
            "p95_ms":round(values[min(len(values)-1,math.ceil(.95*len(values))-1)],3),
            "max_ms":round(values[-1],3)}

def report(index,stamp,*,severity="critical",category="Disaster"):
    lon=-166+(index*137%33200)/100
    lat=-62+(index*83%12400)/100
    kind=HAZARD_KEYS[index%len(HAZARD_KEYS)]
    row=dict(id=f"loaded-red-{index}",event_key=f"loaded-red:{index}",
             title=f"FICTIONAL loaded archive report {index}",
             summary="Offline synthetic record, not an actual event",
             source_id="loaded-offline-fixture",publisher="Synthetic fixture",
             url=f"https://example.invalid/loaded/{index}",published_at=stamp,
             retrieved_at=stamp,category=category,severity=severity,
             latitude=lat,longitude=lon,geo_precision="exact",region="Global",
             country="",synthetic=True,official=True,
             official_scope="measurement",hazard_types=[kind] if category=="Disaster" else [])
    if 20<=index<200 and category=="Disaster":
        # 180 distinct provider polygons, 501 vertices each, no invented
        # centroids. 90,180 vertices approach the admitted 100k budget.
        ring=[[round(lon+.15*math.cos(2*math.pi*k/500),6),
               round(lat+.15*math.sin(2*math.pi*k/500),6)] for k in range(500)]
        ring.append(list(ring[0]))
        row["area_geometry"]={"type":"Polygon","coordinates":[ring]}
    return row

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",action="store_true")
    args=parser.parse_args()
    app=QApplication.instance() or QApplication([])
    summary={"baseline":args.baseline}
    started=time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        ctl=Controller(Path(directory),demo=True)
        w=None
        timer=QTimer()
        gaps=[]
        last=[time.perf_counter()]
        def beat():
            now=time.perf_counter()
            gaps.append((now-last[0])*1000)
            last[0]=now
        timer.setInterval(20)
        timer.timeout.connect(beat)
        writer=None
        launch=threading.Event()
        written=threading.Event()
        writer_errors=[]
        try:
            now=datetime.now(timezone.utc)-timedelta(minutes=4)
            recent=now.isoformat()
            retained=(now-timedelta(days=8)).isoformat()
            # 5,005 active red records plus 495 ordinary records. Five red
            # records beyond the cap force the true canonical tie-break.
            older=[report(i,retained) for i in range(10)]
            assert len(ctl.store.ingest(older,now=retained))==10
            remaining=[report(i,recent) for i in range(10,5005)]
            remaining.extend(report(i,recent,severity="moderate",category="Health")
                             for i in range(5005,5500))
            for offset in range(0,len(remaining),1000):
                batch=remaining[offset:offset+1000]
                ctl.store.ingest(batch,now=recent)
                assert not ctl.store.last_ingest_errors,ctl.store.last_ingest_errors[:2]
            # Inert future/withdrawn fixtures must not promote to current red.
            future=report(5501,(now+timedelta(days=1)).isoformat())
            ctl.store.ingest([future],now=recent)
            revoked=report(5502,recent)
            ctl.store.ingest([revoked],now=recent)
            ctl.store.ingest([dict(revoked,kind="retraction",status="retracted",
                                   title="FICTIONAL withdrawn loaded record")],now=recent)
            assert ctl.store.stats()["events"]>=5500
            observations=[{"indicator":f"fixture_{i%2}","indicator_name":"Synthetic measurement",
                           "country":f"Test Country {i%200:03d}","date":str(1990+i//200),
                           "value":float(i%100),"source_id":"offline-measurement",
                           "url":f"https://example.invalid/obs/{i}","synthetic":True}
                          for i in range(3200)]
            assert ctl.store.put_observations(observations)==3200
            summary["seed_ms"]=round((time.perf_counter()-started)*1000,3)
            ctl.store._lock=RecordingLock(ctl.store._lock)
            since=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
            phase=time.perf_counter()
            map_rows=ctl.store.list_events(map_evidence=True,limit=5000,since=since,keep_significant=True)
            summary["map_read_ms"]=round((time.perf_counter()-phase)*1000,3)
            expected={str(e["id"]) for e in critical_alerts(map_rows)}
            assert len(expected)==5000, len(expected)
            assert sum(len(a["geometry"]["coordinates"][0])
                       for e in map_rows for a in e.get("map_areas",[]))>=90000
            cutoff=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
            ctl.store._lock.sections.clear()
            phase=time.perf_counter()
            brief=ctl.brief_events(since=cutoff,period="daily")
            summary["brief_read_ms"]=round((time.perf_counter()-phase)*1000,3)
            summary["brief_store_lock"]=stats(ctl.store._lock.sections)
            actual={str(e["id"]) for e in critical_alerts(brief)}
            summary["canonical_red_missing"]=len(expected-actual)
            summary["canonical_red_extra"]=len(actual-expected)
            feed=ctl.events(limit=500)
            live=overview_evidence_candidates(feed,map_rows)
            summary["overview_missing"]=len(expected-{str(e["id"]) for e in critical_alerts(live)})
            summary["overview_extra"]=len({str(e["id"]) for e in critical_alerts(live)}-expected)
            if not args.baseline:
                assert actual==expected,(len(expected-actual),len(actual-expected))
                assert {str(e["id"]) for e in critical_alerts(live)}==expected
            phase=time.perf_counter()
            w=MainWindow(ctl)
            w.resize(1440,940)
            w.show()
            app.processEvents()
            summary["window_first_paint_ms"]=round((time.perf_counter()-phase)*1000,3)
            phase=time.perf_counter()
            assert w.prepare_initial_workspaces()
            summary["opening_workspace_ms"]=round((time.perf_counter()-phase)*1000,3)
            snapshot=w._daily_brief_snapshot
            index=snapshot["markdown"].split("## Critical alerts — immediate attention",1)[1].split("## At a glance",1)[0]
            summary["opening_red_lines"]=index.count("Severity: **CRITICAL**")
            summary["opening_missing_source_links"]=sum(
                e["reports"][0]["url"] not in index for e in map_rows if str(e["id"]) in expected)
            summary["opening_overview_missing"]=sum(
                ("pulse-event://open/"+str(e["id"])+"'") not in w._overview_html_cached
                for e in map_rows if str(e["id"]) in expected)
            if not args.baseline:
                assert summary["opening_red_lines"]==5000
                assert summary["opening_missing_source_links"]==0
                assert summary["opening_overview_missing"]==0
            assert len(w.world_map.area_layer.paths)>=180
            assert len(w._observations)>=3200
            w._workspace_warm_timer.stop()
            w._evidence_refresh_timer.stop()
            geometry=w.geometry()
            state=w.windowState()
            toggles=[]
            last[0]=time.perf_counter()
            timer.start()
            for enabled in (False,True,False,True):
                phase=time.perf_counter()
                w.hazard_master.setChecked(enabled)
                app.processEvents()
                w.world_map.grab()
                toggles.append((time.perf_counter()-phase)*1000)
                assert bool(w.world_map.area_layer.visible())==enabled
                assert w.geometry()==geometry and w.windowState()==state
            summary["hazard_action_paint"]=stats(toggles)
            # Force exactly one concurrent writer between source reads.
            # No mixed source revision may commit under a selected category.
            old_events=ctl.events
            gui=threading.get_ident()
            def write():
                try:
                    assert launch.wait(30)
                    new_time=datetime.now(timezone.utc).isoformat()
                    ctl.store.ingest([report(6000,new_time,severity="high",category="Health")])
                    ctl.evidence_changed.emit()
                except Exception as exc:writer_errors.append(str(exc))
                finally:written.set()
            writer=threading.Thread(target=write,daemon=True)
            writer.start()
            def contested(**kwargs):
                assert threading.get_ident()!=gui,"warmed filter SQLite on GUI"
                rows=old_events(**kwargs)
                if not launch.is_set():
                    launch.set()
                    assert written.wait(30)
                return rows
            settles=[]
            with patch.object(ctl,"events",contested):
                for category in ("Health","Disaster",""):
                    ix=w.category.findData(category)
                    assert ix>=0
                    phase=time.perf_counter()
                    w.category.setCurrentIndex(ix)
                    deadline=time.monotonic()+90
                    while w._filter_refresh_pending and time.monotonic()<deadline:
                        app.processEvents()
                        QTest.qWait(10)
                    settles.append((time.perf_counter()-phase)*1000)
                    assert not w._filter_refresh_pending,"category did not settle"
                    assert not writer_errors,writer_errors
                    assert w.geometry()==geometry and w.windowState()==state
                    if category:
                        assert all(e["category"]==category for e in w._events)
                    w._workspace_warm_timer.stop()
            timer.stop()
            summary["category_settle"]=stats(settles)
            summary["heartbeat"]=stats(gaps)
            summary["final_point_candidates"]=len(w.world_map.events)
            summary["final_warning_areas"]=len(w.world_map.area_layer.paths)
            summary["archive_events"]=ctl.store.stats()["events"]
            print("R20_MATCHED_LOAD="+json.dumps(summary,sort_keys=True),flush=True)
        finally:
            timer.stop()
            launch.set()
            if writer is not None:writer.join(timeout=35)
            if w is not None:
                w._force_close=True
                for name in ("_filter_refresh_timer","_workspace_warm_timer","_evidence_refresh_timer",
                             "_collection_refresh_timer","search_timer","_brief_clock_timer"):
                    if hasattr(w,name):getattr(w,name).stop()
                w.media.shutdown()
                w.close()
                w.deleteLater()
            ctl.close()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
if __name__=="__main__":
    main()
