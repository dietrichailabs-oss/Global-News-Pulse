"""Engineering regression: crisis country stripes need fresh *topical* source evidence.

All events are invented local fixtures. These tests are not independent QA or
live Iran/Ukraine/health observations and do not establish Windows client UI.
"""
from copy import deepcopy
from datetime import datetime, timezone

from global_pulse.crisis_overlay import build_country_activity, classify_event

NOW = datetime(2026, 11, 11, 15, tzinfo=timezone.utc)
FRESH = "2026-11-11T14:00:00Z"
OLD = "2026-09-01T14:00:00Z"


def report(identifier, title, *, date=FRESH, official=False, origin="", status="active",
           independence="original"):
    return {
        "id": identifier, "source_id": "fixture-" + identifier,
        "title": title, "summary": title, "category": "News",
        "country": "Ukraine", "country_basis": "provider_incident",
        "published_at": date, "publication_time_known": True,
        "origin_id": origin, "independence": independence, "kind": "report",
        "official": official, "evidence_status": status,
    }


def event(*records, origins=None):
    return {
        "id": "inert-fixture", "status": "active",
        "country": "Ukraine", "country_basis": "provider_incident",
        "title": "Historical shelling in fictional example", "category": "Conflict",
        "published_at": FRESH, "created_at": FRESH,
        "reports": list(records),
        "independent_origins": origins if origins is not None else [],
    }


def activity(row):
    return build_country_activity([row], now=NOW)


def test_stale_official_crisis_cannot_borrow_fresh_neutral_official_timestamp():
    old = report("old", "TEST armed conflict and shelling", date=OLD, official=True)
    fresh = report("today", "TEST routine agency meeting", official=True)
    row = event(old, fresh)
    original = deepcopy(row)
    assert activity(row) == {}
    assert row == original


def test_stale_quoted_origin_cannot_corroborate_lone_recent_original():
    old = report("past", "TEST shelling", date=OLD, origin="origin-old")
    recent = report("recent", "TEST armed fighting", origin="origin-new")
    row = event(old, recent, origins=["origin-old", "origin-new"])
    assert activity(row) == {}


def test_retracted_report_origin_cannot_corroborate_current_report():
    withdrawn = report("withdrawn", "TEST missile strike", origin="origin-a", status="retracted")
    recent = report("today", "TEST armed fighting", origin="origin-b")
    row = event(withdrawn, recent, origins=["origin-a", "origin-b"])
    assert classify_event(row) == set()
    assert activity(row) == {}


def test_syndicated_second_origin_is_not_independent():
    original = report("first", "TEST armed clashes", origin="wire")
    syndicated = report("copy", "TEST armed clashes", origin="republisher", independence="syndicated")
    row = event(original, syndicated, origins=["wire", "republisher"])
    assert classify_event(row) == set()
    assert activity(row) == {}


def test_two_recent_original_origins_still_support_current_country_coverage():
    first = report("first", "TEST armed clashes", origin="one")
    second = report("second", "TEST shelling and fighting", origin="two")
    row = event(first, second, origins=["one", "two"])
    assert activity(row)["ukraine"]["conflict"] == 1


def test_current_official_topical_report_survives_stale_neutral_report():
    old = report("old", "TEST routine meeting", date=OLD, official=True)
    fresh = report("new", "TEST armed clashes", official=True)
    assert activity(event(old, fresh))["ukraine"]["conflict"] == 1


def test_only_stale_reports_cannot_use_new_aggregate_store_time():
    old = report("old", "TEST refugees displaced", date=OLD, official=True)
    assert activity(event(old)) == {}


def test_legacy_compact_event_without_per_report_dates_keeps_prior_behavior():
    legacy = event({"id": "legacy", "source_id": "legacy", "title": "TEST armed clashes",
                    "country": "Ukraine", "country_basis": "provider_incident",
                    "category": "Conflict", "official": True})
    assert activity(legacy)["ukraine"]["conflict"] == 1
