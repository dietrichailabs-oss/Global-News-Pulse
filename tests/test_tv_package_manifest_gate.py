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


def test_tv_subtree_forbids_unexpected_nested_payload_and_executable(tmp_path: Path):
    native = tmp_path / "tv"
    (native / "unexpected").mkdir(parents=True)
    (native / "unexpected" / "loader.dll").write_bytes(b"not a declared runtime subtree")
    with pytest.raises(ValueError, match="outside reviewed native TV subtree"):
        manifest.scan(tmp_path, require_complete=False)
    (native / "unexpected" / "loader.dll").unlink()
    (native / "unexpected").rmdir()
    (native / "evil.exe").write_bytes(b"unexpected process")
    with pytest.raises(ValueError, match="unreviewed native TV root file"):
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


def _tv_reference_notice_fixture(tmp_path: Path):
    native = tmp_path / "tv"
    ledger = native / "licenses"
    ledger.mkdir(parents=True)
    (native / "GlobalPulse.TV.deps.json").write_text(json.dumps({
        "libraries": {
            "Microsoft.Web.WebView2.Core/1.0.4314.35": {"type": "reference"},
            "Microsoft.Web.WebView2.WinForms/1.0.4314.35": {"type": "reference"},
            "Microsoft.Web.WebView2.Wpf/1.0.4314.35": {"type": "reference"},
            "GlobalPulse.TV/1.0.0": {"type": "project"},
        }
    }), encoding="utf-8")
    records = []
    notice_paths = []
    for name in ("Microsoft.Web.WebView2.Core", "Microsoft.Web.WebView2.WinForms",
                 "Microsoft.Web.WebView2.Wpf"):
        folder = ledger / (name + "-1.0.4314.35")
        folder.mkdir()
        notice = folder / "LICENSE.txt"
        notice.write_text("reviewed fixture for " + name, encoding="utf-8")
        notice_paths.append(notice)
        records.append({
            "package": name,
            "version": "1.0.4314.35",
            "type": "reference",
            "notice_source_package": manifest.TV_PARENT,
            "notice_source_lock_sha512": manifest.TV_NUGET_CONTENT_SHA512,
            "notice_source_archive_sha512": manifest.TV_ARCHIVE_SHA512,
            "notice_files": [{
                "packaged_relative": "licenses/" + folder.name + "/LICENSE.txt",
                "bytes": notice.stat().st_size,
                "sha256": manifest.digest(notice),
            }],
        })
    receipt = {"packages": records}
    ledger_file = ledger / "NATIVE_PACKAGE_NOTICES.json"
    ledger_file.write_text(json.dumps(receipt), encoding="utf-8")
    return ledger_file, receipt, notice_paths


def test_ref_only_tv_dependency_and_all_three_dual_pinned_notices_are_accepted(tmp_path: Path):
    ledger, receipt, paths = _tv_reference_notice_fixture(tmp_path)
    # The rest of the whole-program fixture is intentionally missing; the
    # exact native TV reference/notice identities themselves must not fail.
    with pytest.raises(ValueError) as incomplete:
        manifest.scan(tmp_path, require_complete=True)
    assert "Native television lacks exact reviewed WebView2 assembly identities" not in str(incomplete.value)
    assert "Native television lacks dual-pinned WebView2 SDK notice proof" not in str(incomplete.value)
    assert "exact native TV notice bytes differ" not in str(incomplete.value)
    assert "not recorded by exact native TV notice ledger" not in str(incomplete.value)
    manifest.sbom(tmp_path)
    sbom = json.loads((tmp_path / "SBOM.cdx.json").read_text(encoding="utf-8"))
    sdk = [item for item in sbom["components"]
           if item.get("bom-ref") == "pkg:nuget/Microsoft.Web.WebView2@1.0.4314.35"]
    assert len(sdk) == 1
    assert not any(item.get("bom-ref") == "pkg:nuget/Microsoft.Web.WebView2.Core@1.0.4314.35"
                   for item in sbom["components"])


@pytest.mark.parametrize("violation,expected", [
    ("missing_wpf_alias", "Native television lacks dual-pinned WebView2 SDK notice proof"),
    ("tampered_archive_pin", "Native television lacks dual-pinned WebView2 SDK notice proof"),
    ("tampered_notice_copy", "exact native TV notice bytes differ"),
    ("missing_notice_copy", "exact native TV notice bytes differ"),
    ("notice_path_traversal", "Native television has unsafe notice path"),
    ("unlisted_notice", "not recorded by exact native TV notice ledger"),
])
def test_tv_notice_ledger_rejects_incomplete_or_tampered_copy(tmp_path: Path, violation, expected):
    ledger, receipt, notices = _tv_reference_notice_fixture(tmp_path)
    if violation == "missing_wpf_alias":
        receipt["packages"].pop()
    elif violation == "tampered_archive_pin":
        receipt["packages"][0]["notice_source_archive_sha512"] = "TAMPERED"
    elif violation == "tampered_notice_copy":
        notices[0].write_text("tampered contents", encoding="utf-8")
    elif violation == "missing_notice_copy":
        notices[0].unlink()
    elif violation == "notice_path_traversal":
        receipt["packages"][0]["notice_files"][0]["packaged_relative"] = "licenses/../outside.txt"
    elif violation == "unlisted_notice":
        (ledger.parent / "extra" / "UNLISTED.txt").parent.mkdir()
        (ledger.parent / "extra" / "UNLISTED.txt").write_text("not in receipt")
    ledger.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        manifest.scan(tmp_path, require_complete=True)


@pytest.mark.parametrize("name", ["evil.exe", "payload.dll"])
def test_tv_license_subtree_rejects_executable_payloads(tmp_path: Path, name):
    folder = tmp_path / "tv" / "licenses" / "Unexpected-1.0"
    folder.mkdir(parents=True)
    (folder / name).write_bytes(b"never ship an executable inside notices")
    with pytest.raises(ValueError, match="unreviewed native TV license payload"):
        manifest.scan(tmp_path, require_complete=False)


def test_tv_dependency_is_recorded_once_in_cyclonedx_sbom(tmp_path: Path):
    for directory in ("tv", "notifications"):
        folder = tmp_path / directory
        folder.mkdir()
        (folder / "helper.deps.json").write_text(
            json.dumps({
                "libraries": {
                    "Microsoft.Web.WebView2/1.0.4314.35": {"type": "package"},
                    "System.Runtime/10.0.14": {"type": "package"},
                    "Microsoft.Web.WebView2.Core/1.0.4314.35": {"type": "reference"},
                    "GlobalPulse.TV/1.0.0": {"type": "project"},
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

    assert not any(
        item.get("bom-ref") in {
            "pkg:nuget/Microsoft.Web.WebView2.Core@1.0.4314.35",
            "pkg:nuget/GlobalPulse.TV@1.0.0",
        }
        for item in sbom["components"]
    ), "Reference aliases and the local project are not independent NuGet packages"
