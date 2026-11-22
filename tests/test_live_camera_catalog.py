"""Finite live-video catalog routing; no provider request or playback claim."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

import pytest

from global_pulse.camera_context import approved_camera, associated_cameras, camera_catalog


EXPECTED = {
    "gpc-tannum-sands-live": "https://gpcl.com.au/environment/live-beach-cameras/tannum-sands-webcam/",
    "gpc-1770-live": "https://gpcl.com.au/environment/live-beach-cameras/1770-webcam/",
    "bsyc-seacliff-live": "https://www.ipcamlive.com/bsyc1080",
}


def live_entries():
    return [row for row in camera_catalog() if row.get("playback") == "live_video"]


def test_exact_three_live_choices_are_distinct_from_unchanged_snapshot_bank():
    catalog = camera_catalog()
    assert len(catalog) == 17 and len({row["id"] for row in catalog}) == 17
    assert {row["id"]: row["url"] for row in live_entries()} == EXPECTED
    snapshots = [row for row in catalog if row.get("snapshot_url")]
    assert len(snapshots) == 14
    # Canonical JSON of all 14 original records at base 74c8de9. This verifies
    # every field without requiring a full Git history in a shallow CI checkout.
    encoded = json.dumps(snapshots, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert hashlib.sha256(encoded).hexdigest() == "3d821af21ae75d9a16cd54d21c44bdc15810508f8c231a21d086596cbadb1255"


@pytest.mark.parametrize("identifier", sorted(EXPECTED))
def test_live_records_use_original_pages_exact_hosts_and_manual_consent(identifier):
    row = next(row for row in live_entries() if row["id"] == identifier)
    assert row["type"] == "webcam" and row["manual_only"] is True
    assert not row.get("snapshot_url") and not row.get("area_keywords")
    assert row["review_status"] == "public_player_verified"
    assert "not Windows Pulse" in row["verification_context"]
    assert row["attribution"] and row["rights"] and row["rights_url"]
    assert urlsplit(row["url"]).hostname in row["allowed_hosts"]
    assert set(row["allowed_frame_hosts"]) <= set(row["allowed_hosts"])
    for host in row["allowed_hosts"]:
        assert host == host.strip().lower() and "." in host
        assert not any(character in host for character in "/\\:@?#[]*")
        assert "youtube" not in host and "kiwisdr" not in host


@pytest.mark.parametrize("identifier", sorted(EXPECTED))
def test_caller_host_fields_cannot_expand_a_canonical_live_camera(identifier):
    row = next(row for row in live_entries() if row["id"] == identifier)
    poisoned = dict(row, allowed_hosts=["unreviewed.example"], manual_only=False,
                    attribution="injected", allowed_frame_hosts=["unreviewed.example"])
    assert approved_camera(poisoned) == row
    assert approved_camera(dict(row, url=row["url"] + "?unreviewed=1")) is None
    assert approved_camera(dict(row, playback="snapshot")) is None
    assert approved_camera(dict(row, snapshot_url="https://unreviewed.example/image.jpg")) is None


@pytest.mark.parametrize("supplied", [None, [], "camera", {"id": "unreviewed"}])
def test_invalid_or_unknown_camera_cannot_enter_registry(supplied):
    assert approved_camera(supplied) is None


def test_even_matching_live_geography_never_uses_snapshot_auto_association():
    row = dict(live_entries()[0], area_keywords=["Tannum Sands"], region_keywords=["Tannum Sands"])
    event = {"title": "Tannum Sands conditions", "region": "Tannum Sands", "country": "Australia"}
    assert associated_cameras(event, [row]) == []
    assert associated_cameras(event, [dict(row, manual_only=False)]) == []
