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


@pytest.mark.parametrize("assembly", [
    "Microsoft.Web.WebView2.Core",
    "Microsoft.Web.WebView2.WinForms",
    "Microsoft.Web.WebView2.Wpf",
])
def test_retired_video_reference_cannot_use_removed_notice_exception(tmp_path, assembly):
    deps = tmp_path / "app.deps.json"
    _deps(deps, [(assembly + "/1.0.4314.35", "reference", [assembly + ".dll"], [])])
    nuget = tmp_path / "packages"
    _package(nuget, "Microsoft.Web.WebView2", "1.0.4314.35")
    with pytest.raises(ValueError, match="unsupported notice source"):
        notices.collect(deps, nuget, tmp_path / "out" / "licenses")


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


def _camera_source(tmp_path, monkeypatch):
    """Exact synthetic SDK archive proves aliases resolve to one parent source."""
    import base64
    import hashlib
    import zipfile

    nuget = tmp_path / "packages"
    restored = _package(nuget, "Microsoft.Web.WebView2", notices.CAMERA_WEBVIEW2_VERSION, notice=False)
    texts = {"LICENSE.txt": b"INERT SDK LICENSE", "NOTICE.txt": b"INERT SDK NOTICE"}
    archive = restored / ("microsoft.web.webview2." + notices.CAMERA_WEBVIEW2_VERSION + ".nupkg")
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, data in texts.items():
            zipped.writestr(name, data)
            (restored / name).write_bytes(data)
    monkeypatch.setattr(notices, "CAMERA_WEBVIEW2_ARCHIVE_SHA512", base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode())
    lock = tmp_path / "camera.lock.json"
    lock.write_text(json.dumps({"dependencies": {"net10.0-windows10.0.19041/win-x64": {
        "Microsoft.Web.WebView2": {"resolved": notices.CAMERA_WEBVIEW2_VERSION, "contentHash": notices.CAMERA_WEBVIEW2_LOCK_SHA512}
    }}}))
    monkeypatch.setattr(notices, "CAMERA_LOCK", lock)
    camera = tmp_path / "camera"
    camera.mkdir()
    deps = camera / "GlobalPulse.Camera.deps.json"
    _deps(deps, [
        (notices.CAMERA_WEBVIEW2_PARENT, "package", [], ["runtimes/win-x64/native/WebView2Loader.dll"]),
        *[(name + "/" + notices.CAMERA_WEBVIEW2_VERSION, "reference", [name + ".dll"], []) for name in sorted(notices.CAMERA_WEBVIEW2_ALIASES)],
    ])
    return deps, nuget, camera / "licenses", restored, archive, lock


def test_camera_alias_notices_bind_to_exact_parent_lock_archive_and_actual_text(tmp_path, monkeypatch):
    deps, nuget, output, restored, _, _ = _camera_source(tmp_path, monkeypatch)
    result = notices.collect(deps, nuget, output, component="camera")
    assert result["component"] == "camera"
    assert result["deps_sha256"] == notices.digest(deps)
    assert len(result["packages"]) == 4
    for record in result["packages"]:
        assert record["notice_source_package"] == notices.CAMERA_WEBVIEW2_PARENT
        assert record["notice_source_lock_sha512"] == notices.CAMERA_WEBVIEW2_LOCK_SHA512
        assert record["notice_source_archive_sha512"] == notices.CAMERA_WEBVIEW2_ARCHIVE_SHA512
        assert {item["source_relative"] for item in record["notice_files"]} == {"LICENSE.txt", "NOTICE.txt"}
        for item in record["notice_files"]:
            assert (output.parent / item["packaged_relative"]).read_bytes() == (restored / item["source_relative"]).read_bytes()
    assert result["supplemental_resources"] == []
    assert "HOLD" in result["release_rights_status"]


@pytest.mark.parametrize("field,value", [("resolved", "1.0.4314.36"), ("contentHash", "wrong-lock-contentHash")])
def test_camera_notice_source_requires_exact_restored_lock_identity(tmp_path, monkeypatch, field, value):
    deps, nuget, output, _, _, lock = _camera_source(tmp_path, monkeypatch)
    document = json.loads(lock.read_text())
    next(iter(document["dependencies"].values()))["Microsoft.Web.WebView2"][field] = value
    lock.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="lock identity differs"):
        notices.collect(deps, nuget, output, component="camera")


def test_camera_notice_source_rejects_modified_signed_archive(tmp_path, monkeypatch):
    deps, nuget, output, _, archive, _ = _camera_source(tmp_path, monkeypatch)
    with archive.open("ab") as stream:
        stream.write(b"MODIFIED")
    with pytest.raises(ValueError, match="archive identity differs"):
        notices.collect(deps, nuget, output, component="camera")


def test_camera_notice_source_rejects_cache_notice_not_in_verified_archive(tmp_path, monkeypatch):
    deps, nuget, output, restored, _, _ = _camera_source(tmp_path, monkeypatch)
    (restored / "NOTICE.txt").write_text("Cache was modified independently of archive")
    with pytest.raises(ValueError, match="notice differs from reviewed archive"):
        notices.collect(deps, nuget, output, component="camera")


def test_camera_notice_source_rejects_other_component_and_wrong_deps_name(tmp_path, monkeypatch):
    deps, nuget, output, _, _, _ = _camera_source(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Unsupported native component"):
        notices.collect(deps, nuget, output, component="tv")
    wrong = deps.with_name("GlobalPulse.TV.deps.json")
    deps.rename(wrong)
    with pytest.raises(ValueError, match="published camera dependency identity"):
        notices.collect(wrong, nuget, output, component="camera")


@pytest.mark.parametrize("identity,kind,runtime,native", [
    ("Microsoft.Web.WebView2.Core/1.0.4314.36", "reference", ["Microsoft.Web.WebView2.Core.dll"], []),
    ("Microsoft.Web.WebView2.NewAlias/1.0.4314.35", "reference", ["Microsoft.Web.WebView2.NewAlias.dll"], []),
    ("Unrelated/1.0", "reference", ["Unrelated.dll"], []),
    ("Microsoft.Web.WebView2.Core/1.0.4314.35", "reference", ["Another.dll"], []),
    ("Microsoft.Web.WebView2.Core/1.0.4314.35", "reference", ["Microsoft.Web.WebView2.Core.dll"], ["Unexpected.dll"]),
    ("Microsoft.Web.WebView2/1.0.4314.36", "package", [], ["WebView2Loader.dll"]),
])
def test_camera_notice_exception_is_not_a_general_reference_or_sdk_bypass(tmp_path, monkeypatch, identity, kind, runtime, native):
    deps, nuget, output, _, _, _ = _camera_source(tmp_path, monkeypatch)
    _deps(deps, [(identity, kind, runtime, native)])
    with pytest.raises(ValueError, match="unsupported notice source|unreviewed asset|only for the exact camera"):
        notices.collect(deps, nuget, output, component="camera")


def test_camera_notice_target_must_be_windows_x64(tmp_path, monkeypatch):
    deps, nuget, output, _, _, _ = _camera_source(tmp_path, monkeypatch)
    document = json.loads(deps.read_text())
    target = document["targets"].pop(".NETCoreApp,Version=v10.0/win-x64")
    document["targets"][".NETCoreApp,Version=v10.0/win-arm64"] = target
    deps.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Windows x64 target missing"):
        notices.collect(deps, nuget, output, component="camera")


def test_camera_unknown_windowsdesktop_version_is_rejected_before_resource_admission(tmp_path):
    with pytest.raises(ValueError, match="runtime version is not reviewed"):
        notices.camera_desktop_resources({"runtimepack.Microsoft.WindowsDesktop.App.Runtime.win-x64/10.0.99": {}}, tmp_path, tmp_path)
