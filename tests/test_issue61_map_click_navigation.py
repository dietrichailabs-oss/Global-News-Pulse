"""Regression for owner screenshot: first map click must not queue full reloads.

Uses real synthetic SQLite Store, Controller and PySide6 MainWindow without
network access; never treats synthetic events as live incidents.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(app,tmp_path):
    controller=Controller(tmp_path,demo=True)
    at=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    events=controller.store.ingest([{
        "id":f"qa-map-{name}","source_id":"qa-offline-map-click",
        "publisher":"QA SYNTHETIC","title":f"SYNTHETIC map report {name}",
        "summary":"No real incident or location",
        "url":f"https://example.org/map/{name}",
        "event_key":f"qa-map-click:{name}",
        "published_at":at,"retrieved_at":at,
        "category":"News","region":"Global","synthetic":True,
        "severity":"unassessed",
    } for name in ("alpha","bravo")])
    ids={name:next(e["id"] for e in events if name in e["title"])
         for name in ("alpha","bravo")}
    window=MainWindow(controller)
    window.show()
    app.processEvents()
    yield window,controller,ids
    window._force_close=True
    window.close()
    controller.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_visible_map_event_click_only_updates_one_row_and_brief(desktop,app,monkeypatch):
    window,controller,ids=desktop
    window.navigate_event(ids["alpha"])
    map_calls=[]
    feed_calls=[]
    original_map=window.world_map.set_events
    original_feed=window._populate_feed
    monkeypatch.setattr(window.world_map,"set_events",lambda *a,**k:(map_calls.append(1),original_map(*a,**k)))
    monkeypatch.setattr(window,"_populate_feed",lambda *a,**k:(feed_calls.append(1),original_feed(*a,**k)))

    # Emitting the same signal as a real WorldMap point selection.
    window.world_map.event_selected.emit(ids["bravo"])
    assert not map_calls and not feed_calls
    assert window._selected_id==ids["bravo"]
    assert window.feed_list.currentItem().data(Qt.ItemDataRole.UserRole)["id"]==ids["bravo"]
    assert window.save_button.property("event_id")==ids["bravo"]
    assert "bravo" in window.intel_browser.toPlainText().lower()


def test_hidden_event_map_click_clears_filters_atomically_one_refresh(desktop,app,monkeypatch):
    window,controller,ids=desktop
    window.search.setText("no-such-incident")
    window.refresh_data()
    window.search_timer.stop()
    assert window.feed_list.count()==0
    calls=[]
    original=window.world_map.set_events
    def counted(*a,**k):
        calls.append("map")
        return original(*a,**k)
    monkeypatch.setattr(window.world_map,"set_events",counted)

    window.world_map.event_selected.emit(ids["bravo"])
    assert calls==["map"]
    assert window.search.text()==""
    assert window.time_range.currentIndex()==3
    assert window.history_slider.value()==1000
    assert window._selected_id==ids["bravo"]
    assert window.save_button.property("event_id")==ids["bravo"]
    assert "bravo" in window.intel_browser.toPlainText().lower()
    QTest.qWait(230)
    app.processEvents()
    # A pending search debouncer must not cause a second full map rebuild.
    assert calls==["map"]


def test_map_selection_after_historical_replay_uses_one_current_refresh(desktop,app,monkeypatch):
    window,controller,ids=desktop
    window.navigate_event(ids["alpha"])
    window.time_range.setCurrentIndex(3)
    window.history_slider.setValue(0)
    assert window.history_slider.value()==0
    calls=[]
    orig=window.world_map.set_events
    monkeypatch.setattr(window.world_map,"set_events",
                        lambda *a,**k:(calls.append(True),orig(*a,**k)))
    window.world_map.event_selected.emit(ids["alpha"])
    assert calls==[True]
    assert window.history_slider.value()==1000
    assert window._selected_id==ids["alpha"]
    assert window.save_button.property("event_id")==ids["alpha"]
