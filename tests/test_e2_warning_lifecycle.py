"""Real parser/store/controller regressions: synthetic only, no HTTP or toasts."""
from itertools import permutations
from pathlib import Path
import json
import pytest
from global_pulse.core import Store, normalize_report, alert_reason
from global_pulse.sources import parse_nws, parse_feed

T = '2026-11-08T12:00:00Z'
END = '2026-11-08T13:00:00Z'
SOURCE = dict(id='nws-test', name='Synthetic warning authority', url='https://alerts.example/index',
              category='Disaster', country='Norland', official=True, language='en', independence='original')


def message(identifier, kind='Alert', references=(), minute=0, **override):
    p = dict(id=identifier, **{'@id': 'https://alerts.example/' + identifier},
             status='Actual', messageType=kind, sender='fixture@alerts.example',
             sent=f'2026-11-08T12:{minute:02d}:00Z', headline=f'Synthetic warning {kind} {identifier}',
             event='Synthetic Warning', description=f'Controlled fictional notice {identifier}',
             severity='Severe' if kind=='Alert' else 'Minor', areaDesc='Synthetic area',
             expires=END, references=[{'identifier': ref, '@id': 'https://alerts.example/' + ref,
                  'sender': 'fixture@alerts.example', 'sent': T} for ref in references])
    p.update(override)
    raw = {'id': 'https://alerts.example/' + identifier, 'properties': p}
    r = parse_nws({'features': [raw]}, SOURCE, p['sent'])[0]
    r['synthetic'] = True
    return r


def cap(identifier, kind='Alert', references=(), info=True, sender='fixture@alerts.example', minute=0):
    refs = ' '.join(f'{sender},{ref},{T}' for ref in references)
    details = f'<info><event>Synthetic flood warning</event><headline>Synthetic {identifier}</headline><severity>Severe</severity><expires>{END}</expires></info>' if info else ''
    xml = f'<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><identifier>{identifier}</identifier><sender>{sender}</sender><sent>2026-11-08T12:{minute:02d}:00Z</sent><status>Actual</status><msgType>{kind}</msgType><references>{refs}</references>{details}</alert>'
    r = parse_feed(xml.encode(), dict(SOURCE, adapter='cap'), T)[0]
    r['synthetic'] = True
    return r


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path/'warning.sqlite3', mode='synthetic') as s:
        yield s


@pytest.mark.parametrize('order', list(permutations(range(3))))
def test_nws_three_message_chain_any_delivery_order(store, order):
    records = [message('a'), message('b', 'Update', ['a'], 5), message('c', 'Cancel', ['b'], 10)]
    for index in order:
        store.ingest([records[index]], now='2026-11-08T12:20:00Z')
    events = store.list_events()
    assert len(events)==1
    e=events[0]
    assert e['status']=='cancelled'
    assert e['report_count']==3
    assert all(r['evidence_status']!='active' for r in e['reports'])
    assert all(r.get('cap_message_type') and r.get('expires_at') for r in e['reports'])


@pytest.mark.parametrize('reverse', [False, True])
def test_cap_standalone_cancel_preserves_identity_and_history(store, reverse):
    records=[cap('a'),cap('b','Cancel',['a'],False,minute=5)]
    if reverse: records.reverse()
    first=store.ingest([records[0]],now='2026-11-08T12:10:00Z')[0]
    store.ingest([records[1]],now='2026-11-08T12:11:00Z')
    assert len(store.list_events())==1
    e=store.get_event(first['id'])
    assert e['status']=='cancelled'
    assert len(e['reports'])==2 and len(e['timeline'])==2
    assert 'cancelled' in e['recap'] and 'retracted' not in e['recap']


def test_cancel_alert_once_then_persistent_after_reopen(tmp_path):
    path=tmp_path/'restart.sqlite3'
    with Store(path,mode='synthetic') as s:
        a=s.ingest([message('a')],now=T)[0]
        s.add_alert(a,alert_reason(a))
        b=s.ingest([message('b','Cancel',['a'],5)],now='2026-11-08T12:05:00Z')[0]
        reason=alert_reason(b,a)
        assert reason.startswith('Correction:')
        assert s.add_alert(b,reason)
        assert s.ingest([message('b','Cancel',['a'],5)],now='2026-11-08T12:06:00Z')==[]
        assert s.add_alert(b,reason) is None
    with Store(path,mode='synthetic') as s:
        assert len(s.list_events())==1 and s.get_event(a['id'])['status']=='cancelled'
        assert len(s.list_alerts())==2


def test_expiry_from_empty_successful_poll_is_not_new_announcement(store):
    a=store.ingest([message('a')],now=T)[0]
    changed=store.ingest([],now=END)
    assert len(changed)==1
    e=changed[0]
    assert e['status']=='expired'
    assert all(x['kind']=='expiry' for x in e['changes'])
    assert alert_reason(e,a) is None
    assert store.ingest([],now='2026-11-08T13:01:00Z')==[]
    assert store.get_event(a['id'],at='2026-11-08T12:30:00Z')['status']=='active'


def test_unknown_cancel_is_pending_and_does_not_announce_warning(store):
    e=store.ingest([message('c','Cancel',['missing'],5)],now='2026-11-08T12:06:00Z')[0]
    assert e['status']=='pending'
    assert alert_reason(e) is None
    assert e['reports'][0]['unresolved_reference']


def test_wrong_sender_cannot_cancel_warning(store):
    a=store.ingest([message('a')],now=T)[0]
    other=message('c','Cancel',['a'],5,sender='other@alerts.example')
    store.ingest([other],now='2026-11-08T12:06:00Z')
    assert store.get_event(a['id'])['status']=='active'


def test_cross_source_cannot_cancel_warning(store):
    a=store.ingest([message('a')],now=T)[0]
    other=message('b','Cancel',['a'],5)
    other['source_id']='other'
    store.ingest([other],now='2026-11-08T12:06:00Z')
    assert store.get_event(a['id'])['status']=='active'


def test_reference_metadata_survives_and_remains_inert():
    r=normalize_report(message('b','Cancel',['a'],5),'2026-11-08T12:06:00Z')
    assert r['source_references'][0]['identifier']=='a'
    assert r['source_references'][0]['sender']=='fixture@alerts.example'
    assert r['cap_message_type']=='Cancel' and r['expires_at']==END


def test_future_cancel_becomes_effective_via_unrelated_ingest(store):
    a=store.ingest([message('a')],now=T)[0]
    c=message('c','Cancel',['a'],30)
    store.ingest([c],now=T)
    assert store.get_event(a['id'])['status']=='active'
    changed=store.ingest([],now='2026-11-08T12:31:00Z')
    e=next(e for e in changed if e['id']==a['id'])
    assert e['status']=='cancelled'
    assert alert_reason(e,a).startswith('Correction:')
    assert any(c['kind']=='correction' for c in e['changes'])


def test_bridge_merge_preserves_saved_links_and_historical_ids(store):
    a=store.ingest([message('a')],now=T)[0]
    c=store.ingest([message('c','Cancel',['b'],10)],now='2026-11-08T12:11:00Z')[0]
    assert len(store.list_events())==2
    store.save_situation(c['id'])
    store.ingest([message('b','Update',['a'],5)],now='2026-11-08T12:12:00Z')
    assert len(store.list_events())==1
    assert store.get_event(c['id'])['status']=='cancelled'
    assert store.get_event(c['id'])['id']==a['id']
    assert store.get_event(c['id'],at='2026-11-08T12:11:00Z')['id']==c['id']
    assert len(store.list_situations())==1


def test_nws_reference_alias_is_an_alternative_not_a_second_required_warning(store):
    a=message('a')
    # Original supplied only its stable identifier; cancellation has an extra URL.
    a['identity_aliases']=[a['id']]
    original=store.ingest([a],now=T)[0]
    result=store.ingest([message('c','Cancel',['a'],5)],now='2026-11-08T12:06:00Z')[0]
    assert result['id']==original['id'] and result['status']=='cancelled'
    assert alert_reason(result,original).startswith('Correction:')


def test_user_supplied_cap_is_not_promoted_to_official_authority():
    xml=f'<alert><identifier>a</identifier><sender>untrusted</sender><sent>{T}</sent><status>Actual</status><msgType>Alert</msgType><info><headline>Unverified source warning</headline><severity>Severe</severity></info></alert>'
    source=dict(SOURCE,adapter='rss',official=False,independence='unknown')
    report=parse_feed(xml.encode(),source,T)[0]
    assert not report['official']
    with Store(':memory:') as s:
        event=s.ingest([report],now=T)[0]
        assert not event['official_attribution'] and alert_reason(event) is None


def test_invalid_expiry_cannot_create_active_official_warning(store):
    e=store.ingest([message('a',expires='definitely-not-a-time')],now=T)[0]
    assert e['status']=='pending'
    assert e['reports'][0]['expiry_invalid']
    assert not e['official_attribution'] and alert_reason(e) is None


def test_merge_retention_removes_both_histories_but_keeps_current_redirect(store):
    a=message('a');a['retention_days']=1
    original=store.ingest([a],now=T)[0]
    cancel=store.ingest([message('c','Cancel',['b'],10)],now='2026-11-08T12:11:00Z')[0]
    store.ingest([message('b','Update',['a'],5)],now='2026-11-08T12:12:00Z')
    current=store.get_event(original['id'])
    assert current['linked_event_histories'][cancel['id']]
    store.save_situation(cancel['id']);store.save_situation(original['id'])
    assert len(store.list_situations())==1
    store.prune(now='2026-11-10T12:00:00Z')
    assert store.get_event(cancel['id'],at='2026-11-08T12:11:00Z') is None
    current=store.get_event(original['id'])
    assert current is not None and current['linked_event_histories']=={}
    assert all(r['id']!=a['id'] for r in current['reports'])
    assert store.get_event(cancel['id'])['id']==original['id']
