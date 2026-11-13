"""Actual Collector/parser/Store/map helpers, mocked bounded NWS transport."""
import copy
import json
from datetime import datetime,timezone
import socket
import httpx
import pytest
from global_pulse.nws_zone_resolver import ZoneResolver,MAX_REQUESTS,MAX_CACHE_ENTRIES
from global_pulse.map_evidence import normalize_map_fields,event_areas,wrapped_polygons
from global_pulse.sources import Collector,load_catalog
from global_pulse.core import Store

NOW=datetime(2026,11,11,9,tzinfo=timezone.utc)
ZONE='https://api.weather.gov/zones/forecast/PKZ801'
OTHER='https://api.weather.gov/zones/forecast/PKZ802'
GEO={'type':'Polygon','coordinates':[[[179,60],[-179,60],[-179,62],[179,62],[179,60]]]}

class Clock:
    def __init__(self):self.value=0.;self.waits=[]
    def __call__(self):return self.value
    def sleep(self,seconds):self.waits.append(seconds);self.value+=seconds

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*a,**kw):raise AssertionError('Offline NWS tests cannot access the network')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)


def report(refs=None,**changes):
    r=dict(id='fixture',source_id='nws',official=True,cap_message_type='Alert',
        published_at='2026-11-11T08:00:00Z',expires_at='2026-11-11T12:00:00Z',
        affected_zones=refs if refs is not None else [ZONE],region='Alaska offshore synthetic area')
    r.update(changes);return r


def zone_payload(url=ZONE,geometry=None):
    return {'id':url,'type':'Feature','properties':{'id':url.rsplit('/',1)[-1]},'geometry':copy.deepcopy(GEO if geometry is None else geometry)}


def transport(handler):
    calls=[]
    def wrapped(req):calls.append(req);return handler(req)
    def factory(**kwargs):return httpx.Client(transport=httpx.MockTransport(wrapped),**kwargs)
    return factory,calls


def resolver():
    clock=Clock();return ZoneResolver(clock=clock,sleep=clock.sleep,now=lambda:NOW),clock


def test_null_alert_geometry_gets_real_zone_polygon_without_invented_point():
    r,clock=resolver();factory,calls=transport(lambda req:httpx.Response(200,json=zone_payload(str(req.url)),request=req))
    original=report();result,stats=r.enrich([original],client_factory=factory)
    assert original==report() and len(calls)==1
    assert result[0]['area_geometry']['type']=='MultiPolygon'
    assert result[0]['area_geometry_basis']=='nws_affected_zones'
    assert 'latitude' not in result[0] and 'longitude' not in result[0]
    assert result[0]['area_zone_sources'][0]['url']==ZONE
    assert stats['unresolved_alerts']==0
    assert len(list(wrapped_polygons(result[0]['area_geometry'])))==2


def test_existing_alert_polygon_wins_without_zone_request():
    r,_=resolver();factory,calls=transport(lambda req:pytest.fail('No lookup for supplied polygon'))
    result,stats=r.enrich([report(area_geometry=GEO)],client_factory=factory)
    assert result[0]['area_geometry']==GEO and not calls

@pytest.mark.parametrize('bad',['http://api.weather.gov/zones/forecast/PKZ801','https://api.weather.gov.evil.example/zones/forecast/PKZ801','https://api.weather.gov/zones/forecast/PKZ801?url=http://127.0.0.1','https://127.0.0.1/zones/forecast/PKZ801','https://api.weather.gov:443/zones/forecast/PKZ801','https://api.weather.gov/zones/forecast/../../alerts'])
def test_zone_urls_cannot_redirect_to_arbitrary_or_local_targets(bad):
    r,_=resolver();factory,calls=transport(lambda req:pytest.fail('Invalid URL must not be requested'))
    result,stats=r.enrich([report([bad])],client_factory=factory)
    assert not calls and 'area_geometry' not in result[0]

@pytest.mark.parametrize('change',[{'cap_message_type':'Cancel'},{'official':False},{'future_dated':True},{'expires_at':'2026-11-11T07:00:00Z'},{'published_at':'2026-11-12T08:00:00Z'}])
def test_cancelled_unofficial_future_expired_alerts_do_not_start_lookups(change):
    r,_=resolver();factory,calls=transport(lambda req:pytest.fail('Ineligible report lookup'))
    r.enrich([report(**change)],client_factory=factory);assert not calls


def test_positive_cache_reused_and_bounded():
    r,clock=resolver();factory,calls=transport(lambda req:httpx.Response(200,json=zone_payload(str(req.url)),request=req))
    r.enrich([report()],client_factory=factory)
    result,stats=r.enrich([report()],client_factory=factory)
    assert len(calls)==1 and stats['cache_hits']==1
    for i in range(MAX_CACHE_ENTRIES+8):r._put(f'key{i}',GEO,NOW.isoformat(),86400)
    assert len(r.cache)<=MAX_CACHE_ENTRIES


def test_lookup_cap_partial_label_and_negative_cache():
    r,clock=resolver();factory,calls=transport(lambda req:httpx.Response(200,json=zone_payload(str(req.url)),request=req))
    refs=[f'https://api.weather.gov/zones/forecast/PKZ{i:03}' for i in range(800,820)]
    out,stats=r.enrich([report(refs)],client_factory=factory)
    assert len(calls)==MAX_REQUESTS and stats['partial_alerts']==1
    normalized=normalize_map_fields(out[0]);out[0].update(normalized)
    area=event_areas(out)[0]
    assert area['basis']=='provider_affected_zone_geometry' and 'partial area' in area['description']
    assert out[0]['area_status']=='partial_provider_zones'
    assert all(wait>=2 for wait in clock.waits)

@pytest.mark.parametrize('status',[401,403,429,451,503])
def test_provider_refusal_cools_whole_zone_origin(status):
    r,clock=resolver();factory,calls=transport(lambda req:httpx.Response(status,headers={'Retry-After':'7200'},request=req))
    out,stats=r.enrich([report([ZONE,OTHER])],client_factory=factory)
    assert len(calls)==1 and stats['provider_refusals']==1
    r.enrich([report([OTHER])],client_factory=factory)
    assert len(calls)==1 and 'area_geometry' not in out[0]
    if status==429:assert r.blocked_until>=7200

@pytest.mark.parametrize('kind',['redirect','wrong_id','missing_geometry','oversize','malformed'])
def test_failed_zone_keeps_alert_and_does_not_retry_loop(kind):
    r,clock=resolver()
    def handler(req):
        if kind=='redirect':return httpx.Response(302,headers={'Location':'https://other.example/'},request=req)
        if kind=='oversize':return httpx.Response(200,headers={'Content-Length':'999999999'},request=req)
        if kind=='malformed':return httpx.Response(200,content=b'not json',request=req)
        payload=zone_payload(OTHER if kind=='wrong_id' else ZONE)
        if kind=='missing_geometry':payload['geometry']=None
        return httpx.Response(200,json=payload,request=req)
    factory,calls=transport(handler)
    out,_=r.enrich([report()],client_factory=factory)
    r.enrich([report()],client_factory=factory)
    assert len(calls)==1 and out[0]['id']=='fixture' and 'area_geometry' not in out[0]


def test_actual_collector_store_reopen_and_map_provenance(tmp_path):
    source=next(s for s in load_catalog() if s['id']=='nws')
    payload={'features':[{'id':'https://api.weather.gov/alerts/fixture','geometry':None,'properties':{
        'id':'https://api.weather.gov/alerts/fixture','status':'Actual','messageType':'Alert',
        'headline':'Alaska offshore warning fixture','event':'Heavy Freezing Spray Warning','severity':'Severe',
        'sent':'2026-11-11T08:00:00Z','expires':'2026-11-11T12:00:00Z','ends':'2026-11-11T14:00:00Z',
        'description':'Synthetic offline NWS fixture','areaDesc':'Alaska offshore','affectedZones':[ZONE]}}]}
    def handler(req):
        return httpx.Response(200,json=zone_payload() if '/zones/' in str(req.url) else payload,request=req)
    factory,calls=transport(handler);r,_=resolver()
    response=Collector(source,client_factory=factory,now=lambda:NOW,zone_resolver=r).collect()
    assert response['state']['status']=='available' and len(calls)==2
    records=response['reports'];assert len(records)==1
    assert records[0]['expires_at']!=records[0]['ends_at']
    path=tmp_path/'fixture.sqlite3';store=Store(path,mode='live')
    try:store.ingest(records,now='2026-11-11T09:00:00Z')
    finally:store.close()
    store=Store(path,mode='live')
    try:
        events=store.list_events(map_evidence=True)
        assert len(events)==1
        restored=events[0]['reports'][0]
        assert restored['area_geometry_basis']=='nws_affected_zones'
        areas=event_areas([restored])
        assert len(areas)==1 and areas[0]['basis']=='provider_affected_zone_geometry'
        assert restored.get('latitude') is None and restored.get('longitude') is None
    finally:store.close()


def test_pending_geometry_does_not_get_stuck_behind_304():
    source=next(s for s in load_catalog() if s['id']=='nws')
    factory,calls=transport(lambda req:httpx.Response(200,json={'features':[]},request=req))
    r,_=resolver()
    result=Collector(source,client_factory=factory,now=lambda:NOW,zone_resolver=r).collect({'etag':'old','last_modified':'yesterday','nws_zones_pending':True})
    assert 'if-none-match' not in calls[0].headers and 'if-modified-since' not in calls[0].headers
    assert result['state']['nws_zones_pending'] is False

@pytest.mark.parametrize('refs', [
    [ZONE, 'https://api.weather.gov.evil.test/zones/marine/PKZ802'],
    [f'https://api.weather.gov/zones/marine/PKZ{i:03d}' for i in range(1, 130)],
])
def test_incomplete_explicit_affected_zones_never_claim_complete_area(tmp_path, refs):
    # Reproduce the actual source -> collector -> stored report path: neither
    # an invalid neighbor nor a reference past the cap can be discarded to
    # make a deceptively complete polygon. UGC cannot override bad explicit refs.
    source=next(s for s in load_catalog() if s['id']=='nws')
    alert_id='https://api.weather.gov/alerts/synthetic-zone-integrity'
    payload={'features':[{'id':alert_id,'geometry':None,'properties':{
        'id':alert_id,'status':'Actual','messageType':'Alert',
        'headline':'Synthetic Alaska offshore warning','event':'Heavy Freezing Spray Warning',
        'severity':'Severe','sent':'2026-11-11T08:00:00Z',
        'expires':'2026-11-11T12:00:00Z','ends':'2026-11-11T14:00:00Z',
        'description':'Synthetic fixture','areaDesc':'Alaska offshore',
        'affectedZones':refs,'geocode':{'UGC':['PKZ801']}}}]}
    def handler(req):
        assert '/zones/' not in str(req.url), 'Partial/unsafe NWS boundary lookup'
        return httpx.Response(200,json=payload,request=req)
    factory,calls=transport(handler)
    r,_=resolver()
    received=Collector(source,client_factory=factory,now=lambda:NOW,zone_resolver=r).collect()
    assert len(calls)==1 and len(received['reports'])==1
    row=received['reports'][0]
    assert row['affected_zones']==[] and row['area_status']=='invalid_zone_references'
    assert not row.get('area_geometry') and row.get('area_zone_reference_basis') is None
    assert row['expires_at']=='2026-11-11T12:00:00Z'
    assert row['ends_at']=='2026-11-11T14:00:00Z'
    path=tmp_path/'zone_integrity.sqlite3'
    with Store(path,mode='live') as db:
        db.ingest(received['reports'],now='2026-11-11T09:00:00Z')
    with Store(path,mode='live') as db:
        saved=db.list_events(map_evidence=True)
        assert len(saved)==1
        stored=saved[0]['reports'][0]
        assert stored['area_status']=='invalid_zone_references'
        assert event_areas([stored])==[]


def test_unsafe_preparsed_zone_input_is_not_partially_resolved():
    r,_=resolver()
    factory,calls=transport(lambda req:pytest.fail('Unsafe provider list must never be requested'))
    out,stats=r.enrich([report([ZONE, 'bad zone'])],client_factory=factory)
    assert not calls and not out[0].get('area_geometry')
    assert out[0]['area_status']=='invalid_zone_references'
    assert stats['unresolved_alerts']==1


def test_original_provider_polygon_still_wins_over_malformed_zone_list():
    from global_pulse.map_evidence import normalize_map_fields, nws_map_fields
    fields=normalize_map_fields({'area_geometry':GEO,'affected_zones':[ZONE,'bad zone']})
    assert fields['area_geometry']==GEO and fields['area_status']=='provider_geometry'
    feature={'geometry':GEO}
    props={'status':'Actual','messageType':'Alert','affectedZones':[ZONE,'bad zone'],
           'geocode':{'UGC':['PKZ801']},'event':'Heavy Freezing Spray Warning'}
    selected=nws_map_fields(feature,props)
    assert selected['area_geometry']==GEO and selected['affected_zones']==[]
    assert 'area_zone_reference_basis' not in selected


@pytest.mark.parametrize('receipts', [
    [],
    [{'url': ZONE, 'retrieved_at': 'not-a-timestamp'}],
    [{'url': OTHER, 'retrieved_at': '2026-11-11T09:00:00Z'}],
    [{'url': 'https://api.weather.gov.evil.test/zones/forecast/PKZ801',
      'retrieved_at': '2026-11-11T09:00:00Z'}],
])
def test_zone_derived_polygon_without_matching_dated_zone_evidence_is_not_direct_geometry(receipts):
    """Do not launder an unattributed zone composite into a provider alert polygon."""
    raw = report([ZONE], area_geometry=GEO,
                 area_geometry_basis='nws_affected_zones', area_zone_sources=receipts)
    normalized = normalize_map_fields(raw)
    assert normalized['affected_zones'] == [ZONE]
    assert normalized['area_status'] == 'zone_geometry_not_resolved'
    assert 'area_geometry' not in normalized
    assert 'area_geometry_basis' not in normalized
    assert event_areas([dict(raw, **normalized, area_geometry=normalized.get('area_geometry'))]) == []


def test_zone_geometry_with_no_zone_refs_cannot_gain_direct_provider_attribution():
    raw = report([], area_geometry=GEO, area_geometry_basis='nws_affected_zones',
                 area_zone_sources=[{'url': ZONE, 'retrieved_at': '2026-11-11T09:00:00Z'}])
    result = normalize_map_fields(raw)
    assert not result['affected_zones'] and 'area_geometry' not in result
    assert result['area_status'] == 'zone_geometry_not_resolved'


def test_valid_dated_zone_receipt_still_admits_true_dateline_geometry():
    raw = report([ZONE], area_geometry=GEO, area_geometry_basis='nws_affected_zones',
                 area_zone_sources=[{'url': ZONE, 'retrieved_at': '2026-11-11T09:00:00Z'}])
    result = normalize_map_fields(raw)
    assert result['area_geometry'] == GEO
    assert result['area_status'] == 'provider_zone_geometry'
    assert result['area_geometry_basis'] == 'nws_affected_zones'
    assert len(list(wrapped_polygons(result['area_geometry']))) == 2


def test_unverified_derived_geometry_fails_closed_through_collector_store_and_map(tmp_path):
    """Synthetic resolver regression: source -> Collector -> persisted SQLite -> map."""
    source = next(s for s in load_catalog() if s['id'] == 'nws')
    alert_id = 'https://api.weather.gov/alerts/synthetic-unattributed-zone'
    payload = {'features': [{'id': alert_id, 'geometry': None, 'properties': {
        'id': alert_id, 'status': 'Actual', 'messageType': 'Alert',
        'headline': 'Synthetic Alaska offshore warning provenance check',
        'event': 'Heavy Freezing Spray Warning', 'severity': 'Severe',
        'sent': '2026-11-11T08:00:00Z',
        'expires': '2026-11-11T12:00:00Z', 'ends': '2026-11-11T14:00:00Z',
        'description': 'Synthetic warning, no actual provider area fetch',
        'areaDesc': 'Synthetic Alaska offshore',
        'affectedZones': [ZONE]}}]}

    class MissingReceiptResolver:
        def enrich(self, rows, *, client_factory=None):
            # Model an incomplete resolver/store handoff; there is no second
            # zone HTTP request and no verified geometry source receipt.
            return [dict(row, area_geometry=copy.deepcopy(GEO),
                         area_geometry_basis='nws_affected_zones',
                         area_zone_sources=[]) for row in rows], {'unresolved_alerts': 1}

    def handler(request):
        assert '/zones/' not in str(request.url)
        return httpx.Response(200, json=payload, request=request)

    factory, calls = transport(handler)
    result = Collector(source, client_factory=factory, now=lambda: NOW,
                       zone_resolver=MissingReceiptResolver()).collect()
    assert result['state']['status'] == 'available' and len(calls) == 1
    assert len(result['reports']) == 1
    assert result['reports'][0]['area_geometry_basis'] == 'nws_affected_zones'
    db_path = tmp_path / 'unverified-zone-provenance.sqlite3'
    with Store(db_path, mode='live') as store:
        stored = store.ingest(result['reports'], now='2026-11-11T09:00:00Z')
        assert stored and not store.last_ingest_errors
    with Store(db_path, mode='live') as store:
        events = store.list_events(limit=50)
        assert len(events) == 1
        report_row = events[0]['reports'][0]
        assert report_row['affected_zones'] == [ZONE]
        assert report_row['area_status'] == 'zone_geometry_not_resolved'
        assert not report_row.get('area_geometry')
        assert report_row['expires_at'] == '2026-11-11T12:00:00Z'
        assert report_row['ends_at'] == '2026-11-11T14:00:00Z'
        assert event_areas([report_row]) == []
        assert all(not e.get('map_areas') for e in store.list_events(map_evidence=True))


@pytest.mark.parametrize('bad_receipts', [
    [],
    [{'url': ZONE, 'retrieved_at': 'not-a-date'}],
    [{'url': OTHER, 'retrieved_at': '2026-11-11T09:00:00Z'}],
    [{'url': 'https://api.weather.gov.evil.test/zones/forecast/PKZ801',
      'retrieved_at': '2026-11-11T09:00:00Z'}],
])
def test_map_renderer_refuses_legacy_unvalidated_zone_composite_without_store_pass(bad_receipts):
    """Direct map projection of an old saved report must enforce provenance too."""
    raw = report([ZONE], area_geometry=GEO, area_geometry_basis='nws_affected_zones',
                 area_zone_sources=bad_receipts)
    original = copy.deepcopy(raw)
    assert event_areas([raw]) == []
    assert raw == original


def test_map_renderer_retains_valid_offshore_zone_and_honest_partial_coverage():
    valid = {'url': ZONE, 'retrieved_at': '2026-11-11T09:00:00Z'}
    raw = report([ZONE, OTHER], area_geometry=GEO,
                 area_geometry_basis='nws_affected_zones',
                 area_zone_sources=[valid])
    areas = event_areas([raw])
    assert len(areas) == 1
    assert areas[0]['basis'] == 'provider_affected_zone_geometry'
    assert '1/2 zones' in areas[0]['description']
    assert 'partial area' in areas[0]['description']
    assert len(list(wrapped_polygons(areas[0]['geometry']))) == 2
    # An invalid neighbor cannot make the one verified zone look complete.
    invalid = dict(raw, affected_zones=[ZONE, 'untrusted zone'])
    assert event_areas([invalid]) == []
    # Actual direct NWS bulletin area does not require fetched zone receipts.
    direct = report([ZONE], area_geometry=GEO)
    assert event_areas([direct])[0]['basis'] == 'provider_alert_geometry'
