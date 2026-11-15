"""Official ECB source-expansion admission and non-corroboration regression."""
from urllib.parse import urlsplit
from global_pulse.sources import load_catalog, parse_feed

IDS = ("ecb_press", "ecb_statpress")
ORIGIN = "ecb"
STAMP = "2026-11-13T08:30:00Z"
REJECTED = {"br_gov_economy", "br_gov_health", "br_gov_infrastructure",
            "br_gov_energy", "br_gov_justice"}


def catalog():
    return {s["id"]: s for s in load_catalog()}


def test_admitted_publisher_group_and_metadata_constraints():
    c = catalog()
    assert len(c) >= 159
    assert len({c[x]["url"] for x in IDS}) == 2
    for sid in IDS:
        s = c[sid]
        assert s["enabled"] is True and s["adapter"] == "rss"
        assert s["metadata_only"] is True and s["official"] is True
        assert s["access_status"] == "reviewed_public"
        assert s["authentication"] == "None"
        assert s["publisher_origin_id"] == ORIGIN
        assert s["independence"] == "original"
        assert s["min_interval"] >= 3600 and s["stale_after_days"] <= 30
        assert s["retention_days"] <= 180
        assert s["license_url"].startswith("https://www.ecb.europa.eu/")
        assert s["feed_documentation"].startswith("https://www.ecb.europa.eu/")
        assert s["attribution"] and s["license"] and s["limitation"]
        assert s["country"] == ""
        assert s["article_domains"] == ["www.ecb.europa.eu", "ecb.europa.eu"]
    assert c["ecb_statpress"]["official_scope"] == "measurement"
    assert c["ecb_press"]["official_scope"] == "statement"
    assert not (REJECTED & set(c))


def test_rss_metadata_only_and_original_publisher_link():
    for sid in IDS:
        s = catalog()[sid]
        link = "https://www.ecb.europa.eu//press/stats/test.html"
        xml = f"""<rss><channel><item><guid>test-release</guid>
          <title>ECB publication notice</title><link>{link}</link>
          <pubDate>Fri, 13 Nov 2026 08:00:00 GMT</pubDate>
          <description>Publisher body/excerpt not for syndication.</description>
          <enclosure url="https://www.ecb.europa.eu/image.jpg" type="image/jpeg"/>
          </item></channel></rss>""".encode()
        report, = parse_feed(xml, s, STAMP)
        assert report["title"] == "ECB publication notice"
        assert report["url"] == link == report["original_url"]
        assert report["published_at"] == "2026-11-13T08:00:00Z"
        assert report["summary"] == "" and report["media"] == []
        assert report["metadata_only"] is True
        assert report["origin_id"] == ORIGIN
        assert report["attribution"] == s["attribution"]


def test_unapproved_article_host_is_blocked():
    c = catalog()
    for sid in IDS:
        xml = b"""<rss><channel><item><guid>bad</guid><title>Untrusted</title>
          <link>https://third-party.invalid/article</link>
          <pubDate>Fri, 13 Nov 2026 08:00:00 GMT</pubDate>
          </item></channel></rss>"""
        assert parse_feed(xml, c[sid], STAMP) == []


def test_country_scope_is_not_event_geography():
    c = catalog()
    for sid in IDS:
        source = c[sid]
        xml = b"""<rss><channel><item><title>ECB statement</title>
          <link>https://www.ecb.europa.eu/press/example</link>
          <pubDate>Fri, 13 Nov 2026 08:00:00 GMT</pubDate>
          </item></channel></rss>"""
        report, = parse_feed(xml, source, STAMP)
        assert report["country_basis"] == "publisher_coverage"
        assert report["country"] == ""
        assert report["latitude"] is None and report["longitude"] is None


def test_approved_urls_and_reuse_scope():
    c = catalog()
    for sid in IDS:
        s = c[sid]
        assert urlsplit(s["url"]).hostname in s["allowed_domains"]
        assert "no summaries, bodies, images" in s["license"]
        assert "named-author" in s["license"] or "Named-author" in s["limitation"]
