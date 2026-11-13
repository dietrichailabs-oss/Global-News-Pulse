"""Source-expansion regression for ECB Market Information Dissemination RSS."""
from urllib.parse import urlsplit

from global_pulse.sources import load_catalog, parse_feed

SID = "ecb_mid"
ORIGIN = "eu_ecb"
STAMP = "2026-11-13T09:10:00Z"


def source():
    return next(s for s in load_catalog() if s["id"] == SID)


def test_mid_is_keyless_metadata_only_and_one_ecb_origin():
    s = source()
    c = {item["id"]: item for item in load_catalog()}
    assert s["enabled"] and s["adapter"] == "rss"
    assert s["metadata_only"] and s["official"]
    assert s["authentication"] == "None"
    assert s["access_status"] == "reviewed_public"
    assert s["publisher_origin_id"] == ORIGIN == c["ecb_press"]["publisher_origin_id"]
    assert c["ecb_statpress"]["publisher_origin_id"] == ORIGIN
    assert s["independence"] == "original"
    assert s["min_interval"] >= 3600
    assert s["retention_days"] <= 180 and s["stale_after_days"] <= 30
    assert s["country"] == "" and s["official_scope"] == "measurement"
    assert s["allowed_domains"] == ["mid.ecb.europa.eu"]
    assert s["article_domains"] == ["mid.ecb.europa.eu"]
    assert urlsplit(s["url"]).hostname in s["allowed_domains"]
    assert s["feed_documentation"].startswith("https://www.ecb.europa.eu/")
    assert "public domain" in s["license"].lower()


def test_mid_original_xml_link_and_body_media_exclusion():
    s = source()
    link = "https://mid.ecb.europa.eu/rel/test-status.xml"
    xml = f"""<rss version="2.0"><channel><item>
      <title>ECB MID settlement service notification</title>
      <link>{link}</link><guid>{link}</guid>
      <pubDate>Fri, 13 Nov 2026 08:45:00 GMT</pubDate>
      <description>Long publisher technical body not for retention.</description>
      <enclosure url="https://mid.ecb.europa.eu/assets/chart.png" type="image/png"/>
      </item></channel></rss>""".encode()
    report, = parse_feed(xml, s, STAMP)
    assert report["title"] == "ECB MID settlement service notification"
    assert report["url"] == link == report["original_url"]
    assert report["published_at"] == "2026-11-13T08:45:00Z"
    assert report["summary"] == "" and report["media"] == []
    assert report["origin_id"] == ORIGIN
    assert report["attribution"] == s["attribution"]
    assert report["metadata_only"] is True
    assert report["country_basis"] == "publisher_coverage"
    assert report["country"] == ""
    assert report["latitude"] is None and report["longitude"] is None


def test_mid_unapproved_article_host_rejected():
    s = source()
    xml = b"""<rss><channel><item><title>Incorrect link</title>
      <link>https://example.com/fake-mid</link>
      <pubDate>Fri, 13 Nov 2026 08:00:00 GMT</pubDate>
      </item></channel></rss>"""
    assert parse_feed(xml, s, STAMP) == []
