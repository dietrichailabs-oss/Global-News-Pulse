"""Non-future evidence regression controls for the temporal-policy patch."""
from global_pulse.core import Store, alert_reason, notification_view
from test_e2_temporal_evidence import NOW, report, measurement


def test_current_official_measurement_keeps_attribution_and_location(tmp_path):
    with Store(tmp_path/'current.sqlite3',mode='synthetic') as store:
        e=store.ingest([measurement(published_at=NOW)],now=NOW)[0]
        assert e['verification']=='official' and e['official_attribution']
        assert (e['latitude'],e['longitude'])==(30.0,40.0)
        assert alert_reason(e).startswith('Official announcement:')


def test_two_current_original_reporting_origins_remain_developing(tmp_path):
    with Store(tmp_path/'independent.sqlite3',mode='synthetic') as store:
        a=report(kind='report',origin_id='first',independence='original',severity='moderate')
        b=report('second',source_id='second-desk',kind='report',origin_id='second',
                 independence='original',severity='moderate',summary='A distinct independent account.')
        e=store.ingest([a,b],now=NOW)[0]
        assert e['verification']=='developing'
        assert e['independent_origins']==['first','second']
        assert alert_reason(e).startswith('Developing event:')


def test_ten_syndicated_copies_do_not_confirm_a_rumor(tmp_path):
    with Store(tmp_path/'syndication.sqlite3',mode='synthetic') as store:
        reports=[report(origin_id='rumor')]+[
            report(f'copy{i}',source_id=f'desk{i}',origin_id='rumor',independence='syndicated',kind='repost')
            for i in range(10)]
        e=store.ingest(reports,now=NOW)[0]
        assert len(e['reports'])==11 and not e['independent_origins']
        assert e['verification']=='unverified' and alert_reason(e) is None


def test_current_material_correction_retains_history_and_policy(tmp_path):
    with Store(tmp_path/'correction.sqlite3',mode='synthetic') as store:
        e=store.ingest([report(official=True,kind='announcement',severity='high')],now=NOW)[0]
        e2=store.ingest([report('correction',official=True,kind='correction',correction_of='current',
              severity='informational',summary='The original closure notice was wrong.')],
              now='2026-11-08T12:01:00Z')[0]
        assert len(store.list_events())==1
        assert alert_reason(e2,e).startswith('Correction:')
        assert next(r for r in e2['reports'] if r['id']=='current')['evidence_status']=='corrected'
        assert store.get_event(e['id'],at=NOW)['severity']=='high'


def test_foreign_source_cannot_withdraw_original_reporting(tmp_path):
    with Store(tmp_path/'foreign.sqlite3',mode='synthetic') as store:
        original=report(official=True,official_scope='measurement',severity='high')
        false_withdrawal=report('withdrawal',source_id='foreign',retraction_of='current',kind='retraction')
        e=store.ingest([original,false_withdrawal],now=NOW)[0]
        assert e['verification']=='official'
        assert next(r for r in e['reports'] if r['id']=='current')['evidence_status']=='active'
        assert next(r for r in e['reports'] if r['id']=='withdrawal')['unresolved_reference']=='current'


def test_source_muting_does_not_erase_archive_and_removes_official_credit(tmp_path):
    with Store(tmp_path/'mute.sqlite3',mode='synthetic') as store:
        e=store.ingest([report(),measurement(published_at=NOW)],now=NOW)[0]
        projected=notification_view(e,['measure'])
        assert projected['verification']=='unverified'
        assert not projected['official_attribution']
        assert alert_reason(projected) is None
        assert store.get_event(e['id'])['verification']=='official'
        assert len(store.get_event(e['id'])['reports'])==2
