"""Germany Destatis / France DILA metadata-only source admission regressions.

The fixtures are synthetic and never store copied publisher article content.
"""
from copy import deepcopy

from global_pulse.sources import load_catalog, parse_feed

STAMP = "2026-11-13T03:05:00Z"


def catalog():
    return {source["id"]: source for source in load_catalog()}


def test_germany_and_france_are_reviewed_metadata_only_official_feeds():
    sources = catalog()
    german = sources["destatis_press"]
    french = sources["fr_service_public_business"]

    for row in (german, french):
        assert row["enabled"] is True
        assert row["access_status"] == "reviewed_public"
        assert row["adapter"] == "rss"
        assert row["metadata_only"] is True
        assert row["independence"] == "original"
        assert row["official"] is True
        assert row["min_interval"] >= 900
        assert row["url"].startswith("https://")
        assert row["license_url"].startswith("https://")
        assert row["feed_documentation"].startswith("https://")
        assert row["attribution"]
        assert row["article_domains"]
        assert row["stale_after_days"] <= 21

    assert german["publisher_origin_id"] == "destatis"
    assert french["publisher_origin_id"] == "fr_dila"
    assert german["publisher_origin_id"] != french["publisher_origin_id"]
    assert german["language"] == "de" and german["country"] == "Germany"
    assert french["language"] == "fr" and french["country"] == "France"


def test_destatis_parser_preserves_origin_and_original_link_without_body_or_media():
    source = catalog()["destatis_press"]
    xml = b'''<?xml version="1.0"?><rss><channel><item>
    <guid>destatis-2026-11-12</guid>
    <title>Amtliche Statistik: neue Ergebnisse</title>
    <link>https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/11/example.html</link>
    <pubDate>Thu, 12 Nov 2026 08:00:00 +0100</pubDate>
    <description>Do not retain this description or any article text.</description>
    </item></channel></rss>'''
    reports = parse_feed(xml, source, STAMP)
    assert len(reports) == 1
    report = reports[0]
    assert report["title"] == "Amtliche Statistik: neue Ergebnisse"
    assert report["url"] == "https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/11/example.html"
    assert report["published_at"] == "2026-11-12T07:00:00Z"
    assert report["origin_id"] == "destatis"
    assert report["summary"] == "" and report["media"] == []
    assert report["metadata_only"] is True
    assert report["attribution"] == source["attribution"]
    assert report["country_basis"] == "publisher_coverage"


def test_dila_parser_preserves_origin_and_original_link_without_body_or_media():
    source = catalog()["fr_service_public_business"]
    xml = b'''<?xml version="1.0"?><rss><channel><item>
    <guid>fr-dila-2026-11-04</guid>
    <title>Information pour les entreprises</title>
    <link>https://entreprendre.service-public.gouv.fr/actualites/A00000</link>
    <pubDate>Wed, 04 Nov 2026 23:00:00 GMT</pubDate>
    <description>Do not retain or mirror this summary.</description>
    </item></channel></rss>'''
    reports = parse_feed(xml, source, STAMP)
    assert len(reports) == 1
    report = reports[0]
    assert report["title"] == "Information pour les entreprises"
    assert report["url"] == "https://entreprendre.service-public.gouv.fr/actualites/A00000"
    assert report["published_at"] == "2026-11-04T23:00:00Z"
    assert report["origin_id"] == "fr_dila"
    assert report["summary"] == "" and report["media"] == []
    assert report["metadata_only"] is True
    assert report["attribution"] == source["attribution"]
    assert report["country_basis"] == "publisher_coverage"


def test_sibling_feeds_from_same_publisher_cannot_create_independent_origins():
    source = catalog()["fr_service_public_business"]
    sibling = deepcopy(source)
    sibling["id"] = "fr_service_public_business_sibling"
    sibling["url"] = "https://www.service-public.gouv.fr/abonnements/rss/other.rss"
    xml = b'''<rss><channel><item><guid>same-claim</guid><title>Same event</title>
    <link>https://www.service-public.gouv.fr/particuliers/actualites/A00001</link>
    <pubDate>Wed, 04 Nov 2026 23:00:00 GMT</pubDate>
    </item></channel></rss>'''
    first = parse_feed(xml, source, STAMP)[0]
    second = parse_feed(xml, sibling, STAMP)[0]
    assert first["id"] != second["id"]
    assert first["origin_id"] == second["origin_id"] == "fr_dila"
    assert not first["summary"] and not second["summary"]
