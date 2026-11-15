"""Windows-only, offline visual check for embedded WebView2 composition.

The standalone native codec probe can decode H.264 while the Qt media pane
remains black. This test instead checks pixels of a known HTML color that the
same WebView2 child presents through the actual Qt window-container path.
It is synthetic display QA, not a claim that YouTube video/audio played.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.native_tv import NativeTvHost


def run(helper: Path) -> int:
    if sys.platform != "win32" or not helper.is_file():
        raise RuntimeError("Native embed probe requires the built Windows TV helper")
    app = QApplication.instance() or QApplication([])
    host = NativeTvHost()
    host.setWindowTitle("Global Pulse offline visual QA")
    host.resize(800, 500)
    host.move(80, 80)
    host.show()
    app.processEvents()
    parent = int(host.winId())
    if not parent:
        raise RuntimeError("Qt parent HWND unavailable")
    events = []
    process = QProcess(host)
    process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
    process.readyReadStandardOutput.connect(lambda: host._consume(process))
    process.errorOccurred.connect(lambda error: host._failed(process, error))
    process.finished.connect(lambda code, state: host._finished(process, code))
    host.status_received.connect(events.append)
    host._process = process
    result = {"type": "visual_embed_probe", "network": "none", "marker": "f21a9a"}
    try:
        process.start(str(helper), ["--probe-embed", str(parent)])
        deadline = time.monotonic() + 18.0
        while time.monotonic() < deadline:
            app.processEvents()
            if any(event.get("type") == "error" for event in events):
                raise RuntimeError("Native attach/error: " + repr(events))
            if any(event.get("type") == "embed_probe_ready" for event in events):
                break
            if process.state() == QProcess.ProcessState.NotRunning:
                raise RuntimeError("Native child exited before visual marker: " + repr(events))
            QTest.qWait(40)
        else:
            raise TimeoutError("WebView2 visual marker not received")
        if not host._window_container or not host._child_window:
            raise RuntimeError("Qt foreign-window container was not created")

        # Qt keeps the native foreign HWND in the real scrollable widget tree.
        # Capture the displayed desktop composition, not webpage JS output.
        host._window_container.show()
        host.raise_()
        QTest.qWait(800)
        app.processEvents()
        screen = host.screen()
        shot = screen.grabWindow(parent)
        image = shot.toImage()
        if image.isNull() or image.width() < 200 or image.height() < 150:
            raise RuntimeError("Native desktop screenshot unavailable")
        samples = [(0.25, 0.25), (0.5, 0.25), (0.5, 0.5),
                   (0.75, 0.5), (0.75, 0.75)]
        pixels = []
        for x, y in samples:
            color = image.pixelColor(int(image.width()*x), int(image.height()*y))
            pixels.append([color.red(), color.green(), color.blue()])
        expected = [0xF2, 0x1A, 0x9A]
        visible = sum(max(abs(channel-target) for channel, target in zip(pixel,expected)) <= 30
                      for pixel in pixels)
        result.update({"embedded": True, "image_size": [image.width(), image.height()],
                       "samples": pixels, "visible_marker_samples": visible})
        if visible < 3:
            raise AssertionError("The decoded WebView2 window is still visually black/obscured")
        result["passed"] = True
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        if not result.get("passed"):
            print(json.dumps(dict(result, passed=False, events=events[-5:]), sort_keys=True))
        host.stop()
        if process.state() != QProcess.ProcessState.NotRunning:
            if not process.waitForFinished(4000):
                process.kill()
                process.waitForFinished(1000)
        host.close()
        app.processEvents()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m scripts.issue82_native_embed_probe <GlobalPulse.TV.exe>")
    sys.exit(run(Path(sys.argv[1])))
