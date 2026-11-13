"""Banco Central do Brasil first-party Atom RSS admission, feed-update time and provenance."""
from urllib.parse import urlsplit
from global_pulse.sources import load_catalog, parse_feed

IDS = ("br_bcb_press", "br_bcb_news", "br_bcb_acts", "br_bcb_focus")
ORIGIN = "br_bcb"
RETRIEVED = "2026-11-13T09:15:00Z"


def catalog():
    return {s["id"]: s for s in load_catalog()}


def test_bcb_metadata_only_rights_origin_group_and_release_time_scope():
    c = catalog()
    assert len({c[i]["url"] for i in IDS}) == 4
    assert len({c[i]["publisher_origin_id"] for i in IDS}) == 1
    for sid in IDS:
        s = c[sid]
        assert s["enabled"] and s["metadata_only"] and s["official"]
        assert s["adapter"] == "atom" or s["adapter"] == "rss"
        assert s["publisher_origin_id"] == ORIGIN
        assert s["independence"] == "original"
        assert s["updated_is_publication_time"] is True
        assert s["authentication"] == "None"
        assert s["access_status"] == "reviewed_public"
        assert s["min_interval"] >= 3600 and s["retention_days"] <= 180 and s["stale_after_days"] <= 30
        assert s["region"] == "South America" and s["country"] == "Brazil"
        assert s["language"] == "pt"
        assert s["attribution"] and s["license"]
        assert s["license_url"] == "https://www.bcb.gov.br/en/about/privacystatement"
        assert s["feed_documentation"] == "https://www.bcb.gov.br/en/about/rssen"
        assert urlsplit(s["url"]).hostname in s["allowed_domains"]
        assert "www.bcb.gov.br" in s["article_domains"]
        assert "updated" in s["limitation"].lower()
        assert "first publication" in s["limitation"].lower()


def test_atom_updated_source_scoped_not_retrieval_time():
    c = catalog()
    for sid in IDS:
        s = c[sid]
        link = "https://www.bcb.gov.br/detalhenoticia/21318/nota"
        xml = f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>urn:bcb:news:sample</id><title>BCB official information</title>
          <updated>2026-11-12T08:30:13-03:00</updated>
          <link rel="alternate" href="{link}"/>
          <summary>Long publisher text must not be stored</summary>
          <content>Full content must not be stored</content>
          </entry></feed>""".encode()
        report, = parse_feed(xml, s, RETRIEVED)
        assert report["title"] == "BCB official information"
        assert report["url"] == link == report["original_url"]
        assert report["published_at"] == "2026-11-12T11:30:13Z"
        assert report["source_updated_at"] == "2026-11-12T11:30:13Z"
        assert not report["publication_time_unknown"]
        assert report["summary"] == "" and report["media"] == []
        assert report["origin_id"] == ORIGIN
        assert report["attribution"] == s["attribution"]
        assert report["country_basis"] == "publisher_coverage"
        assert report["latitude"] is None and report["longitude"] is None
        # The allowance is explicitly source-scoped. No default Atom updated-date promotion.
        without_flag = dict(s, updated_is_publication_time=False)
        unreviewed, = parse_feed(xml, without_flag, RETRIEVED)
        assert unreviewed["publication_time_unknown"] is True
        assert not unreviewed["published_at"]


def test_bcb_atom_untrusted_article_host_rejected():
    for sid in IDS:
        s = catalog()[sid]
        xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>untrusted</id><title>Malicious redirect</title>
          <updated>2026-11-12T08:30:13-03:00</updated>
          <link rel="alternate" href="https://untrusted.example.invalid/article"/>
          </entry></feed>"""
        assert parse_feed(xml, s, RETRIEVED) == []


def test_bcb_focus_is_economic_measurement_no_event_coordinate():
    c = catalog()
    assert c["br_bcb_focus"]["official_scope"] == "measurement"
    assert c["br_bcb_acts"]["official_scope"] == "statement"
    s = c["br_bcb_focus"]
    link = "https://www.bcb.gov.br/publicacoes/focus/06112026"
    xml = f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>Focus Market Readout</title>
      <updated>2026-11-06T00:00:00-03:00</updated>
      <link href="{link}" />
      </entry></feed>""".encode()
    report, = parse_feed(xml, s, RETRIEVED)
    assert report["published_at"] == "2026-11-06T03:00:00Z"
    assert report["original_url"] == link and report["origin_id"] == ORIGIN
    assert report["country_basis"] == "publisher_coverage"
    assert report["country"] == "Brazil"
    assert report["latitude"] is None and report["longitude"] is None
