import importlib.util
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
