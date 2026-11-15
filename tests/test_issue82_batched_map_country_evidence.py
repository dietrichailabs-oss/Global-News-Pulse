"""Differential QA of optimized country map evidence against original slow projection.

Only offline synthetic/live fixtures; no network or fabricated publisher approval.
Every changed map projection is compared to the exact existing source-time
_get_event_unlocked implementation, including full labelled report evidence.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from global_pulse.map_widget import WorldMap

from global_pulse.core import Store


AT = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
T0 = AT.isoformat()
T1 = (AT + timedelta(days=2)).isoformat()


def report(index: int, *, at=T0, synthetic=True, event_key=None, **updates):
    value = {
        "id": f"map-batch-report-{index}",
        "event_key": event_key or f"map-batch:event-{index}",
        "source_id": "offline-country-map",
        "publisher": "Offline synthetic comparison",
        "title": f"Offline fictional record {index}",
        "summary": "No real public warning or live event",
        "url": f"https://example.invalid/map-batch/{index}",
        "published_at": at,
        "retrieved_at": at,
        "category": "Infrastructure",
        "region": "Fictional test region",
        "country": "United States",
        "latitude": 40 + (index % 10) / 10,
        "longitude": -75 - (index % 10) / 10,
        "synthetic": synthetic,
        "severity": "informational",
        "official": False,
        "kind": "report",
    }
    value.update(updates)
    return value


def slow_projection(store: Store, event_id: str):
    with store._lock:
        event = store._get_event_unlocked(event_id, map_projection=True)
    if event:
        event["retained_on_map"] = False
        event["map_retention_note"] = ""
    return event


def compare_all_to_original(store: Store, *, limit=5000):
    actual = store.list_events(map_evidence=True, limit=limit)
    # Re-run the unchanged candidate/qualification/limit loop with its
    # original per-row projection. Checking returned events alone can miss a
    # silently dropped or reordered newer pending-warning decoy candidate.
    with patch.object(
        store, "_map_evidence_page_unlocked",
        side_effect=lambda page: [
            store._get_event_unlocked(row["id"], map_projection=True) for row in page
        ],
    ):
        original = store.list_events(map_evidence=True, limit=limit)
    assert [item["id"] for item in actual] == [item["id"] for item in original], (
        "Country evidence result length/order and pending candidate eligibility must be exact"
    )
    assert actual == original, "No source identity, area, or report annotation may change"
    for item in actual:
        expected = slow_projection(store, item["id"])
        assert item == expected, (
            "Batch map projection changed source report/status/area/retention "
            f"semantics for event {item['id']}"
        )
    return actual


def test_513_active_sources_match_exact_original_and_use_three_bounded_queries(tmp_path):
    with Store(tmp_path / "batch.sqlite3", mode="synthetic") as store:
        assert len(store.ingest([report(i) for i in range(513)], now=T0)) == 513
        queries = []
        store._conn.set_trace_callback(
            lambda sql: queries.append(sql)
            if "SELECT event_id,body FROM reports WHERE event_id IN" in sql else None
        )
        try:
            with patch.object(store, "_get_event_unlocked",
                              wraps=store._get_event_unlocked) as slow:
                actual = store.list_events(map_evidence=True, limit=513)
                assert slow.call_count == 0, "Ordinary stable events need no N+1 slow reads"
            assert len(actual) == 513
            assert len(queries) == 3, "256+256+1 selected active events need three bounded scans"
        finally:
            store._conn.set_trace_callback(None)
        assert all(item.get("reports") and item["reports"][0]["source_id"] == "offline-country-map"
                   for item in actual)
        compare_all_to_original(store, limit=513)


def test_future_source_updated_revision_and_expiry_keep_frozen_original_version(tmp_path):
    with Store(tmp_path / "future.sqlite3", mode="synthetic") as store:
        original = report(1)
        changed = store.ingest([original], now=T0)
        identity = changed[0]["id"]
        later = {**original, "summary": "Future source revision deferred",
                 "source_updated_at": T1}
        store.ingest([later], now=T0)
        with patch.object(store, "_get_event_unlocked",
                          wraps=store._get_event_unlocked) as slow:
            actual = store.list_events(map_evidence=True, limit=20)
            assert slow.call_count >= 1, "Deferred latest must use report_revision historical fallback"
        event = next(item for item in actual if item["id"] == identity)
        assert event == slow_projection(store, identity)
        assert event["reports"][0]["summary"] == original["summary"]
        # Clock-only admission of a material source-time transition remains
        # a separate immutable event revision, never an unrecorded GUI advance.
        store.ingest([], now=T1)
        compare_all_to_original(store, limit=20)

        expiring = report(2, expires_at=T1, kind="warning")
        store.ingest([expiring], now=T0)
        compare_all_to_original(store, limit=20)
        store.ingest([], now=T1)
        compare_all_to_original(store, limit=20)


def test_live_non_synthetic_country_reports_and_merged_mega_event_are_not_truncated(tmp_path):
    with Store(tmp_path / "live.sqlite3", mode="live") as store:
        changed = store.ingest([report(i, synthetic=False) for i in range(5)], now=T0)
        assert len(changed) == 5
        actual = compare_all_to_original(store)
        assert len(actual) == 5
        assert all(item["reports"][0]["synthetic"] is False for item in actual)

    with Store(tmp_path / "mega.sqlite3", mode="synthetic") as store:
        reports = [report(2000 + i, event_key="large-shared-map-event") for i in range(70)]
        store.ingest(reports, now=T0)
        with patch.object(store, "_get_event_unlocked",
                          wraps=store._get_event_unlocked) as slow:
            actual = store.list_events(map_evidence=True, limit=20)
            assert slow.call_count >= 1, "Large event must take bounded legacy per-event path"
        assert len(actual) == 1 and actual[0]["report_count"] == 70
        compare_all_to_original(store, limit=20)


def test_report_count_tampering_falls_back_without_dropping_source_evidence(tmp_path):
    with Store(tmp_path / "tampered.sqlite3", mode="synthetic") as store:
        changed = store.ingest([report(8080)], now=T0)
        identity = changed[0]["id"]
        with store._lock, store._conn:
            row = store._conn.execute(
                "SELECT body FROM events WHERE id=?", (identity,)
            ).fetchone()
            event = json.loads(row["body"])
            event["report_count"] = 0  # Intentionally stale/corrupt denormalized claim.
            store._conn.execute(
                "UPDATE events SET body=? WHERE id=?",
                (json.dumps(event, sort_keys=True, separators=(",", ":")), identity),
            )
        with patch.object(store, "_get_event_unlocked",
                          wraps=store._get_event_unlocked) as slow:
            actual = store.list_events(map_evidence=True, limit=20)
            assert slow.call_count >= 1, "Actual source count mismatch must use old path"
        assert len(actual) == 1
        assert len(actual[0]["reports"]) == 1
        compare_all_to_original(store, limit=20)


def test_live_country_category_circle_preserves_searchable_source_reports(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = None
    with Store(tmp_path / "country-live.sqlite3", mode="live") as store:
        assert store.ingest([
            report(81, synthetic=False, category="Infrastructure",
                   latitude=None, longitude=None),
        ], now=T0)
        evidence = compare_all_to_original(store, limit=100)
        widget = WorldMap()
        try:
            widget.set_events([], country_events=evidence)
            app.processEvents()
            circles = widget.country_category_evidence_for("United States")
            assert circles.get("count") == 1, (
                "Neutral country-category circle must still expose official-location "
                "independent source attribution"
            )
            assert circles["categories"].get("Infrastructure") == 1
            searchable = [
                source.get("title", "") + " " + source.get("summary", "")
                for event in circles["events"]
                for source in event.get("reports", [])
            ]
            assert any("Offline fictional record 81" in value for value in searchable), (
                "Country circle search must retain full source records, not only "
                "active aggregate labels"
            )
        finally:
            widget.close()
            widget.deleteLater()
            app.processEvents()
