"""Federal Reserve official topical RSS admission: direct links, rights, dates, metadata and shared origin."""
from urllib.parse import urlsplit

from global_pulse.sources import load_catalog, parse_feed

IDS=("fed_enforcement","fed_monetary")
ORIGIN="federal_reserve_press"
RETRIEVED="2026-11-13T12:30:00Z"


def catalog():
    return {s["id"]:s for s in load_catalog()}


def test_fed_source_catalog_and_same_publisher_origin():
    c=catalog()
    assert c["federal_reserve_press"]["enabled"]
    assert c["federal_reserve_press"]["publisher_origin_id"]==ORIGIN
    assert {c[s]["publisher_origin_id"] for s in IDS}=={ORIGIN}
    for identity in IDS:
        s=c[identity]
        assert s["enabled"] is True and s["metadata_only"] is True and s["official"] is True
        assert s["independence"]=="original" and s["official_scope"]=="statement"
        assert s["adapter"]=="rss" and s["access_status"]=="reviewed_public"
        assert s["authentication"]=="None" and s["publisher_origin_id"]==ORIGIN
        assert s["retention_days"]<=90 and s["stale_after_days"]<=30 and s["min_interval"]>=3600
        assert s["allowed_domains"]==["www.federalreserve.gov"]
        assert s["article_domains"]==["www.federalreserve.gov"]
        assert urlsplit(s["url"]).hostname=="www.federalreserve.gov"
        assert s["feed_documentation"]=="https://www.federalreserve.gov/feeds/feeds.htm"
        assert s["license_url"]=="https://www.federalreserve.gov/disclaimer.htm"
        assert "Federal Reserve" in s["attribution"] or "Board of Governors" in s["attribution"]
        assert s["country"]=="United States" and s["region"]=="North America"


def test_fed_parser_keeps_headline_timestamp_and_direct_url_not_body_or_media():
    for identity in IDS:
        s=catalog()[identity]
        original="https://www.federalreserve.gov/newsevents/pressreleases/monetary20261112a.htm"
        rss=f"""<?xml version="1.0"?>
        <rss><channel><item><guid>guid-not-original</guid><title>Board issues policy statement</title>
        <link>{original}</link><pubDate>Thu, 12 Nov 2026 17:45:00 GMT</pubDate>
        <description>Do not retain the publisher summary or body.</description>
        <enclosure url="https://www.federalreserve.gov/images/not-reusable.jpg" type="image/jpeg"/>
        </item></channel></rss>""".encode()
        out=parse_feed(rss,s,RETRIEVED)
        assert len(out)==1
        r=out[0]
        assert r["title"]=="Board issues policy statement"
        assert r["published_at"]=="2026-11-12T17:45:00Z"
        assert r["url"]==original and r["original_url"]==original
        assert r["origin_id"]==ORIGIN
        assert r["attribution"]==s["attribution"]
        assert r["metadata_only"] is True and r["summary"]=="" and r["media"]==[]
        assert r["country_basis"]=="publisher_coverage"
        assert r["latitude"] is None and r["longitude"] is None


def test_fed_nonpublisher_article_urls_are_rejected():
    xml=b"""<rss><channel><item><title>Spurious report</title>
    <link>https://example.org/fraud</link><pubDate>Thu, 12 Nov 2026 17:45:00 GMT</pubDate>
    </item></channel></rss>"""
    for identity in IDS:
        assert parse_feed(xml,catalog()[identity],RETRIEVED)==[]


def test_fed_topical_feeds_never_count_as_another_independent_source():
    c=catalog()
    assert all(c[x]["publisher_origin_id"]==c["federal_reserve_press"]["publisher_origin_id"] for x in IDS)
    assert len(set([c[x]["publisher_origin_id"] for x in IDS]+[c["federal_reserve_press"]["id"]]))==1
