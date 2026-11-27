"""Owner regression: first collection after empty opening and direct Generate."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from test_r20_executive_brief_snapshot import _report


def wait_until(predicate, timeout=12):
    loop=QEventLoop()
    timer=QTimer()
    timer.setInterval(10)
    deadline=time.monotonic()+timeout
    def check():
        if predicate() or time.monotonic()>=deadline:
            loop.quit()
    timer.timeout.connect(check)
    timer.start()
    try:
        if not predicate():
            loop.exec()
    finally:
        timer.stop()
    return bool(predicate())


@pytest.fixture
def desktop(tmp_path):
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    w=None
    try:
        w=MainWindow(ctl)
        assert w.prepare_initial_workspaces()
        w._workspace_warm_timer.stop()
        w._evidence_refresh_timer.stop()
        w._brief_clock_timer.stop()
        assert w._daily_brief_snapshot is not None
        assert not w._daily_brief_snapshot["manifest"]
        yield app,ctl,w
    finally:
        if w is not None:
            w._force_close=True
            for name in ("_filter_refresh_timer","_workspace_warm_timer",
                         "_evidence_refresh_timer","_collection_refresh_timer",
                         "search_timer","_brief_clock_timer"):
                getattr(w,name).stop()
            w.media.shutdown()
            w.close()
        ctl.close()
        if w is not None:
            w.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_empty_opening_is_replaced_after_first_eligible_collection(desktop):
    app,ctl,w=desktop
    old=w._daily_brief_snapshot
    ctl.store.ingest([_report(1,"critical","Disaster"),_report(2,"high","Health")])
    w._last_navigation_at=time.monotonic()-10
    w._start_idle_snapshot()
    assert wait_until(lambda:not w._idle_snapshot_inflight
                     and w._deferred_brief_events is not None)
    assert w._generate_brief(idle=True)
    assert w._daily_brief_snapshot is not old
    assert w._daily_brief_snapshot["manifest"]
    assert "FICTIONAL executive report 1" in w.brief_browser.toPlainText()
    assert w.brief_export_button.isEnabled()


def test_generate_bypasses_monitor_and_accepts_unrelated_write(desktop,monkeypatch):
    app,ctl,w=desktop
    ctl.store.ingest([_report(i,"high","Health") for i in range(1,101)])
    gui=threading.get_ident()
    original=ctl.brief_events
    reads=[]
    def read(**kwargs):
        assert threading.get_ident()!=gui
        rows=original(**kwargs)
        reads.append(len(rows))
        # Status/settings writes must not starve the dated source manifest.
        ctl.store.set_setting("brief-offline-fixture-counter",len(reads))
        return rows
    monkeypatch.setattr(ctl,"brief_events",read)
    with patch.object(w,"_start_idle_snapshot",side_effect=AssertionError("Monitor dependency")), \
         patch.object(w,"_schedule_evidence_refresh",side_effect=AssertionError("Monitor dependency")):
        w._request_brief()
        w._request_brief()
        assert wait_until(lambda:w._requested_brief_job is None
                         and w._displayed_brief_snapshot is not None)
    assert len(reads)==1 and reads[0]>0
    assert w._daily_brief_snapshot["manifest"]
    assert w.brief_export_button.isEnabled()


def test_generate_retries_changed_manifest_and_never_publishes_old_title(desktop,monkeypatch):
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"critical","Disaster")])
    original=ctl.brief_events
    calls=[]
    def read(**kwargs):
        rows=original(**kwargs)
        calls.append(1)
        if len(calls)==1:
            ctl.store.ingest([dict(_report(1,"critical","Disaster"),
                                   title="FICTIONAL corrected brief source")])
        return rows
    monkeypatch.setattr(ctl,"brief_events",read)
    w._request_brief()
    assert wait_until(lambda:w._requested_brief_job is None
                     and w._displayed_brief_snapshot is not None)
    assert len(calls)==2
    assert "FICTIONAL corrected brief source" in w.brief_browser.toPlainText()
    assert ctl.store.brief_manifest_matches(w._displayed_brief_snapshot["manifest"])
    assert w.brief_export_button.isEnabled()


def test_generate_read_error_is_visible_and_manual_retry_recovers(desktop,monkeypatch):
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"high","Health")])
    original=ctl.brief_events
    calls=[]
    def read(**kwargs):
        calls.append(1)
        if len(calls)==1:
            raise RuntimeError("offline intentional read failure")
        return original(**kwargs)
    monkeypatch.setattr(ctl,"brief_events",read)
    w._request_brief()
    assert wait_until(lambda:w._requested_brief_job is None)
    assert "Brief read failed" in w.brief_browser.toPlainText()
    assert not w.brief_export_button.isEnabled()
    w._request_brief()
    assert wait_until(lambda:w._requested_brief_job is None
                     and w._displayed_brief_snapshot is not None)
    assert len(calls)==2
    assert w.brief_export_button.isEnabled()
