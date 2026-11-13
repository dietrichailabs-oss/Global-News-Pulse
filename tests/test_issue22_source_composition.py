"""Current source composition smoke: bounded reviewed entries and publisher identity.

No network access, live admission or translation inference is performed here.
"""
from global_pulse.sources import load_catalog, make_user_feed, parse_feed
from global_pulse.core import normalize_report


def test_reviewed_source_catalog_coexists_with_fail_closed_user_language():
    catalog = load_catalog()
    assert 49 <= len(catalog) <= 512
    ids={item["id"] for item in catalog}
    assert ids >= {"sec_press","federal_reserve_press","who","un_peace_security",
                   "un_humanitarian_aid","un_health","un_economic_development",
                   "un_migrants_refugees","un_affairs"}
    assert {item.get("publisher_origin_id") for item in catalog if item["id"].startswith("un_")} >= {"un_news"}
    manual = make_user_feed("https://example.org/rss", "Custom feed", validate_dns=False)
    assert manual["language"] == "und"
    assert manual["independence"] == "unknown"


def test_grouped_independence_and_unknown_language_share_actual_rss_parser():
    source = {
        "id": "one", "name": "Test original", "url": "https://www.nass.usda.gov/rss/one.xml",
        "adapter": "rss", "language": "und", "independence": "original",
        "publisher_origin_id": "usda_nass", "allowed_domains": ["www.nass.usda.gov"],
        "article_domains": ["www.nass.usda.gov"], "category": "Economy"
    }
    rss = (b"<rss><channel><item><guid>report1</guid><title>Economic report</title>"
           b"<link>https://www.nass.usda.gov/news/one</link>"
           b"<pubDate>Wed, 11 Nov 2026 19:00:00 GMT</pubDate></item></channel></rss>")
    one = parse_feed(rss, source, "2026-11-11T21:00:00Z")[0]
    two = parse_feed(rss, {**source, "id": "two"}, "2026-11-11T21:00:00Z")[0]
    assert one["origin_id"] == two["origin_id"] == "usda_nass"
    assert one["id"] != two["id"] and one["source_id"] != two["source_id"]
    assert one["language"] == "und" and two["language"] == "und"
    assert one["country_basis"] == "publisher_coverage"
    assert one["latitude"] is None and one["longitude"] is None
    assert one["published_at"] == "2026-11-11T19:00:00Z"


def test_expansion_keeps_historical_who_and_ecb_origin_identity_without_duplicate_polls():
    catalog = {entry["id"]: entry for entry in load_catalog()}
    enabled = [entry for entry in catalog.values() if entry["enabled"]]
    urls = [entry["url"] for entry in enabled]
    assert len(urls) == len(set(urls)), "One active poller per exact publisher URL"
    assert catalog["ecb"]["enabled"] is False
    assert {catalog[key]["publisher_origin_id"] for key in
            ("ecb", "ecb_press", "ecb_statpress", "ecb_mid")} == {"ecb"}
    assert {catalog[key]["publisher_origin_id"] for key in
            ("who", "who_afro_emergencies")} == {"who_don"}
    rss = (b"<rss><channel><item><guid>ECB-1</guid>"
           b"<title>Publisher policy report</title>"
           b"<link>https://www.ecb.europa.eu/press/item.html</link>"
           b"<pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate>"
           b"</item></channel></rss>")
    historical = parse_feed(rss, catalog["ecb"], "2026-11-13T12:00:00Z")[0]
    expanded = parse_feed(rss, catalog["ecb_press"], "2026-11-13T12:00:00Z")[0]
    assert historical["origin_id"] == expanded["origin_id"] == "ecb"


def test_sanews_family_preserves_unknown_legacy_trust_and_one_configured_publisher_origin():
    catalog = {entry["id"]: entry for entry in load_catalog()}
    assert {catalog[key]["publisher_origin_id"] for key in
            ("sanews", "za_sanews_news", "za_sanews_features")} == {"sanews"}
    assert catalog["sanews"]["independence"] == "unknown"
    assert catalog["za_sanews_news"]["independence"] == "original"
    assert catalog["za_sanews_features"]["independence"] == "original"
    rss = (b"<rss><channel><item><guid>ZA-1</guid>"
           b"<title>Government update</title>"
           b"<link>https://www.sanews.gov.za/south-africa/government-update</link>"
           b"<pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate>"
           b"</item></channel></rss>")
    legacy = parse_feed(rss, catalog["sanews"], "2026-11-13T12:00:00Z")[0]
    expanded = parse_feed(rss, catalog["za_sanews_news"], "2026-11-13T12:00:00Z")[0]
    assert legacy["origin_id"] == ""
    assert expanded["origin_id"] == "sanews"


def test_metadata_only_embedded_media_is_rejected_at_parser_and_store_boundaries():
    source = next(row for row in load_catalog() if row["id"] == "fed_monetary")
    rss = (b"<rss><channel><item><guid>f1</guid>"
           b"<title>Policy publication</title>"
           b"<link>https://www.federalreserve.gov/newsevents/pressreleases/test.htm</link>"
           b"<pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate>"
           b"<videoid>abcdefghijk</videoid></item></channel></rss>")
    report = parse_feed(rss, source, "2026-11-13T12:00:00Z")[0]
    assert report["metadata_only"] is True
    assert report["media"] == []
    assert normalize_report(report, "2026-11-13T12:00:00Z")["media"] == []
    # An alternate parser or already-cached report must not sneak media
    # around the RSS parser's metadata-only policy during normalization.
    injected = {**report, "media": [{"type": "youtube",
                 "url": "https://www.youtube.com/watch?v=abcdefghijk",
                 "title": "unapproved embedded media"}]}
    assert normalize_report(injected, "2026-11-13T12:00:00Z")["media"] == []
    # Do not block an explicitly non-metadata-only feed by accident.
    rich_source = {**source, "metadata_only": False}
    rich = parse_feed(rss, rich_source, "2026-11-13T12:00:00Z")[0]
    assert len(rich["media"]) == 1
    assert len(normalize_report(rich, "2026-11-13T12:00:00Z")["media"]) == 1
