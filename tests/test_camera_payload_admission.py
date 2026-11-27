"""Reviewed MIME exceptions do not widen the public-camera trust boundary."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QByteArray, QBuffer, QCoreApplication, QEvent, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication

from global_pulse.camera_context import camera_catalog
from global_pulse.camera_snapshot import CameraSnapshot
import global_pulse.camera_snapshot as snapshots


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class LocalReply(QNetworkReply):
    """Inert real Qt reply; no socket or provider access."""
    def __init__(self, payload, mime, status=200, parent=None):
        super().__init__(parent)
        self.payload = payload
        self.aborted = False
        self.setAttribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute, status)
        self.setRawHeader(b"Content-Type", mime.encode("ascii"))
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def readData(self, maximum):
        result, self.payload = self.payload[:maximum], self.payload[maximum:]
        return result

    def bytesAvailable(self):
        return len(self.payload) + super().bytesAvailable()

    def abort(self):
        self.aborted = True
        self.setError(QNetworkReply.NetworkError.OperationCanceledError, "Offline cancellation")


def encoded_image(fmt):
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(0xff304050)
    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, fmt)
    buffer.close()
    return bytes(data)


def complete(camera, payload, mime, status=200):
    camera._stopped = False
    camera.reply = LocalReply(payload, mime, status, camera)
    camera._finished()
    return camera._pixmap is not None


def cleanup(camera, app):
    camera.stop()
    camera.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    CameraSnapshot._images.clear()
    CameraSnapshot._attempts.clear()


@pytest.mark.parametrize("fmt,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png")])
def test_original_image_mime_and_signature_still_render(app, fmt, mime):
    camera = CameraSnapshot(camera_catalog()[0])
    try:
        assert complete(camera, encoded_image(fmt), mime)
        assert camera.item["id"] in CameraSnapshot._images
        assert camera.reply is None and not camera._data
    finally:
        cleanup(camera, app)


@pytest.mark.parametrize("payload,mime", [
    (encoded_image("JPEG"), "application/octet-stream"),
    (encoded_image("JPEG"), "text/html"),
    (encoded_image("PNG"), "image/jpeg"),
    (encoded_image("JPEG"), "image/png"),
    (b"<svg xmlns='http://www.w3.org/2000/svg' width='3' height='2'/>", "image/png"),
    (b"GIF89a\x03\x00\x02\x00", "image/jpeg"),
])
def test_unreviewed_or_mismatched_binary_cannot_render(app, payload, mime):
    camera = CameraSnapshot(camera_catalog()[0])
    try:
        assert not complete(camera, payload, mime)
        assert camera.item["id"] not in CameraSnapshot._images
    finally:
        cleanup(camera, app)


def test_event_fields_cannot_grant_binary_exception(app):
    supplied = dict(camera_catalog()[0], allowed_content_types=["application/octet-stream"])
    camera = CameraSnapshot(supplied)
    try:
        assert camera.item.get("allowed_content_types") != ["application/octet-stream"]
        assert not complete(camera, encoded_image("JPEG"), "application/octet-stream")
    finally:
        cleanup(camera, app)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_only_canonical_reviewed_registry_can_allow_binary_mime(app, monkeypatch, fmt):
    reviewed = dict(camera_catalog()[0], allowed_content_types=["application/octet-stream"])
    monkeypatch.setattr(snapshots, "approved_camera", lambda item: reviewed)
    camera = CameraSnapshot(reviewed)
    try:
        assert complete(camera, encoded_image(fmt), "application/octet-stream; charset=binary")
        assert camera.item["id"] in CameraSnapshot._images
    finally:
        cleanup(camera, app)


@pytest.mark.parametrize("payload,status", [
    (b"<html>upstream unavailable</html>", 200),
    (b"\xff\xd8\xffnot-a-decodable-jpeg", 200),
    (encoded_image("JPEG"), 302),
    (encoded_image("JPEG"), 403),
    (b"\xff\xd8\xff" + b"x" * CameraSnapshot.MAX_BYTES, 200),
])
def test_reviewed_binary_exception_keeps_payload_size_status_and_decode_checks(app, monkeypatch, payload, status):
    reviewed = dict(camera_catalog()[0], allowed_content_types=["application/octet-stream"])
    monkeypatch.setattr(snapshots, "approved_camera", lambda item: reviewed)
    camera = CameraSnapshot(reviewed)
    try:
        assert not complete(camera, payload, "application/octet-stream", status)
        assert camera.reply is None and not camera._data
        assert camera.item["id"] not in CameraSnapshot._images
    finally:
        cleanup(camera, app)


def test_stop_rejects_late_binary_reply(app, monkeypatch):
    reviewed = dict(camera_catalog()[0], allowed_content_types=["application/octet-stream"])
    monkeypatch.setattr(snapshots, "approved_camera", lambda item: reviewed)
    camera = CameraSnapshot(reviewed)
    try:
        camera._stopped = False
        reply = LocalReply(encoded_image("JPEG"), "application/octet-stream", parent=camera)
        camera.reply = reply
        camera.stop()
        camera._finished()
        assert reply.aborted and camera.reply is None
        assert camera._pixmap is None and camera.item["id"] not in CameraSnapshot._images
    finally:
        cleanup(camera, app)
