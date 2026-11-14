"""QA-only adversarial checks of owner-night stability/map candidate.

Frozen product ancestor 404c2cc60a884d10a5191d313b5f08f9f2199c52.
No product/runtime edits, third-party network access or physical GUI claims.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.map_widget import WorldMap, CATEGORY_COLORS
from global_pulse.ui import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def row(identity, title, category, country, *, basis):
    at=datetime.now(timezone.utc).isoformat()
    return {
        "id":identity,"title":title,"category":category,
        "status":"active","synthetic":False,"longitude":None,
        "latitude":None,"map_areas":[],"reports":[{
            "id":identity+"-report","source_id":"qa-source-"+identity,
            "title":title,"category":category,"country":country,
            "country_basis":basis,"evidence_status":"active",
            "publication_time_known":True,"published_at":at,
            "official":False,
        }],
    }


def test_no_publisher_only_or_multi_country_guessing_of_political_points(app):
    world=WorldMap()
    world.resize(1600,700)
    world.show()
    app.processEvents()
    try:
        records=[
            row("false","Routine publisher announcement","Government",
                "Ukraine",basis="publisher_coverage"),
            row("ambiguous","Ukraine and Russia discuss new notice","Government",
                "",basis=""),
            row("genuine","Official statement concerning Ukraine","Government",
                "Ukraine",basis="provider_incident"),
        ]
        world.set_events([],country_events=records)
        world.grab()
        circles=[h for h in world._country_badge_hits
                 if h[2]=="Ukraine" and h[3]=="Government"]
        assert len(circles)==1
        assert world.country_evidence_for("Ukraine")["count"]==1
        assert world.visible_clusters()==[]
        assert "0 points" in world.coverage_summary()
        assert not world.country_activity
        assert "Government" in CATEGORY_COLORS
    finally:
        world.close()
        world.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_report_category_filter_never_broadens_to_other_country_badges(app):
    world=WorldMap()
    world.resize(1600,700)
    world.show()
    app.processEvents()
    categories=["Economy","Health","Infrastructure","Government","Humanitarian","News"]
    rows=[row("f"+str(i),"Official publication "+str(i),cat,
              "United States of America",basis="explicit_record")
          for i,cat in enumerate(categories)]
    try:
        world.set_events([],country_events=rows)
        world.grab()
        all_cats={h[3] for h in world._country_badge_hits
                  if h[2]=="United States of America"}
        assert all_cats==set(categories)
        for category in categories:
            world.categories={category}
            world.grab()
            shown={h[3] for h in world._country_badge_hits
                   if h[2]=="United States of America"}
            assert shown=={category}
            assert "0 points" in world.coverage_summary()
    finally:
        world.close()
        world.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.fixture
def desktop(app,tmp_path):
    controller=Controller(tmp_path,demo=True)
    at=datetime.now(timezone.utc).isoformat()
    record={
        "id":"QA-STABLE-STAR","source_id":"qa-offline-source",
        "publisher":"QA offline fixture","title":"SYNTHETIC owner UI stability",
        "summary":"Synthetic event, no physical crisis",
        "url":"https://example.org/qa-stability", "event_key":"qa-stability:event",
        "published_at":at,"retrieved_at":at,
        "category":"News","country":"","region":"Global",
        "synthetic":True,"severity":"unassessed",
    }
    event=controller.store.ingest([record])[0]
    window=MainWindow(controller)
    window.show()
    app.processEvents()
    window.navigate_event(event["id"])
    app.processEvents()
    yield window,controller,event["id"]
    window._force_close=True
    window.close()
    controller.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_rapid_star_tab_and_status_bursts_do_not_rebuild_map(desktop,app,monkeypatch):
    window,controller,identity=desktop
    calls=[]
    def prohibited(*a,**k):
        calls.append("unwanted full map rebuild")
        raise AssertionError("UI action rebuilt map source evidence")
    monkeypatch.setattr(window.world_map,"set_events",prohibited)
    controller.last_collection="2026-11-13T19:00:00Z"
    started=time.monotonic()
    for index in range(30):
        window.open_page(0)
        window.save_button.click()
        window.open_page(1)
        window.open_page(0)
        controller.source_status_changed.emit()
        if index%5==0:
            app.processEvents()
    QTest.qWait(700)
    app.processEvents()
    assert not calls
    assert not controller.store.saved_situation_ids()
    assert window.save_button.text()=="☆ Star"
    assert "13 Nov 19:00" in window.last_label.text()
    assert time.monotonic()-started < 30.0


def test_source_health_update_on_hidden_sources_tab_defers_expensive_repaint(desktop,app,monkeypatch):
    window,controller,_=desktop
    window.open_page(0)
    calls=[]
    def counted(*a,**k):
        calls.append("source-table")
    monkeypatch.setattr(window,"_populate_sources",counted)
    for _ in range(50):
        controller.source_status_changed.emit()
    QTest.qWait(700)
    assert not calls
    window.open_page(3)
    assert calls==["source-table"]
    for _ in range(20):
        window.open_page(3)
    assert calls==["source-table"]
