"""Independent QA checks for PR7 source expansion.

QA-only branch. These checks deliberately do not alter product/source code and
do not treat Engineering workflow success as independent QA evidence.
"""
from __future__ import annotations

import threading
from urllib.parse import urlsplit

from global_pulse.map_evidence import incident_country
from global_pulse.sources import Scheduler, load_catalog, parse_feed

STAMP = "2026-11-13T12:30:00Z"

STATCAN = {
    "statcan_agriculture","statcan_business","statcan_crime","statcan_digital",
    "statcan_economic_accounts","statcan_energy","statcan_environment",
    "statcan_government","statcan_health","statcan_housing","statcan_income",
    "statcan_trade","statcan_labour","statcan_manufacturing",
    "statcan_population","statcan_prices","statcan_transport","statcan_travel",
}
NZ_DENIED = {
    "nz_economic_growth","nz_energy","nz_foreign_affairs","nz_health",
    "nz_infrastructure","nz_national_security","nz_trade",
}

class MemoryStore:
    def __init__(self):
        self.states = {}
    def get_source_state(self, sid):
        return dict(self.states.get(sid, {}))
    def set_source_state(self, sid, state):
        self.states[sid] = dict(state)

def catalog():
    return {row["id"]: row for row in load_catalog()}

def test_exact_catalog_counts_and_enabled_admission_contract():
    rows = load_catalog()
    enabled = [row for row in rows if row.get("enabled")]
    assert len(rows) == 170
    assert len(enabled) == 130
    assert all(row.get("access_status") == "reviewed_public" for row in enabled)
    assert all(str(row.get("url", "")).startswith("https://") for row in enabled)
    assert all(int(row.get("min_interval", 0)) >= 60 for row in enabled)
    assert len({row["id"] for row in rows}) == len(rows)

def test_same_enabled_host_cannot_split_into_multiple_publisher_origins():
    by_host = {}
    for row in load_catalog():
        if not row.get("enabled"):
            continue
        host = urlsplit(row["url"]).hostname
        if not host:
            continue
        by_host.setdefault(host.lower(), []).append(row)
    for host, rows in by_host.items():
        if len(rows) < 2:
            continue
        origins = {row.get("publisher_origin_id") or row["id"] for row in rows}
        assert len(origins) == 1, (host, sorted((r["id"], r.get("publisher_origin_id")) for r in rows))

def test_new_multi_feed_families_have_one_effective_origin():
    c = catalog()
    families = {
        "statcan": STATCAN,
        "federal_reserve_press": {"federal_reserve_press","fed_enforcement","fed_monetary"},
        "eu_ecb": {"ecb","ecb_press","ecb_statpress","ecb_mid"},
        "noaa": {"nws","swpc","noaa_news","nhc_atlantic_outlook","nhc_east_pacific_outlook"},
        "who": {"who","who_afro_emergencies"},
        "un_news": {"un_news","un_peace_security","un_humanitarian_aid","un_health","un_economic_development","un_migrants_refugees","un_affairs"},
        "bls": {"bls_latest","bls_employment","bls_jolts","bls_cpi","bls_ppi","bls_import_export","bls_work_stoppages"},
        "usda_nass": {"nass_news","nass_reports","nass_asb","nass_census"},
        "uk_government": {"fcdo","ukhsa","hm_treasury","cabinet_office","uk_mod","uk_home_office","uk_desnz","uk_dft","uk_dhsc","uk_defra","uk_dsit"},
        "japan_mod": {"japan_mod_updates","japan_mod_press"},
        "jma": {"jma_weather_updates","jma_eqvol_updates"},
        "br_bcb": {"br_bcb_press","br_bcb_news","br_bcb_acts","br_bcb_focus"},
        "br_camara": {"br_camara_all","br_camara_health","br_camara_economy"},
        "norway_ssb": {"norway_ssb_latest","norway_ssb_labour","norway_ssb_energy"},
        "eu_eea": {"eea_press_releases","eea_publications"},
        "eu_ema": {"ema_news_releases","ema_whats_new"},
        "nl_cbs": {"nl_cbs_news","nl_cbs_economy","nl_cbs_health","nl_cbs_energy"},
    }
    for origin, ids in families.items():
        assert ids <= set(c), (origin, sorted(ids - set(c)))
        assert {c[i].get("publisher_origin_id") or c[i]["id"] for i in ids} == {origin}

def test_nz_access_denial_is_quarantined_fail_closed():
    c = catalog()
    for identity in NZ_DENIED:
        row = c[identity]
        assert row["enabled"] is False
        assert row["status"] == "disabled"
        assert row["publisher_origin_id"] == "nz_government"
        assert "403" in row.get("limitation", "")

def test_statcan_date_and_nested_title_exceptions_are_exactly_scoped():
    c = catalog()
    nested = {i for i, row in c.items() if row.get("nested_feed_text")}
    updated = {i for i, row in c.items() if row.get("updated_is_publication_time")}
    assert nested == STATCAN
    assert updated == STATCAN

def test_statcan_nested_markup_is_sanitized_metadata_only():
    source = catalog()["statcan_prices"]
    xml = b'''<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>https://www.statcan.gc.ca/daily-quotidien/261112/dq261112d-eng.htm</id>
        <title><span>Consumer Price Index</span>, October 2026</title>
        <link href="https://www.statcan.gc.ca/daily-quotidien/261112/dq261112d-eng.htm"/>
        <updated>2026-11-12T08:30:00-05:00</updated>
        <summary><b>Publisher summary must not be retained.</b></summary>
      </entry>
    </feed>'''
    reports = parse_feed(xml, source, STAMP)
    assert len(reports) == 1
    report = reports[0]
    assert report["title"] == "Consumer Price Index , October 2026"
    assert report["published_at"] == "2026-11-12T13:30:00Z"
    assert report["summary"] == ""
    assert report["metadata_only"] is True
    assert report["origin_id"] == "statcan"

def test_publisher_country_does_not_create_incident_country():
    event = {
        "id": "qa",
        "status": "active",
        "reports": [{
            "id": "r",
            "source_id": "statcan_prices",
            "title": "Consumer Price Index release",
            "summary": "",
            "country": "Canada",
            "source_country": "Canada",
            "country_basis": "publisher_coverage",
            "evidence_status": "active",
            "published_at": "2026-11-12T13:30:00Z",
            "publication_time_known": True,
        }],
    }
    assert incident_country(event) == ""

def test_multi_country_title_is_not_forced_to_one_country():
    event = {
        "id": "qa2",
        "status": "active",
        "reports": [{
            "id": "r2",
            "source_id": "qa",
            "title": "Iran and Israel exchange statements",
            "summary": "",
            "country": "",
            "source_country": "",
            "country_basis": "publisher_coverage",
            "evidence_status": "active",
            "published_at": "2026-11-12T13:30:00Z",
            "publication_time_known": True,
        }],
    }
    assert incident_country(event) == ""

def test_130_enabled_sources_fit_scheduler_worker_cap_without_network(tmp_path):
    rows = load_catalog()
    store = MemoryStore()
    release = threading.Event()

    class BlockingCollector:
        def __init__(self, source):
            self.source = source
        def collect(self, state):
            release.wait(2)
            return {"reports": [], "observations": [], "state": {"status": "available", "next_poll": "2099-01-01T00:00:00Z"}}

    scheduler = Scheduler(store, lambda reports: None, collector_factory=BlockingCollector, max_workers=4)
    scheduler.set_sources(rows)
    assert len([r for r in scheduler.sources if r.get("enabled")]) == 130
    assert scheduler.max_workers == 4
    try:
        # Force scheduler ticks without waiting for real pacing; the internal
        # worker cap must still prevent more than four concurrent collectors.
        for _ in range(12):
            scheduler._global_next = 0
            scheduler._host_next = {}
            scheduler._tick()
        assert len([t for t in scheduler._workers.values() if t.is_alive()]) <= 4
    finally:
        release.set()
        scheduler.stop(timeout=2.0)
