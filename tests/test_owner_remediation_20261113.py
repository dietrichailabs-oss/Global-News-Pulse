"""Owner physical-test remediation regressions (2026-11-13).

Offline fixtures only. These tests verify source contracts, conservative country
attribution, dated economic map coverage, and do not establish live provider
availability or independent QA.
"""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import httpx
import pytest
from PySide6.QtWidgets import QApplication

from global_pulse.map_evidence import incident_country
from global_pulse.map_widget import WorldMap
from global_pulse.sources import Collector,load_catalog,parse_who_don,parse_worldbank

STAMP="2026-11-13T01:00:00Z"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_catalog_adds_real_health_humanitarian_government_economy_coverage():
    catalog={row["id"]:row for row in load_catalog()}
    assert catalog["who"]["enabled"]
    assert catalog["who"]["adapter"]=="who_don"
    assert catalog["who"]["metadata_only"]
    assert "/api/news/diseaseoutbreaknews" in catalog["who"]["url"]

    expected={
        "un_peace_security":"News",
        "un_humanitarian_aid":"Humanitarian",
        "un_health":"Health",
        "un_economic_development":"Economy",
        "un_migrants_refugees":"Humanitarian",
        "un_affairs":"Government",
    }
    for identity,category in expected.items():
        row=catalog[identity]
        assert row["enabled"]
        assert row["category"]==category
        assert row["publisher_origin_id"]=="un_news"
        assert row["metadata_only"] is True

    for identity in ("wb_inflation","wb_unemployment","wb_gdp"):
        assert "/country/all/indicator/" in catalog[identity]["url"]
        assert "mrv=3" in catalog[identity]["url"]


def test_who_don_parser_retains_only_bounded_metadata_and_country_text():
    source=next(row for row in load_catalog() if row["id"]=="who")
    payload={"value":[{
        "Id":"11111111-1111-1111-1111-111111111111",
        "DonId":"2026-DON999",
        "PublicationDateAndTime":"2026-11-12T12:00:00Z",
        "ItemDefaultUrl":"/emergencies/disease-outbreak-news/item/2026-DON999",
        "Title":"Dengue - Iran",
        "Summary":"WHO reports an outbreak in Iran.",
        "Overview":"<p>"+"full narrative "*500+"</p>",
        "LastModified":"2026-11-12T13:00:00Z",
    }]}
    reports=parse_who_don(payload,source,STAMP)
    assert len(reports)==1
    report=reports[0]
    assert report["title"]=="Dengue - Iran"
    assert report["summary"]=="WHO reports an outbreak in Iran."
    assert report["metadata_only"] is True
    assert report["official"] is True
    assert report["origin_id"]=="who_don"
    assert report["published_at"]=="2026-11-12T12:00:00Z"
    assert "who.int/emergencies/disease-outbreak-news/item/2026-DON999" in report["url"]
    assert "full narrative" not in report["summary"]


def test_who_collector_uses_json_api_contract():
    source=next(row for row in load_catalog() if row["id"]=="who")
    payload={"value":[{
        "Id":"22222222-2222-2222-2222-222222222222",
        "PublicationDateAndTime":"2026-11-12T12:00:00Z",
        "ItemDefaultUrl":"/emergencies/disease-outbreak-news/item/fixture",
        "Title":"Cholera - Ukraine",
        "Summary":"WHO reports an outbreak in Ukraine.",
        "LastModified":"2026-11-12T13:00:00Z",
    }]}
    def factory(**kwargs):
        return httpx.Client(
            transport=httpx.MockTransport(lambda request:httpx.Response(
                200,content=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type":"application/json"}
            )),
            **kwargs,
        )
    result=Collector(source,client_factory=factory).collect()
    assert len(result["reports"])==1
    assert result["state"]["status"] in {"available","stale"}
    assert incident_country({"reports":result["reports"]})=="Ukraine"


def test_worldbank_all_country_parser_rejects_aggregates_but_keeps_real_iso3():
    source=next(row for row in load_catalog() if row["id"]=="wb_gdp")
    payload=[
        {"lastupdated":"2026-11-01"},
        [
            {"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth"},
             "country":{"id":"IR","value":"Iran"},"countryiso3code":"IRN",
             "date":"2025","value":2.1,"unit":""},
            {"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth"},
             "country":{"id":"1W","value":"World"},"countryiso3code":"WLD",
             "date":"2025","value":2.7,"unit":""},
        ],
    ]
    rows=parse_worldbank(payload,source,STAMP)
    assert len(rows)==1
    assert rows[0]["country"]=="Iran"
    assert rows[0]["country_code"]=="IRN"


def _event(title, *, summary="", source_country="France"):
    return {
        "id":"fixture",
        "status":"active",
        "reports":[{
            "id":"r1","source_id":"fixture_source","title":title,"summary":summary,
            "country":source_country,"source_country":source_country,
            "country_basis":"publisher_coverage","evidence_status":"active",
            "published_at":"2026-11-12T12:00:00Z",
            "publication_time_known":True,
        }],
    }


def test_general_map_country_attribution_uses_exactly_one_explicit_source_country():
    assert incident_country(_event("Humanitarian needs rise across Ukraine"))=="Ukraine"
    assert incident_country(_event("Health response expands in Iran"))=="Iran"
    assert incident_country(_event("Iran and Israel exchange statements"))==""
    assert incident_country(_event("Aid reaches South Sudan"))=="South Sudan"
    assert incident_country(_event("Routine ministry update",source_country="Ukraine"))==""


def test_world_map_economy_layer_reads_dated_observations_without_crisis_inference(app):
    world=WorldMap()
    try:
        world.set_events([],observations=[{
            "indicator":"NY.GDP.MKTP.KD.ZG","indicator_name":"GDP growth",
            "country":"Iran","country_code":"IRN","observation_date":"2025",
            "value":2.1,"unit":"annual %",
        }])
        assert "iran" in world.economic_observations
        assert world.economic_observations["iran"]["count"]==1
        assert world.economic_observations["iran"]["latest"]=="2025"
        assert "1 economy countries/1 observations" in world.coverage_summary()

        world.categories={"Health"}
        world._activity_categories=object()
        world._refresh_country_activity()
        assert world.economic_observations=={}
    finally:
        world.close();world.deleteLater();app.processEvents()
