"""Engineering regression for QA107 country-only/current-crisis double counting.

Inert offline records only. This does not claim live Ukraine conflict reporting,
actual Windows11 behavior, or independent QA acceptance.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone
import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.map_widget import WorldMap


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def world(app):
    instance = WorldMap()
    yield instance
    if instance.country_dialog:
        instance.country_dialog.close()
    instance.close()
    app.processEvents()


def record(identity, *, title, category, published, official=True):
    """Sourced country-only event with explicit incident country and source time."""
    return {
        "id": identity, "title": title, "country": "Ukraine",
        "country_basis": "provider_incident", "category": category,
        "status": "active", "synthetic": False, "latitude": None,
        "longitude": None, "map_areas": [],
        "updated_at": "2026-11-12T04:00:00Z",
        "reports": [{
            "id": identity + "-report", "source_id": "fixture-" + identity,
            "title": title, "category": category, "country": "Ukraine",
            "country_basis": "provider_incident", "published_at": published,
            "publication_time_known": True, "official": official,
            "evidence_status": "active",
        }],
    }


def test_current_crisis_stripe_never_creates_neutral_archive_count(world):
    now = datetime.now(timezone.utc).isoformat()
    fresh = record("current", title="Armed clashes and shelling reported",
                   category="Conflict", published=now)
    world.set_events([], country_events=[fresh])
    assert world.country_activity_for("Ukraine").get("conflict") == 1
    assert world.country_evidence_for("Ukraine") == {}
    assert "0 country-only records" in world.coverage_summary()


def test_old_conflict_and_noncrisis_stay_visible_beside_current_stripe(world):
    now = datetime.now(timezone.utc).isoformat()
    current = record("current", title="Armed clashes and shelling reported",
                     category="Conflict", published=now)
    past = record("historical", title="Historical armed clashes",
                  category="Conflict", published="2026-08-01T12:00:00Z")
    health = record("routine-health", title="Routine public health information",
                    category="Health", published=now)
    world.set_events([], country_events=[current, past, health])
    assert world.country_activity_for("Ukraine").get("conflict") == 1
    archive = world.country_evidence_for("Ukraine")
    assert archive["count"] == 2
    assert {e["id"] for e in archive["events"]} == {"historical", "routine-health"}
    world.categories = {"Conflict"}
    assert world.country_activity_for("Ukraine").get("conflict") == 1
    assert world.country_evidence_for("Ukraine")["count"] == 1
    assert world.country_evidence_for("Ukraine")["events"][0]["id"] == "historical"
    world.categories = {"Health"}
    assert world.country_activity_for("Ukraine") == {}
    assert world.country_evidence_for("Ukraine")["count"] == 1
    world.categories = None
    assert world.country_evidence_for("Ukraine")["count"] == 2


def test_more_than_twenty_current_reports_do_not_leak_into_neutral_archive(world):
    now = datetime.now(timezone.utc).isoformat()
    current = [record(f"fresh-{i}", title="Armed clashes and shelling reported",
                      category="Conflict", published=now) for i in range(25)]
    historical = record("historical", title="Previously reported clashes",
                        category="Conflict", published="2026-08-01T12:00:00Z")
    world.set_events([], country_events=current + [historical])
    assert world.country_activity_for("Ukraine")["conflict"] == 25
    assert len(world.country_activity_for("Ukraine")["event_ids"]) == 20
    assert world.country_evidence_for("Ukraine")["count"] == 1
    assert world.country_evidence_for("Ukraine")["events"][0]["id"] == "historical"
