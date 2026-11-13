"""Current source composition smoke: 49 reviewed entries plus language/publisher identity.

No network access, live admission or translation inference is performed here.
"""
from global_pulse.sources import load_catalog, make_user_feed, parse_feed


def test_49_source_catalog_coexists_with_fail_closed_user_language():
    catalog = load_catalog()
    assert len(catalog) == 49
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
