"""Exercise Git checkout conversion with inert evidence, without network access."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def _git(directory: Path, *arguments: str) -> None:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    subprocess.run(
        ["git", "-C", str(directory), *arguments],
        check=True, capture_output=True, env=environment,
    )


def _checkout(tmp_path: Path, *, protect_evidence: bool):
    original = tmp_path / "original"
    original.mkdir()
    _git(original, "init", "--quiet")
    _git(original, "config", "core.autocrlf", "false")
    _git(original, "config", "user.name", "Inert checkout test")
    _git(original, "config", "user.email", "checkout-test@example.invalid")
    fixtures = {
        "packaging/licenses/windows-sdk/SDK_REDIST.html": b"INERT REDIST\nsecond line\n",
        "packaging/licenses/windows-sdk/SDK_LICENSE.rtf": b"INERT RTF\r\nsecond line\r\n",
        "packaging/licenses/qt-webengine-pdf/SOURCE-NOTICES.txt": b"\xef\xbb\xbfINERT NOTICE\nsecond line\n",
        "docs/engineering/GP-ENG-FREEWARE-COMPLIANCE-001/upstream/original.txt": b"INERT UPSTREAM\nsecond line\n",
    }
    for relative, data in fixtures.items():
        path = original / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (original / "ordinary-source.txt").write_bytes(b"ordinary source\n")
    if protect_evidence:
        (original / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    _git(original, "add", ".")
    _git(original, "commit", "--quiet", "-m", "Inert checkout fixture")

    checkout = tmp_path / "windows-style-checkout"
    _git(tmp_path, "clone", "--quiet", "--no-checkout", str(original), str(checkout))
    _git(checkout, "config", "core.autocrlf", "true")
    _git(checkout, "config", "core.eol", "crlf")
    _git(checkout, "checkout", "--quiet", "--detach", "HEAD")
    return checkout, fixtures


def test_hashed_evidence_survives_windows_style_git_checkout(tmp_path):
    checkout, fixtures = _checkout(tmp_path, protect_evidence=True)
    for relative, expected in fixtures.items():
        actual = (checkout / relative).read_bytes()
        assert actual == expected, relative
        assert len(actual) == len(expected)
        assert hashlib.sha256(actual).digest() == hashlib.sha256(expected).digest()
    # The policy is narrowly scoped, not a global checkout configuration change.
    assert (checkout / "ordinary-source.txt").read_bytes() == b"ordinary source\r\n"


def test_unprotected_windows_style_checkout_reproduces_exact_byte_failure(tmp_path):
    checkout, fixtures = _checkout(tmp_path, protect_evidence=False)
    relative = "packaging/licenses/windows-sdk/SDK_REDIST.html"
    original = fixtures[relative]
    actual = (checkout / relative).read_bytes()
    assert actual == original.replace(b"\n", b"\r\n")
    assert len(actual) != len(original)
    assert hashlib.sha256(actual).digest() != hashlib.sha256(original).digest()
