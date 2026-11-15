"""Issue82 collector/GUI/tray responsiveness, real SQLite + Qt offline.

No external providers, receiver/audio/video autoplay, public release or
physical Windows responsiveness is asserted by these Engineering tests.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.core import Store
from global_pulse.ui import MainWindow

NOW = "2026-11-08T12:00:00Z"
FUTURE = "2026-11-09T12:00:00Z"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def report(index=0, *, at=NOW, future=False):
    return {
        "id": f"perf-synthetic-{index}",
        "event_key": "perf-synthetic:event",
        "source_id": "offline-performance",
        "publisher": "Fictional performance source",
        "title": f"Offline report {index}",
        "summary": "Synthetic timeline only, never a live crisis",
        "url": f"https://example.invalid/perf/{index}",
        "published_at": FUTURE if future else at,
        "retrieved_at": at,
        "country": "Testland",
        "region": "Test Region",
        "category": "Infrastructure",
        "severity": "informational",
        "synthetic": True,
        "official": bool(future),
        "kind": "report",
        "official_scope": "measurement" if future else "",
        "origin_id": "future-source" if future else "current-source",
        "independence": "original",
    }


def test_identical_ingest_skips_gui_signal_but_clock_only_transition_kept(tmp_path):
    c = Controller(tmp_path, demo=True)
    evidence = []
    immediate = []
    c.evidence_changed.connect(lambda: evidence.append("evidence"))
    c.data_changed.connect(lambda: immediate.append("user"))
    try:
        initial = [report(), report(1, future=True)]
        c._on_reports(initial, allow_synthetic=True, now=NOW)
        assert evidence == ["evidence"]
        assert not immediate
        c._on_reports(initial, allow_synthetic=True, now=NOW)
        c._on_reports([], allow_synthetic=True, now=NOW)
        assert evidence == ["evidence"], "No-op provider polls must not redraw"
        # Store.ingest([], now=...) still performs temporal reassessment.
        c._on_reports([], allow_synthetic=True, now=FUTURE)
        assert len(evidence) == 2, "Clock-only future evidence must reach GUI"
        c._on_reports([], allow_synthetic=True, now=FUTURE)
        assert len(evidence) == 2, "Same transition must not redraw twice"
        assert not immediate
    finally:
        c.close()


def test_real_observation_ingest_keeps_separate_collector_notification(tmp_path):
    c = Controller(tmp_path, demo=True)
    evidence, immediate = [], []
    c.evidence_changed.connect(lambda: evidence.append(True))
    c.data_changed.connect(lambda: immediate.append(True))
    try:
        c.monitoring = True
        c._on_observations([{
            "source_id": "offline-observations",
            "indicator": "consumer-index",
            "country": "Testland",
            "date": "2026-11",
            "value": 12.5,
            "synthetic": True,
        }])
        assert len(c.store.list_observations()) == 1
        assert evidence == [True] and not immediate
    finally:
        c.monitoring = False
        c.close()


def test_tray_error_scan_one_bounded_query_per_400_sources(tmp_path):
    with Store(tmp_path / "states.sqlite3", mode="synthetic") as s:
        ids = [f"source-{i}" for i in range(513)]
        for key in ids:
            s.set_source_state(key, {"status": "active"})
        seen = []
        s._conn.set_trace_callback(lambda sql: seen.append(sql)
                                   if "FROM source_states WHERE source_id IN" in sql else None)
        try:
            assert s.any_source_error([]) is False
            assert not seen
            assert s.any_source_error(ids[:1]) is False
            assert len(seen) == 1
            seen.clear()
            assert s.any_source_error(ids[:200]) is False
            assert len(seen) == 1
            seen.clear()
            assert s.any_source_error(ids + ids[:15]) is False
            assert len(seen) == 2, "513 distinct enabled sources need 2 batched scans"
            # The final source may not be silently truncated or skipped.
            s.set_source_state(ids[-1], {"status": "rate_limited"})
            seen.clear()
            assert s.any_source_error(ids) is True
            assert len(seen) == 2
            assert s.any_source_error([ids[-1]]) is True
            assert s.any_source_error(["no-such-source"]) is False
            assert s.any_source_error([None]) is True
            # Parameterized IDs cannot change the WHERE clause.
            malicious = "x') OR 1=1 --"
            s.set_source_state(malicious, {"status": "active"})
            assert s.any_source_error([malicious]) is False
            assert s.any_source_error([malicious, ids[-1]]) is True
            # A corrupted persisted state must not be shown as healthy.
            with s._lock, s._conn:
                s._conn.execute(
                    "INSERT INTO source_states VALUES(?,?)",
                    ("corrupt", "this is not JSON"),
                )
            assert s.any_source_error(["corrupt"]) is True
        finally:
            s._conn.set_trace_callback(None)


@pytest.fixture
def desktop(app, tmp_path):
    c = Controller(tmp_path, demo=True)
    at = datetime.now(timezone.utc).isoformat()
    c.store.ingest([{
        **report(i, at=at),
        "event_key": f"perf-map-{i}",
        "published_at": at,
        "retrieved_at": at,
    } for i in range(160)])
    w = MainWindow(c)
    w.show()
    app.processEvents()
    yield w, c
    w._force_close = True
    w.media.shutdown()
    w.close()
    c.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_100_evidence_signals_one_map_refresh_and_user_direct_immediate(
    desktop, monkeypatch, app
):
    w, c = desktop
    redraws = []
    monkeypatch.setattr(w.world_map, "set_events",
                        lambda *args, **kwargs: redraws.append(True))
    for _ in range(100):
        c.evidence_changed.emit()
    assert w._evidence_refresh_timer.isActive()
    assert not redraws, "Collector signal must not read 5k map synchronously"
    QTest.qWait(320)
    app.processEvents()
    assert len(redraws) == 1

    c.evidence_changed.emit()
    assert w._evidence_refresh_timer.isActive()
    w.refresh_data()  # Explicit user/filter action remains immediate.
    assert len(redraws) == 2
    assert not w._evidence_refresh_timer.isActive()
    QTest.qWait(250)
    assert len(redraws) == 2, "An already-served revision must not re-render"
    c.data_changed.emit()
    assert len(redraws) == 3, "Explicit user/settings signal remains immediate"


def test_continuous_collector_burst_cannot_starve_first_due_timer(
    desktop, monkeypatch
):
    w, c = desktop
    redraws = []
    monkeypatch.setattr(w.world_map, "set_events",
                        lambda *args, **kwargs: redraws.append(True))
    for _ in range(24):
        c.evidence_changed.emit()
        QTest.qWait(30)
    QTest.qWait(250)
    assert 2 <= len(redraws) <= 8, (
        "Continuous 20-30Hz source events must flush without 24 redraws "
        "or indefinitely restarting the deadline"
    )


def test_reentrant_new_evidence_queues_exactly_one_followup(
    desktop, monkeypatch
):
    w, c = desktop
    redraws = []
    def redraw(*args, **kwargs):
        redraws.append(True)
        if len(redraws) == 1:
            c.evidence_changed.emit()
    monkeypatch.setattr(w.world_map, "set_events", redraw)
    c.evidence_changed.emit()
    QTest.qWait(420)
    assert len(redraws) == 2, "A revision during UI composition must not be lost"


def test_worker_thread_signal_starts_gui_timer_safely(desktop, monkeypatch, app):
    w, c = desktop
    redraws = []
    monkeypatch.setattr(w.world_map, "set_events",
                        lambda *args, **kwargs: redraws.append(True))
    worker = threading.Thread(target=c.evidence_changed.emit, daemon=True)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    app.processEvents()
    assert w._evidence_refresh_timer.isActive()
    QTest.qWait(320)
    assert len(redraws) == 1


def test_pending_collector_timer_never_reads_closed_archive(app, tmp_path, monkeypatch):
    c = Controller(tmp_path, demo=True)
    w = MainWindow(c)
    try:
        redraws = []
        monkeypatch.setattr(w.world_map, "set_events",
                            lambda *args, **kwargs: redraws.append(True))
        c.evidence_changed.emit()
        assert w._evidence_refresh_timer.isActive()
        w._force_close = True
        w.close()
        c.close()
        QTest.qWait(300)
        assert not redraws
    finally:
        w.media.shutdown()
        w._force_close = True
        w.close()
        c.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
