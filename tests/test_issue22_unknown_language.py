"""Unknown-language RSS/Atom source data must not silently become English.

This tests production parsing, custom-feed construction, Collector receipt and
SQLite persistence offline. It does not install models or assert translation.
"""
from datetime import datetime, timezone

import httpx
import pytest

from global_pulse.core import Store
from global_pulse.sources import Collector, make_user_feed, parse_feed

NOW = datetime(2026, 11, 11, 21, 0, tzinfo=timezone.utc)
RETRIEVED = "2026-11-11T21:00:00Z"
DATE = "Wed, 11 Nov 2026 19:00:00 GMT"


def rss(title, *, include_date=True):
    publication = f"<pubDate>{DATE}</pubDate>" if include_date else ""
    return (f'<rss version="2.0"><channel><item><guid>notice-1</guid>'
            f'<title>{title}</title>'
            f'<link>https://example.org/reports/notice-1</link>'
            f'{publication}</item></channel></rss>').encode("utf-8")


def custom():
    # DNS-free validation is limited to test fixtures: no network is contacted.
    return make_user_feed("https://example.org/rss", "User-provided publisher", validate_dns=False)


def test_custom_feed_declares_unidentified_language_not_english():
    source = custom()
    assert source["language"] == "und"
    assert source["independence"] == "unknown"
    assert source["metadata_only"] is True
    report = parse_feed(rss("Breve aviso"), source, RETRIEVED)[0]
    assert report["language"] == "und"
    assert report["published_at"] == "2026-11-11T19:00:00Z"
    assert report["url"] == "https://example.org/reports/notice-1"
    assert report["country_basis"] == "publisher_coverage"
    assert report["latitude"] is None and report["longitude"] is None


@pytest.mark.parametrize("override", [None, "", "und"])
def test_missing_or_empty_source_language_fails_closed(override):
    source = custom()
    if override is None:
        source.pop("language")
    else:
        source["language"] = override
    report = parse_feed(rss("Short notice"), source, RETRIEVED)[0]
    assert report["language"] == "und"
    assert report["source_id"] == source["id"]


def test_known_english_and_explicit_non_english_language_preserved():
    source = custom()
    source["language"] = "en"
    assert parse_feed(rss("Brief notice"), source, RETRIEVED)[0]["language"] == "en"
    source["language"] = "es"
    assert parse_feed(rss("Breve aviso"), source, RETRIEVED)[0]["language"] == "es"


def test_unknown_cyrillic_and_arabic_script_not_mislabeled_english():
    source = custom()
    assert parse_feed(rss("Последние новости"), source, RETRIEVED)[0]["language"] == "ru"
    assert parse_feed(rss("أخبار المنطقة"), source, RETRIEVED)[0]["language"] == "ar"


def test_collector_to_persisted_report_preserves_unknown_language(tmp_path):
    source = custom()
    payload = rss("Breve aviso")
    calls = []
    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, headers={"content-type": "application/rss+xml"}, content=payload)
    def client_factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)
    result = Collector(source, now=lambda: NOW, client_factory=client_factory).collect({"configured_interval": 600})
    assert len(calls) == 1
    assert result["state"]["status"] == "available"
    assert len(result["reports"]) == 1
    parsed = result["reports"][0]
    assert parsed["language"] == "und"
    assert parsed["published_at"] == "2026-11-11T19:00:00Z"
    db = tmp_path / "pulse.sqlite3"
    store = Store(db, mode="live")
    try:
        store.ingest(result["reports"])
    finally:
        store.close()
    reopened = Store(db, mode="live")
    try:
        records = [r for event in reopened.list_events(limit=100) for r in event.get("reports", [])]
        matches = [r for r in records if r.get("id") == parsed["id"]]
        assert len(matches) == 1
        assert matches[0]["language"] == "und"
        assert matches[0]["published_at"] == parsed["published_at"]
    finally:
        reopened.close()
