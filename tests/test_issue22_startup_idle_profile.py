"""Issue22 owner baseline: first paint and no-click startup/idle responsiveness.

Actual Qt event-loop callbacks and actual bounded SQLite/store/chart work on a
synthetic 820-report/3,200-observation archive. Never collect news, open media,
play audio, or imply a physical Windows 11 pass from hosted test timings.
"""
from __future__ import annotations

import json
import os
import statistics
import threading
import time
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import global_pulse.provider_actions as provider_actions
from global_pulse.__main__ import prepare_initial_dashboard, show_initializing
from global_pulse.controller import Controller
from global_pulse.core import Store
from global_pulse.map_widget import WorldMap
from global_pulse.ui import EconomicChart, EconomicTableModel, MainWindow


def _observations(count=3200):
    return [
        {
            "indicator": "synthetic_inflation" if i % 2 else "synthetic_growth",
            "indicator_name": "Synthetic economic observation",
            "country": f"Test Country {i % 120:03d}",
            "date": str(2010 + (i % 16)),
            "value": float(i % 200) / 4,
            "source_id": "synthetic-offline",
            "url": f"https://example.invalid/source/{i}",
            "synthetic": True,
        }
        for i in range(count)
    ]


def _reports(count=820):
    at = datetime.now(timezone.utc).isoformat()
    categories = ("Disaster", "Conflict", "Health", "Economy", "News")
    return [
        {
            "id": f"idle-fixture-{i}",
            "event_key": f"idle-fixture:{i}",
            "title": f"SYNTHETIC idle profile {categories[i % 5]} {i}",
            "summary": "Offline synthetic test; not a real-world finding",
            "source_id": "synthetic-offline",
            "publisher": "Synthetic Qt fixture",
            "url": f"https://example.invalid/fixture/{i}",
            "published_at": at, "retrieved_at": at,
            "country": "", "region": "Global", "category": categories[i % 5],
            "synthetic": True, "severity": "unassessed",
        }
        for i in range(count)
    ]


def _stats(samples):
    values = sorted(samples)
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(values[min(len(values)-1, (95*len(values)+99)//100-1)], 3),
        "max_ms": round(values[-1], 3),
    }


def _close(app, window, controller, splash=None):
    if splash is not None:
        splash.close()
    if window is not None:
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer"):
            getattr(window, name).stop()
        window._force_close = True
        window.media.shutdown()
        window.close()
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_economy_idle_warm_renders_one_model_and_manual_dropdown_wins(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        records = _observations(200)
        assert controller.store.put_observations(records) == 200
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        window.open_page(0)
        window.refresh_data()
        window._workspace_warm_timer.stop()
        assert 2 in window._dirty_pages

        west = "Test Country 007"
        window._open_economic_country(west)
        assert window._pending_economic_country == west
        counts = {"chart": 0, "model": 0}
        chart_original = window.economic_chart.set_observations
        model_original = window.economy_model.set_observations

        def chart(*args, **kwargs):
            counts["chart"] += 1
            return chart_original(*args, **kwargs)

        def model(*args, **kwargs):
            counts["model"] += 1
            return model_original(*args, **kwargs)

        with monkeypatch.context() as m:
            m.setattr(window.economic_chart, "set_observations", chart)
            m.setattr(window.economy_model, "set_observations", model)
            window._last_navigation_at = time.monotonic() - 3
            window._warm_next_workspace()
            window._workspace_warm_timer.stop()
        assert counts == {"chart": 1, "model": 1}, counts
        assert window._pending_economic_country is None
        assert window.economy_country.currentText() == west
        assert window.economy_model.rowCount() > 0

        # The user changes the country from the still-visible dropdown after
        # a newer map click has queued a different country while dirty.
        window.open_page(0)
        window.refresh_data()
        window._workspace_warm_timer.stop()
        assert 2 in window._dirty_pages
        window._open_economic_country("Test Country 010")
        assert window._pending_economic_country is not None
        east_index = window.economy_country.findText("Test Country 011")
        assert east_index > 0
        window.economy_country.setCurrentIndex(east_index)
        assert window._pending_economic_country is None
        window._last_navigation_at = time.monotonic() - 3
        window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert window.economy_country.currentText() == "Test Country 011"
        assert window.economy_model.rowCount() > 0
    finally:
        _close(app, window, controller)


def test_heavy_first_paint_and_post_splash_no_click_heartbeat(tmp_path):
    """Do not click a tab or open YouTube during the measured idle window."""
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = splash = None
    phase = {"value": "startup"}
    # The old profile counted worker-thread SQL in a dictionary labelled
    # "synchronous_main_thread_operations". That mislabeled a slow worker read
    # as a Qt event-loop stall; keep the measured timings but split ownership.
    gui_thread_id = threading.get_ident()
    methods = defaultdict(list)
    worker_methods = defaultdict(list)

    def trace_method(cls, name, stack):
        original = getattr(cls, name)

        def timed(self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return original(self, *args, **kwargs)
            finally:
                label = (name if cls in (MainWindow, EconomicChart, EconomicTableModel)
                         else cls.__name__ + "." + name)
                # Attribute each real worker read separately: a single slow
                # Store.list_events aggregate hides whether feed, sourced
                # country-area projection, or point-map SQL is the bottleneck.
                # Keep the same timed call and unchanged no-click assertions.
                if cls in (Store, Controller) and name in ("list_events", "events"):
                    kind = ("country_evidence" if kwargs.get("map_evidence")
                            else "point_map" if kwargs.get("map_view") else "feed")
                    label += ":" + kind
                bucket = (methods if threading.get_ident() == gui_thread_id
                          else worker_methods)
                bucket[phase["value"] + ":" + label].append(
                    (time.perf_counter() - started) * 1000
                )
        stack.enter_context(patch.object(cls, name, timed))

    try:
        assert len(controller.store.ingest(_reports())) >= 800
        assert controller.store.put_observations(_observations()) == 3200
        splash = show_initializing(app)
        with ExitStack() as stack:
            for name in (
                "refresh_data", "_warm_next_workspace",
                "_refresh_evidence_when_idle", "_populate_workspace",
                "_refresh_source_status_ui", "_populate_economy",
                "_populate_sources", "_populate_alerts",
                "_populate_situations", "_generate_brief",
            ):
                trace_method(MainWindow, name, stack)
            for name in ("_populate_feed", "_populate_filter_options",
                         "_update_world_overview", "_sync_map_controls"):
                trace_method(MainWindow, name, stack)
            for name in ("set_events", "coverage_summary", "_refresh_country_activity"):
                trace_method(WorldMap, name, stack)
            # Determine whether hidden Sources prewarm is waiting for the
            # Store lock, computing catalog fingerprints or spending time in
            # Qt row/header layout. No fabricated heartbeat thresholds.
            for name in ("list_events", "list_observations",
                         "list_source_states", "content_revision",
                         "event_filter_options", "_map_evidence_page_unlocked",
                         "_get_event_unlocked"):
                trace_method(Store, name, stack)
            for name in ("events", "get_setting"):
                trace_method(Controller, name, stack)
            for name in ("populate_sources", "_catalog_fingerprint",
                         "_effective", "_existing_source_rows", "capability"):
                trace_method(provider_actions, name, stack)
            trace_method(EconomicChart, "set_observations", stack)
            trace_method(EconomicTableModel, "set_observations", stack)
            started = time.perf_counter()
            window = MainWindow(controller)
            constructor_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            assert prepare_initial_dashboard(app, splash, window, controller)
            priming_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            window.show()
            splash.finish(window)
            app.processEvents()
            first_visible_ms = (time.perf_counter() - started) * 1000
            assert window._background_warm_enabled
            assert not window._dirty_pages.intersection(range(1, 6))
            assert window.media.camera.camera is None
            assert not controller.monitoring

            phase["value"] = "idle"
            tick_marks = []
            ticker = QTimer()
            ticker.setInterval(16)
            ticker.timeout.connect(lambda: tick_marks.append(time.perf_counter()))
            def collected():
                # The real worker writes occur outside the GUI in production;
                # exercise only real GUI signal delivery, coalescing and
                # subsequent Store/map revisions, without a synthetic GUI
                # thread database write.
                for _ in range(40):
                    controller.evidence_changed.emit()
                    controller.source_status_changed.emit()
            ticker.start()
            QTimer.singleShot(75, collected)
            QTest.qWait(7200)
            ticker.stop()
            heartbeat = [(b-a)*1000 for a, b in zip(tick_marks, tick_marks[1:])]
            result = {
                "synthetic_archive_reports": 820,
                "synthetic_economy_observations": 3200,
                "media_opened": False,
                "collector_network_started": False,
                "first_window_construction_ms": round(constructor_ms, 3),
                "splash_preparation_ms": round(priming_ms, 3),
                "first_visible_paint_ms": round(first_visible_ms, 3),
                "idle_16ms_heartbeat": _stats(heartbeat),
                "synchronous_main_thread_operations": {
                    key: _stats(samples) for key, samples in sorted(methods.items())
                },
                "background_worker_operations": {
                    key: _stats(samples) for key, samples in sorted(worker_methods.items())
                },
            }
            print("PULSE_STARTUP_IDLE_PROFILE=" + json.dumps(result, sort_keys=True), flush=True)
            assert len(heartbeat) >= 40, "Main-thread heartbeat did not run"
            assert methods["idle:_refresh_evidence_when_idle"], "No collector-triggered idle evidence revision"
            assert methods["idle:refresh_data"], "No real idle full refresh after collector signals"
            # A no-click post-splash source update may read SQLite on its own
            # worker, never block the Qt GUI thread with these archive scans.
            assert not methods.get("idle:Store.list_observations"), (
                "No-click Economy observations queried synchronously on Qt")
            assert not methods.get("idle:Store.list_events"), (
                "No-click archive events queried synchronously on Qt")
            assert worker_methods.get("idle:Store.list_observations"), (
                "Did not exercise the actual background observations path")
            assert not controller.monitoring
            assert window.media.camera.camera is None
    finally:
        _close(app, window, controller, splash)
