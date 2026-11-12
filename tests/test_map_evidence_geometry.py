"""Offline geometry/provenance tests. All shapes and messages are inert fixtures."""
from copy import deepcopy
import pytest

from global_pulse.map_evidence import (
    normalize_geometry, wrapped_polygons, normalize_map_fields,
    nws_map_fields, valid_nws_zone, incident_country, event_areas,
)

ALASKA = {"type": "Polygon", "coordinates": [[[-170, 70], [-150, 70], [-150, 76], [-170, 76], [-170, 70]]]}
DATELINE = {"type": "Polygon", "coordinates": [[[170, 65], [-170, 65], [-170, 75], [170, 75], [170, 65]]]}


def test_polygon_copied_without_fabricated_point():
    value = normalize_geometry(ALASKA)
    assert value == ALASKA and value is not ALASKA
    assert "latitude" not in value and "longitude" not in value


@pytest.mark.parametrize("value", [None, {}, {"type": "Point", "coordinates": [-160, 70]},
    {"type": "Polygon", "coordinates": []},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [2, 2], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}])
def test_bad_geometries_rejected(value):
    with pytest.raises(ValueError):
        normalize_geometry(value)


@pytest.mark.parametrize("coordinate", [True, float('nan'), float('inf'), "170", 181])
def test_bad_coordinate_rejected(coordinate):
    value = deepcopy(ALASKA)
    value['coordinates'][0][1][0] = coordinate
    with pytest.raises(ValueError):
        normalize_geometry(value)


def test_point_budget_rejected_before_constructing_large_paths():
    value = {'type': 'Polygon', 'coordinates': [ALASKA['coordinates'][0] * 2000]}
    with pytest.raises(ValueError, match='budget'):
        normalize_geometry(value)


def test_multigeometry_and_holes_survive_dateline_unwrap():
    hole = [[175, 68], [-175, 68], [-175, 72], [175, 72], [175, 68]]
    value = {'type': 'MultiPolygon', 'coordinates': [[DATELINE['coordinates'][0], hole], ALASKA['coordinates']]}
    assert normalize_geometry(value) == value
    copies = list(wrapped_polygons(value))
    assert len(copies) == 3
    for polygon in copies:
        outer = polygon[0]
        assert max(p[0] for p in outer) - min(p[0] for p in outer) <= 20
        for ring in polygon:
            assert ring[0] == ring[-1]
            assert all(abs(a[0] - b[0]) <= 180 for a, b in zip(ring, ring[1:]))


@pytest.mark.parametrize('url', ['http://api.weather.gov/zones/forecast/PKZ859',
    'https://api.weather.gov.evil.example/zones/forecast/PKZ859',
    'https://user:password@api.weather.gov/zones/forecast/PKZ859',
    'https://api.weather.gov/zones/forecast/PKZ859?token=private',
    'https://127.0.0.1/zones/forecast/PKZ859',
    'https://api.weather.gov/../../secrets', 'not-a-url'])
def test_zone_references_are_data_not_arbitrary_request_destinations(url):
    assert not valid_nws_zone(url)


def test_nws_zone_geocode_and_distinct_provider_times_retained():
    fields = nws_map_fields({'geometry': ALASKA}, {
        'affectedZones': ['https://api.weather.gov/zones/forecast/PKZ859', 'https://private.example/'],
        'geocode': {'UGC': ['PKZ859', 'BAD'], 'SAME': ['002001']},
        'onset': '2026-11-10T04:00:00-09:00',
        'ends': '2026-11-11T05:00:00-09:00',
        'effective': '2026-11-10T03:00:00-09:00',
    })
    assert fields['area_geometry'] == ALASKA
    assert fields['affected_zones'] == ['https://api.weather.gov/zones/forecast/PKZ859']
    assert fields['area_geocodes'] == {'UGC': ['PKZ859'], 'SAME': ['002001']}
    assert fields['onset_at'] == '2026-11-10T13:00:00Z'
    assert fields['ends_at'] == '2026-11-11T14:00:00Z'
    assert 'expires_at' not in fields


def test_no_zone_geometry_is_truthfully_unresolved():
    value = nws_map_fields({'geometry': None}, {'affectedZones': ['https://api.weather.gov/zones/forecast/PKZ859']})
    assert value['area_status'] == 'zone_geometry_not_resolved'
    assert 'area_geometry' not in value and 'latitude' not in value
    assert normalize_map_fields(value)['area_status'] == 'zone_geometry_not_resolved'


def test_invalid_shape_does_not_erase_warning_or_turn_into_point():
    value = nws_map_fields({'geometry': {'type': 'Point', 'coordinates': [-160, 70]}}, {})
    assert value['area_status'] == 'invalid_or_unsupported_geometry'
    assert 'area_geometry' not in value
    assert normalize_map_fields(value)['area_status'] == 'invalid_or_unsupported_geometry'


def test_publisher_country_is_never_crisis_country():
    report = {'country': 'United Kingdom', 'source_id': 'fcdo', 'country_basis': 'publisher_coverage'}
    assert not incident_country({'country': 'United Kingdom', 'reports': [report]})


def test_conflicting_incident_countries_remain_ambiguous():
    reports = [{'country': x, 'country_basis': 'provider_incident'} for x in ['Ukraine', 'Poland']]
    assert not incident_country({'country': 'Ukraine', 'reports': reports})


def test_corrected_or_future_country_cannot_lend_location():
    reports = [dict(country='Ukraine', evidence_status='corrected'), dict(country='Poland', future_dated=True)]
    assert not incident_country({'country': 'Ukraine', 'reports': reports})


def test_only_active_official_shapes_are_rendered():
    report = {'id': 'fixture', 'official': True, 'area_geometry': ALASKA, 'url': 'https://example.org/fixture'}
    assert len(event_areas([report])) == 1
    for extra in ({'official': False}, {'future_dated': True}, {'evidence_status': 'expired'}, {'evidence_status': 'corrected'}):
        assert not event_areas([dict(report, **extra)])
