"""Developer-only lock refresh from official PyPI metadata; never run at app startup.

Uses installed, tested versions when available, and resolves Windows-only
dependencies against their declared requirements. Every PyPI artifact hash for
the selected release is included so the lock supports both Windows and Linux.
"""
from __future__ import annotations

import concurrent.futures
import importlib.metadata as metadata
import json
from pathlib import Path

import httpx
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ["PySide6", "httpx[socks]", "defusedxml", "langdetect", "ctranslate2", "sentencepiece", "sacremoses", "subword-nmt"]
BUILD = ["pytest", "pyinstaller", "setuptools", "wheel", "packaging"]


def main():
    import tomllib
    pinned = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    seeds = pinned + [f"{x}=={metadata.version(x)}" for x in BUILD]
    environments = []
    for platform in ("linux", "win32"):
        env = default_environment()
        env.update(sys_platform=platform, platform_system="Windows" if platform == "win32" else "Linux", os_name="nt" if platform == "win32" else "posix", python_version="3.12", python_full_version="3.12.14")
        environments.append(env)
    records, extras = {}, {}
    pending = [Requirement(s) for s in seeds]
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        while pending:
            requirement = pending.pop(0)
            name = canonicalize_name(requirement.name)
            extras.setdefault(name, set()).update(requirement.extras)
            if name in records:
                if records[name]["version"] not in requirement.specifier:
                    raise ValueError(f"Conflicting dependency version for {name}")
                continue
            try:
                version = metadata.version(name)
            except metadata.PackageNotFoundError:
                response = client.get(f"https://pypi.org/pypi/{name}/json")
                response.raise_for_status()
                releases = response.json()["releases"]
                candidates = [Version(v) for v, files in releases.items() if files and not Version(v).is_prerelease and v in requirement.specifier and not all(f.get("yanked",False) for f in files)]
                version = str(max(candidates))
            if version not in requirement.specifier:
                raise ValueError(f"Installed version of {name} does not satisfy {requirement.specifier}")
            response = client.get(f"https://pypi.org/pypi/{name}/{version}/json")
            response.raise_for_status()
            result = response.json()
            hashes = sorted({f["digests"]["sha256"] for f in result["urls"] if not f.get("yanked", False)})
            if not hashes:
                raise ValueError(f"No non-yanked artifacts for {name}")
            info = result["info"]
            records[name] = {"version": version, "sha256": hashes, "license_expression": info.get("license_expression") or info.get("license") or "NOASSERTION", "project_url": info.get("project_url") or info.get("package_url"), "requires": []}
            for raw in info.get("requires_dist") or []:
                dependency = Requirement(raw)
                applicable = dependency.marker is None or any(dependency.marker.evaluate({**env, "extra": extra}) for env in environments for extra in extras[name] | {""})
                if applicable:
                    pending.append(dependency)
                    records[name]["requires"].append(canonicalize_name(dependency.name))

    def closure(seed_names):
        found, queue = set(), [canonicalize_name(Requirement(n).name) for n in seed_names]
        while queue:
            name = queue.pop()
            if name not in found:
                found.add(name)
                queue.extend(records[name]["requires"])
        return found

    def write_lock(filename, names):
        text = "# Tested exact versions. PyPI SHA-256 artifact hashes.\n# Python 3.12; Windows x64 and Linux. Refresh only through engineering review.\n"
        for name in sorted(names):
            record = records[name]
            marker = '; sys_platform == "win32"' if name in {"pefile", "pywin32-ctypes", "colorama"} else ""
            text += f"\n{name}=={record['version']}{marker} \\\n"
            text += " \\\n".join(f"    --hash=sha256:{h}" for h in record["sha256"]) + "\n"
        (ROOT / filename).write_text(text)

    write_lock("requirements.lock", closure(RUNTIME))
    write_lock("requirements-build.lock", set(records))
    write_lock("requirements-bootstrap.lock", closure(["setuptools", "wheel", "packaging"]))
    (ROOT / "docs" / "DEPENDENCY_INVENTORY.json").write_text(json.dumps(records, indent=2))
    print(f"Locked {len(records)} packages with release artifact SHA-256 hashes")


if __name__ == "__main__":
    main()
