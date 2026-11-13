"""Regression coverage for reviewed public-feed expansion."""
from global_pulse.sources import load_catalog,parse_feed

STAMP="2026-11-13T02:00:00Z"

def _catalog():
    return {row["id"]:row for row in load_catalog()}

def test_admitted_expansion_sources_are_enabled_metadata_only_and_grouped():
    c=_catalog()
    uk={"fcdo","ukhsa","hm_treasury","cabinet_office"}
    canada={"health_canada_news"}
    ecdc={"ecdc_news"}
    independent={"rba_media","eurostat_news","bank_canada_press","eu_council_press"}
    for identity in (uk-{"fcdo"})|canada|ecdc|independent:
        assert c[identity]["enabled"] is True
        assert c[identity]["metadata_only"] is True
        assert c[identity]["access_status"]=="reviewed_public"
    assert c["fcdo"]["enabled"] is True
    assert {c[x]["publisher_origin_id"] for x in uk}=={"uk_government"}
    assert {c[x]["publisher_origin_id"] for x in canada}=={"canada_gov"}
    assert {c[x]["publisher_origin_id"] for x in ecdc}=={"ecdc"}
    assert c["bank_canada_press"]["publisher_origin_id"]=="bank_canada"
    assert c["eu_council_press"]["publisher_origin_id"]=="eu_council"

def test_stale_or_unparsed_candidates_are_not_active_evidence():
    c=_catalog()
    rejected={
        "voa_africa","voa_middle_east","voa_iran","voa_europe","voa_ukraine",
        "voa_economy","voa_health","fda_outbreaks","fda_press","fda_medwatch",
        "phac_public_health","phac_travel_health","ecdc_cdtr",
    }
    for identity in rejected:
        assert c[identity]["enabled"] is False
        assert c[identity]["status"]=="disabled"

def test_expansion_fills_requested_categories_and_regions():
    c=_catalog()
    assert c["ukhsa"]["category"]=="Health"
    assert c["hm_treasury"]["category"]=="Economy"
    assert c["cabinet_office"]["category"]=="Government"
    assert c["rba_media"]["country"]=="Australia"
    assert c["eurostat_news"]["region"]=="Europe"
    assert c["phac_travel_health"]["region"]=="Global"
    assert c["bank_canada_press"]["category"]=="Economy"
    assert c["ecdc_cdtr"]["category"]=="Health"
    assert c["eu_council_press"]["category"]=="Government"

def test_rss_metadata_only_keeps_headline_link_and_one_publisher_origin():
    c=_catalog()
    xml=b'''<?xml version="1.0"?><rss><channel>
      <item><guid>1</guid><title>Health update in Canada</title>
      <link>https://www.ecdc.europa.eu/en/news-events/example</link>
      <pubDate>Thu, 12 Nov 2026 20:00:00 GMT</pubDate>
      <description>Longer publisher summary must not be retained.</description></item>
    </channel></rss>'''
    rows=parse_feed(xml,c["ecdc_news"],STAMP)
    assert len(rows)==1
    assert rows[0]["title"]=="Health update in Canada"
    assert rows[0]["summary"]==""
    assert rows[0]["metadata_only"] is True
    assert rows[0]["origin_id"]=="ecdc"

def test_atom_govuk_feed_uses_shared_government_origin():
    c=_catalog()
    xml=b'''<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>tag:gov.uk,2026:/example</id><title>Public health update</title>
      <link rel="alternate" href="https://www.gov.uk/government/news/example"/>
      <updated>2026-11-12T20:00:00Z</updated><summary>Not retained.</summary></entry>
    </feed>'''
    rows=parse_feed(xml,c["ukhsa"],STAMP)
    assert len(rows)==1
    assert rows[0]["summary"]==""
    assert rows[0]["origin_id"]=="uk_government"
