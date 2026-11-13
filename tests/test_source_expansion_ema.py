"""EMA first-party licensed RSS, publisher-origin and metadata-only regressions."""
from global_pulse.sources import load_catalog, parse_feed

IDS = ("ema_news_releases", "ema_whats_new")
STAMP = "2026-11-13T05:13:00Z"


def rows():
    return {item["id"]: item for item in load_catalog()}


def test_ema_feeds_share_origin_and_have_conservative_rights_controls():
    catalog = rows()
    assert {catalog[k]["publisher_origin_id"] for k in IDS} == {"eu_ema"}
    for identity in IDS:
        row = catalog[identity]
        assert row["enabled"] and row["metadata_only"] and row["official"]
        assert row["independence"] == "original"
        assert row["access_status"] == "reviewed_public"
        assert row["min_interval"] >= 3600
        assert row["stale_after_days"] == 30 and row["retention_days"] <= 180
        assert row["license_url"].startswith("https://")
        assert row["feed_documentation"].startswith("https://")
        assert row["article_domains"] == ["www.ema.europa.eu", "ema.europa.eu"]
        assert row["country"] == "" and row["category"] == "Health"
        assert "advertis" in row["limitation"]
        assert row["attribution"]
    assert "ema_new_human" not in catalog
    assert "ema_withdrawn_applications" not in catalog


def test_ema_preserves_original_publisher_links_timestamps_without_copied_body():
    xml = b'''<rss><channel><item><guid>ema-2026-11-12</guid><title>Regulatory update</title>
    <link>https://www.ema.europa.eu/en/news/test-update</link>
    <pubDate>Thu, 12 Nov 2026 16:20:00 GMT</pubDate>
    <description>Article text is intentionally not stored.</description>
    <enclosure url="https://www.ema.europa.eu/en/media/test.jpg"/>
    </item></channel></rss>'''
    catalog = rows()
    reports = [parse_feed(xml, catalog[k], STAMP)[0] for k in IDS]
    assert len({r["id"] for r in reports}) == 2
    assert {r["origin_id"] for r in reports} == {"eu_ema"}
    for identity, report in zip(IDS, reports):
        assert report["url"] == report["original_url"] == "https://www.ema.europa.eu/en/news/test-update"
        assert report["published_at"] == "2026-11-12T16:20:00Z"
        assert report["summary"] == "" and report["media"] == []
        assert report["country"] == "" and report["country_basis"] == "publisher_coverage"
        assert report["attribution"] == catalog[identity]["attribution"]


def test_reject_external_report_links():
    xml = b'''<rss><channel><item><title>Untrusted external link</title>
    <link>https://outside.example/advertisement</link>
    <pubDate>Thu, 12 Nov 2026 16:20:00 GMT</pubDate>
    </item></channel></rss>'''
    for identity in IDS:
        assert parse_feed(xml, rows()[identity], STAMP) == []
