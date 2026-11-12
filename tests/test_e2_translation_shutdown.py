"""Owned real child processes; no downloaded model or external network is needed."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
import sys
import time
import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication
from global_pulse.translation_process import TranslationProcess
from global_pulse.controller import Controller

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

def spin(app, predicate, timeout=5):
    end=time.monotonic()+timeout
    while not predicate() and time.monotonic()<end:
        app.processEvents();time.sleep(.005)
    assert predicate(),"Expected process observation did not arrive"

@pytest.fixture
def worker(tmp_path,app):
    w=TranslationProcess(tmp_path)
    yield w
    w.close()

def command(code):
    return lambda:(sys.executable,["-c",code])

SUCCESS='import pathlib,sys,json; w=pathlib.Path(sys.argv[-1]); r=json.loads((w/"request.json").read_bytes()); (w/"response.json").write_text(json.dumps({"text":"translated "+r["text"],"error":""}))'
HANG='import time,pathlib,sys; w=pathlib.Path(sys.argv[-1]); (w/"partial.argosmodel").write_bytes(b"partial"); time.sleep(30)'

def test_real_child_result_and_private_workspace_cleanup(worker,app,monkeypatch):
    monkeypatch.setattr(worker,"command",command(SUCCESS))
    results=[];worker.completed.connect(lambda *r:results.append(r))
    assert worker.submit("a","de","source excerpt",False)
    spin(app,lambda:bool(results))
    assert results==[("a","de","translated source excerpt","")]
    assert not list((worker.data_dir/"translation-jobs").iterdir())

def test_hung_inference_deadline_terminates_owned_child(worker,app,monkeypatch):
    monkeypatch.setattr(worker,"command",command(HANG));worker.inference_timeout_ms=150
    results=[];worker.completed.connect(lambda *r:results.append(r))
    worker.submit("a","de","text",False)
    spin(app,lambda:bool(results))
    assert "time limit" in results[0][3] and not results[0][2]
    assert worker.process is None and not list((worker.data_dir/"translation-jobs").iterdir())

@pytest.mark.parametrize("install",[False,True])
def test_full_controller_exit_kills_running_translation_or_download(tmp_path,app,monkeypatch,install):
    c=Controller(tmp_path);monkeypatch.setattr(c._workers,"command",command(HANG))
    results=[];c.translation_ready.connect(lambda *r:results.append(r))
    c._workers.submit("a","de","text",install)
    spin(app,lambda:c._workers.process.state()==QProcess.ProcessState.Running)
    process=c._workers.process
    start=time.monotonic();c.close();elapsed=time.monotonic()-start
    assert elapsed<3 and process.state()==QProcess.ProcessState.NotRunning
    assert c._store_closed and not results
    assert not list((tmp_path/"translation-jobs").iterdir())
    app.processEvents();assert not results

def test_failed_start_is_reported_and_cleaned(worker,app,monkeypatch):
    monkeypatch.setattr(worker,"command",lambda:(str(worker.data_dir/"missing-executable"),[]))
    results=[];worker.completed.connect(lambda *r:results.append(r))
    worker.submit("a","de","text",False)
    spin(app,lambda:bool(results))
    assert "could not start" in results[0][3]
    assert not list((worker.data_dir/"translation-jobs").iterdir())

def test_bounded_queue_cancelled_without_starting_more_workers(worker,app,monkeypatch):
    monkeypatch.setattr(worker,"command",command(HANG))
    for i in range(8):assert worker.submit(str(i),"de","text",False)
    assert not worker.submit("overflow","de","text",False)
    spin(app,lambda:worker.process.state()==QProcess.ProcessState.Running)
    worker.close();app.processEvents()
    assert not worker.queue and worker.current is None
    assert not worker.submit("closed","de","text",False)

@pytest.mark.parametrize("payload",['[]','{"text":7,"error":""}','x'*65537])
def test_malformed_or_oversized_result_fails_closed(worker,app,monkeypatch,payload):
    script='import pathlib,sys; (pathlib.Path(sys.argv[-1])/"response.json").write_text('+repr(payload)+')'
    monkeypatch.setattr(worker,"command",command(script))
    results=[];worker.completed.connect(lambda *r:results.append(r))
    worker.submit("a","de","text",False);spin(app,lambda:bool(results))
    assert results[0][2]=="" and results[0][3]

def test_real_worker_rejects_unavailable_model_without_download(worker,app):
    results=[];worker.completed.connect(lambda *r:results.append(r))
    worker.submit("a","zz","text",False);spin(app,lambda:bool(results))
    assert results[0][2]=="" and results[0][3]=="ValueError"
