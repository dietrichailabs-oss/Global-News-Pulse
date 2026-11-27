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
import stat
import tempfile
import threading
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from contextlib import ExitStack
from functools import wraps
from collections import defaultdict
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QCoreApplication,QEvent,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog,QPushButton
from global_pulse.brief_selection import critical_alerts,overview_evidence_candidates,overview_html
from global_pulse.controller import Controller
from global_pulse.hazards import HAZARD_KEYS
from global_pulse.ui import MainWindow

class RecordingLock:
    def __init__(self,lock,profiler=None):
        self.backing=lock
        self.profiler=profiler
        self.owners={}
        self.sections=[]
        self.waits=defaultdict(list)
        self.holds=defaultdict(list)
    def acquire(self,blocking=True,timeout=-1):
        who=threading.get_ident()
        outer=who not in self.owners
        start=time.perf_counter()
        ok=self.backing.acquire(blocking,timeout)
        if outer and self.profiler is not None:
            key=(self.profiler.stage+("/gui" if who==self.profiler.gui else "/worker")
                 +("/acquired" if ok else "/busy"))
            self.waits[key].append((time.perf_counter()-start)*1000)
        if ok:
            who=threading.get_ident()
            start,depth=self.owners.get(who,(time.perf_counter(),0))
            self.owners[who]=(start,depth+1)
        return ok
    def release(self):
        who=threading.get_ident()
        start,depth=self.owners[who]
        if depth==1:
            elapsed=(time.perf_counter()-start)*1000
            self.sections.append(elapsed)
            if self.profiler is not None:
                key=self.profiler.stage+("/gui" if who==self.profiler.gui else "/worker")
                self.holds[key].append(elapsed)
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

def path_facts(path):
    raw=Path(path)
    info={"original":str(raw),"absolute":str(raw.absolute()),"resolved":str(raw.resolve())}
    try:
        meta=raw.lstat()
        info.update(mode=stat.filemode(meta.st_mode),attributes=getattr(meta,"st_file_attributes",0),
                    links=meta.st_nlink,symlink=stat.S_ISLNK(meta.st_mode))
    except FileNotFoundError:
        info["exists"]=False
    return info


def private_fixture_root():
    # Do not change the application's archive admission policy. The hosted
    # runner may spell its default temp directory via a redirected/8.3 path.
    # Select a private child of the canonical runner-owned temp directory.
    supplied=Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    root=supplied.resolve(strict=True)
    meta=root.lstat()
    print("R20_TEMP_ROOT="+json.dumps({"default":path_facts(tempfile.gettempdir()),
        "runner":path_facts(supplied),"canonical":path_facts(root)},sort_keys=True),flush=True)
    assert root.is_absolute() and root.resolve(strict=True)==root
    assert stat.S_ISDIR(meta.st_mode) and not stat.S_ISLNK(meta.st_mode)
    assert not getattr(meta,"st_file_attributes",0)&0x400
    return root


class PhaseRecorder:
    """Non-substitutive call timing, same instrumentation on both exact builds.

    Spans are nested, not additive. Identify actual main-thread operations
    overlapping the longest heartbeat intervals, and separately report
    worker source preparation and Store lock ownership.
    """
    def __init__(self):
        self.stage="setup"
        self.gui=threading.get_ident()
        self.spans=[]
        self.sleeps=defaultdict(list)
        self.stack=ExitStack()

    def wrap(self,obj,name,prefix):
        original=getattr(obj,name,None)
        if not callable(original):return
        label=prefix+"."+name
        recorder=self
        @wraps(original)
        def timed(*args,**kwargs):
            stage=recorder.stage
            who="gui" if threading.get_ident()==recorder.gui else "worker"
            begin=time.perf_counter()
            cpu=time.thread_time()
            try:return original(*args,**kwargs)
            finally:
                recorder.spans.append((stage,who,label,begin,time.perf_counter(),
                                       (time.thread_time()-cpu)*1000))
        # Preserve descriptor binding when timing static Store helpers.
        descriptor=vars(obj).get(name) if isinstance(obj,type) else None
        replacement=staticmethod(timed) if isinstance(descriptor,staticmethod) else timed
        self.stack.enter_context(patch.object(obj,name,replacement))

    def __enter__(self):
        import global_pulse.core as core
        import global_pulse.brief_selection as selection
        import global_pulse.brief_rendering as rendering
        from global_pulse.map_widget import WorldMap
        from global_pulse.map_area_layer import WarningAreaLayer
        from global_pulse.headline_translation import HeadlineTranslations
        from global_pulse.translation import Translator
        from PySide6.QtWidgets import QTextBrowser
        # Observe actual sleep delays on both builds, including the older
        # fixed 1ms/page path, without changing its requested duration.
        original_sleep=time.sleep
        recorder=self
        def timed_sleep(seconds):
            stage=recorder.stage
            who="gui" if threading.get_ident()==recorder.gui else "worker"
            started=time.perf_counter()
            try:return original_sleep(seconds)
            finally:
                if stage=="brief_read" or stage.startswith("category_"):
                    recorder.sleeps[(stage,who,float(seconds)*1000)].append(
                        (time.perf_counter()-started)*1000)
        self.stack.enter_context(patch.object(time,"sleep",timed_sleep))
        targets=(
            (core.Store,"Store",("list_events","_map_evidence_page_unlocked",
                "_cooperative_map_projection","_cooperative_map_candidates",
                "_cooperative_map_page","_cooperative_map_yield",
                "list_brief_events","list_observations","brief_manifest_matches","ingest")),
            (MainWindow,"MainWindow",("refresh_data","_populate_feed","_sync_map_controls",
                "_populate_filter_options","_update_world_overview","_render_idle_selection",
                "_render_event","_refresh_translated_headlines","_populate_economy",
                "_warm_next_workspace","_generate_brief","_validate_brief_snapshots",
                "_queue_filter_refresh","_start_filter_refresh","_retry_pending_filter",
                "_start_idle_snapshot","_apply_idle_snapshot","_show_overview_page",
                "_request_brief","_start_requested_brief","_apply_requested_brief",
                "_begin_idle_brief_read","_apply_idle_brief","_export_brief")),
            (WorldMap,"WorldMap",("set_events","_refresh_country_activity",
                "_visible_cluster_paint_specs","visible_clusters","_paint_country_backdrop",
                "_mapped_country_paths","_visible_country_badge_specs","paintEvent")),
            (WarningAreaLayer,"WarningAreaLayer",("set_events","paint","visible")),
            (QTextBrowser,"QTextBrowser",("setHtml","setPlainText")),
            (HeadlineTranslations,"HeadlineTranslations",("_drain_deferred","view","_headline_language")),
            (Translator,"Translator",("installed",)),
            (Controller,"Controller",("_headline_preference_if_available",)),
            (selection,"selection",("overview_evidence_candidates","overview_html","overview_documents")),
            (core,"core",("build_brief",)),
            (rendering,"rendering",("brief_html",)),
        )
        for obj,prefix,names in targets:
            for name in names:self.wrap(obj,name,prefix)
        return self

    def __exit__(self,*args):
        return self.stack.__exit__(*args)

    def report(self,heartbeat):
        by_phase=defaultdict(list)
        cpu=defaultdict(list)
        for stage,who,label,start,end,elapsed_cpu in self.spans:
            key=stage+"/"+who+"/"+label
            by_phase[key].append((end-start)*1000)
            cpu[key].append(elapsed_cpu)
        rows={key:dict(stats(values),total_ms=round(sum(values),3),
                       cpu_total_ms=round(sum(cpu[key]),3))
              for key,values in sorted(by_phase.items())}
        longest=[]
        for start,end,stage in sorted(heartbeat,key=lambda gap:gap[1]-gap[0],reverse=True)[:8]:
            overlaps=[]
            for phase,who,label,a,b,elapsed_cpu in self.spans:
                overlap=max(0,min(end,b)-max(start,a))*1000
                if overlap>=5:
                    overlaps.append({"thread":who,"operation":label,"stage":phase,
                                     "overlap_ms":round(overlap,3),
                                     "call_ms":round((b-a)*1000,3),
                                     "cpu_ms":round(elapsed_cpu,3)})
            overlaps.sort(key=lambda row:row["overlap_ms"],reverse=True)
            longest.append({"stage":stage,"gap_ms":round((end-start)*1000,3),
                            "gui": [row for row in overlaps if row["thread"]=="gui"][:8],
                            "worker":[row for row in overlaps if row["thread"]=="worker"][:5]})
        return {"spans":rows,"longest_heartbeat_intervals":longest,
                "sleep_observations":[dict(stage=stage,thread=who,requested_ms=requested,
                    observed=stats(values),total_ms=round(sum(values),3))
                    for (stage,who,requested),values in sorted(self.sleeps.items())]}


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

def exercise_generate(app,w,ctl,profiler,expected,map_rows,stamp,root):
    """Click the actual button, with a real competing synthetic archive writer.

    One application-owned event loop drives both periods. Force a correction
    AFTER the first coherent requested read returns, then allow the actual
    application to retry. Unrelated status and source writes continue until
    the requested document reaches its terminal state. No product mock data,
    fake manifest, disabled collector UI, timeout extension or live provider.
    """
    original=ctl.brief_events
    gui=threading.get_ident()
    button=next(b for b in w.findChildren(QPushButton) if b.text()=="Generate brief")
    periods=iter(("daily","weekly"))
    current={}
    phases=[]
    failures=[]
    writers=[]
    stop_all=threading.Event()
    phase_lock=threading.Lock()
    active=set()
    poll=QTimer()
    poll.setInterval(20)

    def read(**kwargs):
        name=threading.current_thread().name
        requested=name=="pulse-requested-brief"
        with phase_lock:
            assert not active,"overlapping Brief source reads"
            active.add(name)
        try:
            if requested:
                assert threading.get_ident()!=gui
            rows=original(**kwargs)
            phase=current
            if requested:
                assert kwargs["period"]==phase["period"]
                phase["reads"]+=1
                if phase["reads"]==1:
                    # Pick an actually admitted critical record without a
                    # polygon; retained identity/revision must be checked.
                    selected=next(e for e in critical_alerts(rows)
                                  if e["title"].startswith("FICTIONAL loaded archive report ")
                                  and 200<=int(e["title"].split()[-1])<5005)
                    phase["correction"]=(str(selected["id"]),
                                         int(selected["title"].split()[-1]),
                                         selected["revision"])
                    phase["correct"].set()
                    assert phase["corrected"].wait(15),"fixture correction did not finish"
                    assert not phase["errors"],phase["errors"]
            return rows
        finally:
            with phase_lock:
                active.discard(name)

    def writer(phase):
        try:
            while not phase["stop"].is_set() and not stop_all.is_set():
                if phase["correct"].is_set() and not phase["corrected"].is_set():
                    identity,index,revision=phase["correction"]
                    title=f"FICTIONAL corrected {phase['period']} archive report {index}"
                    now=datetime.now(timezone.utc).isoformat()
                    replacement=dict(report(index,stamp),title=title,
                                     summary="Offline corrected source record",retrieved_at=now)
                    ctl.store.ingest([replacement],now=now)
                    updated=ctl.store.get_event(identity)
                    assert updated and updated["revision"]!=revision
                    assert updated["title"]==title
                    phase["corrected_title"]=title
                    phase["corrected_revision"]=updated["revision"]
                    phase["corrected"].set()
                    ctl.evidence_changed.emit()
                number=phase["writes"]
                ctl.store.set_setting("offline-brief-load-probe",number)
                phase["writes"]+=1
                if number%4==0:
                    index=(7000 if phase["period"]=="daily" else 8000)+number
                    now=datetime.now(timezone.utc).isoformat()
                    ctl.store.ingest([report(index,now,severity="high",category="Health")],now=now)
                    assert not ctl.store.last_ingest_errors
                    phase["ingests"]+=1
                    ctl.evidence_changed.emit()
                phase["stop"].wait(.20)
        except Exception as exc:
            phase["errors"].append(type(exc).__name__+": "+str(exc))
            phase["corrected"].set()
        finally:
            phase["done"].set()

    def fail(exc):
        failures.append(exc)
        poll.stop()
        stop_all.set()
        if current:
            current["stop"].set()
        app.exit(1)

    def start_next():
        nonlocal current
        try:
            period=next(periods)
        except StopIteration:
            poll.stop()
            app.exit(0)
            return
        try:
            current={"period":period,"reads":0,"writes":0,"ingests":0,
                     "errors":[],"stop":threading.Event(),"done":threading.Event(),
                     "correct":threading.Event(),"corrected":threading.Event()}
            profiler.stage="requested_"+period
            w.brief_period.setCurrentIndex(0 if period=="daily" else 1)
            w.open_page(5)
            thread=threading.Thread(target=writer,args=(current,),name="offline-brief-collector")
            writers.append(thread)
            current["started"]=time.perf_counter()
            thread.start()
            phase=time.perf_counter()
            button.click()
            current["click_ms"]=(time.perf_counter()-phase)*1000
            assert w._requested_brief_target is not None
            poll.start()
        except Exception as exc:
            fail(exc)

    def check():
        try:
            phase=current
            elapsed=(time.perf_counter()-phase["started"])*1000
            assert not phase["errors"],phase["errors"]
            assert elapsed<60000,"explicit Generate harness deadline"
            if w._requested_brief_target is not None or w._requested_brief_job is not None:
                return
            snapshot=w._displayed_brief_snapshot
            if "terminal_ms" not in phase:
                phase["terminal_ms"]=elapsed
                phase["stop"].set()
                print("R20_GENERATE_TERMINAL="+json.dumps({
                    "period":phase["period"],"elapsed_ms":elapsed,
                    "click_ms":phase["click_ms"],"reads":phase["reads"],
                    "writes":phase["writes"],"ingests":phase["ingests"],
                    "status":w.brief_state_label.text()[:300],
                    "ready":snapshot is not None},sort_keys=True),flush=True)
            assert snapshot is not None,"Generate did not publish a verified brief"
            assert snapshot["key"][0]==phase["period"]
            if not phase["done"].is_set() or w._idle_snapshot_inflight or w._idle_brief_worker_active:
                return
            valid=ctl.store.brief_manifest_matches(snapshot["manifest"],nonblocking=True)
            if valid is None:
                return
            assert valid is True
            assert phase["reads"]>=2 and phase["reads"]<=3
            assert phase["writes"]>=1 and phase["ingests"]>=1
            identity,_,_=phase["correction"]
            manifest=dict(snapshot["manifest"])
            assert expected<=set(manifest)
            assert manifest[identity]==phase["corrected_revision"]
            index=snapshot["markdown"].split("## Critical alerts — immediate attention",1)[1].split("## At a glance",1)[0]
            assert index.count("Severity: **CRITICAL**")==5000
            assert all(e["reports"][0]["url"] in index for e in map_rows if str(e["id"]) in expected)
            assert phase["corrected_title"] in snapshot["markdown"]
            assert phase["corrected_title"] in w.brief_browser.toPlainText()
            # Export must bind to the exact visible bytes, not re-read a new brief.
            target=root/("generated-"+phase["period"]+".md")
            with patch.object(QFileDialog,"getSaveFileName",return_value=(str(target),"Markdown")):
                w._export_brief()
            if not target.exists():
                # A collector snapshot may have acquired the lock after the
                # probe; preserve the existing safe refusal and retry only
                # after another observation of the same valid document.
                return
            assert target.read_text(encoding="utf-8").endswith(snapshot["markdown"])
            phases.append({key:phase[key] for key in
                           ("period","reads","writes","ingests","click_ms","terminal_ms")})
            print("R20_GENERATE_VERIFIED="+json.dumps(phases[-1],sort_keys=True),flush=True)
            poll.stop()
            QTimer.singleShot(0,start_next)
        except Exception as exc:
            fail(exc)

    poll.timeout.connect(check)
    try:
        with patch.object(ctl,"brief_events",read):
            QTimer.singleShot(0,start_next)
            result=app.exec()
        if failures:
            raise failures[0]
        assert result==0 and len(phases)==2
        return phases
    finally:
        stop_all.set()
        poll.stop()
        if current:
            current["stop"].set()
        for thread in writers:
            thread.join(timeout=20)
            assert not thread.is_alive(),"synthetic writer did not drain"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",action="store_true")
    args=parser.parse_args()
    app=QApplication.instance() or QApplication([])
    summary={"baseline":args.baseline,"trial":os.environ.get("R20_MATCHED_TRIAL","1")}
    started=time.perf_counter()
    runner_root=private_fixture_root()
    with tempfile.TemporaryDirectory(prefix="gp-r20-load-",dir=runner_root) as directory, PhaseRecorder() as profiler:
        original=Path(directory)
        canonical=original.resolve(strict=True)
        meta=canonical.lstat()
        print("R20_FIXTURE_PATH="+json.dumps(path_facts(original),sort_keys=True),flush=True)
        assert canonical.parent==runner_root and stat.S_ISDIR(meta.st_mode)
        assert not stat.S_ISLNK(meta.st_mode) and not getattr(meta,"st_file_attributes",0)&0x400
        ctl=Controller(canonical,demo=True)
        w=None
        timer=QTimer()
        gaps=[]
        heartbeat=[]
        last=[time.perf_counter()]
        def beat():
            now=time.perf_counter()
            gaps.append((now-last[0])*1000)
            heartbeat.append((last[0],now,profiler.stage))
            last[0]=now
        timer.setInterval(20)
        timer.timeout.connect(beat)
        writer=None
        launch=threading.Event()
        written=threading.Event()
        writer_errors=[]
        try:
            from global_pulse.archive_storage import footprint
            db=ctl.store.path
            print("R20_FIXTURE_DATABASE="+json.dumps(
                {suffix or "database":path_facts(Path(str(db)+suffix))
                 for suffix in ("","-wal","-shm","-journal")},sort_keys=True),flush=True)
            assert Path(db).parent==canonical
            footprint(db)
            profiler.stage="seed"
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
            # Real bundled geography names, synthetic measurements only.
            # 20 map countries x 2 indicators x 80 historical annual dates.
            countries=("France","Germany","Italy","Spain","Portugal","United Kingdom",
                       "Belgium","Netherlands","Poland","Austria","Switzerland","Sweden",
                       "Norway","Finland","Denmark","Greece","Canada","Mexico","Brazil","Argentina")
            observations=[{"indicator":f"fixture_{(i//20)%2}","indicator_name":"Synthetic measurement",
                           "country":countries[i%20],"date":str(1930+i//40),
                           "value":float(i%100),"source_id":"offline-measurement",
                           "url":f"https://example.invalid/obs/{i}","synthetic":True}
                          for i in range(3200)]
            assert ctl.store.put_observations(observations)==3200
            summary["seed_ms"]=round((time.perf_counter()-started)*1000,3)
            ctl.store._lock=RecordingLock(ctl.store._lock,profiler)
            since=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
            profiler.stage="map_read"
            phase=time.perf_counter()
            map_rows=ctl.store.list_events(map_evidence=True,limit=5000,since=since,keep_significant=True)
            summary["map_read_ms"]=round((time.perf_counter()-phase)*1000,3)
            expected={str(e["id"]) for e in critical_alerts(map_rows)}
            assert len(expected)==5000, len(expected)
            assert sum(len(a["geometry"]["coordinates"][0])
                       for e in map_rows for a in e.get("map_areas",[]))>=90000
            cutoff=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
            ctl.store._lock.sections.clear()
            profiler.stage="brief_read"
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
            profiler.stage="first_paint"
            phase=time.perf_counter()
            w=MainWindow(ctl)
            w.resize(1440,940)
            w.show()
            app.processEvents()
            summary["window_first_paint_ms"]=round((time.perf_counter()-phase)*1000,3)
            profiler.stage="opening_workspaces"
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
            if hasattr(w,"_overview_pages"):
                page_ids=tuple(identity for _,identities,_ in w._overview_pages for identity in identities)
                assert len(page_ids)==5000 and set(page_ids)==expected
                assert max(len(ids) for _,ids,_ in w._overview_pages)<=100
                assert w._overview_page_index==0
                summary["opening_overview_pages"]=len(w._overview_pages)
                summary["opening_visible_overview_bytes"]=len(w._overview_visible_html.encode("utf-8"))
                summary["opening_full_overview_bytes"]=len(w._overview_html_cached.encode("utf-8"))
                w._show_overview_page(len(w._overview_pages)-2)
                assert w._overview_pages[w._overview_page_index][1][-1]==page_ids[-1]
                w._show_overview_page(0)
            assert len(w.world_map.area_layer.paths)>=180
            assert len(w._observations)>=3200
            economic=w.world_map.economic_observations
            assert len(economic)==20,len(economic)
            assert sum(entry["count"] for entry in economic.values())==3200
            summary["map_economy_countries"]=len(economic)
            w._workspace_warm_timer.stop()
            w._evidence_refresh_timer.stop()
            geometry=w.geometry()
            state=w.windowState()
            toggles=[]
            profiler.stage="hazard_toggle"
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
                    profiler.stage="category_"+(category or "All")
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
            summary["category_settle"]=stats(settles)
            # The original Monitor workload remains unchanged. Measure the
            # actual Generate path separately, with its own heartbeat slice.
            generate_start=len(gaps)
            summary["requested_briefs"]=exercise_generate(
                app,w,ctl,profiler,expected,map_rows,recent,canonical)
            summary["requested_heartbeat"]=stats(gaps[generate_start:])
            timer.stop()
            summary["heartbeat"]=stats(gaps)
            summary["final_point_candidates"]=len(w.world_map.events)
            summary["final_warning_areas"]=len(w.world_map.area_layer.paths)
            summary["archive_events"]=ctl.store.stats()["events"]
            print("R20_MATCHED_LOAD="+json.dumps(summary,sort_keys=True),flush=True)
        finally:
            profile=profiler.report(heartbeat)
            lock=ctl.store._lock
            if isinstance(lock,RecordingLock):
                profile["lock_waits"]={key:dict(stats(values),total_ms=round(sum(values),3))
                                       for key,values in sorted(lock.waits.items())}
                profile["lock_holds"]={key:dict(stats(values),total_ms=round(sum(values),3))
                                       for key,values in sorted(lock.holds.items())}
            print("R20_PHASE_PROFILE="+json.dumps(profile,sort_keys=True),flush=True)
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
