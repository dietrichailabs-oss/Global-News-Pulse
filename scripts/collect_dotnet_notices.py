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
from pathlib import Path

REVIEWED_REFERENCE_ROOT = Path(__file__).resolve().parents[1] / "packaging" / "licenses"
REVIEWED_PACKAGE_LOCK_PATH = Path(__file__).resolve().parents[1] / "packaging" / "tv" / "packages.lock.json"
# Published WebView2 assembly identities are .deps.json "reference" entries, not
# independently restored packages. Only these exact SDK version identities may
# take their notice provenance from the pinned parent Microsoft.Web.WebView2.
REVIEWED_WEBVIEW2_REFERENCE_PARENTS = {
    ("microsoft.web.webview2.core", "1.0.4314.35"): ("Microsoft.Web.WebView2", "1.0.4314.35"),
    ("microsoft.web.webview2.winforms", "1.0.4314.35"): ("Microsoft.Web.WebView2", "1.0.4314.35"),
    ("microsoft.web.webview2.wpf", "1.0.4314.35"): ("Microsoft.Web.WebView2", "1.0.4314.35"),
}
REVIEWED_EXTERNAL_LICENSE_REFERENCES = {
    ("runtimepack.microsoft.windows.sdk.net.ref", "10.0.19041.57"):
        "Microsoft.Windows.SDK.NET.Ref-10.0.19041.57-LICENSE-REFERENCE.txt",
}

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


def reviewed_reference_notice_root(
    library_name: str, version: str, libraries: dict, nuget_root: Path,
) -> tuple[Path, str, str]:
    """Resolve only reviewed WebView2 assembly references to a locked NuGet source.

    Validate both the source-locked package record and the restored NuGet
    SHA-512 digest. Unknown references, missing lock proof, and mismatches STOP.
    """
    alias = REVIEWED_WEBVIEW2_REFERENCE_PARENTS.get((library_name.lower(), version))
    if alias is None:
        raise ValueError(
            f"Shipped dependency has unsupported notice source: {library_name}/{version} (reference)"
        )
    parent, pinned_version = alias
    parent_identity = f"{parent}/{pinned_version}"
    if parent_identity in libraries:
        parent_kind = str(libraries[parent_identity].get("type", "")).lower()
        if parent_kind != "package":
            raise ValueError(f"Reference parent dependency type mismatch: {parent_identity}")

    lock = json.loads(REVIEWED_PACKAGE_LOCK_PATH.read_text(encoding="utf-8-sig"))
    dependency_sets = (lock.get("dependencies") or {}).values()
    records = [dep.get(parent) for dep in dependency_sets if isinstance(dep, dict)]
    records = [record for record in records if isinstance(record, dict)]
    if not records or any(
        record.get("type") != "Direct"
        or record.get("resolved") != pinned_version
        or record.get("requested") != f"[{pinned_version}, )"
        or not isinstance(record.get("contentHash"), str)
        for record in records
    ):
        raise ValueError(f"Exact WebView2 reference parent lock missing: {parent_identity}")
    locked_hashes = {record["contentHash"].strip() for record in records}
    if len(locked_hashes) != 1:
        raise ValueError(f"WebView2 reference package lock hashes conflict: {parent_identity}")
    locked_hash = locked_hashes.pop()
    root = package_root(nuget_root, parent, pinned_version)
    basename = f"{parent.lower()}.{pinned_version.lower()}.nupkg"
    hash_file = root / f"{basename}.sha512"
    archive = root / basename
    if not archive.is_file() or archive.is_symlink() or not hash_file.is_file():
        raise ValueError(f"Restored WebView2 SDK archive or hash receipt missing: {parent_identity}")
    with archive.open("rb") as stream:
        actual_hash = base64.b64encode(hashlib.file_digest(stream, "sha512").digest()).decode("ascii")
    if (actual_hash != locked_hash
            or hash_file.read_text(encoding="utf-8").strip() != actual_hash):
        raise ValueError(f"Restored WebView2 reference archive SHA512 differs from lock: {parent_identity}")
    return root, parent_identity, actual_hash


def collect(deps_path: Path, nuget_root: Path, output: Path) -> dict:
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
        if kind == "reference":
            root, notice_source_package, reference_lock_hash = reviewed_reference_notice_root(
                package, version, libraries, nuget_root
            )
        elif kind in {"package", "runtimepack"}:
            root = package_root(nuget_root, package, version)
        else:
            raise ValueError(f"Shipped dependency has unsupported notice source: {identity} ({kind or 'unknown'})")
        sources = notice_files(root)
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
            "runtime_files": sorted(runtime),
            "native_files": sorted(native),
            "notice_files": copied,
        })

    if not records:
        raise ValueError("No shipped external .NET runtime packages found")
    receipt = {
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
    args = parser.parse_args(argv)
    result = collect(args.deps, args.nuget_root, args.output)
    print(json.dumps({"status": "PASS", "packages": len(result["packages"]),
                      "notice_files": sum(len(r["notice_files"]) for r in result["packages"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
