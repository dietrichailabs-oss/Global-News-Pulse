"""Diagnostic-only cProfile of exact 5k map-evidence projection hot path.

No production changes, no network or release. Compares against the original
per-event projection on the same SQLite store and same hosted runner.
"""
from __future__ import annotations

import cProfile
import io
import json
import pstats
import time
from datetime import datetime, timezone

from global_pulse.core import Store


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



def test_hotpath_profile_5000_map_evidence(tmp_path):
    store = Store(tmp_path / "profile-map.sqlite")
    try:
        now = datetime.now(timezone.utc).isoformat()
        for offset in range(0, 5000, 2000):
            store.ingest([fixture_report(i, now)
                          for i in range(offset, min(offset + 2000, 5000))])
        profiler = cProfile.Profile()
        profiler.enable()
        profiled = store.list_events(map_evidence=True, limit=5000)
        profiler.disable()
        at = time.perf_counter()
        current = store.list_events(map_evidence=True, limit=5000)
        optimized_ms = (time.perf_counter() - at) * 1000
        original_batch = store._map_evidence_page_unlocked
        def original_per_event(page):
            return [store._get_event_unlocked(row["id"], map_projection=True) for row in page]
        store._map_evidence_page_unlocked = original_per_event
        at = time.perf_counter()
        original = store.list_events(map_evidence=True, limit=5000)
        legacy_ms = (time.perf_counter() - at) * 1000
        store._map_evidence_page_unlocked = original_batch
        assert len(current) == len(original) == len(profiled) == 5000
        assert current == original, "Exact 5k batched versus original projection content/order must match"
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(45)
        print("PULSE_5000_HOTPATH_PROFILE=" + json.dumps({
            "optimized_ms": round(optimized_ms, 2),
            "legacy_ms": round(legacy_ms, 2),
            "optimized_over_legacy_ratio": round(optimized_ms / legacy_ms, 3),
            "top_cumulative": stream.getvalue().splitlines()[-48:],
        }, sort_keys=True), flush=True)
    finally:
        store.close()
