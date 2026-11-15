"""Windows-only, offline visual check for embedded WebView2 composition.

The standalone native codec probe can decode H.264 while the Qt media pane
remains black. This test instead checks pixels of a known HTML color that the
same WebView2 child presents through the actual Qt window-container path.
It is synthetic display QA, not a claim that YouTube video/audio played.
"""
from __future__ import annotations

import json
import ctypes
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QProcess, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.native_tv import NativeTvHost
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


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
        image = screen.grabWindow(parent).toImage()
        desktop_image = screen.grabWindow(0).toImage()
        child_image = screen.grabWindow(host._child_window).toImage()
        if (image.isNull() or image.width() < 200 or image.height() < 150
                or desktop_image.isNull()):
            raise RuntimeError("Native desktop screenshot unavailable")
        samples = [(0.25, 0.25), (0.5, 0.25), (0.5, 0.5),
                   (0.75, 0.5), (0.75, 0.75)]
        def get_pixels(picture, transform):
            pixels=[]
            for x, y in samples:
                px, py=transform(x, y)
                if picture.isNull() or not (0 <= px < picture.width() and 0 <= py < picture.height()):
                    pixels.append([-1, -1, -1])
                else:
                    color=picture.pixelColor(px,py)
                    pixels.append([color.red(),color.green(),color.blue()])
            return pixels

        host_pixels=get_pixels(image,lambda x,y:(int(image.width()*x),int(image.height()*y)))
        child_pixels=get_pixels(child_image,lambda x,y:(int(child_image.width()*x),int(child_image.height()*y)))
        desktop_pixels=get_pixels(desktop_image,lambda x,y:(
            host.mapToGlobal(QPoint(int(host.width()*x),int(host.height()*y))).x()-screen.geometry().x(),
            host.mapToGlobal(QPoint(int(host.width()*x),int(host.height()*y))).y()-screen.geometry().y()
        ))
        user32=ctypes.WinDLL("user32",use_last_error=True)
        user32.GetParent.argtypes=(ctypes.c_void_p,)
        user32.GetParent.restype=ctypes.c_void_p
        user32.IsWindowVisible.argtypes=(ctypes.c_void_p,)
        user32.IsWindowVisible.restype=ctypes.c_bool
        native_parent=user32.GetParent(ctypes.c_void_p(host._child_window))
        native_visible=user32.IsWindowVisible(ctypes.c_void_p(host._child_window))
        expected = [0xF2, 0x1A, 0x9A]
        visible = sum(max(abs(channel-target) for channel, target in zip(pixel,expected)) <= 30
                      for pixel in desktop_pixels)
        result.update({"embedded": True, "image_size": [image.width(), image.height()],
                       "host_samples": host_pixels, "child_samples": child_pixels,
                       "desktop_samples": desktop_pixels, "visible_marker_samples": visible,
                       "qt_host_visible": host.isVisible(),
                       "qt_container_visible": host._window_container.isVisible(),
                       "foreign_visible": host._foreign_window.isVisible(),
                       "native_child_visible": native_visible,
                       "native_parent": int(native_parent or 0),
                       "qt_container_hwnd": int(host._window_container.winId()),
                       "qt_container_size": [host._window_container.width(),host._window_container.height()],
                       "foreign_window_size": [host._foreign_window.width(),host._foreign_window.height()]})
        if int(native_parent or 0) != int(host._window_container.winId()):
            raise AssertionError("WebView2 is a desktop popup, not a native Qt child")
        if not native_visible:
            raise AssertionError("WebView2 is not natively visible inside its Qt parent")
        if visible < 3:
            raise AssertionError("The embedded WebView2 surface is not visibly painted on desktop")
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


def run_in_app(helper: Path) -> int:
    """Check real MainWindow > MediaPanel > QScrollArea video composition.

    The standalone parent check cannot expose scroll-area stacking failures.
    This uses the same offline WebView2 color marker without YouTube/network.
    """
    if sys.platform != "win32" or not helper.is_file():
        raise RuntimeError("In-app embed probe requires the built Windows TV helper")
    app=QApplication.instance() or QApplication([])
    result={"type":"visual_inapp_embed_probe","network":"none","marker":"f21a9a"}
    with tempfile.TemporaryDirectory(prefix="pulse-qt-embed-") as temporary:
        controller=Controller(Path(temporary),demo=True)
        window=None
        host=None
        process=None
        heartbeat=[]
        timer=None
        try:
            window=MainWindow(controller)
            window.resize(1440,940)
            window.show()
            window.vertical_split.setSizes([180,720])
            window.lower_split.setSizes([250,850,250])
            app.processEvents()
            television=window.media.tv
            television.display.hide()
            host=NativeTvHost(television)
            host.setMinimumHeight(230)
            television.layout_.insertWidget(3,host,1)
            host.show()
            window.media_scroll.ensureWidgetVisible(host,0,0)
            app.processEvents()
            qt_parent=int(host.winId())
            if not qt_parent:
                raise AssertionError("Real television tile did not expose a native Qt parent")
            events=[]
            process=QProcess(host)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
            process.readyReadStandardOutput.connect(lambda:host._consume(process))
            process.errorOccurred.connect(lambda error:host._failed(process,error))
            process.finished.connect(lambda code,state:host._finished(process,code))
            host.status_received.connect(events.append)
            host._process=process
            timer=QTimer(window)
            timer.setInterval(16)
            timer.timeout.connect(lambda:heartbeat.append(time.perf_counter()))
            timer.start()
            process.start(str(helper),["--probe-embed",str(qt_parent)])
            deadline=time.monotonic()+18
            while time.monotonic()<deadline:
                app.processEvents()
                if any(e.get("type")=="error" for e in events):
                    raise AssertionError("Real video tile attach error: "+repr(events))
                if any(e.get("type")=="embed_probe_ready" for e in events):
                    break
                if process.state()==QProcess.ProcessState.NotRunning:
                    raise RuntimeError("In-app child exited: "+repr(events))
                QTest.qWait(40)
            else:
                raise TimeoutError("In-app WebView2 did not become ready")

            def visible_marker(label):
                window.media_scroll.ensureWidgetVisible(host,0,0)
                host._window_container.show()
                QTest.qWait(350)
                app.processEvents()
                viewport=window.media_scroll.viewport()
                surface=QRect(host.mapToGlobal(QPoint(0,0)),host.size())
                clip=QRect(viewport.mapToGlobal(QPoint(0,0)),viewport.size())
                visible=surface.intersected(clip).intersected(
                    QRect(window.mapToGlobal(QPoint(0,0)),window.size()))
                if not host.isVisible() or visible.width()<80 or visible.height()<60:
                    raise AssertionError(f"{label}: video clipped out of real scroll viewport: {visible}")
                screen=host.screen()
                image=screen.grabWindow(0).toImage()
                if image.isNull():
                    raise RuntimeError("Windows desktop image unavailable")
                ratios=[(.2,.2),(.5,.2),(.5,.5),(.8,.5),(.8,.8)]
                pixels=[]
                matches=0
                for fx,fy in ratios:
                    x=int(visible.x()+visible.width()*fx-screen.geometry().x())
                    y=int(visible.y()+visible.height()*fy-screen.geometry().y())
                    if x<0 or y<0 or x>=image.width() or y>=image.height():
                        raise AssertionError(f"{label}: sampling coordinate outside desktop")
                    color=image.pixelColor(x,y)
                    rgb=[color.red(),color.green(),color.blue()]
                    pixels.append(rgb)
                    matches+=max(abs(v-w) for v,w in zip(rgb,(242,26,154)))<=30
                if matches<3:
                    raise AssertionError(f"{label}: blank/clipped in-app media surface: {pixels}")
                return {"case":label,"visible_rect":[visible.x(),visible.y(),visible.width(),visible.height()],
                        "samples":pixels,"matching_pixels":matches}

            result["cases"]=[visible_marker("initial_1440x940")]
            window.open_page(1)
            app.processEvents()
            if host.isVisible():
                raise AssertionError("Switching away left native video visible on another tab")
            window.open_page(0)
            result["cases"].append(visible_marker("returned_to_monitor"))
            window.resize(960,640)
            result["cases"].append(visible_marker("resized_960x640"))
            window.resize(1440,940)
            result["cases"].append(visible_marker("resized_1440x940"))
            user32=ctypes.WinDLL("user32",use_last_error=True)
            user32.GetParent.argtypes=(ctypes.c_void_p,)
            user32.GetParent.restype=ctypes.c_void_p
            actual=int(user32.GetParent(ctypes.c_void_p(host._child_window)) or 0)
            target=int(host._window_container.winId())
            if actual!=target:
                raise AssertionError("In-app WebView2 is not parented to exact Qt container")
            gaps=[b-a for a,b in zip(heartbeat,heartbeat[1:])]
            result.update({"qt_container_hwnd":target,"native_parent":actual,
                           "max_heartbeat_gap_ms":round(max(gaps,default=0)*1000,1),
                           "heartbeat_ticks":len(heartbeat),"passed":True})
            print(json.dumps(result,sort_keys=True))
            return 0
        finally:
            if not result.get("passed"):
                print(json.dumps(dict(result,passed=False),sort_keys=True))
            if timer is not None:timer.stop()
            if host is not None:host.stop()
            if process is not None and process.state()!=QProcess.ProcessState.NotRunning:
                if not process.waitForFinished(4000):
                    process.kill()
                    process.waitForFinished(1000)
            if window is not None:
                window.media.shutdown()
                window._force_close=True
                window.close()
                app.processEvents()
            controller.close()


if __name__ == "__main__":
    if len(sys.argv)==3 and sys.argv[1]=="--inapp":
        sys.exit(run_in_app(Path(sys.argv[2])))
    if len(sys.argv)!=2:
        sys.exit("usage: python -m scripts.issue82_native_embed_probe [--inapp] <GlobalPulse.TV.exe>")
    sys.exit(run(Path(sys.argv[1])))
