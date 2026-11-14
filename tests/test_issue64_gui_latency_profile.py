"""Synthetic SQLite + real Qt desktop latency instrumentation, Engineering only.

Hosted offscreen GUI timings are NOT physical Windows 11 responsiveness,
actual camera streaming, publisher evidence, or independent QA acceptance.
No network requests or auto-playback are initiated by this probe.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone
from urllib.parse import quote

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, QUrl
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow

CATEGORIES = ("Disaster", "Conflict", "Unrest", "Health", "Government",
              "Economy", "Humanitarian", "Infrastructure", "News")


def _reports(count):
    at = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": f"ui-latency-fixture-{i}",
            "event_key": f"ui-latency-fixture:{i}",
            "title": f"SYNTHETIC UI profile {CATEGORIES[i % len(CATEGORIES)]} #{i}",
            "summary": "Fictional offline evidence, never an actual crisis",
            "source_id": "offline-qt-profile",
            "publisher": "SYNTHETIC profile publication",
            "url": f"https://example.invalid/fixture/{i}",
            "published_at": at, "retrieved_at": at,
            "country": "", "region": "Global",
            "category": CATEGORIES[i % len(CATEGORIES)],
            "synthetic": True, "severity": "unassessed",
        } for i in range(count)
    ]


def _measure(app, action):
    """Time synchronous action plus next Qt event-loop turn."""
    fired = []
    timer = QTimer()
    timer.setSingleShot(True)
    start = time.perf_counter()
    timer.timeout.connect(lambda: fired.append((time.perf_counter()-start)*1000))
    timer.start(0)
    action()
    app.processEvents()
    if not fired:
        app.processEvents()
    timer.stop()
    timer.deleteLater()
    assert len(fired) == 1, "Qt event loop did not respond after a UI action"
    return fired[0]


def _summary(samples):
    data = sorted(round(value, 3) for value in samples)
    return {"count": len(data), "median_ms": round(statistics.median(data), 3),
            "p95_ms": data[max(0, (95*len(data)+99)//100-1)],
            "max_ms": data[-1]}


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("archive_size", [180, 820])
def test_archive_world_brief_star_tab_camera_and_media_latency(app, tmp_path, archive_size):
    """Larger real persisted archive crosses the 500-row feed ceiling."""
    controller = Controller(tmp_path, demo=True)
    window = None
    results = {}
    try:
        start = time.perf_counter()
        controller.store.ingest(_reports(archive_size))
        results["sqlite_ingest_ms"] = round((time.perf_counter()-start)*1000, 3)
        start = time.perf_counter()
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        results["first_gui_paint_ms"] = round((time.perf_counter()-start)*1000, 3)
        assert len(window._events) == min(500, archive_size)
        assert "World intelligence overview" in window.overview_browser.toPlainText()
        assert "Health & disease" in window.overview_browser.toPlainText()
        assert not controller.monitoring
        identity = str(window._events[0]["id"])
        results["visible_story_navigation"] = _summary([
            _measure(app, lambda: window.navigate_event(identity)) for _ in range(8)
        ])
        assert window._selected_id == identity
        assert window.save_button.property("event_id") == identity
        assert window.intelligence_mode.currentIndex() == 1

        timings = []
        for _ in range(12):
            def star_tabs():
                window.open_page(0)
                window.save_button.click()
                window.open_page(1)
                window.open_page(0)
            timings.append(_measure(app, star_tabs))
        results["star_situations_tab_roundtrip"] = _summary(timings)
        assert controller.store.situation_state(identity)["saved"] is False
        assert window._selected_id == identity

        # The packaged app uses exactly one TV, one Radio and one Cameras
        # tab, not the old tiled MediaPanel. Never start any stream here.
        window.media.set_event({
            "id": identity, "synthetic": True, "severity": "unassessed",
        })
        timings = []
        for _ in range(12):
            def media_browse():
                window.media.tabs.setCurrentIndex(2)  # camera bank, no connect
                window.media.tabs.setCurrentIndex(0)  # single TV, no Watch
                window.media.tabs.setCurrentIndex(1)  # radio, no Play
                window.media.tabs.setCurrentIndex(0)
            timings.append(_measure(app, media_browse))
        results["camera_tv_radio_tab_roundtrip"] = _summary(timings)
        assert window.media.tabs.count() == 3
        assert not window.media.auto_cameras
        assert window.media.camera.camera is None
        window.media.stop()

        results["full_archive_refresh"] = _summary([
            _measure(app, window.refresh_data) for _ in range(3)
        ])
        # Diagnostic attribution: record one additional *normal* refresh by
        # timing its real database, feed, map and UI composition calls. This
        # instrumentation never replaces, stubs, or suppresses those methods.
        from contextlib import ExitStack
        from unittest.mock import patch
        phases = []
        targets = [(controller, "events"), (controller.store, "list_observations"),
                   (window.world_map, "set_events"),
                   (window, "_populate_feed"), (window, "_populate_filter_options"),
                   (window, "_update_world_overview"), (window, "_sync_map_controls")]
        if window.gdelt_panel is not None:
            targets.append((window.gdelt_panel, "refresh"))
        with ExitStack() as patches:
            for target, method_name in targets:
                original = getattr(target, method_name)
                def timed(*args, _original=original, _name=method_name, **kwargs):
                    started = time.perf_counter()
                    try:
                        return _original(*args, **kwargs)
                    finally:
                        label = _name
                        if _name == "events":
                            label += ":" + ("country_map" if kwargs.get("map_evidence") else
                                              "map" if kwargs.get("map_view") else "feed")
                        phases.append({"phase": label, "ms": round(
                            (time.perf_counter()-started)*1000, 3)})
                patches.enter_context(patch.object(target, method_name, timed))
            total = _measure(app, window.refresh_data)
        print("PULSE_GUI_PHASES=" + json.dumps({
            "archive_size": archive_size, "full_refresh_ms": round(total, 3),
            "phases": phases}, sort_keys=True), flush=True)

        url = QUrl("pulse-event://open/" + quote(identity, safe=""))
        results["overview_story_link"] = _summary([
            _measure(app, lambda: window._open_overview_event(url)) for _ in range(5)
        ])
        assert window._selected_id == identity
        assert "SYNTHETIC UI profile" in window.intel_browser.toPlainText()
        assert window.save_button.property("event_id") == identity
        assert "Could not update view" not in window.status_label.text()
        print("PULSE_GUI_PROFILE=" + json.dumps(
            {"archive_size": archive_size, **results}, sort_keys=True), flush=True)
    finally:
        if window is not None:
            window._force_close = True
            window.media.shutdown()
            window.close()
        controller.close()
        if window is not None:
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
