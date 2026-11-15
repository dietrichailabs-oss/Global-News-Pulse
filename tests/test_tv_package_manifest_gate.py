"""Regression contracts for the packaged isolated native WebView2 TV helper.

These tests use only a temporary, synthetic runtime tree: no network, NuGet,
WebView2 startup, player playback or developer workstation mutations.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import package_manifest as manifest


def test_reviewed_tv_subtree_is_admitted_without_generic_directory_escape(tmp_path: Path):
    native = tmp_path / "tv"
    (native / "licenses").mkdir(parents=True)
    (native / "GlobalPulse.TV.exe").write_bytes(b"synthetic TV fixture")
    (native / "licenses" / "NOTICE.txt").write_text("synthetic notice", encoding="utf-8")
    result = manifest.scan(tmp_path, require_complete=False)
    assert result["status"] == "PASS"
    assert result["files"] == 2

    (tmp_path / "arbitrary").mkdir()
    (tmp_path / "arbitrary" / "helper.dll").write_bytes(b"unauthorized")
    with pytest.raises(ValueError, match="root directory is not allowlisted"):
        manifest.scan(tmp_path, require_complete=False)


def test_tv_pdb_stays_forbidden_even_when_tv_subtree_is_admitted(tmp_path: Path):
    native = tmp_path / "tv"
    native.mkdir()
    (native / "GlobalPulse.TV.exe").write_bytes(b"synthetic TV fixture")
    (native / "GlobalPulse.TV.pdb").write_bytes(b"never ship debug symbols")
    with pytest.raises(ValueError, match="tv/GlobalPulse.TV.pdb: forbidden runtime file type"):
        manifest.scan(tmp_path, require_complete=False)


def test_complete_runtime_requires_tv_exe_loader_notices_and_self_contained_coreclr(tmp_path: Path):
    # Other required app files are intentionally absent too. Each TV-specific
    # required identity must independently be present in the refusal.
    with pytest.raises(ValueError) as error:
        manifest.scan(tmp_path, require_complete=True)
    message = str(error.value)
    for path in (
        "tv/GlobalPulse.TV.exe",
        "tv/GlobalPulse.TV.deps.json",
        "tv/GlobalPulse.TV.runtimeconfig.json",
        "tv/coreclr.dll",
        "tv/Microsoft.Web.WebView2.Core.dll",
        "tv/Microsoft.Web.WebView2.WinForms.dll",
        "tv/runtimes/win-x64/native/WebView2Loader.dll",
        "tv/licenses/NATIVE_PACKAGE_NOTICES.json",
    ):
        assert path in message


def test_tv_dependency_is_recorded_once_in_cyclonedx_sbom(tmp_path: Path):
    for directory in ("tv", "notifications"):
        folder = tmp_path / directory
        folder.mkdir()
        (folder / "helper.deps.json").write_text(
            json.dumps({
                "libraries": {
                    "Microsoft.Web.WebView2/1.0.4314.35": {"type": "package"},
                    "System.Runtime/10.0.14": {"type": "package"},
                }
            }),
            encoding="utf-8",
        )
    result = manifest.sbom(tmp_path)
    assert result["components"] > 2
    sbom = json.loads((tmp_path / "SBOM.cdx.json").read_text(encoding="utf-8"))
    webview_refs = [
        item for item in sbom["components"]
        if item["bom-ref"] == "pkg:nuget/Microsoft.Web.WebView2@1.0.4314.35"
    ]
    assert len(webview_refs) == 1
    assert webview_refs[0]["name"] == "Microsoft.Web.WebView2"
    assert any(
        item["type"] == "file" and item["name"] == "tv/helper.deps.json"
        for item in sbom["components"]
    )
