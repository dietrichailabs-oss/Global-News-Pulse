"""Issue74 regression: selection remains explicit; deferred titles keep Qt row lifetime.

The fixtures are synthetic, local-only and run on a real Qt QWidget/ListView.
No radio, camera, media or network connections are opened.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(app,tmp_path):
    controller=Controller(tmp_path,demo=True)
    now=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    records=[{
        "id":f"gui-contract-{name}","event_key":f"gui-contract:{name}",
        "source_id":"synthetic-gui-issue74", "publisher":"QA synthetic",
        "title":f"SYNTHETIC report {name}", "summary":"Offline fixture only.",
        "published_at":now,"retrieved_at":now,
        "url":f"https://example.org/gui-contract/{name}",
        "region":"Global","country":"","category":"News",
        "severity":"unassessed","synthetic":True,
    } for name in ("alpha","beta")]
    stored=controller.store.ingest(records)
    ids={name:next(row["id"] for row in stored if name in row["title"])
         for name in ("alpha","beta")}
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


def test_deferred_title_update_keeps_exact_qt_item_and_id(desktop,monkeypatch,app):
    window,controller,ids=desktop
    target=next(window.feed_list.item(i) for i in range(window.feed_list.count())
                if window.feed_list.item(i).data(Qt.ItemDataRole.UserRole)["id"]==ids["beta"])
    before_rows=[window.feed_list.item(i) for i in range(window.feed_list.count())]
    original=controller.headline_view

    def fake_view(event, *, defer_language=False, enabled_override=None):
        # Mirror the current controller contract; this is a translated-row
        # identity test, not an assertion about language-preference lookups.
        view=dict(original(event,defer_language=defer_language,
                           enabled_override=enabled_override))
        if str(event.get("id"))==ids["beta"]:
            view["title"]="Translated synthetic beta"
            view["label"]="Synthetic local translation"
        return view

    monkeypatch.setattr(controller,"headline_view",fake_view)
    window._refresh_translated_headlines()
    app.processEvents()
    assert window.feed_list.count()==len(before_rows)
    assert all(window.feed_list.item(i) is before_rows[i] for i in range(len(before_rows)))
    assert target.text()=="Translated synthetic beta"
    assert target.data(Qt.ItemDataRole.UserRole)["id"]==ids["beta"]
    assert window.world_map is not None


def test_explicit_deselection_survives_deferred_language_repaint(desktop,app):
    window,controller,ids=desktop
    window.navigate_event(ids["alpha"])
    assert window.feed_list.currentItem() is not None
    window.feed_list.setCurrentRow(-1)
    app.processEvents()
    assert window._feed_explicitly_cleared
    assert window._selected_id==""
    assert window.feed_list.currentItem() is None
    window._refresh_translated_headlines()
    app.processEvents()
    assert window.feed_list.currentItem() is None
    assert window._selected_id==""
    assert window.save_button.property("event_id")==""
    assert not window.save_button.isEnabled()
    # Passive filter/collector repaint must also preserve explicit deselection.
    window.refresh_data()
    app.processEvents()
    assert window.feed_list.currentItem() is None
    assert window._selected_id==""
    # Choosing an item is an explicit consent to resume source selection.
    window.feed_list.setCurrentRow(0)
    app.processEvents()
    assert window._selected_id


def test_selected_event_layout_can_shrink_to_20_percent(desktop,app):
    window,controller,ids=desktop
    window.navigate_event(ids["alpha"])
    for width,height in ((1440,940),(1280,800),(960,640)):
        window.resize(width,height)
        app.processEvents()
        window.intelligence_mode.setCurrentIndex(1)
        app.processEvents()
        split=window.lower_split.sizes()
        assert sum(split)>0
        assert split[2]/sum(split)<.25,split
        assert window.intel_scroll.viewport().height()>0
    window.intelligence_mode.setCurrentIndex(0)
    assert window.overview_browser.isVisible()
