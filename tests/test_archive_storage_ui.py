"""Actual Qt/Controller/SQLite controls and offline owned cleanup process."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import socket
import sqlite3
import sys
import time
import pytest
from PySide6.QtWidgets import QApplication,QMessageBox
from global_pulse.controller import Controller
from global_pulse.archive_storage_controls import ArchiveStorageControls
from global_pulse import archive_storage as storage
from test_core import report

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def controls(tmp_path,app,monkeypatch):
    def denied(*args,**kwargs):raise AssertionError('No provider requests in storage UI tests')
    monkeypatch.setattr(socket,'getaddrinfo',denied);monkeypatch.setattr(socket.socket,'connect',denied)
    errors=[];monkeypatch.setattr(sys,'excepthook',lambda *a:errors.append(a))
    controller=Controller(tmp_path);widget=ArchiveStorageControls(controller)
    yield widget,controller,errors
    widget.timer.stop();widget.close();controller.close();app.processEvents()
    assert not errors


def test_exact_dropdown_default_usage_and_reopen(controls,tmp_path,app):
    widget,c,errors=controls
    assert [widget.maximum.itemData(i) for i in range(widget.maximum.count())]==[5,10,15,20,30,50,100]
    assert widget.maximum.currentData()==30 and '30 GB maximum' in widget.usage.text()
    widget.maximum.setCurrentIndex(widget.maximum.findData(50))
    assert c.get_setting('archive_max_gb')==50 and not c.monitoring and c._gdelt.process is None
    widget.timer.stop();widget.close();c.close()
    reopened=Controller(tmp_path);again=ArchiveStorageControls(reopened)
    try:assert again.maximum.currentData()==50
    finally:again.timer.stop();again.close();reopened.close()


@pytest.mark.parametrize('bad',[True,'5',6,0,30.0])
def test_unsupported_values_refused_before_state_change(controls,bad):
    widget,c,errors=controls
    with pytest.raises(ValueError):c.set_setting('archive_max_gb',bad)
    assert c.get_setting('archive_max_gb')==30 and c._gdelt.process is None


def test_lower_cap_decline_then_accept(controls,monkeypatch):
    widget,c,errors=controls
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
    widget.maximum.setCurrentIndex(widget.maximum.findData(5))
    assert c.get_setting('archive_max_gb')==30 and widget.maximum.currentData()==30
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    widget.maximum.setCurrentIndex(widget.maximum.findData(5))
    assert c.get_setting('archive_max_gb')==5 and not c.monitoring and c._gdelt.process is None


def test_failed_write_restores_display_and_keeps_safe_message(controls,monkeypatch):
    widget,c,errors=controls
    def unavailable(*a,**k):raise sqlite3.DatabaseError('private database secret path')
    monkeypatch.setattr(c.store,'set_setting',unavailable)
    widget.maximum.setCurrentIndex(widget.maximum.findData(100))
    assert not errors and widget.maximum.currentData()==30
    assert 'could not be saved' in widget.usage.text() and 'secret' not in widget.usage.text()
    widget.refresh();assert 'could not be saved' in widget.usage.text()


def test_read_failure_restores_last_readable_display(controls,monkeypatch):
    widget,c,errors=controls
    def unavailable(*a,**k):raise sqlite3.DatabaseError('private detail')
    monkeypatch.setattr(c,'archive_storage_status',unavailable)
    monkeypatch.setattr(c,'set_setting',unavailable)
    widget.maximum.setCurrentIndex(widget.maximum.findData(100))
    assert widget.maximum.currentData()==30 and not widget.clean.isEnabled()
    assert 'unavailable' in widget.usage.text() and 'private' not in widget.usage.text()


def test_regular_collection_pauses_on_storage_block_without_alert(controls,monkeypatch,app):
    widget,c,errors=controls
    messages=[];alerts=[];c.status_changed.connect(messages.append);c.native_alert.connect(alerts.append)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:type('Disk',(),{'free':0})())
    c.monitoring=True
    c._on_reports([report(synthetic=False)])
    app.processEvents()
    assert not c.monitoring and c.store.stats()['reports']==0 and not alerts
    assert any('free space' in message for message in messages)


def test_cleanup_button_owns_real_product_worker_without_network(controls,monkeypatch,app):
    widget,c,errors=controls
    before=c._gdelt.schedule.status()
    code="import sys,socket; socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(AssertionError('network forbidden')); socket.getaddrinfo=socket.socket.connect; from global_pulse.gdelt_worker import main; raise SystemExit(main(sys.argv[1:]))"
    monkeypatch.setattr(c._gdelt,'command',lambda:(sys.executable,['-c',code]))
    widget.clean.click()
    end=time.monotonic()+15
    while c._gdelt.process is not None and time.monotonic()<end:
        app.processEvents();time.sleep(.01)
    assert c._gdelt.process is None and not c.monitoring
    assert c._gdelt.schedule.status()==before
    state=c.archive_storage_status()
    assert state['last_cleanup']['state']=='ready' and state['last_cleanup']['removed_rows']==0
    assert not errors


def test_budget_control_is_present_in_real_main_window(controls):
    from global_pulse.ui import MainWindow
    widget,c,errors=controls
    window=MainWindow(c)
    try:
        assert window.archive_storage_controls.maximum.currentData()==30
        assert window.archive_storage_controls.maximum.count()==7
    finally:window._force_close=True;window.close()
