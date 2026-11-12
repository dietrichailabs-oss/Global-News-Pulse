"""Actual Qt-controller integration with local records and no network/native QA."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller, in_quiet_hours


def iso(value=None):
    return (value or datetime.now(timezone.utc)).isoformat(timespec="seconds").replace("+00:00", "Z")


def report(id="a", **changes):
    stamp = iso()
    data = dict(id=id, source_id="official", publisher="Official fixture publisher", title="Port authority announces temporary harbor closure",
                summary="The port authority announces a temporary closure while equipment is inspected.",
                url=f"https://authority.example/report/{id}", published_at=stamp, retrieved_at=stamp,
                language="en", region="North Atlantic", country="Norland", category="Infrastructure",
                event_key="controller-test", severity="high", official=True, official_scope="statement",
                origin_id="authority", independence="original", synthetic=False)
    data.update(changes)
    return data


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(tmp_path, app):
    c = Controller(tmp_path)
    c.monitoring = True  # Directly deliver collector records; no scheduler/network starts.
    yield c
    c.close()


def capture_native(controller):
    emitted = []
    controller.native_alert.connect(lambda event, reason: emitted.append((event, reason)))
    return emitted


def test_real_controller_routes_fresh_alert_with_exact_internal_identity(controller):
    native = capture_native(controller)
    controller._on_reports([report()])
    alerts = controller.store.list_alerts()
    assert len(alerts) == len(native) == 1
    assert native[0][0]["_alert_id"] == alerts[0]["id"]
    assert native[0][0]["id"] == alerts[0]["event_id"]
    assert controller.event(alerts[0]["event_id"])


def test_historical_initial_import_does_not_alert_as_new(controller):
    native = capture_native(controller)
    old = iso(datetime.now(timezone.utc) - timedelta(days=4))
    controller._on_reports([report(published_at=old)])
    assert len(controller.events()) == 1
    assert not controller.store.list_alerts() and not native


def test_undated_feed_with_fresh_retrieval_is_feed_only(controller):
    native = capture_native(controller)
    controller._on_reports([report(published_at="", publication_time_unknown=True)])
    assert controller.events()[0]["publication_time_known"] is False
    assert not controller.store.list_alerts() and not native


def test_fresh_provider_revision_of_old_record_can_alert(controller):
    old = iso(datetime.now(timezone.utc) - timedelta(days=4))
    native = capture_native(controller)
    controller._on_reports([report(published_at=old, source_updated_at=iso())])
    assert len(native) == 1


def test_future_publication_is_not_alerted(controller):
    native = capture_native(controller)
    future = iso(datetime.now(timezone.utc) + timedelta(days=2))
    controller._on_reports([report(published_at=future)])
    assert not native and not controller.store.list_alerts()


def test_source_mute_cannot_be_bypassed_by_unmuted_repost(controller):
    controller.set_setting("muted_sources", ["official"])
    native = capture_native(controller)
    controller._on_reports([report(), report("copy", source_id="repost", official=False, origin_id="authority", independence="syndicated", kind="social")])
    assert controller.events()[0]["report_count"] == 2
    assert not native and not controller.store.list_alerts()


def test_muted_critical_impact_cannot_raise_unmuted_informational_alert(controller):
    controller.set_setting("muted_sources", ["official"])
    controller._on_reports([report(severity="critical"), report("low", source_id="unmuted", severity="informational", title="Separate informational service notice")])
    assert controller.events()[0]["severity"] == "critical"
    assert not controller.store.list_alerts()


def test_muted_second_origin_cannot_corroborate_remaining_source(controller):
    controller.set_setting("muted_sources", ["second"])
    a = report(official=False, origin_id="first-desk", source_id="first")
    b = report("b", official=False, origin_id="second-desk", source_id="second", summary="A second desk reports a closure after checking independently.")
    controller._on_reports([a, b])
    assert controller.events()[0]["verification"] == "developing"
    assert not controller.store.list_alerts()


def test_quiet_hours_retains_alert_with_truthful_delivery_status(controller):
    native = capture_native(controller)
    controller.set_setting("quiet_enabled", True)
    controller.set_setting("quiet_start", "00:00")
    controller.set_setting("quiet_end", "00:00")
    controller._on_reports([report()])
    assert not native
    assert "Quiet hours" in controller.store.list_alerts()[0]["delivery_status"]


def test_user_notification_mute_retains_history(controller):
    native = capture_native(controller)
    controller.set_setting("notifications_enabled", False)
    controller._on_reports([report()])
    assert not native
    assert "muted" in controller.store.list_alerts()[0]["delivery_status"]


def test_pause_prevents_new_monitoring_records_and_alerts(controller):
    controller.pause()
    controller._on_reports([report()])
    assert not controller.events()
    assert not controller.store.list_alerts()


def test_pause_while_ingest_completes_does_not_emit_post_pause_alert(controller, monkeypatch):
    original = controller.store.ingest
    def stop_after_store(records, now=None):
        changed = original(records, now=now)
        controller.pause()
        return changed
    monkeypatch.setattr(controller.store, "ingest", stop_after_store)
    native = capture_native(controller)
    controller._on_reports([report()])
    assert len(controller.events()) == 1
    assert not controller.store.list_alerts() and not native


def test_live_and_synthetic_fixture_archives_are_separate(controller, tmp_path, app, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "crisis.json"
    with pytest.raises(ValueError, match="separate database"):
        controller.load_fixture(fixture)
    controller._on_reports([report(synthetic=True)])
    assert not controller.events()
    c = Controller(tmp_path / "review", demo=True)
    try:
        calls = []
        monkeypatch.setattr(c.scheduler, "start", lambda: calls.append("start"))
        monkeypatch.setattr(c.scheduler, "resume", lambda: calls.append("resume"))
        monkeypatch.setattr(c.scheduler, "poll_now", lambda: calls.append("poll"))
        native = capture_native(c)
        c.load_fixture(fixture)
        c.start()
        c.resume()
        c.refresh()
        assert not calls and not native and not c.monitoring
        assert c.events()[0]["synthetic"]
        assert len(c.events()[0]["timeline"]) == 10
        assert c.store.list_observations()[0]["synthetic"]
        assert all("Synthetic" in a["delivery_status"] for a in c.store.list_alerts())
        assert not controller.events()
    finally:
        c.close()


def test_fresh_correction_and_retraction_of_old_event_remain_actionable(controller):
    old = iso(datetime.now(timezone.utc) - timedelta(days=4))
    controller._on_reports([report(published_at=old)])
    assert not controller.store.list_alerts()
    controller._on_reports([report("correction", kind="correction", correction_of="a", summary="Authority corrects the earlier closure duration.")])
    assert controller.store.list_alerts()[0]["kind"] == "correction"
    controller._on_reports([report("retraction", kind="retraction", retraction_of="correction", summary="Authority withdraws its earlier estimate.")])
    alerts = controller.store.list_alerts()
    assert len(alerts) == 2
    assert {a["kind"] for a in alerts} == {"correction", "retraction"}


def test_no_fake_independence_from_multiple_unknown_feed_domains(controller):
    records = [report(str(i), source_id=f"source{i}", official=False, independence="unknown", origin_id=f"domain{i}", summary=f"A similarly attributed report from source{i}") for i in range(3)]
    controller._on_reports(records)
    assert not controller.store.list_alerts()
    assert controller.events()[0]["independent_origins"] == []


def test_quiet_hours_cross_midnight_and_boundaries():
    settings = {"quiet_enabled": True, "quiet_start": "22:00", "quiet_end": "07:00"}
    assert in_quiet_hours(settings, datetime(2026, 11, 8, 23, 30))
    assert in_quiet_hours(settings, datetime(2026, 11, 8, 6, 59))
    assert not in_quiet_hours(settings, datetime(2026, 11, 8, 7, 0))
    assert not in_quiet_hours(settings, datetime(2026, 11, 8, 12, 0))


def test_user_feed_setup_defers_dns_to_background_collector(controller, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS must not run in the UI feed setup path"))
    controller.add_user_feed("https://public-feed.example.org/rss", "User public feed")
    assert controller.catalog[-1]["access_status"] == "user_supplied"


def test_qt_child_and_posted_events_keep_native_dispatch(controller, app):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    child = QTimer(controller)
    QCoreApplication.postEvent(controller, QEvent(QEvent.Type.User))
    app.processEvents()
    assert child.parent() is controller
