"""Exact-source recovery regressions for the public Windows packaging migration.

Engineering-only: these checks do not establish installer or independent QA acceptance.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qt_distribution_notice_gate", ROOT / "scripts/qt_distribution.py")
qt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qt)
BUNDLE = ROOT / "packaging/licenses/qt-webengine-pdf"


def _dest(tmp_path):
    destination = tmp_path / "runtime/licenses/qt-open-source/corresponding-source/SOURCE-NOTICES.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _synthetic(tmp_path):
    root = tmp_path / "source"
    parts = root / "notices-parts"
    parts.mkdir(parents=True)
    payloads = [(f"Third party notice part {i}: Ω\n").encode("utf-8") for i in range(27)]
    for i, payload in enumerate(payloads):
        (parts / f"part-{i:02d}.txt").write_bytes(payload)
    expected_data = b"".join(payloads)
    expected = {"bytes": len(expected_data), "sha256": hashlib.sha256(expected_data).hexdigest()}
    return root, expected, expected_data


def test_historical_eight_megabyte_notice_reassembles_exactly(tmp_path):
    metadata = json.loads((BUNDLE / "SOURCE_MAP.json").read_text(encoding="utf-8"))
    destination = _dest(tmp_path)
    expected = metadata["documents"]["SOURCE-NOTICES.txt"]
    assert expected == {
        "bytes": 8066680,
        "sha256": "fafc8fcf2d62d46d423f6a24bd7240081a137fcd6296aa278b9d5db47537dd6c",
    }
    qt.materialize_notice_parts(BUNDLE, destination, expected)
    assert destination.stat().st_size == expected["bytes"]
    assert qt.digest(destination) == expected["sha256"]
    assert not (BUNDLE / "SOURCE-NOTICES.txt").exists()
    assert not destination.with_name(destination.name + ".partial").exists()


def test_synthetic_notice_reassembly_preserves_bytes(tmp_path):
    bundle, expected, payload = _synthetic(tmp_path)
    destination = _dest(tmp_path)
    qt.materialize_notice_parts(bundle, destination, expected)
    assert destination.read_bytes() == payload


def test_same_size_tampering_fails_closed_without_partial_delivery(tmp_path):
    bundle, expected, _ = _synthetic(tmp_path)
    part = bundle / "notices-parts/part-03.txt"
    part.write_bytes(part.read_bytes().replace(b"notice", b"NOTice"))
    destination = _dest(tmp_path)
    with pytest.raises(ValueError, match="differ from reviewed source"):
        qt.materialize_notice_parts(bundle, destination, expected)
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".partial").exists()


def test_missing_part_is_rejected(tmp_path):
    bundle, expected, _ = _synthetic(tmp_path)
    (bundle / "notices-parts/part-14.txt").unlink()
    with pytest.raises(ValueError, match="Missing, extra"):
        qt.materialize_notice_parts(bundle, _dest(tmp_path), expected)


def test_extra_part_is_rejected(tmp_path):
    bundle, expected, _ = _synthetic(tmp_path)
    (bundle / "notices-parts/part-27.txt").write_text("unreviewed")
    with pytest.raises(ValueError, match="Missing, extra"):
        qt.materialize_notice_parts(bundle, _dest(tmp_path), expected)


def test_existing_destination_is_never_overwritten(tmp_path):
    bundle, expected, _ = _synthetic(tmp_path)
    destination = _dest(tmp_path)
    destination.write_bytes(b"pre-existing")
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        qt.materialize_notice_parts(bundle, destination, expected)
    assert destination.read_bytes() == b"pre-existing"


def test_failed_size_gate_removes_partial(tmp_path):
    bundle, expected, _ = _synthetic(tmp_path)
    destination = _dest(tmp_path)
    smaller = {**expected, "bytes": expected["bytes"] - 1}
    with pytest.raises(ValueError, match="exceed reviewed size"):
        qt.materialize_notice_parts(bundle, destination, smaller)
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".partial").exists()
