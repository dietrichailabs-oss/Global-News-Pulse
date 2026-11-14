"""Office for Budget Responsibility RSS provenance and Open Government Licence admission."""
from urllib.parse import urlsplit

from global_pulse.sources import load_catalog, parse_feed

ID = "uk_obr_news"
ORIGIN = "uk_obr"
RETRIEVED = "2026-11-13T10:18:00Z"


def row():
    return {item["id"]: item for item in load_catalog()}[ID]


def test_obr_catalog_scoping_rights_and_no_scraping():
    s = row()
    assert s["enabled"] and s["metadata_only"] and s["official"]
    assert s["adapter"] == "rss" and s["official_scope"] == "statement"
    assert s["publisher_origin_id"] == ORIGIN and s["independence"] == "original"
    assert s["url"] == "https://obr.uk/feed/"
    assert s["authentication"] == "None" and s["access_status"] == "reviewed_public"
    assert s["min_interval"] >= 3600 and s["retention_days"] <= 180
    assert s["stale_after_days"] <= 30
    assert s["country"] == "United Kingdom" and s["category"] == "Economy"
    assert s["license_url"] == "https://obr.uk/legal-pages/copyright/"
    assert "Open Government Licence" in s["license"]
    assert "logo" in s["license"].lower()
    assert s["attribution"] and s["homepage"] and s["feed_documentation"]
    assert urlsplit(s["url"]).hostname in s["allowed_domains"]


def test_obr_parser_preserves_original_licence_metadata_only():
    s = row()
    url = "https://obr.uk/official-economic-and-fiscal-update/"
    rss = (
        "<rss><channel><item><guid>https://obr.uk/news/unique-guid</guid>"
        "<title>OBR economic and fiscal update</title>"
        f"<link>{url}</link>"
        "<pubDate>Wed, 28 Oct 2026 16:42:05 GMT</pubDate>"
        "<description>This publisher summary must not be retained</description>"
        '<enclosure url="https://obr.uk/image.jpg" type="image/jpeg"/>'
        "</item></channel></rss>"
    ).encode()
    reports = parse_feed(rss, s, RETRIEVED)
    assert len(reports) == 1
    report = reports[0]
    assert report["title"] == "OBR economic and fiscal update"
    assert report["original_url"] == url == report["url"]
    assert report["published_at"] == "2026-10-28T16:42:05Z"
    assert report["summary"] == "" and report["media"] == []
    assert report["origin_id"] == ORIGIN
    assert report["country"] == "United Kingdom"
    assert report["country_basis"] == "publisher_coverage"
    assert report["latitude"] is None and report["longitude"] is None
    assert report["attribution"] == s["attribution"]


def test_obr_untrusted_link_rejected():
    rss = (
        "<rss><channel><item><title>Fake official update</title>"
        "<link>https://untrusted.example.invalid/claim</link>"
        "<pubDate>Wed, 28 Oct 2026 16:42:05 GMT</pubDate>"
        "</item></channel></rss>"
    ).encode()
    assert parse_feed(rss, row(), RETRIEVED) == []


def test_obr_independence_not_collapsed_into_uk_government():
    c = {item["id"]: item for item in load_catalog()}
    assert c[ID]["publisher_origin_id"] == ORIGIN
    assert c[ID]["publisher_origin_id"] != c["uk_mod"]["publisher_origin_id"]
    assert c[ID]["publisher_origin_id"] != c["uk_metoffice_news"]["publisher_origin_id"]
    assert c[ID]["publisher_origin_id"] != c["ons_releases"]["publisher_origin_id"]
