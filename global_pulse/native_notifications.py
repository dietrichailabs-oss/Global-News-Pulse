"""Windows App SDK bridge. Submission is never reported as visible delivery."""
from __future__ import annotations

import json
import sys
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .security import event_id, redact


class NativeNotifications(QObject):
    activated = Signal(str)
    status_changed = Signal(str)
    # First argument is the exact internal alert ID, never merely the event ID.
    delivery_changed = Signal(str, str)

    def __init__(self, *, enabled=True, predicate=None, parent=None):
        super().__init__(parent)
        self.enabled = enabled
        self.process = None
        self.ready = False
        self.status = "Internal alert history available"
        self._buffer = b""
        self.predicate = predicate or (lambda: True)
        self._pending = deque()
        self._inflight = {}
        self._attempted = deque(maxlen=256)
        self._stopped = False
        self._queue_timer = QTimer(self)
        self._queue_timer.setInterval(1000)
        self._queue_timer.timeout.connect(self._flush)

    def start(self):
        if not self.enabled:
            self._status("Synthetic mode · Windows notifications disabled")
            return
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if sys.platform != "win32":
            self._status("Windows notifications require Windows; internal alert history is active")
            return
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        candidates = [base / "notifications" / "GlobalPulse.Notifications.exe", base / "build" / "notifications" / "GlobalPulse.Notifications.exe"]
        executable = next((p for p in candidates if p.is_file()), None)
        if executable is None:
            self._status("Native notification component is missing; use the complete Windows build")
            return
        self._stopped = False
        self._buffer = b""
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.errorOccurred.connect(lambda _: self._status("Windows notification helper failed; alerts remain in history"))
        self.process.finished.connect(self._finished)
        self.process.start(str(executable), ["--bridge"])
        self._queue_timer.start()
        self._status("Registering Windows notifications…")

    def _status(self, value):
        self.status = value
        self.status_changed.emit(value)

    def _finished(self, *_):
        self.ready = False
        self._queue_timer.stop()
        while self._pending:
            event, _, _ = self._pending.popleft()
            self.delivery_changed.emit(event["_alert_id"], "Native helper exited before submission; retained in history")
        for alert_id in self._inflight:
            self.delivery_changed.emit(alert_id, "Native helper exited before acknowledgement; submission outcome unknown; retained in history")
        self._inflight.clear()
        self._status("Windows notification helper stopped; alerts remain in history")

    def _read(self):
        if not self.process:
            return
        self._buffer += bytes(self.process.readAllStandardOutput())
        if len(self._buffer) > 65536:
            self._buffer = b""
            self._status("Invalid notification-helper response")
            return
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError("Helper response is not an object")
                kind = data.get("type")
                if kind == "ready":
                    if self._stopped:
                        continue
                    self.ready = True
                    self._status("Windows notification service ready · " + str(data.get("setting", "unknown")))
                    self._flush()
                elif kind == "activate":
                    if not self._stopped:
                        self.activated.emit(event_id(data["event_id"]))
                elif kind == "submitted":
                    identifier = event_id(data["alert_id"])
                    requested = self._inflight.get(identifier)
                    if not requested or event_id(data["event_id"]) != requested[0]:
                        raise ValueError("Receipt does not match an outstanding submission")
                    self._inflight.pop(identifier)
                    status = "Submitted to Windows; visibility depends on Windows settings"
                    if data.get("setting") != "Enabled":
                        status = "Windows reports " + str(data.get("setting")) + "; saved in alert history"
                    self.delivery_changed.emit(identifier, status)
                elif kind == "error":
                    self._status("Windows notification error: " + redact(str(data.get("message", "unknown"))))
                    if data.get("alert_id"):
                        identifier = event_id(data["alert_id"])
                        if identifier in self._inflight:
                            self._inflight.pop(identifier)
                            self.delivery_changed.emit(identifier, self.status)
                else:
                    raise ValueError("Unknown helper response type")
            except (ValueError, KeyError, TypeError, AttributeError):
                self._status("Invalid notification-helper response")

    def notify(self, event, reason):
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            raise ValueError("Invalid notification event")
        identifier = event_id(event["id"])
        raw_alert_id = event.get("_alert_id", identifier)
        if not isinstance(raw_alert_id, str):
            raise ValueError("Invalid alert identifier")
        alert_id = event_id(raw_alert_id)
        # Validate both identities before the registration queue can hold them.
        event = dict(event, id=identifier, _alert_id=alert_id)
        if self._stopped or not self.enabled:
            self.delivery_changed.emit(alert_id, "Native notifications are stopped or disabled; retained in history")
            return False
        if not self.predicate():
            self.delivery_changed.emit(alert_id, "Native notification suppressed by current monitoring/quiet/mute settings")
            return False
        if alert_id in self._attempted:
            # A successful write is not a receipt. Never blindly retry a request
            # after losing the helper's acknowledgement.
            return False
        if any(queued[0]["_alert_id"] == alert_id for queued in self._pending):
            return True
        if not self.ready or not self.process:
            if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
                if len(self._pending) >= 32:
                    self.delivery_changed.emit(alert_id, "Native registration queue is full; retained in history")
                    return False
                self._pending.append((event, reason, time.monotonic()))
                self.delivery_changed.emit(alert_id, "Waiting for native notification registration")
                return True
            self.delivery_changed.emit(alert_id, self.status)
            return False
        data = {
            "command": "notify", "event_id": identifier, "alert_id": alert_id,
            "title": str(event.get("title") or "Global Pulse update")[:150],
            "details": " · ".join([str(event.get("region", "Global")), str(event.get("severity", "unassessed")).title(), str(event.get("verification", "unverified")).title()])[:180],
            "body": (str(reason) + " · " + str(event.get("updated_at", "")))[:350],
        }
        payload = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        self._attempted.append(alert_id)
        written = self.process.write(payload)
        if written != len(payload):
            self.delivery_changed.emit(alert_id, "Native request write failed or was incomplete; submission outcome unknown; retained in history")
            return False
        self._inflight[alert_id] = (identifier, time.monotonic())
        return True

    def _flush(self):
        if self._stopped:
            return
        now = time.monotonic()
        for alert_id, (_, requested_at) in list(self._inflight.items()):
            if now - requested_at > 15:
                self._inflight.pop(alert_id)
                self.delivery_changed.emit(alert_id, "Native acknowledgement timed out; submission outcome unknown; retained in history")
        for _ in range(len(self._pending)):
            event, reason, queued_at = self._pending.popleft()
            if not self.predicate():
                self.delivery_changed.emit(event["_alert_id"], "Native notification suppressed by current monitoring/quiet/mute settings")
            elif now - queued_at > 15:
                self.delivery_changed.emit(event["_alert_id"], "Native registration timed out; retained in history")
            elif self.ready:
                self.notify(event, reason)
            else:
                self._pending.append((event, reason, queued_at))

    def stop(self):
        self._stopped = True
        self.ready = False
        self._queue_timer.stop()
        while self._pending:
            event, _, _ = self._pending.popleft()
            self.delivery_changed.emit(event["_alert_id"], "Application exited before native submission; retained in history")
        for alert_id in self._inflight:
            self.delivery_changed.emit(alert_id, "Application exited before native acknowledgement; submission outcome unknown; retained in history")
        self._inflight.clear()
        process = self.process
        if process and process.state() != QProcess.ProcessState.NotRunning:
            process.write(b'{"command":"exit"}\n')
            process.closeWriteChannel()
            if not process.waitForFinished(3000):
                process.terminate()
                if not process.waitForFinished(1000):
                    process.kill()
                    process.waitForFinished(1000)
        self.process = None
        self._buffer = b""
        self.ready = False
        if process:
            process.deleteLater()
