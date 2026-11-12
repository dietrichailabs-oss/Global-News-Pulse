"""Engineering-only Issue22 publisher-country provenance alias regressions.

All records are synthetic, offline and do not establish a live current event.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from global_pulse.crisis_overlay import build_country_activity
from global_pulse.map_evidence import incident_country
from global_pulse.core import Store

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
STAMP = "2026-11-12T11:00:00Z"


def event(country="United States of America", source_id="ftc_press",
          source_country="", basis="", other=None):
    report = {
        "id": "fixture-report", "source_id": source_id, "country": country,
        "country_basis": basis, "source_country": source_country,
        "official": True, "publication_time_known": True,
        "evidence_status": "active", "published_at": STAMP,
        "title": "TEST FIXTURE ONLY: armed conflict",
        "category": "Conflict",
    }
    return {
        "id": "fixture-event", "status": "active", "country": country,
        "published_at": STAMP, "category": "Conflict",
        "reports": [report] + ([other] if other is not None else []),
    }


class PublisherCountryAliasEngineering(unittest.TestCase):
    def test_legacy_us_publisher_default_alias_is_not_an_incident(self):
        row = event()
        self.assertEqual(incident_country(row), "")
        self.assertEqual(build_country_activity([row], now=NOW), {})

    def test_legacy_uk_publisher_default_alias_is_not_an_incident(self):
        row = event(country="UK", source_id="fcdo")
        self.assertEqual(incident_country(row), "")
        self.assertEqual(build_country_activity([row], now=NOW), {})

    def test_explicit_publisher_metadata_alias_is_not_an_incident(self):
        row = event(country="Türkiye", source_id="fixture-custom",
                    source_country="Turkey")
        self.assertEqual(incident_country(row), "")
        self.assertEqual(build_country_activity([row], now=NOW), {})

    def test_explicit_incident_provenance_is_preserved_even_when_names_match(self):
        row = event(basis="provider_incident")
        self.assertEqual(incident_country(row), "United States of America")
        self.assertEqual(build_country_activity([row], now=NOW)
                         ["unitedstatesofamerica"]["conflict"], 1)

    def test_same_explicit_incident_in_two_country_spellings_is_not_lost(self):
        other = dict(event(country="USA", source_id="fixture-second",
                           basis="explicit_record")["reports"][0], id="second")
        row = event(country="United States", source_id="fixture-first",
                    basis="explicit_record", other=other)
        self.assertEqual(incident_country(row), "USA")
        self.assertEqual(build_country_activity([row], now=NOW)
                         ["unitedstatesofamerica"]["conflict"], 1)

    def test_distinct_active_incident_countries_remain_ambiguous(self):
        second = dict(event(country="Poland", source_id="fixture-other",
                            basis="explicit_record")["reports"][0], id="other")
        row = event(country="Ukraine", source_id="fixture-first",
                    basis="provider_incident", other=second)
        self.assertEqual(incident_country(row), "")
        self.assertEqual(build_country_activity([row], now=NOW), {})

    def test_invalid_source_id_type_does_not_crash_provenance_check(self):
        row = event(country="Ukraine", source_id=["invalid-id"])
        self.assertEqual(incident_country(row), "Ukraine")

    def test_real_sqlite_store_path_does_not_promote_legacy_publisher_hint(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            raw = {
                "id": "synthetic-legacy-us", "source_id": "ftc_press",
                "publisher": "TEST ONLY", "url": "https://example.org/test-only",
                "title": "TEST FIXTURE ONLY: armed conflict",
                "summary": "Inert fixture, not live reporting",
                "published_at": STAMP, "retrieved_at": STAMP,
                "country": "United States of America",
                "category": "Conflict", "official": True, "severity": "high",
            }
            with Store(Path(directory) / "fixture.sqlite3", mode="live") as store:
                store.ingest([raw], now=STAMP)
                saved = store.list_events(map_evidence=True)
                self.assertEqual(len(saved), 1)
                self.assertEqual(incident_country(saved[0]), "")
                self.assertEqual(build_country_activity(saved, now=NOW), {})


if __name__ == "__main__":
    unittest.main()
