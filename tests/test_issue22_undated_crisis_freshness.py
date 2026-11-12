"""Engineering regression: explicitly undated source records cannot paint fresh crisis stripes.

All fixtures are invented and offline. This is not independent QA, real-source
observation, current-event verification, or native-client acceptance.
"""
from datetime import datetime, timezone

from global_pulse.crisis_overlay import build_country_activity, classify_event

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
FRESH = "2026-11-11T14:20:00Z"
OLD = "2026-09-11T14:20:00Z"


def record(identity, title, *, known=True, published=FRESH, updated=None,
           official=True, origin=""):
    item = {
        "id": identity, "source_id": "test-" + identity,
        "country": "Ukraine", "country_basis": "provider_incident",
        "category": "News", "title": title, "summary": title,
        "published_at": published, "publication_time_known": known,
        "official": official, "evidence_status": "active",
    }
    if updated is not None:
        item["source_updated_at"] = updated
    if origin:
        item.update(origin_id=origin, independence="original")
    return item


def source_event(*reports, independent_origins=None):
    return {
        "id": "invented-evidence-only", "status": "active",
        "country": "Ukraine", "country_basis": "provider_incident",
        "category": "News", "title": "Locally cached event heading",
        "published_at": FRESH, "created_at": FRESH, "updated_at": FRESH,
        "reports": list(reports),
        "independent_origins": independent_origins or [],
    }


def activity(event):
    return build_country_activity([event], now=NOW)


def test_unknown_publication_and_absent_source_update_cannot_borrow_event_ingest_time():
    data = source_event(record("undated", "Armed conflict in a fictional fixture", known=False))
    assert classify_event(data) == set()
    assert activity(data) == {}


def test_unknown_publication_with_dated_provider_update_remains_eligible():
    data = source_event(record("dated-update", "Armed conflict in a fictional fixture",
                               known=False, published=FRESH, updated=FRESH))
    assert "conflict" in classify_event(data)
    assert activity(data)["ukraine"]["conflict"] == 1


def test_stale_provider_update_is_not_rejuvenated_by_local_event_timestamp():
    data = source_event(record("stale-update", "Armed conflict in a fictional fixture",
                               known=False, published=FRESH, updated=OLD))
    assert not activity(data)


def test_unknown_date_headline_cannot_lend_topic_to_separate_dated_official_report():
    data = source_event(
        record("routine", "Public meeting minutes released", published=FRESH),
        record("undated-migration", "Refugee displacement crisis", known=False),
    )
    assert classify_event(data) == set()
    assert not activity(data)


def test_undated_origin_cannot_turn_single_dated_nonofficial_report_into_corroboration():
    data = source_event(
        record("first", "Armed conflict", official=False, origin="one"),
        record("undated-second", "Armed conflict", official=False, origin="two", known=False),
        independent_origins=["one", "two"],
    )
    assert not activity(data)


def test_two_dated_origins_remain_eligible_even_if_third_is_undated():
    data = source_event(
        record("first", "Armed conflict", official=False, origin="one"),
        record("second", "Clashes and shelling", official=False, origin="two"),
        record("undated-third", "Some other headline", official=False, origin="three", known=False),
        independent_origins=["one", "two", "three"],
    )
    assert activity(data)["ukraine"]["conflict"] == 1


def test_legacy_compact_reports_without_explicit_unknown_date_flag_keep_prior_semantics():
    original = record("legacy", "Armed conflict in synthetic evidence")
    original.pop("publication_time_known")
    original.pop("published_at")
    data = source_event(original)
    assert activity(data)["ukraine"]["conflict"] == 1
