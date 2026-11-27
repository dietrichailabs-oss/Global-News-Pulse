"""Owner Win11 regression: opt-in toasts, all collectable sources, warm tab switching.

Uses synthetic/offline Qt only. This is not proof of native Windows playback
or timing; independent packaged Win11 QA is still required.
"""
from __future__ import annotations

import os
import time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QLabel

from global_pulse.__main__ import _native_status_visible
from global_pulse.native_notifications import NativeNotifications
from global_pulse.controller import Controller
from global_pulse.source_availability import available_ids, capability, enabled_ids
from global_pulse.sources import load_catalog
from global_pulse.ui import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(app, tmp_path):
    controller = Controller(tmp_path, demo=True)
    window = MainWindow(controller)
    window.show()
    app.processEvents()
    yield window, controller
    window._workspace_warm_timer.stop()
    window.media.shutdown()
    window._force_close = True
    window.close()
    controller.close()
    window.deleteLater()
    app.processEvents()


def test_new_profiles_enable_every_genuinely_collectable_source():
    catalog = load_catalog()
    collectable = available_ids(catalog)
    assert len(collectable) >= 100, "The reviewed public feeds must remain available"
    assert enabled_ids(catalog, None) == collectable
    assert "ecb_press" in collectable
    assert "ecb" not in collectable, "Duplicate legacy ID must not poll the exact URL twice"
    assert "india_pib" not in collectable, "Quarantined HTTP 403 remains unavailable"
    assert "gdelt_world_press" not in collectable, "Timed-out source remains quarantined"
    assert enabled_ids(catalog, []) == set(), "An explicit user opt-out is preserved"
    for source in catalog:
        if source["id"] in collectable:
            assert capability(source)[0]
            assert source.get("access_status") in {"reviewed_public", "user_supplied"}


def test_legacy_enabled_setting_cannot_silently_launch_native_alerts(tmp_path):
    controller = Controller(tmp_path, demo=True)
    changed = []
    redrawn = []
    controller.notification_preference_changed.connect(changed.append)
    controller.data_changed.connect(lambda: redrawn.append(True))
    try:
        assert controller.get_setting("notifications_enabled", False) is False
        controller.store.set_setting("notifications_enabled", True)
        # Old versions wrote this automatically without affirmative consent.
        assert controller.get_setting("notifications_enabled", False) is False
        controller.set_setting("notifications_enabled", True)
        assert controller.get_setting("notifications_enabled", False) is True
        assert changed == [True]
        controller.set_setting("notifications_enabled", True)
        assert changed == [True], "Idempotent save cannot restart notification helper"
        controller.set_setting("notifications_enabled", False)
        assert controller.get_setting("notifications_enabled", True) is False
        assert changed == [True, False]
        assert redrawn == [], "Toast setting must never re-query the world map"
    finally:
        controller.close()


def test_source_toggle_only_invalidates_source_status_not_map(tmp_path):
    controller = Controller(tmp_path, demo=True)
    redraws, statuses = [], []
    controller.data_changed.connect(lambda: redraws.append(True))
    controller.source_status_changed.connect(lambda: statuses.append(True))
    try:
        collectable = sorted(available_ids(controller.catalog))
        assert set(controller._enabled_collection_ids) == set(collectable)
        controller.set_setting("enabled_sources", [collectable[0]])
        assert controller._enabled_collection_ids == frozenset((collectable[0],))
        assert statuses == [True]
        assert redraws == []
    finally:
        controller.close()


def test_settings_enable_all_available_requires_save_and_never_enables_blocked(desktop):
    window, controller = desktop
    controller.set_setting("enabled_sources", [])
    window._populate_source_preferences()
    assert enabled_ids(controller.catalog, controller.get_setting("enabled_sources", None)) == set()
    assert window.setting_notify.isChecked() is False
    window._enable_all_available_sources()
    expected = available_ids(controller.catalog)
    selections = set()
    blocked_count = 0
    for i in range(window.source_preferences.rowCount()):
        control = window.source_preferences.cellWidget(i, 0)
        if isinstance(control, QCheckBox) and control.isChecked():
            selections.add(control.property("source_id"))
        elif not isinstance(control, QCheckBox):
            blocked_count += 1
            assert not control.isEnabled()
    assert selections == expected
    assert blocked_count > 0
    assert controller.get_setting("enabled_sources", []) == [], "Save remains an explicit user action"
    window._save_settings()
    assert "Settings saved" in window.settings_result.text()
    assert enabled_ids(controller.catalog, controller.get_setting("enabled_sources", None)) == expected


def test_warmed_tab_navigation_does_not_populate_or_read_on_click(desktop, monkeypatch):
    window, controller = desktop
    assert window.prepare_initial_workspaces() is True
    window._dirty_pages.update(range(1, 6))
    calls = []
    for name in ("_populate_situations", "_populate_economy", "_populate_sources",
                 "_populate_alerts", "_generate_brief"):
        monkeypatch.setattr(
            window, name,
            lambda *args, name=name, **kwargs: (calls.append((name, kwargs)), True)[1]
        )
    for _ in range(30):
        for page in (1, 2, 3, 4, 5, 0):
            window.open_page(page)
    assert not calls, "Click handlers must only change stacked QWidget selection"
    assert window.pages.currentIndex() == 0
    assert window._workspace_warm_timer.isActive()
    # One explicitly invoked idle turn processes only ONE stale page.
    window._workspace_warm_timer.stop()
    window._last_navigation_at = 0.0  # Simulate a genuinely idle GUI turn.
    window._warm_next_workspace()
    assert len(calls) == 1
    window._workspace_warm_timer.stop()


def test_source_registry_live_health_update_reuses_expensive_table_widgets(desktop):
    window, controller = desktop
    window.open_page(3)
    source = next(s for s in controller.catalog if capability(s)[0])
    rows = [i for i in range(window.source_table.rowCount())
            if (window.source_table.item(i, 0).data(Qt.ItemDataRole.UserRole) or {}).get("id") == source["id"]]
    assert len(rows) == 1
    row = rows[0]
    before_item = window.source_table.item(row, 0)
    before_action = window.source_table.cellWidget(row, 8)
    assert isinstance(before_action, QPushButton)
    controller.store.set_source_state(source["id"], {
        "status": "available", "last_success": "2026-11-15T12:00:00+00:00"
    })
    window._populate_sources()
    assert window.source_table.item(row, 0) is before_item
    assert window.source_table.cellWidget(row, 8) is before_action
    assert "Last check succeeded" in window.source_table.item(row, 3).text()


def test_same_id_capability_change_rebuilds_controls_even_after_sorting(desktop):
    window, controller = desktop
    window.open_page(3)
    window.source_table.setSortingEnabled(True)
    window.source_table.sortItems(0, Qt.SortOrder.DescendingOrder)
    source = next(s for s in controller.catalog if capability(s)[0])
    source_id = source["id"]

    def row_for_id():
        return next(i for i in range(window.source_table.rowCount())
                    if (window.source_table.item(i, 0).data(Qt.ItemDataRole.UserRole) or {}).get("id") == source_id)

    row = row_for_id()
    assert isinstance(window.source_table.cellWidget(row, 8), QPushButton)
    original_status = source.get("status")
    try:
        # A catalog revision can preserve the same ID and row count while
        # revoking the collector. Never show its old Enable button.
        source["status"] = "disabled"
        window._populate_sources()
        row = row_for_id()
        assert isinstance(window.source_table.cellWidget(row, 8), QLabel)
        assert not window.source_table.cellWidget(row, 8).isEnabled() or (
            window.source_table.cellWidget(row, 8).text() == "Unavailable"
        )
        assert window.source_table.item(row, 0).data(Qt.ItemDataRole.UserRole)["status"] == "disabled"
    finally:
        source["status"] = original_status
    window._populate_sources()
    row = row_for_id()
    assert isinstance(window.source_table.cellWidget(row, 8), QPushButton)


def test_opt_out_during_native_registration_blocks_pending_dispatch(app):
    assert _native_status_visible("Windows notification service ready", False).startswith(
        "Windows pop-up notifications off"
    )
    assert _native_status_visible("helper failed", True) == "helper failed"
    state = {"enabled": True}
    notifier = NativeNotifications(enabled=True, predicate=lambda: state["enabled"])
    writes, deliveries = [], []

    class InMemoryProcess:
        def write(self, payload):
            writes.append(payload)
            return len(payload)

    notifier.process = InMemoryProcess()
    notifier.ready = True
    notifier.delivery_changed.connect(lambda identifier, message: deliveries.append((identifier, message)))
    event = {"id": "synthetic-optout-event", "_alert_id": "synthetic-optout-alert"}
    try:
        # In the race a helper can signal ready after Settings/Tray turned OFF.
        state["enabled"] = False
        assert notifier.notify(event, "Synthetic never submitted") is False
        notifier._pending.append((event, "Synthetic queued before opt-out", time.monotonic()))
        notifier._flush()
        assert not writes, "Opt-out must prevent every new native helper write"
        assert not notifier._pending
        assert all("suppressed" in message for _, message in deliveries)
    finally:
        notifier.process = None
        notifier.stop()
        notifier.deleteLater()
