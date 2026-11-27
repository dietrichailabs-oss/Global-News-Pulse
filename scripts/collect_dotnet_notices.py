"""Collect exact notice/license files for shipped .NET/NuGet runtime components.

This script is standard-library only. It consumes the published .deps.json and
copies notice material from the exact restored global-packages cache. Any package
that contributes runtime/native files but has no discoverable notice text fails
closed instead of silently producing a release candidate.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

REVIEWED_REFERENCE_ROOT = Path(__file__).resolve().parents[1] / "packaging" / "licenses"
REVIEWED_EXTERNAL_LICENSE_REFERENCES = {
    ("runtimepack.microsoft.windows.sdk.net.ref", "10.0.19041.57"):
        "Microsoft.Windows.SDK.NET.Ref-10.0.19041.57-LICENSE-REFERENCE.txt",
}

# The camera is the sole admitted WebView2 consumer. Assembly reference aliases
# are not separate NuGet packages: bind them to the exact SDK and restored lock.
CAMERA_WEBVIEW2_VERSION = "1.0.4314.35"
CAMERA_WEBVIEW2_PARENT = "Microsoft.Web.WebView2/" + CAMERA_WEBVIEW2_VERSION
CAMERA_WEBVIEW2_ALIASES = {
    "Microsoft.Web.WebView2.Core", "Microsoft.Web.WebView2.WinForms", "Microsoft.Web.WebView2.Wpf",
}
CAMERA_WEBVIEW2_LOCK_SHA512 = "x5MFf2W03xueU1mMNvivXfHSsQ+ODo7vJ36qw/dLtU5Gs+8d7+7N7zzmNNDoT3ffosmcvZNBtUnlzyiDUuBkSQ=="
# NuGet lock contentHash and the signed archive's full-file hash are different
# identities. Both are checked; neither substitutes for the other.
CAMERA_WEBVIEW2_ARCHIVE_SHA512 = "cOaiVqP3BmQHMnxGpZzANM22tUXgycrisyJHjIGNzIaMsm8iXj7Kx+ceYg+RbYwJtzT009qfcFTocvVLY+ekMw=="
CAMERA_LOCK = Path(__file__).resolve().parents[1] / "packaging/camera/packages.lock.json"

# SDK10.0.403/404 can be selected by the existing global.json policy. Admit
# only their separately reviewed WindowsDesktop14/15 satellite bytes.
CAMERA_DESKTOP_RUNTIME_PINS = {
    "runtimepack.Microsoft.WindowsDesktop.App.Runtime.win-x64/10.0.14": {
        "archive_sha256": "a6dba3ca8b8b5b7945399545d881e0ac294746a7571f2209981934d49ecfe8cc",
        "resources_sha256": "818b04fe69dea719b73913b4d7995aab0d7e7b89aa95090033b5804984a7d417",
    },
    "runtimepack.Microsoft.WindowsDesktop.App.Runtime.win-x64/10.0.15": {
        "archive_sha256": "a036c174bac57a716e21dedccf96459804e4d8d8c31a08e3a8de649bf7684497",
        "resources_sha256": "1414234419f334e5b663493c8a19263424c00db7e93455c3aa1895ac098fd833",
    },
}
CAMERA_DESKTOP_CULTURES = {"cs", "de", "es", "fr", "it", "ja", "ko", "pl", "pt-BR", "ru", "tr", "zh-Hans", "zh-Hant"}
CAMERA_DESKTOP_SATELLITES = {"Microsoft.VisualBasic.Forms.resources.dll", "System.Windows.Forms.Design.resources.dll", "System.Windows.Forms.Primitives.resources.dll", "System.Windows.Forms.resources.dll"}


def camera_webview2_source(nuget_root: Path) -> Path:
    lock = json.loads(CAMERA_LOCK.read_text(encoding="utf-8-sig"))
    entries = [target["Microsoft.Web.WebView2"]
               for target in lock.get("dependencies", {}).values()
               if "Microsoft.Web.WebView2" in target]
    if not entries or any(entry.get("resolved") != CAMERA_WEBVIEW2_VERSION
                          or entry.get("contentHash") != CAMERA_WEBVIEW2_LOCK_SHA512
                          for entry in entries):
        raise ValueError("Camera WebView2 lock identity differs from reviewed SDK")
    root = package_root(nuget_root, "Microsoft.Web.WebView2", CAMERA_WEBVIEW2_VERSION)
    archive = root / ("microsoft.web.webview2." + CAMERA_WEBVIEW2_VERSION + ".nupkg")
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("Camera WebView2 restored SDK archive missing")
    with archive.open("rb") as stream:
        actual = base64.b64encode(hashlib.file_digest(stream, "sha512").digest()).decode("ascii")
    if actual != CAMERA_WEBVIEW2_ARCHIVE_SHA512:
        raise ValueError("Camera WebView2 signed archive identity differs from reviewed SDK")
    # Copy only the actual license and notice bytes present in this exact SDK;
    # a modified cache file cannot acquire provenance from the archive hash.
    with zipfile.ZipFile(archive) as package:
        for name in ("LICENSE.txt", "NOTICE.txt"):
            path = root / name
            if not path.is_file() or path.is_symlink() or path.read_bytes() != package.read(name):
                raise ValueError("Camera WebView2 notice differs from reviewed archive: " + name)
    return root


def camera_desktop_resources(target: dict, published: Path, nuget_root: Path) -> list[dict]:
    identities = [name for name in target if name.startswith("runtimepack.Microsoft.WindowsDesktop.App.Runtime.")]
    if not identities:
        return []
    if len(identities) != 1 or identities[0] not in CAMERA_DESKTOP_RUNTIME_PINS:
        raise ValueError("Camera WindowsDesktop runtime version is not reviewed")
    identity = identities[0]
    pins = CAMERA_DESKTOP_RUNTIME_PINS[identity]
    package, version = identity.rsplit("/", 1)
    restored = package_root(nuget_root, package, version)
    archive = restored / ("microsoft.windowsdesktop.app.runtime.win-x64." + version + ".nupkg")
    if not archive.is_file() or archive.is_symlink() or digest(archive) != pins["archive_sha256"]:
        raise ValueError("Camera WindowsDesktop archive differs from reviewed runtime")
    records = []
    with zipfile.ZipFile(archive) as zipped:
        for culture in sorted(CAMERA_DESKTOP_CULTURES):
            for name in sorted(CAMERA_DESKTOP_SATELLITES):
                relative = culture + "/" + name
                source = "runtimes/win-x64/lib/net10.0/" + relative
                shipped = published / relative
                if not shipped.is_file() or shipped.is_symlink() or shipped.read_bytes() != zipped.read(source):
                    raise ValueError("Camera WindowsDesktop satellite differs from reviewed runtime: " + relative)
                records.append({"file": relative, "bytes": shipped.stat().st_size, "sha256": digest(shipped)})
    records.sort(key=lambda record: record["file"])
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != pins["resources_sha256"]:
        raise ValueError("Camera WindowsDesktop satellite inventory differs from reviewed runtime")
    return records

NOTICE = re.compile(r"(?:^|[-_.])(license|licence|notice|copying|copyright|third[-_. ]?party)(?:[-_.]|$)", re.I)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_piece(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    if not value or value in {".", ".."}:
        raise ValueError("Invalid package identity")
    return value


def package_root(nuget_root: Path, package: str, version: str) -> Path:
    candidates = [package]
    if package.lower().startswith("runtimepack."):
        candidates.append(package[len("runtimepack."):])
    for candidate in candidates:
        root = nuget_root / candidate.lower() / version.lower()
        if root.is_dir():
            return root.resolve()
    raise ValueError(f"Restored package directory missing: {package} {version}")


def notice_files(root: Path) -> list[Path]:
    found = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.stat().st_size > 8 * 1024 * 1024:
            continue
        if NOTICE.search(path.name):
            found.append(path)
    return sorted(found, key=lambda item: item.relative_to(root).as_posix().lower())


def collect(deps_path: Path, nuget_root: Path, output: Path, *, component: str = "notifications") -> dict:
    if component not in {"notifications", "camera"}:
        raise ValueError("Unsupported native component")
    if component == "camera" and deps_path.name != "GlobalPulse.Camera.deps.json":
        raise ValueError("Camera notice receipt requires the published camera dependency identity")
    deps_path = deps_path.resolve(strict=True)
    nuget_root = nuget_root.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    document = json.loads(deps_path.read_text(encoding="utf-8-sig"))
    targets = document.get("targets") or {}
    if not targets:
        raise ValueError("Published .deps.json has no targets")
    target_name = next((name for name in targets if name.lower().endswith("/win-x64")), None)
    if component == "camera" and target_name is None:
        raise ValueError("Camera published Windows x64 target missing")
    target_name = target_name or next(iter(targets))
    target = targets[target_name]
    libraries = document.get("libraries") or {}

    records = []
    for identity, target_meta in sorted(target.items(), key=lambda item: item[0].lower()):
        runtime = target_meta.get("runtime") or {}
        native = target_meta.get("native") or {}
        if not runtime and not native:
            continue
        if "/" not in identity:
            raise ValueError(f"Malformed dependency identity: {identity}")
        package, version = identity.rsplit("/", 1)
        library = libraries.get(identity) or {}
        kind = str(library.get("type", "")).lower()
        if kind == "project":
            continue
        notice_source_package = identity
        reference_lock_hash = None
        reference_archive_hash = None
        reviewed_camera_reference = (
            component == "camera" and kind == "reference"
            and package in CAMERA_WEBVIEW2_ALIASES and version == CAMERA_WEBVIEW2_VERSION
        )
        reviewed_camera_parent = (
            component == "camera" and kind == "package" and identity == CAMERA_WEBVIEW2_PARENT
        )
        if reviewed_camera_reference or reviewed_camera_parent:
            if reviewed_camera_reference and (set(runtime) != {package + ".dll"} or native):
                raise ValueError("Camera WebView2 reference contains an unreviewed asset")
            root = camera_webview2_source(nuget_root)
            notice_source_package = CAMERA_WEBVIEW2_PARENT
            reference_lock_hash = CAMERA_WEBVIEW2_LOCK_SHA512
            reference_archive_hash = CAMERA_WEBVIEW2_ARCHIVE_SHA512
        elif kind in {"package", "runtimepack"}:
            if "webview2" in package.lower():
                raise ValueError("WebView2 is admitted only for the exact camera SDK")
            root = package_root(nuget_root, package, version)
        else:
            raise ValueError(f"Shipped dependency has unsupported notice source: {identity} ({kind or 'unknown'})")
        sources = ([root / "LICENSE.txt", root / "NOTICE.txt"]
                   if reviewed_camera_reference or reviewed_camera_parent else notice_files(root))
        reference_name = REVIEWED_EXTERNAL_LICENSE_REFERENCES.get((package.lower(), version))
        if not sources and not reference_name:
            raise ValueError(f"Runtime package notice text missing: {package} {version}")

        destination = output / f"{safe_piece(package)}-{safe_piece(version)}"
        destination.mkdir()
        copied = []
        evidence_kind = "package_notice_text"
        if sources:
            for source in sources:
                relative = source.relative_to(root)
                name = safe_piece(relative.as_posix().replace("/", "__"))
                target_file = destination / name
                shutil.copyfile(source, target_file)
                copied.append({
                    "source_relative": relative.as_posix(),
                    "packaged_relative": target_file.relative_to(output.parent).as_posix(),
                    "bytes": target_file.stat().st_size,
                    "sha256": digest(target_file),
                })
        else:
            reference = REVIEWED_REFERENCE_ROOT / reference_name
            if not reference.is_file() or reference.stat().st_size > 512 * 1024:
                raise ValueError(f"Reviewed external license reference missing: {package} {version}")
            target_file = destination / reference.name
            shutil.copyfile(reference, target_file)
            copied.append({
                "source_relative": "external-license-reference",
                "packaged_relative": target_file.relative_to(output.parent).as_posix(),
                "bytes": target_file.stat().st_size,
                "sha256": digest(target_file),
            })
            evidence_kind = "external_license_reference_only"
        records.append({
            "package": package,
            "version": version,
            "type": kind,
            "evidence_kind": evidence_kind,
            "notice_source_package": notice_source_package,
            "notice_source_lock_sha512": reference_lock_hash,
            "notice_source_archive_sha512": reference_archive_hash,
            "runtime_files": sorted(runtime),
            "native_files": sorted(native),
            "notice_files": copied,
        })

    if not records:
        raise ValueError("No shipped external .NET runtime packages found")
    receipt = {
        "component": component,
        "supplemental_resources": camera_desktop_resources(target, deps_path.parent, nuget_root) if component == "camera" else [],
        "deps_file": deps_path.name,
        "deps_sha256": digest(deps_path),
        "target": target_name,
        "packages": records,
        "external_license_reference_only": [
            {"package": r["package"], "version": r["version"]}
            for r in records if r["evidence_kind"] == "external_license_reference_only"
        ],
        "release_rights_status": "HOLD if external license references require separate redistribution-term acceptance",
    }
    (output / "NATIVE_PACKAGE_NOTICES.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deps", required=True, type=Path)
    parser.add_argument("--nuget-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--component", choices=("notifications", "camera"), default="notifications")
    args = parser.parse_args(argv)
    result = collect(args.deps, args.nuget_root, args.output, component=args.component)
    print(json.dumps({"status": "PASS", "packages": len(result["packages"]),
                      "notice_files": sum(len(r["notice_files"]) for r in result["packages"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
