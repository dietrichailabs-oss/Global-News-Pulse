"""Engineering-only offline Issue #22 economic/health vs armed-crisis regression.

All locations and publishers below are inert fixtures, never current-event
claims, provider checks, independent QA, or physical Windows 11 acceptance.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from global_pulse.core import Store
from global_pulse.crisis_overlay import build_country_activity, classify_event
from global_pulse.map_widget import WorldMap


def report_event(title, *, category="News", source_id="fixture-agency"):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "id": "local-mock", "status": "active", "synthetic": False,
        "title": title, "category": category, "country": "France",
        "country_basis": "provider_incident", "published_at": stamp,
        "reports": [{
            "id": "local-mock-source", "source_id": source_id,
            "title": title, "summary": title, "category": category,
            "country": "France", "country_basis": "provider_incident",
            "published_at": stamp, "publication_time_known": True,
            "evidence_status": "active", "official": True,
        }],
    }


@pytest.mark.parametrize("headline", [
    "Retail price war drives discounting",
    "Trade war tariffs raise import prices",
    "Currency war rhetoric affects markets",
    "Bidding war for a commercial property",
    "Public health agency's war on cancer",
    "Community launches war on poverty",
    "Agency announces war on inflation",
    "Company builds a larger war chest for acquisitions",
    "Employers wage war for talent as hiring accelerates",
    "Health ministry declares war on obesity",
    "Retailers enter a war of words over holiday pricing",
])
def test_nonmilitary_war_idiom_cannot_create_current_crisis_stripe(headline):
    row = report_event("TEST: " + headline, category="Economy")
    assert "conflict" not in classify_event(row)
    assert build_country_activity([row]) == {}


def test_nonmilitary_war_with_actual_military_evidence_still_counts():
    row = report_event("TEST: trade war discussions follow missile strikes on border", category="News")
    assert classify_event(row) == {"conflict"}
    assert build_country_activity([row])["france"]["conflict"] == 1


def test_explicit_conflict_category_preserved_for_combined_headline():
    row = report_event("TEST: trade war and deteriorating border security", category="Conflict")
    assert "conflict" in classify_event(row)


def test_economic_idiom_does_not_hide_separate_current_unrest():
    row = report_event("TEST: currency war concerns prompt mass protests", category="Economy")
    kinds = classify_event(row)
    assert "unrest" in kinds
    assert "conflict" not in kinds


def test_store_to_actual_map_keeps_economic_source_inspectable_without_crisis(tmp_path):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    incoming = {
        "id": "test-price-war", "source_id": "fixture-local-agency",
        "publisher": "OFFLINE TEST FIXTURE", "url": "https://example.org/fixture-price-war",
        "title": "TEST: retail price war reduces consumer prices",
        "summary": "Inert example; not a live economic claim.",
        "category": "Economy", "country": "France", "region": "Europe",
        "country_basis": "provider_incident", "official": True,
        "published_at": stamp, "retrieved_at": stamp,
    }
    app = QApplication.instance() or QApplication([])
    with Store(tmp_path / "fixture-economy.sqlite3", mode="live") as store:
        stored = store.ingest([incoming], now=stamp)
        assert len(stored) == 1
        assert store.list_events(map_view=True) == []
        country_rows = store.list_events(map_evidence=True)
        world = WorldMap()
        try:
            world.set_events([], country_events=country_rows)
            assert world.country_activity_for("France") == {}
            archive = world.country_evidence_for("France")
            assert archive["count"] == 1
            assert archive["events"][0]["id"] == stored[0]["id"]
            assert "1 country-only records" in world.coverage_summary()
        finally:
            if world.country_dialog:
                world.country_dialog.close()
            world.close()
            app.processEvents()
