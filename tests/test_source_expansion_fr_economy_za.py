"""France economy + South Africa direct RSS metadata-only admission regressions.

Synthetic fixtures, no publisher article body or media copied.
"""
from copy import deepcopy

from global_pulse.sources import load_catalog, parse_feed

STAMP = "2026-11-13T04:00:00Z"
IDS = ("fr_economie_portal", "fr_economie_daj", "za_statssa_news")


def sources():
    return {item["id"]: item for item in load_catalog()}


def test_lawful_direct_sources_are_metadata_only_and_restrict_hosts():
    catalog = sources()
    for identity in IDS:
        row = catalog[identity]
        assert row["enabled"] is True and row["metadata_only"] is True
        assert row["access_status"] == "reviewed_public"
        assert row["independence"] == "original" and row["official"] is True
        assert row["min_interval"] >= 1800
        assert row["stale_after_days"] == 30
        assert row["license_url"].startswith("https://")
        assert row["feed_documentation"].startswith("https://")
        assert row["url"].startswith("https://")
        assert row["attribution"] and row["article_domains"]
    assert catalog["fr_economie_portal"]["publisher_origin_id"] == "fr_economie"
    assert catalog["fr_economie_daj"]["publisher_origin_id"] == "fr_economie"
    assert catalog["za_statssa_news"]["publisher_origin_id"] == "statssa"


def test_france_economy_metadata_link_timestamps_and_body_denial():
    c = sources()
    sample = b'''<?xml version="1.0"?><rss><channel><item>
        <guid>fr-2026-11-12-test</guid><title>Economic policy update</title>
        <link>https://www.economie.gouv.fr/actualites/test</link>
        <pubDate>Thu, 12 Nov 2026 09:59:16 GMT</pubDate>
        <description>Publisher text must not be retained.</description>
        <enclosure url="https://www.economie.gouv.fr/media/video.mp4" />
    </item></channel></rss>'''
    for identity in IDS[:2]:
        reports = parse_feed(sample, c[identity], STAMP)
        assert len(reports) == 1
        item = reports[0]
        assert item["url"] == "https://www.economie.gouv.fr/actualites/test"
        assert item["original_url"] == item["url"]
        assert item["published_at"] == "2026-11-12T09:59:16Z"
        assert item["summary"] == "" and item["media"] == []
        assert item["origin_id"] == "fr_economie"
        assert item["attribution"] == c[identity]["attribution"]
        assert item["country_basis"] == "publisher_coverage"


def test_south_africa_website_does_not_auto_locate_incidents():
    row = sources()["za_statssa_news"]
    sample = b'''<rss><channel><item>
      <guid>za-2026-11-05-test</guid>
      <title>Quarterly economic statistical release</title>
      <link>https://www.statssa.gov.za/?p=18000</link>
      <pubDate>Thu, 05 Nov 2026 11:10:10 GMT</pubDate>
      <description>Never reproduce full news article bodies.</description>
    </item></channel></rss>'''
    reports = parse_feed(sample, row, STAMP)
    assert len(reports) == 1
    item = reports[0]
    assert item["publisher"] == row["name"]
    assert item["origin_id"] == "statssa"
    assert item["country_basis"] == "publisher_coverage"
    assert item["country"] == "South Africa"
    assert item["published_at"] == "2026-11-05T11:10:10Z"
    assert item["url"] == "https://www.statssa.gov.za/?p=18000"
    assert item["summary"] == "" and item["media"] == []


def test_sibling_feed_not_independent_and_cross_domain_link_rejected():
    row = sources()["fr_economie_portal"]
    sibling = deepcopy(row)
    sibling["id"] = "fr_economie_portal_sibling"
    sibling["url"] = "https://www.economie.gouv.fr/daj/rss"
    xml = b'''<rss><channel><item><guid>1</guid>
    <title>Official notice</title><pubDate>Thu, 12 Nov 2026 09:59:16 GMT</pubDate>
    <link>https://www.economie.gouv.fr/actualites/test</link>
    </item></channel></rss>'''
    a, b = parse_feed(xml, row, STAMP)[0], parse_feed(xml, sibling, STAMP)[0]
    assert a["id"] != b["id"]
    assert a["origin_id"] == b["origin_id"] == "fr_economie"
    bad = xml.replace(b"www.economie.gouv.fr/actualites", b"untrusted.example/actualites")
    assert parse_feed(bad, row, STAMP) == []


def test_stale_and_denied_candidates_must_not_be_admitted():
    catalog = sources()
    assert "fr_economie_tracfin" not in catalog
    assert "fr_economie_dgccrf" not in catalog
    assert "fr_economie_tracfin_probe" not in catalog
    assert "fr_economie_dgccrf_probe" not in catalog
