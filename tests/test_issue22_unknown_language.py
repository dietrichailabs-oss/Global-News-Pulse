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


def test_undeclared_short_cyrillic_and_arabic_script_remain_unknown():
    source = custom()
    # Script is not language: Ukrainian/Russian/Belarusian share Cyrillic,
    # and Arabic/Persian/Urdu share much of Arabic script.
    assert parse_feed(rss("Последние новости"), source, RETRIEVED)[0]["language"] == "und"
    assert parse_feed(rss("أخبار المنطقة"), source, RETRIEVED)[0]["language"] == "und"
    assert parse_feed(rss("خبر فوری"), source, RETRIEVED)[0]["language"] == "und"


def test_distinct_ukrainian_letters_route_without_russian_fallback():
    assert parse_feed(rss("Київ: новини"), custom(), RETRIEVED)[0]["language"] == "uk"


def test_rss_channel_language_routes_declared_ukrainian_and_persian():
    source = custom()
    for tag, expected in [("uk-UA", "uk"), ("fa-IR", "fa"),
                          ("zh-TW", "zt"), ("en-GB", "en")]:
        payload = rss("News").replace(
            b"<channel>", f"<channel><language>{tag}</language>".encode())
        assert parse_feed(payload, source, RETRIEVED)[0]["language"] == expected


def test_rss_item_xml_language_overrides_channel_and_catalog():
    source = custom()
    source["language"] = "ru"
    payload = rss("Новини України").replace(
        b"<channel>", b"<channel><language>ru-RU</language>").replace(
        b"<item>", b'<item xml:lang="uk-UA">')
    report = parse_feed(payload, source, RETRIEVED)[0]
    assert report["language"] == "uk" and report["source_id"] == source["id"]


def test_atom_feed_and_entry_language_routing_preserve_original_headlines():
    source = custom()
    atom = (b'<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="fa-IR">'
            b'<entry><id>persian</id><title>News</title>'
            b'<link href="https://example.org/reports/notice-2"/>'
            b'<published>2026-11-11T19:00:00Z</published></entry>'
            b'<entry xml:lang="uk-UA"><id>ukrainian</id><title>News</title>'
            b'<link href="https://example.org/reports/notice-3"/>'
            b'<published>2026-11-11T19:00:00Z</published></entry></feed>')
    rows = parse_feed(atom, source, RETRIEVED)
    assert [row["language"] for row in rows] == ["fa", "uk"]
    assert [row["title"] for row in rows] == ["News", "News"]


def test_unrecognized_feed_language_is_not_english():
    source = custom()
    payload = rss("Short notice").replace(
        b"<channel>", b"<channel><language>123-???</language>")
    assert parse_feed(payload, source, RETRIEVED)[0]["language"] == "und"


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

def test_declared_language_survives_collector_and_store_restart(tmp_path):
    source = custom()
    payload = rss("Київ: місцеві новини").replace(
        b"<channel>", b"<channel><language>uk-UA</language>")
    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/rss+xml"}, content=payload)
    def client_factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)
    result = Collector(source, now=lambda: NOW, client_factory=client_factory).collect(
        {"configured_interval": 600})
    assert result["state"]["status"] == "available"
    assert len(result["reports"]) == 1
    report = result["reports"][0]
    assert report["language"] == "uk" and report["title"] == "Київ: місцеві новини"
    archive = tmp_path / "language-provenance.sqlite3"
    with Store(archive, mode="live") as store:
        store.ingest(result["reports"])
    with Store(archive, mode="live") as store:
        persisted = [r for event in store.list_events(limit=100)
                     for r in event.get("reports", []) if r.get("id") == report["id"]]
        assert len(persisted) == 1
        assert persisted[0]["language"] == "uk"
        assert persisted[0]["title"] == report["title"]
