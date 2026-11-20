"""Issue82 collector/GUI/tray responsiveness, real SQLite + Qt offline.

No external providers, receiver/audio/video autoplay, public release or
physical Windows responsiveness is asserted by these Engineering tests.
"""
from __future__ import annotations

import os
import threading
import time
import sys
import sqlite3
import ast
from pathlib import Path
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QProcess, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from global_pulse.__main__ import _ExitCoordinator, _TrayRefreshBridge, _tray_health_state
from global_pulse.controller import Controller
from global_pulse.source_availability import capability
from global_pulse.core import Store
from global_pulse.native_notifications import NativeNotifications
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
        source = {
            "source_id": "offline-observations",
            "indicator": "consumer-index",
            "country": "Testland",
            "date": "2026-11",
            "value": 12.5,
            "synthetic": True,
        }
        c._on_observations([source])
        assert len(c.store.list_observations()) == 1
        assert evidence == [True] and not immediate
        c._on_observations([source])
        assert evidence == [True], "Duplicate observation fingerprint must not repaint 5k map"
        assert len(c.store.list_observations()[0]["revisions"]) == 1
        c._on_observations([{**source, "value": 14.0}])
        assert evidence == [True, True], "Corrected indicator value must update the GUI"
        obs = c.store.list_observations()[0]
        assert obs["value"] == 14.0 and obs["revision_count"] == 2
        assert not immediate
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
            for invalid in ([], {}, None):
                key = f"malformed-{type(invalid).__name__}"
                s.set_source_state(key, {"status": invalid})
                assert s.any_source_error([key]) is True, (
                    "Unhashable or null status must be a conservative error, not crash tray"
                )
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
    # Preserve the original strict 420ms / exactly-two acceptance gate.
    # Record WHY an intermittent hosted runner failed: timer arm, callback,
    # refresh duration/status and the reentrant signal. Do not extend wait.
    import time
    w, c = desktop
    redraws, trace = [], []
    start = time.monotonic()

    def stamp(stage):
        trace.append((
            round((time.monotonic() - start) * 1000, 1),
            stage,
            w._evidence_refresh_timer.remainingTime(),
        ))

    original_refresh = w.refresh_data

    def traced_refresh(*args, **kwargs):
        stamp("refresh-enter")
        try:
            return original_refresh(*args, **kwargs)
        except Exception as error:
            stamp("refresh-exception:" + type(error).__name__)
            raise
        finally:
            stamp("refresh-exit")

    monkeypatch.setattr(w, "refresh_data", traced_refresh)
    w._evidence_refresh_timer.timeout.connect(lambda: stamp("timer-timeout-return"))
    def redraw(*args, **kwargs):
        stamp("set-events-" + str(len(redraws) + 1))
        redraws.append(True)
        if len(redraws) == 1:
            stamp("reentrant-emit")
            c.evidence_changed.emit()
            stamp("reentrant-armed")
    monkeypatch.setattr(w.world_map, "set_events", redraw)
    stamp("initial-emit")
    c.evidence_changed.emit()
    stamp("initial-armed")
    QTest.qWait(420)
    stamp("deadline")
    assert len(redraws) == 2, (
        "A revision during UI composition must not be lost; "
        f"trace_ms={trace}, redraws={len(redraws)}, "
        f"background_warm={w._background_warm_enabled}"
    )


def test_reentrant_pending_timer_delivers_new_store_revision_synchronously(
    desktop, monkeypatch
):
    """Deterministic two-tick observer of real Store evidence without deadline slack.

    This supplements, never replaces or relaxes, the unchanged 420ms test.
    """
    w, c = desktop
    monkeypatch.setattr(w, "_background_warm_enabled", False)
    map_pages = []
    now = datetime.now(timezone.utc).isoformat()
    newest = {**report(9801, at=now), "event_key": "r20-qa-new-revision"}
    collected = []
    stored_target_ids = []

    def contains_new_report(event):
        # event_key belongs to normalized reports, not the canonical event's
        # display schema. Match the immutable report identity in real Store
        # output, then bind the next country projection to its canonical ID.
        return any(
            row.get("source_id") == newest["source_id"]
            and row.get("id") == newest["id"]
            for row in event.get("reports", [])
        )

    assert not any(contains_new_report(event) for event in c.events())
    revision_before = c.store.content_revision()

    def draw(events, **kwargs):
        # WorldMap receives point events separately from country-level evidence.
        # This synthetic fixture has no incident coordinates: it must reach
        # country_events, never be invented as a point on the map.
        map_pages.append({
            "points": list(events),
            "country": list(kwargs.get("country_events", [])),
        })
        if len(map_pages) == 1:
            c._on_reports([newest], allow_synthetic=True, now=now)
            matches = [event for event in c.events() if contains_new_report(event)]
            collected.append(len(matches) == 1)
            stored_target_ids.extend(event["id"] for event in matches)

    monkeypatch.setattr(w.world_map, "set_events", draw)
    c.evidence_changed.emit()
    assert w._evidence_refresh_timer.isActive()
    w._evidence_refresh_timer.stop()
    w._refresh_evidence_when_idle()
    assert len(map_pages) == 1
    assert collected == [True]
    assert len(stored_target_ids) == 1
    assert c.store.content_revision() != revision_before
    assert not any(contains_new_report(event) for event in map_pages[0]["country"])
    assert w._evidence_refresh_timer.isActive(), (
        "Store mutation during map composition must queue a follow-up"
    )
    w._evidence_refresh_timer.stop()
    w._refresh_evidence_when_idle()
    assert len(map_pages) == 2
    projected = [event for event in map_pages[1]["country"]
                 if contains_new_report(event)]
    assert [event["id"] for event in projected] == stored_target_ids, (
        "Newly ingested unlocated evidence must reach the map's country "
        "evidence projection on the queued second pass"
    )
    assert projected[0]["latitude"] is None
    assert projected[0]["longitude"] is None
    assert not any(event["id"] in stored_target_ids
                   for page in map_pages for event in page["points"]), (
        "Unlocated report must not acquire fabricated point coordinates"
    )


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


def test_native_tray_uses_effective_scheduler_sources_and_state_precedence(tmp_path):
    c = Controller(tmp_path, demo=True)
    try:
        configured = next(
            (source for source in c.catalog
             if capability(source)[0] and source.get("adapter") != "gdelt_doc"),
            None,
        )
        assert configured, "Test catalog requires one eligible automatic provider"
        source_id = configured["id"]
        c.set_setting("enabled_sources", [source_id])
        c.monitoring = True
        assert source_id in c._enabled_collection_ids
        c.store.set_source_state(source_id, {"status": "error"})
        assert _tray_health_state(c) == "error"
        # Old source-status errors must no longer color the owner-disabled tray.
        c.set_setting("enabled_sources", [])
        assert source_id not in c._enabled_collection_ids
        assert _tray_health_state(c) == "active"
        c.monitoring = False
        assert _tray_health_state(c) == "paused"
        # An unread saved alert has priority even over monitoring paused.
        changed = c.store.ingest([report(9001)], now=NOW)
        assert changed
        alert = c.store.add_alert(changed[0], "Official synthetic test alert")
        assert alert and not alert["read"]
        assert _tray_health_state(c) == "alerts"
        # GDELT delegated batches must not also count as scheduler-enabled.
        gdelt = next(
            (source for source in c.catalog
             if source.get("adapter") == "gdelt_doc" and capability(source)[0]),
            None,
        )
        if gdelt:
            c.set_setting("enabled_sources", [gdelt["id"]])
            assert gdelt["id"] in c._enabled_collection_ids
            c.set_setting("gdelt_batches_enabled", True)
            assert gdelt["id"] not in c._enabled_collection_ids
    finally:
        c.monitoring = False
        c.close()


def test_worker_origin_status_and_tray_bridge_run_on_gui_thread(desktop, app):
    w, c = desktop
    tray_timer = QTimer()
    tray_timer.setSingleShot(True)
    tray_timer.setInterval(700)
    bridge = _TrayRefreshBridge(tray_timer, c)
    c.source_status_changed.connect(bridge.schedule)
    c.evidence_changed.connect(bridge.schedule)
    try:
        w._collection_refresh_timer.stop()
        w._evidence_refresh_timer.stop()
        # Python sender genuinely outside the GUI thread. QObject @Slot
        # receivers must be queued, never start QTimers in this worker.
        worker = threading.Thread(target=c.source_status_changed.emit, daemon=True)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not tray_timer.isActive()
        assert not w._collection_refresh_timer.isActive()
        QTest.qWait(50)
        assert tray_timer.isActive()
        assert w._collection_refresh_timer.isActive()
        tray_timer.stop()
        w._collection_refresh_timer.stop()
        worker = threading.Thread(target=c.evidence_changed.emit, daemon=True)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not tray_timer.isActive()
        QTest.qWait(50)
        assert tray_timer.isActive()
        assert w._evidence_refresh_timer.isActive()
        # No delayed popup or worker signal can resurrect a tray after stop.
        bridge.stopping = True
        tray_timer.stop()
        worker = threading.Thread(target=c.source_status_changed.emit, daemon=True)
        worker.start()
        worker.join(timeout=2)
        QTest.qWait(50)
        assert not tray_timer.isActive()
    finally:
        c.source_status_changed.disconnect(bridge.schedule)
        c.evidence_changed.disconnect(bridge.schedule)
        tray_timer.stop()
        tray_timer.deleteLater()
        app.processEvents()


def test_worker_origin_status_and_alert_widget_updates_are_gui_queued(desktop, app):
    w, c = desktop
    previous = w.status_label.text()
    worker = threading.Thread(
        target=lambda: c.status_changed.emit("Worker-origin collection status"),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert w.status_label.text() == previous, (
        "GPCollect worker must not mutate QWidget before GUI event loop"
    )
    app.processEvents()
    assert w.status_label.text() == "Worker-origin collection status"

    worker = threading.Thread(
        target=lambda: c.alert_received.emit({"id": "offline-worker-alert"}),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert w.status_label.text() == "Worker-origin collection status"
    app.processEvents()
    assert w.status_label.text() == "New alert saved in Alerts."


def test_worker_origin_native_toast_and_storage_pause_are_gui_queued(app, tmp_path):
    c = Controller(tmp_path, demo=True)
    notifier = NativeNotifications(enabled=False)
    deliveries = []
    notifier.delivery_changed.connect(
        lambda alert_id, status: deliveries.append(
            (alert_id, QThread.currentThread() == app.thread(), status)
        )
    )
    c.native_alert.connect(notifier.notify)
    try:
        worker = threading.Thread(
            target=lambda: c.native_alert.emit(
                {"id": "offline-worker-event", "_alert_id": "offline-worker-alert"},
                "Synthetic native notification",
            ),
            daemon=True,
        )
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not deliveries, "QProcess notification bridge must queue off-worker"
        app.processEvents()
        assert len(deliveries) == 1
        assert deliveries[0][0] == "offline-worker-alert"
        assert deliveries[0][1], "Native notification callback ran outside GUI"

        # The storage fail-closed pause also arrives on GUI QObject affinity.
        c.monitoring = True
        worker = threading.Thread(
            target=lambda: c.storage_problem.emit("Synthetic storage blocked"),
            daemon=True,
        )
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert c.monitoring is True, "Worker must not pause GUI scheduler directly"
        app.processEvents()
        assert c.monitoring is False
    finally:
        c.native_alert.disconnect(notifier.notify)
        notifier.stop()
        notifier.deleteLater()
        c.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def _exit_spin(app, condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert condition(), "Shutdown did not reach its expected bounded state"


def test_exit_request_does_not_wait_for_admitted_collector_commit(app, tmp_path):
    c = Controller(tmp_path, demo=True)
    notifier = NativeNotifications(enabled=False)
    shutdown = _ExitCoordinator(c, notifier)
    entered, release = threading.Event(), threading.Event()
    errors, finished, beats = [], [], []
    shutdown.finished.connect(lambda: finished.append(c._store_closed))
    shutdown.blocked.connect(errors.append)
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: beats.append(True))

    def pending_commit():
        # Model Scheduler._collect's admitted callback, including its real
        # transaction. Exit may invalidate future work, not discard this write.
        with c.scheduler._lock, c._ingest_lock, c.store._lock, c.store._conn:
            c.store._conn.execute("INSERT INTO settings VALUES('critical_write','true')")
            entered.set()
            assert release.wait(3)

    worker = threading.Thread(target=pending_commit, daemon=True)
    worker.start()
    assert entered.wait(1)
    try:
        heartbeat.start()
        start = time.monotonic()
        shutdown.begin({"window_geometry": "saved-layout", "map_layers_visible": True})
        assert time.monotonic() - start < .15
        assert c._closed and c.scheduler._stop.is_set() and not c.monitoring
        assert not c._retention_timer.isActive()
        assert not c._headlines.deferred_timer.isActive()
        # Repeated Close cannot snapshot a different layout or begin more work.
        shutdown.begin({"window_geometry": "must-not-replace"})
        c.start()
        c.resume()
        c.set_setting("late_write", True)
        notifier.start()
        assert c.scheduler._thread is None and notifier.process is None
        QTest.qWait(100)
        assert len(beats) >= 3 and not finished and not errors
        release.set()
        _exit_spin(app, lambda: shutdown.completed)
        assert finished == [True] and not errors
        with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as saved:
            assert saved.get_setting("critical_write") is True
            assert saved.get_setting("window_geometry") == "saved-layout"
            assert saved.get_setting("map_layers_visible") is True
            assert saved.get_setting("late_write") is None
            assert saved._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        release.set()
        worker.join(2)
        heartbeat.stop()
        shutdown.timer.stop()
        if shutdown._finalizer:
            shutdown._finalizer.join(3)
        c.close()


def test_exit_archive_timeout_is_visible_and_retry_retains_history(app, tmp_path):
    c = Controller(tmp_path, demo=True)
    event = c.store.ingest([report()], now=NOW)[0]
    alert = c.store.add_alert(event, "Synthetic shutdown history")
    notifier = NativeNotifications(enabled=False)
    notifier._pending.append((dict(event, _alert_id=alert["id"]), "pending", time.monotonic()))
    shutdown = _ExitCoordinator(c, notifier)
    blocked, finished = [], []
    shutdown.blocked.connect(blocked.append)
    shutdown.finished.connect(lambda: finished.append(True))
    entered, release = threading.Event(), threading.Event()

    def hold_store():
        with c.store._lock:
            entered.set()
            assert release.wait(4)

    worker = threading.Thread(target=hold_store, daemon=True)
    worker.start()
    assert entered.wait(1)
    try:
        shutdown.begin({"window_geometry": "retry-layout"})
        _exit_spin(app, lambda: bool(blocked), timeout=2.0)
        assert not c._store_closed and not shutdown.completed and not finished
        assert shutdown._finalized.is_set(), "Bounded lock failure must finish its disk thread"
        assert "archive" in blocked[0].lower()
        original_outcomes = list(shutdown.outcomes)
        assert len(original_outcomes) == 1
        release.set()
        worker.join(1)
        shutdown.retry()
        _exit_spin(app, lambda: shutdown.completed)
        assert finished == [True] and shutdown.outcomes == original_outcomes
        with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as saved:
            assert saved.get_setting("window_geometry") == "retry-layout"
            assert saved.list_alerts()[0]["delivery_status"] == original_outcomes[0][1]
    finally:
        release.set()
        worker.join(2)
        shutdown.timer.stop()
        if shutdown._finalizer:
            shutdown._finalizer.join(3)
        c.close()


@pytest.mark.parametrize("fails_after_deadline", [False, True])
def test_exit_deadline_never_starts_two_archive_finalizers(app, tmp_path, monkeypatch, fails_after_deadline):
    c = Controller(tmp_path, demo=True)
    shutdown = _ExitCoordinator(c, NativeNotifications(enabled=False), deadline_ms=70)
    entered, release = threading.Event(), threading.Event()
    original = c.finish_close
    calls, warnings, finished = [], [], []

    def slow_commit(*args):
        calls.append(threading.current_thread().name)
        entered.set()
        assert release.wait(3)
        if fails_after_deadline:
            raise RuntimeError("Critical archive finalizer failed after deadline")
        original(*args)

    monkeypatch.setattr(c, "finish_close", slow_commit)
    shutdown.blocked.connect(warnings.append)
    shutdown.finished.connect(lambda: finished.append(True))
    try:
        shutdown.begin({"window_geometry": "one-finalizer"})
        _exit_spin(app, lambda: bool(warnings), timeout=1.0)
        assert entered.is_set() and not c._store_closed and not finished
        current = shutdown._finalizer
        for _ in range(3):
            assert shutdown.retry() is False, "Retry must retain the visible waiting state"
            shutdown.begin({"window_geometry": "wrong"})
        assert shutdown._finalizer is current and len(calls) == 1
        release.set()
        if fails_after_deadline:
            _exit_spin(app, lambda: len(warnings) == 2)
            assert "failed after deadline" in warnings[-1]
            assert not c._store_closed and not finished
            monkeypatch.setattr(c, "finish_close", original)
            assert shutdown.retry() is True
        _exit_spin(app, lambda: shutdown.completed)
        assert finished == [True] and len(calls) == 1
    finally:
        release.set()
        shutdown.timer.stop()
        if shutdown._finalizer:
            shutdown._finalizer.join(3)
        c.close()


def test_exit_cancels_owned_children_in_parallel_without_native_waits(app, tmp_path, monkeypatch):
    c = Controller(tmp_path, demo=True)
    notifier = NativeNotifications(enabled=True)
    shutdown = _ExitCoordinator(c, notifier)
    sleepy = lambda: (sys.executable, ["-c", "import time; time.sleep(30)"])
    monkeypatch.setattr(c._workers, "command", sleepy)
    monkeypatch.setattr(c._gdelt, "command", sleepy)
    assert c._workers.submit("owned-job", "de", "synthetic", True)
    token = c._gdelt.schedule.claim()
    assert token
    c._gdelt._launch(token)
    notifier.process = QProcess(notifier)
    notifier.process.finished.connect(notifier._finished)
    notifier.process.start(*sleepy())
    children = [c._workers.process, c._gdelt.process, notifier.process]
    exits = []
    for index, process in enumerate(children):
        process.finished.connect(lambda *_, index=index: exits.append(index))
    try:
        _exit_spin(app, lambda: all(p.state() == QProcess.ProcessState.Running for p in children))
        for process in children:
            monkeypatch.setattr(process, "waitForFinished",
                                lambda *_: pytest.fail("Qt exit path must not wait for a native child"))
        started = time.monotonic()
        shutdown.begin({"window_geometry": "native-cancel"})
        assert time.monotonic() - started < .15
        _exit_spin(app, lambda: shutdown.completed, timeout=2.0)
        assert time.monotonic() - started < 2.0
        assert sorted(exits) == [0, 1, 2]
        assert c._workers.process is None and c._gdelt.process is None and notifier.process is None
        assert not c._workers.submit("late", "de", "text", False)
        c._gdelt.set_active(True)
        notifier.start()
        assert not c._gdelt.active and notifier.process is None
        assert not list((tmp_path / "translation-jobs").iterdir())
        assert c._gdelt.schedule.status()["state"] == "cancelled"
    finally:
        shutdown.timer.stop()
        if shutdown._finalizer:
            shutdown._finalizer.join(3)
        c.close()
        notifier.stop()


def test_exit_keeps_committed_wal_when_external_reader_prevents_truncate(app, tmp_path):
    c = Controller(tmp_path, demo=True)
    c.store.set_setting("before_reader", True)
    reader = sqlite3.connect(c.store.path)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM settings").fetchall()
    c.store.set_setting("after_reader", True)
    shutdown = _ExitCoordinator(c, NativeNotifications(enabled=False))
    try:
        started = time.monotonic()
        shutdown.begin({"window_geometry": "wal-layout"})
        _exit_spin(app, lambda: shutdown.completed, timeout=1.0)
        assert time.monotonic() - started < 1.0, "Exit must not wait 15 seconds for WAL TRUNCATE"
        with sqlite3.connect(c.store.path) as check:
            assert check.execute("SELECT value FROM settings WHERE key='window_geometry'").fetchone()[0] == '"wal-layout"'
            assert check.execute("SELECT value FROM settings WHERE key='after_reader'").fetchone()[0] == "true"
            assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        reader.close()
        shutdown.timer.stop()
        if shutdown._finalizer:
            shutdown._finalizer.join(3)
        c.close()


def test_stop_during_scheduler_store_scan_cannot_admit_new_collector(app, tmp_path, monkeypatch):
    c = Controller(tmp_path, demo=True)
    source = next(s for s in c.catalog if s.get("enabled") and s.get("adapter") != "manual")
    c.scheduler.set_sources([source])
    c.scheduler.resume()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked_state(_):
        entered.set()
        assert release.wait(2)
        return {}

    monkeypatch.setattr(c.store, "get_source_state", blocked_state)
    monkeypatch.setattr(c.scheduler, "collector_factory", lambda _: calls.append(True))
    tick = threading.Thread(target=c.scheduler._tick, daemon=True)
    tick.start()
    assert entered.wait(1)
    shutdown = _ExitCoordinator(c, NativeNotifications(enabled=False))
    try:
        started = time.monotonic()
        shutdown.begin({})
        assert time.monotonic() - started < .15
        release.set()
        tick.join(1)
        assert not tick.is_alive() and not calls and not c.scheduler._workers
        _exit_spin(app, lambda: shutdown.completed)
    finally:
        release.set()
        tick.join(2)
        shutdown.timer.stop()
        if shutdown._finalizer:
            shutdown._finalizer.join(3)
        c.close()


def test_late_bootstrap_and_native_callbacks_are_noops_after_exit(app, tmp_path):
    c = Controller(tmp_path, demo=True)
    notifier = NativeNotifications(enabled=True, predicate=lambda: pytest.fail("Late native admission"))
    shutdown = _ExitCoordinator(c, notifier)
    shutdown.begin({})
    _exit_spin(app, lambda: shutdown.completed)
    # Execute the actual nested production callbacks, not a duplicated guard.
    from global_pulse import __main__ as entrypoint
    tree = ast.parse(Path(entrypoint.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    env = {"controller": c}
    for name, args in (("begin", ()), ("apply_native_preference", (True,)),
                       ("activate", ("late-event",)), ("notification_status_only", ("late status",)),
                       ("delivered", ("late-alert", "late status"))):
        node = next(n for n in ast.walk(main) if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), entrypoint.__file__, "exec"), env)
        env[name](*args)
    assert not notifier.notify({"id": "late-event", "_alert_id": "late-alert"}, "late alert")
    notifier.start()
    assert notifier.process is None and c._store_closed


def _bind_production_exit_warning(window, coordinator):
    from global_pulse import __main__ as entrypoint
    tree = ast.parse(Path(entrypoint.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    show = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "show_exit_problem")
    wrapper = ast.parse(
        "def bind():\n"
        "    exit_warning = None\n"
        "    def warning(): return exit_warning\n"
        "    return show_exit_problem, warning\n")
    wrapper.body[0].body.insert(1, show)
    ast.fix_missing_locations(wrapper)
    env = {"window": window, "QMessageBox": QMessageBox,
           "exit_coordinator": coordinator, "QTimer": QTimer}
    exec(compile(wrapper, entrypoint.__file__, "exec"), env)
    return env["bind"]()


def test_actual_retry_dialog_survives_running_commit_then_late_error(app, tmp_path, monkeypatch):
    c = Controller(tmp_path, demo=True)
    q = _ExitCoordinator(c, NativeNotifications(enabled=False), deadline_ms=30)
    window = QWidget()
    show_problem, warning = _bind_production_exit_warning(window, q)
    q.blocked.connect(show_problem)
    q.finished.connect(lambda: warning().close() if warning() else None)
    blocked = []
    q.blocked.connect(blocked.append)
    entered, release = threading.Event(), threading.Event()
    original = c.finish_close
    calls = []

    def delayed_failure(*_):
        calls.append(True)
        entered.set()
        assert release.wait(2)
        raise RuntimeError("Forced archive failure after Retry")

    monkeypatch.setattr(c, "finish_close", delayed_failure)
    try:
        q.begin({"window_geometry": "dialog-retry"})
        _exit_spin(app, lambda: warning() is not None and warning().isVisible(), timeout=1)
        assert entered.is_set() and q._finalizer.is_alive()
        warning().button(QMessageBox.StandardButton.Retry).click()
        app.processEvents()
        assert warning().isVisible(), "QMessageBox auto-close must not strand the disabled window"
        assert len(calls) == 1 and not window.isEnabled()
        release.set()
        _exit_spin(app, lambda: len(blocked) == 2, timeout=1)
        assert warning().isVisible() and "Forced archive failure" in warning().text()
        assert q.failed and not q.timer.isActive() and not c._store_closed
        monkeypatch.setattr(c, "finish_close", original)
        warning().button(QMessageBox.StandardButton.Retry).click()
        _exit_spin(app, lambda: q.completed)
        assert c._store_closed and not warning().isVisible()
    finally:
        release.set()
        q.timer.stop()
        if q._finalizer:
            q._finalizer.join(3)
        if warning():
            warning().close()
        window.close()
        c.close()


def test_external_quit_keeps_qt_recovery_alive_until_critical_commit_finishes(app, tmp_path, monkeypatch):
    c = Controller(tmp_path, demo=True)
    q = _ExitCoordinator(c, NativeNotifications(enabled=False), deadline_ms=30)
    window = QWidget()
    show_problem, warning = _bind_production_exit_warning(window, q)
    q.blocked.connect(show_problem)
    q.finished.connect(lambda: warning().close() if warning() else None)
    release = threading.Event()
    original = c.finish_close
    observed = []

    def delayed_commit(*args):
        assert release.wait(2)
        original(*args)

    def permit_commit():
        observed.append(bool(warning() and warning().isVisible() and not c._store_closed))
        release.set()

    monkeypatch.setattr(c, "finish_close", delayed_commit)
    try:
        q.begin({"window_geometry": "external-quit"})
        QTimer.singleShot(90, permit_commit)
        started = time.monotonic()
        q.drain_after_event_loop()
        assert time.monotonic() - started < 1.0
        assert observed == [True], "The deadline must expose recovery, not abandon the daemon commit"
        assert q.completed and c._store_closed and not warning().isVisible()
    finally:
        release.set()
        q.timer.stop()
        if q._finalizer:
            q._finalizer.join(3)
        if warning():
            warning().close()
        window.close()
        c.close()

