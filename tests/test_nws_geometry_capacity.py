"""Actual captured public geometry replay; synthetic warning, controlled HTTP.

No new NWS request, provider uptime or original owner-alert claim. Preserve all
19 polygons/10,094 coordinates; 16,384 is a hard bound, not unlimited admission.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import socket
import time
import tracemalloc
import httpx
import pytest
from global_pulse.core import Store
from global_pulse.sources import Collector, load_catalog
from global_pulse.map_evidence import MAX_AREA_POINTS, normalize_geometry, wrapped_polygons
from global_pulse.nws_zone_resolver import ZoneResolver, MAX_CACHE_BYTES, MAX_REQUESTS, MAX_RESPONSE_BYTES
from test_nws_warning_context import NOW, stamp, update_record

FIXTURE=Path(__file__).with_name('fixtures')/'nws_AKZ322_geometry_20261111.json'
SHA='b0432044a3f018a343ddf7f2237f5bae7da356bdf273b3c5e10d8ec291f78054'
ZONE='https://api.weather.gov/zones/forecast/AKZ322'


def captured():
    raw=FIXTURE.read_bytes()
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()=='5cc14a3ce79fa23b7682d5848fdee9229c515335'
    value=json.loads(raw)
    assert value['source_url']==ZONE
    geometry=value['geometry']
    assert hashlib.sha256(json.dumps(geometry,separators=(',',':'),allow_nan=False).encode()).hexdigest()==SHA
    return geometry


def count(value):
    polygons=[value['coordinates']] if value['type']=='Polygon' else value['coordinates']
    return sum(len(r) for p in polygons for r in p)


def circle(points):
    ring=[[math.cos(2*math.pi*i/(points-1))-150,math.sin(2*math.pi*i/(points-1))+60] for i in range(points-1)]
    ring.append(list(ring[0]))
    return {'type':'Polygon','coordinates':[ring]}

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args,**kwargs):raise AssertionError('No network in captured-geometry replay')
    monkeypatch.setattr(socket,'getaddrinfo',denied);monkeypatch.setattr(socket.socket,'connect',denied)


def test_captured_shape_is_exact_and_all_coordinates_survive():
    geometry=captured();original=copy.deepcopy(geometry)
    assert len(geometry['coordinates'])==19 and count(geometry)==10094
    normalized=normalize_geometry(geometry)
    assert normalized==original and geometry==original
    assert count(normalized)==10094
    wrapped=list(wrapped_polygons(normalized))
    assert len(wrapped)==19 and sum(len(r) for p in wrapped for r in p)==10094


@pytest.mark.parametrize('size',[8192,8193,10094,16384])
def test_bounded_capacity_acceptance(size):
    geometry=circle(size)
    assert count(normalize_geometry(geometry))==size


def test_first_excess_position_rejected_not_truncated():
    assert MAX_AREA_POINTS==16384
    with pytest.raises(ValueError,match='point budget'):
        normalize_geometry(circle(MAX_AREA_POINTS+1))


def test_budget_is_total_across_polygons_not_per_ring():
    polygon=circle(8193)['coordinates']
    with pytest.raises(ValueError,match='point budget'):
        normalize_geometry({'type':'MultiPolygon','coordinates':[polygon,polygon]})


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),181,True,'-150'])
def test_larger_accepted_size_does_not_admit_bad_coordinate(bad):
    geometry=circle(10000);geometry['coordinates'][0][5000][0]=bad
    with pytest.raises(ValueError):normalize_geometry(geometry)


def test_unclosed_holes_and_polygon_count_checks_unchanged():
    geometry=circle(10000);geometry['coordinates'][0][-1][0]+=0.01
    with pytest.raises(ValueError,match='Unclosed'):normalize_geometry(geometry)
    polygon=circle(4)['coordinates']
    with pytest.raises(ValueError,match='polygon count'):
        normalize_geometry({'type':'MultiPolygon','coordinates':[polygon]*65})


def test_normalization_resource_measurement_is_bounded():
    geometry=captured()
    tracemalloc.start();start=time.perf_counter()
    try:
        for _ in range(3):normalize_geometry(geometry)
        current,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    elapsed=time.perf_counter()-start
    print('GP_GEOMETRY_RESOURCE '+json.dumps({'points':10094,'normalizations':3,'seconds':elapsed,'python_peak_bytes':peak}),flush=True)
    assert peak<32*1024*1024
    assert elapsed<10  # Guard pathological growth, not a rendering-FPS claim.


def test_actual_capture_resolver_store_restart_map_pipeline(tmp_path):
    geometry=captured();seen=[]
    def response(request):
        seen.append(str(request.url))
        assert str(request.url)==ZONE
        return httpx.Response(200,json={'type':'Feature','id':ZONE,'properties':{'id':'AKZ322'},'geometry':geometry})
    factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(response),**kwargs)
    resolver=ZoneResolver(now=lambda:NOW)
    raw=update_record(area_geometry=None,affected_zones=[ZONE])
    enriched,stats=resolver.enrich([raw],client_factory=factory)
    assert stats['requests']==1 and stats['resolved_alerts']==1 and stats['lookup_failures']==0
    assert enriched[0]['area_geometry']==geometry
    again,second=resolver.enrich([raw],client_factory=factory)
    assert second['cache_hits']==1 and len(seen)==1
    assert 0<resolver.cache_bytes<MAX_CACHE_BYTES
    assert MAX_REQUESTS==8 and MAX_RESPONSE_BYTES==2*1024*1024
    path=tmp_path/'captured.sqlite3'
    with Store(path,mode='live') as db:
        db.ingest(enriched,now=stamp(NOW))
        assert not db.last_ingest_errors
    with Store(path,mode='live') as db:
        mapped=db.list_events(map_evidence=True)
        assert len(mapped)==1 and mapped[0]['status']=='pending'
        assert mapped[0]['map_history_incomplete']
        assert mapped[0]['map_areas'][0]['geometry']==geometry
        assert mapped[0]['reports'][0]['area_zone_sources'][0]['url']==ZONE
        assert not db.list_alerts()


def test_oversize_still_preserves_underlying_warning(tmp_path):
    geometry=circle(16385)
    factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'type':'Feature','id':ZONE,'properties':{'id':'AKZ322'},'geometry':geometry})),**kwargs)
    raw=update_record(area_geometry=None,affected_zones=[ZONE])
    rows,stats=ZoneResolver(now=lambda:NOW).enrich([raw],client_factory=factory)
    assert len(rows)==1 and rows[0]['id']==raw['id'] and not rows[0].get('area_geometry')
    assert stats['lookup_failures']==1
