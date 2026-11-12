"""Platform adapter contract tests, NOT native Windows notification validation.

Qt's event/signals run offscreen. Native helper traffic uses deterministic fake
QProcess receipts; single-instance mailbox tests use actual local lock files.
"""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QLockFile, QProcess
from PySide6.QtWidgets import QApplication

from global_pulse import native_notifications as native_module
from global_pulse import single_instance as instance_module
from global_pulse.native_notifications import NativeNotifications
from global_pulse.single_instance import SingleInstance


class FakeProcess:
    def __init__(self):
        self.running = True
        self.incoming = b""
        self.writes = []
        self.fail_write = False
        self.wait_results = [True]
        self.waits = []
        self.closed_write = False
        self.terminated = False
        self.killed = False
        self.deleted = False

    def state(self):
        return QProcess.ProcessState.Running if self.running else QProcess.ProcessState.NotRunning

    def write(self, payload):
        self.writes.append(bytes(payload))
        return -1 if self.fail_write else len(payload)

    def readAllStandardOutput(self):
        result, self.incoming = self.incoming, b""
        return result

    def closeWriteChannel(self):
        self.closed_write = True

    def waitForFinished(self, milliseconds):
        self.waits.append(milliseconds)
        result = self.wait_results.pop(0) if self.wait_results else True
        if result:
            self.running = False
        return result

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def deleteLater(self):
        self.deleted = True


class OfflineSocket:
    def connectToServer(self, name):
        pass

    def waitForConnected(self, timeout):
        return False


class FailedDeliverySocket(OfflineSocket):
    def waitForConnected(self, timeout):
        return True

    def write(self, payload):
        return -1

    def disconnectFromServer(self):
        pass


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bridge(qt_app):
    bridge = NativeNotifications()
    bridge.process = FakeProcess()
    bridge.status = "Registering Windows notifications"
    yield bridge
    bridge.stop()


def event(identifier="event-a", alert="alert-a"):
    return {"id": identifier, "_alert_id": alert, "title": "Regional development — Δ", "region": "North Atlantic",
            "severity": "high", "verification": "developing", "updated_at": "2026-11-08T12:00:00Z"}


def delivery_log(bridge):
    rows = []
    bridge.delivery_changed.connect(lambda identifier, status: rows.append((identifier, status)))
    return rows


def feed(bridge, payload):
    bridge.process.incoming += (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    bridge._read()


def test_exact_alert_receipts_for_two_alerts_on_same_event(bridge):
    bridge.ready = True
    results = delivery_log(bridge)
    assert bridge.notify(event(alert="alert-one"), "Official update")
    assert bridge.notify(event(alert="alert-two"), "Correction")
    written = [json.loads(payload) for payload in bridge.process.writes]
    assert [row["alert_id"] for row in written] == ["alert-one", "alert-two"]
    assert written[0]["title"].endswith("Δ")
    feed(bridge, {"type": "submitted", "event_id": "event-a", "alert_id": "alert-two", "setting": "Enabled"})
    feed(bridge, {"type": "submitted", "event_id": "event-a", "alert_id": "alert-one", "setting": "Enabled"})
    assert [row[0] for row in results] == ["alert-two", "alert-one"]
    assert all("Submitted to Windows" in row[1] for row in results)
    assert all("visibility depends" in row[1] for row in results)
    assert not any("displayed" in row[1].lower() or "shown" in row[1].lower() for row in results)
    assert not bridge._inflight


def test_windows_suppression_is_not_claimed_as_visual_delivery(bridge):
    bridge.ready = True
    results = delivery_log(bridge)
    bridge.notify(event(), "Official update")
    feed(bridge, {"type": "submitted", "event_id": "event-a", "alert_id": "alert-a", "setting": "DisabledForApplication"})
    assert results == [("alert-a", "Windows reports DisabledForApplication; saved in alert history")]


def test_unmatched_or_mismatched_receipt_cannot_update_another_alert(bridge):
    bridge.ready = True
    results = delivery_log(bridge)
    bridge.notify(event(), "Update")
    feed(bridge, {"type": "submitted", "event_id": "wrong-event", "alert_id": "alert-a", "setting": "Enabled"})
    feed(bridge, {"type": "submitted", "event_id": "event-a", "alert_id": "other-alert", "setting": "Enabled"})
    assert not results
    assert "alert-a" in bridge._inflight
    assert bridge.status == "Invalid notification-helper response"


def test_registration_queue_is_bounded_and_duplicate_safe(bridge, monkeypatch):
    monkeypatch.setattr(native_module.time, "monotonic", lambda: 100)
    results = delivery_log(bridge)
    for i in range(32):
        assert bridge.notify(event(alert=f"alert-{i}"), "Update")
    assert len(bridge._pending) == 32
    assert bridge.notify(event(alert="alert-0"), "Duplicate")
    assert len(bridge._pending) == 32
    assert not bridge.notify(event(alert="overflow-alert"), "Overflow")
    assert "queue is full" in results[-1][1]
    assert results[-1][0] == "overflow-alert"
    assert not bridge.process.writes


def test_registration_queue_expires_with_exact_alert_identity(bridge, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(native_module.time, "monotonic", lambda: clock[0])
    results = delivery_log(bridge)
    bridge.notify(event(alert="queued-alert"), "Update")
    clock[0] = 116.0
    bridge._flush()
    assert not bridge._pending and not bridge.process.writes
    assert results[-1] == ("queued-alert", "Native registration timed out; retained in history")


@pytest.mark.parametrize("state", ["paused", "quiet", "muted"])
def test_predicate_rechecked_when_registration_completes(bridge, state):
    allowed = [True]
    bridge.predicate = lambda: allowed[0]
    results = delivery_log(bridge)
    bridge.notify(event(alert=f"{state}-alert"), "Update")
    allowed[0] = False
    feed(bridge, {"type": "ready", "setting": "Enabled"})
    assert not bridge.process.writes and not bridge._pending
    assert results[-1][0] == f"{state}-alert"
    assert "suppressed" in results[-1][1]


def test_ready_receipt_flushes_pending_request_once(bridge):
    bridge.notify(event(), "Update")
    feed(bridge, {"type": "ready", "setting": "Enabled"})
    assert len(bridge.process.writes) == 1 and not bridge._pending
    feed(bridge, {"type": "ready", "setting": "Enabled"})
    assert len(bridge.process.writes) == 1
    assert not bridge.notify(event(), "Unsafe blind retry")
    assert len(bridge.process.writes) == 1


def test_write_failure_is_recorded_and_never_blindly_retried(bridge):
    bridge.ready = True
    bridge.process.fail_write = True
    results = delivery_log(bridge)
    assert not bridge.notify(event(), "Update")
    assert "submission outcome unknown" in results[-1][1]
    bridge.process.fail_write = False
    assert not bridge.notify(event(), "Retry")
    assert len(bridge.process.writes) == 1


def test_missing_acknowledgement_is_unknown_and_not_retried(bridge, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(native_module.time, "monotonic", lambda: clock[0])
    bridge.ready = True
    results = delivery_log(bridge)
    bridge.notify(event(), "Update")
    clock[0] = 116.0
    bridge._flush()
    assert results[-1][0] == "alert-a"
    assert "acknowledgement timed out" in results[-1][1]
    assert "outcome unknown" in results[-1][1]
    assert not bridge.notify(event(), "Retry")
    assert len(bridge.process.writes) == 1


@pytest.mark.parametrize("payload", [["ready"], None, "ready", {"type":"submitted","alert_id":"../invalid"}, {"type":"activate","event_id":"../../bad"}, {"type":"unknown"}])
def test_malformed_native_messages_are_contained(bridge, payload):
    results = delivery_log(bridge)
    feed(bridge, payload)
    assert bridge.status == "Invalid notification-helper response"
    assert not results


@pytest.mark.parametrize("item", [event(identifier="../bad"), event(alert="bad\nalert"), event(alert="x" * 129), {"id":None,"_alert_id":"alert-a"}])
def test_malformed_ids_are_rejected_before_queueing(bridge, item):
    with pytest.raises(ValueError):
        bridge.notify(item, "Update")
    assert not bridge._pending and not bridge.process.writes


def test_native_activation_preserves_exact_event(bridge):
    seen = []
    bridge.activated.connect(seen.append)
    feed(bridge, {"type":"activate", "event_id":"event-123:revision"})
    assert seen == ["event-123:revision"]


def test_full_stop_clears_pending_and_child_with_bounded_escalation(bridge):
    process = bridge.process
    process.wait_results = [False, False, True]
    bridge.ready = True
    bridge.notify(event(alert="inflight-alert"), "Update")
    bridge.ready = False
    bridge.notify(event(alert="pending-alert"), "Update")
    results = delivery_log(bridge)
    bridge._buffer = b"partial"
    bridge._queue_timer.start()
    bridge.stop()
    assert bridge.process is None and not bridge.ready and not bridge._pending and not bridge._inflight
    assert bridge._buffer == b"" and not bridge._queue_timer.isActive()
    assert process.closed_write and process.terminated and process.killed and process.deleted
    assert process.waits == [3000,1000,1000]
    assert process.writes[-1] == b'{"command":"exit"}\n'
    assert {row[0] for row in results} == {"pending-alert", "inflight-alert"}
    assert not bridge.notify(event(alert="after-exit"), "Update")


def test_late_ready_cannot_reactivate_a_stopping_bridge(bridge):
    bridge._stopped = True
    feed(bridge, {"type":"ready", "setting":"Enabled"})
    assert not bridge.ready


def test_helper_exit_marks_pending_and_uncertain_inflight_separately(bridge):
    bridge.ready = True
    bridge.notify(event(alert="sent"), "Update")
    bridge.ready = False
    bridge.notify(event(alert="unsent"), "Update")
    results = delivery_log(bridge)
    bridge._finished()
    statuses = dict(results)
    assert "before submission" in statuses["unsent"]
    assert "outcome unknown" in statuses["sent"]
    assert not bridge._inflight and not bridge._pending and not bridge.ready


def test_two_instance_mailbox_fallback_routes_exact_id_without_second_owner(tmp_path, qt_app, monkeypatch):
    monkeypatch.setattr(instance_module, "QLocalSocket", OfflineSocket)
    primary = SingleInstance(tmp_path)
    secondary = SingleInstance(tmp_path)
    try:
        assert primary.acquire()
        seen = []
        primary.activated.connect(seen.append)
        assert not secondary.acquire("exact-event-42")
        assert primary.owner and not secondary.owner
        assert len(list(primary.inbox.glob("*.json"))) == 1
        primary._mailbox()
        assert seen == ["exact-event-42"]
        assert not list(primary.inbox.glob("*.json"))
    finally:
        secondary.close()
        primary.close()


def test_mailbox_file_becomes_visible_only_after_atomic_commit(tmp_path, qt_app, monkeypatch):
    monkeypatch.setattr(instance_module, "QLocalSocket", OfflineSocket)
    primary, secondary = SingleInstance(tmp_path), SingleInstance(tmp_path)
    try:
        assert primary.acquire()
        seen, interleavings = [], []
        primary.activated.connect(seen.append)
        actual_replace = os.replace
        def observe_before_commit(source, destination):
            interleavings.append((Path(source).suffix, Path(destination).suffix))
            assert not list(primary.inbox.glob("*.json"))
            primary._mailbox()
            assert not seen
            actual_replace(source, destination)
        monkeypatch.setattr(instance_module.os, "replace", observe_before_commit)
        assert not secondary.acquire("atomic-event")
        assert interleavings == [(".tmp", ".json")]
        primary._mailbox()
        assert seen == ["atomic-event"]
        assert not list(primary.inbox.glob("*.tmp"))
    finally:
        secondary.close()
        primary.close()


def test_socket_write_failure_falls_back_to_mailbox(tmp_path, qt_app, monkeypatch):
    monkeypatch.setattr(instance_module, "QLocalSocket", OfflineSocket)
    primary, secondary = SingleInstance(tmp_path), SingleInstance(tmp_path)
    try:
        assert primary.acquire()
        seen = []
        primary.activated.connect(seen.append)
        monkeypatch.setattr(instance_module, "QLocalSocket", FailedDeliverySocket)
        assert not secondary.acquire("fallback-event")
        primary._mailbox()
        assert seen == ["fallback-event"]
        assert not secondary.owner
    finally:
        secondary.close()
        primary.close()


def test_mailbox_rejects_malformed_expired_and_oversized_files(tmp_path, qt_app, monkeypatch):
    monkeypatch.setattr(instance_module, "QLocalSocket", OfflineSocket)
    primary = SingleInstance(tmp_path)
    try:
        assert primary.acquire()
        seen = []
        primary.activated.connect(seen.append)
        (primary.inbox / "bad.json").write_text('{"event_id":"../../bad"}')
        (primary.inbox / "list.json").write_text('[]')
        expired = primary.inbox / "expired.json"
        expired.write_text('{"event_id":"expired"}')
        os.utime(expired, (time.time() - 120, time.time() - 120))
        (primary.inbox / "large.json").write_text("x" * 2049)
        primary._mailbox()
        assert not seen and not list(primary.inbox.glob("*.json"))
    finally:
        primary.close()


def test_mailbox_queue_has_finite_capacity(tmp_path, qt_app, monkeypatch):
    monkeypatch.setattr(instance_module, "QLocalSocket", OfflineSocket)
    primary, secondary = SingleInstance(tmp_path), SingleInstance(tmp_path)
    try:
        assert primary.acquire()
        for i in range(32):
            (primary.inbox / f"{i}.json").write_text(json.dumps({"event_id":f"event-{i}"}))
        with pytest.raises(RuntimeError, match="too many"):
            secondary.acquire("overflow")
        assert not secondary.owner
        assert len(list(primary.inbox.glob("*.json"))) == 32
    finally:
        secondary.close()
        primary.close()


def test_lock_permission_failure_is_not_misreported_as_existing_owner(tmp_path, qt_app, monkeypatch):
    monkeypatch.setattr(instance_module, "QLocalSocket", OfflineSocket)
    instance = SingleInstance(tmp_path)
    class BrokenLock:
        def tryLock(self, timeout):
            return False
        def error(self):
            return QLockFile.LockError.PermissionError
    instance.lock = BrokenLock()
    with pytest.raises(RuntimeError, match="single-instance lock"):
        instance.acquire("event-a")
    assert not instance.owner and not list(instance.inbox.glob("*.json"))
    instance.close()


def test_mailbox_rejects_real_symlink_when_host_supports_it(tmp_path, qt_app, monkeypatch):
    monkeypatch.setattr(instance_module, "QLocalSocket", OfflineSocket)
    primary = SingleInstance(tmp_path)
    try:
        assert primary.acquire()
        outside = tmp_path / "outside.txt"
        outside.write_text('{"event_id":"outside"}')
        try:
            (primary.inbox / "link.json").symlink_to(outside)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("Real symlink fixture unavailable: ordinary Windows token lacks symlink privilege")
            raise
        seen = []
        primary.activated.connect(seen.append)
        primary._mailbox()
        assert not seen and not list(primary.inbox.glob("*.json"))
        assert outside.read_text() == '{"event_id":"outside"}'
    finally:
        primary.close()
