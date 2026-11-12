"""Offline guards for Issue #22 official-source batch 4."""
from datetime import datetime, timezone
from scripts.official_feed_batch4 import BASE, candidates, eligible_reports

def test_batch4_base_is_exact_independently_accepted_pr93_product():
    assert BASE == "c9f472e58ac61ea57749fb51dbebe21cf056c2a7"

def test_batch4_candidates_are_unique_official_metadata_feeds():
    items = candidates()
    assert [x["id"] for x in items] == ["sec_press","federal_reserve_press","epa_enforcement_news"]
    assert len({x["url"] for x in items}) == 3
    for x in items:
        assert x["official"] is True
        assert x["metadata_only"] is True
        assert x["enabled"] is True
        assert x["min_interval"] >= 3600
        assert x["url"].startswith("https://")
        assert x["access_status"] == "reviewed_public"

def test_batch4_requires_current_dated_https_report():
    source = candidates()[0]
    now = datetime(2026,11,11,23,50,tzinfo=timezone.utc)
    base = {"source_id":source["id"],"id":"r1","title":"Official statement","url":"https://www.sec.gov/example"}
    ok, rows = eligible_reports(source, {"state":{"status":"available"},"reports":[dict(base,published_at="2026-11-11T20:00:00Z")]}, now)
    assert ok and len(rows)==1
    assert eligible_reports(source, {"state":{"status":"available"},"reports":[dict(base,published_at="")]}, now)==(False,[])
    assert eligible_reports(source, {"state":{"status":"available"},"reports":[dict(base,published_at="2026-10-01T20:00:00Z")]}, now)==(False,[])
