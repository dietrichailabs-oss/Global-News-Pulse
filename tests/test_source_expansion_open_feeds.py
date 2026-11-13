"""Regression coverage for reviewed public-feed expansion."""
from global_pulse.sources import load_catalog,parse_feed

STAMP="2026-11-13T02:00:00Z"

def _catalog():
    return {row["id"]:row for row in load_catalog()}

def test_admitted_expansion_sources_are_enabled_metadata_only_and_grouped():
    c=_catalog()
    uk={"fcdo","ukhsa","hm_treasury","cabinet_office","uk_mod","uk_home_office","uk_desnz","uk_dft","uk_dhsc","uk_defra","uk_dsit"}
    ecdc={"ecdc_news"}
    independent={"rba_media","eurostat_news","bank_canada_press","eu_council_press"}
    for identity in (uk-{"fcdo"})|ecdc|independent:
        assert c[identity]["enabled"] is True
        assert c[identity]["metadata_only"] is True
        assert c[identity]["access_status"]=="reviewed_public"
    assert c["fcdo"]["enabled"] is True
    assert {c[x]["publisher_origin_id"] for x in uk}=={"uk_government"}
    assert {c[x]["publisher_origin_id"] for x in ecdc}=={"ecdc"}
    assert c["bank_canada_press"]["publisher_origin_id"]=="bank_canada"
    assert c["eu_council_press"]["publisher_origin_id"]=="eu_council"

def test_stale_or_unparsed_candidates_are_not_active_evidence():
    c=_catalog()
    rejected={
        "voa_africa","voa_middle_east","voa_iran","voa_europe","voa_ukraine",
        "voa_economy","voa_health","fda_outbreaks","fda_press","fda_medwatch",
        "phac_public_health","phac_travel_health","ecdc_cdtr",
        "eia_today","eia_press","occ_news","occ_bulletins","doe_hgeo","health_canada_news",
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


def test_second_batch_is_metadata_only_and_publisher_grouped():
    c=_catalog()
    groups={
        "usda_nass":{"nass_news","nass_reports","nass_asb","nass_census"},
        "sec":{"sec_press","sec_litigation","sec_suspensions"},
        "noaa":{"nws","swpc","noaa_news","nhc_atlantic_outlook","nhc_east_pacific_outlook"},
        "european_commission":{"ec_trade_news","ec_energy_news","ec_environment_news"},
        "nz_government":{"nz_economic_growth","nz_energy","nz_foreign_affairs","nz_health","nz_infrastructure","nz_national_security","nz_trade"},
        "who":{"who","who_afro_emergencies"},
        "bls":{"bls_latest","bls_employment","bls_jolts","bls_cpi","bls_ppi","bls_import_export","bls_work_stoppages"},
    }
    new_ids=set().union(*groups.values())-{"sec_press","nws","swpc","who","who_afro_emergencies","bls_latest"}
    for identity in new_ids:
        row=c[identity]
        assert row["enabled"] is True
        assert row["metadata_only"] is True
        assert row["access_status"]=="reviewed_public"
        assert row["url"].startswith("https://")
    for origin,identities in groups.items():
        assert {c[x]["publisher_origin_id"] for x in identities}=={origin}

def test_second_batch_spans_economy_health_government_disaster_and_infrastructure():
    c=_catalog()
    assert c["doe_hgeo"]["category"]=="Infrastructure"
    assert c["bls_cpi"]["category"]=="Economy"
    assert c["nass_news"]["category"]=="Economy"
    assert c["sec_litigation"]["category"]=="Economy"
    assert c["nhc_atlantic_outlook"]["category"]=="Disaster"
    assert c["ec_trade_news"]["category"]=="Economy"
    assert c["ec_energy_news"]["category"]=="Infrastructure"
    assert c["nz_health"]["category"]=="Health"
    assert c["nz_national_security"]["category"]=="Government"


def test_ons_feed_is_open_government_statistics_source():
    c=_catalog()
    row=c["ons_releases"]
    assert row["enabled"] is True
    assert row["publisher_origin_id"]=="ons"
    assert row["metadata_only"] is True
    assert row["category"]=="Economy"
    assert "releasecalendar" in row["url"]


def test_statcan_open_licence_family_is_grouped_and_metadata_only():
    c=_catalog()
    ids={
        "statcan_agriculture","statcan_business","statcan_crime","statcan_digital",
        "statcan_economic_accounts","statcan_energy","statcan_environment",
        "statcan_government","statcan_health","statcan_housing","statcan_income",
        "statcan_trade","statcan_labour","statcan_manufacturing",
        "statcan_population","statcan_prices","statcan_transport","statcan_travel",
    }
    for identity in ids:
        row=c[identity]
        assert row["enabled"] is True
        assert row["metadata_only"] is True
        assert row["access_status"]=="reviewed_public"
        assert row["publisher_origin_id"]=="statcan"
        assert row["license_url"].endswith("/open-licence")
        assert row["url"].startswith("https://www150.statcan.gc.ca/n1/rss/dai-quo/")
    assert c["statcan_health"]["category"]=="Health"
    assert c["statcan_energy"]["category"]=="Infrastructure"
    assert c["statcan_government"]["category"]=="Government"
    assert c["statcan_prices"]["category"]=="Economy"

def test_default_canada_crown_feed_is_not_assumed_commercially_cleared():
    c=_catalog()
    assert c["health_canada_news"]["enabled"] is False
    assert c["health_canada_news"]["status"]=="disabled"
