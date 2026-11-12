"""Engineering source/Qt tests. Synthetic inputs; no provider or browser access."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from copy import deepcopy
import socket
import sqlite3

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton

from global_pulse.controller import Controller
from global_pulse.source_availability import capability, enabled_ids, health_text, source_link
from global_pulse import provider_actions as actions
from global_pulse.ui import MainWindow


def source(identity="feed", **changes):
    value = dict(id=identity, name="Synthetic " + identity, url="https://feed.example.org/rss",
                 homepage="https://publisher.example.org/", adapter="rss", enabled=True,
                 access_status="reviewed_public", status="not_checked", min_interval=600,
                 allowed_domains=["feed.example.org"], category="News", region="Global")
    value.update(changes)
    return value


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Network access forbidden in source-control tests")
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture
def desktop(tmp_path, app, monkeypatch):
    controller = Controller(tmp_path, demo=True)
    controller.catalog = [source(), source("second", enabled=False),
                          source("website", adapter="manual", enabled=False, status="manual_only"),
                          source("approval", enabled=False, status="requires_approval", access_status="review_required"),
                          source("credentials", enabled=False, status="credentials_required"),
                          source("unknown", adapter="not-an-adapter", enabled=False)]
    controller._apply_sources()
    def no_start(*args, **kwargs):
        raise AssertionError("Source controls must not start or wake collection")
    monkeypatch.setattr(controller.scheduler, "start", no_start)
    monkeypatch.setattr(controller.scheduler, "resume", no_start)
    monkeypatch.setattr(controller.scheduler, "poll_now", no_start)
    window = MainWindow(controller)
    window.show()
    window.open_page(3)
    app.processEvents()
    yield window, controller
    window._force_close = True
    window.close()
    controller.close()
    window.deleteLater()
    app.processEvents()


def row_for(table, identity, column=0):
    for row in range(table.rowCount()):
        item = table.item(row, column)
        if item and (item.data(Qt.ItemDataRole.UserRole) or {}).get("id") == identity:
            return row
    raise AssertionError("Missing provider row: " + identity)


def test_capability_is_not_live_health_and_does_not_resolve_dns():
    assert capability(source())[:2] == (True, "Automatic feed")
    assert health_text({}) == "Not checked"
    assert enabled_ids([source()], None) == {"feed"}
    assert enabled_ids([source()], []) == set()
    assert enabled_ids([source()], "feed") == set()


@pytest.mark.parametrize("changes,kind", [
    ({"adapter": "manual"}, "Website only"),
    ({"status": "requires_approval"}, "Setup required"),
    ({"status": "credentials_required"}, "Setup required"),
    ({"access_status": "review_required"}, "Review required"),
    ({"adapter": "pretend"}, "Not integrated"),
    ({"status": "unavailable"}, "Unavailable"),
    ({"url": "https://127.0.0.1/secret"}, "Unavailable"),
    ({"url": "https://wrong.example.org/rss"}, "Unavailable"),
])
def test_ineligible_sources_never_get_collection_controls(changes, kind):
    candidate = source(**changes)
    assert capability(candidate)[:2] == (False, kind)
    assert enabled_ids([candidate], ["feed"]) == set()


def test_homepage_and_feed_are_distinct_and_unsafe_links_refused():
    assert source_link(source()) == ("Open website", "https://publisher.example.org/")
    assert source_link(source(homepage="")) == ("Open feed", "https://feed.example.org/rss")
    assert source_link(source(homepage="file:///secret", url="https://127.0.0.1/"))[1] == ""


@pytest.mark.parametrize("state,expected", [
    ({"status": "rate_limited"}, "Rate limited"),
    ({"status": "error", "last_success": "2026-11-01T00:00:00Z"}, "Last check failed"),
    ({"status": "available", "freshness": "stale"}, "reporting is stale"),
    ({"status": "available", "last_success": "2026-11-01T00:00:00Z"}, "freshness unknown"),
    ({"status": "not_modified", "last_success": "2026-11-01T00:00:00Z", "latest_publication": "2026-10-30T00:00:00Z"}, "no change"),
])
def test_health_does_not_confuse_fetch_success_with_fresh_reports(state, expected):
    assert expected in health_text(state)


def test_registry_has_real_feed_actions_and_manual_homepage_actions(desktop):
    window, controller = desktop
    table = window.source_table
    assert isinstance(table.cellWidget(row_for(table, "feed"), 8), QPushButton)
    assert isinstance(table.cellWidget(row_for(table, "website"), 8), QLabel)
    assert table.cellWidget(row_for(table, "website"), 9).text() == "Open website"
    assert "2 automatic feeds" in window.source_summary.text()
    assert "monitoring paused" in table.item(row_for(table, "feed"), 2).text()
    assert table.item(row_for(table, "feed"), 3).text() == "Not checked"


def test_manual_setting_is_explanation_not_disabled_checkbox(desktop):
    window, _ = desktop
    for row in range(window.source_preferences.rowCount()):
        control = window.source_preferences.cellWidget(row, 0)
        if control.property("source_id") == "website":
            assert isinstance(control, QLabel) and not isinstance(control, QCheckBox)
            assert "Website only" == control.text()
            assert window.source_preferences.cellWidget(row, 5).isEnabled()
            break
    else:
        pytest.fail("No website preference row")


def test_toggle_preserves_other_sources_pause_and_backoff(desktop):
    window, controller = desktop
    checkpoint = {"status": "rate_limited", "next_poll": "2099-01-01T00:00:00Z", "retry_after_seconds": 3600}
    controller.store.set_source_state("second", checkpoint)
    controller.set_source_enabled("second", True)
    assert controller.get_setting("enabled_sources") == ["feed", "second"]
    assert not controller.monitoring
    assert controller.store.get_source_state("second") == checkpoint
    assert {s["id"] for s in controller.scheduler.sources if s["enabled"]} == {"feed", "second"}
    controller.set_source_enabled("feed", False)
    assert controller.get_setting("enabled_sources") == ["second"]
    assert controller.store.get_source_state("second") == checkpoint


@pytest.mark.parametrize("identity", ["website", "approval", "credentials", "unknown", "removed"])
def test_controller_rejects_unavailable_or_missing_providers(desktop, identity):
    _, controller = desktop
    before = controller.get_setting("enabled_sources")
    with pytest.raises(ValueError):
        controller.set_source_enabled(identity, True)
    assert controller.get_setting("enabled_sources") == before


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_controller_rejects_non_boolean_toggle(desktop, value):
    _, controller = desktop
    with pytest.raises(ValueError):
        controller.set_source_enabled("feed", value)


def test_configuration_cannot_force_approval_required_source_on(desktop):
    _, controller = desktop
    controller.set_setting("enabled_sources", ["approval", "credentials", "unknown", "website"])
    assert not any(s["enabled"] for s in controller.scheduler.sources)


def test_clicked_action_uses_provider_identity_not_selected_row(desktop):
    window, controller = desktop
    feed_action = window.source_table.cellWidget(row_for(window.source_table, "second"), 8)
    window.source_table.selectRow(row_for(window.source_table, "website"))
    feed_action.click()
    assert controller.get_setting("enabled_sources") == ["feed", "second"]
    assert "paused" in window.status_label.text()


def test_browser_action_uses_homepage_without_enabling_collection(desktop, monkeypatch):
    window, controller = desktop
    opened = []
    monkeypatch.setattr(controller, "open_url", lambda url: opened.append(url) or True)
    before = controller.get_setting("enabled_sources")
    window.source_table.cellWidget(row_for(window.source_table, "website"), 9).click()
    assert opened == ["https://publisher.example.org/"]
    assert controller.get_setting("enabled_sources") == before


def test_removed_source_actions_are_refused(desktop, monkeypatch):
    window, controller = desktop
    monkeypatch.setattr(controller, "open_url", lambda url: pytest.fail("Stale browser target"))
    controller.catalog = [s for s in controller.catalog if s["id"] != "second"]
    assert not actions.open_site(window, "second")
    assert not actions.set_enabled(window, "second", True)


def test_registry_refresh_preserves_selection_and_escapes_text(desktop):
    window, controller = desktop
    controller.catalog[0]["name"] = "<img src=x onerror=alert(1)>"
    controller.store.set_source_state("feed", {"status": "error", "error": "<script>bad()</script>"})
    window.source_table.selectRow(row_for(window.source_table, "feed"))
    controller.catalog.reverse()
    actions.populate_sources(window)
    item = window.source_table.item(window.source_table.currentRow(), 0)
    assert item.data(Qt.ItemDataRole.UserRole)["id"] == "feed"
    assert "<script>bad()</script>" in window.source_browser.toPlainText()
    assert "<script>bad()</script>" not in window.source_browser.toHtml()


def test_failed_write_has_no_false_signal_or_success_state(desktop, monkeypatch):
    window, controller = desktop
    signals = []
    controller.data_changed.connect(lambda: signals.append(True))
    before = controller.get_setting("enabled_sources")
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("Synthetic write refusal")
    monkeypatch.setattr(controller.store, "set_setting", fail)
    assert not actions.set_enabled(window, "second", True)
    assert not signals and controller.get_setting("enabled_sources") == before
    assert "Could not" in window.status_label.text()


def test_settings_can_save_with_non_checkbox_manual_rows(desktop):
    window, controller = desktop
    window._save_settings()
    assert "Settings saved" in window.settings_result.text()
    assert controller.get_setting("enabled_sources") == ["feed"]


def test_source_toggle_preserves_other_unsaved_preferences(desktop):
    window, controller = desktop
    for row in range(window.source_preferences.rowCount()):
        control = window.source_preferences.cellWidget(row, 0)
        if control.property("source_id") == "feed":
            control.setChecked(False)
    actions.set_enabled(window, "second", True)
    window._save_settings()
    assert controller.get_setting("enabled_sources") == ["second"]


def test_corrupt_enabled_sources_are_sanitized_before_ui_toggle(desktop):
    """Malformed persisted JSON must not produce a Qt callback TypeError."""
    window, controller = desktop
    controller.set_setting("enabled_sources", [
        "feed", {"id": "second"}, [], None, 17, False, "feed",
    ])
    assert {s["id"] for s in controller.scheduler.sources if s["enabled"]} == {"feed"}

    # Exercise the same GUI/controller path that independent QA found broken.
    assert actions.set_enabled(window, "second", True) is True
    assert controller.get_setting("enabled_sources") == ["feed", "second"]
    assert {s["id"] for s in controller.scheduler.sources if s["enabled"]} == {"feed", "second"}
    assert not controller.monitoring

    assert actions.set_enabled(window, "feed", False) is True
    assert controller.get_setting("enabled_sources") == ["second"]
    assert {s["id"] for s in controller.scheduler.sources if s["enabled"]} == {"second"}


def test_non_list_enabled_source_preference_does_not_crash_controller(desktop):
    """Do not reinterpret a corrupt scalar preference as an iterable of IDs."""
    _, controller = desktop
    controller.store.set_setting("enabled_sources", {"id": "feed"})
    controller._apply_sources()
    assert not any(s["enabled"] for s in controller.scheduler.sources)

    assert controller.set_source_enabled("second", True) is True
    assert controller.get_setting("enabled_sources") == ["second"]
    assert not controller.monitoring
