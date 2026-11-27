"""Norway SSB / EU EEA direct RSS metadata-only source admission regression."""
from copy import deepcopy

from global_pulse.sources import load_catalog, parse_feed

STAMP = "2026-11-13T05:08:00Z"
IDS = ("norway_ssb_latest", "norway_ssb_labour", "norway_ssb_energy", "eea_press_releases", "eea_publications")


def catalog():
    return {item["id"]: item for item in load_catalog()}


def test_licensed_direct_feed_configs_are_safe_and_publisher_grouped():
    rows = catalog()
    assert len(rows) >= 147
    assert all(identity in rows for identity in IDS)
    for identity in IDS:
        row = rows[identity]
        assert row["enabled"] is True
        assert row["metadata_only"] is True
        assert row["access_status"] == "reviewed_public"
        assert row["independence"] == "original" and row["official"] is True
        assert row["min_interval"] >= 1800
        assert row["retention_days"] <= 180
        assert row["stale_after_days"] <= 30
        assert row["authentication"] == "None"
        assert row["license_url"].startswith("https://")
        assert row["feed_documentation"].startswith("https://")
        assert row["attribution"] and row["article_domains"] and row["allowed_domains"]
        assert row["url"].startswith("https://")
    assert {rows[k]["publisher_origin_id"] for k in IDS[:3]} == {"norway_ssb"}
    assert {rows[k]["publisher_origin_id"] for k in IDS[3:]} == {"eu_eea"}
    assert rows["norway_ssb_latest"]["country"] == "Norway"
    assert rows["eea_press_releases"]["country"] == ""


def test_ssb_preserves_original_https_link_and_date_without_reprinting_body():
    row = catalog()["norway_ssb_latest"]
    xml = b'''<?xml version="1.0"?><rss><channel><item>
        <guid>ssb-2026-11-12-test</guid><title>Labour market statistics</title>
        <link>https://www.ssb.no/en/arbeid-og-lonn/sysselsetting/statistikk/test</link>
        <pubDate>Thu, 12 Nov 2026 07:00:00 GMT</pubDate>
        <description>Publisher article body must be omitted.</description>
        <enclosure url="https://www.ssb.no/video/test.mp4" type="video/mp4"/>
    </item></channel></rss>'''
    reports = parse_feed(xml, row, STAMP)
    assert len(reports) == 1
    r = reports[0]
    assert r["origin_id"] == "norway_ssb"
    assert r["url"] == r["original_url"] == "https://www.ssb.no/en/arbeid-og-lonn/sysselsetting/statistikk/test"
    assert r["published_at"] == "2026-11-12T07:00:00Z"
    assert r["summary"] == "" and r["media"] == []
    assert r["attribution"] == row["attribution"]
    assert r["country"] == "Norway" and r["country_basis"] == "publisher_coverage"


def test_ssb_siblings_never_count_as_independent():
    rows = catalog()
    rss = b'''<rss><channel><item><guid>same-item</guid><title>Source data</title>
    <link>https://www.ssb.no/en/statbank</link><pubDate>Thu, 12 Nov 2026 07:00:00 GMT</pubDate>
    </item></channel></rss>'''
    reports = [parse_feed(rss, rows[identity], STAMP)[0] for identity in IDS[:3]]
    assert len({r["id"] for r in reports}) == 3
    assert {r["origin_id"] for r in reports} == {"norway_ssb"}


def test_eea_siblings_never_count_as_independent_and_do_not_geolocate():
    rows = catalog()
    rss = b'''<rss><channel><item><guid>same-eea-release</guid><title>Europe climate update</title>
    <link>https://www.eea.europa.eu/en/newsroom/news/climate-update</link>
    <pubDate>Thu, 12 Nov 2026 09:00:00 GMT</pubDate>
    <description>Do not copy this publisher summary</description></item></channel></rss>'''
    reports = [parse_feed(rss, rows[identity], STAMP)[0] for identity in IDS[3:]]
    assert len({r["id"] for r in reports}) == 2
    assert {r["origin_id"] for r in reports} == {"eu_eea"}
    for report in reports:
        assert report["country"] == "" and report["country_basis"] == "publisher_coverage"
        assert report["summary"] == "" and report["media"] == []
        assert report["original_url"] == report["url"]


def test_off_domain_article_link_rejected_even_with_valid_rss_source():
    rows = catalog()
    for identity, valid in (("norway_ssb_latest", "www.ssb.no"), ("eea_press_releases", "www.eea.europa.eu")):
        bad = b'''<rss><channel><item><title>Untrusted redirect</title>
        <link>https://untrusted.example/advertisement</link>
        <pubDate>Thu, 12 Nov 2026 07:00:00 GMT</pubDate></item></channel></rss>'''
        assert parse_feed(bad, rows[identity], STAMP) == []


def test_no_stale_empty_or_paywalled_candidates_added():
    rows = catalog()
    for identity in IDS:
        row = rows[identity]
        assert "paywall" not in row["access"].lower()
        assert row["min_interval"] >= 1800
        assert row["metadata_only"] is True
