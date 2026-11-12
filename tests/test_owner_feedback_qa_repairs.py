"""Engineering regressions for four GP-QA-E2-0A174915-001 findings.

Actual Qt widgets/reply API and SQLite; no provider/model/native-Windows access.
The shutdown case executes the unchanged nested production shutdown function,
with only OS tray/notifier/single-instance and application-exit surfaces stubbed.
"""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QEvent, QIODevice, QObject
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QWidget

from global_pulse.camera_context import associated_cameras, camera_catalog
from global_pulse.camera_snapshot import CameraSnapshot
from global_pulse.controller import Controller
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
    path = Path(__file__).resolve().parents[1] / "global_pulse" / "__main__.py"
    tree = ast.parse(path.read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    shutdown = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == "shutdown")
    wrapper = ast.parse("def bind():\n    shutting_down = False\n    return shutdown\n")
    wrapper.body[0].body.insert(1, shutdown)
    ast.fix_missing_locations(wrapper)
    observations = []
    env = dict(window=window, controller=controller, QWidget=QWidget,
               notifier=SimpleNamespace(stop=lambda: observations.append("notifier stopped")),
               instance=SimpleNamespace(close=lambda: observations.append("instance closed")),
               tray=SimpleNamespace(hide=lambda: observations.append("tray hidden")),
               app=SimpleNamespace(quit=lambda: observations.append("app quit")))
    exec(compile(wrapper, str(path), "exec"), env)
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
    callback()
    assert reply.aborted and camera.reply is None and not camera.timer.isActive()
    assert not camera.deadline.isActive()
    assert controller._store_closed and observed[-1] == "app quit"
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
