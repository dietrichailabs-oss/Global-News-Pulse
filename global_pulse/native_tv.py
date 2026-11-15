"""Explicit Windows-only isolated WebView2 video host.

The packaged .NET helper is a separate standard-user process, not a generic
browser or a data collector. It admits a single validated YouTube video after
the UI's existing consent prompt. QtWebEngine is kept for other media.
"""
from __future__ import annotations

import ctypes
import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QProcess, QTimer, Signal
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QVBoxLayout, QWidget

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_MAX_STATUS = 8192


class NativeTvHost(QWidget):
    status_received = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setMinimumHeight(180)
        self.setStyleSheet("background:#111111;")
        self._child_window = 0
        self._foreign_window = None
        self._window_container = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._process = None
        self._pending = b""

    @staticmethod
    def executable():
        if sys.platform != "win32":
            return None
        exe = Path(sys.executable).resolve().parent / "tv" / "GlobalPulse.TV.exe"
        return exe if exe.is_file() else None

    def play(self, video_id: str, *, full_watch: bool = False) -> bool:
        if not isinstance(video_id, str) or _VIDEO_ID.fullmatch(video_id) is None:
            return False
        exe = self.executable()
        if exe is None:
            return False
        self.stop()
        self._pending = b""
        self.show()
        parent_hwnd = int(self.winId())
        if not parent_hwnd:
            return False
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(lambda p=process: self._consume(p))
        process.errorOccurred.connect(lambda error, p=process: self._failed(p, error))
        process.finished.connect(lambda code, state, p=process: self._finished(p, code))
        self._process = process
        args = [video_id, str(parent_hwnd)]
        if full_watch:
            args.append("--watch")
        process.start(str(exe), args)
        return True

    def _consume(self, process):
        if process is not self._process:
            return
        self._pending += bytes(process.readAllStandardOutput())
        if len(self._pending) > _MAX_STATUS:
            self._pending = b""
            self.status_received.emit({"type": "error", "reason": "oversized_tv_status"})
            self.stop()
            return
        while b"\n" in self._pending:
            raw, self._pending = self._pending.split(b"\n", 1)
            try:
                event = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                continue
            if event["type"] == "ready":
                hwnd = event.get("hwnd")
                if isinstance(hwnd, int) and hwnd > 0 and event.get("in_private") is True:
                    if not self._attach_window(process, hwnd):
                        self.status_received.emit({"type": "error", "reason": "native_window_attach_failed"})
                        self.stop()
                        return
                else:
                    self.status_received.emit({"type": "error", "reason": "private_window_not_ready"})
                    self.stop()
                    return
            self.status_received.emit(event)

    def _failed(self, process, error):
        if process is self._process:
            self.status_received.emit({"type": "error", "reason": "native_process_start_failed"})
            self.stop()

    def _finished(self, process, code):
        if process is self._process:
            self._release_window()
            self._process = None
            self.status_received.emit({"type": "stopped", "exit_code": code})
        process.deleteLater()

    def _attach_window(self, process, hwnd: int) -> bool:
        """Let Qt manage native child clipping and stacking inside QScrollArea.

        The old MoveWindow-only embedding left a decoded WebView2 surface black
        because Qt never owned the foreign HWND's container. The attached HWND
        must belong to the exact QProcess we just launched, not an arbitrary
        address supplied over stdout.
        """
        if sys.platform != "win32" or process is not self._process:
            return False
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.IsWindow.argtypes = (ctypes.c_void_p,)
            user32.IsWindow.restype = ctypes.c_bool
            user32.GetWindowThreadProcessId.argtypes = (
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)
            )
            user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
            user32.GetParent.argtypes = (ctypes.c_void_p,)
            user32.GetParent.restype = ctypes.c_void_p
            user32.SetParent.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
            user32.SetParent.restype = ctypes.c_void_p
            user32.GetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int)
            user32.GetWindowLongPtrW.restype = ctypes.c_void_p
            user32.SetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.SetWindowPos.argtypes = (
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint
            )
            user32.SetWindowPos.restype = ctypes.c_bool
            handle = ctypes.c_void_p(hwnd)
            owner_pid = ctypes.c_ulong()
            if (not user32.IsWindow(handle)
                    or not user32.GetWindowThreadProcessId(handle, ctypes.byref(owner_pid))
                    or owner_pid.value != int(process.processId())):
                return False
            foreign = QWindow.fromWinId(hwnd)
            if foreign is None:
                return False
            container = QWidget.createWindowContainer(foreign, self)
            if container is None:
                return False
            container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self._foreign_window = foreign
            self._window_container = container
            self._child_window = hwnd
            self._layout.addWidget(container)
            container.show()
            container.raise_()
            container.installEventFilter(self)
            # Qt's foreign-window wrapper can resize and visibly paint an
            # unmanaged *top-level* HWND over the desktop. That passes a naive
            # screenshot test but can sit behind the Qt viewport for the owner.
            # Require a real Win32 child of the exact Qt native container.
            parent_hwnd = int(container.winId())
            if not parent_hwnd:
                return False
            old_style = int(user32.GetWindowLongPtrW(handle, -16) or 0)
            child_style = (old_style | 0x40000000 | 0x02000000) & ~0x80000000
            if old_style != child_style:
                ctypes.set_last_error(0)
                user32.SetWindowLongPtrW(handle, -16, ctypes.c_void_p(child_style))
                if ctypes.get_last_error() != 0:
                    return False
            if int(user32.GetParent(handle) or 0) != parent_hwnd:
                user32.SetParent(handle, ctypes.c_void_p(parent_hwnd))
            if int(user32.GetParent(handle) or 0) != parent_hwnd:
                return False
            if not self._resize_native_child():
                return False
            return True
        except (OSError, TypeError, ValueError, RuntimeError):
            return False

    def _release_window(self):
        container = self._window_container
        self._window_container = None
        self._foreign_window = None
        self._child_window = 0
        if container is not None:
            container.hide()
            self._layout.removeWidget(container)
            container.deleteLater()

    def eventFilter(self, watched, event):
        if watched is self._window_container and event.type() == QEvent.Type.Resize:
            self._resize_native_child()
        return super().eventFilter(watched, event)

    def _resize_native_child(self) -> bool:
        container = self._window_container
        if sys.platform != "win32" or not self._child_window or container is None:
            return False
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.SetWindowPos.argtypes = (
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint
            )
            user32.SetWindowPos.restype = ctypes.c_bool
            return bool(user32.SetWindowPos(
                ctypes.c_void_p(self._child_window), ctypes.c_void_p(), 0, 0,
                max(1, container.width()), max(1, container.height()),
                0x0020 | 0x0004 | 0x0040  # FRAMECHANGED, NOZORDER, SHOWWINDOW
            ))
        except (OSError, TypeError, ValueError, RuntimeError):
            return False

    def command(self, value: str):
        process = self._process
        if process is not None and process.state() == QProcess.ProcessState.Running:
            process.write((value + "\n").encode("ascii"))

    def stop(self):
        process = self._process
        self._process = None
        self._release_window()
        self._pending = b""
        if process is not None:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.write(b"STOP\n")
                # Give the helper time to dispose its private browser profile.
                # The UI hides immediately and never blocks on that cleanup.
                # An unresponsive child is killed after the finite deadline.
                # Timer lifetime is owned by this exact child QProcess.
                # A global singleShot callback captured a Python wrapper
                # after deleteLater() had destroyed its native Qt object
                # during rapid Stop/Watch cycles.
                watchdog=QTimer(process)
                watchdog.setSingleShot(True)
                watchdog.timeout.connect(
                    lambda p=process: p.kill()
                    if p.state() != QProcess.ProcessState.NotRunning else None
                )
                process.finished.connect(watchdog.stop)
                watchdog.start(3000)
                process.finished.connect(lambda *_args, p=process: p.deleteLater())
            else:
                # A very fast or failed child may have finished before Stop;
                # do not wait for a finished signal already delivered.
                process.deleteLater()
        self.hide()
