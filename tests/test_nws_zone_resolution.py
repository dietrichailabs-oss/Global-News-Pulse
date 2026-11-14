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



def test_expired_bulletin_with_future_hazard_end_retains_official_area_without_reactivation(tmp_path):
    # The bulletin expires at 08:30, while the publisher explicitly dates the
    # hazard end at 14:00. Keep the sourced area in archived evidence without
    # promoting the expired CAP notice to a current map alert.
    source=next(s for s in load_catalog() if s['id']=='nws')
    payload={'features':[{'id':'https://api.weather.gov/alerts/expired-bulletin-fixture',
        'geometry':None,'properties':{
        'id':'https://api.weather.gov/alerts/expired-bulletin-fixture',
        'status':'Actual','messageType':'Alert',
        'headline':'Synthetic Alaska offshore hazardous spray warning',
        'event':'Heavy Freezing Spray Warning','severity':'Severe',
        'sent':'2026-11-11T08:00:00Z','expires':'2026-11-11T08:30:00Z',
        'ends':'2026-11-11T14:00:00Z','description':'Synthetic offline only',
        'areaDesc':'Alaska offshore test area','affectedZones':[ZONE]}}]}
    def handler(req):
        return httpx.Response(200,json=zone_payload() if '/zones/' in str(req.url) else payload,request=req)
    factory,calls=transport(handler)
    area_resolver,_=resolver()
    collected=Collector(source,client_factory=factory,now=lambda:NOW,zone_resolver=area_resolver).collect()
    assert collected['state']['status']=='available' and len(calls)==2
    reports=collected['reports']
    assert len(reports)==1
    assert reports[0]['expires_at']=='2026-11-11T08:30:00Z'
    assert reports[0]['ends_at']=='2026-11-11T14:00:00Z'
    assert reports[0]['area_geometry_basis']=='nws_affected_zones'
    assert not any(key in reports[0] for key in ('latitude','longitude'))
    path=tmp_path/'expired_offshore.sqlite3'
    store=Store(path,mode='live')
    try: store.ingest(reports,now='2026-11-11T09:00:00Z')
    finally: store.close()
    store=Store(path,mode='live')
    try:
        events=store.list_events()  # Historical archive; map evidence may filter an expired notice.
        assert len(events)==1
        restored=events[0]['reports'][0]
        assert restored['evidence_status']=='expired'
        assert restored['ends_at']=='2026-11-11T14:00:00Z'
        assert restored['expires_at']=='2026-11-11T08:30:00Z'
        assert restored['area_geometry_basis']=='nws_affected_zones'
        assert restored['area_zone_sources'][0]['url']==ZONE
        assert len(list(wrapped_polygons(restored['area_geometry'])))==2
        assert event_areas([restored])==[]  # Historical geometry is not a live alert.
    finally:store.close()


def test_pending_geometry_does_not_get_stuck_behind_304():
    source=next(s for s in load_catalog() if s['id']=='nws')
    factory,calls=transport(lambda req:httpx.Response(200,json={'features':[]},request=req))
    r,_=resolver()
    result=Collector(source,client_factory=factory,now=lambda:NOW,zone_resolver=r).collect({'etag':'old','last_modified':'yesterday','nws_zones_pending':True})
    assert 'if-none-match' not in calls[0].headers and 'if-modified-since' not in calls[0].headers
    assert result['state']['nws_zones_pending'] is False

@pytest.mark.parametrize('length_delta', [-1, 1])
def test_nws_zone_200_length_mismatch_never_admits_partial_transfer(length_delta):
    """Valid JSON with incorrect HTTP framing must not become official map evidence."""
    payload = json.dumps(zone_payload(), separators=(',', ':')).encode()
    claimed = len(payload) + length_delta
    r, _ = resolver()
    factory, calls = transport(lambda req: httpx.Response(
        200, content=payload, headers={'Content-Length': str(claimed)}, request=req))
    result, stats = r.enrich([report()], client_factory=factory)
    assert len(calls) == 1
    assert stats['lookup_failures'] == 1
    assert stats['unresolved_alerts'] == 1
    assert result[0]['affected_zones'] == [ZONE]
    assert 'area_geometry' not in result[0]
    assert event_areas(result) == []



@pytest.mark.parametrize('bad_length', ['not-a-number', '-42', '1, 2'])
def test_nws_zone_malformed_http_length_cannot_become_official_zone_evidence(bad_length):
    """Ambiguous/invalid framing is not accepted as a complete publisher polygon."""
    payload = json.dumps(zone_payload(), separators=(',', ':')).encode()
    r, _ = resolver()
    factory, calls = transport(lambda req: httpx.Response(
        200, content=payload, headers={'Content-Length': bad_length}, request=req))
    result, stats = r.enrich([report()], client_factory=factory)
    assert len(calls) == 1 and stats['lookup_failures'] == 1
    assert result[0]['affected_zones'] == [ZONE]
    assert 'area_geometry' not in result[0]
    assert event_areas(result) == []


def test_nws_zone_matching_200_length_still_admits_valid_offshore_area():
    """Correctly framed official zone transfers keep working with the same parser."""
    payload = json.dumps(zone_payload(), separators=(',', ':')).encode()
    r, _ = resolver()
    factory, calls = transport(lambda req: httpx.Response(
        200, content=payload, headers={'Content-Length': str(len(payload))}, request=req))
    result, stats = r.enrich([report()], client_factory=factory)
    assert len(calls) == 1 and stats['resolved_alerts'] == 1
    assert result[0]['area_zone_sources'][0]['url'] == ZONE
    assert event_areas(result)[0]['basis'] == 'provider_affected_zone_geometry'
    assert len(list(wrapped_polygons(result[0]['area_geometry']))) == 2
