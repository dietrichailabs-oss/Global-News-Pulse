"""Complete, searchable source inventory; offline synthetic provider states.

These are Qt/Store regressions, not live provider availability or owner-PC QA.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse import provider_actions as actions
from global_pulse.ui import MainWindow


def _source(identity, **changes):
    row = dict(id=identity, name="Synthetic " + identity, adapter="rss",
               url="https://example.org/feed/" + identity,
               homepage="https://example.org/", allowed_domains=["example.org"],
               access_status="reviewed_public", status="not_checked", enabled=True,
               min_interval=600, category="Economy", country="US", region="Global")
    row.update(changes)
    return row


def _visible(window):
    return {window.source_table.item(row, 0).data(Qt.ItemDataRole.UserRole)["id"]
            for row in range(window.source_table.rowCount())
            if not window.source_table.isRowHidden(row)}


def _mode(window, name):
    window.source_filter.setCurrentIndex(window.source_filter.findData(name))


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No live network in source-inventory tests")
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    controller.catalog = [
        _source("alpha"),
        _source("beta", category="Health", country="CA"),
        _source("gamma", category="Climate", country="GB"),
        _source("website", adapter="manual", status="manual_only", enabled=False),
    ]
    controller.store.set_setting("enabled_sources", ["alpha", "gamma"])
    controller.store.set_source_state("gamma", {"status": "error", "error": "Synthetic timeout"})
    controller._apply_sources()
    window = MainWindow(controller)
    window.show()
    window.open_page(3)
    app.processEvents()
    window._workspace_warm_timer.stop()
    try:
        yield window, controller, app
    finally:
        window._force_close = True
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer", "_source_batch_timer", "search_timer"):
            getattr(window, name).stop()
        window.media.shutdown()
        window.close()
        controller.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_all_registry_rows_include_enabled_never_checked_off_and_manual(inventory):
    window, controller, _ = inventory
    assert set(actions._existing_source_rows(window.source_table)) == {
        source["id"] for source in controller.catalog}
    assert _visible(window) == {"alpha", "beta", "gamma", "website"}
    alpha = actions._existing_source_rows(window.source_table)["alpha"]
    beta = actions._existing_source_rows(window.source_table)["beta"]
    assert window.source_table.item(alpha, 3).text() == "Not checked"
    assert "Enabled" in window.source_table.item(alpha, 2).text()
    assert window.source_table.item(beta, 2).text() == "Off"
    assert "4 total registered entries" in window.source_summary.text()
    assert "Showing 4 of 4 registry entries" in window.source_visible_count.text()
    assert "2 enabled collectors" in window.source_visible_count.text()


def test_filter_search_reset_are_in_memory_and_do_not_enable_sources(inventory):
    window, controller, _ = inventory
    saved = controller.get_setting("enabled_sources")
    with patch.object(controller, "get_setting", side_effect=AssertionError("filter read settings")), \
         patch.object(controller.store, "list_source_states", side_effect=AssertionError("filter read states")), \
         patch.object(controller.store, "set_setting", side_effect=AssertionError("filter wrote preferences")):
        _mode(window, "enabled")
        assert _visible(window) == {"alpha", "gamma"}
        assert "Showing 2 of 4" in window.source_visible_count.text()
        window.source_search.setText("Economy")
        assert _visible(window) == {"alpha"}
        assert "Showing 1 of 4" in window.source_visible_count.text()
        window.source_search.setText("not-a-publisher")
        assert not _visible(window)
        assert "Showing 0 of 4" in window.source_visible_count.text()
        actions.reset_source_filters(window)
        assert _visible(window) == {"alpha", "beta", "gamma", "website"}
    assert controller.get_setting("enabled_sources") == saved


@pytest.mark.parametrize("mode,expected", [
    ("available", {"alpha", "beta", "gamma"}),
    ("off", {"beta"}), ("unavailable", {"website"}),
    ("unchecked", {"alpha", "beta"}), ("attention", {"gamma"}),
])
def test_source_filters_distinguish_capability_collection_and_health(inventory, mode, expected):
    window, _, _ = inventory
    _mode(window, mode)
    assert _visible(window) == expected
    assert window.source_table.rowCount() == 4


def test_new_enabled_source_without_health_checkpoint_is_immediately_searchable(inventory):
    window, controller, _ = inventory
    controller.catalog.append(_source("new-provider", name="New synthetic provider", country="NZ"))
    controller.store.set_setting("enabled_sources", ["alpha", "gamma", "new-provider"])
    controller._apply_sources()
    assert controller.store.get_source_state("new-provider") == {}
    assert window._populate_sources(idle=True)
    _mode(window, "enabled")
    window.source_search.setText("NZ")
    assert _visible(window) == {"new-provider"}
    assert "Showing 1 of 5" in window.source_visible_count.text()
    row = actions._existing_source_rows(window.source_table)["new-provider"]
    assert window.source_table.item(row, 3).text() == "Not checked"


def test_same_id_metadata_changes_invalidate_search_content(inventory):
    window, controller, _ = inventory
    window.source_search.setText("AU")
    assert not _visible(window)
    controller.catalog[0]["country"] = "AU"
    assert window._populate_sources(idle=True)
    assert _visible(window) == {"alpha"}


def test_selected_source_error_recovery_updates_detail_from_same_batch(inventory):
    window, controller, _ = inventory
    row = actions._existing_source_rows(window.source_table)["alpha"]
    window.source_table.setCurrentCell(row, 0)
    assert "Not checked" in window.source_browser.toPlainText()
    controller.store.set_source_state("alpha", {
        "status": "error", "error": "<script>SYNTHETIC new failure</script>",
        "last_attempt": "2026-11-20T15:00:00Z", "last_failure": "2026-11-20T15:00:00Z",
    })
    with patch.object(controller.store, "get_source_state", side_effect=AssertionError("detail reopened Store")):
        assert window._populate_sources(idle=True)
    assert "SYNTHETIC new failure" in window.source_browser.toPlainText()
    assert "<script>" not in window.source_browser.toHtml()
    assert "Last attempted check" in window.source_browser.toPlainText()
    _mode(window, "attention")
    assert _visible(window) == {"alpha", "gamma"}
    controller.store.set_source_state("alpha", {
        "status": "available", "last_attempt": "2026-11-20T15:10:00Z",
        "last_success": "2026-11-20T15:10:00Z", "latest_publication": "2026-11-20T15:09:00Z",
    })
    with patch.object(controller.store, "get_source_state", side_effect=AssertionError("detail reopened Store")):
        assert window._populate_sources(idle=True)
    assert _visible(window) == {"gamma"}
    assert "Last check succeeded" in window.source_browser.toPlainText()
    assert "SYNTHETIC new failure" not in window.source_browser.toPlainText()


def test_sorting_cannot_move_filter_visibility_to_wrong_provider(inventory):
    window, _, _ = inventory
    window.source_search.setText("Climate")
    assert _visible(window) == {"gamma"}
    window.source_table.setSortingEnabled(True)
    window.source_table.sortItems(0, Qt.SortOrder.DescendingOrder)
    assert _visible(window) == {"gamma"}
    assert "Showing 1 of 4" in window.source_visible_count.text()


def test_explicit_toggle_updates_enabled_filter_and_count(inventory):
    window, _, _ = inventory
    _mode(window, "enabled")
    assert actions.set_enabled(window, "beta", True)
    assert _visible(window) == {"alpha", "beta", "gamma"}
    assert "3 enabled collectors" in window.source_visible_count.text()
    assert actions.set_enabled(window, "alpha", False)
    assert _visible(window) == {"beta", "gamma"}
    assert "2 enabled collectors" in window.source_visible_count.text()


def test_selected_source_enable_disable_refreshes_collection_detail_without_extra_read(inventory):
    window, controller, _ = inventory
    row = actions._existing_source_rows(window.source_table)["alpha"]
    window.source_table.setCurrentCell(row, 0)
    assert "Collection: Enabled; monitoring paused" in window.source_browser.toPlainText()
    with patch.object(controller.store, "get_source_state", side_effect=AssertionError("detail reopened Store")):
        assert actions.set_enabled(window, "alpha", False)
        assert window.source_table.item(row, 2).text() == "Off"
        assert "Collection: Off" in window.source_browser.toPlainText()
        assert "Collection: Enabled" not in window.source_browser.toPlainText()
        assert actions.set_enabled(window, "alpha", True)
        assert "Collection: Enabled; monitoring paused" in window.source_browser.toPlainText()


def test_selected_source_monitoring_transition_refreshes_detail_from_same_snapshot(inventory):
    window, controller, _ = inventory
    row = actions._existing_source_rows(window.source_table)["alpha"]
    window.source_table.setCurrentCell(row, 0)
    assert "Collection: Enabled; monitoring paused" in window.source_browser.toPlainText()
    with patch.object(controller.store, "get_source_state", side_effect=AssertionError("detail reopened Store")):
        # Only the runtime monitoring flag changes; no synthetic network poll
        # or Store health mutation should be necessary to update Collection.
        controller.monitoring = True
        assert window._populate_sources(idle=True)
        assert window.source_table.item(row, 2).text() == "Enabled"
        assert "Collection: Enabled" in window.source_browser.toPlainText()
        assert "monitoring paused" not in window.source_browser.toPlainText()
        controller.monitoring = False
        assert window._populate_sources(idle=True)
        assert "Collection: Enabled; monitoring paused" in window.source_browser.toPlainText()
        with patch.object(actions, "source_selected", side_effect=AssertionError("unchanged details rebuilt")):
            assert window._populate_sources(idle=True)


def test_batch_collector_is_visible_separately_without_new_sql_or_publisher_count(inventory, monkeypatch):
    window, controller, _ = inventory
    before_rows = window.source_table.rowCount()
    before_summary = window.source_summary.text()
    recorded = "Waiting\nLast successful check: 20 Nov 14:00 UTC\nCached rows: 1234"
    window.gdelt_controls._saved_enabled = True
    window.gdelt_controls.status_label.setText(recorded)
    with monkeypatch.context() as m:
        m.setattr(controller, "_gdelt", SimpleNamespace(active=True, process=None))
        m.setattr(controller, "gdelt_status", lambda: pytest.fail("Sources queried batch schedule"))
        m.setattr(controller, "get_setting", lambda *args: pytest.fail("Sources queried setting"))
        actions.refresh_batch_source_status(window)
        assert "GDELT 15-minute batches" in window.source_batch_status.text()
        assert "Enabled" in window.source_batch_status.text()
        assert "waiting for next allowed check" in window.source_batch_status.text()
        actions.show_batch_source_details(window)
        assert recorded in window.source_browser.toPlainText()
        assert "not additional registered publishers" in window.source_browser.toPlainText()
    assert window.source_table.rowCount() == before_rows
    assert window.source_summary.text() == before_summary


def test_batch_status_handles_startup_without_settings_widget(inventory, monkeypatch):
    window, _, _ = inventory
    with monkeypatch.context() as m:
        m.delattr(window, "gdelt_controls")
        actions.refresh_batch_source_status(window)
        assert "not yet available" in window.source_batch_status.text()
