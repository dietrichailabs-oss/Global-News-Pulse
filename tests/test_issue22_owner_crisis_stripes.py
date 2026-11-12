"""Owner-observed zero-stripe regression coverage.

Invented local fixtures only. Country text is evidence only when exactly one
country is explicitly named in eligible source text; publisher country is never
promoted to incident geography.
"""
from datetime import datetime, timezone

from global_pulse.crisis_overlay import build_country_activity, normalize_country

NOW=datetime(2026,11,12,12,tzinfo=timezone.utc)


def report(identity, source, title, *, origin, official=False,
           publisher_country="Germany", category="News"):
    return {
        "id": identity,
        "source_id": source,
        "publisher": source,
        "title": title,
        "summary": title,
        "category": category,
        "country": publisher_country,
        "source_country": publisher_country,
        "country_basis": "publisher_coverage",
        "published_at": "2026-11-12T11:00:00Z",
        "publication_time_known": True,
        "retrieved_at": "2026-11-12T11:05:00Z",
        "origin_id": origin,
        "independence": "original",
        "kind": "report",
        "official": official,
        "evidence_status": "active",
    }


def event(identity, row):
    return {
        "id": identity,
        "status": "active",
        "synthetic": False,
        "title": row["title"],
        "category": row["category"],
        "country": row["country"],
        "country_basis": "publisher_coverage",
        "published_at": row["published_at"],
        "created_at": row["published_at"],
        "reports": [row],
        "independent_origins": [row["origin_id"]],
    }


def test_two_separate_independent_publishers_restore_ukraine_conflict_stripe():
    a=event("a",report("r1","publisher_a","Ukraine reports shelling and fighting near the front",origin="origin-a"))
    b=event("b",report("r2","publisher_b","Fighting and missile strikes continue in Ukraine",origin="origin-b",publisher_country="France"))
    activity=build_country_activity([a,b],now=NOW)
    row=activity[normalize_country("Ukraine")]
    assert row["conflict"]==2
    assert row["basis"]["conflict"]=="cross_event_independent"


def test_single_nonofficial_publisher_still_cannot_create_stripe():
    one=event("one",report("r1","publisher_a","Ukraine reports shelling and fighting near the front",origin="origin-a"))
    assert build_country_activity([one],now=NOW)=={}


def test_same_origin_republished_across_events_does_not_corroborate():
    a=event("a",report("r1","publisher_a","Ukraine reports shelling and fighting",origin="wire"))
    b=event("b",report("r2","publisher_b","Missile strikes reported in Ukraine",origin="wire",publisher_country="France"))
    assert build_country_activity([a,b],now=NOW)=={}


def test_explicit_official_country_text_can_create_stripe_without_publisher_location():
    row=event("official",report(
        "r1","official_source","Ukraine authorities report shelling in border communities",
        origin="",official=True,publisher_country="United States"
    ))
    activity=build_country_activity([row],now=NOW)
    assert activity[normalize_country("Ukraine")]["conflict"]==1
    assert activity[normalize_country("Ukraine")]["basis"]["conflict"]=="official_text_country"


def test_two_country_headline_remains_ambiguous_and_unstriped():
    a=event("a",report("r1","publisher_a","Russia launches missiles into Ukraine",origin="one"))
    b=event("b",report("r2","publisher_b","Russia and Ukraine report fighting",origin="two",publisher_country="France"))
    assert build_country_activity([a,b],now=NOW)=={}


def test_publisher_country_hint_alone_never_creates_unrest_stripe():
    a=event("a",report("r1","publisher_a","Mass protests continue after court ruling",origin="one",publisher_country="France"))
    b=event("b",report("r2","publisher_b","Demonstrators gather for another protest",origin="two",publisher_country="France"))
    assert build_country_activity([a,b],now=NOW)=={}


def test_two_independent_explicit_france_reports_create_unrest_stripe():
    a=event("a",report("r1","publisher_a","Mass protests continue across France",origin="one",publisher_country="Germany"))
    b=event("b",report("r2","publisher_b","Demonstrators in France join nationwide protest",origin="two",publisher_country="United States"))
    activity=build_country_activity([a,b],now=NOW)
    assert activity[normalize_country("France")]["unrest"]==2
    assert activity[normalize_country("France")]["basis"]["unrest"]=="cross_event_independent"


def test_nonmilitary_war_idiom_stays_out_even_with_country_text():
    a=event("a",report("r1","publisher_a","Germany expands its war for talent",origin="one"))
    b=event("b",report("r2","publisher_b","Germany employers intensify war for talent",origin="two",publisher_country="France"))
    assert build_country_activity([a,b],now=NOW)=={}
