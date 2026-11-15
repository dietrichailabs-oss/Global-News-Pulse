"""Publisher-direct Netherlands CBS and South Africa SAnews metadata-only admission."""
from global_pulse.sources import load_catalog, parse_feed

IDS_CBS = ("nl_cbs_news", "nl_cbs_economy", "nl_cbs_health", "nl_cbs_energy")
IDS_SA = ("za_sanews_news", "za_sanews_features")
IDS = IDS_CBS + IDS_SA
STAMP = "2026-11-13T05:59:00Z"


def rows():
    return {r["id"]: r for r in load_catalog()}


def test_source_catalog_contract_and_provenance():
    catalog = rows()
    assert len(catalog) >= 155
    assert {catalog[i]["publisher_origin_id"] for i in IDS_CBS} == {"nl_cbs"}
    assert {catalog[i]["publisher_origin_id"] for i in IDS_SA} == {"sanews"}
    assert not any(sid.startswith("in_pib_") for sid in catalog)
    for sid in IDS:
        r = catalog[sid]
        assert r["enabled"] and r["metadata_only"] and r["official"]
        assert r["adapter"] == "rss" and r["independence"] == "original"
        assert r["access_status"] == "reviewed_public" and r["authentication"] == "None"
        assert r["min_interval"] >= 3600 and r["stale_after_days"] == 30
        assert r["retention_days"] <= 180 and r["license_url"].startswith("https://")
        assert r["feed_documentation"].startswith("https://") and r["attribution"]
        assert r["url"].startswith("https://") and r["article_domains"]
        assert r["country"] in ("Netherlands", "South Africa")


def test_sibling_feeds_share_origin_not_report_identity():
    catalog = rows()
    for siblings, original_url, origin in (
        (IDS_CBS, "https://www.cbs.nl/en-gb/news/2026/46/example", "nl_cbs"),
        (IDS_SA, "https://www.sanews.gov.za/south-africa/news/example", "sanews"),
    ):
        rss = (f'<rss><channel><item><guid>same-news-id</guid><title>Source release</title>'
               f'<link>{original_url}</link><pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate>'
               '<description>Never retain source article body.</description>'
               '<enclosure url="https://invalid.example/photo.jpg"/></item></channel></rss>').encode()
        reports = [parse_feed(rss, catalog[sid], STAMP)[0] for sid in siblings]
        assert len({r["id"] for r in reports}) == len(siblings)
        assert {r["origin_id"] for r in reports} == {origin}
        for report in reports:
            assert report["url"] == report["original_url"] == original_url
            assert report["published_at"] == "2026-11-12T12:00:00Z"
            assert report["summary"] == "" and report["media"] == []
            assert report["country_basis"] == "publisher_coverage"
            assert report["latitude"] is None and report["longitude"] is None
            assert report["attribution"]


def test_unauthorized_redirect_domain_is_rejected_for_each_family():
    bad = (b'<rss><channel><item><title>Out of domain</title>'
           b'<link>https://external.example/false-credit</link>'
           b'<pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>')
    for sid in IDS:
        assert parse_feed(bad, rows()[sid], STAMP) == []


def test_authoritative_publisher_coverage_does_not_imply_event_location():
    catalog = rows()
    for sid in ("nl_cbs_news", "za_sanews_news"):
        host = catalog[sid]["article_domains"][0]
        rss = (f'<rss><channel><item><title>Government statistics update</title>'
               f'<link>https://{host}/news/update</link>'
               '<pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate>'
               '</item></channel></rss>').encode()
        report = parse_feed(rss, catalog[sid], STAMP)[0]
        assert report["country"] == catalog[sid]["country"]
        assert report["country_basis"] == "publisher_coverage"
        assert report["latitude"] is None and report["longitude"] is None
