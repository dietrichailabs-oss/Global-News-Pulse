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


def test_timeout_retires_document_but_never_overlaps_previous_reader(desktop,monkeypatch):
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"high","Health")])
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def read(**kwargs):
        calls.append(kwargs["period"])
        if len(calls)==1:
            entered.set()
            assert release.wait(5)
        return original(**kwargs)
    monkeypatch.setattr(ctl,"brief_events",read)
    try:
        w._request_brief()
        assert entered.wait(2)
        first=w._requested_brief_job
        w._expire_requested_brief(first[0])
        assert w._requested_brief_target is None
        assert w._requested_brief_job==first
        assert "timed out" in w.brief_browser.toPlainText()
        assert not w.brief_export_button.isEnabled()
        w._request_brief()
        queued=w._requested_brief_target
        w._request_brief()
        assert w._requested_brief_target==queued and queued!=first[0]
        assert w._requested_brief_job==first and len(calls)==1
        release.set()
        assert wait_until(lambda:w._requested_brief_job is None
                         and w._displayed_brief_snapshot is not None)
        assert len(calls)==2
        assert w.brief_export_button.isEnabled()
    finally:
        release.set()


def test_actual_idle_reader_drains_before_requested_reader(desktop,monkeypatch):
    from datetime import timedelta
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"high","Health")])
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def read(**kwargs):
        calls.append(kwargs["period"])
        if len(calls)==1:
            entered.set()
            assert release.wait(5)
        return original(**kwargs)
    monkeypatch.setattr(ctl,"brief_events",read)
    generated=datetime.now(timezone.utc)
    snapshot={"generation":w._idle_snapshot_generation,
              "brief_period":"daily","brief_epoch":w._brief_request_epoch,
              "brief_since":(generated-timedelta(days=1)).isoformat(),
              "brief_generated":generated}
    try:
        w._idle_brief_inflight=True
        w._begin_idle_brief_read(snapshot)
        assert entered.wait(2) and w._idle_brief_worker_active
        w._request_brief()
        assert w._requested_brief_job is None and w._requested_brief_target is not None
        assert len(calls)==1
        release.set()
        assert wait_until(lambda:w._requested_brief_target is None
                         and w._displayed_brief_snapshot is not None)
        assert len(calls)==2
        assert not w._idle_brief_worker_active
        assert not w._idle_brief_inflight
    finally:
        release.set()


def test_hidden_daily_correction_does_not_cancel_requested_weekly(desktop,monkeypatch):
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"critical","Disaster")])
    assert w._generate_brief()
    w.brief_period.setCurrentIndex(1)
    w._workspace_warm_timer.stop()
    w._evidence_refresh_timer.stop()
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def read(**kwargs):
        calls.append(kwargs["period"])
        entered.set()
        assert release.wait(5)
        return original(**kwargs)
    monkeypatch.setattr(ctl,"brief_events",read)
    try:
        w._request_brief()
        assert entered.wait(2)
        target=w._requested_brief_target
        old_epoch=w._brief_request_epoch
        ctl.store.ingest([dict(_report(1,"critical","Disaster"),
                              title="FICTIONAL corrected daily evidence")])
        w._validate_brief_snapshots()
        assert w._brief_request_epoch>old_epoch
        assert w._requested_brief_target==target
        release.set()
        assert wait_until(lambda:w._requested_brief_target is None
                         and w._displayed_brief_snapshot is not None)
        assert calls==["weekly"]
        assert w._displayed_brief_key[0]=="weekly"
        assert "FICTIONAL corrected daily evidence" in w.brief_browser.toPlainText()
        assert w.brief_export_button.isEnabled()
    finally:
        release.set()


def test_requested_html_is_constructed_off_gui_and_preserves_exact_renderer_output(desktop,monkeypatch):
    from global_pulse import brief_rendering
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"critical","Disaster"),_report(2,"high","Health")])
    owner=threading.get_ident()
    original=brief_rendering.brief_html
    calls=[]
    def render(events,period,*,markdown=None):
        assert threading.get_ident()!=owner,"requested HTML constructed on GUI"
        calls.append((period,markdown))
        return original(events,period,markdown=markdown)
    monkeypatch.setattr(brief_rendering,"brief_html",render)
    w._request_brief()
    assert wait_until(lambda:w._requested_brief_job is None
                     and w._displayed_brief_snapshot is not None)
    snapshot=w._displayed_brief_snapshot
    assert calls==[("daily",snapshot["markdown"])]
    assert snapshot["html"]==original([],"daily",markdown=snapshot["markdown"])
    assert "FICTIONAL executive report 1" in w.brief_browser.toPlainText()
    assert ctl.store.brief_manifest_matches(snapshot["manifest"])
    assert w.brief_export_button.isEnabled()


def test_requested_worker_render_correction_is_revalidated_before_publication(desktop,monkeypatch):
    from global_pulse import brief_rendering
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"critical","Disaster")])
    owner=threading.get_ident()
    original=brief_rendering.brief_html
    calls=[]
    def render(events,period,*,markdown=None):
        assert threading.get_ident()!=owner
        html=original(events,period,markdown=markdown)
        calls.append(markdown)
        if len(calls)==1:
            ctl.store.ingest([dict(_report(1,"critical","Disaster"),
                                   title="FICTIONAL corrected during HTML preparation")])
        return html
    monkeypatch.setattr(brief_rendering,"brief_html",render)
    w._request_brief()
    assert wait_until(lambda:w._requested_brief_job is None
                     and w._displayed_brief_snapshot is not None)
    assert len(calls)==2
    assert "FICTIONAL corrected during HTML preparation" not in calls[0]
    assert "FICTIONAL corrected during HTML preparation" in w.brief_browser.toPlainText()
    assert ctl.store.brief_manifest_matches(w._displayed_brief_snapshot["manifest"])
    assert w.brief_export_button.isEnabled()


def test_real_scheduled_deadline_keeps_reader_lease_and_late_retry_recovers(desktop,monkeypatch):
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"high","Health")])
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def read(**kwargs):
        calls.append(kwargs["period"])
        if len(calls)==1:
            entered.set()
            assert release.wait(65),"test did not release actual deadline fixture"
        return original(**kwargs)
    monkeypatch.setattr(ctl,"brief_events",read)
    try:
        started=time.monotonic()
        w._request_brief()
        assert entered.wait(2)
        old=w._requested_brief_job
        # No timer substitution, manual expiry call or changed production bound.
        assert wait_until(lambda:w._requested_brief_target is None,timeout=50)
        elapsed=time.monotonic()-started
        assert 44<=elapsed<50,elapsed
        assert w._requested_brief_job==old
        assert ctl._brief_reader_count==1
        assert "timed out" in w.brief_browser.toPlainText()
        assert not w.brief_export_button.isEnabled()
        w._request_brief()
        assert w._requested_brief_target!=old[0]
        assert w._requested_brief_job==old
        assert len(calls)==1
        release.set()
        assert wait_until(lambda:w._requested_brief_job is None
                         and w._displayed_brief_snapshot is not None)
        assert len(calls)==2
        assert ctl._settle_brief_readers()
        assert w.brief_export_button.isEnabled()
    finally:
        release.set()
        assert ctl._settle_brief_readers(timeout=5)


@pytest.mark.parametrize("period",["daily","weekly"])
def test_close_during_owned_brief_read_preserves_store_until_reader_drains(desktop,monkeypatch,period):
    from global_pulse.controller import ShutdownPending
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"high","Health")])
    w.brief_period.setCurrentIndex(0 if period=="daily" else 1)
    w._workspace_warm_timer.stop()
    w._evidence_refresh_timer.stop()
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    finished=threading.Event()
    outcomes=[]
    def read(**kwargs):
        # The actual worker has released SQLite but still requires a later
        # access. The connection must stay open across shutdown finalization.
        assert ctl.store.content_revision()
        entered.set()
        assert release.wait(8)
        rows=original(**kwargs)
        finished.set()
        return rows
    monkeypatch.setattr(ctl,"brief_events",read)
    try:
        w._request_brief()
        assert entered.wait(2)
        ctl.begin_close()
        with pytest.raises(ShutdownPending,match="closing"):
            ctl.start_brief_reader(lambda:None,name="forbidden-after-close")
        def finish():
            try:
                ctl.finish_close({})
            except Exception as exc:
                outcomes.append(exc)
            else:
                outcomes.append("closed")
        finalizer=threading.Thread(target=finish)
        finalizer.start()
        assert wait_until(lambda:bool(outcomes),timeout=4)
        finalizer.join(2)
        assert len(outcomes)==1 and isinstance(outcomes[0],ShutdownPending),outcomes
        assert "Brief archive reader" in str(outcomes[0])
        assert not ctl._store_closed and not ctl.store._closed
        assert ctl.store.stats()["events"]==1
        release.set()
        assert wait_until(lambda:finished.is_set() and ctl._brief_reader_count==0)
        assert wait_until(lambda:w._requested_brief_job is None)
        assert w._displayed_brief_snapshot is None
        assert not w.brief_export_button.isEnabled()
        assert wait_until(ctl.close_ready)
        outcomes.clear()
        finalizer=threading.Thread(target=finish)
        finalizer.start()
        assert wait_until(lambda:bool(outcomes),timeout=5)
        finalizer.join(2)
        assert outcomes==["closed"],outcomes
        assert ctl._store_closed and ctl.store._closed
    finally:
        release.set()
        assert ctl._settle_brief_readers(timeout=5)


def test_real_period_supersession_queues_weekly_and_rejects_old_daily(desktop,monkeypatch):
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"critical","Disaster")])
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def read(**kwargs):
        calls.append(kwargs["period"])
        rows=original(**kwargs)
        if len(calls)==1:
            entered.set()
            assert release.wait(8)
        return rows
    monkeypatch.setattr(ctl,"brief_events",read)
    try:
        w._request_brief()
        assert entered.wait(2)
        original_job=w._requested_brief_job
        w.brief_period.setCurrentIndex(1)
        assert w._requested_brief_target[1]=="weekly"
        assert w._requested_brief_job==original_job
        assert calls==["daily"] and not w.brief_export_button.isEnabled()
        release.set()
        assert wait_until(lambda:w._requested_brief_target is None
                          and w._displayed_brief_snapshot is not None)
        assert calls==["daily","weekly"]
        assert w._displayed_brief_key[0]=="weekly"
        assert w._daily_brief_snapshot is None
        assert ctl.store.brief_manifest_matches(w._displayed_brief_snapshot["manifest"])
        assert w.brief_export_button.isEnabled()
    finally:
        release.set()
        assert ctl._settle_brief_readers(timeout=5)


def test_real_requested_daily_rollover_rejects_old_day_and_recaptures(desktop,monkeypatch):
    from datetime import timedelta
    from global_pulse import ui
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"critical","Disaster")])
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    now=datetime.now(timezone.utc)
    next_day=now+timedelta(days=1)
    calls=[]
    def read(**kwargs):
        calls.append(kwargs["since"])
        rows=original(**kwargs)
        if len(calls)==1:
            entered.set()
            assert release.wait(8)
        return rows
    class NextDay(datetime):
        @classmethod
        def now(cls,tz=None):
            return next_day.astimezone(tz) if tz else next_day.replace(tzinfo=None)
    monkeypatch.setattr(ctl,"brief_events",read)
    try:
        w._request_brief()
        assert entered.wait(2)
        monkeypatch.setattr(ui,"datetime",NextDay)
        w._brief_clock_tick()
        assert not w.brief_export_button.isEnabled()
        release.set()
        assert wait_until(lambda:w._requested_brief_target is None
                          and w._displayed_brief_snapshot is not None)
        assert len(calls)==2
        snapshot=w._displayed_brief_snapshot
        assert snapshot["day"]==next_day.date().isoformat()
        assert snapshot["manifest"]
        assert datetime.fromisoformat(calls[1])==next_day-timedelta(days=1)
        assert w.brief_export_button.isEnabled()
    finally:
        release.set()
        assert ctl._settle_brief_readers(timeout=5)


def test_real_prune_during_requested_read_cannot_publish_removed_source(desktop,monkeypatch):
    from datetime import timedelta
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"critical","Disaster")])
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def read(**kwargs):
        rows=original(**kwargs)
        calls.append(len(rows))
        if len(calls)==1:
            entered.set()
            assert release.wait(8)
        return rows
    monkeypatch.setattr(ctl,"brief_events",read)
    try:
        w._request_brief()
        assert entered.wait(2)
        assert ctl.store.prune(1,now=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat())["reports"]==1
        w._brief_reports_pruned()
        assert not w.brief_export_button.isEnabled()
        release.set()
        assert wait_until(lambda:w._requested_brief_target is None
                          and w._displayed_brief_snapshot is not None)
        assert calls==[1,0]
        assert not w._displayed_brief_snapshot["manifest"]
        assert "FICTIONAL executive report 1" not in w.brief_browser.toPlainText()
        assert "FICTIONAL executive report 1" not in w._displayed_brief_snapshot["html"]
        assert "FICTIONAL executive report 1" not in w._displayed_brief_snapshot["markdown"]
    finally:
        release.set()
        assert ctl._settle_brief_readers(timeout=5)


def test_actual_idle_reader_exit_coordinator_waits_and_finalizes_once(desktop,monkeypatch):
    from datetime import timedelta
    from types import SimpleNamespace
    from global_pulse.__main__ import _ExitCoordinator
    app,ctl,w=desktop
    ctl.store.ingest([_report(1,"critical","Disaster")])
    original=ctl.brief_events
    entered,release=threading.Event(),threading.Event()
    def read(**kwargs):
        assert ctl.store.content_revision()
        entered.set()
        assert release.wait(12)
        return original(**kwargs)
    monkeypatch.setattr(ctl,"brief_events",read)
    completed,waiting,blocked=[],[],[]
    # Actual coordinator and archive, inert notification dependency only.
    notifier=SimpleNamespace(begin_close=lambda:[],close_ready=lambda:True)
    coordinator=_ExitCoordinator(ctl,notifier)
    coordinator.finished.connect(lambda:completed.append(True))
    coordinator.waiting.connect(waiting.append)
    coordinator.blocked.connect(blocked.append)
    generated=datetime.now(timezone.utc)
    snapshot={"generation":w._idle_snapshot_generation,
              "brief_period":"daily","brief_epoch":w._brief_request_epoch,
              "brief_since":(generated-timedelta(days=1)).isoformat(),
              "brief_generated":generated}
    try:
        w._idle_brief_inflight=True
        w._begin_idle_brief_read(snapshot)
        assert entered.wait(2)
        assert ctl._brief_reader_count==1 and w._idle_brief_worker_active
        coordinator.begin({})
        assert wait_until(lambda:bool(waiting),timeout=6)
        assert not completed and not blocked
        assert not coordinator.completed and not coordinator.failed
        assert not ctl.store._closed and ctl.store.stats()["events"]==1
        release.set()
        assert wait_until(lambda:coordinator.completed,timeout=6)
        assert completed==[True] and not blocked
        assert ctl.store._closed and ctl._brief_reader_count==0
        assert not w._idle_brief_worker_active
        assert w._deferred_brief_events is None
    finally:
        release.set()
        assert ctl._settle_brief_readers(timeout=5)
        if coordinator.started and not coordinator.completed:
            wait_until(lambda:coordinator.completed or coordinator.failed,timeout=6)
        coordinator.timer.stop()


def test_reader_start_failure_rolls_back_lease_and_sync_close_refuses_active_reader(desktop):
    from global_pulse.controller import ShutdownPending
    app,ctl,w=desktop
    with patch.object(threading.Thread,"start",side_effect=RuntimeError("fixture start failure")):
        with pytest.raises(RuntimeError,match="fixture start failure"):
            ctl.start_brief_reader(lambda:None,name="failed-fixture-reader")
    assert ctl._brief_reader_count==0 and ctl._settle_brief_readers(timeout=0)
    entered,release=threading.Event(),threading.Event()
    def read():
        entered.set()
        assert release.wait(8)
        ctl.store.content_revision()
    try:
        ctl.start_brief_reader(read,name="sync-close-fixture-reader")
        assert entered.wait(2)
        with pytest.raises(ShutdownPending,match="Brief archive reader"):
            ctl.close()
        assert not ctl.store._closed and ctl._brief_reader_count==1
        release.set()
        assert ctl._settle_brief_readers(timeout=5)
        ctl.close()
        assert ctl.store._closed
    finally:
        release.set()
        assert ctl._settle_brief_readers(timeout=5)


def test_large_brief_preview_pages_preserve_full_text_links_and_export(desktop,monkeypatch,tmp_path):
    from collections import Counter
    from html.parser import HTMLParser
    from PySide6.QtWidgets import QFileDialog
    from global_pulse.brief_rendering import brief_markdown_pages,PREVIEW_PAGE_BYTES
    app,ctl,w=desktop
    ctl.store.ingest([_report(i,"critical","Disaster") for i in range(1,301)])
    w._request_brief()
    assert wait_until(lambda:w._requested_brief_job is None
                     and w._displayed_brief_snapshot is not None)
    snapshot=w._displayed_brief_snapshot
    parts=brief_markdown_pages(snapshot["markdown"])
    pages=snapshot["preview_pages"]
    assert len(pages)==len(parts)>1
    assert "".join(parts)==snapshot["markdown"]
    assert max(len(part.encode("utf-8")) for part in parts)<=PREVIEW_PAGE_BYTES
    class Links(HTMLParser):
        def __init__(self,html):
            super().__init__()
            self.links=[]
            self.feed(html)
        def handle_starttag(self,tag,attrs):
            if tag=="a" and dict(attrs).get("href"):
                self.links.append(dict(attrs)["href"])
    assert Counter(link for page in pages for link in Links(page).links)==Counter(Links(snapshot["html"]).links)
    assert len(snapshot["manifest"])==300
    assert w.brief_preview_page.maximum()==len(pages)
    assert w._brief_preview_index==0
    w.brief_preview_page.setValue(len(pages))
    assert w._brief_preview_index==len(pages)-1
    assert w._displayed_brief_snapshot is snapshot
    assert "Verification notes" in w.brief_browser.toPlainText()
    target=tmp_path/"full-paged-report.html"
    monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *a,**k:(str(target),"HTML"))
    w._export_brief()
    assert target.read_text(encoding="utf-8")==snapshot["html"]
    # A subsequent correction invalidates every page and the full export.
    ctl.store.ingest([dict(_report(1,"critical","Disaster"),
                           title="FICTIONAL corrected paged evidence")])
    w.brief_preview_page.setValue(1)
    assert w._displayed_brief_snapshot is None
    assert not w.brief_export_button.isEnabled()
    assert w.brief_preview_page.maximum()==1
