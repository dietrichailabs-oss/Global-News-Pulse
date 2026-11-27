"""Offline selector/lifecycle regression using real widgets and inert players.

These tests establish manual routing, cancellation, retry and stale-status
handling. They never establish Windows embedding, codecs or provider playback.
"""
from __future__ import annotations

import os
import socket

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from global_pulse.camera_context import camera_catalog
from global_pulse.camera_snapshot import CameraSnapshot as RealSnapshot
from global_pulse.single_media import MediaPanel


LIVE_IDS = {"gpc-tannum-sands-live", "gpc-1770-live", "bsyc-seacliff-live"}


class FakeLiveCamera(QWidget):
    status_changed = Signal(str)
    instances = []

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = dict(item)
        self.active = False
        self.closed = False
        self.start_count = 0
        self.stop_count = 0
        self.__class__.instances.append(self)

    def start(self):
        if self.closed:
            return False
        self.active = True
        self.start_count += 1
        self.status_changed.emit("Opening original camera page; video not verified")
        return True

    def stop(self):
        self.active = False
        self.stop_count += 1

    def shutdown(self):
        self.closed = True
        self.stop()


class FakeSnapshot(FakeLiveCamera):
    instances = []
    _images = {}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline camera integration test attempted network/browser access")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(QNetworkAccessManager, "get", forbidden)
    monkeypatch.setattr(QDesktopServices, "openUrl", forbidden)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    import global_pulse.live_camera as live_camera
    import global_pulse.camera_snapshot as camera_snapshot
    FakeLiveCamera.instances = []
    FakeSnapshot.instances = []
    FakeSnapshot._images = {}
    monkeypatch.setattr(live_camera, "LiveCamera", FakeLiveCamera)
    monkeypatch.setattr(camera_snapshot, "CameraSnapshot", FakeSnapshot)


@pytest.fixture
def panel(app):
    widget = MediaPanel()
    yield widget
    widget.shutdown()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def select_camera(panel, identifier):
    tile = panel.camera
    index = next(i for i in range(tile.selector.count())
                 if (tile.selector.itemData(i) or {}).get("id") == identifier)
    tile.selector.setCurrentIndex(index)
    return tile


def snapshot_id():
    return next(row["id"] for row in camera_catalog() if row.get("snapshot_url"))


def test_three_manual_live_choices_exist_without_creating_a_backend(panel):
    live = [row for row in camera_catalog() if row.get("playback") == "live_video"]
    assert {row["id"] for row in live} == LIVE_IDS
    assert panel.camera.selector.count() == 17
    assert len([row for row in camera_catalog() if row.get("snapshot_url")]) == 14
    for identifier in sorted(LIVE_IDS):
        select_camera(panel, identifier)
        assert not FakeLiveCamera.instances and not FakeSnapshot.instances
        assert "image responded at review" not in panel.camera_attribution.text().lower()
    assert panel.radio._session is None


def test_declined_connection_never_creates_player(panel, monkeypatch):
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    assert tile.watch() is False
    assert not FakeLiveCamera.instances and not FakeSnapshot.instances


def test_failed_native_start_leaves_no_connected_player(panel, monkeypatch):
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    monkeypatch.setattr(FakeLiveCamera, "start", lambda self: False)
    assert tile.watch() is False
    player = FakeLiveCamera.instances[-1]
    assert not player.active and player.stop_count >= 1
    assert tile.camera is None and tile.camera_id is None
    assert "Source" in tile.note.text()


def test_native_start_error_is_visible_without_playback_claim(panel, monkeypatch):
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    def failed(_self):
        raise RuntimeError("Required Windows camera runtime unavailable")
    monkeypatch.setattr(FakeLiveCamera, "start", failed)
    assert tile.watch() is False and tile.camera is None
    assert "Required Windows camera runtime unavailable" in tile.note.text()
    assert "Source" in tile.note.text()


@pytest.mark.parametrize("identifier", sorted(LIVE_IDS))
def test_live_connect_routes_only_to_live_backend(panel, identifier):
    tile = select_camera(panel, identifier)
    assert tile.watch() is True
    assert len(FakeLiveCamera.instances) == 1 and not FakeSnapshot.instances
    player = FakeLiveCamera.instances[0]
    assert player.item["id"] == identifier and player.active and player.start_count == 1
    assert not player.item.get("snapshot_url")


def test_async_failure_can_retry_once_while_active_connect_is_idempotent(panel, monkeypatch):
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    consent_calls = []
    def consent(*args, **kwargs):
        consent_calls.append(True)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", consent)
    assert tile.watch() is True
    old = FakeLiveCamera.instances[-1]
    assert tile.watch() is True and len(FakeLiveCamera.instances) == 1
    assert consent_calls == [True]
    old.active = False
    old.status_changed.emit("Camera page timed out; use Source")
    assert "timed out" in tile.note.text()
    assert tile.watch() is True
    current = FakeLiveCamera.instances[-1]
    assert current is not old and current.active and current.start_count == 1
    assert len(FakeLiveCamera.instances) == 2 and consent_calls == [True, True]
    expected = tile.note.text()
    old.status_changed.emit("LATE_OLD_CAMERA_PLAYING")
    assert tile.note.text() == expected
    assert tile.watch() is True and len(FakeLiveCamera.instances) == 2


def test_snapshot_connect_remains_idempotent(panel):
    tile = select_camera(panel, snapshot_id())
    assert tile.watch() is True
    original = tile.camera
    assert tile.watch() is True and tile.camera is original
    assert len(FakeSnapshot.instances) == 1 and original.start_count == 1


@pytest.mark.parametrize("kind", ["live", "snapshot"])
def test_shutdown_during_consent_cannot_start_a_player(panel, monkeypatch, kind):
    tile = select_camera(panel, sorted(LIVE_IDS)[0] if kind == "live" else snapshot_id())
    def consent(*args, **kwargs):
        panel.shutdown()
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", consent)
    assert tile.watch() is False
    assert tile.camera is None and not FakeLiveCamera.instances and not FakeSnapshot.instances


@pytest.mark.parametrize("kind", ["live", "snapshot"])
def test_selection_change_during_consent_rejects_old_request(panel, monkeypatch, kind):
    identifier = sorted(LIVE_IDS)[0] if kind == "live" else snapshot_id()
    tile = select_camera(panel, identifier)
    replacement = sorted(LIVE_IDS)[1] if kind == "live" else next(
        row["id"] for row in camera_catalog() if row.get("snapshot_url") and row["id"] != identifier)
    def consent(*args, **kwargs):
        select_camera(panel, replacement)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", consent)
    assert tile.watch() is False
    assert not FakeLiveCamera.instances and not FakeSnapshot.instances
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert tile.watch() is True and tile.camera.item["id"] == replacement


@pytest.mark.parametrize("kind", ["live", "snapshot"])
@pytest.mark.parametrize("action", ["stop", "hide"])
def test_stop_or_hide_during_consent_cancels_but_allows_later_manual_retry(panel, app, monkeypatch, kind, action):
    panel.tabs.setCurrentWidget(panel.camera_page)
    panel.show()
    app.processEvents()
    tile = select_camera(panel, sorted(LIVE_IDS)[0] if kind == "live" else snapshot_id())
    def consent(*args, **kwargs):
        if action == "hide":
            panel.hide()
        else:
            tile.user_stop()
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", consent)
    assert tile.watch() is False
    assert not FakeLiveCamera.instances and not FakeSnapshot.instances
    panel.show()
    app.processEvents()
    assert not FakeLiveCamera.instances and not FakeSnapshot.instances
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert tile.watch() is True and tile.camera.active


@pytest.mark.parametrize("identifier", sorted(LIVE_IDS))
def test_snapshot_auto_consent_cannot_start_live_video(panel, identifier):
    tile = select_camera(panel, identifier)
    panel.restore_auto_cameras(True)
    panel.tabs.setCurrentWidget(panel.camera_page)
    assert tile.connect_camera(auto_consented=True) is False
    assert not FakeLiveCamera.instances and not FakeSnapshot.instances


def test_selection_switch_disconnects_old_live_and_does_not_start_new(panel):
    first, second = sorted(LIVE_IDS)[:2]
    tile = select_camera(panel, first)
    assert tile.watch() is True
    old = tile.camera
    select_camera(panel, second)
    assert not old.active and old.stop_count >= 1
    assert len(FakeLiveCamera.instances) == 1
    assert tile.watch() is True
    current = tile.camera
    expected = tile.note.text()
    old.status_changed.emit("LATE_OLD_CAMERA_PLAYING")
    assert current is not old and current.item["id"] == second and tile.note.text() == expected


def test_stop_ignores_late_status_and_manual_selection_does_not_restart(panel):
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    assert tile.watch() is True
    player = tile.camera
    tile.user_stop()
    expected = tile.note.text()
    player.status_changed.emit("LATE_STOPPED_CAMERA_LOADED")
    assert not player.active and tile.note.text() == expected
    tile.select_relative(1)
    tile.select_relative(-1)
    assert len(FakeLiveCamera.instances) == 1


def test_radio_tab_switch_stops_live_and_returning_does_not_resume(panel):
    panel.tabs.setCurrentWidget(panel.camera_page)
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    assert tile.watch() is True
    player = tile.camera
    panel.tabs.setCurrentWidget(panel.radio)
    assert not player.active
    panel.tabs.setCurrentWidget(panel.camera_page)
    assert len(FakeLiveCamera.instances) == 1 and not player.active


def test_hiding_panel_stops_live_and_showing_does_not_resume(panel, app):
    panel.tabs.setCurrentWidget(panel.camera_page)
    panel.show()
    app.processEvents()
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    assert tile.watch() is True
    player = tile.camera
    panel.hide()
    assert not player.active
    panel.show()
    app.processEvents()
    assert len(FakeLiveCamera.instances) == 1 and not player.active


def test_shutdown_is_terminal_for_direct_connect_calls(panel):
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    assert tile.watch() is True
    player = tile.camera
    panel.shutdown()
    assert tile.watch() is False and tile.connect_camera() is False
    assert not player.active and len(FakeLiveCamera.instances) == 1


def test_live_and_snapshot_switching_keep_separate_backends(panel):
    tile = select_camera(panel, sorted(LIVE_IDS)[0])
    assert tile.watch() is True
    live = tile.camera
    select_camera(panel, snapshot_id())
    assert not live.active
    assert tile.watch() is True
    assert len(FakeLiveCamera.instances) == len(FakeSnapshot.instances) == 1
    assert isinstance(tile.camera, FakeSnapshot)


def test_snapshot_backend_refuses_live_rows_before_network(panel):
    item = next(row for row in camera_catalog() if row.get("playback") == "live_video")
    with pytest.raises(ValueError, match="snapshot"):
        RealSnapshot(item, panel)


@pytest.mark.parametrize("auto", [False, True])
def test_news_reordering_does_not_disconnect_manual_live_camera(panel, auto):
    panel.tabs.setCurrentWidget(panel.camera_page)
    panel.restore_auto_cameras(auto)
    tile = select_camera(panel, "gpc-1770-live")
    assert tile.watch() is True
    player = tile.camera
    status = tile.note.text()
    for event in (
        {"id": "nz", "title": "Mount Ruapehu volcanic activity", "severity": "high"},
        {"id": "us", "title": "Grand Canyon wildfire", "severity": "high"},
        None,
    ):
        panel.set_event(event)
        assert tile._current()["id"] == "gpc-1770-live"
        assert tile.camera is player and player.active
        assert player.start_count == 1 and player.stop_count == 0
        assert tile.note.text() == status
    assert len(FakeLiveCamera.instances) == 1 and not FakeSnapshot.instances


def test_live_filter_keeps_selected_session_but_snapshots_filter_stops_it(panel):
    tile = select_camera(panel, "gpc-1770-live")
    assert tile.watch() is True
    player = tile.camera
    panel.camera_kind.setCurrentIndex(panel.camera_kind.findData("live_video"))
    assert tile._current()["id"] == "gpc-1770-live"
    assert tile.camera is player and player.active
    assert tile.selector.count() == len(LIVE_IDS)
    panel.camera_kind.setCurrentIndex(panel.camera_kind.findData("snapshot"))
    assert tile.camera is None and not player.active
    assert tile.selector.count() == 14
    assert all(tile.selector.itemData(i).get("snapshot_url") for i in range(14))
    assert len(FakeLiveCamera.instances) == 1 and not FakeSnapshot.instances


def test_live_filter_composes_with_search_and_region_without_autoplay(panel):
    panel.camera_kind.setCurrentIndex(panel.camera_kind.findData("live_video"))
    panel.camera_search.setText("1770")
    assert panel.camera.selector.count() == 1
    assert panel.camera._current()["id"] == "gpc-1770-live"
    assert "1 / 17" in panel.camera_status.text()
    panel.camera_region.setCurrentIndex(panel.camera_region.findData("Europe"))
    assert panel.camera._current() == {}
    assert "0 / 17" in panel.camera_status.text()
    assert not FakeLiveCamera.instances and not FakeSnapshot.instances


def test_live_consent_survives_news_reordering_not_removal(panel, monkeypatch):
    tile = select_camera(panel, "gpc-1770-live")
    def consent(*args, **kwargs):
        panel.set_event({"id": "nz", "title": "Mount Ruapehu volcanic activity", "severity": "high"})
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", consent)
    assert tile.watch() is True
    assert tile.camera.item["id"] == "gpc-1770-live"
    tile.user_stop()
    def remove(*args, **kwargs):
        panel.camera_kind.setCurrentIndex(panel.camera_kind.findData("snapshot"))
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", remove)
    assert tile.watch() is False
    assert tile.camera is None and len(FakeLiveCamera.instances) == 1
