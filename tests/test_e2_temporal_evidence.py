"""Engineering GP-CORE-003 regressions using the complete core and real SQLite.

All reports are synthetic and offline. These are not independent QA or Qt/native tests.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest
from global_pulse.core import Store, alert_reason, build_brief, notification_view

NOW = '2026-11-08T12:00:00Z'
FUTURE = '2026-11-09T12:00:00Z'

def report(identifier='current', **overrides):
    r = dict(id=identifier, source_id='desk', publisher='Fictional regional desk',
             title='Fictional port closure report', summary='An unverified port closure is reported.',
             url='https://reports.example/' + identifier, published_at=NOW, retrieved_at=NOW,
             language='en', region='Test Region', country='Testland', category='Infrastructure',
             event_key='temporal-test', severity='informational', kind='social', official=False,
             origin_id='', independence='unknown', synthetic=True)
    r.update(overrides)
    return r

def measurement(**overrides):
    r = report('measurement', source_id='measure', publisher='Fictional measuring authority',
               title='Future official port measurement', summary='FUTURE_ONLY_EXCERPT',
               official=True, official_scope='measurement', kind='report', origin_id='measurement-origin',
               independence='original', severity='critical', published_at=FUTURE,
               latitude=30.0, longitude=40.0, geo_precision='exact')
    r.update(overrides)
    return r

@pytest.fixture
def store(tmp_path):
    with Store(tmp_path/'records.sqlite3', mode='synthetic') as s:
        yield s


def test_future_official_measurement_does_not_verify_current_report(store):
    e = store.ingest([report(), measurement()], now=NOW)[0]
    assert e['verification'] == 'unverified'
    assert not e['official_attribution']
    assert e['independent_origins'] == []
    assert len(e['reports']) == 2
    assert next(r for r in e['reports'] if r['id']=='measurement')['future_dated']


def test_future_evidence_does_not_supply_current_severity_recap_or_location(store):
    e = store.ingest([report(), measurement()], now=NOW)[0]
    assert e['severity'] == 'informational'
    assert e['latitude'] is None and e['longitude'] is None
    assert 'FUTURE_ONLY_EXCERPT' not in e['recap']
    assert e['title'] == 'Fictional port closure report'
    assert not e['emerging']
    assert e['dimensions']['evidence_quality'] != 'official measurement'


def test_future_independent_origin_cannot_corroborate(store):
    a = report(kind='report', origin_id='desk-a', independence='original')
    b = report('future-b', source_id='desk-b', kind='report', origin_id='desk-b',
               independence='original', published_at=FUTURE, summary='Independent future account')
    e = store.ingest([a, b], now=NOW)[0]
    assert e['verification'] == 'unverified'
    assert e['independent_origins'] == ['desk-a']
    assert alert_reason(e) is None


def test_future_claim_does_not_create_current_contradiction(store):
    claims = lambda n: {'evacuated': {'value': n, 'unit':'people', 'as_of':NOW, 'scope':'port'}}
    e = store.ingest([report(claims=claims(2)), measurement(claims=claims(200))], now=NOW)[0]
    assert e['contradictions'] == []


@pytest.mark.parametrize('kind,field', [('correction','correction_of'),('retraction','retraction_of')])
def test_future_notice_cannot_withdraw_current_evidence(store, kind, field):
    original = report(official=True, kind='report', official_scope='measurement', severity='high')
    store.ingest([original], now=NOW)
    notice = report('notice', published_at=FUTURE, kind=kind, severity='informational', official=True,
                    summary='Future withdrawal', **{field:'current'})
    e = store.ingest([notice], now=NOW)[0]
    assert e['verification'] == 'official'
    assert e['status'] == 'active'
    assert next(r for r in e['reports'] if r['id']=='current')['evidence_status']=='active'
    assert alert_reason(e, store.last_previous_events[e['id']]) is None


def test_future_only_is_deferred_not_retracted_or_currently_official(store):
    e = store.ingest([measurement()], now=NOW)[0]
    assert e['status'] == 'pending'
    assert e['verification'] == 'unverified'
    assert e['severity'] == 'unassessed'
    assert not e['official_attribution']
    assert e['latitude'] is None and not e['emerging']
    assert 'future-dated' in e['recap'].lower()
    assert alert_reason(e) is None


@pytest.mark.parametrize('seconds,eligible', [(599, True), (600,True), (601,False)])
def test_existing_ten_minute_clock_skew_boundary(store, seconds, eligible):
    t = datetime.fromisoformat(NOW.replace('Z','+00:00')) + timedelta(seconds=seconds)
    e = store.ingest([measurement(published_at=t.isoformat())], now=NOW)[0]
    assert (e['verification']=='official') is eligible


def test_unchanged_reingestion_reassesses_time_but_preserves_history(store):
    old = store.ingest([report(), measurement()], now=NOW)[0]
    changed = store.ingest([measurement()], now=FUTURE)
    assert len(changed)==1
    current = changed[0]
    assert current['verification']=='official'
    assert current['revision']==old['revision']+1
    past = store.get_event(old['id'], at=NOW)
    assert past['verification']=='unverified'
    assert next(r for r in past['reports'] if r['id']=='measurement')['future_dated']
    assert not next(r for r in current['reports'] if r['id']=='measurement')['future_dated']
    assert store.ingest([measurement()], now=FUTURE)==[]


def test_clock_only_refresh_after_restart_preserves_original_source_revision(tmp_path):
    path=tmp_path/'restart.sqlite3'
    with Store(path, mode='synthetic') as s:
        e=s.ingest([report(),measurement()], now=NOW)[0]
        count=s._conn.execute('SELECT count(*) FROM report_revisions').fetchone()[0]
    with Store(path, mode='synthetic') as s:
        changed=s.ingest([], now=FUTURE)
        assert len(changed)==1 and changed[0]['id']==e['id']
        assert changed[0]['verification']=='official'
        assert s._conn.execute('SELECT count(*) FROM report_revisions').fetchone()[0]==count
        assert s.get_event(e['id'], at=NOW)['verification']=='unverified'
        assert s.ingest([], now=FUTURE)==[]


def test_future_source_revision_timestamp_is_not_current_evidence(store):
    e=store.ingest([report(),measurement(published_at=NOW,source_updated_at=FUTURE)], now=NOW)[0]
    assert e['verification']=='unverified'
    assert next(r for r in e['reports'] if r['id']=='measurement')['future_dated']


def test_muted_projection_does_not_promote_remaining_future_measurement(store):
    e=store.ingest([report(),measurement()], now=NOW)[0]
    projected=notification_view(e,['desk'])
    assert projected['verification']=='unverified'
    assert projected['status']=='pending'
    assert not projected['official_attribution']
    assert alert_reason(projected) is None


def test_brief_retains_future_source_but_not_current_measurement_claim(store):
    e=store.ingest([report(),measurement()], now=NOW)[0]
    brief=build_brief([e])
    assert 'Future official port measurement' in brief
    assert 'FUTURE_ONLY_EXCERPT' not in brief
    assert 'future' in brief.lower()
    assert 'This is an official measurement' not in brief


def test_repeated_fetch_before_due_does_not_create_fake_revisions(store):
    e=store.ingest([report(),measurement()], now=NOW)[0]
    assert store.ingest([measurement()], now='2026-11-08T13:00:00Z')==[]
    assert store.get_event(e['id'])['revision']==e['revision']


def test_existing_e1_overstatement_is_repaired_without_overwriting_historical_snapshot(store):
    e=store.ingest([report(),measurement()], now=NOW)[0]
    # Emulate the cached derived E1 row; do not alter raw report/history bytes.
    cached=json.loads(store._conn.execute('SELECT body FROM events WHERE id=?',(e['id'],)).fetchone()[0])
    cached.pop('evidence_policy_version',None)
    cached['verification']='official'
    store._conn.execute('UPDATE events SET body=? WHERE id=?',(json.dumps(cached),e['id']))
    store._conn.commit()
    changed=store.ingest([],now='2026-11-08T12:01:00Z')
    assert len(changed)==1
    assert changed[0]['verification']=='unverified'
    assert changed[0]['evidence_policy_version']>=2


def test_e1_historical_projection_is_recomputed_without_changing_original_snapshot(store):
    e=store.ingest([report(),measurement()],now=NOW)[0]
    row=store._conn.execute('SELECT body FROM event_revisions WHERE event_id=?',(e['id'],)).fetchone()
    saved=json.loads(row[0]); saved['event'].pop('evidence_policy_version',None)
    saved['event']['verification']='official'
    original=json.dumps(saved)
    store._conn.execute('UPDATE event_revisions SET body=? WHERE event_id=?',(original,e['id']))
    store._conn.commit()
    read=store.get_event(e['id'],at=NOW)
    assert read['verification']=='unverified'
    assert read['recorded_verification']=='official'
    assert read['classification_recomputed']
    assert read['timeline'][0]['verification']=='unverified'
    assert read['timeline'][0]['recorded_verification']=='official'
    assert store._conn.execute('SELECT body FROM event_revisions WHERE event_id=?',(e['id'],)).fetchone()[0]==original


def test_temporal_refresh_crosses_multiple_scan_pages(store):
    records=[measurement(id=f'm{i}',event_key=f'future-{i}',url=f'https://reports.example/m{i}') for i in range(270)]
    store.ingest(records,now=NOW)
    changed=store.ingest([],now=FUTURE)
    assert len(changed)==270
    assert all(e['verification']=='official' for e in changed)
    assert store.ingest([],now=FUTURE)==[]


@pytest.mark.parametrize('kind,field,prefix',[('correction','correction_of','Correction:'),('retraction','retraction_of','Retraction:')])
@pytest.mark.parametrize('delivery',['empty_poll','unchanged_report','other_report'])
def test_deferred_material_notice_keeps_notice_policy_when_it_becomes_eligible(store,kind,field,prefix,delivery):
    original=report(official=True,kind='report',severity='high')
    notice=report('notice',official=True,kind=kind,severity='informational',published_at=FUTURE,
                  summary='The earlier warning is withdrawn or corrected.',**{field:'current'})
    e=store.ingest([original,notice],now=NOW)[0]
    previous=store.get_event(e['id'])
    incoming=[] if delivery=='empty_poll' else [notice] if delivery=='unchanged_report' else [report('other',published_at=FUTURE)]
    current=store.ingest(incoming,now=FUTURE)[0]
    assert alert_reason(current,previous).startswith(prefix)
    change=next(c for c in current['changes'] if c.get('report_id')=='notice')
    assert change['temporal_reassessment']
    assert change['kind']==kind
    assert store.get_event(e['id'],at=NOW)['status']=='active'


def test_future_retrieval_time_alone_does_not_defer_source_evidence(store):
    e=store.ingest([measurement(published_at=NOW,retrieved_at=FUTURE)],now=NOW)[0]
    assert e['verification']=='official'


def test_timestamp_correction_does_not_rewrite_earlier_snapshot(store):
    e=store.ingest([report(),measurement()],now=NOW)[0]
    corrected=measurement(published_at=NOW)
    current=store.ingest([corrected],now='2026-11-08T12:01:00Z')[0]
    assert current['verification']=='official'
    assert store.get_event(e['id'],at=NOW)['verification']=='unverified'


def test_current_evidence_remains_identical_regardless_of_future_report_order(tmp_path):
    events=[]
    for i,records in enumerate(([report(),measurement()],[measurement(),report()])):
        with Store(tmp_path/f'order{i}.sqlite3',mode='synthetic') as s:
            events.append(s.ingest(records,now=NOW)[0])
    for key in ['title','recap','severity','verification','latitude','longitude','material_signature','independent_origins','contradictions']:
        assert events[0][key]==events[1][key]
