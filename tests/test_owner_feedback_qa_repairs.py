"""Engineering regressions for four GP-QA-E2-0A174915-001 findings.

Actual Qt widgets/reply API and SQLite; no provider/model/native-Windows access.
The shutdown case executes the unchanged nested production shutdown function,
with only OS tray/notifier/single-instance and application-exit surfaces stubbed.
"""
import ast
import sqlite3
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QEvent, QIODevice, QObject
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from global_pulse.camera_context import associated_cameras, camera_catalog
from global_pulse.camera_snapshot import CameraSnapshot
from global_pulse.controller import Controller, ShutdownPending
from global_pulse.core import Store
from global_pulse.media_widget import MediaPanel
from global_pulse.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(tmp_path, app):
    controller = Controller(tmp_path, demo=True)
    window = MainWindow(controller)
    yield window, controller
    # Cleanup must not modify persistent consent or start any network operation.
    for tile in window.media.tiles:
        tile.stop()
    window._force_close = True
    window.close()
    controller.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def report(identity, stamp, region="Asia", category="Infrastructure", severity="high"):
    return dict(id=identity, event_key=identity, source_id="local-qa-fixture",
                publisher="Fictional test authority", title="Fictional incident " + identity,
                summary="Controlled offline regression fixture.",
                url="https://authority.example/" + identity, published_at=stamp,
                retrieved_at=stamp, region=region, country="", category=category,
                severity=severity, official=True, official_scope="measurement",
                independence="original", origin_id="local-qa-fixture", synthetic=True,
                latitude=30.0, longitude=90.0)


class LocalReply(QNetworkReply):
    """Real Qt reply header/status/error methods; the bytes are local only."""
    def __init__(self, payload=b"", status=200, mime="image/png", error=None, parent=None):
        super().__init__(parent)
        self.payload = payload
        self.aborted = False
        self.setAttribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute, status)
        self.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, mime)
        if error is not None:
            self.setError(error, "Controlled local error")
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def readData(self, maximum):
        data, self.payload = self.payload[:maximum], self.payload[maximum:]
        return data

    def bytesAvailable(self):
        return len(self.payload) + super().bytesAvailable()

    def abort(self):
        self.aborted = True
        self.setError(QNetworkReply.NetworkError.OperationCanceledError, "Controlled cancellation")


def image_bytes(fmt="PNG"):
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(0xff304050)
    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, fmt)
    buffer.close()
    return bytes(data)


def complete_reply(app, *, status=200, mime="image/png", payload=None, error=None):
    CameraSnapshot._images.clear()
    camera = CameraSnapshot(camera_catalog()[0])
    camera._stopped = False
    reply = LocalReply(image_bytes() if payload is None else payload, status, mime, error, camera)
    camera.reply = reply
    camera.deadline.start()
    statuses = []
    camera.status_changed.connect(statuses.append)
    try:
        camera._finished()
        return camera, reply, statuses
    except BaseException:
        camera.stop()
        camera.deleteLater()
        raise


def test_cam001_real_reply_renders_png(app):
    camera, reply, statuses = complete_reply(app)
    try:
        assert camera._pixmap is not None and not camera._pixmap.isNull()
        assert camera.reply is None and not camera.deadline.isActive()
        assert not camera._data
        assert camera.item["id"] in CameraSnapshot._images
        assert "snapshot fetched" in statuses[-1]
    finally:
        camera.stop()
        camera.deleteLater()


@pytest.mark.parametrize("status,mime,payload,error", [
    (200, "image/jpeg", image_bytes("JPEG"), None),
    (404, "image/png", image_bytes(), None),
    (200, "text/html", b"<html>not an image</html>", None),
    (200, "image/png", b"not a PNG", None),
    (200, "image/png", image_bytes(), QNetworkReply.NetworkError.TimeoutError),
    (200, "image/png", b"x" * (CameraSnapshot.MAX_BYTES + 1), None),
])
def test_real_reply_completion_preserves_acceptance_and_cleanup(app, status, mime, payload, error):
    camera, reply, statuses = complete_reply(app, status=status, mime=mime, payload=payload, error=error)
    try:
        accepted = mime == "image/jpeg" and status == 200 and error is None
        assert (camera._pixmap is not None) == accepted
        assert camera.reply is None and not camera.deadline.isActive() and not camera._data
        assert (camera.item["id"] in CameraSnapshot._images) == accepted
        assert "snapshot fetched" in statuses[-1] if accepted else "unavailable" in statuses[-1]
        import shiboken6
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(reply)
    finally:
        camera.stop()
        camera.deleteLater()


def test_map001_selected_region_survives_feed_churn(desktop):
    window, controller = desktop
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=3)).isoformat()
    retained = controller.store.ingest([report("asia", old)], now=old)[0]
    window.refresh_data()
    window.region.setCurrentIndex(window.region.findData("Asia"))
    window.category.setCurrentIndex(window.category.findData("Infrastructure"))
    controller.store.ingest([report(str(i), now.isoformat(), "North America", "Disaster")
                             for i in range(510)], now=now.isoformat())
    for _ in range(3):
        window.refresh_data()
        assert window.region.currentData() == "Asia"
        assert window.category.currentData() == "Infrastructure"
        assert [event["id"] for event in window.world_map.events] == [retained["id"]]


def test_archive_option_query_is_independent_of_feed_pagination(desktop, monkeypatch):
    window, controller = desktop
    stamp = datetime.now(timezone.utc).isoformat()
    controller.store.ingest([report("asia", stamp)], now=stamp)
    monkeypatch.setattr(controller, "events", lambda **kw: pytest.fail("Options must not read a feed page"))
    window._populate_filter_options()
    assert window.region.findData("Asia") >= 0
    assert window.category.findData("Infrastructure") >= 0


def test_empty_archive_does_not_silently_clear_explicit_filters(desktop):
    window, controller = desktop
    window.region.addItem("Asia", "Asia")
    window.region.setCurrentIndex(window.region.findData("Asia"))
    window.category.addItem("Infrastructure", "Infrastructure")
    window.category.setCurrentIndex(window.category.findData("Infrastructure"))
    window._populate_filter_options()
    assert window.region.currentData() == "Asia"
    assert window.category.currentData() == "Infrastructure"
    assert not window.region.signalsBlocked() and not window.category.signalsBlocked()


def test_cam002_campus_in_phoenix_is_not_park_context():
    assert not associated_cameras(dict(title="Grand Canyon University campus disturbance",
                                      region="Phoenix, Arizona", country="United States",
                                      severity="high", status="active"))


@pytest.mark.parametrize("event", [
    {"title": "Grand Canyon University campus alert"},
    {"title": "Grand Canyon wildfire", "region": "Phoenix, Arizona"},
    {"title": "Grand Canyon wildfire", "country": "Canada"},
    {"title": "Kilauea eruption", "region": "Kauai, Hawaii"},
    {"title": "Kilauea hotel fire", "region": "Hawaii"},
    {"title": "Grand", "region": "Canyon"},
])
def test_conflicting_or_ambiguous_area_evidence_fails_closed(event):
    assert not associated_cameras(dict(status="active", **event))


@pytest.mark.parametrize("event", [
    {"title": "Grand Canyon wildfire"},
    {"title": "Yavapai Point smoke", "region": "Grand Canyon National Park, Arizona", "country": "USA"},
    {"title": "Kīlauea eruption", "region": "Hawaii", "country": "United States"},
    {"title": "Halemaʻumaʻu activity", "region": "Hawaii Volcanoes National Park"},
])
def test_consistent_reviewed_area_matches_preserved(event):
    assert len(associated_cameras(dict(status="active", **event))) == 1


def bind_production_shutdown(window, controller):
    from PySide6.QtCore import QTimer
    from global_pulse.__main__ import _ExitCoordinator
    from global_pulse.native_notifications import NativeNotifications
    path = Path(__file__).resolve().parents[1] / "global_pulse" / "__main__.py"
    tree = ast.parse(path.read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    shutdown = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == "shutdown")
    wrapper = ast.parse("def bind():\n    shutting_down = False\n    return shutdown\n")
    wrapper.body[0].body.insert(1, shutdown)
    ast.fix_missing_locations(wrapper)
    observations = []
    coordinator = _ExitCoordinator(controller, NativeNotifications(enabled=False), controller)
    env = dict(window=window, controller=controller, QWidget=QWidget,
               QTimer=QTimer, exit_coordinator=coordinator, exit_warning=None,
               instance=SimpleNamespace(close=lambda: observations.append("instance closed")),
               tray=SimpleNamespace(hide=lambda: observations.append("tray hidden")),
               app=SimpleNamespace(quit=lambda: observations.append("app quit")))
    exec(compile(wrapper, str(path), "exec"), env)
    finish = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == "finish_exit")
    exec(compile(ast.Module(body=[finish], type_ignores=[]), str(path), "exec"), env)
    coordinator.finished.connect(env["finish_exit"])
    return env["bind"](), observations


def test_cam003_actual_exit_body_preserves_consent_and_aborts_requests(desktop, app, monkeypatch):
    window, controller = desktop
    controller.set_setting("auto_event_cameras", True)
    window.media.restore_auto_cameras(True)
    changes = []
    window.media.auto_cameras_changed.connect(changes.append)
    # Replace the manager factory, not a bound method on a C++ QObject.
    # Restoring a bound native method onto a deleted wrapper can retain a
    # self-reference until interpreter teardown. Keep the real reply API.
    from global_pulse import camera_snapshot

    class LocalManager(QObject):
        def get(self, request):
            return reply

    monkeypatch.setattr(camera_snapshot, "QNetworkAccessManager", LocalManager)
    camera = CameraSnapshot(camera_catalog()[0], window.media.tiles[0])
    reply = LocalReply(parent=camera)
    camera._attempts.clear()
    window.media.tiles[0].camera = camera
    camera.start()
    assert camera.reply is reply and camera.timer.isActive()
    callback, observed = bind_production_shutdown(window, controller)
    window.show()
    started = time.monotonic()
    callback()
    assert time.monotonic() - started < .15
    assert not window.isVisible() and "tray hidden" in observed
    assert "instance closed" not in observed, "Singleton must outlive the pending archive commit"
    assert reply.aborted and camera.reply is None and not camera.timer.isActive()
    assert not camera.deadline.isActive()
    # The actual exit body aborts cameras immediately; committed persistence
    # and singleton release complete through Qt's nonblocking exit coordinator.
    for _ in range(300):
        if controller._store_closed and observed[-1:] == ["app quit"]:
            break
        QTest.qWait(10)
    assert controller._store_closed and observed[-1] == "app quit"
    assert observed.index("instance closed") < observed.index("app quit")
    assert changes == []
    reopened = Controller(controller.data_dir, demo=True)
    try:
        assert reopened.get_setting("auto_event_cameras", False) is True
    finally:
        reopened.close()


def test_nontray_window_cleanup_preserves_saved_camera_preference(desktop):
    window, controller = desktop
    controller.set_setting("auto_event_cameras", True)
    window.media.restore_auto_cameras(True)
    window.show()
    window.set_close_handler(None)
    window.close()
    assert controller.get_setting("auto_event_cameras", False) is True


def test_explicit_stop_all_still_revokes_saved_auto_choice(desktop):
    window, controller = desktop
    controller.set_setting("auto_event_cameras", True)
    window.media.restore_auto_cameras(True)
    window.media.stop()
    assert controller.get_setting("auto_event_cameras", True) is False
    assert not window.media.auto_cameras and not window.media.auto_camera_check.isChecked()


def test_shutdown_cleanup_cannot_reconnect_on_late_refresh(app, monkeypatch):
    panel = MediaPanel()
    panel.restore_auto_cameras(True)
    panel.shutdown()
    calls = []
    with monkeypatch.context() as local_patch:
        for tile in panel.tiles:
            local_patch.setattr(tile, "connect_camera", lambda **kwargs: calls.append(kwargs))
        panel.set_event(dict(id="park", title="Grand Canyon wildfire", severity="high", status="active"))
        assert not calls
        assert panel.auto_cameras is True
    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("barrier", ["source_callback", "archive_ingest"])
def test_close_barrier_contention_is_pending_and_retains_admitted_commit(app, tmp_path, barrier):
    controller = Controller(tmp_path, demo=True)
    entered, release = threading.Event(), threading.Event()
    admission_lock = (controller.scheduler._lock if barrier == "source_callback"
                      else controller._ingest_lock)
    worker_errors = []

    def admitted_commit():
        try:
            with admission_lock, controller.store._lock, controller.store._conn:
                controller.store._conn.execute(
                    "INSERT INTO settings VALUES('admitted_shutdown_commit','true')")
                entered.set()
                assert release.wait(4), "Test must release its admitted transaction"
        except BaseException as error:
            worker_errors.append(error)

    writer = threading.Thread(target=admitted_commit, daemon=True)
    writer.start()
    finalizer_errors = []
    settings = {"window_geometry": "pending-drain-layout", "map_layers_visible": True}

    def finish_archive():
        try:
            controller.finish_close(settings)
        except BaseException as error:
            finalizer_errors.append(error)

    attempt = threading.Thread(target=finish_archive, daemon=True)
    try:
        assert entered.wait(1)
        controller.begin_close()
        assert controller.close_ready()
        attempt.start()
        attempt.join(2)
        assert not attempt.is_alive(), "A barrier attempt must remain bounded"
        assert len(finalizer_errors) == 1
        assert type(finalizer_errors[0]) is ShutdownPending
        assert not controller._store_closed and not controller.store._closed
        assert controller._closed and controller.scheduler._stop.is_set()
        # Only the coordinator interprets this typed state as an automatic
        # retry. The finalizer must not roll back an already-admitted write.
        release.set()
        writer.join(1)
        assert not writer.is_alive() and not worker_errors
        finalizer_errors.clear()
        retry = threading.Thread(target=finish_archive, daemon=True)
        retry.start()
        retry.join(2)
        assert not retry.is_alive() and not finalizer_errors
        assert controller._store_closed
        with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as saved:
            assert saved.get_setting("admitted_shutdown_commit") is True
            assert saved.get_setting("window_geometry") == "pending-drain-layout"
            assert saved.get_setting("map_layers_visible") is True
            assert saved._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        release.set()
        writer.join(2)
        if attempt.ident is not None:
            attempt.join(2)
        controller.close()


@pytest.mark.parametrize("failure_type", [OSError, RuntimeError, ValueError])
def test_real_shutdown_persistence_error_is_not_transient_pending(app, tmp_path, monkeypatch, failure_type):
    controller = Controller(tmp_path, demo=True)
    original = controller.store.close_after_shutdown
    failure = failure_type("Controlled durable archive failure")

    def fail_commit(*_args, **_kwargs):
        raise failure

    try:
        controller.begin_close()
        assert controller.close_ready()
        monkeypatch.setattr(controller.store, "close_after_shutdown", fail_commit)
        with pytest.raises(failure_type) as caught:
            controller.finish_close({"window_geometry": "error-retry-layout"})
        assert caught.value is failure and not isinstance(caught.value, ShutdownPending)
        assert not controller._store_closed and not controller.store._closed
        monkeypatch.setattr(controller.store, "close_after_shutdown", original)
        controller.finish_close({"window_geometry": "error-retry-layout"})
        with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as saved:
            assert saved.get_setting("window_geometry") == "error-retry-layout"
    finally:
        monkeypatch.setattr(controller.store, "close_after_shutdown", original)
        controller.close()


def _tray_layout_snapshot(label="captured-layout", **extra):
    return dict(window_geometry=label, vertical_split=[470, 350],
                lower_split=[560, 560, 280], intel_split=[220, 70, 55],
                map_view={"zoom": 2.0, "pan_x": 0.1, "pan_y": 0.0,
                          "density": False, "labels": True},
                map_layers_visible=True, **extra)


def test_tray_layout_snapshot_is_atomic_durable_and_emits_no_dashboard_refresh(app, tmp_path):
    controller = Controller(tmp_path, demo=True)
    signals, saved, errors = [], [], []
    controller.data_changed.connect(lambda: signals.append("data_changed"))
    snapshot = _tray_layout_snapshot(tray_explained=True)

    def persist():
        try:
            saved.append(controller.persist_layout_snapshot(snapshot))
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=persist, daemon=True)
    try:
        worker.start()
        worker.join(2)
        assert not worker.is_alive() and not errors and saved == [True]
        app.processEvents()
        assert signals == [], "Tray layout persistence must not recompose the dashboard"
        assert controller.tray_explained is True
        with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as reopened:
            assert {key: reopened.get_setting(key) for key in snapshot} == snapshot
    finally:
        worker.join(2)
        controller.close()


def test_tray_layout_transaction_failure_rolls_back_every_key_and_cache(app, tmp_path):
    controller = Controller(tmp_path, demo=True)
    baseline = _tray_layout_snapshot("baseline", tray_explained=False)
    try:
        assert controller.persist_layout_snapshot(baseline)
        with controller.store._lock, controller.store._conn:
            controller.store._conn.execute("""
                CREATE TRIGGER reject_layout BEFORE UPDATE ON settings
                WHEN NEW.key='map_view'
                BEGIN SELECT RAISE(ABORT, 'Controlled layout storage failure'); END
            """)
        changed = _tray_layout_snapshot("must-roll-back", tray_explained=True)
        with pytest.raises(sqlite3.IntegrityError, match="Controlled layout storage failure"):
            controller.persist_layout_snapshot(changed)
        assert {key: controller.get_setting(key) for key in baseline} == baseline
        assert controller.tray_explained is False
    finally:
        controller.close()


@pytest.mark.parametrize("correction", [
    {"notifications_enabled": True}, {"close_to_tray": False},
    {"map_view": {"zoom": float("nan")}}, {"vertical_split": [-1, 350]},
    {"map_layers_visible": "true"}, {"tray_explained": "true"},
])
def test_tray_layout_snapshot_rejects_nonlayout_or_invalid_values(app, tmp_path, correction):
    controller = Controller(tmp_path, demo=True)
    try:
        invalid = _tray_layout_snapshot()
        invalid.update(correction)
        with pytest.raises(ValueError):
            controller.persist_layout_snapshot(invalid)
        assert controller.get_setting("window_geometry") is None
        assert controller.tray_explained is False
    finally:
        controller.close()


def test_atomic_settings_snapshot_preserves_existing_size_limit_without_partial_write(tmp_path):
    with Store(tmp_path / "settings.sqlite3", mode="synthetic") as store:
        store.set_setting("first", "original")
        with pytest.raises(ValueError, match="Setting is too large"):
            store.set_settings_atomic({"first": "changed", "oversize": "x" * 250_001})
        assert store.get_setting("first") == "original"
        assert store.get_setting("oversize") is None


def test_close_policy_cache_only_changes_after_successful_persistence(app, tmp_path, monkeypatch):
    controller = Controller(tmp_path, demo=True)
    original = controller.store.set_setting
    try:
        assert controller.close_to_tray_enabled is True and controller.tray_explained is False
        controller.set_setting("close_to_tray", False)
        controller.set_setting("tray_explained", True)
        assert controller.close_to_tray_enabled is False and controller.tray_explained is True

        def fail_write(*_args):
            raise OSError("Controlled policy write failure")

        monkeypatch.setattr(controller.store, "set_setting", fail_write)
        with pytest.raises(OSError):
            controller.set_setting("close_to_tray", True)
        with pytest.raises(OSError):
            controller.set_setting("tray_explained", False)
        assert controller.close_to_tray_enabled is False and controller.tray_explained is True
        monkeypatch.setattr(controller.store, "set_setting", original)
        controller.close()
        reopened = Controller(tmp_path, demo=True)
        try:
            assert reopened.close_to_tray_enabled is False and reopened.tray_explained is True
        finally:
            reopened.close()
    finally:
        monkeypatch.setattr(controller.store, "set_setting", original)
        controller.close()


@pytest.mark.parametrize("already_admitted", [False, True])
def test_exit_latest_layout_wins_over_deferred_tray_save(app, tmp_path, monkeypatch, already_admitted):
    controller = Controller(tmp_path, demo=True)
    old = _tray_layout_snapshot("older-tray-layout", tray_explained=True)
    final = _tray_layout_snapshot("latest-exit-layout")
    entered, release = threading.Event(), threading.Event()
    saved, errors = [], []
    original = controller.store.set_settings_atomic

    def pause_admitted_snapshot(snapshot):
        entered.set()
        assert release.wait(3)
        original(snapshot)

    def hold_store_before_admission():
        with controller.store._lock:
            entered.set()
            assert release.wait(3)

    blocker = None
    if already_admitted:
        monkeypatch.setattr(controller.store, "set_settings_atomic", pause_admitted_snapshot)
    else:
        blocker = threading.Thread(target=hold_store_before_admission, daemon=True)
        blocker.start()
        assert entered.wait(1)

    def save_older():
        try:
            saved.append(controller.persist_layout_snapshot(old))
        except BaseException as error:
            errors.append(error)

    def exit_archive():
        try:
            controller.finish_close(final)
        except BaseException as error:
            errors.append(error)

    writer = threading.Thread(target=save_older, daemon=True)
    finalizer = threading.Thread(target=exit_archive, daemon=True)

    def shutdown_thread_diagnostics():
        # Evaluated only if the unchanged completion assertion fails. Capture
        # only these two workers, allowing either to exit during the snapshot.
        frames = sys._current_frames()
        stacks = {}
        for thread in (writer, finalizer):
            frame = frames.get(thread.ident)
            stacks[thread.name] = ("".join(traceback.format_stack(frame))
                                   if frame is not None else "Thread has already exited")
        return {"worker_stacks": stacks, "errors": [repr(error) for error in errors]}

    try:
        writer.start()
        if already_admitted:
            assert entered.wait(1)
        else:
            # The snapshot worker holds the ingestion barrier while waiting
            # for Store. Exit must still prevent its as-yet-unadmitted write.
            for _ in range(200):
                if not controller._ingest_lock.acquire(blocking=False):
                    break
                controller._ingest_lock.release()
                QTest.qWait(1)
            else:
                pytest.fail("Snapshot worker never reached its admission barrier")
        controller.begin_close()
        assert controller.close_ready()
        finalizer.start()
        release.set()
        writer.join(2)
        finalizer.join(2)
        assert not writer.is_alive() and not finalizer.is_alive() and not errors, shutdown_thread_diagnostics()
        assert saved == [already_admitted]
        assert controller._store_closed
        with Store(tmp_path / "synthetic.sqlite3", mode="synthetic") as reopened:
            assert {key: reopened.get_setting(key) for key in final} == final
            assert reopened._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        release.set()
        writer.join(2)
        if finalizer.ident is not None:
            finalizer.join(2)
        if blocker is not None:
            blocker.join(2)
        monkeypatch.setattr(controller.store, "set_settings_atomic", original)
        controller.close()
