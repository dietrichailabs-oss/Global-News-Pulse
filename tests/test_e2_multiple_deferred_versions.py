"""GP-CORE-007: real SQLite/Qt regressions for multiple deferred source versions.

Synthetic clocks and local records only. Signals/internal alert rows are not
Windows toast observations. Source-version rows and historical snapshots remain
immutable; an empty/304 collection is not a new source retrieval.
"""
import json

import pytest

from global_pulse.core import Store, alert_reason

T0 = '2026-11-09T12:00:00Z'
T1 = '2026-11-09T12:01:00Z'
T2 = '2026-11-09T12:02:00Z'
MID = '2026-11-09T12:20:00Z'
END = '2026-11-09T12:40:00Z'


def version(number=1, **overrides):
    r = dict(id='measurement', source_id='qa-authority', publisher='Fictional authority',
        title='Fictional Northhaven gauge', summary=f'Fictional gauge version {number}',
        url='https://authority.example/report/1', published_at=T0,
        retrieved_at={1:T0, 2:T1, 3:T2}[number], language='en',
        region='Northhaven', country='Norland', category='Infrastructure',
        event_key='multiple-deferred', severity='high' if number==1 else 'informational',
        official=True, official_scope='measurement', origin_id='qa-authority',
        independence='original', synthetic=True, status='active', kind='measurement')
    if number == 2:
        r.update(source_updated_at=MID, kind='correction')
    if number == 3:
        r.update(source_updated_at=END, kind='retraction', status='retracted')
    r.update(overrides)
    return r


def source_rows(store):
    return [tuple(r) for r in store._conn.execute(
        'SELECT id,record_key,seen_at,fingerprint,body FROM report_revisions ORDER BY id')]


@pytest.mark.parametrize('trigger', ['empty', 'unchanged', 'unrelated'])
@pytest.mark.parametrize('reopen', [False, True])
def test_each_effective_version_and_notice_once(tmp_path, trigger, reopen):
    path = tmp_path/'multiple.sqlite3'
    with Store(path, mode='synthetic') as s:
        first = s.ingest([version()], now=T0)[0]
        eid = first['id']
        assert s.ingest([version(2)], now=T1) == []
        assert s.ingest([version(3)], now=T2) == []
        assert s.get_event(eid)['revision'] == 1
        immutable = source_rows(s)
        if reopen:
            s.close()
            s = Store(path, mode='synthetic')
        try:
            payload = {'empty': [], 'unchanged':[version(3)],
                'unrelated':[version(id='comment', source_id='comment', kind='commentary',
                                     official=False, source_updated_at=MID)]}[trigger]
            changed = s.ingest(payload, now=MID)
            middle = s.get_event(eid)
            assert len(changed) == 1
            assert middle['revision'] == 2
            assert middle['reports'][0]['summary'] == version(2)['summary'] or any(
                r['id']=='measurement' and r['summary']==version(2)['summary'] for r in middle['reports'])
            assert alert_reason(middle, s.last_previous_events[eid]).startswith('Correction:')
            assert s.ingest(payload, now=MID) == []
            final = s.ingest([], now=END)[0]
            assert final['revision'] == 3
            assert alert_reason(final, s.last_previous_events[eid]).startswith('Retraction:')
            assert s.ingest([], now=END) == []
            assert [r for r in source_rows(s) if r[1]==immutable[0][1]] == immutable
            for at,number,rev in [(T2,1,1),(MID,2,2),(END,3,3)]:
                old=s.get_event(eid,at=at)
                report=next(r for r in old['reports'] if r['id']=='measurement')
                assert old['revision']==rev
                assert report['summary']==version(number)['summary']
                assert report['retrieved_at']==version(number)['retrieved_at']
        finally:
            s.close()


def test_three_versions_received_in_one_batch_do_not_emit_future_notice(tmp_path):
    with Store(tmp_path/'batch.sqlite3', mode='synthetic') as s:
        e=s.ingest([version(),version(2),version(3)],now=T2)[0]
        assert e['reports'][0]['summary']==version()['summary']
        assert not any(c['kind'] in {'correction','retraction'} for c in e['changes'])
        assert alert_reason(e).startswith('Official announcement:')
        assert s.ingest([],now=MID)[0]['reports'][0]['summary']==version(2)['summary']


def test_multiple_future_only_versions_cannot_borrow_present_notice(tmp_path):
    with Store(tmp_path/'pending.sqlite3',mode='synthetic') as s:
        a=s.ingest([version(2)],now=T1)[0]
        b=s.ingest([version(3)],now=T2)[0]
        assert a['future_dated'] and b['future_dated']
        assert alert_reason(b,a) is None
        assert s.ingest([],now=MID)[0]['reports'][0]['summary']==version(2)['summary']


def test_numerous_deferred_versions_follow_every_observed_boundary(tmp_path):
    from datetime import datetime,timedelta,timezone
    base=datetime(2026,11,9,12,tzinfo=timezone.utc)
    stamp=lambda n:(base+timedelta(minutes=n)).isoformat().replace('+00:00','Z')
    with Store(tmp_path/'many.sqlite3',mode='synthetic') as s:
        original=s.ingest([version()],now=T0)[0]
        for i in range(1,7):
            assert s.ingest([version(2,summary=f'Correction {i}',source_updated_at=stamp(20*i))],now=T1)==[]
        original_rows=source_rows(s)
        for i in range(1,7):
            e=s.ingest([],now=stamp(20*i))[0]
            assert e['reports'][0]['summary']==f'Correction {i}'
            assert e['revision']==i+1
            assert alert_reason(e,s.last_previous_events[original['id']]).startswith('Correction:')
            assert s.ingest([],now=stamp(20*i))==[]
        assert source_rows(s)==original_rows


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


@pytest.mark.parametrize('trigger', ['empty', 'unchanged', 'scheduler_available', 'scheduler_not_modified'])
def test_actual_controller_reopen_and_scheduler_notice_sequence(tmp_path, app, trigger):
    from global_pulse.controller import Controller
    c=Controller(tmp_path,demo=True)
    try:
        for r,t in [(version(),T0),(version(2),T1),(version(3),T2)]:
            c._on_reports([r],allow_synthetic=True,now=t)
        assert [a['kind'] for a in c.store.list_alerts()]==['official']
        eid=c.events()[0]['id']
        c.close()
        c=Controller(tmp_path,demo=True)
        if trigger.startswith('scheduler_'):
            state='not_modified' if trigger.endswith('not_modified') else 'available'
            class Collector:
                def __init__(self,source): self.source=source
                def collect(self,previous):
                    return dict(reports=[],observations=[],state=dict(status=state,last_success=MID))
            c.scheduler.collector_factory=Collector
            calls=[]
            def deliver(reports):
                calls.append(reports)
                c._on_reports(reports,allow_synthetic=True,now=MID)
            c.scheduler.on_reports=deliver
            c.scheduler._collect({'id':'qa-source','url':'https://authority.example/feed'}, {}, c.scheduler._generation)
            assert calls==[[]]
            assert c.store.get_source_state('qa-source')['status']==state
        else:
            c._on_reports([version(3)] if trigger=='unchanged' else [],allow_synthetic=True,now=MID)
        assert [a['kind'] for a in reversed(c.store.list_alerts())]==['official','correction']
        c._on_reports([],allow_synthetic=True,now=MID)
        c._on_reports([],allow_synthetic=True,now=END)
        c._on_reports([],allow_synthetic=True,now=END)
        assert [a['kind'] for a in reversed(c.store.list_alerts())]==['official','correction','retraction']
        assert c.event(eid)['revision']==3
        assert all('Synthetic' in a['delivery_status'] for a in c.store.list_alerts())
    finally:
        c.close()


@pytest.mark.parametrize('setting,value', [
    ('muted_sources',['qa-authority']), ('countries',['Different country']),
    ('categories',['Different category']), ('alert_threshold','critical'),
])
def test_actual_controller_current_preferences_still_apply(tmp_path,app,setting,value):
    from global_pulse.controller import Controller
    c=Controller(tmp_path,demo=True)
    try:
        c._on_reports([version()],allow_synthetic=True,now=T0)
        c._on_reports([version(2)],allow_synthetic=True,now=T1)
        c._on_reports([version(3)],allow_synthetic=True,now=T2)
        c.set_setting(setting,value)
        c._on_reports([],allow_synthetic=True,now=MID)
        c._on_reports([],allow_synthetic=True,now=END)
        assert [a['kind'] for a in c.store.list_alerts()]==['official']
        assert c.events()[0]['revision']==3
    finally:
        c.close()
