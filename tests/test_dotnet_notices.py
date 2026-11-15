import importlib.util
import base64
import hashlib
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "gp_collect_dotnet_notices",
    Path(__file__).parents[1] / "scripts" / "collect_dotnet_notices.py",
)
notices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notices)


def _deps(path, libraries):
    target = {}
    inventory = {}
    for identity, kind, runtime, native in libraries:
        target[identity] = {"runtime": {name: {} for name in runtime}, "native": {name: {} for name in native}}
        inventory[identity] = {"type": kind}
    path.write_text(json.dumps({
        "targets": {".NETCoreApp,Version=v10.0/win-x64": target},
        "libraries": inventory,
    }))


def _package(root, name, version, notice=True):
    folder = root / name.lower() / version.lower()
    folder.mkdir(parents=True)
    if notice:
        (folder / "LICENSE.txt").write_text(f"license for {name} {version}")
    return folder


def test_collects_notices_for_exact_shipped_package(tmp_path):
    nuget = tmp_path / "packages"
    _package(nuget, "Example.Runtime", "1.2.3")
    deps = tmp_path / "app.deps.json"
    _deps(deps, [("Example.Runtime/1.2.3", "package", ["Example.dll"], [])])
    result = notices.collect(deps, nuget, tmp_path / "out" / "licenses")
    assert [item["package"] for item in result["packages"]] == ["Example.Runtime"]
    copied = result["packages"][0]["notice_files"]
    assert len(copied) == 1
    assert (tmp_path / "out" / copied[0]["packaged_relative"]).is_file()


def test_runtimepack_identity_maps_to_nuget_package_directory(tmp_path):
    nuget = tmp_path / "packages"
    _package(nuget, "Microsoft.NETCore.App.Runtime.win-x64", "10.0.14")
    deps = tmp_path / "app.deps.json"
    _deps(deps, [(
        "runtimepack.Microsoft.NETCore.App.Runtime.win-x64/10.0.14",
        "runtimepack",
        ["System.Private.CoreLib.dll"],
        ["coreclr.dll"],
    )])
    result = notices.collect(deps, nuget, tmp_path / "out" / "licenses")
    assert result["packages"][0]["package"].startswith("runtimepack.")
    assert result["packages"][0]["notice_files"]


def test_fails_closed_when_shipped_package_has_no_notice_text(tmp_path):
    nuget = tmp_path / "packages"
    _package(nuget, "Missing.Notice", "2.0", notice=False)
    deps = tmp_path / "app.deps.json"
    _deps(deps, [("Missing.Notice/2.0", "package", ["Missing.dll"], [])])
    with pytest.raises(ValueError, match="Runtime package notice text missing"):
        notices.collect(deps, nuget, tmp_path / "out" / "licenses")


def test_ignores_build_only_library_without_runtime_or_native_assets(tmp_path):
    nuget = tmp_path / "packages"
    _package(nuget, "Runtime.Package", "1.0")
    deps = tmp_path / "app.deps.json"
    _deps(deps, [
        ("Runtime.Package/1.0", "package", ["Runtime.dll"], []),
        ("Build.Only/9.9", "package", [], []),
    ])
    result = notices.collect(deps, nuget, tmp_path / "out" / "licenses")
    assert [item["package"] for item in result["packages"]] == ["Runtime.Package"]


def test_rejects_reference_or_unknown_shipped_dependency_without_package_provenance(tmp_path):
    deps = tmp_path / "app.deps.json"
    _deps(deps, [("Projection/1.0", "reference", ["Projection.dll"], [])])
    (tmp_path / "packages").mkdir()
    with pytest.raises(ValueError, match="unsupported notice source"):
        notices.collect(deps, tmp_path / "packages", tmp_path / "out" / "licenses")


def test_exact_reviewed_external_license_reference_is_preserved_but_marked_hold(tmp_path, monkeypatch):
    nuget = tmp_path / "packages"
    _package(nuget, "Microsoft.Windows.SDK.NET.Ref", "10.0.19041.57", notice=False)
    deps = tmp_path / "app.deps.json"
    _deps(deps, [(
        "runtimepack.Microsoft.Windows.SDK.NET.Ref/10.0.19041.57",
        "runtimepack",
        ["Microsoft.Windows.SDK.NET.dll"],
        [],
    )])
    reviewed = tmp_path / "reviewed"
    reviewed.mkdir()
    reference = reviewed / "Microsoft.Windows.SDK.NET.Ref-10.0.19041.57-LICENSE-REFERENCE.txt"
    reference.write_text("OFFICIAL LICENSE REFERENCE TEST FIXTURE")
    monkeypatch.setattr(notices, "REVIEWED_REFERENCE_ROOT", reviewed)
    result = notices.collect(deps, nuget, tmp_path / "out" / "licenses")
    record = result["packages"][0]
    assert record["evidence_kind"] == "external_license_reference_only"
    assert result["external_license_reference_only"] == [{
        "package": "runtimepack.Microsoft.Windows.SDK.NET.Ref",
        "version": "10.0.19041.57",
    }]
    assert "HOLD" in result["release_rights_status"]


def test_unreviewed_windows_sdk_reference_version_still_fails_closed(tmp_path, monkeypatch):
    nuget = tmp_path / "packages"
    _package(nuget, "Microsoft.Windows.SDK.NET.Ref", "10.0.19041.58", notice=False)
    deps = tmp_path / "app.deps.json"
    _deps(deps, [(
        "runtimepack.Microsoft.Windows.SDK.NET.Ref/10.0.19041.58",
        "runtimepack",
        ["Microsoft.Windows.SDK.NET.dll"],
        [],
    )])
    monkeypatch.setattr(notices, "REVIEWED_REFERENCE_ROOT", tmp_path / "reviewed-empty")
    with pytest.raises(ValueError, match="Runtime package notice text missing"):
        notices.collect(deps, nuget, tmp_path / "out" / "licenses")


def _webview2_lock(tmp_path, monkeypatch, version="1.0.4314.35", package_hash=None):
    # The package-content SHA512 and signed-archive SHA512 legitimately differ.
    package_hash = package_hash or base64.b64encode(
        hashlib.sha512(b"synthetic NuGet CONTENT excluding signature").digest()
    ).decode("ascii")
    monkeypatch.setattr(notices, "REVIEWED_WEBVIEW2_NUGET_CONTENT_SHA512", package_hash)
    monkeypatch.setattr(
        notices, "REVIEWED_WEBVIEW2_ARCHIVE_SHA512",
        base64.b64encode(hashlib.sha512(b"synthetic WebView2 SDK locked archive").digest()).decode("ascii"),
    )
    lock_path = tmp_path / "webview2" / "packages.lock.json"
    lock_path.parent.mkdir()
    lock_path.write_text(json.dumps({
        "version": 1,
        "dependencies": {
            "net10.0-windows10.0.19041/win-x64": {
                "Microsoft.Web.WebView2": {
                    "type": "Direct",
                    "requested": f"[{version}, )",
                    "resolved": version,
                    "contentHash": package_hash,
                }
            }
        }
    }))
    monkeypatch.setattr(notices, "REVIEWED_PACKAGE_LOCK_PATH", lock_path)
    return package_hash


@pytest.mark.parametrize("assembly", [
    "Microsoft.Web.WebView2.Core",
    "Microsoft.Web.WebView2.WinForms",
    "Microsoft.Web.WebView2.Wpf",
])
def test_exact_locked_webview2_reference_copies_parent_sdk_notice(tmp_path, monkeypatch, assembly):
    nuget = tmp_path / "packages"
    parent = _package(nuget, "Microsoft.Web.WebView2", "1.0.4314.35")
    lock_hash = _webview2_lock(tmp_path, monkeypatch)
    (parent / "microsoft.web.webview2.1.0.4314.35.nupkg").write_bytes(
        b"synthetic WebView2 SDK locked archive"
    )
    (parent / "microsoft.web.webview2.1.0.4314.35.nupkg.sha512").write_text(
        notices.REVIEWED_WEBVIEW2_ARCHIVE_SHA512
    )
    (parent / ".nupkg.metadata").write_text(json.dumps({
        "version": 2,
        "contentHash": lock_hash,
        "source": "https://api.nuget.org/v3/index.json",
    }))
    deps = tmp_path / "app.deps.json"
    _deps(deps, [
        ("Microsoft.Web.WebView2/1.0.4314.35", "package", [], []),
        (f"{assembly}/1.0.4314.35", "reference", [assembly + ".dll"], []),
    ])
    result = notices.collect(deps, nuget, tmp_path / "out" / "licenses")
    assert len(result["packages"]) == 1
    record = result["packages"][0]
    assert record["type"] == "reference"
    assert record["notice_source_package"] == "Microsoft.Web.WebView2/1.0.4314.35"
    assert record["notice_source_lock_sha512"] == lock_hash
    assert record["notice_source_archive_sha512"] == notices.REVIEWED_WEBVIEW2_ARCHIVE_SHA512
    assert record["notice_source_archive_sha512"] != record["notice_source_lock_sha512"]
    assert record["evidence_kind"] == "package_notice_text"
    assert len(record["notice_files"]) == 1
    copied = record["notice_files"][0]
    assert copied["sha256"] == notices.digest(parent / "LICENSE.txt")
    assert (tmp_path / "out" / copied["packaged_relative"]).read_bytes() == (parent / "LICENSE.txt").read_bytes()


@pytest.mark.parametrize("violation", [
    "missing_lock",
    "wrong_locked_version",
    "restored_hash_mismatch",
    "missing_restored_hash",
    "missing_notice",
    "unreviewed_reference_version",
    "unreviewed_reference_name",
    "wrong_parent_deps_kind",
    "tampered_archive",
    "metadata_lock_mismatch",
    "metadata_source_invalid",
    "missing_metadata",
    "missing_archive",
    "reviewed_content_pin_mismatch",
    "reviewed_archive_pin_mismatch",
])
def test_webview2_reference_provenance_fail_closed(tmp_path, monkeypatch, violation):
    nuget = tmp_path / "packages"
    parent = _package(
        nuget, "Microsoft.Web.WebView2", "1.0.4314.35",
        notice=(violation != "missing_notice"),
    )
    lock_hash = _webview2_lock(
        tmp_path, monkeypatch,
        version="1.0.4314.36" if violation == "wrong_locked_version" else "1.0.4314.35",
    )
    archive = parent / "microsoft.web.webview2.1.0.4314.35.nupkg"
    if violation != "missing_archive":
        archive.write_bytes(
            b"modified content" if violation == "tampered_archive"
            else b"synthetic WebView2 SDK locked archive"
        )
    hash_file = parent / "microsoft.web.webview2.1.0.4314.35.nupkg.sha512"
    if violation != "missing_restored_hash":
        hash_file.write_text(
            "BAD_HASH" if violation == "restored_hash_mismatch"
            else notices.REVIEWED_WEBVIEW2_ARCHIVE_SHA512
        )
    if violation != "missing_metadata":
        (parent / ".nupkg.metadata").write_text(json.dumps({
            "version": 2,
            "contentHash": "BAD_HASH" if violation == "metadata_lock_mismatch" else lock_hash,
            "source": "https://nuget.example.com/v3/index.json"
            if violation == "metadata_source_invalid" else "https://api.nuget.org/v3/index.json",
        }))
    if violation == "reviewed_content_pin_mismatch":
        monkeypatch.setattr(notices, "REVIEWED_WEBVIEW2_NUGET_CONTENT_SHA512", "BAD_PIN")
    if violation == "reviewed_archive_pin_mismatch":
        monkeypatch.setattr(notices, "REVIEWED_WEBVIEW2_ARCHIVE_SHA512", "BAD_PIN")
    if violation == "missing_lock":
        notices.REVIEWED_PACKAGE_LOCK_PATH.unlink()
    name = "Microsoft.Web.WebView2.Core"
    version = "1.0.4314.35"
    if violation == "unreviewed_reference_name":
        name = "Microsoft.Web.WebView2.Obscure"
    elif violation == "unreviewed_reference_version":
        version = "1.0.4314.36"
    kind = "project" if violation == "wrong_parent_deps_kind" else "package"
    deps = tmp_path / "app.deps.json"
    _deps(deps, [
        ("Microsoft.Web.WebView2/1.0.4314.35", kind, [], []),
        (f"{name}/{version}", "reference", [name + ".dll"], []),
    ])
    with pytest.raises((ValueError, FileNotFoundError)):
        notices.collect(deps, nuget, tmp_path / "out" / "licenses")
