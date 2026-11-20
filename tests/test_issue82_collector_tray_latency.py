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
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.__main__ import _TrayRefreshBridge, _tray_health_state
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

