"""Cold-archive official updates: area context, never lifecycle/alert promotion."""
from __future__ import annotations
import copy
from datetime import datetime, timedelta, timezone
import socket
import pytest
from global_pulse.core import Store, normalize_report
from global_pulse.sources import parse_nws, load_catalog
from global_pulse.warning_context import current_update_context, project_warning_context, LABEL
from global_pulse.crisis_overlay import build_country_activity

NOW=datetime.now(timezone.utc).replace(microsecond=0)
def stamp(value):return value.isoformat().replace('+00:00','Z')
SHAPE={'type':'Polygon','coordinates':[[[-150,60],[-149,60],[-149,61],[-150,61],[-150,60]]]}

def update_record(**changes):
    source=next(s for s in load_catalog() if s['id']=='nws')
    props={'id':'urn:oid:context-update','@id':'https://api.weather.gov/alerts/urn:oid:context-update',
      'status':'Actual','messageType':'Update','sender':'w-nws.webmaster@noaa.gov',
      'headline':'Synthetic coastal warning update','description':'Synthetic fixture only',
      'event':'Coastal Flood Warning','severity':'Severe','areaDesc':'Synthetic coastal area',
      'sent':stamp(NOW-timedelta(minutes=10)),'expires':stamp(NOW+timedelta(hours=2)),
      'ends':stamp(NOW+timedelta(hours=3)),
      'references':[{'identifier':'urn:oid:missing-prior','sender':'w-nws.webmaster@noaa.gov','sent':stamp(NOW-timedelta(hours=1))}]}
    feature={'type':'Feature','id':props['@id'],'geometry':copy.deepcopy(SHAPE),'properties':props}
    row=parse_nws({'features':[feature]},source,stamp(NOW))[0];row.update(changes)
    return row

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('No network in warning context tests')
    monkeypatch.setattr(socket,'getaddrinfo',denied);monkeypatch.setattr(socket.socket,'connect',denied)


def derived_pending():
    with Store(':memory:',mode='live') as db:
        event=db.ingest([update_record()],now=stamp(NOW))[0]
        assert event['status']=='pending'
        return event


def test_reproduction_pending_history_retained_but_own_current_area_available(tmp_path):
    path=tmp_path/'archive.sqlite3'
    with Store(path,mode='live') as db:
        event=db.ingest([update_record()],now=stamp(NOW))[0]
        assert event['status']=='pending' and event['reports'][0]['lifecycle_resolved'] is False
        original=copy.deepcopy(db.get_event(event['id']))
        saved_rows=[tuple(row) for row in db._conn.execute('SELECT * FROM report_revisions')]
    with Store(path,mode='live') as db:
        assert db.list_events(map_view=True)==[]
        mapped=db.list_events(map_evidence=True)
        assert len(mapped)==1 and mapped[0]['id']==event['id']
        shown=mapped[0]
        assert shown['status']=='pending' and shown['map_history_incomplete'] is True
        assert shown['map_areas'][0]['context_only'] is True
        assert LABEL in shown['map_areas'][0]['description']
        assert shown['map_areas'][0]['geometry']==SHAPE
        assert shown['latitude'] is None and shown['longitude'] is None
        assert db.get_event(event['id'])==original and not db.list_alerts()
        assert [tuple(row) for row in db._conn.execute('SELECT * FROM report_revisions')]==saved_rows
        assert build_country_activity(mapped)=={}


def test_context_is_only_read_projection_not_source_or_history_rewrite():
    event=derived_pending();original=copy.deepcopy(event)
    shown=project_warning_context(event,stamp(NOW))
    assert shown is not event and event==original and shown['status']=='pending'
    assert 'map_history_incomplete' not in event

@pytest.mark.parametrize('key,value',[
 ('cap_message_type','Cancel'),('cap_status','Test'),('official',False),('source_id','custom'),
 ('kind','report'),('status','retracted'),('evidence_status','cancelled'),('evidence_status','superseded'),
 ('future_dated',True),('expired',True),('expiry_invalid',True),('reference_errors',True),
 ('superseded_by','newer'),('unresolved_reference',''),('lifecycle_references',[]),
 ('lifecycle_references',['other-source:id']),('lifecycle_references',True),
 ('expires_at',''),('expires_at','2026-11-11T10:00:00'),('published_at',{}),
 ('area_geometry',None),('source_updated_at',stamp(NOW+timedelta(hours=1))),
 ('effective_at',stamp(NOW+timedelta(hours=1))),('ends_at',stamp(NOW-timedelta(seconds=1))),
])
def test_invalid_or_inactive_reports_do_not_gain_map_context(key,value):
    event=derived_pending();event['reports'][0][key]=value
    assert current_update_context(event['reports'][0],stamp(NOW)) is False
    assert 'map_history_incomplete' not in project_warning_context(event,stamp(NOW))


def test_expiry_and_future_are_checked_at_projection_time_without_new_poll():
    event=derived_pending()
    assert 'map_history_incomplete' not in project_warning_context(event,stamp(NOW+timedelta(hours=2)))
    assert 'map_history_incomplete' not in project_warning_context(event,stamp(NOW-timedelta(hours=1)))


def test_pending_without_shape_does_not_appear_and_search_filters_apply(tmp_path):
    with Store(tmp_path/'a.sqlite3',mode='live') as db:
        db.ingest([update_record()],now=stamp(NOW))
        assert len(db.list_events(query='coastal',map_evidence=True))==1
        assert not db.list_events(query='unrelatedword',map_evidence=True)
        assert not db.list_events(category='Economy',map_evidence=True)
    with Store(tmp_path/'b.sqlite3',mode='live') as db:
        db.ingest([update_record(area_geometry=None)],now=stamp(NOW))
        assert not db.list_events(map_evidence=True)


def test_historical_map_uses_requested_time_not_current_or_future_information(tmp_path):
    with Store(tmp_path/'a.sqlite3',mode='live') as db:
        db.ingest([update_record()],now=stamp(NOW))
        assert not db.list_events(before=stamp(NOW-timedelta(seconds=1)),map_evidence=True)
        shown=db.list_events(before=stamp(NOW),map_evidence=True)
        assert len(shown)==1 and shown[0]['map_history_incomplete']
        assert not db.list_events(before=stamp(NOW+timedelta(hours=3)),map_evidence=True)


def test_zone_partial_context_stays_explicit_and_bounded():
    event=derived_pending();row=event['reports'][0]
    row.update(area_geometry_basis='nws_affected_zones',affected_zones=['a','b'],area_zone_sources=[{'url':'a'}])
    shown=project_warning_context(event,stamp(NOW))
    assert '1/2' in shown['map_areas'][0]['description'] and 'partial area' in shown['map_areas'][0]['description']
    assert 'bulletin expires' in shown['map_areas'][0]['description'] and 'hazard end' in shown['map_areas'][0]['description']


def test_ambiguous_geometry_never_draws():
    event=derived_pending();event['reports'][0]['area_geometry']={'type':'Point','coordinates':[-150,60]}
    assert 'map_history_incomplete' not in project_warning_context(event,stamp(NOW))
