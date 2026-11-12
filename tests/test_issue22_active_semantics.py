"""Engineering follow-up to QA A1: no inactive text or aggregate-caption leak."""
from copy import deepcopy
import pytest
from global_pulse.crisis_overlay import classify_event


def event():
    return {'status':'active','title':'TEST routine bulletin','category':'News',
        'country':'Ukraine','reports':[{'id':'benign','source_id':'fixture',
        'title':'TEST routine bulletin','summary':'Inert test fixture.',
        'category':'News','official':True,'evidence_status':'active'}]}


@pytest.mark.parametrize('status',['retracted','corrected','expired','pending'])
def test_inactive_report_title_and_category_do_not_classify(status):
    value=event()
    value['reports'].append({'id':'inactive','title':'TEST armed conflict and refugees',
        'category':'Conflict','evidence_status':status,'official':True})
    assert classify_event(value)==set()


def test_future_title_and_category_do_not_classify():
    value=event()
    value['reports'].append({'id':'future','title':'TEST armed conflict',
        'category':'Migration','future_dated':True,'official':True})
    assert classify_event(value)==set()


def test_cached_event_headline_and_category_do_not_reintroduce_old_claim():
    value=event()
    value.update(title='TEST armed conflict',recap='TEST refugees displaced',category='Conflict')
    assert classify_event(value)==set()


def test_only_inactive_sources_cannot_fall_back_to_cached_event_caption():
    value=event()
    value.update(title='TEST armed conflict',category='Conflict',independent_origins=['a','b'])
    value['reports'][0]['evidence_status']='retracted'
    assert classify_event(value)==set()


def test_active_report_category_preserved_and_inputs_unchanged():
    value=event()
    value['reports'][0]['category']='Migration'
    original=deepcopy(value)
    assert classify_event(value)=={'migration'}
    assert value==original


def test_non_report_entries_never_restore_cached_caption():
    value=event()
    value['title']='TEST armed conflict'
    value['reports'].extend([None,'armed conflict',[],42])
    assert classify_event(value)==set()


def test_compact_legacy_report_flags_retain_existing_caption_support():
    value={'status':'active','title':'TEST armed conflict','category':'News',
        'reports':[{'official':True,'published_at':'2026-11-10T17:00:00Z'}]}
    assert classify_event(value)=={'conflict'}
