"""Brazil Agência Câmara publisher-direct RSS: original links, licensing, no bodies, common origin."""
from urllib.parse import urlsplit

from global_pulse.sources import load_catalog, parse_feed

IDS = ("br_camara_all", "br_camara_health", "br_camara_economy")
ORIGIN = "br_camara"
RETRIEVED = "2026-11-13T11:05:00Z"


def rows():
    catalog = {s["id"]: s for s in load_catalog()}
    return [catalog[identity] for identity in IDS]


def test_camara_catalog_and_publisher_rights():
    all_rows = rows()
    assert len(all_rows) == 3
    for s in all_rows:
        assert s["enabled"] and s["metadata_only"] and s["official"]
        assert s["adapter"] == "rss" and s["official_scope"] == "statement"
        assert s["publisher_origin_id"] == ORIGIN and s["independence"] == "original"
        assert s["authentication"] == "None" and s["access_status"] == "reviewed_public"
        assert s["min_interval"] >= 3600 and s["stale_after_days"] <= 30
        assert s["retention_days"] <= 90
        assert s["country"] == "Brazil" and s["region"] == "South America"
        assert s["license_url"] == "https://infograficos.camara.leg.br/manual-de-comunicacao/agencia-camara/"
        assert s["feed_documentation"] == "https://www.camara.leg.br/noticias/rss"
        assert "Agência Câmara" in s["attribution"] and "Agência Câmara" in s["license"]
        assert s["allowed_domains"] == ["www.camara.leg.br"]
        assert s["article_domains"] == ["www.camara.leg.br"]
        assert urlsplit(s["url"]).hostname == "www.camara.leg.br"
    assert len({s["publisher_origin_id"] for s in all_rows}) == 1


def test_camara_parser_retains_source_headline_time_direct_link_not_summary_or_media():
    for source in rows():
        original = "https://www.camara.leg.br/noticias/1319043-comissao-de-financas-debate"
        rss = (
            "<rss><channel><item>"
            "<title>Comissão de Finanças debate reforma tributária</title>"
            f"<link>{original}</link>"
            "<guid>https://www.camara.leg.br/noticias/guid-should-not-replace-link</guid>"
            "<pubDate>Thu, 12 Nov 2026 22:04:00 GMT</pubDate>"
            "<description>Never retain an article summary or extract body</description>"
            '<enclosure url="https://www.camara.leg.br/media/picture.jpg" type="image/jpeg"/>'
            "</item></channel></rss>"
        ).encode()
        parsed = parse_feed(rss, source, RETRIEVED)
        assert len(parsed) == 1
        report = parsed[0]
        assert report["title"] == "Comissão de Finanças debate reforma tributária"
        assert report["published_at"] == "2026-11-12T22:04:00Z"
        assert report["url"] == report["original_url"] == original
        assert report["summary"] == "" and report["media"] == []
        assert report["origin_id"] == ORIGIN
        assert report["attribution"] == source["attribution"]
        assert report["country_basis"] == "publisher_coverage"
        assert report["latitude"] is None and report["longitude"] is None


def test_camara_nonpublisher_original_links_rejected_without_scraping():
    fake = (
        "<rss><channel><item><title>False attributed report</title>"
        "<link>https://untrusted.invalid/other-publisher-story</link>"
        "<pubDate>Thu, 12 Nov 2026 22:04:00 GMT</pubDate>"
        "</item></channel></rss>"
    ).encode()
    for source in rows():
        assert parse_feed(fake, source, RETRIEVED) == []


def test_camara_sibling_feeds_and_other_brazil_family_not_independent():
    catalog = {s["id"]: s for s in load_catalog()}
    assert {catalog[i]["publisher_origin_id"] for i in IDS} == {ORIGIN}
    assert ORIGIN != catalog["br_bcb_press"]["publisher_origin_id"]
