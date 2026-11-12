"""Offline custody/regression guards for frozen Issue #22 official-source batch 4."""
import json
import subprocess
from pathlib import Path

BASE = "c9f472e58ac61ea57749fb51dbebe21cf056c2a7"
CATALOG = Path("global_pulse/resources/sources.json")
EVIDENCE = Path("docs/engineering/GP-OFFICIAL-FEEDS-BATCH4-20261112/live-check.json")
ADMITTED = ["sec_press", "federal_reserve_press"]

def test_frozen_batch4_catalog_is_exact_41_plus_two():
    baseline = json.loads(subprocess.check_output(["git","show",BASE+":"+CATALOG.as_posix()]))
    current = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert len(baseline["sources"]) == 41
    assert current["sources"][:41] == baseline["sources"]
    appended = current["sources"][41:]
    assert [s["id"] for s in appended] == ADMITTED
    assert len(current["sources"]) == 43
    assert "epa_enforcement_news" not in {s["id"] for s in current["sources"]}
    assert current["catalog_version"] == "2026.11.11.official4"

def test_frozen_batch4_receipts_match_original_completed_job_identity():
    e = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert e["complete"] is True
    assert e["source_head"] == "4c1f3f19953ae5c9b0b0dc885c7ced2d7e5b5771"
    assert e["original_run_id"] == 43129670214
    assert e["original_job_id"] == 130890782156
    assert e["recovery_kind"] == "transcribed_completed_job_log_receipts"
    assert e["admitted_count"] == 2
    assert e["admitted_ids"] == ADMITTED
    assert e["article_fetches"] == 0

    rows = {r["id"]: r for r in e["sources"]}
    assert rows["sec_press"]["http_status"] == 200
    assert rows["sec_press"]["parsed_reports"] == 25
    assert rows["sec_press"]["current_linked_reports"] == 4
    assert rows["sec_press"]["sqlite_reopen_verified"] is True
    assert rows["sec_press"]["parsed_identity_sha256"] == "9ff656b77d3569c25d9abc7dca014c69cd79afffe6be53115b9db1d914628732"

    assert rows["federal_reserve_press"]["http_status"] == 200
    assert rows["federal_reserve_press"]["parsed_reports"] == 20
    assert rows["federal_reserve_press"]["current_linked_reports"] == 3
    assert rows["federal_reserve_press"]["sqlite_reopen_verified"] is True
    assert rows["federal_reserve_press"]["parsed_identity_sha256"] == "26660331d48859107153686c0a279f1194b827bd28d1839b222b2d65791f03d8"

    assert rows["epa_enforcement_news"]["http_status"] == 202
    assert rows["epa_enforcement_news"]["parsed_reports"] == 0
    assert rows["epa_enforcement_news"]["status"] == "not_admitted"

def test_appended_sources_preserve_metadata_only_and_polling_boundaries():
    current = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in current["sources"]}
    for sid in ADMITTED:
        s = by_id[sid]
        assert s["enabled"] is True
        assert s["official"] is True
        assert s["metadata_only"] is True
        assert s["min_interval"] >= 3600
        assert s["url"].startswith("https://")
        assert s["access_status"] == "reviewed_public"
        assert s["official_scope"] == "statement"
