"""Owner-reported stalls and spontaneous size changes: loaded offline Qt checks.

These tests exercise actual Qt and source-shaped fixtures. Hosted offscreen
timings cannot establish physical Windows compositor or live-media acceptance.
"""
import os
import time
import json
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from global_pulse import map_widget
from global_pulse.controller import Controller
from global_pulse.crisis_overlay import build_country_activity, normalize_country
from global_pulse.hazards import HAZARD_KEYS
from global_pulse.ui import MainWindow
from test_issue22_startup_idle_profile import _observations, _reports


def _delete(app, widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_loaded_hazard_toggles_reuse_source_facts_and_keep_exact_evidence():
    app=QApplication.instance() or QApplication([])
    world=map_widget.WorldMap()
    world.resize(1100,540)
    now=datetime.now(timezone.utc)
    rows=[]
    for i in range(5000):
        kind=HAZARD_KEYS[i%len(HAZARD_KEYS)]
        country="France" if i%2 else "Germany"
        rows.append({"id":f"offline-{i}","title":"Fictional hazard report",
            "category":"Disaster","country":country,"country_basis":"explicit_record",
            "latitude":40.0+(i%80)*.01,"longitude":10.0+(i%90)*.01,
            "status":"active","severity":"moderate","verification":"official",
            "reports":[{"id":f"offline-report-{i}","source_id":"fixture",
                "title":"Fictional hazard report","country":country,
                "country_basis":"explicit_record","category":"Disaster",
                "official":True,"hazard_types":[kind],"published_at":now.isoformat(),
                "evidence_status":"active"}]})
    observations=[dict(row,country="France",country_name="France") for row in _observations()]
    context=[{"id":"fixture-conflict","title":"Fictional armed conflict in Ukraine",
        "country":"Ukraine","category":"Conflict","published_at":now.isoformat(),
        "reports":[{"official":True}]}]
    countries=tuple({"name":str(c["name"]),"code":str(c.get("code") or "")} for c in world._countries)
    credits=set()
    activity=build_country_activity(context,now=now,single_record_credits=credits)
    facts=map_widget.prepare_country_source_facts(rows,observations,countries)
    prepared={
        "record_ids":tuple(id(r) for r in rows),"country_rows":countries,
        "crisis_record_ids":tuple(id(r) for r in context),
        "observation_ids":tuple(id(r) for r in observations),
        "category_key":None,"disabled_hazards":frozenset(),"activity":activity,"credits":credits,
        "source_facts":facts,"point_source_index":map_widget.prepare_point_source_index(rows,facts),
        "evidence_index":map_widget.prepare_country_evidence(rows,observations,countries,credits,None,source_facts=facts),
    }
    assert activity[normalize_country("Ukraine")]["conflict"]==1
    try:
        with (patch.object(map_widget,"prepare_country_source_facts",side_effect=AssertionError("source facts rebuilt on Qt")),
              patch.object(map_widget,"incident_country",side_effect=AssertionError("country reclassified on Qt")),
              patch.object(map_widget,"event_hazard_types",side_effect=AssertionError("hazards reparsed on Qt")),
              patch.object(map_widget,"build_country_activity",side_effect=AssertionError("crisis classification repeated on Qt"))):
            world.set_events(rows,country_events=rows,observations=observations,
                             crisis_events=context,preclassified_country=prepared)
            world.show()
            app.processEvents()
            world.grab()
            backing=world._country_backdrop_pixmap
            assert backing is not None
            assert world._coverage_points==5000
            timings=[]
            for kind in ("earthquake","cyclone","flood","wildfire"):
                for enabled in (False,True):
                    start=time.perf_counter()
                    world.set_hazard_layer(kind,enabled)
                    summary=world.coverage_summary()
                    app.processEvents()
                    world.grab()
                    timings.append((time.perf_counter()-start)*1000)
                    expected=5000 if enabled else sum(HAZARD_KEYS[i%len(HAZARD_KEYS)]!=kind for i in range(5000))
                    assert world._coverage_points==expected
                    assert summary.startswith(f"{expected} points")
                    assert sum(len(g) for g in world.visible_clusters())==expected
                    assert world.country_activity==activity
                    assert world.economic_observations[normalize_country("France")]["count"]==3200
                    assert world._country_backdrop_pixmap is backing
            world.set_hazards_enabled(False)
            assert world.coverage_summary().startswith("0 points")
            assert not world.visible_clusters()
            assert world.country_activity==activity
            print("R20_LOADED_HAZARD_ACTION_PAINT_MS="+",".join(f"{ms:.3f}" for ms in timings),flush=True)
    finally:
        _delete(app,world)


def test_loaded_window_category_and_hazard_changes_keep_geometry(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    w=None
    heartbeat=[]
    timer=QTimer()
    last=[time.perf_counter()]
    def beat():
        now=time.perf_counter()
        heartbeat.append((now-last[0])*1000)
        last[0]=now
    timer.setInterval(20)
    timer.timeout.connect(beat)
    try:
        reports=_reports(900)
        reports[0]["region"]="Long source region "+("X"*150)
        assert len(ctl.store.ingest(reports))==900
        assert ctl.store.put_observations(_observations())==3200
        w=MainWindow(ctl)
        w.show()
        app.processEvents()
        assert w.prepare_initial_workspaces()
        w._workspace_warm_timer.stop()
        w._evidence_refresh_timer.stop()
        w.showNormal()
        w.resize(1100,760)
        app.processEvents()
        geometry=w.geometry()
        state=w.windowState()
        minimum=w.minimumSize()
        assert not w.isMaximized() and not w.isFullScreen()
        long_text="Fictional coverage detail "+("long source coverage information " * 80)
        w.count_label.setText(long_text)
        w.status_label.setText(long_text)
        app.processEvents()
        assert w.count_label.text()==long_text and w.count_label.toolTip()==long_text
        assert w.geometry()==geometry and w.windowState()==state
        assert w.minimumSize()==minimum

        original=ctl.events
        import threading
        gui=threading.get_ident()
        trace=[]
        preference_busy=[0]
        revision_busy=[0]
        clock=time.perf_counter
        origin=clock()
        def record(kind, **fields):
            if len(trace)<4000:
                trace.append(dict(kind=kind, ms=round((clock()-origin)*1000,3),
                                  thread="gui" if threading.get_ident()==gui else "worker",
                                  **fields))
        def observe(snapshot):
            # Never access widgets from the signal's emitting thread.
            record("snapshot", **{key:snapshot.get(key) for key in (
                "scope","generation","selected_id","archive_pin_id",
                "explicit_selection_id","revision_before","revision_after",
                "retry_snapshot","error","explicit_filter")})
        w._idle_snapshot_ready.connect(observe)
        def guarded(**kwargs):
            assert threading.get_ident()!=gui,"category click queried SQLite on GUI"
            record("events_start", filters=kwargs)
            try:
                result=original(**kwargs)
                record("events_end", rows=len(result), filters=kwargs)
                return result
            except Exception as exc:
                record("events_error", error=type(exc).__name__+": "+str(exc)[:160])
                raise
        monkeypatch.setattr(ctl,"events",guarded)
        original_revision=ctl.store.content_revision_if_available
        def revision():
            value=original_revision()
            if value is None:
                revision_busy[0]+=1
            else:
                record("revision_probe", value=value)
            return value
        monkeypatch.setattr(ctl.store,"content_revision_if_available",revision)
        original_pref=getattr(ctl._headlines,"enabled_if_available",None)
        if original_pref is not None:
            def preference():
                value=original_pref()
                if value is None:
                    preference_busy[0]+=1
                return value
            monkeypatch.setattr(ctl._headlines,"enabled_if_available",preference)

        def capture_filter_state():
            return dict(pending=w._filter_refresh_pending,
                        inflight=w._idle_snapshot_inflight,
                        refreshing=w._refreshing, generation=w._idle_snapshot_generation,
                        scope=w._archive_scope_key(), selected=w._selected_id,
                        archive_pin=w._archive_selection_id,
                        explicit_selection=w._explicit_feed_selection_id,
                        filter_timer=w._filter_refresh_timer.isActive(),
                        filter_remaining=w._filter_refresh_timer.remainingTime(),
                        deferred=len(ctl._headlines.deferred),
                        deferred_interval=ctl._headlines.deferred_timer.interval(),
                        count=w.count_label.text()[:240], status=w.status_label.text()[:240])
        last[0]=time.perf_counter()
        timer.start()
        for category in ("Health","Disaster",""):
            index=w.category.findData(category)
            assert index>=0
            record("category_request", category=category, state=capture_filter_state())
            w.category.setCurrentIndex(index)
            limit=time.monotonic()+12
            previous=None
            while w._filter_refresh_pending and time.monotonic()<limit:
                app.processEvents()
                QTest.qWait(10)
                current=capture_filter_state()
                # Log transitions, not every 10ms wait or timer countdown.
                key=tuple(str(current[k]) for k in (
                    "pending","inflight","refreshing","generation","scope","selected",
                    "archive_pin","explicit_selection","filter_timer","count","status"))
                if key!=previous:
                    record("state", state=current)
                    previous=key
            # Always emit the terminal state separately from bounded trace storage.
            terminal=dict(kind="category_end", category=category,
                          state=capture_filter_state(),
                          heartbeat_max_ms=max(heartbeat,default=0),
                          headline_preference_busy=preference_busy[0],
                          revision_probe_busy=revision_busy[0],
                          recorded_events=len(trace))
            for entry in trace:
                print("R20_FILTER_TRACE="+json.dumps(entry,default=str),flush=True)
            print("R20_FILTER_END="+json.dumps(terminal,default=str),flush=True)
            trace.clear()
            preference_busy[0]=0
            revision_busy[0]=0
            assert not w._filter_refresh_pending
            if category:
                assert w._events and all(e["category"]==category for e in w._events)
            assert w.geometry()==geometry and w.windowState()==state
            assert not w.isMaximized() and not w.isFullScreen()
            assert w.save_button.property("event_id")==w._selected_id
            w._workspace_warm_timer.stop()
        for enabled in (False,True,False,True):
            w.hazard_master.setChecked(enabled)
            app.processEvents()
            assert w.geometry()==geometry and w.windowState()==state
        assert heartbeat
        print("R20_LOADED_CATEGORY_HEARTBEAT_MAX_MS="+f"{max(heartbeat):.3f}",flush=True)
        # These exact loaded-archive timings are diagnostic; the existing
        # independently required timing gates remain unchanged.
    finally:
        timer.stop()
        if w is not None:
            w._force_close=True
            for name in ("_filter_refresh_timer","_workspace_warm_timer","_evidence_refresh_timer",
                         "_collection_refresh_timer","search_timer"):
                getattr(w,name).stop()
            w.media.shutdown()
            w.close()
        ctl.close()
        if w is not None:
            _delete(app,w)
