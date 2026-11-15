"""Source-level safety contracts for opt-in Windows WebView2 TV helper.

CI's native --probe checks the real codec in the packaged .NET process.
Neither test proves a real YouTube frame, which still needs owner acceptance.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from global_pulse.media_widget import youtube_player_navigation
from global_pulse.native_tv import NativeTvHost
from global_pulse.single_media import Television


def test_video_id_navigation_cannot_change_selection():
    video = "YE7VzlLtp-4"
    assert youtube_player_navigation(
        "https://www.youtube.com/embed/YE7VzlLtp-4?autoplay=0",video
    )
    for url in (
        "https://www.youtube.com/watch?v=b0ZhJhN_Sn8",
        "https://accounts.google.com/",
        "https://www.youtube.com/embed/b0ZhJhN_Sn8",
        "http://www.youtube.com/embed/YE7VzlLtp-4",
        "https://youtube.com.evil.example/embed/YE7VzlLtp-4",
    ):
        assert not youtube_player_navigation(url,video,full_watch=True)


def test_native_windows_process_only_launches_after_existing_consent_gate():
    watch = inspect.getsource(Television.watch)
    full = inspect.getsource(Television.watch_full_page)
    for body in (watch,full):
        assert "QMessageBox.question" in body
        assert body.index("QMessageBox.question") < body.index("_begin_native_player")
    assert "return False" in inspect.getsource(NativeTvHost.play)
    assert ".waitForFinished(" not in inspect.getsource(NativeTvHost.stop)
    assert "watchdog=QTimer(process)" in inspect.getsource(NativeTvHost.stop)


def test_foreign_video_window_uses_qt_scrolling_container_with_pid_validation():
    source = inspect.getsource(NativeTvHost._attach_window)
    assert "GetWindowThreadProcessId" in source
    assert "owner_pid.value != int(process.processId())" in source
    assert "QWindow.fromWinId(hwnd)" in source
    assert "QWidget.createWindowContainer(foreign, self)" in source
    assert "ctypes.windll.user32.MoveWindow(" not in source
    assert "self._release_window()" in inspect.getsource(NativeTvHost.stop)


def test_webview2_source_installs_resource_and_permission_guards_before_navigate():
    source = (Path(__file__).resolve().parents[1] /
              "packaging" / "tv" / "NativeTvProgram.cs").read_text(encoding="utf-8")
    checks = (
        "AddWebResourceRequestedFilter", "WebResourceRequested +=",
        "NavigationStarting +=", "FrameNavigationStarting +=",
        "NewWindowRequested +=", "DownloadStarting +=",
        "PermissionRequested +=", "ServerCertificateErrorDetected +=",
        "IsInPrivateModeEnabled = true", "IsWebMessageEnabled = false",
        "AreHostObjectsAllowed = false",
    )
    for check in checks:
        assert check in source
    assert source.index("WebResourceRequested +=") < source.index("NavigateWithWebResourceRequest")
    assert source.index("NavigationStarting +=") < source.index("NavigateWithWebResourceRequest")
    assert source.index("DownloadStarting +=") < source.index("NavigateWithWebResourceRequest")
    assert 'if (offlineProbe)' in source
    assert 'network = "none"' in source
    assert 'web.IsMuted = desiredMuted;' in source
    assert source.index('web.IsMuted = desiredMuted;') < source.index('NavigateWithWebResourceRequest(request)')
    assert 'SetAudio(muted, null)' in source
    assert 'SetAudio(null, volume)' in source
    assert 'private int desiredVolume = 60;' in source
    assert 'v.volume=' in source and 'v.muted=' in source
    assert 'FrameAllowed(e.Uri,videoId,fullWatch)' in source
    assert 'PolicySelfTest()' in source
    assert 'CleanupPrivateProfileAfterExit()' in source
    assert 'RejectWebView2Overrides();' in source
    assert 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS' in source
    assert 'WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER' in source
    assert 'Registry.LocalMachine, Registry.CurrentUser' in source
    assert 'environment.UserDataFolder' in source
    assert source.index('RejectWebView2Overrides();') < source.index('CoreWebView2Environment.CreateAsync(')
    assert 'ExclusiveUserDataFolderAccess = true' in source
    assert 'SetHighDpiMode(HighDpiMode.PerMonitorV2)' in source
    assert 'GetParent(Handle) != parentHwnd' in source
    assert '"--probe-embed"' in source
    assert '"embed_probe_ready"' in source


def test_native_host_quick_stop_restarts_leave_no_stale_watchdog(monkeypatch):
    # The helper is represented by the local interpreter with impossible CLI
    # arguments, so it exits promptly. No network, video or native TV backend.
    # This exercises QProcess ownership and watchdog callbacks on real Qt.
    qt_app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(NativeTvHost, "executable", staticmethod(lambda: Path(sys.executable)))
    host=NativeTvHost()
    host.resize(320, 180)
    host.show()
    for _ in range(12):
        assert host.play("YE7VzlLtp-4")
        host.stop()
        qt_app.processEvents()
    QTest.qWait(3100)
    qt_app.processEvents()
    assert host._process is None
    host.close()
