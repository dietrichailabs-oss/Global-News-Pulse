"""Independent NWS affected-zone adversarial tests for frozen PR57 production.

Synthetic fixtures, real Collector / SQLite Store / map helpers, httpx MockTransport.
These tests do not imply the owner's historical Alaska alert was captured or played.
"""
from __future__ import annotations

import copy
import socket
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from global_pulse.core import Store
from global_pulse.map_evidence import event_areas, wrapped_polygons
from global_pulse.nws_zone_resolver import ZoneResolver
from global_pulse.sources import Collector, load_catalog

UTC = timezone.utc
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
ZONE = "https://api.weather.gov/zones/marine/PKZ801"
ZONE2 = "https://api.weather.gov/zones/marine/PKZ802"
SHAPE = {
    "type": "Polygon",
    "coordinates": [[[179, 68], [-179, 68], [-179, 70], [179, 70], [179, 68]]],
}


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.t += duration


@pytest.fixture(autouse=True)
def deny_real_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("QA network access is forbidden")
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def factory_for(handler):
    seen = []
    def wrapped(request):
        seen.append(str(request.url))
        return handler(request)
    return (lambda **kw: httpx.Client(transport=httpx.MockTransport(wrapped), **kw)), seen


def resolver():
    c = Clock()
    return ZoneResolver(clock=c, sleep=c.sleep, now=lambda: NOW), c


def zone_feature(url=ZONE, geometry=None):
    return {
        "type": "Feature", "id": url,
        "properties": {"id": url.rsplit("/", 1)[-1]},
        "geometry": copy.deepcopy(SHAPE if geometry is None else geometry),
    }


def report(**kw):
    r = {
        "id": "qa-warning", "source_id": "nws", "official": True,
        "cap_message_type": "Alert", "published_at": "2026-11-11T08:00:00Z",
        "expires_at": "2026-11-11T12:00:00Z", "ends_at": "2026-11-11T14:00:00Z",
        "affected_zones": [ZONE], "region": "Synthetic Arctic offshore warning",
    }
    r.update(kw)
    return r


def alert_feature(*, affected=None, ugc=None):
    props = {
        "id": "https://api.weather.gov/alerts/qa-ugc-only",
        "status": "Actual", "messageType": "Alert",
        "headline": "Synthetic Alaska offshore freezing spray warning",
        "event": "Heavy Freezing Spray Warning", "severity": "Severe",
        "sent": "2026-11-11T08:00:00Z",
        "expires": "2026-11-11T12:00:00Z",
        "ends": "2026-11-11T14:00:00Z",
        "areaDesc": "Synthetic Arctic Offshore",
        "description": "QA synthetic fixture only",
        "geocode": {"UGC": ugc or ["PKZ801"]},
    }
    if affected is not None:
        props["affectedZones"] = affected
    return {
        "features": [{
            "id": "https://api.weather.gov/alerts/qa-ugc-only",
            "geometry": None, "properties": props,
        }]
    }


def test_zone_only_ugc_geocodes_resolve_official_area_through_collector(tmp_path):
    """NWS UGC is an official affected-zone reference, not a made-up centroid.

    Real NWS alert records may carry marine UGC geocodes without an
    affectedZones URL array; a location-less warning must not disappear.
    """
    source = next(s for s in load_catalog() if s["id"] == "nws")
    def handler(req):
        if str(req.url).endswith("/zones/marine/PKZ801"):
            return httpx.Response(200, json=zone_feature(), request=req)
        return httpx.Response(200, json=alert_feature(), request=req)
    factory, seen = factory_for(handler)
    z, _ = resolver()
    outcome = Collector(source, client_factory=factory, now=lambda: NOW, zone_resolver=z).collect()
    assert outcome["state"]["status"] == "available"
    assert len(outcome["reports"]) == 1
    assert len(seen) == 2, "UGC-only geometry must resolve through the official zone API"
    row = outcome["reports"][0]
    assert row["area_geometry_basis"] == "nws_affected_zones"
    assert row["area_zone_sources"][0]["url"] == ZONE
    assert row["latitude"] is None and row["longitude"] is None
    db = tmp_path / "ugc-only.sqlite3"
    with Store(db, mode="live") as store:
        store.ingest(outcome["reports"], now="2026-11-11T09:00:00Z")
    with Store(db, mode="live") as store:
        saved = store.list_events(map_evidence=True)
        assert len(saved) == 1
        restored = saved[0]["reports"][0]
        assert len(event_areas([restored])) == 1


def test_two_zones_partial_map_keeps_attributed_shape_without_fake_pin():
    z, c = resolver()
    factory, seen = factory_for(
        lambda req: httpx.Response(
            200, json=zone_feature(),
            request=req,
        ) if str(req.url) == ZONE else httpx.Response(404, request=req)
    )
    row = report(affected_zones=[ZONE, ZONE2])
    outcome, stats = z.enrich([row], client_factory=factory)
    assert len(seen) == 2 and stats["partial_alerts"] == 1
    got = outcome[0]
    assert got["area_status"] == "partial_provider_zones"
    assert got["area_zone_sources"] == [{"url": ZONE, "retrieved_at": "2026-11-11T09:00:00Z"}]
    assert "latitude" not in got and "longitude" not in got
    area = event_areas([got])[0]
    assert "partial area" in area["description"]
    assert area["basis"] == "provider_affected_zone_geometry"
    assert len(list(wrapped_polygons(got["area_geometry"]))) >= 2


@pytest.mark.parametrize("failure", ["wrong_type", "wrong_zone", "private_redirect", "malformed_ring", "json_array"])
def test_untrusted_zone_response_never_mints_an_area(failure):
    z, _ = resolver()
    def handler(req):
        if failure == "private_redirect":
            return httpx.Response(307, headers={"Location": "http://127.0.0.1/admin"}, request=req)
        obj = zone_feature()
        if failure == "wrong_type":
            obj["type"] = "FeatureCollection"
        elif failure == "wrong_zone":
            obj["properties"]["id"] = "PKZ999"
        elif failure == "malformed_ring":
            obj["geometry"]["coordinates"][0][0][1] = 99
        elif failure == "json_array":
            obj = [obj]
        return httpx.Response(200, json=obj, request=req)
    factory, seen = factory_for(handler)
    result, stats = z.enrich([report()], client_factory=factory)
    assert seen == [ZONE]
    assert "area_geometry" not in result[0]
    assert stats["lookup_failures"] <= 1
    assert not z.lock.locked()


def test_provider_cooldown_survives_other_alerts_and_preserves_retry_after():
    z, c = resolver()
    factory, seen = factory_for(
        lambda req: httpx.Response(429, headers={"Retry-After": "7200"}, request=req)
    )
    first, stats = z.enrich([report()], client_factory=factory)
    assert stats["provider_refusals"] == 1 and len(seen) == 1
    assert z.blocked_until >= c.t + 7200
    second, stats2 = z.enrich([report(affected_zones=[ZONE2])], client_factory=factory)
    assert len(seen) == 1
    assert "area_geometry" not in first[0] and "area_geometry" not in second[0]


def test_negative_zone_cache_expires_and_can_recover():
    z, c = resolver()
    attempts = []
    def handler(req):
        attempts.append(str(req.url))
        if len(attempts) == 1:
            return httpx.Response(404, request=req)
        return httpx.Response(200, json=zone_feature(), request=req)
    factory, seen = factory_for(handler)
    first, _ = z.enrich([report()], client_factory=factory)
    second, _ = z.enrich([report()], client_factory=factory)
    assert not first[0].get("area_geometry") and not second[0].get("area_geometry")
    assert len(seen) == 1
    c.t += 86401
    third, _ = z.enrich([report()], client_factory=factory)
    assert len(seen) == 2 and third[0]["area_geometry_basis"] == "nws_affected_zones"


def test_expired_and_future_report_never_lookup_geo_even_if_zone_valid():
    z, _ = resolver()
    factory, seen = factory_for(lambda req: pytest.fail("Must not contact expired or future alert"))
    result, stats = z.enrich(
        [
            report(expires_at="2026-11-11T08:30:00Z"),
            report(published_at="2026-11-11T11:00:00Z"),
            report(cap_message_type="Cancel"),
        ], client_factory=factory
    )
    assert not seen and stats["requests"] == 0
    assert all("area_geometry" not in r for r in result)


def test_existing_real_alert_shape_skips_zone_lookup_without_rewriting_end():
    z, _ = resolver()
    factory, seen = factory_for(lambda req: pytest.fail("Pre-existing polygon takes precedence"))
    row = report(area_geometry=copy.deepcopy(SHAPE), area_geometry_basis="nws_alert_geometry")
    output, stats = z.enrich([row], client_factory=factory)
    assert output[0]["area_geometry"] == SHAPE
    assert output[0]["ends_at"] == "2026-11-11T14:00:00Z"
    assert output[0]["expires_at"] == "2026-11-11T12:00:00Z"
    assert seen == [] and stats["requests"] == 0
