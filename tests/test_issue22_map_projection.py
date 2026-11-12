"""Regressions for compact-map evidence loss and malformed geographic metadata."""
from datetime import datetime, timezone
import pytest
from global_pulse.core import Store
from global_pulse.map_evidence import normalize_geometry, normalize_map_fields, incident_country


def test_map_projection_has_source_evidence_without_expanding_timelines(tmp_path):
    stamp = datetime.now(timezone.utc).isoformat()
    raw = {'id':'fixture', 'source_id':'fixture', 'publisher':'ISOLATED TEST FIXTURE',
           'title':'TEST armed conflict in Ukraine', 'url':'https://example.org/fixture',
           'published_at':stamp, 'country':'Ukraine', 'country_basis':'provider_incident',
           'category':'Conflict', 'official':True}
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        event = store.ingest([raw], now=stamp)[0]
        projection = store.list_events(map_evidence=True)[0]
        assert projection['reports'][0]['official'] is True
        assert projection['reports'][0]['country'] == 'Ukraine'
        assert 'timeline' not in projection and 'linked_event_histories' not in projection
        assert store.get_event(event['id'])['timeline']
        historical = store.list_events(map_evidence=True, before=stamp)[0]
        assert historical['reports'][0]['country'] == 'Ukraine'
        assert 'timeline' not in historical


def test_unhashable_geometry_type_is_a_controlled_rejection():
    with pytest.raises(ValueError):
        normalize_geometry({'type':[], 'coordinates':[]})


def test_unhashable_optional_metadata_does_not_discard_report():
    record = normalize_map_fields({'country_basis':{}, 'area_status':[]})
    assert record['country_basis'] == 'unresolved'
    assert 'area_geometry' not in record


def test_legacy_compact_region_fallback_is_only_for_a_known_country():
    assert incident_country({'country':'', 'region':'Ukraine', 'reports':[{'official':True}]}) == 'Ukraine'
    assert incident_country({'country':'', 'region':'Europe', 'reports':[{'official':True}]}) == ''
    assert incident_country({'country':'', 'region':'Ukraine', 'reports':[{'source_id':'fcdo','country':''}]}) == ''
