"""Camera package gates use inert headers and notices, never runnable binaries.

Production pins remain fixed. Fixtures replace only expected byte fingerprints
with equally explicit inert material to exercise admission and tampering paths.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct

import pytest

from scripts import package_manifest as manifest


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _pe():
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, 0x8664)
    return bytes(data)


def add_inert_camera(root, monkeypatch, module=manifest):
    camera = root / "camera"
    camera.mkdir(parents=True)
    pins = {}
    for relative in module.CAMERA_WEBVIEW2_ASSETS:
        path = root / relative
        path.write_bytes(_pe())
        pins[relative] = {"bytes": path.stat().st_size, "sha256": module.digest(path)}
    monkeypatch.setattr(module, "CAMERA_WEBVIEW2_ASSETS", pins)
    for name in ("GlobalPulse.Camera.exe", "GlobalPulse.Camera.dll", "coreclr.dll"):
        (camera / name).write_bytes(_pe())
    duplicate = root / module.CAMERA_WEBVIEW2_NATIVE_DUPLICATE
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(_pe())
    _write_json(camera / "GlobalPulse.Camera.runtimeconfig.json", {"runtimeOptions": {"tfm": "net10.0", "includedFrameworks": [{"name": "Microsoft.NETCore.App", "version": "10.0.14"}]}})
    target_name = ".NETCoreApp,Version=v10.0/win-x64"
    target = {
        "GlobalPulse.Camera/0.1.1": {"runtime": {"GlobalPulse.Camera.dll": {}}},
        "runtimepack.Microsoft.NETCore.App.Runtime.win-x64/10.0.14": {"native": {"coreclr.dll": {}}},
        module.CAMERA_WEBVIEW2_PARENT: {"native": {"runtimes/win-x64/native/WebView2Loader.dll": {}}},
    }
    libraries = {
        "GlobalPulse.Camera/0.1.1": {"type": "project"},
        "runtimepack.Microsoft.NETCore.App.Runtime.win-x64/10.0.14": {"type": "runtimepack"},
        module.CAMERA_WEBVIEW2_PARENT: {"type": "package", "sha512": "sha512-" + module.CAMERA_WEBVIEW2_LOCK_SHA512},
    }
    for name in sorted(module.CAMERA_WEBVIEW2_ALIASES):
        identity = name + "/" + module.CAMERA_WEBVIEW2_VERSION
        target[identity] = {"runtime": {name + ".dll": {}}}
        libraries[identity] = {"type": "reference"}
    deps = camera / "GlobalPulse.Camera.deps.json"
    _write_json(deps, {"targets": {target_name: target}, "libraries": libraries})
    notice_data = {"LICENSE.txt": b"INERT CAMERA SDK LICENSE", "NOTICE.txt": b"INERT CAMERA SDK NOTICE"}
    monkeypatch.setattr(module, "CAMERA_WEBVIEW2_NOTICE_PINS", {name: {"bytes": len(data), "sha256": _sha(data)} for name, data in notice_data.items()})
    records = []
    for identity, meta in target.items():
        package, version = identity.rsplit("/", 1)
        kind = libraries[identity]["type"]
        if kind == "project":
            continue
        webview = package in module.CAMERA_WEBVIEW2_ALIASES or identity == module.CAMERA_WEBVIEW2_PARENT
        paths = []
        for name, data in notice_data.items() if webview else {"LICENSE.txt": b"INERT DOTNET LICENSE"}.items():
            relative = f"licenses/{package}-{version}/{name}"
            path = camera / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            paths.append({"source_relative": name, "packaged_relative": relative, "bytes": len(data), "sha256": _sha(data)})
        records.append({"package": package, "version": version, "type": kind,
                        "evidence_kind": "package_notice_text", "runtime_files": sorted(meta.get("runtime", {})), "native_files": sorted(meta.get("native", {})),
                        "notice_source_package": module.CAMERA_WEBVIEW2_PARENT if webview else identity,
                        "notice_source_lock_sha512": module.CAMERA_WEBVIEW2_LOCK_SHA512 if webview else None,
                        "notice_source_archive_sha512": module.CAMERA_WEBVIEW2_ARCHIVE_SHA512 if webview else None,
                        "notice_files": paths})
    _write_json(camera / "licenses/NATIVE_PACKAGE_NOTICES.json", {
        "component": "camera", "deps_file": deps.name, "deps_sha256": module.digest(deps),
        "target": target_name, "packages": records, "supplemental_resources": [],
        "release_rights_status": "HOLD: inert fixture is not redistribution approval",
    })
    return root


@pytest.fixture
def camera(tmp_path, monkeypatch):
    return add_inert_camera(tmp_path, monkeypatch)


def _edit_ledger(root, change):
    path = root / "camera/licenses/NATIVE_PACKAGE_NOTICES.json"
    ledger = json.loads(path.read_text())
    change(ledger)
    _write_json(path, ledger)


def _edit_deps(root, change):
    path = root / "camera/GlobalPulse.Camera.deps.json"
    deps = json.loads(path.read_text())
    change(deps)
    _write_json(path, deps)
    _edit_ledger(root, lambda ledger: ledger.update(deps_sha256=manifest.digest(path)))


def test_exact_camera_lane_admits_inert_package_with_separate_provenance(camera):
    assert manifest.scan(camera, require_complete=False)["status"] == "PASS"
    assert manifest.camera_payload(camera)["sdk_package"] == manifest.CAMERA_WEBVIEW2_PARENT


@pytest.mark.parametrize("relative", sorted(manifest.CAMERA_REQUIRED_FILES))
def test_camera_gate_rejects_each_missing_required_file(camera, relative):
    (camera / relative).unlink()
    with pytest.raises(ValueError, match="Required camera runtime file is missing"):
        manifest.scan(camera, require_complete=False)


@pytest.mark.parametrize("relative", sorted(manifest.CAMERA_WEBVIEW2_ASSETS))
def test_camera_gate_rejects_modified_reviewed_webview_bytes(camera, relative):
    with (camera / relative).open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="asset byte identity differs"):
        manifest.scan(camera, require_complete=False)


def test_native_loader_duplicate_is_hash_bound_to_the_same_x64_asset(camera):
    (camera / manifest.CAMERA_WEBVIEW2_NATIVE_DUPLICATE).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="native duplicate byte identity differs"):
        manifest.scan(camera, require_complete=False)


@pytest.mark.parametrize("relative", [
    "camera/extra.exe", "camera/extra.dll", "camera/browser_cache/history.json",
    "camera/anything.json", "camera/another/GlobalPulse.Camera.exe", "camera/Microsoft.Web.WebView2.Core.xml",
    "camera/runtimes/win-x86/native/WebView2Loader.dll", "camera/runtimes/win-arm64/native/WebView2Loader.dll",
    "camera/licenses/Microsoft.Web.WebView2-1.0.4314.35/unlisted.txt",
    "notifications/Microsoft.Web.WebView2.Core.dll", "_internal/WebView2Loader.dll",
    "notifications/licenses/Microsoft.Web.WebView2-1.0.4314.35/LICENSE.txt",
    "camera/tv/old.dll", "camera/GlobalPulse.TV.exe", "camera/native_tv.py",
])
def test_camera_allowance_does_not_admit_extra_architecture_cache_or_tv_files(camera, relative):
    path = camera / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"INERT EXTRA FILE")
    with pytest.raises(ValueError, match="Runtime package rejected"):
        manifest.scan(camera, require_complete=False)


@pytest.mark.parametrize("field,value", [
    ("notice_source_package", "Microsoft.Web.WebView2/9.9"),
    ("notice_source_lock_sha512", "not-the-reviewed-lock"),
    ("notice_source_archive_sha512", "not-the-reviewed-archive"),
    ("version", "1.0.4314.99"), ("runtime_files", ["Unlisted.dll"]),
])
def test_camera_reference_requires_exact_parent_archive_lock_and_runtime_binding(camera, field, value):
    def mutate(ledger):
        next(row for row in ledger["packages"] if row["package"] in manifest.CAMERA_WEBVIEW2_ALIASES)[field] = value
    _edit_ledger(camera, mutate)
    with pytest.raises(ValueError, match="Camera"):
        manifest.scan(camera, require_complete=False)


@pytest.mark.parametrize("field,value", [("component", "notifications"), ("deps_file", "GlobalPulse.TV.deps.json"), ("deps_sha256", "0"*64), ("target", ".NETCoreApp,Version=v10.0/win-arm64")])
def test_camera_ledger_is_bound_to_shipped_camera_manifest(camera, field, value):
    _edit_ledger(camera, lambda data: data.update({field: value}))
    with pytest.raises(ValueError, match="not bound"):
        manifest.scan(camera, require_complete=False)


def test_camera_cannot_drop_notice_record_and_keep_binaries(camera):
    _edit_ledger(camera, lambda data: data["packages"].pop())
    with pytest.raises(ValueError, match="missing shipped dependencies"):
        manifest.scan(camera, require_complete=False)


def test_camera_cannot_duplicate_notice_record(camera):
    _edit_ledger(camera, lambda data: data["packages"].append(data["packages"][0]))
    with pytest.raises(ValueError, match="duplicate dependency"):
        manifest.scan(camera, require_complete=False)


def test_camera_rejects_tampered_notice_even_if_ledger_hash_is_rewritten(camera):
    def mutate(data):
        record = next(row for row in data["packages"] if row["package"] in manifest.CAMERA_WEBVIEW2_ALIASES)
        notice = record["notice_files"][0]
        path = camera / "camera" / notice["packaged_relative"]
        path.write_bytes(b"FAKE LICENSE")
        notice.update(bytes=path.stat().st_size, sha256=manifest.digest(path))
    _edit_ledger(camera, mutate)
    with pytest.raises(ValueError, match="notice bytes/path differ"):
        manifest.scan(camera, require_complete=False)


def test_camera_notice_path_cannot_escape_license_inventory(camera):
    _edit_ledger(camera, lambda data: data["packages"][0]["notice_files"][0].update(packaged_relative="../outside.txt"))
    with pytest.raises(ValueError, match="Unsafe camera inventory path"):
        manifest.scan(camera, require_complete=False)


@pytest.mark.parametrize("field", ["framework", "frameworks"])
def test_camera_framework_dependent_output_is_rejected(camera, field):
    path = camera / "camera/GlobalPulse.Camera.runtimeconfig.json"
    _write_json(path, {"runtimeOptions": {"tfm": "net10.0", field: {"name": "Microsoft.NETCore.App", "version": "10.0.14"}}})
    with pytest.raises(ValueError, match="self-contained .NET10"):
        manifest.scan(camera, require_complete=False)


def test_camera_parent_sdk_dep_hash_is_independent_of_ledger_hash(camera):
    _edit_deps(camera, lambda data: data["libraries"][manifest.CAMERA_WEBVIEW2_PARENT].update(sha512="sha512-fake"))
    with pytest.raises(ValueError, match="reviewed parent WebView2 SDK"):
        manifest.scan(camera, require_complete=False)


def test_camera_unknown_reference_cannot_inherit_webview_permission(camera):
    def change(data):
        target = next(iter(data["targets"].values()))
        target["Unknown/1.0"] = {"runtime": {"Unknown.dll": {}}}
        data["libraries"]["Unknown/1.0"] = {"type": "reference"}
    _edit_deps(camera, change)
    with pytest.raises(ValueError, match="no reviewed package provenance"):
        manifest.scan(camera, require_complete=False)


def test_camera_sbom_uses_one_real_parent_sdk_without_alias_packages(camera, monkeypatch):
    monkeypatch.setattr(manifest.metadata, "distributions", lambda: [])
    manifest.sbom(camera)
    data = json.loads((camera / "SBOM.cdx.json").read_text())
    sdk = [item for item in data["components"] if item["type"] == "library" and item["name"].startswith("Microsoft.Web.WebView2")]
    assert [(item["name"], item["version"]) for item in sdk] == [("Microsoft.Web.WebView2", "1.0.4314.35")]
    assert data["compositions"][0]["aggregate"] == "incomplete"
    assert "NOASSERTION" in json.dumps(sdk)


def test_production_notice_and_manifest_pins_agree():
    from scripts import collect_dotnet_notices as notices
    for name in ("CAMERA_WEBVIEW2_PARENT", "CAMERA_WEBVIEW2_LOCK_SHA512", "CAMERA_WEBVIEW2_ARCHIVE_SHA512", "CAMERA_DESKTOP_RUNTIME_PINS", "CAMERA_DESKTOP_CULTURES", "CAMERA_DESKTOP_SATELLITES"):
        assert getattr(notices, name) == getattr(manifest, name)
    assert manifest.CAMERA_WEBVIEW2_LOCK_SHA512 != manifest.CAMERA_WEBVIEW2_ARCHIVE_SHA512
    assert len(manifest.CAMERA_WEBVIEW2_ASSETS) == 4


def test_owner_workflow_retains_full_gate_and_probes_after_actual_main_build():
    root = Path(__file__).parents[1]
    text = (root / ".github/workflows/r20-live-cameras-owner-package.yml").read_text()
    frozen = (root / ".github/workflows/issue21-r20-digital-radio-owner-package.yml").read_text()
    flags = lambda value: re.findall(r"--(?:ignore|deselect)=\S+", value)
    assert flags(text) == flags(frozen)
    assert len([flag for flag in flags(text) if flag.startswith("--deselect")]) == 14
    assert len([flag for flag in flags(text) if flag.startswith("--ignore")]) == 2
    assert text.index("scripts\\build_windows.ps1") < text.index("'--self-test-policy'") < text.index("scripts/qa_windows_camera_embed.py")
    assert "dist\\GlobalPulse\\camera\\GlobalPulse.Camera.exe" in text
    assert "blocked_standard_user" in text and "profile_cleanup_status" in text
    assert "live_camera_playback_verified = $false" in text
    assert "camera_helper_exe_sha256" in text and "camera_helper_dll_sha256" in text
    assert "checks.Count -ne 8" in text
    assert "Preserve embedded diagnostic captures even on failure\n        if: always()" in text
    assert "branches: [eng/r20-live-cameras-20261122]" in text


def _add_inert_desktop_resources(camera, monkeypatch):
    identity = "runtimepack.Microsoft.WindowsDesktop.App.Runtime.win-x64/10.0.14"
    dll = camera / "camera/System.Windows.Forms.dll"
    dll.write_bytes(_pe())
    def change(data):
        next(iter(data["targets"].values()))[identity] = {"runtime": {dll.name: {}}}
        data["libraries"][identity] = {"type": "runtimepack"}
    _edit_deps(camera, change)
    package, version = identity.rsplit("/", 1)
    notice = camera / "camera/licenses" / (package + "-" + version) / "LICENSE.txt"
    notice.parent.mkdir()
    notice.write_bytes(b"INERT WINDOWS DESKTOP LICENSE")
    records = []
    for culture in sorted(manifest.CAMERA_DESKTOP_CULTURES):
        for name in sorted(manifest.CAMERA_DESKTOP_SATELLITES):
            relative = culture + "/" + name
            path = camera / "camera" / relative
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(_pe() + relative.encode())
            records.append({"file": relative, "bytes": path.stat().st_size, "sha256": manifest.digest(path)})
    records.sort(key=lambda item: item["file"])
    pins = {key: dict(value) for key, value in manifest.CAMERA_DESKTOP_RUNTIME_PINS.items()}
    pins[identity]["resources_sha256"] = _sha(json.dumps(records, sort_keys=True, separators=(",", ":")).encode())
    monkeypatch.setattr(manifest, "CAMERA_DESKTOP_RUNTIME_PINS", pins)
    def ledger_change(ledger):
        ledger["supplemental_resources"] = records
        ledger["packages"].append({"package": package, "version": version, "type": "runtimepack", "runtime_files": [dll.name], "native_files": [],
                                  "notice_files": [{"source_relative": "LICENSE.txt", "packaged_relative": notice.relative_to(camera / "camera").as_posix(), "bytes": notice.stat().st_size, "sha256": manifest.digest(notice)}]})
    _edit_ledger(camera, ledger_change)
    return records


def test_exact_known_desktop_satellites_are_admitted_by_reviewed_inventory(camera, monkeypatch):
    resources = _add_inert_desktop_resources(camera, monkeypatch)
    assert len(resources) == 52
    assert manifest.scan(camera, require_complete=False)["status"] == "PASS"


def test_desktop_resource_file_tampering_is_rejected(camera, monkeypatch):
    resources = _add_inert_desktop_resources(camera, monkeypatch)
    (camera / "camera" / resources[0]["file"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="satellite byte identity differs"):
        manifest.scan(camera, require_complete=False)


def test_desktop_resource_tampering_cannot_be_hidden_by_rehashing_receipt(camera, monkeypatch):
    resources = _add_inert_desktop_resources(camera, monkeypatch)
    path = camera / "camera" / resources[0]["file"]
    path.write_bytes(b"tampered")
    _edit_ledger(camera, lambda ledger: ledger["supplemental_resources"][0].update(bytes=path.stat().st_size, sha256=manifest.digest(path)))
    with pytest.raises(ValueError, match="satellite inventory differs"):
        manifest.scan(camera, require_complete=False)


def test_desktop_resource_ledger_cannot_expand_known_cultures(camera, monkeypatch):
    resources = _add_inert_desktop_resources(camera, monkeypatch)
    _edit_ledger(camera, lambda ledger: ledger["supplemental_resources"].append({**resources[0], "file": "unknown/Arbitrary.resources.dll"}))
    with pytest.raises(ValueError, match="satellite set differs"):
        manifest.scan(camera, require_complete=False)


def test_resource_receipt_without_exact_desktop_parent_fails(camera):
    _edit_ledger(camera, lambda ledger: ledger.update(supplemental_resources=[{"file": "fr/Extra.dll", "bytes": 1, "sha256": "0"*64}]))
    with pytest.raises(ValueError, match="lack exact runtime package provenance"):
        manifest.scan(camera, require_complete=False)
