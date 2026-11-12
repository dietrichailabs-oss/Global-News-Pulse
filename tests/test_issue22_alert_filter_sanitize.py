"""Engineering regression: untrusted persisted alert filter types.

Synthetic/local policy checks only. Independent QA suite and its earlier FAIL
remain separate and untouched. No native Windows alert or media claim.
"""
from __future__ import annotations

import socket

import pytest

from global_pulse.controller import Controller
from global_pulse.core import Store

EVENT = {
    "id": "engineering-synthetic-filter-alert",
    "country": "US",
    "region": "US",
    "category": "Weather",
    "severity": "high",
    "reports": [{"source_id": "public-official-weather"}],
}


class LocalSettings:
    def __init__(self, **overrides):
        self.saved = {
            "countries": [],
            "categories": [],
            "muted_sources": [],
            "alert_threshold": "moderate",
        }
        self.saved.update(overrides)

    def get_setting(self, name, default=None):
        return self.saved.get(name, default)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Offline alert eligibility test attempted network")
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def watched(**settings):
    return Controller._watched(LocalSettings(**settings), EVENT)


def test_valid_defaults():
    assert watched()
    assert watched(countries=["US"], categories=["Weather"], alert_threshold="high")


def test_explicit_user_filters_still_limit_matching():
    assert not watched(countries=["CA"])
    assert not watched(categories=["Economy"])
    assert not watched(alert_threshold="critical")
    assert watched(countries=["us"])
    assert watched(countries=["us"], categories=["Weather"])
    # Preserve the original category comparison rather than broadening it.
    assert not watched(categories=["weather"])


@pytest.mark.parametrize("key", ["countries", "categories"])
@pytest.mark.parametrize("invalid", [True, False, 123, "US", {"US": True}, None])
def test_invalid_nonlist_persisted_filter_is_unfiltered(key, invalid):
    assert watched(**{key: invalid})


@pytest.mark.parametrize("key", ["countries", "categories"])
@pytest.mark.parametrize("entries", [
    [123], [{"unhashable": []}], [None, True], ["", "   ", False]
])
def test_invalid_list_entries_do_not_implicitly_block(key, entries):
    assert watched(**{key: entries})


def test_valid_values_with_invalid_values_still_narrow():
    assert watched(countries=[None, "US", {"ignored": []}], categories=[True, "Weather"])
    assert not watched(countries=[None, "CA", {"ignored": []}])
    assert not watched(categories=[False, "Economy", ["not-hashable"]])


@pytest.mark.parametrize("invalid", [
    [], [3], {}, {"moderate": 1}, True, 8, None, "unknown", "",
])
def test_malformed_threshold_uses_existing_moderate_default(invalid):
    assert watched(alert_threshold=invalid)


def test_valid_threshold_rank_semantics_remain():
    for level in ("unassessed", "informational", "moderate", "high"):
        assert watched(alert_threshold=level)
    assert not watched(alert_threshold="critical")


def test_muted_sources_remain_excluded():
    assert not watched(muted_sources=["public-official-weather"])
    assert watched(muted_sources=[{"bad": []}, "other-source"])


def test_real_sqlite_roundtrip_of_corrupt_filter_json(tmp_path):
    store = Store(tmp_path / "engineering-alert-filters.sqlite3", mode="synthetic")
    try:
        store.set_setting("countries", True)
        store.set_setting("categories", [{"malformed": []}])
        store.set_setting("alert_threshold", [])
        persisted = {key: store.get_setting(key) for key in (
            "countries", "categories", "alert_threshold"
        )}
        assert persisted == {
            "countries": True,
            "categories": [{"malformed": []}],
            "alert_threshold": [],
        }
        assert Controller._watched(LocalSettings(**persisted), EVENT)
    finally:
        store.close()
