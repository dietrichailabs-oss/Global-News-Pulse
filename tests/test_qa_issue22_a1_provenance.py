"""Independent QA: Issue #22 A1 source-provenance and active-report integrity.

Offline synthetic fixtures, not real incidents or news. These tests intentionally
exercise negative evidence: corrected/retracted/future reports must not lend
headline semantics to an otherwise innocuous active event. Failing tests are
findings, not implicit product changes or release acceptance.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from global_pulse.crisis_overlay import build_country_activity, classify_event
from global_pulse.map_evidence import incident_country

NOW = datetime(2026, 11, 10, 18, tzinfo=timezone.utc)
FRESH = "2026-11-10T17:00:00Z"
OLD = "2026-09-10T17:00:00Z"


def evidence_event():
    return {
        "id": "qa-isolated-evidence-1",
        "status": "active",
        "category": "News",
        "title": "TEST FIXTURE: routine public information update",
        "summary": "Purely synthetic benign verification fixture.",
        "published_at": FRESH,
        "country": "Ukraine",
        "reports": [
            {
                "id": "active-official",
                "source_id": "qa-fictional-official",
                "country": "Ukraine",
                "country_basis": "provider_incident",
                "official": True,
                "evidence_status": "active",
                "title": "TEST FIXTURE: routine public information update",
                "summary": "No active crisis category asserted.",
                "published_at": FRESH,
            }
        ],
    }


class IndependentIssue22A1Provenance(unittest.TestCase):
    def activity(self, event):
        return build_country_activity([event], now=NOW)

    def test_active_official_conflict_remains_visible(self):
        event = evidence_event()
        event["reports"][0]["title"] = "TEST FIXTURE: armed conflict with verified reports"
        self.assertEqual(self.activity(event)["ukraine"]["conflict"], 1)

    def test_retracted_report_cannot_lend_crisis_terms(self):
        event = evidence_event()
        event["reports"].append({
            "id": "retracted-claim", "source_id": "qa-fictional-retired",
            "country": "Ukraine", "country_basis": "provider_incident",
            "official": False, "evidence_status": "retracted",
            "title": "TEST FIXTURE: armed conflict and bombardment",
            "published_at": FRESH,
        })
        self.assertEqual(classify_event(event), set(),
                         "Retracted report text must not create an active conflict classification")
        self.assertEqual(self.activity(event), {},
                         "Retracted report text must not create an active country stripe")

    def test_future_report_cannot_lend_crisis_terms(self):
        event = evidence_event()
        event["reports"].append({
            "id": "future-claim", "source_id": "qa-fictional-future",
            "country": "Ukraine", "country_basis": "provider_incident",
            "official": False, "future_dated": True,
            "title": "TEST FIXTURE: armed conflict and missiles",
            "published_at": "2027-01-01T00:00:00Z",
        })
        self.assertEqual(classify_event(event), set(),
                         "Future-dated report text must not create an active classification")
        self.assertEqual(self.activity(event), {},
                         "Future-dated report text must not create an active country stripe")

    def test_corrected_report_cannot_lend_migration_terms(self):
        event = evidence_event()
        event["reports"].append({
            "id": "corrected-claim", "source_id": "qa-fictional-corrected",
            "country": "Ukraine", "country_basis": "provider_incident",
            "official": False, "evidence_status": "corrected",
            "title": "TEST FIXTURE: forced displacement of refugees",
            "published_at": FRESH,
        })
        self.assertEqual(classify_event(event), set(),
                         "Corrected obsolete report text must not create migration activity")

    def test_conflicting_active_incident_countries_are_not_silently_selected(self):
        event = evidence_event()
        event["reports"][0]["title"] = "TEST FIXTURE: armed conflict"
        event["reports"].append({
            "id": "other-active", "source_id": "qa-fictional-official2",
            "country": "Poland", "country_basis": "provider_incident",
            "official": True, "evidence_status": "active",
            "title": "TEST FIXTURE: armed conflict", "published_at": FRESH,
        })
        self.assertEqual(incident_country(event), "")
        self.assertEqual(self.activity(event), {})

    def test_old_active_report_is_not_rejuvenated_by_recent_local_event_timestamp(self):
        event = evidence_event()
        event["reports"][0]["published_at"] = OLD
        self.assertEqual(self.activity(event), {},
                         "Local ingestion/update timestamp is not fresh source evidence")

    def test_retracted_country_does_not_outvote_active_country(self):
        event = evidence_event()
        event["reports"][0]["title"] = "TEST FIXTURE: armed conflict"
        event["reports"].append({
            "id": "retired-country", "source_id": "qa-fictional-retired",
            "country": "Poland", "country_basis": "provider_incident",
            "official": True, "evidence_status": "retracted",
            "title": "TEST FIXTURE: routine update", "published_at": FRESH,
        })
        self.assertEqual(incident_country(event), "Ukraine")
        self.assertEqual(self.activity(event)["ukraine"]["conflict"], 1)


if __name__ == "__main__":
    unittest.main()
