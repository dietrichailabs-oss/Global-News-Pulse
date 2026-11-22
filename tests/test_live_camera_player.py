"""Offline camera-host lifecycle; subprocess fixtures never prove native video."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from global_pulse.camera_context import camera_catalog
import global_pulse.live_camera as live


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline camera test attempted network or external browser")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(QDesktopServices, "openUrl", forbidden)


class ProcessFixture(QObject):
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    errorOccurred = Signal(object)
    finished = Signal(int, int)
    ProcessState = QProcess.ProcessState
    ProcessChannelMode = QProcess.ProcessChannelMode

    def __init__(self, parent=None):
        super().__init__(parent)
        self.started = None
        self.writes = []
        self.output = b""
        self.killed = False
        self.write_closed = False
        self._state = self.ProcessState.NotRunning

    def setProcessChannelMode(self, value):
        self.channels = value

    def start(self, executable, args):
        self.started = (executable, args)
        self._state = self.ProcessState.Running

    def state(self):
        return self._state

    def write(self, payload):
        self.writes.append(payload)

    def closeWriteChannel(self):
        self.write_closed = True

    def kill(self):
        self.killed = True

    def processId(self):
        return 4242

    def readAllStandardOutput(self):
        value, self.output = self.output, b""
        return value

    def readAllStandardError(self):
        return b""

    def send(self, **event):
        self.output += (json.dumps({"camera_id": self._camera_id, **event}) + "\n").encode()
        self.readyReadStandardOutput.emit()

    def finish(self):
        self._state = self.ProcessState.NotRunning
        self.finished.emit(0, 0)

    def waitForFinished(self, timeout):
        self.wait_timeout = timeout
        return self._state == self.ProcessState.NotRunning


@pytest.fixture
def camera(app, monkeypatch):
    sessions = []

    class Process(ProcessFixture):
        def __init__(self, parent=None):
            super().__init__(parent)
            sessions.append(self)

    monkeypatch.setattr(live, "QProcess", Process)
    monkeypatch.setattr(live, "_native_session_guard", lambda: None)
    monkeypatch.setattr(live.LiveCamera, "executable", staticmethod(lambda: Path("/fixture/camera/GlobalPulse.Camera.exe")))
    monkeypatch.setattr(live.LiveCamera, "_attach_window", lambda *args: True)
    item = next(row for row in camera_catalog() if row.get("id") == "gpc-tannum-sands-live")
    widget = live.LiveCamera(item)
    yield widget, sessions
    widget.shutdown()
    for process in sessions:
        if process.state() != Process.ProcessState.NotRunning:
            process.finish()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_initialization_does_not_start_browser_and_uses_immutable_registry(camera):
    widget, sessions = camera
    assert not widget.active and not widget.closed and not sessions
    assert widget._process is None
    assert isinstance(widget.item["allowed_hosts"], tuple)
    with pytest.raises(TypeError):
        widget.item["url"] = "https://unreviewed.example/"


def test_start_only_sends_finite_id_and_parent_hwnd_not_url(camera):
    widget, sessions = camera
    assert widget.start() is True
    process = sessions[0]
    assert process.started[1] == [widget.item["id"], str(int(widget.winId()))]
    assert "https" not in str(process.started)
    assert widget.deadline.isActive() and widget.active
    assert widget.start() is True and len(sessions) == 1


def test_loaded_is_not_playback_and_ready_requires_private_owned_window(camera):
    widget, sessions = camera
    messages = []
    widget.status_changed.connect(messages.append)
    widget.start()
    process = sessions[0]
    process.send(type="ready", hwnd=123, in_private=True)
    process.send(type="page_loaded", success=True)
    assert widget.active and not widget.deadline.isActive()
    assert "not automatically verified" in messages[-1]
    assert not any("playing" in message.lower() for message in messages)


@pytest.mark.parametrize("event", [
    {"type": "ready", "hwnd": 123, "in_private": False},
    {"type": "ready", "hwnd": True, "in_private": True},
    {"type": "ready", "hwnd": -1, "in_private": True},
    {"type": "page_loaded", "success": True},
    {"type": "ready", "hwnd": 123, "in_private": True, "camera_id": "arbitrary"},
])
def test_invalid_ready_or_identity_stops(camera, event):
    widget, sessions = camera
    widget.start()
    sessions[0].send(**event)
    assert not widget.active and widget._process is None
    assert "Source" in widget.message.text()
    assert sessions[0].writes == [b"STOP\n"]


def test_failed_window_attachment_stops(camera, monkeypatch):
    widget, sessions = camera
    widget.start()
    monkeypatch.setattr(widget, "_attach_window", lambda *a: False)
    sessions[0].send(type="ready", hwnd=123, in_private=True)
    assert not widget.active and "could not attach" in widget.message.text()


def test_stop_idempotent_retires_exact_process_and_watchdog_survives_widget(camera, app):
    widget, sessions = camera
    widget.start()
    process = sessions[0]
    widget.stop()
    widget.stop()
    assert widget._process is None and not widget.active and not widget.deadline.isActive()
    assert process.writes == [b"STOP\n"] and process.write_closed
    assert process.parent() is app
    timers = process.findChildren(QTimer)
    assert len(timers) == 1 and timers[0].isActive()
    timers[0].timeout.emit()
    assert process.killed
    assert "cleanup requested" in widget.message.text()


def test_retired_ready_and_finished_cannot_replace_new_session_status(camera):
    widget, sessions = camera
    messages = []
    widget.status_changed.connect(messages.append)
    widget.start()
    old = sessions[0]
    widget.stop()
    widget.start()
    current = sessions[1]
    last = messages[-1]
    old.send(type="ready", hwnd=123, in_private=True)
    old.send(type="page_loaded", success=True)
    old.send(type="privacy_cleanup", state="pending")
    old.finish()
    assert widget._process is current and widget.active
    assert messages[-1] == last
    assert live.cleanup_outcomes()[-1] == {"camera_id": widget.item["id"], "state": "pending"}


def test_cleanup_receipt_keeps_only_finite_state_no_paths_or_tokens(camera):
    widget, sessions = camera
    widget.start()
    process = sessions[0]
    process.send(type="privacy_cleanup", state="removed", path="secret", token="secret")
    process.finish()
    assert widget.cleanup_state == "removed" and not widget.active
    assert "secret" not in str(live.cleanup_outcomes())
    assert "profile removed" in widget.message.text()


def test_crash_without_cleanup_receipt_remains_unknown(camera):
    widget, sessions = camera
    widget.start()
    sessions[0].finish()
    assert not widget.active and widget.cleanup_state == "unknown"
    assert "unconfirmed" in widget.message.text()


@pytest.mark.parametrize("payload", [b"not-json\n", b"x" * (live._MAX_STATUS + 1)])
def test_malformed_or_oversize_status_fails_closed(camera, payload):
    widget, sessions = camera
    widget.start()
    sessions[0].output = payload
    sessions[0].readyReadStandardOutput.emit()
    assert not widget.active
    assert "invalid status" in widget.message.text()


def test_timeout_error_hide_and_terminal_shutdown(camera, app):
    widget, sessions = camera
    widget.show()
    app.processEvents()
    widget.start()
    widget._timeout()
    assert not widget.active and "timed out" in widget.message.text()
    widget.start()
    sessions[-1].errorOccurred.emit("fixture failure")
    assert not widget.active
    widget.start()
    widget.hide()
    assert not widget.active
    count = len(sessions)
    widget.show()
    app.processEvents()
    assert len(sessions) == count
    widget.shutdown()
    assert widget.closed and widget.start() is False
    assert len(sessions) == count


def test_missing_helper_reports_source_fallback_without_process(camera, monkeypatch):
    widget, sessions = camera
    monkeypatch.setattr(live.LiveCamera, "executable", staticmethod(lambda: None))
    assert widget.start() is False and not sessions and not widget.active
    assert "Source" in widget.message.text()


def test_caller_metadata_cannot_expand_native_trust(app):
    item = next(row for row in camera_catalog() if row.get("id") == "gpc-tannum-sands-live")
    forged = dict(item, allowed_hosts=["unreviewed.example"], allowed_frame_hosts=["unreviewed.example"])
    widget = live.LiveCamera(forged)
    assert "unreviewed.example" not in widget.item["allowed_hosts"]
    widget.deleteLater()
    for forged in (dict(item, id="unknown"), dict(item, url="https://unreviewed.example/"),
                   dict(item, snapshot_url="https://unreviewed.example/snapshot.jpg")):
        with pytest.raises(ValueError):
            live.LiveCamera(forged)


@pytest.mark.parametrize("host", [
    "*.ipcamlive.com", "localhost", "127.0.0.1", "169.254.169.254", "host.internal",
    "www.youtube.com", "youtube-nocookie.com", "a.googlevideo.com", "kiwisdr.com",
    "host:443", "name@host.example",
])
def test_unsafe_or_retired_hosts_rejected(app, monkeypatch, host):
    import global_pulse.camera_context as context
    item = next(row for row in camera_catalog() if row.get("id") == "gpc-tannum-sands-live")
    forged = dict(item, allowed_hosts=[host], allowed_frame_hosts=[host])
    monkeypatch.setattr(context, "approved_camera", lambda _: forged)
    with pytest.raises(ValueError):
        live.LiveCamera(item)


def test_native_host_source_contract_no_arbitrary_url_or_provider_identity_workaround():
    source = (ROOT / "packaging/camera/NativeCameraProgram.cs").read_text()
    policy = (ROOT / "packaging/camera/CameraPolicy.cs").read_text()
    assert "catalog.TryGetValue(args[0]" in source
    assert 'web.Navigate(camera.WatchUrl)' in source
    assert "IsInPrivateModeEnabled = true" in source
    assert "OwnedProcessJob.Contains(browserProcess.Handle)" in source
    assert 'e.State = CoreWebView2PermissionState.Deny' in source
    assert 'CoreWebView2ServerCertificateErrorAction.Cancel' in source
    assert "Directory.Delete(path, recursive: true)" in source
    assert '["bsyc-seacliff-live"]' in policy
    assert "--no-sandbox" not in source and "UserAgent =" not in source
