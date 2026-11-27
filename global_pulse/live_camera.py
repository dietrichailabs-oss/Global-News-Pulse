"""Manual, finite Windows WebView2 cameras; never a generic video browser.

Only a bundled camera ID reaches the packaged helper. The helper has its own
compiled copy of the reviewed watch-page/host policy, uses a fresh InPrivate
temporary profile, and attempts to remove that exact owned folder on shutdown.
No URLs, cookies, player tokens or recordings are sent over the process pipe.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from collections import deque
from pathlib import Path
from time import monotonic
from types import MappingProxyType
from urllib.parse import urlsplit

from PySide6.QtCore import QEvent, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from .security import safe_url

CAMERA_PLAYER_PAGES = MappingProxyType({
    "gpc-tannum-sands-live": "https://widget.coastalcoms.com/video/005972b5-8290-420c-8527-9ce69bbcd2ec",
    "gpc-1770-live": "https://widget.coastalcoms.com/video/e53407e0-915b-4964-b60a-638e1bd32d6d",
    # This camera's standalone embed is unavailable. Keep its public document
    # and provider-created player; the native helper only adjusts its layout.
    "bsyc-seacliff-live": "https://www.ipcamlive.com/bsyc1080",
})
CAMERA_IDS = frozenset(CAMERA_PLAYER_PAGES)
_RETIRED_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtu.be", "googlevideo.com", "ytimg.com", "kiwisdr.com")
_MAX_STATUS = 16_384
_CLEANUP_OUTCOMES = deque(maxlen=32)
_OWNED_PROCESSES = set()
_SHUTDOWN_HOOK = False


def cleanup_outcomes():
    """Bounded, non-sensitive in-memory receipts; never paths or page data."""
    return tuple(dict(receipt) for receipt in _CLEANUP_OUTCOMES)


def _record_cleanup(process, state):
    if state not in {"removed", "pending", "unknown"}:
        return
    if getattr(process, "_camera_cleanup", None) == state:
        return
    process._camera_cleanup = state
    _CLEANUP_OUTCOMES.append({"camera_id": process._camera_id, "state": state})


def _shutdown_processes():
    """At app exit only, share one finite grace period across exact children."""
    processes = tuple(_OWNED_PROCESSES)
    deadline = monotonic() + LiveCamera.STOP_TIMEOUT_MS / 1000
    for process in processes:
        try:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.write(b"STOP\n")
                process.closeWriteChannel()
        except RuntimeError:
            _OWNED_PROCESSES.discard(process)
    for process in processes:
        try:
            remaining = max(0, int((deadline - monotonic()) * 1000))
            if process.state() != QProcess.ProcessState.NotRunning and remaining:
                process.waitForFinished(remaining)
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()  # Only this QProcess and its helper-owned job.
                _record_cleanup(process, "unknown")
            else:
                _OWNED_PROCESSES.discard(process)
        except RuntimeError:
            _OWNED_PROCESSES.discard(process)


def _canonical_camera(item):
    """Use immutable local policy, never caller-supplied hosts or stream URLs."""
    from .camera_context import approved_camera

    if not isinstance(item, dict) or item.get("id") not in CAMERA_IDS:
        raise ValueError("Only the three reviewed live cameras can use this player")
    canonical = approved_camera(item)
    if (not canonical or canonical.get("id") != item["id"]
            or canonical.get("playback") != "live_video"
            or canonical.get("manual_only") is not True or canonical.get("snapshot_url")
            or canonical.get("type") != "webcam"):
        raise ValueError("Camera is not an approved manual live-video entry")
    url = safe_url(canonical["url"])
    player_url = safe_url(canonical.get("player_url", ""))
    if player_url != CAMERA_PLAYER_PAGES[canonical["id"]]:
        raise ValueError("Live camera player page is not in the reviewed registry")
    hosts = canonical.get("allowed_hosts")
    frames = canonical.get("allowed_frame_hosts")
    if (not isinstance(hosts, list) or not 1 <= len(hosts) <= 24
            or not isinstance(frames, list) or not 1 <= len(frames) <= 12):
        raise ValueError("Live camera has no finite reviewed network policy")
    for host in hosts:
        if (not isinstance(host, str) or not host or host != host.strip()
                or any(character in host for character in "/\\:@?#[]*")
                or safe_url("https://" + host + "/") != "https://" + host + "/"
                or host != host.encode("idna").decode("ascii").lower()
                or any(host == denied or host.endswith("." + denied) for denied in _RETIRED_HOSTS)):
            raise ValueError("Live camera hosts must be exact public names")
    if (urlsplit(url).hostname not in hosts or urlsplit(player_url).hostname not in hosts
            or not set(frames).issubset(hosts)):
        raise ValueError("Live camera page or frame is outside its reviewed hosts")
    return MappingProxyType({
        key: tuple(value) if isinstance(value, list) else value
        for key, value in canonical.items()
    })


def _native_session_guard():
    if sys.platform != "win32":
        raise RuntimeError("Live cameras require the packaged Windows player; use Source")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.IsUserAnAdmin.argtypes = ()
    shell32.IsUserAnAdmin.restype = ctypes.c_bool
    if shell32.IsUserAnAdmin():
        raise RuntimeError("Live cameras require a standard Windows user session")
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").lower()
    if (os.environ.get("QTWEBENGINE_DISABLE_SANDBOX", "").strip() not in {"", "0"}
            or any(flag in flags for flag in ("--no-sandbox", "--disable-setuid-sandbox", "--disable-web-security"))):
        raise RuntimeError("Live cameras require browser sandboxing to remain enabled")


class LiveCamera(QWidget):
    status_changed = Signal(str)
    LOAD_TIMEOUT_MS = 30_000
    STOP_TIMEOUT_MS = 4_000

    def __init__(self, item, parent=None):
        canonical = _canonical_camera(item)
        super().__init__(parent)
        self.item = canonical
        self._active = False
        self._closed = False
        self._epoch = 0
        self._process = None
        self._pending = b""
        self._ready = False
        self.cleanup_state = "not_started"
        self._child_window = 0
        self._foreign_window = None
        self._window_container = None
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setMinimumSize(80, 100)
        self.setStyleSheet("background:#10151b;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.message = QLabel("Live video · not connected")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self._layout.addWidget(self.message)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.setInterval(self.LOAD_TIMEOUT_MS)
        self.deadline.timeout.connect(self._timeout)

    @property
    def active(self):
        return self._active

    @property
    def closed(self):
        return self._closed

    @staticmethod
    def executable():
        if sys.platform != "win32":
            return None
        candidate = Path(sys.executable).resolve().parent / "camera" / "GlobalPulse.Camera.exe"
        return candidate if candidate.is_file() else None

    def _status(self, text):
        self.message.setText(text)
        self.status_changed.emit(text)

    def start(self):
        global _SHUTDOWN_HOOK
        if self._closed:
            return False
        if self._active:
            return True
        try:
            _native_session_guard()
            executable = self.executable()
            if executable is None:
                raise RuntimeError("Packaged Windows camera player is unavailable; use Source")
            parent_hwnd = int(self.winId())
            if parent_hwnd <= 0:
                raise RuntimeError("Camera window could not be created; use Source")
        except (OSError, RuntimeError, ValueError) as error:
            self._status(str(error))
            return False
        self._epoch += 1
        self._active = True
        self._ready = False
        self._pending = b""
        process = QProcess(self)
        process._camera_id = self.item["id"]
        process._camera_pending = b""
        process._camera_cleanup = "not_reported"
        self.cleanup_state = "not_reported"
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(lambda p=process: self._consume(p))
        process.readyReadStandardError.connect(lambda p=process: p.readAllStandardError())
        process.errorOccurred.connect(lambda error, p=process: self._failed(p, error))
        process.finished.connect(lambda code, state, p=process: self._finished(p, code))
        process.finished.connect(lambda *_args, p=process: _OWNED_PROCESSES.discard(p))
        _OWNED_PROCESSES.add(process)
        if not _SHUTDOWN_HOOK:
            QApplication.instance().aboutToQuit.connect(_shutdown_processes)
            _SHUTDOWN_HOOK = True
        self._process = process
        self.message.show()
        self._status("Connecting camera player…")
        self.deadline.start()
        # Finite registry ID, not a URL/path/header from a feed or IPC payload.
        process.start(str(executable), [self.item["id"], str(parent_hwnd)])
        return self._active

    def _consume(self, process):
        chunk = bytes(process.readAllStandardOutput())
        current = process is self._process and self._active
        pending = getattr(process, "_camera_pending", b"") + chunk
        if len(pending) > _MAX_STATUS:
            process._camera_pending = b""
            if current:
                self._fail("Camera player sent an invalid status; use Source")
            return
        while b"\n" in pending:
            raw, pending = pending.split(b"\n", 1)
            process._camera_pending = pending
            try:
                event = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                if current:
                    self._fail("Camera player sent an invalid status; use Source")
                return
            if (not isinstance(event, dict) or event.get("camera_id") != process._camera_id
                    or not isinstance(event.get("type"), str)):
                if current:
                    self._fail("Camera player identity did not match; use Source")
                return
            kind = event["type"]
            if kind == "privacy_cleanup":
                state = event.get("state")
                if state in {"removed", "pending"}:
                    _record_cleanup(process, state)
                    if current:
                        self.cleanup_state = state
                continue
            if not current:
                continue  # Only cleanup receipts survive selection retirement.
            if kind == "ready":
                hwnd = event.get("hwnd")
                if (self._ready or type(hwnd) is not int or hwnd <= 0
                        or event.get("in_private") is not True
                        or not self._attach_window(process, hwnd)):
                    self._fail("Private camera player could not attach; use Source")
                    return
                self._ready = True
                self.message.hide()
                self.status_changed.emit("Original camera page connecting · use its Play control")
            elif kind == "page_loaded":
                if not self._ready or event.get("success") is not True:
                    self._fail("Camera page unavailable; use Source or try again later")
                    return
                self.deadline.stop()
                self.status_changed.emit(
                    "Player page loaded · press Play if needed"
                )
            elif kind == "error":
                self._fail("Camera player unavailable (" + self._error_label(event.get("reason")) + "); use Source")
                return
            # Other diagnostic fields are not a playback-success assertion.
        process._camera_pending = pending
        if current:
            self._pending = pending

    @staticmethod
    def _error_label(reason):
        return {"webview2_unavailable": "WebView2 Runtime missing",
                "unsafe_browser_override": "browser override refused",
                "standard_user_required": "standard user required",
                "page_timeout": "page load timed out",
                "renderer_exited": "renderer stopped",
                "codec_unavailable": "video codec unavailable",
                "navigation_failed": "page load failed"}.get(reason, "initialization failed")

    def _failed(self, process, _error):
        if process is self._process and self._active:
            self._fail("Camera player could not start; use Source")

    def _finished(self, process, _code):
        self._consume(process)  # Preserve the final cleanup line before deletion.
        if getattr(process, "_camera_cleanup", None) not in {"removed", "pending"}:
            _record_cleanup(process, "unknown")
        if process is self._process:
            self._process = None
            self._active = False
            self._ready = False
            self.deadline.stop()
            self._pending = b""
            self._release_window()
            self.message.show()
            self.cleanup_state = process._camera_cleanup
            self._status("Camera player stopped · temporary profile cleanup remains unconfirmed"
                         if self.cleanup_state != "removed"
                         else "Camera player stopped · private temporary profile removed")
        process.deleteLater()

    def _timeout(self):
        if self._active:
            self._fail("Camera page timed out; use Source or try again later")

    def _fail(self, text):
        self.stop()
        self._status(text)

    def _attach_window(self, process, hwnd):
        if sys.platform != "win32" or process is not self._process:
            return False
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.IsWindow.argtypes = (ctypes.c_void_p,)
            user32.IsWindow.restype = ctypes.c_bool
            user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
            user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
            user32.GetParent.argtypes = (ctypes.c_void_p,)
            user32.GetParent.restype = ctypes.c_void_p
            user32.SetParent.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
            user32.SetParent.restype = ctypes.c_void_p
            user32.GetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int)
            user32.GetWindowLongPtrW.restype = ctypes.c_void_p
            user32.SetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            handle = ctypes.c_void_p(hwnd)
            pid = ctypes.c_ulong()
            if (not user32.IsWindow(handle)
                    or not user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
                    or pid.value != int(process.processId())):
                return False
            foreign = QWindow.fromWinId(hwnd)
            if foreign is None:
                return False
            container = QWidget.createWindowContainer(foreign, self)
            if container is None:
                return False
            self._foreign_window = foreign
            self._window_container = container
            self._child_window = hwnd
            container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self._layout.addWidget(container)
            container.show()
            container.raise_()
            container.installEventFilter(self)
            parent_hwnd = int(container.winId())
            if not parent_hwnd:
                return False
            style = int(user32.GetWindowLongPtrW(handle, -16) or 0)
            child_style = (style | 0x40000000 | 0x02000000) & ~0x80000000
            if style != child_style:
                ctypes.set_last_error(0)
                user32.SetWindowLongPtrW(handle, -16, ctypes.c_void_p(child_style))
                if ctypes.get_last_error():
                    return False
            if int(user32.GetParent(handle) or 0) != parent_hwnd:
                user32.SetParent(handle, ctypes.c_void_p(parent_hwnd))
            return int(user32.GetParent(handle) or 0) == parent_hwnd and self._resize_native_child()
        except (OSError, TypeError, ValueError, RuntimeError):
            return False

    def _resize_native_child(self):
        container = self._window_container
        if sys.platform != "win32" or not self._child_window or container is None:
            return False
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            from ctypes.wintypes import RECT
            user32.GetClientRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(RECT))
            user32.GetClientRect.restype = ctypes.c_bool
            user32.SetWindowPos.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint)
            user32.SetWindowPos.restype = ctypes.c_bool
            rectangle = RECT()
            if not user32.GetClientRect(ctypes.c_void_p(int(container.winId())), ctypes.byref(rectangle)):
                return False
            # Win32 client dimensions, not Qt logical pixels, on mixed-DPI screens.
            return bool(user32.SetWindowPos(ctypes.c_void_p(self._child_window), ctypes.c_void_p(),
                                           0, 0, max(1, rectangle.right - rectangle.left), max(1, rectangle.bottom - rectangle.top),
                                           0x0020 | 0x0004 | 0x0040))
        except (OSError, TypeError, ValueError, RuntimeError):
            return False

    def _release_window(self):
        container = self._window_container
        self._window_container = self._foreign_window = None
        self._child_window = 0
        if container is not None:
            container.hide()
            self._layout.removeWidget(container)
            container.deleteLater()

    def eventFilter(self, watched, event):
        if watched is self._window_container and event.type() == QEvent.Type.Resize:
            self._resize_native_child()
        return super().eventFilter(watched, event)

    def stop(self):
        was_active = self._active
        self._active = False
        self._ready = False
        self._epoch += 1
        self.deadline.stop()
        process, self._process = self._process, None
        self._pending = b""
        if process is not None:
            self.cleanup_state = "requested"
            # Retire the process under QApplication, not this soon-deleted
            # widget. Its own bounded watchdog must survive tile replacement.
            process.setParent(QApplication.instance())
            if process.state() != QProcess.ProcessState.NotRunning:
                process.write(b"STOP\n")
                process.closeWriteChannel()
                watchdog = QTimer(process)
                watchdog.setSingleShot(True)
                watchdog.timeout.connect(lambda p=process: p.kill()
                                         if p.state() != QProcess.ProcessState.NotRunning else None)
                process.finished.connect(watchdog.stop)
                watchdog.start(self.STOP_TIMEOUT_MS)
            else:
                _OWNED_PROCESSES.discard(process)
                process.deleteLater()
        self._release_window()
        self.message.show()
        if was_active:
            self._status("Live camera stopped · temporary player profile cleanup requested")

    def shutdown(self):
        self._closed = True
        self.stop()

    def hideEvent(self, event):
        self.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
