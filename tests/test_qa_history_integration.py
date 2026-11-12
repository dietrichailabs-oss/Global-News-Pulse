"""Engineering regressions for GP-CORE-001/005/006, using real Qt and SQLite.
No live collection or native notification helper runs. Captured Qt signals are
not evidence of a displayed Windows notification or independent QA acceptance.
"""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timedelta, timezone
import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.core import Store, alert_reason, notification_view

T0 = datetime(2026, 11, 9, tzinfo=timezone.utc)


def stamp(days=0, hours=0, minutes=0):
    return (T0 + timedelta(days=days, hours=hours, minutes=minutes)).isoformat().replace("+00:00", "Z")


def report(identifier="a", at=None, **values):
    moment = at or stamp()
    result = dict(id=identifier, source_id="authority", publisher="Fictional test authority",
                  title="Fictional harbor closure notice", summary="A fictional harbor is closed for inspection.",
                  url="https://authority.example/report/" + identifier,
                  published_at=moment, retrieved_at=moment, language="en", region="North Atlantic",
                  country="Norland", category="Infrastructure", event_key="history-regression",
                  severity="high", official=True, official_scope="measurement",
                  origin_id="authority", independence="original", kind="report", synthetic=False)
    result.update(values)
    return result


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(tmp_path, app):
    value = Controller(tmp_path)
    value.monitoring = True  # Direct isolated records; scheduler/network never starts.
    yield value
    value.close()


def send(controller, at, *records):
    controller._on_reports(list(records), now=at)
    assert not controller.store.last_ingest_errors


@pytest.mark.parametrize("same_record", [True, False])
@pytest.mark.parametrize("reopen", [True, False])
def test_twelve_daily_corrections_and_retraction_keep_all_alerts(tmp_path, app, same_record, reopen):
    c = Controller(tmp_path)
    c.monitoring = True
    try:
        send(c, stamp(), report())
        previous_id = "a"
        for day in range(1, 13):
            if reopen:
                c.close()
                c = Controller(tmp_path)
                c.monitoring = True
            identifier = "a" if same_record else "correction-" + str(day)
            correction = report(identifier, stamp(days=day), kind="correction", severity="informational",
                                correction_of="" if same_record else previous_id,
                                summary="Material correction number " + str(day) + ": the closure estimate was wrong.")
            send(c, stamp(days=day), correction)
            previous_id = identifier
            assert len(c.store.list_alerts()) == day + 1
            assert c.events()[0]["severity"] == "informational"
        withdrawal = report("withdrawal", stamp(days=13), kind="retraction", retraction_of=previous_id,
                            severity="informational", summary="The final fictional closure claim is withdrawn.")
        send(c, stamp(days=13), withdrawal)
        assert len(c.store.list_alerts()) == 14
        assert len(c.events()[0]["timeline"]) == 14
        assert c.store.list_alerts()[0]["kind"] == "retraction"
        send(c, stamp(days=13, minutes=1), withdrawal)
        assert len(c.store.list_alerts()) == 14  # Identical notices remain deduplicated.
    finally:
        c.close()


def test_intervening_ordinary_downgrade_does_not_erase_correction_history(controller):
    send(controller, stamp(), report())
    send(controller, stamp(hours=1), report(at=stamp(hours=1), severity="informational", summary="Routine lower-severity update."))
    assert len(controller.store.list_alerts()) == 1
    send(controller, stamp(hours=2), report(at=stamp(hours=2), severity="informational", kind="correction", summary="Material correction after the routine downgrade."))
    assert [a["kind"] for a in controller.store.list_alerts()] == ["correction", "official"]


@pytest.mark.parametrize("key,value", [
    ("muted_sources", ["authority"]), ("categories", ["Economy"]),
    ("countries", ["Elsewhere"]), ("alert_threshold", "critical"),
])
def test_historical_significance_does_not_bypass_current_preferences(controller, key, value):
    send(controller, stamp(), report())
    controller.set_setting(key, value)
    send(controller, stamp(hours=1), report(at=stamp(hours=1), severity="informational", kind="correction", summary="First material correction."))
    send(controller, stamp(hours=2), report(at=stamp(hours=2), severity="informational", kind="correction", summary="Second material correction."))
    assert len(controller.store.list_alerts()) == 1


def test_muted_historical_source_cannot_lend_significance_to_other_source(controller):
    send(controller, stamp(), report())
    send(controller, stamp(hours=1), report("low", stamp(hours=1), source_id="other", origin_id="other", severity="informational", summary="Independent low-severity notice."))
    controller.set_setting("muted_sources", ["authority"])
    before = len(controller.store.list_alerts())
    send(controller, stamp(hours=2), report("low", stamp(hours=2), source_id="other", origin_id="other", severity="informational", kind="correction", summary="The other low-severity notice is corrected."))
    assert len(controller.store.list_alerts()) == before
    projected = notification_view(controller.events()[0], ["authority"])
    assert "authority" not in projected["significance_history"]


@pytest.mark.parametrize("quiet", [False, True])
def test_repeat_corrections_keep_history_without_violating_delivery_controls(controller, quiet):
    emitted = []
    controller.native_alert.connect(lambda *args: emitted.append(args))
    if quiet:
        controller.set_setting("quiet_enabled", True)
        controller.set_setting("quiet_start", "00:00")
        controller.set_setting("quiet_end", "00:00")
    else:
        controller.set_setting("notifications_enabled", False)
    send(controller, stamp(), report())
    for hour in (1, 2):
        send(controller, stamp(hours=hour), report(at=stamp(hours=hour), severity="informational", kind="correction", summary="Material correction " + str(hour)))
    assert len(controller.store.list_alerts()) == 3
    assert not emitted
    assert all(("Quiet hours" if quiet else "muted") in a["delivery_status"] for a in controller.store.list_alerts())


def test_legacy_event_without_history_recovers_retained_significance(controller):
    send(controller, stamp(), report())
    send(controller, stamp(hours=1), report(at=stamp(hours=1), severity="informational", summary="Routine downgrade."))
    event = controller.events()[0]
    with controller.store._conn:
        body = json.loads(controller.store._conn.execute("SELECT body FROM events WHERE id=?", (event["id"],)).fetchone()[0])
        body.pop("significance_history", None)  # Emulate the existing pre-repair archive representation.
        controller.store._conn.execute("UPDATE events SET body=? WHERE id=?", (json.dumps(body), event["id"]))
    send(controller, stamp(hours=2), report(at=stamp(hours=2), severity="informational", kind="correction", summary="Correction after archive upgrade."))
    assert len(controller.store.list_alerts()) == 2
    assert controller.events()[0]["significance_history"]["authority"] == "high"


def test_retention_removes_significance_derived_only_from_expired_report(tmp_path):
    with Store(tmp_path / "retention.sqlite3", mode="live") as store:
        store.ingest([report(retention_days=1)], now=stamp())
        store.ingest([report("low", stamp(days=2), severity="informational", kind="correction", correction_of="a", summary="Low-severity replacement.")], now=stamp(days=2))
        assert store.list_events()[0]["significance_history"]["authority"] == "high"
        result = store.prune(365, now=stamp(days=3))
        assert result["reports"] == 1
        assert store.list_events()[0]["significance_history"]["authority"] == "informational"


@pytest.mark.parametrize("kind", ["correction", "retraction"])
@pytest.mark.parametrize("reopen", [False, True])
def test_deferred_notice_on_unrelated_rebuild_is_versioned_and_alerted(tmp_path, app, kind, reopen):
    c = Controller(tmp_path)
    c.monitoring = True
    try:
        notice = report("deferred", stamp(hours=25), severity="informational", kind=kind,
                        summary="Deferred material " + kind, **{kind + "_of": "a"})
        # Retrieval occurs now, not at the notice's future publication time.
        notice["retrieved_at"] = stamp()
        send(c, stamp(), report(), notice)
        event_id = c.events()[0]["id"]
        assert len(c.store.list_alerts()) == 1
        if reopen:
            c.close()
            c = Controller(tmp_path)
            c.monitoring = True
        context = report("context", stamp(hours=25), source_id="context", origin_id="context", official=False,
                         independence="unknown", kind="commentary", severity="informational", summary="Unrelated current context.")
        send(c, stamp(hours=25), context)
        current = c.event(event_id)
        deferred = next(r for r in current["reports"] if r["id"] == "deferred")
        assert not deferred["future_dated"]
        assert deferred["retrieved_at"] == stamp()  # Do not invent another retrieval.
        assert any(change["report_id"] == "deferred" and change["kind"] == kind for change in current["changes"])
        assert len(c.store.list_alerts()) == 2
        assert c.store.list_alerts()[0]["kind"] == kind
        past = c.event(event_id, at=stamp(hours=1))
        assert next(r for r in past["reports"] if r["id"] == "deferred")["future_dated"]
        send(c, stamp(hours=26), dict(context, id="context2", url="https://context.example/second", published_at=stamp(hours=26)))
        assert len(c.store.list_alerts()) == 2
    finally:
        c.close()


def test_historical_replay_uses_chosen_revision_time_without_writing(tmp_path):
    with Store(tmp_path / "history.sqlite3", mode="live") as store:
        withdrawal = report("future-withdrawal", stamp(hours=25), kind="retraction", retraction_of="a", severity="informational")
        store.ingest([report(), withdrawal], now=stamp())
        initial = store.list_events()[0]
        counts = store.stats()
        versions = store._conn.execute("SELECT count(*) FROM report_revisions").fetchone()[0]
        historical = store.get_event(initial["id"], at=stamp(days=2))
        assert historical["revision"] == initial["revision"] == 1
        assert historical["updated_at"] == stamp()
        assert historical["verification"] == "official"
        assert historical["status"] == "active"
        assert next(r for r in historical["reports"] if r["id"] == "a")["evidence_status"] == "active"
        assert next(r for r in historical["reports"] if r["id"] == "future-withdrawal")["future_dated"]
        assert store.stats() == counts
        assert store._conn.execute("SELECT count(*) FROM report_revisions").fetchone()[0] == versions


def test_fresh_commentary_cannot_make_old_deferred_retraction_a_new_alert(controller):
    withdrawal = report("old-future-withdrawal", stamp(hours=25), kind="retraction", retraction_of="a", severity="informational")
    send(controller, stamp(), report(), withdrawal)
    context = report("context", stamp(days=5), kind="commentary", official=False, source_id="context", origin_id="context", severity="informational")
    send(controller, stamp(days=5), context)
    event = controller.events()[0]
    assert event["status"] == "retracted"
    assert any(c["kind"] == "retraction" for c in event["changes"])
    assert len(controller.store.list_alerts()) == 1


def test_future_high_evidence_never_seeds_current_significance_history(controller):
    send(controller, stamp(), report("future", stamp(days=5), severity="critical"),
         report("low", stamp(), source_id="low", origin_id="low", severity="informational"))
    send(controller, stamp(hours=1), report("low", stamp(hours=1), source_id="low", origin_id="low", severity="informational", kind="correction", summary="An informational correction."))
    assert controller.events()[0]["significance_history"].get("authority") is None
    assert not controller.store.list_alerts()
