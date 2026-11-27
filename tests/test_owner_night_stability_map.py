"""Owner map/startup integration: honest country-category circle rendering.

Offline synthetic source records only. No live/independent location claims.
"""
from __future__ import annotations
import inspect
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QListWidget, QLabel

from global_pulse.map_widget import WorldMap, CATEGORY_COLORS
from global_pulse.__main__ import show_initializing


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _record(identity, title, category, *, country="United States of America",
            basis="provider_incident"):
    now=datetime.now(timezone.utc).isoformat()
    report={
        "id":identity + "-report", "source_id":"test-publisher-" + identity,
        "title":title,"country":country,"country_basis":basis,
        "published_at":now,"publication_time_known":True,
        "evidence_status":"active","official":False,"category":category,
    }
    return {
        "id":identity,"title":title,"country":country,
        "country_basis":basis,"category":category,"status":"active",
        "synthetic":False,"latitude":None,"longitude":None,
        "map_areas":[],"reports":[report],
    }


@pytest.fixture
def map_widget(app):
    world=WorldMap()
    world.resize(1600,680)
    world.show()
    app.processEvents()
    yield world
    if world.country_dialog:
        world.country_dialog.close()
    world.close()
    world.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def _render(world):
    image=QPixmap(world.width(),world.height())
    image.fill(Qt.GlobalColor.transparent)
    world.render(image)
    return image.toImage()


def test_all_source_categories_get_distinct_circles_not_only_disaster(map_widget):
    categories=(
        ("Government","Regulatory policy notice"),
        ("Economy","Quarterly statistical data release"),
        ("Health","Hospital services announcement"),
        ("Humanitarian","Food support program bulletin"),
        ("Infrastructure","Transport engineering update"),
        ("News","Local public information notice"),
        ("Disaster","Flood watch with no exact affected-zone coordinates"),
    )
    rows=[_record(f"category-{i}",title,category)
          for i,(category,title) in enumerate(categories)]
    map_widget.set_events([],country_events=rows)
    picture=_render(map_widget)
    usa=[hit for hit in map_widget._country_badge_hits
         if hit[2]=="United States of America"]
    assert {hit[3] for hit in usa}=={c for c,_ in categories}
    assert len({CATEGORY_COLORS[h[3]] for h in usa})==len(categories)
    assert "0 points" in map_widget.coverage_summary()
    assert map_widget.visible_clusters()==[]
    for center,_,_,category,_ in usa:
        color=picture.pixelColor(int(center.x()),int(center.y()))
        assert color.alpha()>0, category
    map_widget.categories={"Health"}
    _render(map_widget)
    usa=[hit for hit in map_widget._country_badge_hits
         if hit[2]=="United States of America"]
    assert {hit[3] for hit in usa}=={"Health"}


def test_country_circle_click_opens_country_source_evidence(map_widget,app):
    map_widget.set_events([],country_events=[
        _record("gov","Government press announcement","Government")])
    _render(map_widget)
    hit=next(h for h in map_widget._country_badge_hits if h[3]=="Government")
    selected=[]
    map_widget.country_selected.connect(selected.append)
    point=QPoint(round(hit[0].x()),round(hit[0].y()))
    QTest.mouseClick(map_widget,Qt.MouseButton.LeftButton,pos=point)
    app.processEvents()
    assert selected==["United States of America"]
    assert map_widget.country_dialog is not None


def test_publisher_geography_alone_never_creates_country_circle(map_widget):
    record=_record("unlocated","Routine publisher press notice","Government",
                   basis="publisher_coverage")
    map_widget.set_events([],country_events=[record])
    _render(map_widget)
    assert not map_widget._country_badge_hits
    assert "0 points" in map_widget.coverage_summary()


def test_dated_economic_observation_has_country_circle_not_crisis(map_widget):
    map_widget.set_events([],country_events=[],observations=[{
        "country_name":"United States of America","country_code":"USA",
        "indicator_name":"GDP growth","observation_date":"2025",
        "value":1.0
    }])
    _render(map_widget)
    usa=[h for h in map_widget._country_badge_hits
         if h[2]=="United States of America"]
    assert len(usa)==1 and usa[0][3]=="Economy"
    assert "dated economic observation" in usa[0][4]
    assert "0 points" in map_widget.coverage_summary()
    assert not map_widget.country_activity



def test_observation_only_economy_badge_opens_dated_data_not_empty_country_dialog(map_widget, app):
    map_widget.set_events([], country_events=[], observations=[{
        "country_name": "United States of America", "country_code": "USA",
        "indicator_name": "GDP growth", "observation_date": "2025", "value": 1.0,
    }])
    _render(map_widget)
    economic = [hit for hit in map_widget._country_badge_hits if hit[3] == "Economy"]
    assert len(economic) == 1
    selected = []
    map_widget.economic_country_requested.connect(selected.append)
    point = QPoint(round(economic[0][0].x()), round(economic[0][0].y()))
    QTest.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()
    assert selected == ["United States of America"]
    assert map_widget.country_dialog is None


def test_current_official_conflict_has_country_category_circle_without_neutral_double_count(map_widget, app):
    """Fresh official source evidence must not disappear from the Conflict layer."""
    row = _record("current-conflict", "Armed clashes and shelling reported", "Conflict",
                  country="Ukraine")
    row["reports"][0]["official"] = True
    map_widget.set_events([], country_events=[row])
    _render(map_widget)
    assert map_widget.country_activity_for("Ukraine").get("conflict") == 1
    assert map_widget.country_evidence_for("Ukraine") == {}
    assert "0 country-only records" in map_widget.coverage_summary()
    hits = [hit for hit in map_widget._country_badge_hits
            if hit[2] == "Ukraine" and hit[3] == "Conflict"]
    assert len(hits) == 1
    assert map_widget.visible_clusters() == []
    point = QPoint(round(hits[0][0].x()), round(hits[0][0].y()))
    QTest.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()
    dialog = map_widget.country_dialog
    assert dialog is not None
    assert "Country-attributed" in dialog.windowTitle()
    listing = dialog.findChild(QListWidget, "country_evidence_results")
    assert listing is not None and listing.count() == 1
    assert "Armed clashes" in listing.item(0).text()


def test_real_incident_point_and_country_category_circle_remain_distinct(map_widget):
    """An actual provider coordinate is a point; a separate ring is a country summary."""
    row = _record("provider-point", "Official conflict report", "Conflict",
                  country="Ukraine")
    row["reports"][0]["official"] = True
    row["latitude"], row["longitude"] = 49.0, 32.0
    map_widget.set_events([row], country_events=[row])
    _render(map_widget)
    assert len(map_widget.visible_clusters()) == 1
    assert any(hit[2] == "Ukraine" and hit[3] == "Conflict"
               for hit in map_widget._country_badge_hits)
    assert map_widget.country_evidence_for("Ukraine") == {}
    assert map_widget.country_category_evidence_for("Ukraine")["count"] == 1


def test_official_pin_is_double_circular_ring_never_square_frame():
    method=inspect.getsource(WorldMap.paintEvent)
    assert "if verification == \"official\"" in method
    assert "painter.drawRect(QRectF(center" not in method
    assert "painter.drawEllipse(center, radius+5, radius+5)" in method


def test_initializing_notice_survives_clicks_before_window_ready(app):
    splash=show_initializing(app)
    try:
        assert splash.isVisible()
        assert "INITIALIZING" in splash.message()
        QTest.mouseClick(splash,Qt.MouseButton.LeftButton,pos=QPoint(10,10))
        app.processEvents()
        assert splash.isVisible()
    finally:
        splash.close()
        splash.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_category_circle_opens_matching_sources_not_first_thirty_weather(map_widget, app):
    """A Health ring amid 42 disaster records must show Health first, not storms."""
    rows = [_record(f"storm-{i}", f"Storm number {i}", "Disaster")
            for i in range(42)]
    rows.append(_record("hospital", "Hospital services notice", "Health"))
    map_widget.set_events([], country_events=rows)
    _render(map_widget)

    health = [hit for hit in map_widget._country_badge_hits
              if hit[2] == "United States of America" and hit[3] == "Health"]
    assert len(health) == 1
    point = QPoint(round(health[0][0].x()), round(health[0][0].y()))
    QTest.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()

    dialog = map_widget.country_dialog
    assert dialog is not None
    combo = dialog.findChild(QComboBox, "country_evidence_categories")
    listing = dialog.findChild(QListWidget, "country_evidence_results")
    search = dialog.findChild(QLineEdit, "country_evidence_search")
    count = dialog.findChild(QLabel, "country_evidence_count")
    assert combo and listing and search and count
    assert combo.currentData() == "Health"
    assert listing.count() == 1
    assert "Hospital services notice" in listing.item(0).text()
    assert "43 total" in count.text()

    # Explicitly choosing All must restore broad country search, including
    # a title past the initial 30 visible weather entries.
    combo.setCurrentIndex(0)
    app.processEvents()
    assert listing.count() == 30
    assert "Showing 30 of 43" in count.text()
    search.setText("Storm number 41")
    app.processEvents()
    assert listing.count() == 1
    assert "Storm number 41" in listing.item(0).text()


def test_normalized_category_ring_drills_into_original_lowercase_source(map_widget, app):
    """A source category alias in lower case must remain discoverable."""
    row = _record("lowercase-health", "Clinic capacity statement", "health")
    map_widget.set_events([], country_events=[row])
    _render(map_widget)
    hit = next(hit for hit in map_widget._country_badge_hits
               if hit[3] == "Health")
    QTest.mouseClick(map_widget, Qt.MouseButton.LeftButton,
                     pos=QPoint(round(hit[0].x()), round(hit[0].y())))
    app.processEvents()
    dialog = map_widget.country_dialog
    combo = dialog.findChild(QComboBox, "country_evidence_categories")
    listing = dialog.findChild(QListWidget, "country_evidence_results")
    assert combo.currentData() == "Health"
    assert listing.count() == 1
    assert "Clinic capacity statement" in listing.item(0).text()
