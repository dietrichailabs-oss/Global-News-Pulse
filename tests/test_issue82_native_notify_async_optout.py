"""Issue82: turning native Windows alerts OFF must not block the Qt GUI.

Offline synthetic QProcess contract, not evidence of native Windows toast delivery.
"""
from collections import deque
import sys
import time

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from global_pulse.native_notifications import NativeNotifications


class FakeBridge:
    """Minimal nonblocking bridge: deliberately has no waitForFinished method."""

    def __init__(self):
        self.running = True
        self.writes = []
        self.closed = False
        self.terminated = 0
        self.killed = 0
        self.deleted = 0

    def state(self):
        return (QProcess.ProcessState.Running if self.running
                else QProcess.ProcessState.NotRunning)

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def closeWriteChannel(self):
        self.closed = True

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1

    def deleteLater(self):
        self.deleted += 1


def test_opt_out_returns_without_blocking_and_retains_alert_receipts():
    app = QApplication.instance() or QApplication([])
    notifier = NativeNotifications(enabled=True, predicate=lambda: True)
    fake = FakeBridge()
    notifier.process = fake
    notifier.ready = True
    notifier._pending = deque([({"_alert_id": "alert-one"}, "reason", 0)])
    notifier._inflight = {"alert-two": ("event", 0)}
    receipts = []
    notifier.delivery_changed.connect(lambda ident, status: receipts.append((ident, status)))
    try:
        notifier.disable_nonblocking()
        assert notifier._stopped
        assert not notifier.ready
        assert notifier._queue_timer.isActive() is False
        assert fake.writes == [b'{"command":"exit"}\n']
        assert fake.closed
        assert not fake.terminated and not fake.killed
        assert "off" in notifier.status.lower()
        assert [ident for ident, _ in receipts] == ["alert-one", "alert-two"]
        assert all("history" in status for _, status in receipts)
        # No waitForFinished exists on the fake. Calling one would have failed.
        notifier._terminate_disabled(fake)
        assert fake.terminated == 1
        notifier._kill_disabled(fake)
        assert fake.killed == 1
    finally:
        fake.running = False
        notifier._finished()
        notifier.deleteLater()
        app.processEvents()


def test_reopt_in_waits_for_exact_old_bridge_exit_and_reoptout_cancels_restart(monkeypatch):
    app = QApplication.instance() or QApplication([])
    notifier = NativeNotifications(enabled=True)
    fake = FakeBridge()
    notifier.process = fake
    try:
        notifier.disable_nonblocking()
        notifier.start()
        assert notifier._restart_after_async_stop is True
        assert notifier._stopped is True
        # A second OFF request cancels any deferred restart.
        notifier.disable_nonblocking()
        assert notifier._restart_after_async_stop is False
        notifier.start()
        assert notifier._restart_after_async_stop is True
        calls = []
        monkeypatch.setattr(notifier, "start", lambda: calls.append("restart"))
        fake.running = False
        notifier._finished()
        assert notifier.process is None
        assert fake.deleted == 1
        assert calls == ["restart"]
        assert not notifier._stopped
        assert not notifier._restart_after_async_stop
    finally:
        notifier.deleteLater()
        app.processEvents()


def test_no_queued_restart_after_final_application_stop(monkeypatch):
    app = QApplication.instance() or QApplication([])
    notifier = NativeNotifications(enabled=True)
    fake = FakeBridge()
    fake.running = False
    notifier.process = fake
    notifier._restart_after_async_stop = True
    monkeypatch.setattr(notifier, "start", lambda: (_ for _ in ()).throw(
        AssertionError("App exit must not restart helper")))
    try:
        notifier.stop()
        assert notifier._stopped
        assert not notifier._restart_after_async_stop
        notifier._finished()
        assert notifier.process is None
    finally:
        notifier.deleteLater()
        app.processEvents()


def test_actual_qprocess_optout_is_nonblocking_and_writes_exit_frame():
    """Hosted Qt subprocess evidence, still NOT a packaged Windows SDK helper."""
    app = QApplication.instance() or QApplication([])
    notifier = NativeNotifications(enabled=True)
    child = QProcess(notifier)
    # Worker reads one line then exits only for the exact newline-delimited
    # bridge exit frame. Incorrect literal backslash-n would hang here.
    script = (
        "import sys\n"
        "frame=sys.stdin.buffer.readline()\n"
        "raise SystemExit(0 if frame == b'{\"command\":\"exit\"}\\n' else 7)\n"
    )
    ended = []
    child.finished.connect(lambda code, _status: ended.append(code))
    child.finished.connect(notifier._finished)
    child.start(sys.executable, ["-u", "-c", script])
    try:
        assert child.waitForStarted(5000), "The synthetic local child did not launch"
        notifier.process = child
        beginning = time.monotonic()
        notifier.disable_nonblocking()
        assert time.monotonic() - beginning < 1.0, (
            "Settings/tray OFF must not synchronously wait for process exit"
        )
        end_time = time.monotonic() + 4
        while not ended and time.monotonic() < end_time:
            app.processEvents()
            time.sleep(0.005)
        assert ended == [0], "The exact exit frame must retire the real Qt child"
        assert notifier._stopped
        assert notifier.process is None
    finally:
        # _finished() schedules the child for Qt deferred deletion.
        # Never access a potentially deleted QProcess wrapper after exit.
        if not ended and child.state() != QProcess.ProcessState.NotRunning:
            child.kill()
            child.waitForFinished(1000)
        notifier.deleteLater()
        app.processEvents()
