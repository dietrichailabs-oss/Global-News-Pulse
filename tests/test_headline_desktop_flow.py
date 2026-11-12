"""Real Controller/SQLite/Qt presentation; controlled inference, no live services."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import socket
from datetime import datetime, timezone
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow

class Worker:
    def __init__(self): self.calls=[]; self.cancelled=[]
    def submit(self,*args): self.calls.append(args); return True
    def cancel(self,rid): self.cancelled.append(rid); return True

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def desktop(tmp_path,app,monkeypatch):
    def denied(*args,**kwargs):raise AssertionError('Headline UI tests cannot use network or consent dialogs')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(QMessageBox,'question',denied)
    c=Controller(tmp_path,demo=True)
    worker=Worker();c._headlines.worker=worker
    c.translator.catalog={'fr':{'name':'French','key':'fr-fixture','sha256':'a'*64}}
    monkeypatch.setattr(c.translator,'installed',lambda code:True)
    w=MainWindow(c);w.show();app.processEvents()
    yield w,c,worker
    w._force_close=True;w.close();c.close();app.processEvents()

def seed(c,count=2):
    stamp=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    reports=[]
    for i in range(count):
        reports.append(dict(id=f'fr{i}',source_id='fixture',publisher='Fictional French source',
            title=f'Le port {i} est fermé',summary='Original source excerpt',language='fr',
            url=f'https://publisher.example/story/{i}',published_at=stamp,retrieved_at=stamp,
            category='News',region='Global',country='',severity='unassessed',
            independence='unknown',event_key=f'headline-fixture-{i}',synthetic=True))
    c.store.ingest(reports,now=stamp)
    return copy.deepcopy(c.events())

def test_feed_rows_auto_translate_without_selecting_each_and_preserve_evidence(desktop,app,monkeypatch):
    w,c,worker=desktop
    originals=seed(c)
    c.data_changed.emit();app.processEvents()
    assert w.feed_list.count()==2
    assert len(worker.calls)==2
    assert all(call[3] is False for call in worker.calls)
    first=w.feed_list.item(0).data(Qt.ItemDataRole.UserRole)
    w.navigate_event(first['id']);app.processEvents()
    media=[];maps=[];manual=[]
    monkeypatch.setattr(w.media,'set_event',lambda *args:media.append(args))
    monkeypatch.setattr(w.world_map,'set_events',lambda *args,**kwargs:maps.append(args))
    c.translation_ready.connect(lambda *args:manual.append(args))
    outputs={}
    for rid,code,title,_ in list(worker.calls):
        outputs[title]='Translated headline for '+title
        c._translation_complete(rid,code,outputs[title],'')
    app.processEvents();app.processEvents()
    for i in range(2):
        item=w.feed_list.item(i);e=item.data(Qt.ItemDataRole.UserRole)
        assert item.text()==outputs[e['title']]
        assert e['title'].startswith('Le port')
        assert 'Machine translated' in e['_translation_label']
        assert e['title'] in item.toolTip()
    assert outputs[first['title']] in w.intel_browser.toPlainText()
    assert 'Original headline:' in w.intel_browser.toPlainText()
    assert c.events()==originals
    assert not media and not maps and not manual
    assert w._selected_id==first['id']

def test_english_control_restores_originals_and_does_not_start_monitoring(desktop,app):
    w,c,worker=desktop
    seed(c);c.data_changed.emit();app.processEvents()
    pending=list(worker.calls)
    w.english_headlines.setChecked(False);app.processEvents()
    assert c.get_setting('english_headlines') is False
    assert len(worker.cancelled)==2
    for rid,code,title,_ in pending:c._translation_complete(rid,code,'Late translated text','')
    app.processEvents()
    for i in range(w.feed_list.count()):
        item=w.feed_list.item(i)
        assert item.text()==item.data(Qt.ItemDataRole.UserRole)['title']
    assert not c.monitoring and not c.scheduler._thread
    c.set_setting('english_headlines',True);app.processEvents()
    assert w.english_headlines.isChecked()

def test_missing_model_leaves_original_and_visible_install_status(desktop,app,monkeypatch):
    w,c,worker=desktop
    monkeypatch.setattr(c.translator,'installed',lambda code:False)
    seed(c);c.data_changed.emit();app.processEvents()
    assert not worker.calls
    item=w.feed_list.item(0)
    assert item.text()==item.data(Qt.ItemDataRole.UserRole)['title']
    assert 'install French model' in item.data(Qt.ItemDataRole.UserRole)['_translation_label']

def test_untrusted_translation_is_escaped_in_brief(desktop,app):
    w,c,worker=desktop
    seed(c,1);c.data_changed.emit();app.processEvents()
    rid,code,title,_=worker.calls[0]
    payload='<b>Literal translated headline</b>'
    c._translation_complete(rid,code,payload,'');app.processEvents();app.processEvents()
    assert payload in w.intel_browser.toPlainText()
    assert w.feed_list.item(0).text()==payload
