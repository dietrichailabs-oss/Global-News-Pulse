"""Engineering regression for explicit source-time claims (invented offline fixtures).

Not independent QA, actual crisis observation, or physical Windows 11 evidence.
"""
from datetime import datetime, timezone

from global_pulse.crisis_overlay import build_country_activity, classify_event

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
FRESH = "2026-11-11T14:20:00Z"


def report(identifier, title, *, published=FRESH, known=True, official=True, origin=""):
    value = {
        "id": identifier, "source_id": "fixture-" + identifier,
        "country": "Ukraine", "country_basis": "provider_incident",
        "title": title, "summary": title, "category": "News",
        "publication_time_known": known, "published_at": published,
        "official": official, "evidence_status": "active",
    }
    if origin:
        value["origin_id"] = origin
    return value


def event(*records, origins=None):
    return {
        "id": "invented-event", "status": "active",
        "country": "Ukraine", "country_basis": "provider_incident",
        "title": "Local event caption", "category": "News",
        "published_at": FRESH, "created_at": FRESH,
        "reports": list(records), "independent_origins": origins or [],
    }


def activity(*records, origins=None):
    return build_country_activity([event(*records, origins=origins)], now=NOW)


def test_known_publication_missing_cannot_borrow_store_timestamp():
    bad = report("missing", "Shelling in a fictional report", published=None)
    assert classify_event(event(bad)) == set()
    assert activity(bad) == {}


def test_invalid_known_publication_cannot_borrow_later_page_update():
    bad = report("bad", "Refugee displacement in fictional report", published="invalid")
    bad["source_updated_at"] = FRESH
    assert classify_event(event(bad)) == set()
    assert activity(bad) == {}


def test_missing_date_crisis_cannot_borrow_unrelated_fresh_official_report():
    bad = report("undated", "Armed conflict in fictional report", published="")
    neutral = report("dated", "Routine meeting of fictional council")
    assert classify_event(event(bad, neutral)) == set()
    assert activity(bad, neutral) == {}


def test_missing_dated_origin_cannot_create_false_independent_corroboration():
    credible = report("one", "Fictional clashes and fighting", official=False, origin="source-one")
    bad = report("two", "Fictional shelling", published="", official=False, origin="source-two")
    assert activity(credible, bad, origins=["source-one", "source-two"]) == {}


def test_valid_dated_official_source_still_maps():
    eligible = report("dated", "Fictional shelling with publication evidence")
    assert activity(eligible)["ukraine"]["conflict"] == 1


def test_legacy_source_without_explicit_flag_keeps_historical_behavior():
    legacy = report("legacy", "Fictional shelling in legacy evidence", published=None)
    legacy.pop("publication_time_known")
    assert activity(legacy)["ukraine"]["conflict"] == 1


def test_unknown_publication_with_dated_provider_update_still_maps():
    updated = report("updated", "Fictional armed conflict", known=False, published=None)
    updated["source_updated_at"] = FRESH
    assert activity(updated)["ukraine"]["conflict"] == 1
