"""Measure REAL Qt deferred-headline queue work and interaction delay.

Engineering diagnostic only: synthetic offline SQLite, no media playback,
no publisher collection or article translation downloads, no Windows11 claims.
The benchmark controls only the in-memory notification batch (16 vs 64)
without modifying product code, QA tests, package gates or crash instrumentation.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.headline_translation import HeadlineTranslations
from global_pulse.ui import MainWindow


def _reports(count=820):
    at = datetime.now(timezone.utc).isoformat()
    categories = ("Disaster", "Conflict", "Unrest", "Health", "Government",
                  "Economy", "Humanitarian", "Infrastructure", "News")
    return [
        {"id": f"backlog-fixture-{i}", "event_key": f"backlog-fixture:{i}",
         "title": f"SYNTHETIC backlog profile {categories[i % 9]} #{i}",
         "summary": "Synthetic, not a real-world crisis",
         "source_id": "synthetic-backlog", "publisher": "Offline fixture",
         "url": f"https://example.invalid/backlog/{i}",
         "published_at": at, "retrieved_at": at,
         "country": "", "region": "Global", "category": categories[i % 9],
         "synthetic": True, "severity": "unassessed"}
        for i in range(count)
    ]


def _stats(samples):
    if not samples:
        return {"count": 0}
    values = sorted(samples)
    return {"count": len(values),
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[min(len(values)-1, (95*len(values)+99)//100-1)], 3),
            "max_ms": round(values[-1], 3)}


def _act(app, callback):
    """Record wall-time until a queued next-turn Qt callback fires."""
    done = []
    timer = QTimer()
    timer.setSingleShot(True)
    start = time.perf_counter()
    timer.timeout.connect(lambda: done.append((time.perf_counter()-start)*1000))
    timer.start(0)
    callback()
    app.processEvents()
    if not done:
        app.processEvents()
    timer.stop()
    timer.deleteLater()
    assert len(done) == 1, "No Qt callback after user interaction"
    return done[0]


@pytest.mark.parametrize("batch", [16, 64])
def test_820_record_deferred_queue_during_actual_gui_navigation(tmp_path, monkeypatch, batch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(HeadlineTranslations, "DEFERRED_NOTIFY_BATCH", batch)
    controller = Controller(tmp_path, demo=True)
    window = None
    redraw_ms = []
    navigation_ms = []
    tick_intervals = []
    tick_marks = []
    original = MainWindow._refresh_translated_headlines

    def timed_redraw(self):
        t = time.perf_counter()
        try:
            return original(self)
        finally:
            redraw_ms.append((time.perf_counter()-t)*1000)

    def tick():
        tick_marks.append(time.perf_counter())
        if len(tick_marks) > 1:
            tick_intervals.append((tick_marks[-1] - tick_marks[-2])*1000)

    ticker = QTimer()
    ticker.setInterval(16)
    ticker.timeout.connect(tick)
    try:
        controller.store.ingest(_reports())
        with patch.object(MainWindow, "_refresh_translated_headlines", timed_redraw):
            window = MainWindow(controller)
            window.show()
            app.processEvents()
            engine = controller._headlines
            assert len(window._events) == 500
            assert len(engine.deferred) >= 450
            assert "World intelligence overview" in window.overview_browser.toPlainText()
            identity = str(window._events[0]["id"])
            window.navigate_event(identity)
            assert window._selected_id == identity
            assert "SYNTHETIC" in window.intel_browser.toPlainText()
            assert not controller.monitoring
            assert window.media.camera.camera is None
            assert not window.media.auto_cameras
            # Observe the real 1-ms scheduling and the real repaint callback.
            # Do not replace statistical language_of, views, Store or Qt timer.
            ticker.start()
            started = time.perf_counter()
            last_action = 0.0
            while engine.deferred and time.perf_counter()-started < 35:
                QTest.qWait(3)
                elapsed = time.perf_counter()-started
                if elapsed-last_action > 0.3 and len(navigation_ms) < 12:
                    navigation_ms.append(_act(app, lambda: (
                        window.save_button.click(),
                        window.open_page(1),
                        window.open_page(0),
                        window.media.tabs.setCurrentIndex(2),
                        window.media.tabs.setCurrentIndex(0),
                        window.media.tabs.setCurrentIndex(1),
                        window.media.tabs.setCurrentIndex(0)
                    )))
                    last_action = elapsed
            ticker.stop()
            completed = len(engine.deferred) == 0
            result = {"batch": batch,
                      "duration_ms": round((time.perf_counter()-started)*1000, 3),
                      "remaining": len(engine.deferred),
                      "redraw": _stats(redraw_ms),
                      "navigation": _stats(navigation_ms),
                      "sixteen_ms_ticker": _stats(tick_intervals)}
            print("PULSE_DEFERRED_BACKLOG=" + json.dumps(result, sort_keys=True), flush=True)
            assert completed, "Deferred queue did not finish within bounded probe"
            assert redraw_ms, "Actual feed repaint path was not called"
            assert len(navigation_ms) >= 4, "Navigation while backlog active was not exercised"
            assert window._selected_id == identity
            assert window.save_button.property("event_id") == identity
            assert window.media.camera.camera is None
            assert not window.media.auto_cameras
            assert "Could not update view" not in window.status_label.text()
            # Guard against gross hangs, not a universal hosted performance SLA.
            assert max(navigation_ms) < 3000, "A user event loop hung for multiple seconds"
    finally:
        ticker.stop()
        if window is not None:
            window._force_close = True
            window.media.shutdown()
            window.close()
        controller.close()
        if window is not None:
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
