"""Engineering regression for malformed persisted muted source preferences.

Only local/synthetic alert policy, no live collection or native notification.
Independent QA owns its unchanged adversarial suite separately (PR #44).
"""
from __future__ import annotations

import json
import socket
import pytest

from global_pulse.core import Store, muted_source_ids, notification_view
from global_pulse.controller import Controller

SOURCE_ID = "official-feed"
EVENT = {
    "id": "eng-alert-mute-fixture",
    "country": "US", "region": "US", "category": "Weather", "severity": "high",
    "reports": [{"source_id": SOURCE_ID}],
}


class SettingsStub:
    def __init__(self, saved):
        self.saved = saved

    def get_setting(self, key, default=None):
        return {"countries": [], "categories": [],
                "muted_sources": self.saved, "alert_threshold": "moderate"}.get(key, default)


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Offline Engineering regression must not call the network")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.mark.parametrize("malformed", [
    [{"id": SOURCE_ID}], [None, 1, False, ["nested"]], "official-feed", 99, None,
])
def test_malformed_entries_do_not_mute_or_abort_alert(malformed):
    assert muted_source_ids(malformed) == set()
    assert notification_view(EVENT, malformed) is EVENT
    assert Controller._watched(SettingsStub(malformed), EVENT) is True


def test_mixed_preference_preserves_valid_mute_and_skips_corrupt_neighbors():
    mixed = [SOURCE_ID, {"invalid": []}, [SOURCE_ID], None, 12, SOURCE_ID]
    assert muted_source_ids(mixed) == {SOURCE_ID}
    assert notification_view(EVENT, mixed) is None
    assert Controller._watched(SettingsStub(mixed), EVENT) is False


def test_stored_settings_roundtrip_preserves_unmodified_history(tmp_path):
    store = Store(tmp_path / "eng-muted-alert.sqlite3", mode="synthetic")
    try:
        saved = [SOURCE_ID, {"bad": [SOURCE_ID]}]
        store.set_setting("muted_sources", saved)
        readback = store.get_setting("muted_sources", [])
        assert readback == saved
        assert notification_view(EVENT, readback) is None
        assert Controller._watched(SettingsStub(readback), EVENT) is False
        assert store.get_setting("muted_sources", []) == saved
    finally:
        store.close()


def test_generator_source_ids_remain_supported():
    assert muted_source_ids(s for s in [SOURCE_ID, None, "other"]) == {SOURCE_ID, "other"}


def test_empty_preference_preserves_original_projection_identity():
    assert notification_view(EVENT, []) is EVENT
    assert Controller._watched(SettingsStub([]), EVENT) is True
