"""Regression coverage for reviewed open/public feed expansion."""
from global_pulse.sources import load_catalog,parse_feed

STAMP="2026-11-13T02:00:00Z"

def _catalog():
    return {row["id"]:row for row in load_catalog()}

def test_expansion_sources_are_enabled_metadata_only_and_grouped():
    c=_catalog()
    voa={"voa_africa","voa_middle_east","voa_iran","voa_europe","voa_ukraine","voa_economy","voa_health"}
    fda={"fda_outbreaks","fda_press","fda_medwatch"}
    uk={"fcdo","ukhsa","hm_treasury","cabinet_office"}
    new_sources=voa|fda|{"ukhsa","hm_treasury","cabinet_office","rba_media","eurostat_news"}
    for identity in new_sources:
        assert c[identity]["enabled"] is True
        assert c[identity]["metadata_only"] is True
        assert c[identity]["access_status"]=="reviewed_public"
    assert c["fcdo"]["enabled"] is True
    assert {c[x]["publisher_origin_id"] for x in voa}=={"voa"}
    assert {c[x]["publisher_origin_id"] for x in fda}=={"fda"}
    assert {c[x]["publisher_origin_id"] for x in uk}=={"uk_government"}

def test_expansion_fills_requested_coverage_categories_and_regions():
    c=_catalog()
    assert c["voa_ukraine"]["region"]=="Europe"
    assert c["voa_iran"]["region"]=="Middle East"
    assert c["voa_africa"]["region"]=="Africa"
    assert c["voa_economy"]["category"]=="Economy"
    assert c["voa_health"]["category"]=="Health"
    assert c["fda_outbreaks"]["category"]=="Health"
    assert c["hm_treasury"]["category"]=="Economy"
    assert c["cabinet_office"]["category"]=="Government"
    assert c["rba_media"]["country"]=="Australia"
    assert c["eurostat_news"]["region"]=="Europe"

def test_rss_metadata_only_keeps_headline_link_and_one_publisher_origin():
    c=_catalog()
    xml=b'''<?xml version="1.0"?><rss><channel>
      <item><guid>1</guid><title>Ukraine security update</title>
      <link>https://www.voanews.com/a/example/1.html</link>
      <pubDate>Thu, 12 Nov 2026 20:00:00 GMT</pubDate>
      <description>Longer publisher summary must not be retained.</description></item>
    </channel></rss>'''
    rows=parse_feed(xml,c["voa_ukraine"],STAMP)
    assert len(rows)==1
    assert rows[0]["title"]=="Ukraine security update"
    assert rows[0]["summary"]==""
    assert rows[0]["metadata_only"] is True
    assert rows[0]["origin_id"]=="voa"

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
