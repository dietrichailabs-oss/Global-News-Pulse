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
from datetime import datetime, timedelta, timezone
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


class _TimedStoreLock:
    """Measure real Store RLock wait/ownership without shortening any test gate.

    The backing lock is unchanged, including reentrance and nonblocking probes.
    Account for lock hold time only at the outermost release, so worker/GUI
    contention and expensive in-lock SQL can be distinguished.
    """
    def __init__(self, backing, gui_thread, phase):
        self._backing = backing
        self._gui_thread = gui_thread
        self._phase = phase
        self._ownership = {}
        self.waits = defaultdict(list)
        self.holds = defaultdict(list)
        self.slowest = []

    def acquire(self, blocking=True, timeout=-1):
        started = time.perf_counter()
        acquired = self._backing.acquire(blocking, timeout)
        elapsed = (time.perf_counter() - started) * 1000
        tid = threading.get_ident()
        side = "GUI" if tid == self._gui_thread else "worker"
        key = self._phase["value"] + ":" + side
        self.waits[key].append(elapsed)
        if acquired:
            if tid in self._ownership:
                began, depth, caller = self._ownership[tid]
                self._ownership[tid] = (began, depth + 1, caller)
            else:
                # Frame inspection is constant-time and avoids logging URLs,
                # source records, or any private archive content.
                import sys
                frame = sys._getframe(1)
                caller = (frame.f_back.f_code.co_name if frame.f_code.co_name == "__enter__"
                          else frame.f_code.co_name)
                self._ownership[tid] = (time.perf_counter(), 1, caller)
        if elapsed > 20:
            # A GUI lock delay alone does not locate the source-level
            # offender. Capture only method names from the actual call chain:
            # no source bytes, file paths, report content, or arbitrary data.
            import sys
            frame = sys._getframe(1)
            callsite = []
            for _ in range(5):
                if frame is None:
                    break
                callsite.append(frame.f_code.co_name)
                frame = frame.f_back
            self.slowest.append({"kind": "wait", "thread": key,
                                 "ms": round(elapsed, 3),
                                 "callsite": callsite})
        return acquired

    def release(self):
        tid = threading.get_ident()
        began, depth, caller = self._ownership[tid]
        if depth == 1:
            elapsed = (time.perf_counter() - began) * 1000
            key = self._phase["value"] + ":" + (
                "GUI" if tid == self._gui_thread else "worker")
            self.holds[key].append(elapsed)
            if elapsed > 20:
                self.slowest.append({"kind": "hold", "thread": key,
                                     "method": caller, "ms": round(elapsed, 3)})
            del self._ownership[tid]
        else:
            self._ownership[tid] = (began, depth - 1, caller)
        self._backing.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()



def test_idle_feed_cache_rejects_source_change_scope_and_backward_cutoff(tmp_path):
    """Only an unchanged stored revision may avoid rehydrating source records."""
    store=Store(tmp_path / "idle-source-cache.sqlite", mode="synthetic")
    try:
        assert len(store.ingest(_reports(130))) == 130
        events=store.list_events(limit=130)
        before=store.content_revision()
        old_since=(datetime.now(timezone.utc)-__import__("datetime").timedelta(days=7)).isoformat()
        newer_since=(datetime.now(timezone.utc)-__import__("datetime").timedelta(days=6)).isoformat()
        scope=("","", "", 1, 1000)
        filters={"query":"","category":"","region":"","limit":130,"since":old_since}
        cache={"revision":before,"scope":scope,"filters":filters,
               "feed":tuple(events),"filter_options":{"category":[],"region":[]}}
        assert MainWindow._unchanged_source_feed(
            cache,before,scope,filters) == events
        narrowed={**filters,"since":newer_since}
        assert MainWindow._unchanged_source_feed(
            cache,before,scope,narrowed) == [
                e for e in events if e["updated_at"] >= newer_since]
        assert MainWindow._unchanged_source_feed(
            cache,before,scope,{**filters,"since":"2000-01-01T00:00:00+00:00"}) is None
        assert MainWindow._unchanged_source_feed(
            cache,before,("different",),filters) is None
        assert MainWindow._unchanged_source_feed(
            cache,before,scope,{**filters,"category":"Conflict"}) is None
        # A real Store change must never reuse previous archive evidence.
        assert store.ingest([{
            **_reports(1)[0], "id":"new-source-evidence",
            "event_key":"new-source-evidence",
        }])
        assert MainWindow._unchanged_source_feed(
            cache,store.content_revision(),scope,filters) is None
    finally:
        store.close()



def test_observation_readthrough_cache_preserves_corrections_and_independence(tmp_path):
    """Exact revision token permits memoization, never stale Economy source."""
    store=Store(tmp_path / "observation-cache.sqlite", mode="synthetic")
    try:
        original=_observations(4)
        assert store.put_observations(original) == 4
        first=store.list_observations()
        assert store._observation_cache is not None
        token=store._observation_cache[0]
        again=store.list_observations()
        assert first==again
        assert again is not first and again[0] is not first[0]
        again[0]["value"] = -99999
        if again[0]["revisions"]:
            again[0]["revisions"][0]["value"] = -99999
        assert store.list_observations()==first
        correction={**original[0],"value":original[0]["value"]+9}
        assert store.put_observations([correction]) == 1
        changed=store.list_observations()
        assert store._observation_cache is not None
        assert store._observation_cache[0] != token
        assert changed != first
        assert changed==store.list_observations()
        assert store.list_observations(country="Test Country 000") == [
            item for item in changed if item["country"]=="Test Country 000"]
    finally:
        store.close()




def test_noop_country_evidence_reuses_complete_revision_only(tmp_path):
    """Actual Store reports; moving cutoff is safe only for stable full pages."""
    store = Store(tmp_path / "country-noop.sqlite", mode="synthetic")
    try:
        assert len(store.ingest(_reports(9))) == 9
        old_since=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        new_since=(datetime.now(timezone.utc)-timedelta(hours=23)).isoformat()
        scope=("", "", "", 0, 1000)
        filters={"query":"","category":"","region":"","limit":5000,
                 "since":old_since,"map_view":True,"keep_significant":True}
        events=store.list_events(**dict(filters,map_evidence=True))
        assert len(events)==9
        token=store.content_revision()
        cache={"revision":token,"scope":scope,"filters":filters,
               "events":tuple(events)}
        current=MainWindow._unchanged_country_evidence(
            cache,token,scope,{**filters,"since":new_since})
        assert current is not None
        assert [e["id"] for e in current]==[e["id"] for e in events]
        assert all(a is not b for a,b in zip(current,events))
        assert all(not e["retained_on_map"] for e in current)
        # Source/datetime changes NEVER mutate the original cached evidence.
        assert all(not e["retained_on_map"] for e in events)
        old_event=dict(events[0],updated_at=old_since)
        crossing=dict(cache,events=(old_event,*events[1:]))
        trimmed=MainWindow._unchanged_country_evidence(
            crossing,token,scope,{**filters,"since":new_since})
        assert trimmed is not None
        assert events[0]["id"] not in [e["id"] for e in trimmed]
        important=dict(old_event,severity="critical")
        crossing=dict(cache,events=(important,*events[1:]))
        retained=MainWindow._unchanged_country_evidence(
            crossing,token,scope,{**filters,"since":new_since})
        assert retained is not None and retained[0]["retained_on_map"]
        assert retained[0]["map_retention_note"].startswith("Retained significant")
        assert not important.get("retained_on_map")
        # Complete page and unchanged query are mandatory. A capped page,
        # backwards cutoff, new country/filter, or temporal warning cannot
        # inherit old source evidence.
        assert MainWindow._unchanged_country_evidence(
            cache,token,scope,{**filters,"limit":9,"since":new_since}) is None
        assert MainWindow._unchanged_country_evidence(
            cache,token,scope,{**filters,"since":old_since[:10]}) is None
        assert MainWindow._unchanged_country_evidence(
            cache,token,("new-scope",),filters) is None
        assert MainWindow._unchanged_country_evidence(
            cache,token,scope,{**filters,"category":"Conflict"}) is None
        for extra in ({"map_areas":[{"type":"Polygon"}]},
                      {"status":"pending"},
                      {"map_history_incomplete":True},
                      {"evidence_policy_version":1},
                      {"reports":[{**events[0]["reports"][0],
                                  "expires_at":"2026-11-19T00:00:00Z"}]}):
            unsafe=dict(cache,events=(dict(events[0],**extra),*events[1:]))
            assert MainWindow._unchanged_country_evidence(
                unsafe,token,scope,filters) is None
        # Actual persisted ingest changes revision: no read-through allowed.
        assert store.ingest([{
            **_reports(1)[0],"id":"new-map-evidence",
            "event_key":"new-map-evidence",
        }])
        assert MainWindow._unchanged_country_evidence(
            cache,store.content_revision(),scope,filters) is None
    finally:
        store.close()

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
        # Instrument the *real* Store lock after fixture ingest. No mocked
        # archive results, no delay changes and no weakened 7.2s requirement.
        traced_lock = _TimedStoreLock(controller.store._lock, gui_thread_id, phase)
        controller.store._lock = traced_lock
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
            # If the exact 7.2-second gate is missed, report where the real
            # source worker is *right now* without extending the deadline,
            # changing test assertions or printing any source data/paths.
            import sys
            worker_stack_at_deadline = []
            for worker in threading.enumerate():
                if worker.name != "pulse-idle-evidence" or worker.ident is None:
                    continue
                frame = sys._current_frames().get(worker.ident)
                while frame is not None and len(worker_stack_at_deadline) < 12:
                    worker_stack_at_deadline.append(frame.f_code.co_name)
                    frame = frame.f_back
                break
            result = {
                "worker_stack_at_deadline": worker_stack_at_deadline,
                "worker_inflight_at_deadline": window._idle_snapshot_inflight,
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
                "store_rlock_wait": {
                    key: _stats(samples) for key, samples in sorted(traced_lock.waits.items())
                },
                "store_rlock_outer_hold": {
                    key: _stats(samples) for key, samples in sorted(traced_lock.holds.items())
                },
                "store_rlock_slowest_waits_and_holds": sorted(
                    traced_lock.slowest, key=lambda x: x["ms"], reverse=True
                )[:12],
            }
            print("PULSE_STARTUP_IDLE_PROFILE=" + json.dumps(result, sort_keys=True), flush=True)
            assert len(heartbeat) >= 40, "Main-thread heartbeat did not run"
            assert methods["idle:_refresh_evidence_when_idle"], "No collector-triggered idle evidence revision"
            assert methods["idle:refresh_data"], "No real idle full refresh after collector signals"
            assert not worker_methods.get("idle:Store.list_events:country_evidence"), (
                "Unchanged complete map source re-read during no-click collector NO-OP")
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
