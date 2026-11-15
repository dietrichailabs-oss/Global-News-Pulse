"""One-time owner-requested source enable-all upgrade, no live provider access."""
from __future__ import annotations

from global_pulse.source_availability import (
    available_ids,
    enabled_ids,
    migrate_all_available_sources_once,
)


class InertSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = []

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.writes.append((key, value))
        self.values[key] = value


def _source(identifier, **overrides):
    value = {
        "id": identifier,
        "url": "https://example.org/feed.xml",
        "allowed_domains": ["example.org"],
        "adapter": "rss",
        "access_status": "reviewed_public",
        "status": "available",
    }
    value.update(overrides)
    return value


def _catalog():
    return [
        _source("alpha"),
        _source("beta"),
        _source("approval", status="requires_approval"),
        _source("manual", adapter="manual"),
        _source("duplicate", disabled_reason="Duplicate exact feed URL: alpha"),
        _source("unreviewed", access_status="pending"),
        _source("unintegrated", adapter="unknown-adapter"),
        _source("restricted", status="restricted"),
    ]


def test_fresh_profile_already_defaults_to_all_and_is_marked_once():
    catalog = _catalog()
    store = InertSettings()
    assert available_ids(catalog) == {"alpha", "beta"}
    assert migrate_all_available_sources_once(store, catalog) is False
    assert store.get_setting("enabled_sources") is None
    assert enabled_ids(catalog, store.get_setting("enabled_sources")) == {"alpha", "beta"}
    assert store.get_setting("source_enable_all_upgrade_v1") is True
    assert store.get_setting("enabled_sources_before_enable_all_v1") is None
    assert store.writes == [("source_enable_all_upgrade_v1", True)]


def test_existing_profile_enables_every_eligible_source_once_and_saves_original():
    catalog = _catalog()
    store = InertSettings({"enabled_sources": ["alpha", "manual", "missing"]})
    assert migrate_all_available_sources_once(store, catalog) is True
    assert store.get_setting("enabled_sources") == ["alpha", "beta"]
    assert store.get_setting("enabled_sources_before_enable_all_v1") == [
        "alpha", "manual", "missing"
    ]
    assert store.get_setting("source_enable_all_upgrade_v1") is True
    assert [name for name, _ in store.writes] == [
        "enabled_sources_before_enable_all_v1",
        "enabled_sources",
        "source_enable_all_upgrade_v1",
    ]


def test_after_one_upgrade_future_opt_out_survives_restart():
    store = InertSettings({"enabled_sources": ["alpha"]})
    catalog = _catalog()
    assert migrate_all_available_sources_once(store, catalog) is True
    store.set_setting("enabled_sources", ["beta"])
    before = len(store.writes)
    assert migrate_all_available_sources_once(store, catalog) is False
    assert len(store.writes) == before
    assert store.get_setting("enabled_sources") == ["beta"]
    assert enabled_ids(catalog, store.get_setting("enabled_sources")) == {"beta"}


def test_existing_upgrade_marker_honors_empty_disabled_source_selection():
    store = InertSettings({
        "enabled_sources": [],
        "source_enable_all_upgrade_v1": True,
    })
    assert migrate_all_available_sources_once(store, _catalog()) is False
    assert store.writes == []
    assert enabled_ids(_catalog(), store.get_setting("enabled_sources")) == set()


def test_interrupted_upgrade_preserves_first_backup_and_recovers():
    store = InertSettings({
        "enabled_sources_before_enable_all_v1": ["alpha"],
        "enabled_sources": ["alpha", "beta"],
    })
    assert migrate_all_available_sources_once(store, _catalog()) is True
    assert store.get_setting("enabled_sources_before_enable_all_v1") == ["alpha"]
    assert store.get_setting("enabled_sources") == ["alpha", "beta"]
    assert store.get_setting("source_enable_all_upgrade_v1") is True


def test_malformed_historical_preference_is_backed_up_but_never_reenabled_raw():
    store = InertSettings({"enabled_sources": {"unexpected": "shape"}})
    assert migrate_all_available_sources_once(store, _catalog()) is True
    assert store.get_setting("enabled_sources_before_enable_all_v1") == {
        "unexpected": "shape"
    }
    assert store.get_setting("enabled_sources") == ["alpha", "beta"]


def test_zero_eligible_sources_does_not_invent_provider_access():
    catalog = [
        _source("approval", status="requires_approval"),
        _source("restricted", status="restricted"),
    ]
    store = InertSettings({"enabled_sources": ["approval"]})
    assert migrate_all_available_sources_once(store, catalog) is True
    assert store.get_setting("enabled_sources") == []
    assert enabled_ids(catalog, store.get_setting("enabled_sources")) == set()


def test_actual_sqlite_controller_upgrade_restart_and_later_opt_out(tmp_path):
    """Exercise the real live Controller/Store without starting monitoring."""
    from PySide6.QtCore import QCoreApplication
    from global_pulse.controller import Controller
    from global_pulse.core import Store

    app = QCoreApplication.instance() or QCoreApplication([])
    profile = tmp_path / "live-profile"
    profile.mkdir()
    store = Store(profile / "global-pulse.sqlite3", mode="live")
    store.set_setting("enabled_sources", ["historical_missing_feed"])
    store.close()

    first = Controller(profile, demo=False)
    try:
        eligible = available_ids(first.catalog)
        assert eligible
        assert first._enabled_sources_migrated is True
        assert set(first.get_setting("enabled_sources")) == eligible
        assert first._enabled_collection_ids == frozenset(eligible)
        assert first.store.get_setting("enabled_sources_before_enable_all_v1") == [
            "historical_missing_feed"
        ]
        assert first.monitoring is False
        excluded = sorted(eligible)[0]
        first.set_source_enabled(excluded, False)
    finally:
        first.close()

    second = Controller(profile, demo=False)
    try:
        assert second._enabled_sources_migrated is False
        assert excluded not in second._enabled_collection_ids
        assert len(second._enabled_collection_ids) == len(eligible) - 1
        assert second.store.get_setting("enabled_sources_before_enable_all_v1") == [
            "historical_missing_feed"
        ]
        assert second.monitoring is False
    finally:
        second.close()


def test_actual_synthetic_controller_does_not_rewrite_demo_selection(tmp_path):
    from PySide6.QtCore import QCoreApplication
    from global_pulse.controller import Controller
    from global_pulse.core import Store

    app = QCoreApplication.instance() or QCoreApplication([])
    profile = tmp_path / "synthetic-profile"
    profile.mkdir()
    store = Store(profile / "synthetic.sqlite3", mode="synthetic")
    store.set_setting("enabled_sources", [])
    store.close()

    controller = Controller(profile, demo=True)
    try:
        assert controller._enabled_sources_migrated is False
        assert controller.get_setting("enabled_sources") == []
        assert controller._enabled_collection_ids == frozenset()
        assert controller.store.get_setting("source_enable_all_upgrade_v1") is None
        assert controller.monitoring is False
    finally:
        controller.close()
