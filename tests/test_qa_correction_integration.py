"""GP-CORE-001 full Qt/controller/SQLite regressions.

No scheduler, HTTP collection, or Windows notification helper starts. Assertions
about native_alert concern the controller's signal only, never visible toasts.
Missing Qt is a collection error, not a silent PASS or skipped acceptance case.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller


def report(*, severity="high", kind="report", **changes):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    value = dict(id="qa-correction", source_id="qa-authority",
                 publisher="Fictional QA authority", title="Fictional port closure notice",
                 summary="Fictional port authority reports a closure.",
                 url="https://authority.example/qa-correction", published_at=stamp,
                 retrieved_at=stamp, language="en", region="North Atlantic",
                 country="Norland", category="Infrastructure", event_key="qa-correction",
                 severity=severity, kind=kind, official=True, official_scope="statement",
                 origin_id="qa-authority", independence="original", synthetic=True)
    value.update(changes)
    return value


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(tmp_path, app):
    instance = Controller(tmp_path, demo=True)
    yield instance
    instance.close()


def ingest_original(controller):
    controller._on_reports([report()], allow_synthetic=True)
    alerts = controller.store.list_alerts()
    assert len(alerts) == 1
    return alerts[0]


def correction():
    return report(severity="informational", kind="correction",
                  summary="The fictional authority corrects its notice: the port never closed.")


def test_real_controller_records_downgrade_correction_and_preserves_identity(controller):
    first = ingest_original(controller)
    controller._on_reports([correction()], allow_synthetic=True)
    alerts = controller.store.list_alerts()
    assert len(alerts) == 2
    changed = next(a for a in alerts if a["id"] != first["id"])
    assert changed["kind"] == "correction"
    assert changed["event_id"] == first["event_id"]
    assert controller.event(first["event_id"])["severity"] == "informational"


def test_repeated_identical_correction_is_not_a_duplicate_alert(controller):
    ingest_original(controller)
    revised = correction()
    controller._on_reports([revised], allow_synthetic=True)
    controller._on_reports([revised], allow_synthetic=True)
    assert len(controller.store.list_alerts()) == 2


@pytest.mark.parametrize("setting,value", [("countries", ["Elsewhere"]),
    ("categories", ["Economy"]), ("muted_sources", ["qa-authority"]),
    ("alert_threshold", "critical")])
def test_new_explicit_preferences_still_suppress_correction(controller, setting, value):
    ingest_original(controller)
    controller.set_setting(setting, value)
    controller._on_reports([correction()], allow_synthetic=True)
    assert len(controller.store.list_alerts()) == 1


def test_current_and_prior_low_significance_do_not_alert(controller):
    controller._on_reports([report(severity="informational")], allow_synthetic=True)
    controller._on_reports([correction()], allow_synthetic=True)
    assert not controller.store.list_alerts()


def test_retraction_downgrade_retains_prior_significance(controller):
    first = ingest_original(controller)
    controller._on_reports([report(severity="informational", kind="retraction",
        status="retracted", summary="The fictional authority withdraws its closure notice.")],
        allow_synthetic=True)
    alerts = controller.store.list_alerts()
    assert len(alerts) == 2
    assert any(a["kind"] == "retraction" and a["event_id"] == first["event_id"] for a in alerts)


def test_restart_keeps_prior_significance_in_sqlite(tmp_path, app):
    first = Controller(tmp_path, demo=True)
    try:
        original = ingest_original(first)
    finally:
        first.close()
    resumed = Controller(tmp_path, demo=True)
    try:
        resumed._on_reports([correction()], allow_synthetic=True)
        alerts = resumed.store.list_alerts()
        assert len(alerts) == 2
        assert all(a["event_id"] == original["event_id"] for a in alerts)
    finally:
        resumed.close()


def test_synthetic_correction_never_emits_native_signal(controller):
    emitted = []
    controller.native_alert.connect(lambda *args: emitted.append(args))
    ingest_original(controller)
    controller._on_reports([correction()], allow_synthetic=True)
    assert len(controller.store.list_alerts()) == 2
    assert not emitted
    assert all("Synthetic" in a["delivery_status"] for a in controller.store.list_alerts())


@pytest.mark.parametrize("settings,status,signals", [
    ({"notifications_enabled": False}, "muted", 1),
    ({"quiet_enabled": True, "quiet_start": "00:00", "quiet_end": "00:00"}, "Quiet hours", 1),
    ({}, None, 2),
])
def test_correction_delivery_preferences_in_isolated_controller(tmp_path, app, settings, status, signals):
    # Fictional records exercise the normal controller in a temporary test store;
    # no collector or native notification helper is attached or started.
    c = Controller(tmp_path / "delivery-test")
    emitted = []
    c.native_alert.connect(lambda *args: emitted.append(args))
    c.monitoring = True
    try:
        c._on_reports([report(synthetic=False)])
        assert len(c.store.list_alerts()) == 1
        for key, value in settings.items():
            c.set_setting(key, value)
        revised = dict(correction(), synthetic=False)
        c._on_reports([revised])
        alerts = c.store.list_alerts()
        assert len(alerts) == 2
        assert len(emitted) == signals
        notice = next(a for a in alerts if a["kind"] == "correction")
        if status:
            assert status in notice["delivery_status"]
    finally:
        c.close()


def test_paused_monitoring_does_not_ingest_or_notify_correction(tmp_path, app):
    c = Controller(tmp_path / "pause-test")
    c.monitoring = True
    try:
        c._on_reports([report(synthetic=False)])
        c.pause()
        c._on_reports([dict(correction(), synthetic=False)])
        assert len(c.store.list_alerts()) == 1
        assert c.events()[0]["severity"] == "high"
    finally:
        c.close()
