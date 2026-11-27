"""Offline priority brief and daily/live snapshot lifecycle."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog
from global_pulse.brief_selection import overview_evidence_candidates,overview_html,critical_alerts
from global_pulse.core import build_brief
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from test_r20_daily_brief_depth import item


def test_critical_index_all_active_red_and_priority_order_with_source_links():
    now="2026-11-20T14:00:00Z"
    red=[item(n,"Weather",severity="critical") for n in range(20)]
    high=item(50,"Government",severity="high",title="Fictional HIGH assessment")
    moderate=item(51,"Health",severity="moderate",title="Fictional MODERATE assessment")
    unassessed=item(52,"Conflict",title="Fictional UNRATED assessment")
    withdrawn=item(53,"News",severity="critical",status="retracted",title="Fictional withdrawn record")
    future=item(54,"News",severity="critical",future_dated=True,title="Fictional future record")
    old=item(55,"Disaster",severity="critical",updated_at="2026-11-18T13:00:00Z",
             title="Fictional retained critical alert")
    events=[unassessed,moderate,high,withdrawn,future,*red,old]
    chosen=overview_evidence_candidates(events,events)
    assert len(critical_alerts(chosen))==21
    page=overview_html(chosen)
    for event in red+[old]:
        assert "pulse-event://open/"+event["id"]+"'" in page
    assert page.index("Critical alerts — immediate attention")<page.index("Fictional HIGH assessment")
    assert page.index("Fictional HIGH assessment")<page.index("Fictional MODERATE assessment")<page.index("Fictional UNRATED assessment")
    index=page.split("High priority",1)[0]
    assert "Fictional withdrawn record" not in index and "Fictional future record" not in index
    brief=build_brief(events,generated_at=now)
    index=brief.split("## Critical alerts — immediate attention",1)[1].split("## At a glance",1)[0]
    assert index.count("Severity: **CRITICAL**")==21
    assert "retained from before reporting window" in index
    assert "Fictional withdrawn record" not in index and "Fictional future record" not in index
    assert "https://example.org/report/0" in index
    assert brief.index("Fictional HIGH assessment")<brief.index("Fictional MODERATE assessment")<brief.index("Fictional UNRATED assessment")


def _report(n,severity="unassessed",category="News",age_hours=0):
    stamp=(datetime.now(timezone.utc)-timedelta(hours=age_hours,minutes=1)).isoformat()
    return {"id":f"executive-{n}","event_key":f"executive:{n}",
            "title":f"FICTIONAL executive report {n}","summary":"Offline synthetic source record",
            "source_id":"executive-fixture","publisher":"Fictional publisher",
            "url":f"https://example.invalid/executive/{n}","published_at":stamp,
            "retrieved_at":stamp,"category":category,"region":"Global","country":"",
            "severity":severity,"synthetic":True,"kind":"report"}


def test_store_red_priority_exceeds_detail_cap_and_includes_retained_alerts(tmp_path):
    ctl=Controller(tmp_path,demo=True)
    try:
        ctl.store.ingest([_report(n,"critical","Disaster",age_hours=48 if n==0 else 0)
                          for n in range(18)])
        ctl.store.ingest([_report(99,"moderate","Health")])
        since=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        records=ctl.brief_events(since=since,period="daily")
        red=critical_alerts(records)
        assert len(red)==18
        assert any("executive report 0"==row["title"].removeprefix("FICTIONAL ") for row in red)
        assert any(row["category"]=="Health" for row in records)
        assert len({row["id"] for row in records})==len(records)
    finally:
        ctl.close()


def _pump(app,predicate,timeout=15):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        app.processEvents()
        if predicate():return True
        QTest.qWait(20)
    return False


def test_daily_opening_and_live_overview_diverge_only_on_new_source(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    w=None
    try:
        ctl.store.ingest([_report(1,"critical","Disaster"),_report(2,"high","Health")])
        w=MainWindow(ctl)
        assert w.prepare_initial_workspaces()
        daily=w._daily_brief_snapshot
        assert daily and "FICTIONAL executive report 1" in daily["markdown"]
        assert "FICTIONAL executive report 1" in w._overview_html_cached
        assert "FICTIONAL executive report 2" in daily["markdown"]
        assert "FICTIONAL executive report 2" in w._overview_html_cached
        assert "opening Daily Brief snapshot" in w._overview_html_cached
        first_text=w.brief_browser.toPlainText()
        ctl.store.ingest([_report(3,"critical","Government")])
        original=ctl.brief_events
        with patch.object(ctl,"brief_events",side_effect=AssertionError("same-day daily re-read")):
            w._last_navigation_at=time.monotonic()-10
            w._start_idle_snapshot()
            assert _pump(app,lambda: not w._idle_snapshot_inflight and
                         "FICTIONAL executive report 3" in w._overview_html_cached)
            assert not w._idle_brief_inflight
            assert w._generate_brief(idle=True)
            assert w._daily_brief_snapshot is daily
            assert w.brief_browser.toPlainText()==first_text
            target=tmp_path/"daily.md"
            monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *a,**k:(str(target),"Markdown"))
            w._export_brief()
            assert target.read_text(encoding="utf-8").endswith(daily["markdown"])
            assert "FICTIONAL executive report 3" not in target.read_text(encoding="utf-8")
        # A deliberate Generate request is the only same-day replacement.
        assert w._generate_brief()
        assert w._daily_brief_snapshot is not daily
        assert "FICTIONAL executive report 3" in w._daily_brief_snapshot["markdown"]
        # On UTC rollover the same exact-revision worker prepares a new daily.
        w._daily_brief_snapshot=dict(w._daily_brief_snapshot,day="1900-01-01")
        w._last_navigation_at=time.monotonic()-10
        w._start_idle_snapshot()
        assert _pump(app,lambda:not w._idle_snapshot_inflight and w._deferred_brief_events is not None)
        assert w._generate_brief(idle=True)
        assert w._has_current_daily_brief("daily")
    finally:
        if w is not None:
            w._force_close=True
            for name in ("_filter_refresh_timer","_workspace_warm_timer","_evidence_refresh_timer","_collection_refresh_timer","search_timer"):
                getattr(w,name).stop()
            w.media.shutdown()
            w.close()
            w.deleteLater()
        ctl.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
