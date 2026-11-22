"""Retired video payloads must not survive a repeated or stale Windows build.

Only inert temporary files are used. Notification and Qt receiver dependencies
remain required; removing the YouTube helper must not loosen their gates.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import package_manifest as manifest


@pytest.mark.parametrize("relative", [
    "tv/GlobalPulse.TV.exe",
    "tv/coreclr.dll",
    "TV/old-helper.dll",
    "tv/licenses/Old/NOTICE.txt",
    "_internal/GlobalPulse.TV.exe",
    "_internal/GlobalPulse.TV.deps.json",
    "_internal/Microsoft.Web.WebView2.Core.dll",
    "notifications/Microsoft.Web.WebView2.WinForms.dll",
    "_internal/runtimes/win-x64/native/WebView2Loader.dll",
    "_internal/global_pulse/native_tv.py",
    "_internal/global_pulse/native_tv.pyc",
    "_internal/global_pulse/resources/tv_playback_verified.json",
])
def test_stale_retired_video_payload_is_rejected_in_every_package_lane(tmp_path, relative):
    file = tmp_path / relative
    file.parent.mkdir(parents=True)
    file.write_bytes(b"inert stale video fixture")
    with pytest.raises(ValueError, match="retired YouTube playback payload is forbidden"):
        manifest.scan(tmp_path, require_complete=False)


def test_native_notifications_and_qt_receiver_files_remain_admitted(tmp_path):
    files = [
        "notifications/GlobalPulse.Notifications.exe",
        "notifications/coreclr.dll",
        "_internal/PySide6/QtWebEngineWidgets.pyd",
        "_internal/PySide6/Qt6WebEngineCore.dll",
        "_internal/PySide6/QtWebEngineProcess.exe",
    ]
    for relative in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"inert retained dependency")
    result = manifest.scan(tmp_path, require_complete=False)
    assert result["status"] == "PASS"
    assert result["files"] == len(files)


def test_complete_package_still_requires_notification_identity_and_x64_runtime(tmp_path):
    with pytest.raises(ValueError) as missing:
        manifest.scan(tmp_path, require_complete=True)
    message = str(missing.value)
    for required in (
        "notifications/GlobalPulse.Notifications.exe",
        "notifications/GlobalPulse.Notifications.deps.json",
        "notifications/GlobalPulse.Notifications.runtimeconfig.json",
        "notifications/coreclr.dll",
        "_internal/python312.dll",
    ):
        assert required in message
    assert "tv/" not in message
    assert "camera/GlobalPulse.Camera.exe" in message
    assert "camera/WebView2Loader.dll" in message
    assert "tv" not in manifest.TOP_DIRECTORIES
    assert {"qt6webenginecore.dll", "qtwebengineprocess.exe"} <= manifest.QT_REQUIRED_RUNTIME_BASENAMES


def test_native_notification_packages_are_still_recorded_in_sbom(tmp_path):
    folder = tmp_path / "notifications"
    folder.mkdir()
    (folder / "GlobalPulse.Notifications.deps.json").write_text(json.dumps({
        "libraries": {
            "Microsoft.WindowsAppSDK.Foundation/2.6.5": {"type": "package"},
            "System.Runtime/10.0.14": {"type": "package"},
            "GlobalPulse.Notifications/1.0.0": {"type": "project"},
        }
    }), encoding="utf-8")
    manifest.sbom(tmp_path)
    data = json.loads((tmp_path / "SBOM.cdx.json").read_text(encoding="utf-8"))
    refs = {entry["bom-ref"] for entry in data["components"]}
    assert "pkg:nuget/Microsoft.WindowsAppSDK.Foundation@2.6.5" in refs
    assert "pkg:nuget/System.Runtime@10.0.14" in refs
    assert "pkg:nuget/GlobalPulse.Notifications@1.0.0" not in refs
    assert not any("WebView2" in item or "GlobalPulse.TV" in item for item in refs)


def test_nonallowlisted_payload_and_debug_symbols_remain_forbidden(tmp_path):
    folder = tmp_path / "arbitrary"
    folder.mkdir()
    (folder / "helper.dll").write_bytes(b"inert unreviewed fixture")
    with pytest.raises(ValueError, match="root directory is not allowlisted"):
        manifest.scan(tmp_path, require_complete=False)
    (folder / "debug.pdb").write_bytes(b"inert debug symbols")
    with pytest.raises(ValueError, match="forbidden runtime file type"):
        manifest.scan(tmp_path, require_complete=False)
