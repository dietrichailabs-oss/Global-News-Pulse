"""No-click source-backed map classification runs once per report batch.

Fictional dated reports only; a lower Qt/CPU cost does not prove physical Win11 smoothness.
"""
from datetime import datetime, timedelta, timezone
from time import perf_counter
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
import global_pulse.crisis_overlay as overlay
import global_pulse.map_widget as map_widget
from global_pulse.map_evidence import incident_country

NOW = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)


def _record(index, *, official=False, title="Fictional quarterly crop forecast",
            category="Economy", status="active", offset_days=0, origins=1,
            country="Ukraine"):
    stamp = (NOW + timedelta(days=offset_days)).isoformat()
    records = [{
        "id": f"source-{index}-{j}", "origin_id": f"fictional-origin-{index}-{j}",
        "source_id": "fictional-offline", "kind": "report",
        "independence": "original", "country": country,
        "country_basis": "explicit_record", "title": title,
        "summary": "Fictional offline source evidence, not a live incident",
        "category": category, "official": official,
        "published_at": stamp, "evidence_status": "active",
    } for j in range(origins)]
    return {
        "id": f"event-{index}", "title": title, "category": category,
        "status": status, "updated_at": stamp,
        "independent_origins": [r["origin_id"] for r in records],
        "reports": records,
    }


def _cases():
    return [
        _record("official", official=True, title="Fictional military clash in Ukraine",
                category="Conflict"),
        _record("two-originals", origins=2, title="Fictional armed conflict in Ukraine",
                category="Conflict"),
        _record("single-original", title="Fictional armed conflict in Ukraine",
                category="Conflict"),
        _record("economic", official=True),
        _record("future", official=True, title="Fictional military clash in Ukraine",
                category="Conflict", offset_days=3),
        _record("stale", official=True, title="Fictional military clash in Ukraine",
                category="Conflict", offset_days=-45),
        _record("retracted", official=True, title="Fictional military clash in Ukraine",
                category="Conflict", status="retracted"),
        _record("different-place", official=True,
                title="Fictional military clash in Germany", category="Conflict",
                country="Germany"),
    ]


def test_per_record_credits_equal_individual_source_classifier_without_cross_event_leak():
    events = _cases()
    credit = set()
    complete = overlay.build_country_activity(events, now=NOW, single_record_credits=credit)
    expected = set()
    for event in events:
        country = overlay.normalize_country(incident_country(event))
        if country and overlay.build_country_activity((event,), now=NOW).get(country):
            expected.add((id(event), country))
    assert credit == expected
    ukraine = overlay.normalize_country("Ukraine")
    assert (id(events[0]), ukraine) in credit
    assert (id(events[1]), ukraine) in credit
    for record in events[2:7]:
        assert (id(record), ukraine) not in credit
    assert complete[ukraine]["conflict"] >= 1


def test_two_separate_one_origin_records_corrobate_aggregate_but_remain_neutral_singly():
    a = _record("unconfirmed-a", title="Fictional missiles reported in Ukraine", category="Conflict")
    b = _record("unconfirmed-b", title="Fictional missiles reported in Ukraine", category="Conflict")
    credit = set()
    result = overlay.build_country_activity((a, b), now=NOW, single_record_credits=credit)
    assert result[overlay.normalize_country("Ukraine")]["basis"]["conflict"] == "cross_event_independent"
    assert not credit, "A cross-event stripe cannot convert either uncorroborated report into a singly verified event"


def test_map_uses_one_aggregate_classifier_and_retains_neutral_evidence():
    app = QApplication.instance() or QApplication([])
    records = _cases() + [_record(i) for i in range(420)]
    ukraine = overlay.normalize_country("Ukraine")
    baseline = [
        record for record in records
        if overlay.normalize_country(incident_country(record)) == ukraine
        and not overlay.build_country_activity((record,), now=NOW).get(ukraine)
    ]
    original = map_widget.build_country_activity
    calls = []
    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    def counted(rows, **kw):
        calls.append((len(rows), bool(kw.get("single_record_credits") is not None)))
        # Both sides of this equivalence check use the fixture's clock. The
        # +3-day record must remain future-dated after the real date advances.
        assert kw["now"] == NOW
        return original(rows, **kw)

    widget = map_widget.WorldMap()
    started = perf_counter()
    try:
        with (patch.object(map_widget, "datetime", FixtureClock),
              patch.object(map_widget, "build_country_activity", side_effect=counted)):
            widget.set_events(records, country_events=records)
            widget.coverage_summary()   # Cached; must not run the classifier again
        assert calls == [(len(records), True)], calls
        actual = widget.country_only_evidence[ukraine]["events"]
        assert {e["id"] for e in actual} == {e["id"] for e in baseline}
        assert widget.country_activity[ukraine]["conflict"] >= 1
        print(f"PULSE_SOURCE_MAP_SINGLE_CREDIT_{len(records)}_REPORTS_MS={(perf_counter()-started)*1000:.3f}", flush=True)
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()
