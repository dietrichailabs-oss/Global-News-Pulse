"""Source-level safety contracts for opt-in Windows WebView2 TV helper.

CI's native --probe checks the real codec in the packaged .NET process.
Neither test proves a real YouTube frame, which still needs owner acceptance.
"""
from __future__ import annotations

import inspect
from pathlib import Path

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
    assert "waitForFinished" not in inspect.getsource(NativeTvHost.stop)


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
