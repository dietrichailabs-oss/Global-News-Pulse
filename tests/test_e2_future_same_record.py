"""GP-CORE-007 regressions: defer same-ID source updates without losing current evidence.

All records are fictional, offline and source-controlled. These are Engineering
tests, not independent Pulse QA or native Windows notification acceptance.
"""
import json

import pytest
from PySide6.QtWidgets import QApplication

from global_pulse.core import Store
from global_pulse.controller import Controller

T0 = "2026-11-09T12:00:00Z"
T1 = "2026-11-09T12:01:00Z"
FUTURE = "2026-11-10T12:00:00Z"
MATURE = "2026-11-10T12:02:00Z"


def measurement(**changes):
    record = dict(
        id="measurement", source_id="qa-authority",
        publisher="Fictional port authority", title="Fictional port measurement",
        summary="Valid current measurement", url="https://authority.example/measure/1",
        published_at=T0, retrieved_at=T0, language="en",
        region="North Atlantic", country="Norland", category="Infrastructure",
        event_key="qa-same-record-future", severity="high",
        latitude=40, longitude=-74, official=True, official_scope="measurement",
        origin_id="qa-government", independence="original", synthetic=True,
    )
    record.update(changes)
    return record


@pytest.mark.parametrize("kind,status", [
    ("correction", "corrected"),
    ("retraction", "retracted"),
    ("report", "active"),
])
def test_future_same_id_preserves_last_eligible_version_through_reopen_and_maturity(tmp_path, kind, status):
    path = tmp_path / "temporal.sqlite3"
    store = Store(path, mode="synthetic")
    original = store.ingest([measurement()], now=T0)[0]
    event_id = original["id"]
    assert original["verification"] == "official"
    assert original["severity"] == "high"
    assert original["reports"][0]["latitude"] == 40

    deferred = measurement(
        source_updated_at=FUTURE, retrieved_at=T1,
        summary="Source update not yet eligible", severity="informational",
        kind=kind, status=status, latitude=None, longitude=None,
    )
    store.ingest([deferred], now=T1)
    current = store.get_event(event_id)
    assert current["verification"] == original["verification"]
    assert current["severity"] == original["severity"]
    assert current["status"] == original["status"]
    assert current["revision"] == original["revision"]
    assert current["reports"][0]["summary"] == "Valid current measurement"
    assert current["reports"][0]["latitude"] == 40
    # Latest received and last eligible versions both remain immutable.
    saved = store._conn.execute(
        "SELECT body FROM report_revisions WHERE record_key=? ORDER BY id",
        (current["reports"][0]["record_key"],),
    ).fetchall()
    assert len(saved) == 2
    assert json.loads(saved[-1][0])["source_updated_at"] == FUTURE
    store.close()

    store = Store(path, mode="synthetic")
    reopened = store.get_event(event_id)
    assert reopened["verification"] == "official"
    assert reopened["reports"][0]["summary"] == "Valid current measurement"
    assert store.ingest([], now=MATURE)
    matured = store.get_event(event_id)
    assert matured["revision"] == original["revision"] + 1
    assert matured["reports"][0]["summary"] == deferred["summary"]
    assert matured["reports"][0]["source_updated_at"] == FUTURE
    assert len(matured["timeline"]) == 2
    assert store.ingest([], now=MATURE) == []
    assert store.get_event(event_id)["revision"] == matured["revision"]
    historical = store.get_event(event_id, at=T1)
    assert historical["reports"][0]["summary"] == "Valid current measurement"
    store.close()


def test_current_same_record_update_is_not_deferred(tmp_path):
    store = Store(tmp_path / "current.sqlite3", mode="synthetic")
    original = store.ingest([measurement()], now=T0)[0]
    updated = store.ingest([measurement(summary="Eligible source correction",
            kind="correction", source_updated_at=T1, retrieved_at=T1)], now=T1)[0]
    assert updated["id"] == original["id"]
    assert updated["revision"] == original["revision"] + 1
    assert store.get_event(updated["id"])["reports"][0]["summary"] == "Eligible source correction"
    store.close()


def test_actual_qt_controller_reopen_keeps_eligible_same_id_evidence(tmp_path):
    app = QApplication.instance() or QApplication([])
    first = Controller(tmp_path, demo=True)
    first._on_reports([measurement()], allow_synthetic=True, now=T0)
    event_id = first.events()[0]["id"]
    first._on_reports([measurement(kind="retraction", status="retracted",
        severity="informational", source_updated_at=FUTURE, retrieved_at=T1,
        summary="Future retraction")], allow_synthetic=True, now=T1)
    assert first.event(event_id)["verification"] == "official"
    assert first.event(event_id)["status"] == "active"
    first.close()

    second = Controller(tmp_path, demo=True)
    assert second.event(event_id)["verification"] == "official"
    assert second.event(event_id)["status"] == "active"
    second._on_reports([], allow_synthetic=True, now=MATURE)
    matured = second.event(event_id)
    assert matured["revision"] == 2
    assert matured["reports"][0]["summary"] == "Future retraction"
    second._on_reports([], allow_synthetic=True, now=MATURE)
    assert second.event(event_id)["revision"] == 2
    second.close()
    assert app is not None
