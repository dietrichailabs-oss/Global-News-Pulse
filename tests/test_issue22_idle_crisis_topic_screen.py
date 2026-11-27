"""Source-faithful non-crisis screen for the no-click map classification hot path.

All events below are fictional, offline report-shaped fixtures, not live crises.
Do not treat reduced CPU work as a Windows 11 smoothness acceptance.
"""
from datetime import datetime, timedelta, timezone
from time import perf_counter
from unittest.mock import patch

import global_pulse.crisis_overlay as overlay

NOW = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)


def _event(i, *, title="Quarterly cereal yield statistics released",
           category="Economy", official=True, source="fixture-0",
           published=None, status="active", country="Ukraine", basis="explicit_record"):
    stamp = (published or NOW).isoformat()
    return {
        "id": f"fixture-{i}", "title": title, "category": category,
        "status": status, "updated_at": stamp, "independent_origins": [source],
        "reports": [{
            "id": f"source-report-{i}", "source_id": "offline-fixture",
            "origin_id": source, "independence": "original", "kind": "report",
            "country": country, "country_basis": basis,
            "title": title, "summary": "Original dated sample only",
            "category": category, "published_at": stamp,
            "official": official, "evidence_status": "active",
        }],
    }


def test_ordinary_dated_reports_do_not_run_incident_country_inference():
    # This is a REAL source-record-shaped batch, unlike an all-synthetic demo
    # map. Valid recent official economics is not evidence of armed conflict.
    rows = [_event(i) for i in range(420)]
    started = perf_counter()
    with (
        patch.object(overlay, "structured_incident_country",
                     side_effect=AssertionError("non-crisis report reached geography")) as structured,
        patch.object(overlay, "_explicit_text_country",
                     side_effect=AssertionError("non-crisis report reached text geocoder")) as textual,
    ):
        assert overlay.build_country_activity(rows, now=NOW) == {}
        assert structured.call_count == 0
        assert textual.call_count == 0
    print(f"PULSE_NONCRISIS_TOPIC_SCREEN_420_REPORTS_MS={(perf_counter()-started)*1000:.3f}", flush=True)


def test_source_dated_conflict_still_preserves_official_country_evidence():
    item = _event("supported", title="Fictional military shelling report in Ukraine",
                  category="Conflict")
    activity = overlay.build_country_activity([item], now=NOW)
    key = overlay.normalize_country("Ukraine")
    assert key in activity
    assert activity[key]["conflict"] >= 1
    assert item["id"] in activity[key]["event_ids"]


def test_future_stale_withdrawn_and_uncorroborated_stay_unstriped():
    title = "Fictional missile strikes reported in Ukraine"
    cases = [
        _event("old", title=title, category="Conflict", published=NOW-timedelta(days=45)),
        _event("future", title=title, category="Conflict", published=NOW+timedelta(days=2)),
        _event("withdrawn", title=title, category="Conflict", status="retracted"),
        _event("uncorroborated", title=title, category="Conflict", official=False),
    ]
    # One independent nonofficial source does not authorize a current stripe.
    assert overlay.build_country_activity(cases, now=NOW) == {}


def test_two_separate_eligible_sources_still_support_cross_event_corroboration():
    title = "Fictional armed conflict reporting in Ukraine"
    rows = [
        _event("a", title=title, category="Conflict", official=False, source="origin-a"),
        _event("b", title=title, category="Conflict", official=False, source="origin-b"),
    ]
    result = overlay.build_country_activity(rows, now=NOW)
    entry = result[overlay.normalize_country("Ukraine")]
    assert entry["conflict"] >= 1
    assert entry["basis"]["conflict"] == "cross_event_independent"
