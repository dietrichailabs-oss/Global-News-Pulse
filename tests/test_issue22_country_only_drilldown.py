"""Engineering fixtures: country-only archive evidence must be inspectable without invented pins.

Offline records are inert and are not verification of live events or of a real
Windows 11 user session. The crisis overlay's independent QA remains distinct.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone
import pytest
from PySide6.QtWidgets import QApplication, QListWidget

from global_pulse.core import Store
from global_pulse.map_widget import WorldMap

APP = None


@pytest.fixture(scope="module")
def app():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


@pytest.fixture
def world(app):
    instance = WorldMap()
    instance.resize(1020, 520)
    yield instance
    if instance.country_dialog:
        instance.country_dialog.close()
    instance.close()
    app.processEvents()


def evidence(identity="health-1", country="Ukraine", basis="provider_incident",
             category="Health", published_at="2026-09-01T12:00:00Z",
             status="active", synthetic=False, source_time_known=True):
    return {
        "id": identity, "title": "TEST: routine public health information",
        "country": country, "country_basis": basis, "category": category,
        "status": status, "synthetic": synthetic,
        "latitude": None, "longitude": None, "map_areas": [],
        "updated_at": "2026-11-11T15:00:00Z",
        "reports": [{
            "id": identity + "-source", "source_id": "explicit-source",
            "country": country, "country_basis": basis,
            "published_at": published_at,
            "publication_time_known": source_time_known,
            "title": "TEST: routine public health information",
            "official": True, "evidence_status": "active",
        }],
    }


def test_country_only_records_are_discoverable_but_never_current_crisis_stripes(world):
    old = evidence()
    world.set_events([], country_events=[old])
    item = world.country_evidence_for("Ukraine")
    assert item["count"] == 1
    assert item["events"][0]["id"] == "health-1"
    assert world.country_activity_for("Ukraine") == {}
    assert world.visible_clusters() == []
    assert world.area_layer.visible() == []
    assert "1 country-only records" in world.coverage_summary()
    assert "0 points" in world.coverage_summary()
    assert "0 countries with activity" in world.coverage_summary()
    assert "Country-only records" in world.empty_coverage_message()
    assert world._latest_source_publication(old) == "2026-09-01 12:00 UTC"


def test_undated_record_is_not_falsely_freshened_by_store_update(world):
    row = evidence(published_at="", source_time_known=False)
    world.set_events([], country_events=[row])
    assert world.country_evidence_for("Ukraine")["count"] == 1
    assert world._latest_source_publication(row) == "source publication undated"
    assert not world.country_activity_for("Ukraine")


def test_country_basis_unknown_or_publisher_coverage_never_maps_country(world):
    covered = evidence("publisher", "Ukraine", "publisher_coverage")
    unknown = evidence("unknown", "", "unresolved")
    synthetic = evidence("training", "Ukraine", "provider_incident", synthetic=True)
    world.set_events([], country_events=[covered, unknown, synthetic])
    assert world.country_evidence_for("Ukraine") == {}
    assert "0 country-only records" in world.coverage_summary()
    assert "2 unlocated" in world.coverage_summary()


def test_existing_category_filter_controls_country_only_records(world):
    health = evidence("health", category="Health")
    economy = evidence("economy", category="Economy")
    world.set_events([], country_events=[health, economy])
    world.categories = {"Economy"}
    assert world.country_evidence_for("Ukraine")["count"] == 1
    assert world.country_evidence_for("Ukraine")["events"][0]["id"] == "economy"
    world.categories = {"Conflict"}
    assert not world.country_evidence_for("Ukraine")
    world.categories = None
    assert world.country_evidence_for("Ukraine")["count"] == 2


def test_country_inspection_selects_only_actual_archived_event_identity(world, app):
    row = evidence("source-id")
    world.set_events([], country_events=[row])
    selected = []
    world.event_selected.connect(selected.append)
    assert world.show_country_evidence("Ukraine")
    dialog = world.country_dialog
    listing = dialog.findChild(QListWidget)
    assert listing is not None and listing.count() == 1
    assert "source publication" not in listing.item(0).text().lower()
    assert listing.item(0).data(0x0100) == "source-id"
    listing.itemActivated.emit(listing.item(0))
    assert selected == ["source-id"]
    assert not world.has_location(row)
    assert not world.show_country_evidence("France")
    app.processEvents()


def test_store_to_map_country_only_evidence_without_source_geometry(tmp_path, world):
    current = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": "stored-health", "source_id": "test-local", "publisher": "TEST ONLY",
        "url": "https://example.org/local-fixture", "title": "TEST: local health update",
        "published_at": current, "category": "Health", "country": "Ukraine",
        "country_basis": "provider_incident", "official": True, "latitude": None,
        "longitude": None, "summary": "TEST only", "severity": "informational",
    }
    with Store(tmp_path / "local.sqlite3", mode="live") as store:
        inserted = store.ingest([raw], now=current)[0]
        assert store.list_events(map_view=True) == []
        evidence_rows = store.list_events(map_evidence=True)
        assert len(evidence_rows) == 1
        world.set_events([], country_events=evidence_rows)
        assert world.country_evidence_for("Ukraine")["count"] == 1
        assert world.country_evidence_for("Ukraine")["events"][0]["id"] == inserted["id"]
        assert not world.country_activity_for("Ukraine")
