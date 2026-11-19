"""Issue22: no-click country/dated-economy evidence index runs off the Qt thread.

These use fictional offline reports, no network/media, and do not certify a
physical Windows 11 latency or rights/release state.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse import map_widget
from global_pulse.controller import Controller
from global_pulse.crisis_overlay import build_country_activity, normalize_country
from global_pulse.ui import MainWindow


def _report(i, category="Health", *, synthetic=False):
    at = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"source-index-{i}",
        "event_key": f"source-index:{i}",
        "title": f"FICTIONAL offline {category} source report {i}",
        "summary": "Fictional test only; not a live country situation",
        "country": "Ukraine", "country_basis": "explicit_record",
        "source_id": "offline-index-test", "publisher": "Fictional test",
        "url": f"https://example.invalid/index/{i}",
        "published_at": at, "retrieved_at": at,
        "region": "Europe", "category": category,
        "synthetic": synthetic, "severity": "unassessed",
    }


def _observations():
    return [{"country_name": "Ukraine", "country_code": "",
             "indicator": "fictional_growth", "indicator_name": "Fictional growth",
             "observation_date": "2025-12-01", "value": 2.0,
             "source_id": "offline-index-test", "synthetic": True}]


def _country_rows(world):
    return tuple({"name": str(c["name"]), "code": str(c.get("code") or "")}
                 for c in world._countries)


def _summary(world):
    return {
        "activity": world.country_activity,
        "neutral": world.country_only_evidence,
        "categories": world.country_category_evidence,
        "economy": world.economic_observations,
        "coverage_points": world._coverage_points,
        "coverage_unlocated": world._coverage_unlocated,
        "footer": world._footer_point_count,
    }


def _clean_world(app, world):
    world.close()
    world.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_exact_worker_index_matches_direct_and_skips_gui_rebuild(monkeypatch):
    app = QApplication.instance() or QApplication([])
    world = map_widget.WorldMap()
    records = [_report(i, "Health" if i % 2 else "Conflict") for i in range(90)]
    observations = _observations()
    country = normalize_country("Ukraine")
    try:
        world.set_events(records, country_events=records, observations=observations)
        expected = _summary(world)
        assert expected["categories"][country]["count"] == 90
        assert expected["economy"][country]["count"] == 1
        assert expected["neutral"] is not None

        credits = set()
        classified = build_country_activity(
            records, now=datetime.now(timezone.utc), single_record_credits=credits)
        rows = _country_rows(world)
        indexed = map_widget.prepare_country_evidence(
            records, observations, rows, credits, None)
        prepared = {
            "category_key": None,
            "record_ids": tuple(id(record) for record in records),
            "observation_ids": tuple(id(row) for row in observations),
            "country_rows": rows,
            "activity": classified,
            "credits": credits,
            "evidence_index": indexed,
        }
        calls = []
        original = map_widget.prepare_country_evidence

        def tracked(*args, **kwargs):
            calls.append(threading.get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(map_widget, "prepare_country_evidence", tracked)
        world.set_events(records, country_events=records, observations=observations,
                         preclassified_country=prepared)
        assert not calls, "Source-identical prepared country index reran on Qt"
        assert _summary(world) == expected
        assert world._pending_preclassified_country is None
        assert world._pending_observation_ids is None

        # A changed map filter must rebuild both crisis and neutral source
        # categories from the new selected evidence rather than reuse old rings.
        world.categories = {"Health"}
        world.set_events(records, country_events=records, observations=observations,
                         preclassified_country=prepared)
        assert len(calls) == 1
        assert world.country_category_evidence[country]["count"] == 45
        assert set(world.country_category_evidence[country]["categories"]) == {"Health"}

        # Identity changes in source evidence or dated observation objects
        # cannot inherit an index from a different worker snapshot.
        world.categories = None
        copied = [dict(record) for record in records]
        world.set_events(copied, country_events=copied, observations=observations,
                         preclassified_country=prepared)
        assert len(calls) == 2
        world.set_events(records, country_events=records,
                         observations=[dict(item) for item in observations],
                         preclassified_country=prepared)
        assert len(calls) == 3
        assert _summary(world) == expected
    finally:
        _clean_world(app, world)


def test_idle_snapshot_builds_country_and_economy_indexes_on_worker(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        controller.store.ingest([_report(i, synthetic=True) for i in range(80)])
        controller.store.put_observations(_observations())
        window = MainWindow(controller)
        window.refresh_data()
        assert window.prepare_initial_workspaces()
        window._workspace_warm_timer.stop()
        gui_id = threading.get_ident()
        calls = []
        original = map_widget.prepare_country_evidence

        def tracked(*args, **kwargs):
            calls.append(threading.get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(map_widget, "prepare_country_evidence", tracked)
        window._last_navigation_at = time.monotonic() - 5
        window._last_full_refresh_at = time.monotonic() - 10
        window._start_idle_snapshot()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (not calls or window._idle_snapshot_inflight):
            app.processEvents()
            QTest.qWait(20)
        assert calls and not window._idle_snapshot_inflight
        assert all(thread_id != gui_id for thread_id in calls), calls
        assert len(window.world_map.evidence_events) == 80
        assert window.world_map.economic_observations, "Dated economy layer lost"
        assert not controller.monitoring
    finally:
        if window is not None:
            window._force_close = True
            for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                         "_collection_refresh_timer", "search_timer"):
                getattr(window, name).stop()
            window.media.shutdown()
            window.close()
        controller.close()
        if window is not None:
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
