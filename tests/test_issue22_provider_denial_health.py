"""Issue #22: provider failure state must survive Collector -> SQLite -> desktop.

All HTTP replies are in-memory MockTransport; no provider contacted.
These are Engineering regressions, not independent QA or physical Windows11 tests.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.sources import Collector
from global_pulse.source_availability import health_text
from global_pulse.ui import MainWindow

NOW = datetime(2026, 11, 12, 7, 0, tzinfo=timezone.utc)


def sample_source():
    return {
        "id": "synthetic-publisher", "name": "Offline test publisher",
        "url": "https://feed.example.org/rss",
        "homepage": "https://publisher.example.org/",
        "allowed_domains": ["feed.example.org"],
        "adapter": "rss", "enabled": True,
        "access_status": "reviewed_public", "status": "not_checked",
        "min_interval": 600, "category": "News", "region": "Global",
    }


@pytest.mark.parametrize("status, expected", [
    ("denied", "Provider denied access; retry deferred"),
    ("unavailable", "Provider temporarily unavailable; retry scheduled"),
    ("rate_limited", "Rate limited; waiting for provider retry"),
    ("error", "Last check failed"),
])
def test_failed_attempt_overrides_old_success_and_stale_evidence(status, expected):
    state = {
        "status": status,
        "last_success": "2026-11-01T00:00:00Z",
        "latest_publication": "2026-10-01T00:00:00Z",
        "freshness": "stale",
        "last_failure": "2026-11-12T07:00:00Z",
        "next_poll": "2026-11-13T07:00:00Z",
    }
    assert health_text(state) == expected
    assert health_text(state) != "Not checked"
    assert "stale" not in health_text(state).lower()


@pytest.mark.parametrize("http_status, expected", [
    (403, "Provider denied access; retry deferred"),
    (503, "Provider temporarily unavailable; retry scheduled"),
])
def test_denial_reaches_reopened_archive_source_registry_and_settings(tmp_path, http_status, expected):
    source = sample_source()
    seen = []

    def client_factory(**kwargs):
        def response(request):
            seen.append(str(request.url))
            return httpx.Response(http_status, request=request,
                                  headers={"Retry-After": "7200"})
        return httpx.Client(transport=httpx.MockTransport(response), **kwargs)

    previous = {
        "last_success": "2026-11-01T00:00:00Z",
        "latest_publication": "2026-10-01T00:00:00Z",
        "freshness": "stale",
    }
    result = Collector(source, client_factory=client_factory, now=lambda: NOW).collect(previous)
    state = result["state"]
    assert seen == ["https://feed.example.org/rss"]
    assert result["reports"] == [] and result["observations"] == []
    assert state["last_success"] == previous["last_success"]
    assert state["status"] == ("denied" if http_status == 403 else "unavailable")
    assert state["next_poll"] and state["last_failure"]
    assert health_text(state) == expected

    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        controller.catalog = [source]
        controller._apply_sources()
        controller.store.set_source_state(source["id"], state)
        # Actual persisted SQLite round-trip, not merely rendering a dict.
        from global_pulse.core import Store
        with Store(controller.store.path) as reopened:
            recovered = reopened.get_source_state(source["id"])
        assert recovered["status"] == state["status"]
        assert recovered["next_poll"] == state["next_poll"]
        assert health_text(recovered) == expected

        window = MainWindow(controller)
        window.show()
        window.open_page(3)
        app.processEvents()
        assert window.source_table.rowCount() == 1
        assert window.source_table.item(0, 3).text() == expected
        assert window.source_table.item(0, 6).text() != "—"
        window.source_table.selectRow(0)
        window._source_selected()
        assert expected in window.source_browser.toPlainText()
        window._populate_source_preferences()
        assert window.source_preferences.item(0, 4).text() == expected
    finally:
        if window is not None:
            window._force_close = True
            window.close()
            window.deleteLater()
        controller.close()
        app.processEvents()
