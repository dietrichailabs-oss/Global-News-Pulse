from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from global_pulse.core import Store
from global_pulse.crisis_overlay import build_country_activity, classify_event, normalize_country
from global_pulse.map_widget import WorldMap
from global_pulse.sources import gdelt_request_url, load_catalog, parse_feed, parse_gdelt_doc

UTC = timezone.utc
NOW = datetime(2026, 11, 9, 22, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def event(identity, country, title, *, category="News", official=True, report_count=1, updated="2026-11-09T21:00:00Z"):
    reports = [{
        "id": identity + "-r1",
        "title": title,
        "summary": title,
        "category": category,
        "official": official,
    }]
    return {
        "id": identity,
        "country": country,
        "title": title,
        "recap": title,
        "category": category,
        "updated_at": updated,
        "published_at": updated,
        "status": "active",
        "synthetic": False,
        "report_count": report_count,
        "reports": reports,
        "independent_origins": ["one", "two"] if report_count >= 2 else [],
        "verification": "corroborated" if report_count >= 2 else "unverified",
    }


def live_crisis_report(identity, source_id, title, published_at, *, official=False,
                       independence="original", origin_id="", event_key="crisis:qa", country="France"):
    return {
        "id": identity,
        "source_id": source_id,
        "publisher": source_id.replace("_", " ").title(),
        "title": title,
        "url": f"https://example.com/{source_id}/{identity}",
        "retrieved_at": "2026-11-09T22:00:00Z",
        "published_at": published_at,
        "summary": title,
        "language": "en",
        "region": country,
        "country": country,
        "category": "Conflict",
        "kind": "report",
        "origin_id": origin_id,
        "independence": independence,
        "event_key": event_key,
        "severity": "unassessed",
        "claims": {},
        "media": [],
        "official": official,
        "official_scope": "statement",
        "synthetic": False,
        "retention_days": 30,
    }


def test_crisis_overlay_classifies_supported_recent_activity_and_aliases():
    events = [
        event("war", "United States", "Armed conflict fighting continues near border", category="Conflict"),
        event("protest", "France", "Mass protests and civil unrest continue", report_count=2),
        event("migration", "France", "Refugee displacement crisis expands", category="Migration"),
    ]
    activity = build_country_activity(events, now=NOW)
    assert activity[normalize_country("United States of America")]["conflict"] == 1
    assert activity[normalize_country("France")]["unrest"] == 1
    assert activity[normalize_country("France")]["migration"] == 1


def test_crisis_overlay_rejects_generic_humanitarian_as_migration():
    health = event("health", "Kenya", "Cholera response expands after outbreak", category="Humanitarian")
    assert "migration" not in classify_event(health)
    assert not build_country_activity([health], now=NOW)


def test_crisis_overlay_rejects_weak_old_synthetic_and_trade_war_false_positive():
    weak = event("weak", "Japan", "Protest planned", official=False, report_count=1)
    synthetic = event("fake", "Canada", "Armed conflict", category="Conflict")
    synthetic["synthetic"] = True
    old = event("old", "Italy", "Armed conflict", category="Conflict", updated="2026-09-01T00:00:00Z")
    trade = event("trade", "Germany", "Trade war rhetoric grows", category="Economy")
    activity = build_country_activity([weak, synthetic, old, trade], now=NOW)
    assert not activity
    assert classify_event(trade) == set()


def test_store_crisis_freshness_uses_source_time_not_ingest_rebuild_time(tmp_path):
    with Store(tmp_path / "stale-crisis.sqlite3", mode="live") as store:
        old = live_crisis_report(
            "old-war",
            "source_old",
            "Armed conflict fighting continues near border",
            "2026-09-01T12:00:00Z",
            official=True,
        )
        # A later page/source refresh is provenance, not a new publication.
        old["source_updated_at"] = "2026-11-09T21:30:00Z"
        event_row = store.ingest([old], now="2026-11-09T22:00:00Z")[0]
        assert event_row["updated_at"] == "2026-11-09T22:00:00Z"
        assert event_row["reports"][0]["published_at"] == "2026-09-01T12:00:00Z"
        assert not build_country_activity([event_row], now=NOW)


def test_store_crisis_same_origin_or_syndicated_repeats_do_not_corroborate(tmp_path):
    with Store(tmp_path / "same-origin-crisis.sqlite3", mode="live") as store:
        first = live_crisis_report(
            "one",
            "source_a",
            "Armed conflict fighting reported in border district",
            "2026-11-09T20:00:00Z",
            independence="original",
            origin_id="origin-a",
        )
        repeated = live_crisis_report(
            "two",
            "source_copy",
            "Armed conflict fighting reported in border district",
            "2026-11-09T20:05:00Z",
            independence="syndicated",
            origin_id="origin-a",
        )
        event_row = store.ingest([first, repeated], now="2026-11-09T22:00:00Z")[0]
        assert event_row["report_count"] == 2
        assert event_row["independent_origins"] == ["origin-a"]
        assert not build_country_activity([event_row], now=NOW)


def test_store_crisis_two_independent_current_origins_allow_stripe(tmp_path):
    with Store(tmp_path / "independent-crisis.sqlite3", mode="live") as store:
        first = live_crisis_report(
            "one",
            "source_a",
            "Armed conflict fighting reported in border district",
            "2026-11-09T20:00:00Z",
            independence="original",
            origin_id="origin-a",
        )
        second = live_crisis_report(
            "two",
            "source_b",
            "Independent correspondent reports shelling and clashes near the border",
            "2026-11-09T20:04:00Z",
            independence="original",
            origin_id="origin-b",
        )
        event_row = store.ingest([first, second], now="2026-11-09T22:00:00Z")[0]
        assert set(event_row["independent_origins"]) == {"origin-a", "origin-b"}
        activity = build_country_activity([event_row], now=NOW)
        assert activity[normalize_country("France")]["conflict"] == 1


def test_store_crisis_one_current_official_source_allows_stripe(tmp_path):
    with Store(tmp_path / "official-crisis.sqlite3", mode="live") as store:
        official = live_crisis_report(
            "official",
            "official_source",
            "Official notice reports armed conflict fighting in border district",
            "2026-11-09T20:00:00Z",
            official=True,
            independence="unknown",
            origin_id="",
        )
        event_row = store.ingest([official], now="2026-11-09T22:00:00Z")[0]
        activity = build_country_activity([event_row], now=NOW)
        assert activity[normalize_country("France")]["conflict"] == 1


def test_map_crisis_toggle_state_round_trips(app):
    world = WorldMap()
    world.set_events([
        event("war", "France", "Shelling and armed conflict reported", category="Conflict"),
        event("move", "France", "Internally displaced people flee fighting", category="Migration"),
    ])
    # One conflict fixture plus a displacement event explicitly fleeing fighting
    # means both crisis dimensions are present; overlays are intentionally composable.
    assert world.country_activity_for("France")["conflict"] == 2
    assert world.country_activity_for("France")["migration"] == 1
    world.set_crisis_layer("unrest", False)
    world.set_crisis_overlay_enabled(False)
    state = world.view_state()

    restored = WorldMap()
    restored.restore_view(state)
    assert not restored.crisis_overlay_enabled
    assert not restored.crisis_layers["unrest"]
    assert restored.crisis_layers["conflict"]
    with pytest.raises(ValueError):
        restored.set_crisis_layer("invented", True)
    world.close()
    restored.close()


def test_gdelt_catalog_is_enabled_metadata_only_world_press():
    source = next(item for item in load_catalog() if item["id"] == "gdelt_world_press")
    assert source["enabled"]
    assert source["adapter"] == "gdelt_doc"
    assert source["metadata_only"]
    assert source["allowed_domains"] == ["api.gdeltproject.org"]
    assert source["country_batch_size"] == 8


def test_gdelt_country_rotation_is_bounded_and_persistent():
    source = {
        "url": "https://api.gdeltproject.org/api/v2/doc/doc",
        "countries": ["France", "Germany", "Japan", "Canada", "Brazil"],
        "country_batch_size": 2,
        "max_records": 75,
        "timespan": "6h",
    }
    url1, cursor1, batch1 = gdelt_request_url(source, {})
    assert batch1 == ["France", "Germany"]
    assert cursor1 == 2
    assert "sourcecountry%3Afrance" in url1
    assert "sourcecountry%3Agermany" in url1
    assert "maxrecords=75" in url1

    url2, cursor2, batch2 = gdelt_request_url(source, {"country_cursor": cursor1})
    assert batch2 == ["Japan", "Canada"]
    assert cursor2 == 4
    assert url2 != url1

    _, cursor3, batch3 = gdelt_request_url(source, {"country_cursor": cursor2})
    assert batch3 == ["Brazil", "France"]
    assert cursor3 == 1


def test_gdelt_parser_keeps_only_original_link_metadata_and_dedupes():
    source = {
        "id": "gdelt_world_press",
        "name": "GDELT World Press Discovery",
        "url": "https://api.gdeltproject.org/api/v2/doc/doc",
        "category": "News",
        "region": "Global",
        "country": "",
        "language": "und",
        "retention_days": 30,
        "license": "metadata only",
        "attribution": "GDELT + publisher",
        "independence": "unknown",
        "official": False,
    }
    payload = {
        "articles": [
            {
                "url": "https://example.fr/story?id=1&utm_source=test",
                "title": "Local headline",
                "seendate": "20261109T210000Z",
                "domain": "example.fr",
                "language": "French",
                "sourcecountry": "France",
                "body": "This body must never be copied",
            },
            {
                "url": "https://example.fr/story?id=1&utm_source=other",
                "title": "Duplicate local headline",
                "seendate": "20261109T210100Z",
                "domain": "example.fr",
                "language": "French",
                "sourcecountry": "France",
            },
            {
                "url": "http://insecure.example/story",
                "title": "HTTP entry must be rejected",
                "seendate": "20261109T210200Z",
                "domain": "insecure.example",
                "language": "English",
                "sourcecountry": "United States",
            },
        ]
    }
    reports = parse_gdelt_doc(payload, source, "2026-11-09T21:05:00Z")
    assert len(reports) == 1
    report = reports[0]
    assert report["publisher"] == "example.fr"
    assert report["source_country"] == "France"
    assert report["country"] == ""
    assert report["metadata_only"]
    assert report["summary"].startswith("World-press discovery metadata")
    assert "body" not in report
    assert report["published_at"] == "2026-11-09T21:00:00Z"
    assert report["url"] == "https://example.fr/story?id=1"


def test_gdelt_source_country_survives_store_without_becoming_event_country(tmp_path):
    source = {
        "id": "gdelt_world_press",
        "name": "GDELT World Press Discovery",
        "url": "https://api.gdeltproject.org/api/v2/doc/doc",
        "category": "News",
        "region": "Global",
        "country": "",
        "language": "und",
        "retention_days": 30,
        "license": "metadata only",
        "attribution": "GDELT + publisher",
        "independence": "unknown",
        "official": False,
        "metadata_only": True,
    }
    payload = {
        "articles": [{
            "url": "https://example.fr/world/story?id=42",
            "title": "French outlet reports world event",
            "seendate": "20261109T210000Z",
            "domain": "example.fr",
            "language": "French",
            "sourcecountry": "France",
        }]
    }
    parsed = parse_gdelt_doc(payload, source, "2026-11-09T21:05:00Z")
    assert parsed[0]["source_country"] == "France"
    assert parsed[0]["country"] == ""

    with Store(tmp_path / "gdelt-provenance.sqlite3", mode="live") as store:
        event_row = store.ingest(parsed, now="2026-11-09T22:00:00Z")[0]
        saved = event_row["reports"][0]
        assert saved["source_country"] == "France"
        assert saved["metadata_only"] is True
        assert saved["country"] == ""
        assert event_row["country"] == ""


def test_direct_global_reporting_feeds_are_reviewed_and_metadata_first():
    catalog = {item["id"]: item for item in load_catalog()}
    expected = {
        "un_news",
        "rferl_news",
        "rfa_english",
        "crisisgroup_global",
        "msf_global",
        "africanews_rss",
        "euronews_rss",
        "gdelt_world_press",
        "who_afro_emergencies",
    }
    assert expected <= set(catalog)
    for identity in expected:
        source = catalog[identity]
        assert source["enabled"]
        assert source["access_status"] == "reviewed_public"
        assert source.get("metadata_only")
        assert source["url"].startswith("https://")
        assert source.get("attribution")
        assert source.get("license")
    assert catalog["rfa_english"]["attribution"] == "RFA News Headlines"
    assert catalog["crisisgroup_global"]["category"] == "News"
    assert catalog["msf_global"]["category"] == "Humanitarian"


def test_metadata_only_rss_discards_feed_summary_body():
    source = {
        "id": "fixture_feed",
        "name": "Fixture feed",
        "url": "https://example.org/feed.xml",
        "adapter": "rss",
        "category": "News",
        "region": "Global",
        "country": "",
        "language": "en",
        "retention_days": 30,
        "license": "fixture",
        "attribution": "Fixture",
        "independence": "original",
        "official": False,
        "metadata_only": True,
        "article_domains": ["example.org"],
    }
    xml = b"""<?xml version="1.0"?><rss><channel><item>
      <title>Fixture headline</title>
      <link>https://example.org/story</link>
      <guid>story-1</guid>
      <pubDate>Mon, 09 Nov 2026 21:00:00 GMT</pubDate>
      <description>This intentionally resembles a full copyrighted article body and must not be stored.</description>
    </item></channel></rss>"""
    reports = parse_feed(xml, source, "2026-11-09T21:05:00Z")
    assert len(reports) == 1
    assert reports[0]["metadata_only"]
    assert reports[0]["summary"] == ""
    assert reports[0]["title"] == "Fixture headline"


def test_crisis_overlay_can_use_exact_country_like_region_when_country_missing():
    item = event("region-country", "", "Armed conflict fighting continues", category="Conflict")
    item["region"] = "Ukraine"
    activity = build_country_activity([item], now=NOW)
    assert activity[normalize_country("Ukraine")]["conflict"] == 1
