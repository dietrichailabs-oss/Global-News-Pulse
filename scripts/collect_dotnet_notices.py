"""Collect exact notice/license files for shipped .NET/NuGet runtime components.

This script is standard-library only. It consumes the published .deps.json and
copies notice material from the exact restored global-packages cache. Any package
that contributes runtime/native files but has no discoverable notice text fails
closed instead of silently producing a release candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

REVIEWED_REFERENCE_ROOT = Path(__file__).resolve().parents[1] / "packaging" / "licenses"
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
        if kind not in {"package", "runtimepack"}:
            raise ValueError(f"Shipped dependency has unsupported notice source: {identity} ({kind or 'unknown'})")
        root = package_root(nuget_root, package, version)
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
