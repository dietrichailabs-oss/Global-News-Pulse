"""Post-splash GDELT is a real Qt + SQLite worker operation, never idle SQL.

Synthetic source bytes imported into a real local GDELT archive. No network,
no fabricated current crisis, no accepted audio/video or physical Win11 claim.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import threading
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.map_widget import WorldMap
from global_pulse.gdelt_map_panel import GdeltMapPanel
from global_pulse.gdelt_batches import GdeltBatchCache
from global_pulse.gdelt_map_data import empty
from test_gdelt_batch_cache import event_row, payload, batch_from_archive
import global_pulse.gdelt_map_panel as projection_module


def spin(app, predicate, seconds=5):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    assert predicate(), "Bounded real Qt/worker result not delivered"


def fixture(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path)
    world=WorldMap()
    panel=GdeltMapPanel(controller,world)
    now=datetime.now(timezone.utc)
    past=(now-timedelta(hours=1)).replace(minute=0,second=0,microsecond=0)
    stamp=past.strftime("%Y%m%d%H%M%S")
    data=payload([event_row("9101",country="UP",
                            day=past.strftime("%Y%m%d"),date_added=stamp)],stamp=stamp)
    with GdeltBatchCache(controller.store.path) as cache:
        assert cache.import_export(batch_from_archive(data,stamp=stamp),
                                   data,now=now.isoformat())["added"]==1
    return app,controller,world,panel


def close(app,controller,world,panel):
    panel.timer.stop()
    panel.close()
    world.close()
    controller.close()
    app.processEvents()


def test_real_sqlite_read_is_not_on_qt_and_heartbeat_runs_while_blocked(tmp_path,monkeypatch):
    app,controller,world,panel=fixture(tmp_path)
    gate=threading.Event()
    started=threading.Event()
    calls=[]
    original=projection_module.read_archive
    def slow_read(*a,**kw):
        calls.append(threading.current_thread().name)
        assert threading.current_thread() is not threading.main_thread()
        started.set()
        assert gate.wait(3), "Test worker must be deliberately released"
        return original(*a,**kw)
    monkeypatch.setattr(projection_module,"read_archive",slow_read)
    ticks=[]
    ticker=QTimer()
    ticker.setInterval(16)
    ticker.timeout.connect(lambda:ticks.append(time.monotonic()))
    ticker.start()
    try:
        beginning=time.monotonic()
        panel.refresh_idle({})
        assert time.monotonic()-beginning<.15, "Qt scheduled read blocked before worker"
        assert started.wait(2)
        until=time.monotonic()+.2
        while time.monotonic()<until:
            app.processEvents()
            time.sleep(.005)
        assert len(ticks)>=5, "Qt heartbeat stopped while archive worker waited"
        assert panel.mapped_count==0 and panel.snapshot["state"]=="loading"
        gate.set()
        spin(app,lambda:not panel._idle_inflight)
        assert panel.snapshot["state"]=="ready"
        assert panel.mapped_count==1
        assert "GDELT: 1 retained coded observation" in panel.country_text("Ukraine")
        assert "ukraine" in panel.snapshot["countries"]
        before=len(calls)
        world.view_changed.emit()
        app.processEvents()
        assert len(calls)==before, "Camera movement must never reread SQLite"
    finally:
        gate.set()
        ticker.stop()
        close(app,controller,world,panel)


def test_filter_change_hides_old_worker_result_and_keeps_evidence(tmp_path,monkeypatch):
    app,controller,world,panel=fixture(tmp_path)
    gate=threading.Event()
    started=threading.Event()
    original=projection_module.read_archive
    calls=[]
    def slow_read(*a,**kw):
        calls.append(threading.current_thread().name)
        started.set()
        assert gate.wait(3)
        return original(*a,**kw)
    monkeypatch.setattr(projection_module,"read_archive",slow_read)
    try:
        panel.refresh_idle({})
        assert started.wait(2)
        panel.refresh_idle({"query":"Ukraine"})
        assert panel.snapshot["state"]=="filtered"
        assert panel.mapped_count==0
        gate.set()
        spin(app,lambda:not panel._idle_inflight)
        assert panel.snapshot["state"]=="filtered"
        assert panel.mapped_count==0
        assert len(calls)==1
        panel.refresh_idle({})
        spin(app,lambda:panel.snapshot["state"]=="ready")
        assert panel.mapped_count==1
        assert len(calls)==2
    finally:
        gate.set()
        close(app,controller,world,panel)


def test_many_status_pulses_have_one_pending_worker_and_no_qt_sql(tmp_path,monkeypatch):
    app,controller,world,panel=fixture(tmp_path)
    started=threading.Event()
    gate=threading.Event()
    original=projection_module.read_archive
    names=[]
    def held_read(*a,**kw):
        names.append(threading.current_thread().name)
        if len(names)==1:
            started.set()
            assert gate.wait(3)
        return original(*a,**kw)
    monkeypatch.setattr(projection_module,"read_archive",held_read)
    try:
        panel.refresh_idle({})
        assert started.wait(2)
        for _ in range(12):
            controller.gdelt_status_changed.emit()
            app.processEvents()
        assert len(names)==1
        gate.set()
        spin(app,lambda:len(names)==2 and not panel._idle_inflight)
        assert all(name=="pulse-idle-gdelt" for name in names)
        assert panel.mapped_count==1
        assert not panel._idle_pending
    finally:
        gate.set()
        close(app,controller,world,panel)


def test_failed_async_projection_is_labeled_not_stale_or_fabricated(tmp_path,monkeypatch):
    app,controller,world,panel=fixture(tmp_path)
    try:
        monkeypatch.setattr(projection_module,"read_archive",lambda *a,**kw:empty("unavailable","Read budget reached"))
        panel.refresh_idle({})
        spin(app,lambda:not panel._idle_inflight)
        assert panel.snapshot["state"]=="unavailable"
        assert panel.mapped_count==0
        assert "Read budget reached" in panel.status.text()
    finally:
        close(app,controller,world,panel)
