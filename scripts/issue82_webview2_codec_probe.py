"""Offline Windows WebView2 backend and HTML5 video codec probe.

Research-only: no network URL is opened; no Pulse source or settings are touched.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


def inspect_native_plugin() -> dict[str, object]:
    """Check Qt's installed plugin metadata without starting the video engine."""
    from PySide6.QtCore import QLibraryInfo, QPluginLoader

    plugin_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "webview"
    candidates = sorted(plugin_dir.glob("*.dll")) if plugin_dir.is_dir() else []
    found = []
    inspected = []
    for plugin_file in candidates:
        metadata = QPluginLoader(str(plugin_file)).metaData()
        keys = (metadata.get("MetaData") or {}).get("Keys") or []
        inspected.append({"file": plugin_file.name, "keys": keys})
        if "webview2" in keys:
            found.append(plugin_file.name)
    return {
        "probe": "issue82-qt-native-webview2-codecs",
        "network": "none; local HTML document only",
        "platform": sys.platform,
        "plugin_dir": str(plugin_dir),
        "native_plugin_files": found,
        "inspected_plugins": inspected,
        "plugin_present": bool(found),
        "qt_webview_module_present": importlib.util.find_spec("PySide6.QtWebView") is not None,
    }


def probe_codec_capabilities(report: dict[str, object]) -> dict[str, object]:
    if sys.platform != "win32":
        report["result"] = "unsupported_non_windows"
        return report
    if not report["plugin_present"] or not report["qt_webview_module_present"]:
        report["result"] = "native_webview2_plugin_missing"
        return report

    # Set the backend before QtWebView.initialize(), which must run before QApplication.
    os.environ["QT_WEBVIEW_PLUGIN"] = "webview2"
    from PySide6.QtWebView import QWebView, QtWebView
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

    QtWebView.initialize()
    app = QApplication.instance() or QApplication(["GlobalPulseOfflineCodecProbe"])
    host = QWidget()
    layout = QVBoxLayout(host)
    webview = QWebView()
    layout.addWidget(QWidget.createWindowContainer(webview, host))
    host.resize(400, 240)

    finished = {"value": False}

    def finish(result: str, payload: object = None) -> None:
        if finished["value"]:
            return
        finished["value"] = True
        report["result"] = result
        report["callback_type"] = type(payload).__name__
        report["callback_sample"] = repr(payload)[:500]
        for _ in range(2):
            if not isinstance(payload, str):
                break
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                break
        if isinstance(payload, dict):
            report["video_can_play_type"] = payload
            report["result"] = "codec_capability_reported"
        webview.stop()
        host.close()
        app.quit()

    javascript = """
    (() => {
      const video = document.createElement('video');
      return JSON.stringify({
        h264_aac: video.canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"'),
        vp9_opus: video.canPlayType('video/webm; codecs="vp9, opus"'),
        av1_opus: video.canPlayType('video/webm; codecs="av01.0.08M.08, opus"'),
        media_source: typeof MediaSource !== 'undefined',
        location: String(location.href)
      });
    })()
    """

    def evaluate() -> None:
        try:
            webview.runJavaScript(
                javascript,
                lambda value: finish(
                    "javascript_callback_received" if value is not None else "empty_codec_reply",
                    value,
                ),
            )
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            finish("javascript_exception")

    QTimer.singleShot(3000, evaluate)
    QTimer.singleShot(18000, lambda: finish("native_webview2_timeout"))
    host.show()
    # Offline and deliberately not a YouTube page; this only tests decoder advertising.
    webview.loadHtml("<!doctype html><html><head><title>Offline codec probe</title></head><body>Codec probe</body></html>")
    app.exec()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args(argv)
    report: dict[str, object] = {"probe": "issue82-qt-native-webview2-codecs", "network": "none"}
    try:
        report = inspect_native_plugin()
        if args.inspect_only:
            report["result"] = "inventory_only"
        else:
            report = probe_codec_capabilities(report)
    except Exception as exc:
        report["result"] = "probe_exception"
        report["error"] = f"{type(exc).__name__}: {exc}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    # Experimental information-only probe: a missing backend is not a product test failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
