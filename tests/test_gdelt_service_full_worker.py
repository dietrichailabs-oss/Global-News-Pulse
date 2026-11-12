"""Engineering child-process integration: actual worker/poller/parser/SQLite.

Only HTTP transport is synthetic; parent/child real sockets are blocked. The
shortened deadline test changes a test instance, not the production120s policy.
"""
import gc
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import socket
import sqlite3
import sys
import textwrap
import time
import weakref
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QProcess
from PySide6.QtWidgets import QApplication
from global_pulse.gdelt_service import GdeltService

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args,**kwargs):raise AssertionError('No real network in child integration')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)


def until(app,predicate,timeout=10):
    limit=time.monotonic()+timeout
    while not predicate() and time.monotonic()<limit:
        app.processEvents();time.sleep(.01)
    assert predicate(),'Owned child did not complete within the test bound'


def flush(app):
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents();gc.collect()


def test_real_owned_child_executes_product_worker_and_persists_import(tmp_path,app,monkeypatch):
    program=textwrap.dedent('''
        import hashlib,io,socket,sys,zipfile
        import httpx
        import global_pulse.gdelt_worker as worker
        from global_pulse.gdelt_batches import MANIFEST_URL
        def denied(*a,**k):raise AssertionError('Child must never open a real socket')
        socket.getaddrinfo=denied;socket.socket.connect=denied
        stamp='20261111151500'
        fields=['']*61
        fields[0]='9917';fields[1]='20261111';fields[26]='043';fields[29]='3'
        fields[59]=stamp;fields[60]='https://publisher.example/synthetic-report'
        target=io.BytesIO()
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr(stamp+'.export.CSV','\\t'.join(fields)+'\\n')
        payload=target.getvalue()
        manifest=(str(len(payload))+' '+hashlib.md5(payload).hexdigest()+' http://data.gdeltproject.org/gdeltv2/'+stamp+'.export.CSV.zip\\n').encode('ascii')
        calls=[]
        def handle(request):
            calls.append(str(request.url))
            assert request.url.host=='data.gdeltproject.org' and request.url.scheme=='https'
            assert len(calls)<=2
            return httpx.Response(200,content=manifest if str(request.url)==MANIFEST_URL else payload)
        original=worker.poll_latest_export
        def controlled(cache):
            with httpx.Client(transport=httpx.MockTransport(handle),trust_env=False) as client:
                return original(cache,client=client)
        worker.poll_latest_export=controlled
        result=worker.main(sys.argv[1:])
        assert result==0 and len(calls)==2
        raise SystemExit(result)
    ''')
    path=tmp_path/'global-pulse.sqlite3'
    service=GdeltService(path,lambda:7)
    monkeypatch.setattr(service,'command',lambda:(sys.executable,['-c',program]))
    try:
        service.set_active(True)
        child=service.process;assert child is not None
        until(app,lambda:service.process is None)
        state=service.status()
        assert state['state']=='current' and state['cached_rows']==1
        assert state['last_batch']=='20261111151500' and state['token'] is None
        assert state['next_at']>time.time()
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT global_event_id FROM gdelt_event_rows').fetchall()==[('9917',)]
            assert db.execute('SELECT status,lease_token,lease_until FROM gdelt_batches').fetchall()==[('complete',None,None)]
        service.tick();assert service.process is None
    finally:
        service.close();flush(app)


def test_actual_deadline_timer_stops_a_real_child(tmp_path,app,monkeypatch):
    service=GdeltService(tmp_path/'global-pulse.sqlite3',lambda:7)
    monkeypatch.setattr(service,'command',lambda:(sys.executable,['-c','import time;time.sleep(60)']))
    service.timeout_ms=150
    try:
        service.set_active(True);child=service.process
        assert child.waitForStarted(5000)
        until(app,lambda:service.process is None)
        assert child.state()==QProcess.ProcessState.NotRunning
        assert service.status()['state']=='error' and service.status()['token'] is None
        assert not service.deadline.isActive()
    finally:
        service.close();flush(app)


def test_repeated_real_stop_and_deferred_deletion_release_parent(tmp_path,app,monkeypatch):
    refs=[]
    for index in range(12):
        path=tmp_path/str(index);path.mkdir()
        service=GdeltService(path/'global-pulse.sqlite3',lambda:7)
        # Plain instance override avoids a test monkeypatch retaining services.
        service.command=lambda:(sys.executable,['-c','import time;time.sleep(60)'])
        service.set_active(True);child=service.process
        assert child.waitForStarted(5000)
        service.set_active(False)
        assert child.state()==QProcess.ProcessState.NotRunning and service.process is None
        assert service.status()['state']=='cancelled'
        refs.append(weakref.ref(service))
        service.close();service.deleteLater()
        del child,service
        flush(app)
    assert all(ref() is None for ref in refs)
