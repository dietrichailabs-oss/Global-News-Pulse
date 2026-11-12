"""Engineering UGC routing plus real Collector/Store/provenance regressions."""
import copy
import socket
import httpx
import pytest
from global_pulse.nws_ugc import ugc_zone_urls, MARINE_PREFIXES, MAX_UGC_REFS
from global_pulse.map_evidence import nws_map_fields, normalize_map_fields, event_areas
from global_pulse.sources import Collector, load_catalog
from global_pulse.core import Store
import test_eng_replay_nws_qa62 as fixtures

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args,**kwargs):raise AssertionError('No live network in UGC regression')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)

@pytest.mark.parametrize('prefix',sorted(MARINE_PREFIXES))
def test_marine_codes_route_without_headline_guessing(prefix):
    code=prefix+'Z801'
    assert ugc_zone_urls({'UGC':[code]},'Unrecognized marine event')==['https://api.weather.gov/zones/marine/'+code]

@pytest.mark.parametrize('code,event,family',[
 ('AKC013','Unrecognized event','county'),('NJC005','Tornado Warning','county'),
 ('AKZ101','Flood Warning','forecast'),('CAZ213','Red Flag Warning','fire'),
 ('CAZ213','Fire Weather Watch','fire'),('CAZ213','Winter Storm Warning','forecast'),
])
def test_explicit_unambiguous_families(code,event,family):
    assert ugc_zone_urls({'UGC':[code]},event)==[f'https://api.weather.gov/zones/{family}/{code}']

@pytest.mark.parametrize('values',[None,True,'PKZ801',{},[],['PKZ000'],['PKZ801-802'],['PKZ８０１'],['pkz801'],[' PKZ801'],['PKZ801\n'],['ZZZ801'],['PKC801'],['ALL'],[7],['PKZ801',{}],['PKZ801','XXZ001'],['https://api.weather.gov/zones/marine/PKZ801']])
def test_invalid_lists_and_neighbors_are_not_partly_promoted(values):
    assert ugc_zone_urls({'UGC':values},'Flood Warning')==[]

@pytest.mark.parametrize('event',['Unknown product','Special Weather Statement',None,True,{},['Red Flag Warning']])
def test_ambiguous_land_zones_stay_unresolved(event):
    assert ugc_zone_urls({'UGC':['CAZ213']},event)==[]


def test_bounds_and_dedup():
    assert ugc_zone_urls({'UGC':['PKZ801','PKZ801','PKZ802']})==[fixtures.ZONE,fixtures.ZONE2]
    codes=[f'PKZ{i:03d}' for i in range(1,129)]
    assert len(ugc_zone_urls({'UGC':codes}))==MAX_UGC_REFS
    assert ugc_zone_urls({'UGC':codes+['PKZ129']})==[]


def test_valid_explicit_affected_zone_precedes_disagreeing_ugc():
    feature=fixtures.alert_feature(affected=[fixtures.ZONE2])['features'][0]
    fields=nws_map_fields(feature,feature['properties'])
    assert fields['affected_zones']==[fixtures.ZONE2]
    assert 'area_zone_reference_basis' not in fields


def test_valid_direct_geometry_precedes_ugc():
    feature=fixtures.alert_feature()['features'][0];feature['geometry']=copy.deepcopy(fixtures.SHAPE)
    fields=nws_map_fields(feature,feature['properties'])
    assert fields['area_geometry']==fixtures.SHAPE and fields['affected_zones']==[]
    assert 'area_zone_reference_basis' not in fields


def test_raw_invalid_ugc_neighbor_cannot_be_sanitized_into_full_coverage():
    feature=fixtures.alert_feature(ugc=['PKZ801','not-a-zone'])['features'][0]
    fields=nws_map_fields(feature,feature['properties'])
    assert fields['area_geocodes']['UGC']==['PKZ801']
    assert fields['affected_zones']==[]

@pytest.mark.parametrize('status,message',[('Test','Alert'),('Exercise','Alert'),('Actual','Cancel')])
def test_nonactive_cap_never_creates_ugc_lookups(status,message):
    feature=fixtures.alert_feature()['features'][0]
    feature['properties'].update(status=status,messageType=message)
    assert nws_map_fields(feature,feature['properties'])['affected_zones']==[]


def test_reference_basis_survives_normalization_and_rejects_mismatch():
    feature=fixtures.alert_feature()['features'][0]
    fields=nws_map_fields(feature,feature['properties'])
    normalized=normalize_map_fields(fields)
    assert normalized['area_zone_reference_basis']=='provider_ugc'
    assert normalized['affected_zones']==[fixtures.ZONE]
    wrong=dict(fields,affected_zones=[fixtures.ZONE2])
    assert 'area_zone_reference_basis' not in normalize_map_fields(wrong)

@pytest.mark.parametrize('code,event,family',[('PKZ801','Heavy Freezing Spray Warning','marine'),('AKC013','Flood Warning','county'),('CAZ213','Red Flag Warning','fire'),('AKZ101','Flood Warning','forecast')])
def test_real_collector_store_and_map_families_preserve_source_dates(tmp_path,code,event,family):
    endpoint=f'https://api.weather.gov/zones/{family}/{code}'
    payload=fixtures.alert_feature(ugc=[code]);payload['features'][0]['properties']['event']=event
    def handler(request):
        return httpx.Response(200,json=fixtures.zone_feature(endpoint) if str(request.url)==endpoint else payload)
    factory,seen=fixtures.factory_for(handler);resolver,_=fixtures.resolver()
    source=next(s for s in load_catalog() if s['id']=='nws')
    outcome=Collector(source,client_factory=factory,now=lambda:fixtures.NOW,zone_resolver=resolver).collect()
    assert len(seen)==2 and seen[-1]==endpoint
    row=outcome['reports'][0]
    assert row['area_zone_reference_basis']=='provider_ugc' and row['area_geocodes']['UGC']==[code]
    assert row['expires_at']=='2026-11-11T12:00:00Z' and row['ends_at']=='2026-11-11T14:00:00Z'
    assert row['latitude'] is None and row['longitude'] is None
    path=tmp_path/'warning.sqlite3'
    with Store(path,mode='live') as db:db.ingest(outcome['reports'],now='2026-11-11T09:00:00Z')
    with Store(path,mode='live') as db:
        saved=db.list_events(map_evidence=True)
        assert len(saved)==1
        assert saved[0]['reports'][0]['area_zone_reference_basis']=='provider_ugc'
        areas=event_areas(saved[0]['reports'])
        assert len(areas)==1 and 'source UGC references' in areas[0]['description']
