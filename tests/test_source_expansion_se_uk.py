"""2026-11-13 Sweden SCB and UK Met Office rights/provenance admission regression."""
from global_pulse.sources import load_catalog, parse_feed

IDS = ("se_scb_statistics", "uk_metoffice_news")
PUBLISHER = {"se_scb_statistics": "se_scb", "uk_metoffice_news": "uk_metoffice"}
STAMP = "2026-11-13T07:12:00Z"


def rows():
    return {r["id"]: r for r in load_catalog()}


def test_catalog_admission_contract():
    catalog = rows()
    assert len(catalog) >= 157
    for sid in IDS:
        row = catalog[sid]
        assert row["enabled"] and row["metadata_only"] and row["official"]
        assert row["adapter"] == "rss" and row["independence"] == "original"
        assert row["access_status"] == "reviewed_public" and row["authentication"] == "None"
        assert row["publisher_origin_id"] == PUBLISHER[sid]
        assert row["min_interval"] >= 3600
        assert row["stale_after_days"] == 30 and row["retention_days"] <= 180
        assert row["url"].startswith("https://") and row["license_url"].startswith("https://")
        assert row["feed_documentation"].startswith("https://") and row["attribution"]
        assert row["allowed_domains"] and row["article_domains"]
    assert catalog["se_scb_statistics"]["language"] == "sv"
    assert catalog["se_scb_statistics"]["country"] == "Sweden"
    assert catalog["uk_metoffice_news"]["country"] == "United Kingdom"
    assert {catalog[sid]["publisher_origin_id"] for sid in IDS} == {"se_scb", "uk_metoffice"}
    assert not any(sid in catalog for sid in (
        "eu_eurostat_dataset_updates", "uk_metoffice_warnings"))


def test_parser_keeps_only_original_metadata():
    catalog = rows()
    for sid in IDS:
        source = catalog[sid]
        original = (
            "https://www.scb.se/nyheter/2026/statistik-test/"
            if sid == "se_scb_statistics" else
            "https://www.metoffice.gov.uk/about-us/news-and-media/media-centre/weather-news/test"
        )
        body = (f'<rss><channel><item><guid>publisher-item</guid><title>Official notice</title>'
                f'<link>{original}</link>'
                '<pubDate>Fri, 13 Nov 2026 06:30:00 GMT</pubDate>'
                '<description>Not to be stored as a full summary or article body.</description>'
                '<enclosure url="https://invalid.example/media.jpg" type="image/jpeg"/>'
                '</item></channel></rss>').encode()
        reports = parse_feed(body, source, STAMP)
        assert len(reports) == 1
        report = reports[0]
        assert report["title"] == "Official notice"
        assert report["original_url"] == report["url"] == original
        assert report["published_at"] == "2026-11-13T06:30:00Z"
        assert report["summary"] == "" and report["media"] == []
        assert report["origin_id"] == PUBLISHER[sid]
        assert report["country_basis"] == "publisher_coverage"
        assert report["latitude"] is None and report["longitude"] is None
        assert report["attribution"]


def test_external_article_url_rejected():
    source_map = rows()
    for sid in IDS:
        bogus = (
            b'<rss><channel><item><title>Untrusted redirect</title>'
            b'<link>https://untrusted.example/news/</link>'
            b'<pubDate>Fri, 13 Nov 2026 06:30:00 GMT</pubDate>'
            b'</item></channel></rss>'
        )
        assert parse_feed(bogus, source_map[sid], STAMP) == []


def test_publisher_country_cannot_become_incident_geolocation():
    catalog = rows()
    for sid in IDS:
        s = catalog[sid]
        host = s["article_domains"][0]
        xml = (
            f'<rss><channel><item><title>Publisher notice</title>'
            f'<link>https://{host}/news/notice</link>'
            '<pubDate>Fri, 13 Nov 2026 06:30:00 GMT</pubDate>'
            '</item></channel></rss>'
        ).encode()
        report = parse_feed(xml, s, STAMP)[0]
        assert report["country"] == s["country"]
        assert report["country_basis"] == "publisher_coverage"
        assert report["latitude"] is None and report["longitude"] is None


def test_grouped_publisher_origin_not_endpoint_count():
    catalog = rows()
    assert catalog["se_scb_statistics"]["publisher_origin_id"] == "se_scb"
    assert catalog["uk_metoffice_news"]["publisher_origin_id"] == "uk_metoffice"
    assert catalog["se_scb_statistics"]["publisher_origin_id"] != "eurostat"
    assert catalog["uk_metoffice_news"]["publisher_origin_id"] != "uk_mod"
