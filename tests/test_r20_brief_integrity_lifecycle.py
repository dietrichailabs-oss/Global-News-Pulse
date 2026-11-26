"""Exact retained-source manifest, same-day snapshot and rollover/export checks."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import time
import threading

import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QFileDialog
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from test_r20_executive_brief_snapshot import _report,_pump


@pytest.fixture
def desktop(tmp_path):
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    w=None
    try:
        ctl.store.ingest([_report(1,"critical","Disaster"),_report(2,"high","Health")])
        w=MainWindow(ctl)
        assert w.prepare_initial_workspaces()
        w._workspace_warm_timer.stop()
        w._evidence_refresh_timer.stop()
        assert w._daily_brief_snapshot["manifest"]
        yield app,ctl,w
    finally:
        if w is not None:
            w._force_close=True
            for name in ("_filter_refresh_timer","_workspace_warm_timer","_evidence_refresh_timer",
                         "_collection_refresh_timer","search_timer","_brief_clock_timer"):
                getattr(w,name).stop()
            w.media.shutdown()
            w.close()
            w.deleteLater()
        ctl.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_unrelated_ingest_does_not_replace_snapshot_but_withdrawal_invalidates(desktop):
    app,ctl,w=desktop
    opening=w._daily_brief_snapshot
    ctl.store.ingest([_report(3,"high","Government")])
    assert ctl.store.brief_manifest_matches(opening["manifest"])
    w._validate_brief_snapshots()
    assert w._daily_brief_snapshot is opening
    original=_report(1,"critical","Disaster")
    original.update(status="retracted",kind="retraction",
                    title="FICTIONAL withdrawn executive record 1")
    ctl.store.ingest([original])
    assert not ctl.store.brief_manifest_matches(opening["manifest"])
    w._validate_brief_snapshots()
    assert w._daily_brief_snapshot is None
    assert w._displayed_brief_snapshot is None
    assert not w.brief_export_button.isEnabled()
    assert "FICTIONAL executive report 1" not in w.brief_browser.toPlainText()
    assert w._generate_brief()
    replacement=w._daily_brief_snapshot
    assert replacement is not opening
    critical=replacement["markdown"].split("## Critical alerts — immediate attention",1)[1].split("## At a glance",1)[0]
    assert "FICTIONAL executive report 1" not in critical


def test_real_retention_removal_clears_source_derived_brief_and_blocks_export(desktop,tmp_path,monkeypatch):
    app,ctl,w=desktop
    opening=w._daily_brief_snapshot
    result=ctl.store.prune(1,now=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat())
    assert result["reports"]==2
    assert not ctl.store.brief_manifest_matches(opening["manifest"])
    w._brief_reports_pruned()
    assert w._daily_brief_snapshot is None and w._displayed_brief_snapshot is None
    assert not w.brief_export_button.isEnabled()
    assert "FICTIONAL executive report" not in w.brief_browser.toPlainText()
    with patch.object(QFileDialog,"getSaveFileName",side_effect=AssertionError("invalid brief export dialog")):
        w._export_brief()


def test_period_switch_and_export_modal_reject_changed_evidence(desktop,tmp_path,monkeypatch):
    app,ctl,w=desktop
    old=w._daily_brief_snapshot
    w.brief_period.setCurrentIndex(1)
    assert w._displayed_brief_snapshot is None
    assert not w.brief_export_button.isEnabled()
    with patch.object(QFileDialog,"getSaveFileName",side_effect=AssertionError("wrong period export dialog")):
        w._export_brief()
    assert w._generate_brief()
    assert w._displayed_brief_key[0]=="weekly"
    assert w.brief_export_button.isEnabled()
    w.brief_period.setCurrentIndex(0)
    assert w._generate_brief(idle=True)
    assert w._daily_brief_snapshot is old
    target=tmp_path/"must-not-export.md"
    def modal(*a,**k):
        ctl.store.ingest([dict(_report(2,"high","Health"),
                               title="FICTIONAL corrected record two")])
        return str(target),"Markdown"
    monkeypatch.setattr(QFileDialog,"getSaveFileName",modal)
    w._export_brief()
    assert not target.exists()
    assert w._daily_brief_snapshot is None
    assert not w.brief_export_button.isEnabled()


def test_utc_rollover_without_collection_rejects_prior_day_worker_and_export(desktop,monkeypatch):
    app,ctl,w=desktop
    from global_pulse import ui
    yesterday=w._daily_brief_snapshot
    original_now=datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            value=original_now+timedelta(days=1)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(ui,"datetime",Clock)
    before=ctl.store.content_revision()
    old_epoch=w._brief_request_epoch
    w._brief_clock_tick()
    assert w._daily_brief_snapshot is None
    assert w._displayed_brief_snapshot is None
    assert not w.brief_export_button.isEnabled()
    assert w._evidence_refresh_timer.isActive()
    assert w._brief_request_epoch>old_epoch
    prior={"generation":w._idle_snapshot_generation,"epoch":old_epoch,
           "period":"daily","generated":original_now,
           "revision_before":before,"revision_after":before,"events":[]}
    w._idle_brief_inflight=True
    w._apply_idle_brief(prior)
    assert w._deferred_brief_events is None
    w._idle_brief_inflight=True
    w._apply_idle_brief(dict(prior,error="Offline fixture simulated failed rollover read"))
    assert not w.brief_export_button.isEnabled()
    assert w._displayed_brief_snapshot is None
    # The normal worker path must use the same captured time for the query
    # cutoff and generated document, without relying on a new collector write.
    w._last_navigation_at=time.monotonic()-10
    w._evidence_refresh_timer.stop()
    w._start_idle_snapshot()
    assert _pump(app,lambda:not w._idle_snapshot_inflight and w._deferred_brief_events is not None)
    captured=w._deferred_brief_generated
    assert captured.date()==Clock.now(timezone.utc).date()
    assert w._generate_brief(idle=True)
    assert w._daily_brief_snapshot["key"]==("daily",captured.isoformat())
    assert w._daily_brief_snapshot["day"]!=yesterday["day"]
