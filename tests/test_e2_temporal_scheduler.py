"""Actual scheduler/store integration, with an offline deterministic collector.

No Qt, native notification, live provider or production catalog claim is made.
"""
import pytest
from global_pulse import sources
from global_pulse.core import Store
from test_e2_temporal_evidence import NOW,FUTURE,report,measurement

@pytest.mark.parametrize('status',['available','not_modified','stale'])
def test_successful_empty_poll_refreshes_stored_evidence(monkeypatch,tmp_path,status):
    monkeypatch.setattr(sources,'load_catalog',lambda: [])
    class EmptyCollector:
        def __init__(self,source): pass
        def collect(self,state):
            return {'reports':[],'observations':[],'state':{'status':status,'last_success':FUTURE}}
    with Store(tmp_path/'s.sqlite3',mode='synthetic') as store:
        e=store.ingest([report(),measurement()],now=NOW)[0]
        calls=[]
        def ingest(items):
            calls.append(items)
            store.ingest(items,now=FUTURE)
        scheduler=sources.Scheduler(store,ingest,collector_factory=EmptyCollector)
        scheduler._collect({'id':'fixture','url':'https://fixture.example/feed'}, {},scheduler._generation)
        assert calls==[[]]
        assert store.get_event(e['id'])['verification']=='official'

@pytest.mark.parametrize('state', ['error','rate_limited','unavailable','disabled','paused','stale_generation','stopped'])
def test_unsuccessful_paused_or_stale_collection_cannot_trigger_refresh(monkeypatch,tmp_path,state):
    monkeypatch.setattr(sources,'load_catalog',lambda: [])
    class EmptyCollector:
        def __init__(self,source): pass
        def collect(self,previous):
            status=state if state in {'error','rate_limited','unavailable','disabled'} else 'available'
            return {'reports':[],'observations':[],'state':{'status':status}}
    with Store(tmp_path/'s.sqlite3',mode='synthetic') as store:
        store.ingest([report(),measurement()],now=NOW)
        calls=[]
        scheduler=sources.Scheduler(store,lambda items:calls.append(items),collector_factory=EmptyCollector)
        generation=scheduler._generation
        if state=='paused':scheduler.pause()
        if state=='stale_generation':scheduler._generation+=1
        if state=='stopped':scheduler.stop()
        scheduler._collect({'id':'fixture','url':'https://fixture.example/feed'}, {},generation)
        assert calls==[]
