"""QA-only adversarial checks on frozen PR46 source, not a product modification.

Offline invented publisher fixtures. Passing here cannot certify a physical
Windows 11 rapid-click soak, publisher rights or actual crisis geometry.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QListWidget, QLineEdit

from global_pulse.map_widget import WorldMap


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def world(app):
    widget = WorldMap()
    widget.resize(1600, 680)
    widget.show()
    app.processEvents()
    yield widget
    if widget.country_dialog:
        widget.country_dialog.close()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def record(identity, category, country="United States of America", basis="explicit_record", location=False):
    t = datetime.now(timezone.utc).isoformat()
    report = {"id": identity + "-r", "source_id": "offline-" + identity,
              "title": "OFFLINE " + identity, "country": country,
              "country_basis": basis, "category": category,
              "published_at": t, "publication_time_known": True,
              "evidence_status": "active", "official": False}
    return {"id": identity, "title": "OFFLINE " + identity,
            "category": category, "status": "active", "synthetic": False,
            "latitude": 40.0 if location else None,
            "longitude": -95.0 if location else None,
            "map_areas": [], "reports": [report]}


def hits(world, category):
    world.grab()
    return [row for row in world._country_badge_hits
            if row[2] == "United States of America" and row[3] == category]


def test_qa_case_normalized_health_filter_with_64_disasters_and_search_all(world, app):
    storms = [record(f"Storm {n}", "Disaster") for n in range(64)]
    clinic = record("Clinic", " hEaLtH ")
    world.set_events([], country_events=storms + [clinic])
    world.categories = {"  health "}
    health_hits = hits(world, "Health")
    assert len(health_hits) == 1
    assert not hits(world, "Disaster")
    assert world.country_category_evidence_for("USA")["count"] == 1

    # With All enabled, a click on the Health ring must not show 30 storms.
    world.categories = None
    health_hits = hits(world, "Health")
    QTest.mouseClick(world, Qt.MouseButton.LeftButton, pos=health_hits[0][0].toPoint())
    app.processEvents()
    dlg = world.country_dialog
    assert dlg is not None
    categories = dlg.findChild(QComboBox, "country_evidence_categories")
    listing = dlg.findChild(QListWidget, "country_evidence_results")
    search = dlg.findChild(QLineEdit, "country_evidence_search")
    assert categories.currentData() == "Health"
    assert listing.count() == 1 and "Clinic" in listing.item(0).text()
    categories.setCurrentIndex(0)
    search.setText("Storm 63")
    app.processEvents()
    assert listing.count() == 1
    assert "Storm 63" in listing.item(0).text()


def test_qa_case_no_publisher_only_health_country_and_no_guessing_coordinates(world):
    eligible = record("Clinic", "health")
    publisher = record("HQ only", "Health", "Ukraine", basis="publisher_coverage")
    ambiguous = record("Two countries mentioned", "HEALTH", country="", basis="")
    world.set_events([], country_events=[eligible, publisher, ambiguous])
    world.categories = {"HEALTH"}
    assert len(hits(world, "Health")) == 1
    assert not any(h[2] == "Ukraine" for h in world._country_badge_hits)
    assert len(world.visible_clusters()) == 0
    assert "0 points" in world.coverage_summary()


def test_qa_case_saved_lowercase_filter_preserves_real_point_but_not_disaster(world):
    confirmed_geo = record("Physical incident fixture", "HEALTH", location=True)
    unrelated = record("Separate storm", "DISASTER")
    world.set_events([confirmed_geo], country_events=[confirmed_geo, unrelated])
    world.restore_view({"categories": ["health"]})
    assert len(hits(world, "Health")) == 1
    assert len(world.visible_clusters()) == 1
    assert "1 points" in world.coverage_summary()
    world.restore_view({"categories": ["disaster"]})
    assert len(hits(world, "Disaster")) == 1
    assert not hits(world, "Health")
    assert len(world.visible_clusters()) == 0
