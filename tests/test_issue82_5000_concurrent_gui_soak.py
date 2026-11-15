"""Diagnostic-only 500-feed / 5,000-map SQLite + real Qt concurrent soak.

All reports and positions are fictional test fixtures. This records raw host
timings, not physical Windows 11 acceptance or a hardware-specific PASS gate.
No network, playback, native notification or public build is performed here.
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def fixture_report(index: int, now: str) -> dict:
    return {
        "id": f"fictional-gui-soak-{index}",
        "event_key": f"fictional-gui-soak:event-{index}",
        "title": f"SYNTHETIC Qt performance fixture {index}",
        "summary": "Offline synthetic evidence only, not a real incident",
        "source_id": "offline-qt-performance-catalog",
        "publisher": "SYNTHETIC local-only test publisher",
        "url": f"https://example.invalid/qt-soak/{index}",
        "published_at": now,
        "retrieved_at": now,
        "country": "United States",
        "region": "Synthetic test coordinates",
        "category": "Infrastructure",
        "latitude": 25 + (index % 50) * 0.6,
        "longitude": -125 + ((index // 50) % 100) * 0.6,
        "synthetic": True,
        "official": False,
        "severity": "informational",
        "kind": "report",
    }


def distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)], 2),
        "max_ms": round(ordered[-1], 2),
    }


def test_real_5000_map_qt_heartbeat_with_worker_updates_and_tabs(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    heartbeat = QTimer()
    pages = QTimer()
    metrics = {
        "qt_backend": os.environ.get("QT_QPA_PLATFORM", ""),
        "host_os": platform.system(),
        "seed_events": 5000,
        "worker_revisions_requested": 10,
    }
    writer_errors = []
    try:
        now = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        changed = []
        # Each source callback is bounded at MAX_BATCH=2000 by the real Store.
        for offset in range(0, 5000, 2000):
            changed.extend(controller.store.ingest(
                [fixture_report(i, now) for i in range(offset, min(offset + 2000, 5000))]
            ))
        metrics["seed_sqlite_ms"] = round((time.perf_counter() - started) * 1000, 2)
        assert len(changed) == 5000, "Admission-safe batches must seed 5k events"
        started = time.perf_counter()
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        metrics["first_full_ui_ms"] = round((time.perf_counter() - started) * 1000, 2)
        assert len(window._events) == 500, "Exercise the actual 500-row feed cap"
        assert len(window.world_map.events) == 5000, "Exercise all 5k map entries"

        # Time actual production calls and preserve their output. This is
        # instrumentation, not a stub: every SQLite read, feed item and map
        # composition still runs.
        phase_times = defaultdict(list)
        def instrument(target, method, label):
            original = getattr(target, method)
            def timed(*args, **kwargs):
                at = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    phase_times[label].append((time.perf_counter() - at) * 1000)
            setattr(target, method, timed)

        actual_events = controller.events
        def measured_events(*args, **kwargs):
            label = ("country_projection" if kwargs.get("map_evidence") else
                     "point_map_query" if kwargs.get("map_view") else "feed_query")
            at = time.perf_counter()
            try:
                return actual_events(*args, **kwargs)
            finally:
                phase_times[label].append((time.perf_counter() - at) * 1000)
        controller.events = measured_events
        for target, method, label in (
            (controller.store, "list_observations", "observations_query"),
            (controller, "headline_view", "headline_view"),
            (window, "_populate_feed", "feed_row_build"),
            (window, "_populate_filter_options", "filter_options"),
            (window, "_update_world_overview", "overview_html"),
            (window, "_sync_map_controls", "map_controls"),
            (window, "_populate_sources", "source_tab_build"),
            (window, "_populate_economy", "economy_tab_build"),
        ):
            instrument(target, method, label)

        map_times = []
        original_map = window.world_map.set_events
        def measured_map(*args, **kwargs):
            at = time.perf_counter()
            try:
                return original_map(*args, **kwargs)
            finally:
                map_times.append((time.perf_counter() - at) * 1000)
        window.world_map.set_events = measured_map

        gaps = []
        last_beat = [None]
        def beat():
            at = time.perf_counter()
            if last_beat[0] is not None:
                gaps.append((at - last_beat[0]) * 1000)
            last_beat[0] = at
        heartbeat.setInterval(16)
        heartbeat.timeout.connect(beat)

        tab_times = []
        targets = [0, 3, 2, 0]
        page_number = [0]
        def switch_page():
            at = time.perf_counter()
            window.open_page(targets[page_number[0] % len(targets)])
            tab_times.append((time.perf_counter() - at) * 1000)
            page_number[0] += 1
        pages.setInterval(120)
        pages.timeout.connect(switch_page)

        writer_call_times = []
        def write_real_revisions():
            try:
                for index in range(10):
                    evidence_time = datetime.now(timezone.utc).isoformat()
                    source = {
                        **fixture_report(5100, evidence_time),
                        "id": "fictional-gui-soak-live",
                        "event_key": "fictional-gui-soak:live-revision",
                        "source_id": "offline-qt-live-burst",
                        "title": "SYNTHETIC active revision during Qt soak",
                        "summary": f"Synthetic revised local value {index}",
                    }
                    call_started = time.perf_counter()
                    controller._on_reports(
                        [source], allow_synthetic=True, now=evidence_time
                    )
                    writer_call_times.append((time.perf_counter() - call_started) * 1000)
                    time.sleep(0.1)
            except Exception as error:
                writer_errors.append(f"{type(error).__name__}: {error}")

        heartbeat.start()
        pages.start()
        worker = threading.Thread(target=write_real_revisions, daemon=True)
        started = time.perf_counter()
        worker.start()
        QTest.qWait(4500)
        # Continue pumping GUI timers during any slow writer tail instead of
        # blocking the main thread for up to 60 seconds in worker.join().
        deadline = time.perf_counter() + 60
        while worker.is_alive() and time.perf_counter() < deadline:
            QTest.qWait(50)
        worker.join(timeout=0)
        assert not worker.is_alive(), "Bounded worker must finish and release archive"
        assert not writer_errors, writer_errors
        QTest.qWait(700)
        pages.stop()
        heartbeat.stop()
        app.processEvents()
        metrics["soak_plus_writer_ms"] = round((time.perf_counter() - started) * 1000, 2)

        metrics["heartbeat_gap"] = distribution(gaps)
        metrics["tab_switch_time"] = distribution(tab_times)
        metrics["map_set_events_time"] = distribution(map_times)
        metrics["worker_ingest_call_time"] = distribution(writer_call_times)
        metrics["phases"] = {
            name: {**distribution(values), "total_ms": round(sum(values), 2)}
            for name, values in sorted(phase_times.items())
        }
        metrics["map_count_after"] = len(window.world_map.events)
        metrics["feed_count_after"] = len(window._events)
        with controller.store._lock:
            row = controller.store._conn.execute(
                "SELECT event_id,body FROM reports WHERE source_id=?",
                ("offline-qt-live-burst",),
            ).fetchone()
        assert row, "Actual background report must reach SQLite"
        actual = json.loads(row["body"])
        assert actual["summary"] == "Synthetic revised local value 9"
        stored_event = controller.store.get_event(row["event_id"])
        mapped_event = next(
            (event for event in window.world_map.events
             if event.get("id") == row["event_id"]), None
        )
        metrics["live_event_revision_stored"] = stored_event.get("revision") if stored_event else None
        metrics["live_event_revision_visible"] = mapped_event.get("revision") if mapped_event else None
        assert mapped_event and stored_event
        assert mapped_event.get("revision") == stored_event.get("revision") == 10, (
            "Last worker revision must reach the real map projection"
        )
        assert len(gaps) >= 2, "The GUI heartbeat must actually run"
        assert len(tab_times) >= 2, "Tab navigation must actually execute"
        assert map_times, "Real evidence must cause a real map recomposition"
        assert metrics["map_count_after"] == 5000
        assert metrics["feed_count_after"] == 500
        print("PULSE_5000_CONCURRENT_GUI_SOAK=" + json.dumps(metrics, sort_keys=True), flush=True)
    finally:
        heartbeat.stop()
        pages.stop()
        if window is not None:
            window._force_close = True
            window.media.shutdown()
            window.close()
        controller.close()
        if window is not None:
            window.deleteLater()
        heartbeat.deleteLater()
        pages.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
