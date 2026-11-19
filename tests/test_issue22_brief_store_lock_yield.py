"""Real-Store Engineering regressions for revision-safe, short Brief lock ownership.

This runs original report/evidence/timeline hydration with synthetic offline input.
No claim of physical Windows smoothness, independent QA, or actual media playback.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from global_pulse.core import Store


def _reports(count=100):
    categories = ("Conflict", "Health", "Government", "Economy", "Disaster")
    stamp = datetime.now(timezone.utc).isoformat()
    return [{
        "id": f"brief-yield-{i}",
        "event_key": f"brief-yield-event-{i}",
        "title": f"SYNTHETIC offline {categories[i % len(categories)]} record {i}",
        "summary": "Fictional test evidence, not a real incident",
        "source_id": "synthetic-brief-lock-fixture",
        "publisher": "Synthetic offline fixture",
        "url": f"https://example.invalid/brief-yield/{i}",
        "published_at": stamp,
        "retrieved_at": stamp,
        "country": "",
        "region": "Global",
        "category": categories[i % len(categories)],
        "severity": "unassessed",
        "synthetic": True,
    } for i in range(count)]


def _store(tmp_path):
    store = Store(tmp_path / "brief-lock.sqlite", mode="synthetic")
    assert len(store.ingest(_reports())) == 100
    return store


def _since():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


class _RecordingLock:
    """Retain exact reentrant lock semantics while counting outer hold sections."""
    def __init__(self, backing):
        self.backing = backing
        self.owners = {}
        self.holds_ms = []

    def acquire(self, blocking=True, timeout=-1):
        acquired = self.backing.acquire(blocking, timeout)
        if acquired:
            who = threading.get_ident()
            start, depth = self.owners.get(who, (time.perf_counter(), 0))
            self.owners[who] = (start, depth + 1)
        return acquired

    def release(self):
        who = threading.get_ident()
        start, depth = self.owners[who]
        if depth == 1:
            self.holds_ms.append((time.perf_counter() - start) * 1000)
            del self.owners[who]
        else:
            self.owners[who] = (start, depth - 1)
        self.backing.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()


def test_brief_yields_store_lock_between_canonical_evidence_reads(tmp_path):
    store = _store(tmp_path)
    try:
        lock = _RecordingLock(store._lock)
        store._lock = lock
        original = store._get_event_unlocked
        def slow_evidence(*args, **kwargs):
            time.sleep(0.012)
            return original(*args, **kwargs)

        with patch.object(store, "_get_event_unlocked", slow_evidence):
            events = store.list_brief_events(since=_since(), per_domain=9)
        assert len(events) >= 10
        assert all(event.get("reports") and "timeline" in event for event in events)
        # A single lock across all report/timeline reads would record one
        # huge critical section; the corrected path yields for each event.
        assert len(lock.holds_ms) >= len(events) + 2, lock.holds_ms
        assert not lock.owners
        print("PULSE_BRIEF_LOCK_YIELD=" + str({
            "source_events": len(events),
            "store_lock_sections": len(lock.holds_ms),
            "longest_section_ms": round(max(lock.holds_ms), 3),
            "total_held_ms": round(sum(lock.holds_ms), 3),
        }))
        assert len({event["id"] for event in events}) == len(events)
        for event in events:
            current = store.get_event(event["id"])
            assert current is not None
            assert current["reports"] == event["reports"]
            assert current["timeline"] == event["timeline"]
    finally:
        store.close()


def test_raced_store_revision_retries_without_mixed_brief(tmp_path):
    store = _store(tmp_path)
    try:
        original = store._get_event_unlocked
        calls = 0
        def changing_evidence(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                # This is a real Store mutation inside the canonical RLock;
                # token mismatch must discard the first partial read.
                store.set_setting("synthetic_brief_mutation", "first")
            return original(*args, **kwargs)
        with patch.object(store, "_get_event_unlocked", changing_evidence):
            events = store.list_brief_events(since=_since(), per_domain=4)
        assert events
        assert calls > len(events), "Mixed revision accepted without a retry"
        assert all("timeline" in event and event["reports"] for event in events)
    finally:
        store.close()


def test_repeated_mutations_take_atomic_fallback_not_mixed_output(tmp_path):
    store = _store(tmp_path)
    try:
        original = store._get_event_unlocked
        changes = 0
        def changing_evidence(*args, **kwargs):
            nonlocal changes
            if changes < 2:
                changes += 1
                store.set_setting("synthetic_brief_mutation", changes)
            return original(*args, **kwargs)
        with patch.object(store, "_get_event_unlocked", changing_evidence):
            events = store.list_brief_events(since=_since(), per_domain=4)
        assert changes == 2
        assert len(events) >= 10
        assert len({event["id"] for event in events}) == len(events)
        assert all(event.get("reports") and event.get("timeline") for event in events)
    finally:
        store.close()
