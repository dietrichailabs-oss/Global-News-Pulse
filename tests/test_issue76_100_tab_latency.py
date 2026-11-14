"""Issue76 Engineering diagnostic: actual Qt/SQLite 820-record, 100-cycle tab latency.

This is a real desktop/offscreen Qt test, not independent QA and not physical
Windows 11 acceptance. It does not connect to any publisher or start media.
It measures synchronous navigation work while guarding source/bookmark state.
"""
from __future__ import annotations

import os
import statistics
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _pct(values, percentile):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))]


def test_820_record_100_cycle_star_tabs_camera_media_without_reloading_map(tmp_path, monkeypatch, capsys):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        now = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        categories = ("Disaster", "Conflict", "Health", "Government", "Economy", "Unrest")
        records = [
            dict(
                id=f"issue76-latency-{i}", source_id="offline-benchmark",
                publisher="SYNTHETIC QA", title=f"SYNTHETIC {categories[i % 6]} story {i}",
                event_key=f"issue76-latency:{i}", summary="Offline synthetic latency sample",
                url=f"https://example.org/latency/{i}", published_at=now,
                retrieved_at=now, category=categories[i % 6], region="Global",
                country="", synthetic=True, severity="unassessed",
            )
            for i in range(820)
        ]
        controller.store.ingest(records)
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.feed_list.count() > 0
        window.feed_list.setCurrentRow(0)
        app.processEvents()
        selected_id = window._selected_id
        assert selected_id
        # Warm each page ONCE; measure 100 subsequent rapid navigation rounds.
        for page in (1, 2, 3, 4, 5, 0):
            window.open_page(page)
        app.processEvents()

        rebuilds = {name: 0 for name in (
            "_populate_situations", "_populate_economy", "_populate_sources",
            "_populate_alerts", "_generate_brief"
        )}
        for name in list(rebuilds):
            original = getattr(window, name)
            def tracked(*args, _name=name, _original=original, **kwargs):
                rebuilds[_name] += 1
                return _original(*args, **kwargs)
            monkeypatch.setattr(window, name, tracked)

        unexpected_map_reloads = []
        original_map = window.world_map.set_events
        def map_spy(*args, **kwargs):
            unexpected_map_reloads.append(True)
            return original_map(*args, **kwargs)
        monkeypatch.setattr(window.world_map, "set_events", map_spy)

        durations = {page: [] for page in (0, 1, 2, 3, 4, 5)}
        for round_no in range(100):
            if round_no % 10 == 0:
                # A legitimate Star/Unstar changes ONLY situations state.
                controller.set_situation_saved(selected_id, (round_no // 10) % 2 == 0)
            if round_no % 20 == 0:
                # A native delivery update changes ONLY Alerts/tray status.
                controller.notification_changed.emit()
            for page in (1, 2, 3, 4, 5, 0):
                started = time.perf_counter()
                window.open_page(page)
                app.processEvents()
                durations[page].append((time.perf_counter() - started) * 1000.0)
            assert window._selected_id == selected_id
            assert window.pages.currentIndex() == 0

        # Printing each page separately distinguishes expensive hidden work
        # from real selected-page rebuilds. Do not claim a physical Win11 p95.
        for page, label in (
            (0, "Monitor / map"), (1, "Starred / Situations"),
            (2, "Economy"), (3, "Sources"), (4, "Alerts"),
            (5, "World Brief")
        ):
            data = durations[page]
            print(f"ISSUE76_ACTUAL_QT_100SWITCH page={page} name={label!r} "
                  f"samples={len(data)} median_ms={statistics.median(data):.3f} "
                  f"p95_ms={_pct(data, .95):.3f} max_ms={max(data):.3f}")
        print(f"ISSUE76_REBUILDS {rebuilds} unexpected_map_reloads={len(unexpected_map_reloads)}")

        assert sum(len(data) for data in durations.values()) == 600
        assert not unexpected_map_reloads, "Star/notification/tab changes unexpectedly reloaded the 5k map"
        assert rebuilds["_populate_economy"] == 0
        assert rebuilds["_populate_sources"] == 0
        assert rebuilds["_generate_brief"] == 0
        # Ten bookmark updates, five alert notifications: actual dirty pages
        # must refresh once on their next visit, and not once per tab click.
        assert rebuilds["_populate_situations"] == 10
        assert rebuilds["_populate_alerts"] == 5
        state = controller.store.saved_situation_ids()
        assert selected_id not in state  # final (round 90) toggle is Unstar
    finally:
        if window is not None:
            window._force_close = True
            window.close()
            window.deleteLater()
        controller.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
