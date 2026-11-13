"""Independent QA regressions for PR17 corrections.

QA-only checks on exact PR17 product head. No product/source changes.
"""
from urllib.parse import urlsplit

from global_pulse.core import normalize_report
from global_pulse.sources import load_catalog, parse_feed

STAMP="2026-11-13T13:45:00Z"

def catalog():
    return {row["id"]: row for row in load_catalog()}

def test_active_exact_feed_urls_are_unique():
    rows=[r for r in load_catalog() if r.get("enabled")]
    urls=[r["url"] for r in rows]
    assert len(urls)==len(set(urls))

def test_ecb_family_preserves_one_historical_origin_and_one_press_poller():
    c=catalog()
    assert c["ecb"]["enabled"] is False
    assert c["ecb"]["url"] == c["ecb_press"]["url"]
    assert {c[k]["publisher_origin_id"] for k in ("ecb","ecb_press","ecb_statpress","ecb_mid")} == {"ecb"}
    rss=b'''<rss><channel><item><guid>1</guid><title>ECB publication</title>
    <link>https://www.ecb.europa.eu/press/item.html</link>
    <pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>'''
    old=parse_feed(rss,c["ecb"],STAMP)[0]
    new=parse_feed(rss,c["ecb_press"],STAMP)[0]
    assert old["origin_id"] == new["origin_id"] == "ecb"

def test_who_family_preserves_pr6_historical_origin():
    c=catalog()
    assert {c[k]["publisher_origin_id"] for k in ("who","who_afro_emergencies")} == {"who_don"}

def test_metadata_only_videoid_is_rejected_at_parser_boundary():
    c=catalog()
    source=c["fed_monetary"]
    rss=b'''<rss><channel><item><guid>f1</guid><title>Policy publication</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/test.htm</link>
    <pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate>
    <videoid>abcdefghijk</videoid></item></channel></rss>'''
    report=parse_feed(rss,source,STAMP)[0]
    assert report["metadata_only"] is True
    assert report["media"] == []

def test_metadata_only_injected_media_is_rejected_at_storage_boundary():
    c=catalog()
    source=c["fed_monetary"]
    raw={
      "id":"qa-media","source_id":source["id"],"origin_id":source["publisher_origin_id"],
      "publisher":"Federal Reserve Board","title":"Policy publication","url":"https://www.federalreserve.gov/newsevents/pressreleases/test.htm",
      "published_at":"2026-11-12T12:00:00Z","retrieved_at":STAMP,
      "metadata_only":True,"summary":"",
      "media":[{"type":"youtube","video_id":"abcdefghijk",
                "url":"https://www.youtube.com/watch?v=abcdefghijk","title":"Injected"}]
    }
    normalized=normalize_report(raw,STAMP)
    assert normalized["metadata_only"] is True
    assert normalized["media"] == []

def test_non_metadata_source_still_allows_valid_videoid():
    c=catalog()
    source={**c["fed_monetary"],"metadata_only":False}
    rss=b'''<rss><channel><item><guid>f2</guid><title>Rich publication</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/test.htm</link>
    <pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate>
    <videoid>abcdefghijk</videoid></item></channel></rss>'''
    report=parse_feed(rss,source,STAMP)[0]
    assert len(report["media"]) == 1
    assert len(normalize_report(report,STAMP)["media"]) == 1

def test_enabled_same_host_rows_do_not_split_publisher_identity():
    by_host={}
    for row in load_catalog():
        if not row.get("enabled"):
            continue
        # World Bank rows are observation-only adapters: parse_worldbank()
        # does not emit report origin_id values or enter publisher corroboration.
        if row.get("adapter") == "worldbank":
            continue
        host=(urlsplit(row["url"]).hostname or "").lower()
        if host:
            by_host.setdefault(host,[]).append(row)
    for host,rows in by_host.items():
        if len(rows)<2:
            continue
        origins={r.get("publisher_origin_id") or r["id"] for r in rows}
        assert len(origins)==1,(host,sorted((r["id"],r.get("publisher_origin_id")) for r in rows))

def test_catalog_size_and_quarantine_contract():
    c=catalog()
    enabled=[r for r in c.values() if r.get("enabled")]
    assert len(c)==170
    assert len(enabled)==129
    assert 49 <= len(c) <= 512
    for identity in ("nz_economic_growth","nz_energy","nz_foreign_affairs","nz_health",
                     "nz_infrastructure","nz_national_security","nz_trade"):
        assert c[identity]["enabled"] is False
        assert c[identity]["status"]=="disabled"
