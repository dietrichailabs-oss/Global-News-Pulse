"""Issue #22: a filtered-out event must not remain the Brief/Star target.

Real offscreen Qt + Controller + SQLite Store; all events synthetic and local.
No network, media playback, live crisis claims, or independent-QA assertion.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(tmp_path, app):
    controller = Controller(tmp_path, demo=True)
    now = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    items = []
    for identity in ("orionpattern", "zeuspattern"):
        items.append({
            "id": "filter-selection-" + identity,
            "source_id": "synthetic-filter-source",
            "publisher": "OFFLINE FILTER TEST",
            "title": "SYNTHETIC " + identity + " report",
            "summary": "No real event or claim",
            "url": "https://example.org/filter/" + identity,
            "event_key": "filter-selection:" + identity,
            "published_at": now, "retrieved_at": now,
            "category": "News", "region": "Global",
            "country": "", "severity": "unassessed", "synthetic": True,
        })
    events = controller.store.ingest(items)
    assert len(events) == 2
    ids = {identity: next(event["id"] for event in events if identity in event["title"])
           for identity in ("orionpattern", "zeuspattern")}
    window = MainWindow(controller)
    window.show()
    app.processEvents()
    window.navigate_event(ids["orionpattern"])
    app.processEvents()
    yield window, controller, ids
    window._force_close = True
    window.close()
    controller.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_search_rebinds_visible_brief_and_persisted_star(desktop, app):
    window, controller, ids = desktop
    assert window._selected_id == ids["orionpattern"]
    assert window.save_button.property("event_id") == ids["orionpattern"]

    # A source-filter change hides Orion but leaves its evidence in SQLite.
    # The Brief and Star action must instead refer to the visible Zeus result.
    window.search.setText("zeuspattern")
    window.refresh_data()
    app.processEvents()
    assert window.feed_list.count() == 1
    active = window.feed_list.currentItem()
    assert active is not None
    assert active.data(Qt.ItemDataRole.UserRole)["id"] == ids["zeuspattern"]
    assert window._selected_id == ids["zeuspattern"]
    assert window.save_button.property("event_id") == ids["zeuspattern"]
    assert "zeuspattern" in window.intel_browser.toPlainText().lower()

    window.save_button.click()
    app.processEvents()
    assert controller.store.saved_situation_ids() == {ids["zeuspattern"]}
    assert controller.event(ids["orionpattern"]) is not None


def test_zero_result_filter_clears_all_stale_star_targets(desktop, app):
    window, controller, ids = desktop
    window.search.setText("unmatchablefilterword")
    window.refresh_data()
    app.processEvents()
    assert window.feed_list.count() == 0
    assert window._selected_id == ""
    assert window.save_button.property("event_id") == ""
    assert not window.save_button.isEnabled()
    assert not controller.store.saved_situation_ids()
    assert all(controller.event(value) is not None for value in ids.values())


def test_explicit_feed_deselection_clears_brief_without_deleting_evidence(desktop, app):
    window, controller, ids = desktop
    assert window.feed_list.currentItem() is not None
    window.feed_list.setCurrentRow(-1)
    app.processEvents()
    assert window.feed_list.currentItem() is None
    assert window._selected_id == ""
    assert window.save_button.property("event_id") == ""
    assert not window.save_button.isEnabled()
    assert not controller.store.saved_situation_ids()
    assert controller.event(ids["orionpattern"]) is not None
