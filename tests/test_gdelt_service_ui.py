"""Actual Qt/Controller and owned child tests; no public network or live wait."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import socket
import sys
import time
import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication,QMessageBox
from global_pulse.gdelt_service import GdeltService
from global_pulse.gdelt_schedule import Schedule
from global_pulse.controller import Controller
from global_pulse.gdelt_controls import GdeltControls

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('No public network in desktop scheduler tests')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)


def spin(app,predicate,seconds=8):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        app.processEvents()
        if predicate():return
        time.sleep(.01)
    assert predicate(),'Timed out waiting for owned test process'


def service(tmp_path,monkeypatch,code):
    s=GdeltService(tmp_path/'global-pulse.sqlite3',lambda:7)
    s.schedule.status()
    monkeypatch.setattr(s,'command',lambda:(sys.executable,['-c',code]))
    return s


def test_actual_child_completes_and_next_refresh_cannot_repeat(tmp_path,app,monkeypatch):
    code="import sys;from global_pulse.gdelt_schedule import Schedule;a=sys.argv;Schedule(a[a.index('--database')+1]).finish(a[a.index('--token')+1],{'status':'complete','cached_rows':12,'batch_timestamp':'20261111151500'})"
    s=service(tmp_path,monkeypatch,code)
    try:
        assert s.process is None and not s.timer.isActive()
        s.set_active(True);assert s.process is not None
        spin(app,lambda:s.process is None)
        state=s.status();assert state['state']=='current' and state['cached_rows']==12
        for _ in range(10):s.tick()
        assert s.process is None and s.status()['last_attempt']==state['last_attempt']
    finally:s.close()

@pytest.mark.parametrize('action',['pause','close','timeout'])
def test_owned_sleeping_child_is_terminated_not_abandoned(tmp_path,app,monkeypatch,action):
    s=service(tmp_path,monkeypatch,'import time;time.sleep(60)')
    try:
        s.set_active(True);p=s.process
        assert p.waitForStarted(5000)
        if action=='pause':s.set_active(False)
        elif action=='close':s.close()
        else:s._timeout()
        spin(app,lambda:s.process is None)
        assert p.state()==QProcess.ProcessState.NotRunning
        state=s.status();assert state['token'] is None and state['next_at']>time.time()
        assert state['state']==('error' if action=='timeout' else 'cancelled')
    finally:s.close()


def test_failed_start_records_safe_backoff(tmp_path,app,monkeypatch):
    s=service(tmp_path,monkeypatch,'')
    monkeypatch.setattr(s,'command',lambda:(str(tmp_path/'no-such-program'),[]))
    try:
        s.set_active(True);spin(app,lambda:s.process is None)
        assert s.status()['state']=='error' and s.status()['failures']==1
        s.tick();assert s.process is None
    finally:s.close()


def test_demo_and_default_controller_never_launch_batch_worker(tmp_path,app,monkeypatch):
    c=Controller(tmp_path,demo=True)
    try:
        assert not c.get_setting('gdelt_batches_enabled',False)
        c.set_setting('gdelt_batches_enabled',True);c.start();c.resume()
        assert not c._gdelt.active and c._gdelt.process is None
        controls=GdeltControls(c);assert not controls.enable.isEnabled()
        controls.close()
    finally:c.close()


def test_controller_opt_in_start_pause_resume_and_legacy_search_suppression(tmp_path,app,monkeypatch):
    c=Controller(tmp_path)
    calls=[]
    monkeypatch.setattr(c.scheduler,'start',lambda:None)
    monkeypatch.setattr(c.scheduler,'resume',lambda:None)
    monkeypatch.setattr(c.scheduler,'pause',lambda:None)
    monkeypatch.setattr(c._gdelt,'set_active',lambda value:calls.append(value))
    try:
        c.start();assert calls[-1] is False
        c.set_setting('gdelt_batches_enabled',True);assert calls[-1] is True
        assert all(not s['enabled'] for s in c.scheduler.sources if s.get('adapter')=='gdelt_doc')
        c.pause();assert calls[-1] is False
        c.resume();assert calls[-1] is True
        c.set_setting('gdelt_batches_enabled',False);assert calls[-1] is False
        assert c.events()==[] # Coded records not fabricated as news/map events.
        with pytest.raises(ValueError):c.set_setting('gdelt_batches_enabled','true')
        with pytest.raises(ValueError):c.set_setting('gdelt_retention_days',True)
    finally:c.close()


def test_control_declined_consent_and_status_are_truthful(tmp_path,app,monkeypatch):
    c=Controller(tmp_path)
    controls=GdeltControls(c)
    try:
        monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
        controls.enable.setChecked(True)
        assert not controls.enable.isChecked() and not c.get_setting('gdelt_batches_enabled',False)
        assert c._gdelt.process is None
        monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
        controls.enable.setChecked(True)
        assert c.get_setting('gdelt_batches_enabled') and c._gdelt.process is None
        assert 'Paused' in controls.status_label.text()
        controls.days.setValue(14);assert c.get_setting('gdelt_retention_days')==14
        assert 'The separate GDELT map layer shows supported countries and source records.' in controls.info.text()
    finally:controls.close();c.close()


def test_malformed_saved_batch_preferences_fail_closed_without_overwrite(tmp_path,app):
    c=Controller(tmp_path)
    c.store.set_setting('gdelt_batches_enabled','true');c.store.set_setting('gdelt_retention_days',{})
    c.close();c=Controller(tmp_path)
    try:
        assert c.get_setting('gdelt_batches_enabled') is False
        assert c.get_setting('gdelt_retention_days')==7
        assert c.store.get_setting('gdelt_batches_enabled')=='true'
        assert c.store.get_setting('gdelt_retention_days')=={}
    finally:c.close()
