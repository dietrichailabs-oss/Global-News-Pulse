"""Engineering checks: actual capacity/persistence/UI paths; inference protocol is stubbed."""
import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import socket
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from global_pulse.controller import Controller
from global_pulse.core import Store
from global_pulse.sources import load_catalog, make_user_feed, Scheduler
from global_pulse.capacity_limits import MAX_TOTAL_SOURCES
from global_pulse.headline_translation import HeadlineTranslations

@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('These product tests cannot access the network')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(QMessageBox,'question',denied)

class Worker:
    def __init__(self):self.calls=[];self.cancelled=[];self.accept=True
    def submit(self,*args):self.calls.append(args);return self.accept
    def cancel(self,rid):self.cancelled.append(rid);return True

@pytest.fixture
def service(app):
    worker=Worker()
    translator=SimpleNamespace(catalog={'fr':{'key':'fr-v1','sha256':'a'*64,'name':'French'}}, installed=lambda code:True)
    s=HeadlineTranslations(translator,worker,lambda:True)
    yield s
    s.close()

def event(title='Le port est fermé',code='fr',**changes):
    r={'id':'r1','title':title,'language':code,'evidence_status':'active'}
    r.update(changes)
    return {'id':'e1','title':title,'reports':[r]}

def complete(s,text='The port is closed',error=''):
    rid,code,_,install=s.worker.calls[-1]
    assert install is False
    assert s.complete(rid,code,text,error)

@pytest.mark.parametrize('count',[201,300,301,512])
def test_expanded_bundled_catalog_and_scheduler_accept_capacity(tmp_path,count):
    base=load_catalog()[0]
    rows=[dict(base,id=f'capacity_{i}',enabled=False) for i in range(count)]
    path=tmp_path/'sources.json';path.write_text(json.dumps({'schema_version':1,'sources':rows}))
    loaded=load_catalog(path)
    store=Store(tmp_path/'state.sqlite3')
    try:
        scheduler=Scheduler(store,lambda _:None);scheduler.set_sources(loaded)
        assert len(scheduler.sources)==count and scheduler.max_workers==4
        assert not scheduler._thread and not scheduler._workers
    finally:store.close()

def test_513_catalog_and_scheduler_refuse_without_mutation(tmp_path):
    base=load_catalog()[0];rows=[dict(base,id=f'x{i}',enabled=False) for i in range(513)]
    p=tmp_path/'catalog.json';p.write_text(json.dumps({'schema_version':1,'sources':rows}))
    with pytest.raises(ValueError):load_catalog(p)
    store=Store(tmp_path/'x.sqlite3')
    try:
        s=Scheduler(store,lambda _:None);prior=copy.deepcopy(s.sources)
        with pytest.raises(ValueError):s.set_sources(rows)
        assert s.sources==prior
    finally:store.close()

def test_expanded_catalog_does_not_grant_access(tmp_path):
    base=load_catalog()[0];rows=[dict(base,id=f'x{i}',enabled=False) for i in range(300)]
    rows[-1].update(enabled=True,access_status='review_required')
    p=tmp_path/'catalog.json';p.write_text(json.dumps({'schema_version':1,'sources':rows}))
    with pytest.raises(ValueError):load_catalog(p)
    store=Store(tmp_path/'x.sqlite3')
    try:
        s=Scheduler(store,lambda _:None)
        with pytest.raises(ValueError):s.set_sources(rows)
    finally:store.close()

def test_512_sources_persist_reopen_and_settings_save(tmp_path,app):
    c=Controller(tmp_path)
    count=MAX_TOTAL_SOURCES-len(c.catalog)
    feeds=[make_user_feed(f'https://feed{i}.example.org/rss',f'Feed {i}',validate_dns=False) for i in range(count)]
    c.store.set_setting('user_feeds',feeds)
    c.close()
    c=Controller(tmp_path)
    try:
        assert len(c.catalog)==512
        ids=[s['id'] for s in c.catalog]
        c.set_setting('enabled_sources',ids);c.set_setting('muted_sources',ids)
        assert len(c.scheduler.sources)==512
        assert not c.monitoring and not c.scheduler._thread
        before=c.store.get_setting('user_feeds')
        with pytest.raises(ValueError):c.add_user_feed('https://overflow.example.org/rss','Overflow')
        assert c.store.get_setting('user_feeds')==before
        with pytest.raises(ValueError):c.set_setting('enabled_sources',ids+['overflow'])
    finally:c.close()
    c=Controller(tmp_path)
    try:
        assert len(c.catalog)==512 and c.get_setting('muted_sources')==ids
    finally:c.close()

def test_ordinary_setting_budget_is_not_expanded(tmp_path):
    store=Store(tmp_path/'x.sqlite3')
    try:
        with pytest.raises(ValueError):store.set_setting('ordinary','x'*250001)
        with pytest.raises(ValueError):store.set_setting('user_feeds','x'*2000001)
    finally:store.close()

def test_translation_preserves_original_and_deduplicates(service):
    e=event();old=copy.deepcopy(e)
    assert service.view(e)['state']=='pending'
    service.view(e)
    assert len(service.worker.calls)==1
    complete(service)
    result=service.view(e)
    assert result['title']=='The port is closed' and result['original']==e['title']
    assert result['state']=='ready' and 'Machine translated' in result['label']
    assert e==old and len(service.worker.calls)==1

@pytest.mark.parametrize('code',['en','und','xx'])
def test_english_unknown_and_unsupported_do_not_queue(service,code):
    service.view(event(code=code))
    assert not service.worker.calls

def test_missing_model_does_not_download_or_popup(service):
    service.translator.installed=lambda code:False
    assert service.view(event())['state']=='missing_model'
    assert not service.worker.calls

@pytest.mark.parametrize('changes',[{'future_dated':True},{'evidence_status':'retracted'},{'kind':'retraction'},{'status':'cancelled'}])
def test_ineligible_report_cannot_supply_headline_language(service,changes):
    service.view(event(**changes));assert not service.worker.calls

def test_unmatched_title_not_mislabelled(service):
    e=event();e['reports'][0]['title']='Different title'
    service.view(e);assert not service.worker.calls

def test_background_jobs_bounded_and_never_download(service):
    for i in range(100):service.view(event(title=f'Le port fermé {i}'))
    assert len(service.pending)==2 and len(service.worker.calls)==2
    assert all(call[3] is False for call in service.worker.calls)

def test_queue_full_does_not_leave_phantom_pending(service):
    service.worker.accept=False
    assert service.view(event())['state']=='waiting'
    assert not service.pending and not service.keys

def test_failed_translation_is_not_refreshed_into_retry_loop(service):
    service.view(event());complete(service,error='failed')
    for _ in range(20):assert service.view(event())['state']=='failed'
    assert len(service.worker.calls)==1

def test_changed_text_and_model_never_reuse_stale_result(service):
    service.view(event());complete(service)
    assert service.view(event(title='Le nouveau port est fermé'))['state']=='pending'
    service.translator.catalog['fr']['sha256']='b'*64
    assert service.view(event())['state']=='pending'
    assert len(service.worker.calls)==3

def test_late_replaced_model_result_discarded(service):
    service.view(event());service.translator.catalog['fr']['sha256']='b'*64
    complete(service)
    assert not service.cache

def test_disable_cancel_and_close_suppress_late_popup_path(service):
    service.view(event());rid,code,_,_=service.worker.calls[-1]
    service.cancel_pending()
    assert rid in service.worker.cancelled and service.complete(rid,code,'late','')
    assert not service.cache
    service.enabled=lambda:False
    assert service.view(event())['state']=='original'
    service.close();assert service.complete(rid,code,'later','')

def test_cache_remains_bounded(service):
    service.MAX_CACHE=3
    for i in range(8):
        service.view(event(title=f'Le port fermé {i}'));complete(service,f'Closed port {i}')
    assert len(service.cache)==3

def test_controller_routes_automatic_completion_without_manual_dialog(tmp_path,app,monkeypatch):
    c=Controller(tmp_path)
    worker=Worker();c._headlines.worker=worker
    c.translator.catalog={'fr':{'key':'fr-v1','sha256':'a'*64,'name':'French'}}
    monkeypatch.setattr(c.translator,'installed',lambda code:True)
    manual=[];c.translation_ready.connect(lambda *args:manual.append(args))
    try:
        e=event();c.headline_view(e)
        rid,code,_,_=worker.calls[-1]
        c._translation_complete(rid,code,'The port is closed','')
        assert c.headline_view(e)['state']=='ready' and not manual
        assert c.events()==[] # Presentation never writes source reports.
        c.set_setting('english_headlines',False)
        assert c.headline_view(e)['title']==e['title']
        with pytest.raises(ValueError):c.set_setting('english_headlines','false')
    finally:c.close()

def test_35_model_catalog_and_traditional_routing_are_present(tmp_path,app):
    from global_pulse.language_codes import normalize_language
    c=Controller(tmp_path)
    try:
        assert len(c.translator.catalog)==35
        assert normalize_language('zh-TW-u-nu-hanidec')=='zt'
        assert normalize_language('zh-Hans-TW')=='zh'
    finally:c.close()
