"""QA-only offscreen negative cases for country Economy click routing.

This branch does not change the product. Offline fabricated records exercise
source-versus-dated-observation separation, not real incident geography.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from global_pulse.map_widget import WorldMap


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def world(app):
    widget = WorldMap()
    widget.resize(1600, 700)
    widget.show()
    app.processEvents()
    yield widget
    if widget.country_dialog:
        widget.country_dialog.close()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def record(identity, category):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": identity, "title": "QA invented source bulletin",
        "category": category, "synthetic": False,
        "latitude": None, "longitude": None, "map_areas": [],
        "reports": [{
            "id": identity + "-report", "source_id": "qa-source",
            "title": "QA invented source bulletin",
            "country": "United States of America",
            "country_basis": "explicit_record", "category": category,
            "published_at": now, "publication_time_known": True,
            "evidence_status": "active", "official": False,
        }],
    }


def observation():
    return {
        "country_name": "United States of America", "country_code": "USA",
        "indicator_name": "GDP (test only)", "observation_date": "2025",
        "value": 1.0,
    }


def click_category(world, app, category):
    world.grab()
    hits = [hit for hit in world._country_badge_hits
            if hit[2] == "United States of America" and hit[3] == category]
    assert len(hits) == 1
    QTest.mouseClick(world, Qt.MouseButton.LeftButton, pos=hits[0][0].toPoint())
    app.processEvents()


def test_economy_observation_circle_with_other_category_news_uses_economy_navigation(world, app):
    world.set_events([], country_events=[record("qa-government", "Government")],
                     observations=[observation()])
    emitted = []
    world.economic_country_requested.connect(emitted.append)
    click_category(world, app, "Economy")
    assert emitted == ["United States of America"]
    assert world.country_dialog is None
    assert world.visible_clusters() == []  # No fabricated incident points.


def test_economy_source_event_circle_still_opens_country_evidence_dialog(world, app):
    world.set_events([], country_events=[record("qa-economy", "Economy")],
                     observations=[observation()])
    emitted = []
    world.economic_country_requested.connect(emitted.append)
    click_category(world, app, "Economy")
    assert emitted == []
    assert world.country_dialog is not None
    assert "Economy" in world.country_dialog.windowTitle() or "Country-only" in world.country_dialog.windowTitle()
