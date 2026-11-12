"""Offline guards for Issue #22 official-source batch 2."""
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.official_feed_batch2 import BASE, CATALOG, candidates, eligible_reports


def test_batch2_candidates_are_unique_official_metadata_feeds():
    items = candidates()
    assert len(items) == 3
    assert len({item["id"] for item in items}) == 3
    assert len({item["url"] for item in items}) == 3
    for item in items:
        assert item["official"] is True
        assert item["metadata_only"] is True
        assert item["enabled"] is True
        assert item["min_interval"] >= 3600
        assert item["url"].startswith("https://")
        assert item["access_status"] == "reviewed_public"
        assert item["feed_documentation"].startswith("https://")
        assert item["license_url"].startswith("https://")


def test_batch2_frozen_catalog_preserves_baseline_and_appends_exact_candidates_once():
    import subprocess
    baseline = json.loads(subprocess.check_output(
        ["git", "show", BASE + ":" + CATALOG.as_posix()]
    ))
    catalog = json.loads(Path(CATALOG).read_text(encoding="utf-8"))
    assert catalog["sources"][:len(baseline["sources"])] == baseline["sources"]
    appended = catalog["sources"][len(baseline["sources"]):]
    expected = candidates()
    assert len(appended) == len(expected) == 3
    assert [item["id"] for item in appended] == [item["id"] for item in expected]
    assert appended == expected
    assert catalog["catalog_version"] == "2026.11.11.official2"


def test_current_dated_https_report_required():
    source = candidates()[0]
    now = datetime(2026, 11, 11, 22, 0, tzinfo=timezone.utc)
    base = {
        "source_id": source["id"],
        "id": "r1",
        "title": "Official statement",
        "url": "https://www.ftc.gov/news-events/news/press-releases/example",
    }
    result = {"state": {"status": "available"}, "reports": [dict(base, published_at="2026-11-11T20:00:00Z")]}
    okay, rows = eligible_reports(source, result, now)
    assert okay and len(rows) == 1

    undated = {"state": {"status": "available"}, "reports": [dict(base, published_at="")]}
    assert eligible_reports(source, undated, now) == (False, [])

    stale = {"state": {"status": "available"}, "reports": [dict(base, published_at="2026-10-01T20:00:00Z")]}
    assert eligible_reports(source, stale, now) == (False, [])

    external_http = {"state": {"status": "available"}, "reports": [dict(base, url="http://example.org/x", published_at="2026-11-11T20:00:00Z")]}
    assert eligible_reports(source, external_http, now) == (False, [])


def test_selected_baseline_is_pr90_qa_cleared_source():
    assert BASE == "9401c80dda45435ee38b2f8b708d7fb62281e49f"
