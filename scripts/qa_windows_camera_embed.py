#!/usr/bin/env python3
"""Observe the real Windows camera helper embedded in the production Qt host.

Run with the project's Qt-capable Python and an already built runtime:
    python scripts/qa_windows_camera_embed.py --runtime dist/GlobalPulse --output evidence/camera-embed

The helper's existing --probe-embed mode uses about:blank, never a provider
page. This checks native embedding, resizing and Stop, not live video. The
script never installs dependencies, changes desktop settings or accepts an
unavailable test as PASS. It captures pixels from the visible desktop, not a
fabricated Qt rendering or an offscreen browser buffer.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


READY_SECONDS = 30.0
CAPTURE_SECONDS = 2.0
STOP_SECONDS = 4.0
TOTAL_SECONDS = 45.0
MAX_OUTPUT_BYTES = 65_536
MAX_EVENTS = 32
MARKER = (0xF2, 0x1A, 0x9A)
MARKER_TOLERANCE = 8
MIN_MARKER_FRACTION = 0.85
REPORT_NAME = "WINDOWS_CAMERA_EMBED.json"
CAMERA_ID = "gpc-tannum-sands-live"


class Blocked(RuntimeError):
    """A required execution environment is absent; no acceptance result exists."""


class Failed(RuntimeError):
    """An observed native check failed or exceeded its finite deadline."""


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class NativeDesktop:
    """Read exact native window ownership/geometry and visible desktop pixels."""

    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        for name, args, result in (
            ("IsWindow", [wintypes.HWND], wintypes.BOOL),
            ("IsWindowVisible", [wintypes.HWND], wintypes.BOOL),
            ("GetParent", [wintypes.HWND], wintypes.HWND),
            ("GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            ("GetClientRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            ("GetWindowRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            ("ClientToScreen", [wintypes.HWND, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            ("GetDC", [wintypes.HWND], wintypes.HDC),
            ("ReleaseDC", [wintypes.HWND, wintypes.HDC], ctypes.c_int),
        ):
            function = getattr(self.user32, name)
            function.argtypes, function.restype = args, result
        for name, args, result in (
            ("CreateCompatibleDC", [wintypes.HDC], wintypes.HDC),
            ("DeleteDC", [wintypes.HDC], wintypes.BOOL),
            ("SelectObject", [wintypes.HDC, ctypes.c_void_p], ctypes.c_void_p),
            ("DeleteObject", [ctypes.c_void_p], wintypes.BOOL),
            ("BitBlt", [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD], wintypes.BOOL),
            ("GdiFlush", [], wintypes.BOOL),
        ):
            function = getattr(self.gdi32, name)
            function.argtypes, function.restype = args, result

    def geometry(self, widget, helper_pid):
        container = widget._window_container
        child = int(widget._child_window)
        if container is None or not child:
            raise Failed("Production host has no attached native camera window")
        parent = int(container.winId())
        pid = wintypes.DWORD()
        container_rect, child_rect, window_rect = wintypes.RECT(), wintypes.RECT(), wintypes.RECT()
        origin = wintypes.POINT()
        if not self.user32.IsWindow(child) or not self.user32.IsWindowVisible(child):
            raise Failed("Native camera window is missing or not visible")
        if not self.user32.GetWindowThreadProcessId(child, ctypes.byref(pid)) or pid.value != helper_pid:
            raise Failed("Native camera HWND does not belong to the launched helper PID")
        observed_parent = int(self.user32.GetParent(child) or 0)
        if observed_parent != parent:
            raise Failed("Native camera HWND is not parented to the production Qt container")
        if not (self.user32.GetClientRect(parent, ctypes.byref(container_rect))
                and self.user32.GetClientRect(child, ctypes.byref(child_rect))
                and self.user32.GetWindowRect(child, ctypes.byref(window_rect))
                and self.user32.ClientToScreen(parent, ctypes.byref(origin))):
            raise Failed("Could not read native camera viewport bounds")
        width, height = container_rect.right, container_rect.bottom
        actual = (window_rect.left, window_rect.top,
                  window_rect.right - window_rect.left, window_rect.bottom - window_rect.top)
        expected = (origin.x, origin.y, width, height)
        if width < 80 or height < 100 or actual != expected:
            raise Failed(f"Native child bounds do not fill the Qt viewport: actual={actual}, expected={expected}")
        if (child_rect.right, child_rect.bottom) != (width, height):
            raise Failed("Native child client size differs from its Qt container")
        return {"hwnd": child, "parent_hwnd": parent, "pid": pid.value,
                "screen_x": origin.x, "screen_y": origin.y,
                "width": width, "height": height}

    def capture(self, geometry, image_class):
        """BitBlt the actual desktop at physical native-window coordinates."""
        width, height = geometry["width"], geometry["height"]
        if width * height > 4_000_000:
            raise Failed("Native capture exceeds the diagnostic pixel limit")

        class BitmapHeader(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                        ("height", wintypes.LONG), ("planes", wintypes.WORD),
                        ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                        ("image_size", wintypes.DWORD), ("xppm", wintypes.LONG),
                        ("yppm", wintypes.LONG), ("used", wintypes.DWORD),
                        ("important", wintypes.DWORD)]

        class BitmapInfo(ctypes.Structure):
            _fields_ = [("header", BitmapHeader), ("color", wintypes.DWORD * 1)]

        self.gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BitmapInfo),
                                              wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                              wintypes.HANDLE, wintypes.DWORD]
        self.gdi32.CreateDIBSection.restype = ctypes.c_void_p
        desktop = self.user32.GetDC(None)
        memory = bitmap = previous = None
        try:
            if not desktop:
                raise Failed("Visible desktop device context is unavailable")
            memory = self.gdi32.CreateCompatibleDC(desktop)
            if not memory:
                raise Failed("Native screenshot device context could not be created")
            info = BitmapInfo()
            info.header = BitmapHeader(ctypes.sizeof(BitmapHeader), width, -height, 1, 32,
                                       0, width * height * 4, 0, 0, 0, 0)
            pixels = ctypes.c_void_p()
            bitmap = self.gdi32.CreateDIBSection(memory, ctypes.byref(info), 0,
                                                ctypes.byref(pixels), None, 0)
            if not bitmap or not pixels.value:
                raise Failed("Native screenshot bitmap could not be created")
            previous = self.gdi32.SelectObject(memory, bitmap)
            if not previous or previous == ctypes.c_void_p(-1).value:
                raise Failed("Native screenshot bitmap could not be selected")
            # SRCCOPY | CAPTUREBLT reads the composed visible desktop, including
            # layered surfaces. No PrintWindow or synthetic rendering fallback.
            if not self.gdi32.BitBlt(memory, 0, 0, width, height, desktop,
                                    geometry["screen_x"], geometry["screen_y"], 0x40CC0020):
                raise Failed("Native desktop pixel capture failed")
            if not self.gdi32.GdiFlush():
                raise Failed("Native desktop pixel capture did not synchronize")
            raw = ctypes.string_at(pixels, width * height * 4)
            return image_class(raw, width, height, width * 4, image_class.Format.Format_RGB32).copy()
        finally:
            if memory and previous and previous != ctypes.c_void_p(-1).value:
                self.gdi32.SelectObject(memory, previous)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if memory:
                self.gdi32.DeleteDC(memory)
            if desktop:
                self.user32.ReleaseDC(None, desktop)


def marker_fraction(image):
    matches = samples = 0
    for row in range(25):
        y = 4 + row * max(1, image.height() - 9) // 24
        for column in range(33):
            x = 4 + column * max(1, image.width() - 9) // 32
            color = image.pixelColor(x, y)
            actual = color.red(), color.green(), color.blue()
            matches += all(abs(a - b) <= MARKER_TOLERANCE for a, b in zip(actual, MARKER))
            samples += 1
    return matches / samples


def run_probe(runtime, output, report):
    executable = runtime / "camera" / "GlobalPulse.Camera.exe"
    required = ["GlobalPulse.Camera.exe", "GlobalPulse.Camera.dll", "GlobalPulse.Camera.deps.json",
                "GlobalPulse.Camera.runtimeconfig.json", "coreclr.dll",
                "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
                "runtimes/win-x64/native/WebView2Loader.dll"]
    missing = [name for name in required if not (runtime / "camera" / name).is_file()]
    # Read package bytes before any environment refusal so BLOCKED receipts
    # still identify the reviewed helper. This does not launch native code.
    report["helper_payload"] = {name: {"bytes": (runtime / "camera" / name).stat().st_size,
                                       "sha256": sha256(runtime / "camera" / name)}
                                for name in required if name not in missing}
    report["helper_sha256"] = report["helper_payload"].get("GlobalPulse.Camera.exe", {}).get("sha256")
    report["helper_payload_missing"] = missing
    if sys.platform != "win32":
        raise Blocked("Native camera embedding requires a Windows desktop")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.IsUserAnAdmin.argtypes, shell32.IsUserAnAdmin.restype = [], wintypes.BOOL
    if shell32.IsUserAnAdmin():
        raise Blocked("Elevated session refused; run as a standard Windows user")
    if missing:
        raise Blocked("Packaged camera runtime is incomplete: " + ", ".join(missing))
    report["source_host_sha256"] = sha256(Path(__file__).resolve().parents[1] / "global_pulse/live_camera.py")
    try:
        from PySide6.QtCore import QEventLoop, QIODevice, QProcess
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
        from global_pulse.camera_context import camera_catalog
        import global_pulse.live_camera as live
    except ImportError as error:
        raise Blocked("Project Qt runtime unavailable: " + str(error)) from error

    started_at = time.monotonic()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if app.platformName().lower() != "windows":
        raise Blocked("Qt is not using its native Windows platform")
    screen = app.primaryScreen()
    if screen is None:
        raise Blocked("An interactive Windows screen is unavailable")
    available = screen.availableGeometry()
    if available.width() < 400 or available.height() < 300:
        raise Blocked("Available desktop is too small for the bounded native viewport check")
    report["screen"] = {"available_width": available.width(), "available_height": available.height(),
                        "device_pixel_ratio": screen.devicePixelRatio()}

    observations = {"events": [], "bytes": 0, "pid": None, "exit": None,
                    "launch_arguments": None, "protocol_error": None, "process_errors": []}

    class ProbeProcess(QProcess):
        """Keep production pipe consumption intact; change only offline mode."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.receipt_pending = b""
            self.started.connect(lambda: observations.update(pid=int(self.processId())))
            self.finished.connect(self.record_exit)
            self.errorOccurred.connect(lambda error: observations["process_errors"].append(error.name)
                                       if len(observations["process_errors"]) < 8 else None)

        def record_exit(self, code, state):
            observations["exit"] = {"code": int(code), "status": state.name}

        def start(self, program, arguments, mode=QIODevice.OpenModeFlag.ReadWrite):
            if (Path(program).resolve() != executable or len(arguments) != 2
                    or arguments[0] != CAMERA_ID or not str(arguments[1]).isdigit()):
                raise Failed("Diagnostic refused an unexpected helper launch")
            observations["launch_arguments"] = ["--probe-embed", str(arguments[1])]
            super().start(program, observations["launch_arguments"], mode)

        def readAllStandardOutput(self):
            chunk = super().readAllStandardOutput()
            raw = bytes(chunk)
            observations["bytes"] += len(raw)
            if observations["bytes"] > MAX_OUTPUT_BYTES:
                observations["protocol_error"] = "Helper output exceeded the bounded receipt limit"
                return chunk
            self.receipt_pending += raw
            while b"\n" in self.receipt_pending:
                line, self.receipt_pending = self.receipt_pending.split(b"\n", 1)
                try:
                    event = json.loads(line.decode("utf-8"))
                    if not isinstance(event, dict) or event.get("camera_id") != CAMERA_ID:
                        raise ValueError("Unexpected helper receipt identity")
                    if len(observations["events"]) >= MAX_EVENTS:
                        raise ValueError("Too many helper receipts")
                    # This offline mode emits only bounded status fields. Do
                    # not retain arbitrary diagnostic additions or raw output.
                    allowed = {"type", "camera_id", "hwnd", "in_private", "network", "marker", "reason", "state"}
                    observations["events"].append({k: v for k, v in event.items() if k in allowed})
                except (ValueError, UnicodeError) as error:
                    observations["protocol_error"] = str(error)
            return chunk  # The actual unchanged bytes still reach LiveCamera.

    class PackagedLiveCamera(live.LiveCamera):
        @staticmethod
        def executable():
            return executable

    original_process = live.QProcess
    window = widget = None
    native = NativeDesktop()
    live.QProcess = ProbeProcess
    report["checks"] = {}

    def pump():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if time.monotonic() - started_at > TOTAL_SECONDS:
            raise Failed("Native probe exceeded its total 45-second budget")

    def problem():
        if observations["protocol_error"]:
            raise Failed(observations["protocol_error"])
        errors = [event for event in observations["events"] if event.get("type") == "error"]
        if errors:
            reason = errors[-1].get("reason", "unknown")
            if reason in {"standard_user_required", "webview2_unavailable", "unsafe_browser_override"}:
                raise Blocked("Native helper unavailable: " + reason)
            raise Failed("Native helper failed: " + str(reason))
        if observations["exit"] is not None:
            raise Failed("Native helper exited before the embedding checks completed")
        if observations["process_errors"]:
            raise Failed("Native helper process error: " + observations["process_errors"][-1])

    def wait_for(predicate, seconds, label, check_problem=True):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            pump()
            if check_problem:
                problem()
            if predicate():
                return
            time.sleep(0.01)
        raise Failed(label + " exceeded its deadline")

    def capture_stage(name):
        end = time.monotonic() + CAPTURE_SECONDS
        latest_image = latest_geometry = fraction = None
        geometry_error = None
        while time.monotonic() < end:
            pump()
            problem()
            try:
                latest_geometry = native.geometry(widget, observations["pid"])
                latest_image = native.capture(latest_geometry, QImage)
                fraction = marker_fraction(latest_image)
                if fraction >= MIN_MARKER_FRACTION:
                    break
            except Failed as error:
                geometry_error = str(error)
            time.sleep(0.05)
        details = {"geometry": latest_geometry, "marker_fraction": fraction,
                   "marker_rgb": list(MARKER), "minimum_fraction": MIN_MARKER_FRACTION,
                   "channel_tolerance": MARKER_TOLERANCE}
        if latest_image is not None:
            image_path = output / (name + ".png")
            if not latest_image.save(str(image_path), "PNG"):
                raise Failed("Could not save the actual desktop capture")
            details["capture"] = str(image_path)
            details["capture_sha256"] = sha256(image_path)
        report["checks"][name] = details
        if latest_geometry is None or fraction is None or fraction < MIN_MARKER_FRACTION:
            raise Failed(geometry_error or "Actual desktop capture does not show the helper's magenta viewport")
        return latest_geometry

    try:
        item = next(row for row in camera_catalog() if row.get("id") == CAMERA_ID)
        window = QWidget()
        window.setWindowTitle("Global Pulse — offline native camera QA")
        layout = QVBoxLayout(window)
        widget = PackagedLiveCamera(item, window)
        layout.addWidget(widget)
        width, height = min(640, available.width() - 60), min(420, available.height() - 60)
        window.resize(width, height)
        window.move(available.x() + (available.width() - width) // 2,
                    available.y() + (available.height() - height) // 2)
        window.show()
        window.raise_()
        window.activateWindow()
        pump()
        if widget.start() is not True:
            raise Blocked("Production camera host refused startup: " + widget.message.text())
        wait_for(lambda: bool(widget._ready and observations["pid"]
                             and any(event.get("type") == "embed_probe_ready"
                                     and event.get("network") == "none" and event.get("marker") == "f21a9a"
                                     for event in observations["events"])),
                 READY_SECONDS, "Native helper readiness")
        # This offline mode deliberately emits no live page_loaded event.
        # Stop the page-readiness timer only after the actual readiness receipt;
        # all independent diagnostic and Stop deadlines remain in force.
        widget.deadline.stop()
        report["offline_page_deadline_stopped_after_ready"] = True
        report["checks"]["ready"] = {"production_attach": True, "offline_probe_receipt": True}
        initial = capture_stage("initial_viewport")
        window.resize(max(300, width - 120), max(200, height - 90))

        def resized_native_viewport():
            # Qt and WinForms resize messages need not complete in one event
            # turn. A transient bounds mismatch is polled within the deadline.
            try:
                return native.geometry(widget, observations["pid"])["width"] != initial["width"]
            except Failed:
                return False

        wait_for(resized_native_viewport, CAPTURE_SECONDS, "Native resize")
        resized = capture_stage("resized_viewport")
        if resized["width"] >= initial["width"] or resized["height"] >= initial["height"]:
            raise Failed("Native viewport dimensions did not shrink after the Qt host resize")
        if resized["hwnd"] != initial["hwnd"] or resized["pid"] != initial["pid"]:
            raise Failed("Resize replaced the helper instead of resizing the same native child")
        widget.stop()  # Exercise the production STOP pipe and its own watchdog.
        wait_for(lambda: observations["exit"] is not None, STOP_SECONDS,
                 "Production Stop and native process exit", check_problem=False)
        remaining_pid = wintypes.DWORD()
        original_window_remains = bool(native.user32.IsWindow(initial["hwnd"])
                                       and native.user32.GetWindowThreadProcessId(initial["hwnd"], ctypes.byref(remaining_pid))
                                       and remaining_pid.value == initial["pid"])
        report["checks"]["stop"] = {"host_inactive": not widget.active,
                                      "window_released": widget._child_window == 0,
                                      "owned_native_window_gone": not original_window_remains,
                                      "helper_exit": observations["exit"]}
        if widget.active or widget._child_window or original_window_remains:
            raise Failed("Production Stop retained an active host or attached native window")
        if observations["exit"] != {"code": 0, "status": "NormalExit"}:
            raise Failed("Helper did not exit normally after production Stop")
        cleanup = [event.get("state") for event in observations["events"]
                   if event.get("type") == "privacy_cleanup"]
        report["checks"]["cleanup"] = {"receipts": cleanup}
        if cleanup != ["removed"]:
            raise Failed("Helper temporary-profile removal was not confirmed")
        if observations["protocol_error"]:
            raise Failed(observations["protocol_error"])
        report["status"] = "PASS"
        report["reason"] = "Observed native embedding, desktop pixels, resize, normal Stop and profile-removal receipt"
    finally:
        # Cleanup is limited to the widget and exact helper we started. Never
        # terminate unrelated processes or enumerate/delete profile folders.
        try:
            if widget is not None:
                widget.shutdown()
            if window is not None:
                window.close()
            if observations["pid"] and observations["exit"] is None:
                end = min(time.monotonic() + STOP_SECONDS + 0.5, started_at + TOTAL_SECONDS)
                while observations["exit"] is None and time.monotonic() < end:
                    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
                    time.sleep(0.01)
        finally:
            live.QProcess = original_process
            report["helper_observations"] = observations
            report["teardown_helper_exit_observed"] = observations["exit"] is not None if observations["pid"] else None
            report["duration_seconds"] = round(time.monotonic() - started_at, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True, help="Built GlobalPulse runtime directory")
    parser.add_argument("--output", type=Path, required=True, help="Directory for exact observations and desktop captures")
    args = parser.parse_args()
    runtime, output = args.runtime.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "started_utc": datetime.now(timezone.utc).isoformat(),
              "status": "NOT_RUN", "runtime": str(runtime), "camera_id": CAMERA_ID,
              "scope": "Production-source Windows Qt host plus shipped helper; offline about:blank embedding probe",
              "live_camera_playback_verified": False, "provider_navigation_requested": False,
              "release_approval": False, "maximum_seconds": TOTAL_SECONDS}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        run_probe(runtime, output, report)
    except Blocked as error:
        report.update(status="BLOCKED", reason=str(error))
    except (Failed, OSError, RuntimeError, ValueError, StopIteration) as error:
        report.update(status="FAIL", reason=str(error))
    except Exception as error:
        report.update(status="FAIL", reason=f"Unexpected diagnostic failure: {type(error).__name__}: {error}")
        report["diagnostic_traceback"] = traceback.format_exc(limit=6)
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report_path = output / REPORT_NAME
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "reason": report.get("reason"), "report": str(report_path)}))
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
