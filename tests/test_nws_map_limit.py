"""Engineering reproduction of independent GP-QA-NWS-CONTEXT-LIMIT-01.

The QA suite at PR71 stays unchanged and independent. This separate focused
Engineering regression uses synthetic NWS envelopes, real SQLite and Store.
No real provider requests or owner alert identity are asserted.
"""
from datetime import datetime, timedelta, timezone

import pytest
import global_pulse.core as core
from global_pulse.core import Store
from global_pulse.sources import load_catalog, parse_nws

NOW = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
SHAPE = {"type": "Polygon", "coordinates": [
    [[-150, 60], [-149, 60], [-149, 61], [-150, 61], [-150, 60]]
]}


def stamp(at):
    return at.isoformat(timespec="seconds").replace("+00:00", "Z")


def warning(identity, *, expiry_minutes=120, effective=None):
    source = next(s for s in load_catalog() if s["id"] == "nws")
    props = {
        "id": "urn:oid:" + identity,
        "@id": "https://api.weather.gov/alerts/urn:oid:" + identity,
        "status": "Actual", "messageType": "Update",
        "sender": "w-nws.webmaster@noaa.gov",
        "headline": "Synthetic map paging " + identity,
        "description": "Engineering local-only warning fixture",
        "event": "Coastal Flood Warning", "severity": "Severe",
        "areaDesc": "Synthetic coastal area",
        "sent": stamp(NOW - timedelta(minutes=10)),
        "expires": stamp(NOW + timedelta(minutes=expiry_minutes)),
        "ends": stamp(NOW + timedelta(hours=3)),
        "references": [{
            "identifier": "urn:oid:missing-" + identity,
            "sender": "w-nws.webmaster@noaa.gov",
            "sent": stamp(NOW - timedelta(hours=1)),
        }],
    }
    if effective is not None:
        props["effective"] = stamp(effective)
    row = parse_nws({"features": [{
        "type": "Feature", "id": props["@id"], "geometry": SHAPE,
        "properties": props,
    }]}, source, stamp(NOW))[0]
    row["event_key"] = "engineering-map-page-" + identity
    return row


@pytest.mark.parametrize("blocker", ["expired", "future-effective"])
def test_newer_ineligible_pending_does_not_consume_one_result(tmp_path, monkeypatch, blocker):
    monkeypatch.setattr(core, "utcnow", lambda: stamp(NOW + timedelta(minutes=10)))
    with Store(tmp_path / "global-pulse.sqlite3", mode="live") as db:
        good = db.ingest([warning("good")], now=stamp(NOW))[0]
        bad = warning("bad", expiry_minutes=5 if blocker == "expired" else 120,
                      effective=NOW + timedelta(hours=1) if blocker == "future-effective" else None)
        newest = db.ingest([bad], now=stamp(NOW + timedelta(minutes=1)))[0]
        assert good["id"] != newest["id"]
        assert good["status"] == newest["status"] == "pending"
        unprojected = db.get_event(good["id"])
        assert [x["id"] for x in db.list_events(map_evidence=True, limit=100)] == [good["id"]]
        assert [x["id"] for x in db.list_events(map_evidence=True, limit=1)] == [good["id"]]
        assert not db.list_events(map_view=True, limit=1)
        assert db.get_event(good["id"]) == unprojected


def test_eligible_warning_beyond_multiple_sql_pages_remains_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "utcnow", lambda: stamp(NOW + timedelta(minutes=10)))
    with Store(tmp_path / "global-pulse.sqlite3", mode="live") as db:
        good = db.ingest([warning("older-valid")], now=stamp(NOW))[0]
        # 70 distinct newer expired updates exceed two 32-item SQLite pages.
        for i in range(70):
            db.ingest([warning(f"newer-expired-{i}", expiry_minutes=5)],
                      now=stamp(NOW + timedelta(minutes=1)))
        shown = db.list_events(map_evidence=True, limit=1)
        assert len(shown) == 1 and shown[0]["id"] == good["id"]
        assert shown[0]["map_history_incomplete"] is True
        assert len(shown[0]["map_areas"]) == 1
        assert not db.list_alerts()


def test_strict_history_and_normal_feed_still_obey_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "utcnow", lambda: stamp(NOW + timedelta(minutes=10)))
    with Store(tmp_path / "global-pulse.sqlite3", mode="live") as db:
        good = db.ingest([warning("valid")], now=stamp(NOW))[0]
        db.ingest([warning("invalid", expiry_minutes=5)],
                  now=stamp(NOW + timedelta(minutes=1)))
        present = db.list_events(map_evidence=True, limit=1)
        past = db.list_events(map_evidence=True, before=stamp(NOW), limit=1)
        assert len(present) == 1 and present[0]["id"] == good["id"]
        assert len(past) == 1 and past[0]["id"] == good["id"]
        assert len(db.list_events(limit=1)) == 1
