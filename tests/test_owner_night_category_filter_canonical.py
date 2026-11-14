"""Map category controls must not hide canonically named attributed sources.

Synthetic fixture data only; no claim of a real Health or Disaster event.
Regression scope: categories used for country rings, filter counts, and actual
provider-justified map point clusters must match despite source case/spacing.
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import Qt, QPoint, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QListWidget

from global_pulse.map_widget import WorldMap


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def world(app):
    item = WorldMap()
    item.resize(1600, 680)
    item.show()
    app.processEvents()
    yield item
    if item.country_dialog:
        item.country_dialog.close()
    item.close()
    item.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def source_record(identity, category, *, basis="provider_incident", point=False):
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "id": identity + "-report", "source_id": "offline-qa-" + identity,
        "title": "SYNTHETIC " + identity, "country": "United States of America",
        "country_basis": basis, "published_at": now, "publication_time_known": True,
        "evidence_status": "active", "official": False, "category": category,
    }
    return {
        "id": identity, "title": "SYNTHETIC " + identity,
        "category": category, "status": "active", "synthetic": False,
        "latitude": 39.0 if point else None, "longitude": -97.0 if point else None,
        "map_areas": [], "reports": [report],
    }


def render(world):
    # grab() drives the same geometry/hit recording as actual paintEvent.
    world.grab()


def badges(world):
    return [h for h in world._country_badge_hits
            if h[2] == "United States of America"]


def test_health_filter_keeps_lowercase_country_ring_and_uppercase_real_point(world):
    lower = source_record("clinic-news", "health")
    upper_point = source_record("verified-location", "HEALTH", point=True)
    unrelated = source_record("flood-news", "Disaster")
    world.set_events([upper_point], country_events=[lower, upper_point, unrelated])
    world.categories = {"Health"}
    render(world)
    assert {h[3] for h in badges(world)} == {"Health"}
    assert world.country_category_evidence_for("United States of America")["count"] == 2
    assert len(world.visible_clusters()) == 1
    assert "1 points" in world.coverage_summary()
    assert "3 reports assessed" in world.coverage_summary()


def test_lowercase_saved_filter_name_matches_canonical_ring_and_dialog(world, app):
    lower = source_record("clinic", " health ")
    unrelated = source_record("storm", "Disaster")
    world.set_events([], country_events=[lower, unrelated])
    world.restore_view({"categories": ["health"], "labels": True})
    render(world)
    hits = badges(world)
    assert len(hits) == 1 and hits[0][3] == "Health"
    QTest.mouseClick(world, Qt.MouseButton.LeftButton,
                     pos=QPoint(round(hits[0][0].x()), round(hits[0][0].y())))
    app.processEvents()
    dialog = world.country_dialog
    assert dialog is not None
    combo = dialog.findChild(QComboBox, "country_evidence_categories")
    listing = dialog.findChild(QListWidget, "country_evidence_results")
    assert combo.currentData() == "Health"
    assert listing.count() == 1
    assert "SYNTHETIC clinic" in listing.item(0).text()


def test_filter_toggle_reveals_only_matching_attributed_source_and_no_fake_points(world):
    health = source_record("health", "hEaLtH")
    flood = source_record("disaster", "Disaster")
    publisher_only = source_record("unattributed", "Health", basis="publisher_coverage")
    world.set_events([], country_events=[health, flood, publisher_only])
    for selection, expected in (
        ({"Health"}, {"Health"}),
        ({"disaster"}, {"Disaster"}),
        ({"News"}, set()),
        (None, {"Health", "Disaster"}),
    ):
        world.categories = selection
        render(world)
        assert {h[3] for h in badges(world)} == expected
        assert world.visible_clusters() == []
        assert "0 points" in world.coverage_summary()
