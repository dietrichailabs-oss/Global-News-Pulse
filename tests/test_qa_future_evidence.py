"""GP-CORE-003 full core/SQLite regressions. No Qt, network or native notifications.

These tests exercise the real normalizer, Store, evidence reconstruction and
alert policy. They are only verified when executed in a complete checkout.
"""
from datetime import datetime, timedelta, timezone

import pytest

from global_pulse.core import Store, alert_reason, notification_view

T0 = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def report(identifier="social", **overrides):
    record = {
        "id": identifier,
        "source_id": identifier,
        "publisher": identifier.upper(),
        "title": "Synthetic bridge disruption at Northhaven",
        "summary": "Synthetic incident record for isolated evidence regression.",
        "url": f"https://{identifier}.example.org/report/{identifier}",
        "published_at": iso(T0),
        "retrieved_at": iso(T0),
        "country": "Norland",
        "region": "Northhaven",
        "category": "Infrastructure",
        "event_key": "gp-qa-future-evidence",
        "severity": "informational",
        "independence": "unknown",
        "origin_id": "",
        "synthetic": True,
        "kind": "social",
    }
    record.update(overrides)
    return record


@pytest.fixture
def store(tmp_path):
    storage = Store(tmp_path / "future-evidence.sqlite3", mode="synthetic")
    try:
        yield storage
    finally:
        storage.close()


def test_future_official_measurement_does_not_verify_current_social_report(store):
    now = iso(T0)
    current = report()
    future = report(
        "official", source_id="official", kind="measurement",
        official=True, official_scope="measurement",
        origin_id="agency", independence="original", severity="critical",
        published_at=iso(T0 + timedelta(hours=24)),
        latitude=39.5, longitude=-74.5, geo_precision="exact",
    )
    event = store.ingest([current, future], now=now)[0]
    assert event["report_count"] == 2
    assert event["verification"] == "unverified"
    assert event["official_attribution"] is False
    assert event["independent_origins"] == []
    assert event["severity"] == "informational"
    assert event["latitude"] is None
    assert event["dimensions"]["evidence_quality"] == "source-attributed reports"
    assert any("Future-dated source records" in reason for reason in event["reasons"])
    assert any(r["id"] == "official" and r["future_dated"] for r in event["reports"])
    assert alert_reason(event) is None


def test_future_second_original_does_not_establish_current_corroboration(store):
    current = report(
        source_id="desk1", official=False, kind="report",
        origin_id="desk1", independence="original",
        claims={"closed": {"value": True, "unit": "", "as_of": iso(T0)}},
    )
    future = report(
        "desk2", kind="report", independence="original", origin_id="desk2",
        published_at=iso(T0 + timedelta(days=2)),
        claims={"closed": {"value": False, "unit": "", "as_of": iso(T0)}},
    )
    event = store.ingest([current, future], now=iso(T0))[0]
    assert event["verification"] == "unverified"
    assert event["independent_origins"] == ["desk1"]
    assert event["contradictions"] == []
    assert event["dimensions"]["source_independence"] == 1


def test_future_only_official_record_is_retainable_not_current_verification(store):
    future = report(
        "future", kind="measurement", official=True, official_scope="measurement",
        severity="high", published_at=iso(T0 + timedelta(days=1)),
        latitude=10, longitude=20, geo_precision="exact",
    )
    event = store.ingest([future], now=iso(T0))[0]
    assert event["report_count"] == 1
    assert event["verification"] == "unverified"
    assert event["severity"] == "unassessed"
    assert event["latitude"] is None
    assert "future-dated" in event["recap"].lower()
    assert event["reports"][0]["future_dated"]
    assert alert_reason(event) is None


@pytest.mark.parametrize("kind,reference", [
    ("correction", "correction_of"),
    ("retraction", "retraction_of"),
])
def test_future_notice_cannot_supersede_current_evidence(store, kind, reference):
    original = report(
        "a", source_id="agency", kind="announcement", official=True,
        severity="high", event_key="same-warning",
    )
    notice = report(
        "b", source_id="agency", kind=kind, official=True,
        severity="informational", event_key="same-warning",
        published_at=iso(T0 + timedelta(days=1)),
        **{reference: "a"},
    )
    event = store.ingest([original, notice], now=iso(T0))[0]
    assert event["status"] == "active"
    assert event["severity"] == "high"
    assert next(r for r in event["reports"] if r["id"] == "a")["evidence_status"] == "active"
    assert event["title"] == original["title"]
    assert not any("correction or retraction" in r.lower() for r in event["reasons"])


def test_repeated_identical_report_reclassifies_after_publication_and_keeps_history(store):
    future = report(
        "measurement", kind="measurement", official=True,
        official_scope="measurement", severity="high",
        published_at=iso(T0 + timedelta(days=1)), origin_id="met-office",
        independence="original",
    )
    initial = store.ingest([future], now=iso(T0))[0]
    assert initial["verification"] == "unverified"
    assert initial["revision"] == 1
    later = iso(T0 + timedelta(days=1, minutes=5))
    event = store.ingest([future], now=later)[0]
    assert event["id"] == initial["id"]
    assert event["revision"] == 2
    assert event["verification"] == "official"
    assert event["reports"][0]["future_dated"] is False
    assert event["changes"][0]["kind"] == "eligibility"
    historical = store.get_event(event["id"], at=iso(T0))
    assert historical["revision"] == 1
    assert historical["verification"] == "unverified"
    assert historical["reports"][0]["future_dated"] is True
    assert store.ingest([future], now=later) == []


def test_future_correction_matures_into_same_event_and_preserves_original(store):
    original = report(
        "a", source_id="agency", kind="announcement", official=True,
        severity="high", event_key="warning",
    )
    notice = report(
        "b", source_id="agency", kind="correction", correction_of="a",
        official=True, severity="informational", event_key="warning",
        published_at=iso(T0 + timedelta(hours=24)),
    )
    before = store.ingest([original, notice], now=iso(T0))[0]
    assert next(r for r in before["reports"] if r["id"] == "a")["evidence_status"] == "active"
    after = store.ingest([notice], now=iso(T0 + timedelta(hours=25)))[0]
    assert after["id"] == before["id"]
    assert after["revision"] == before["revision"] + 1
    assert after["changes"][0]["kind"] == "correction"
    assert next(r for r in after["reports"] if r["id"] == "a")["evidence_status"] == "corrected"
    assert {r["id"] for r in after["reports"]} == {"a", "b"}


@pytest.mark.parametrize("minutes,expected_official", [(9, True), (11, False)])
def test_publication_skew_tolerance_is_bounded(store, minutes, expected_official):
    record = report(
        "official", kind="measurement", official=True, official_scope="measurement",
        severity="moderate", published_at=iso(T0 + timedelta(minutes=minutes)),
    )
    event = store.ingest([record], now=iso(T0))[0]
    assert (event["verification"] == "official") is expected_official
    assert event["reports"][0]["future_dated"] is (not expected_official)


def test_muted_projection_does_not_promote_future_source(store):
    current = report()
    future = report(
        "official", kind="measurement", official=True, official_scope="measurement",
        severity="critical", published_at=iso(T0 + timedelta(days=1)),
    )
    event = store.ingest([current, future], now=iso(T0))[0]
    projected = notification_view(event, ["social"])
    assert projected is not None
    assert projected["verification"] == "unverified"
    assert projected["official_attribution"] is False
    assert projected["severity"] == "unassessed"
    assert alert_reason(projected) is None
