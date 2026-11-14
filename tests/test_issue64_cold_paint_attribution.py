"""Measure actual initial native Qt rendering phases before touching accepted UI.

Engineering-only offscreen synthetic persistence. No publisher data, network,
model installation, media playback, physical Windows 11 or crash attribution.
The purpose is to separate cold headline-language CPU from Qt construction and
SQLite retrieval; do not infer an optimization from a warm-cache benchmark.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
import global_pulse.headline_translation as headlines


def _archive(size):
    at = datetime.now(timezone.utc).isoformat()
    categories = ("Disaster", "Conflict", "Unrest", "Health", "Government",
                  "Economy", "Humanitarian", "Infrastructure", "News")
    return [
        {"id": f"issue64-cold-{i}", "event_key": f"issue64-cold:{i}",
         "title": f"SYNTHETIC UI profile {categories[i % len(categories)]} #{i}",
         "summary": "Offline fictional archive record, not a real incident",
         "source_id": "offline-cold-paint", "publisher": "Synthetic Test Publisher",
         "url": f"https://example.invalid/cold/{i}",
         "published_at": at, "retrieved_at": at,
         "region": "Global", "country": "",
         "category": categories[i % len(categories)],
         "synthetic": True, "severity": "unassessed"}
        for i in range(size)
    ]


@pytest.mark.parametrize("size", [180, 820])
def test_first_paint_cpu_attribution_uses_real_qt_feed_and_original_evidence(tmp_path, size):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    phases = {"lang_calls": 0, "lang_ms": 0., "feed_lang_calls": 0,
              "feed_calls": 0, "feed_ms": 0.,
              "refresh_calls": 0, "refresh_ms": 0.}
    try:
        started = time.perf_counter()
        controller.store.ingest(_archive(size))
        ingest_ms = (time.perf_counter() - started) * 1000
        original_language = headlines.language_of
        original_feed = MainWindow._populate_feed
        original_refresh = MainWindow.refresh_data

        def language(*args, **kwargs):
            t = time.perf_counter()
            try:
                return original_language(*args, **kwargs)
            finally:
                phases["lang_calls"] += 1
                phases["lang_ms"] += (time.perf_counter()-t)*1000

        def feed(self, *args, **kwargs):
            t = time.perf_counter()
            before = phases["lang_calls"]
            try:
                return original_feed(self, *args, **kwargs)
            finally:
                phases["feed_lang_calls"] += phases["lang_calls"] - before
                phases["feed_calls"] += 1
                phases["feed_ms"] += (time.perf_counter()-t)*1000

        def refresh(self, *args, **kwargs):
            t = time.perf_counter()
            try:
                return original_refresh(self, *args, **kwargs)
            finally:
                phases["refresh_calls"] += 1
                phases["refresh_ms"] += (time.perf_counter()-t)*1000

        started = time.perf_counter()
        with patch.object(headlines, "language_of", language), \
             patch.object(MainWindow, "_populate_feed", feed), \
             patch.object(MainWindow, "refresh_data", refresh):
            window = MainWindow(controller)
            window.show()
            app.processEvents()
        first_paint_ms = (time.perf_counter()-started)*1000

        assert len(window._events) == min(500, size)
        assert "World intelligence overview" in window.overview_browser.toPlainText()
        assert "Health & disease" in window.overview_browser.toPlainText()
        assert not controller.monitoring
        assert not window.media.auto_cameras
        assert window.media.camera.camera is None
        assert all(e["title"].startswith("SYNTHETIC UI profile") for e in window._events)
        assert phases["feed_calls"] >= 1 and phases["refresh_calls"] >= 1
        assert phases["lang_calls"] >= 1, "Cold route instrumentation did not cover language_of"
        # Pre-deferred builds performed all 500 language detections INSIDE
        # feed population. Now the Qt event loop performs separate bounded
        # tasks, so language time must NOT be claimed as part of feed time.
        # Preserve both independent timings instead of weakening this to a
        # no-op or hiding timer work from the first-paint measurement.
        assert 0 <= phases["feed_ms"] <= first_paint_ms + 10
        assert 0 <= phases["lang_ms"] <= first_paint_ms + 10
        assert phases["feed_lang_calls"] <= 1, (
            "Feed preview is still doing synchronous headline detection",
            phases,
        )
        assert len(controller._headlines.deferred) <= controller._headlines.MAX_DEFERRED
        print("PULSE_COLD_PAINT=" + json.dumps({
            "size": size, "ingest_ms_excluded": round(ingest_ms, 3),
            "first_paint_ms": round(first_paint_ms, 3),
            "deferred_remaining_after_first_paint": len(controller._headlines.deferred),
            **{k: round(v, 3) if k.endswith("_ms") else v for k, v in phases.items()}
        }, sort_keys=True), flush=True)
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
