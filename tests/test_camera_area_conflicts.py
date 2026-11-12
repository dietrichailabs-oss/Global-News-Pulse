"""GP-OF-CAM-002 residual: contradictory reviewed areas must not auto-connect.

Engineering source regressions. Real Qt panel/reply objects use an inert,
parent-owned manager factory: no sockets, provider or Windows execution.
"""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QIODevice, QObject
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication, QMessageBox

from global_pulse.camera_context import associated_cameras, camera_catalog
from global_pulse.camera_snapshot import CameraSnapshot
from global_pulse.media_widget import MediaPanel
import global_pulse.camera_snapshot as snapshots


CONFLICTS = [
    ("QA fixture: Kilauea eruption", "Grand Canyon National Park, Arizona"),
    ("QA fixture: Grand Canyon wildfire", "Kilauea summit, Hawaii"),
    ("QA fixture: Kīlauea eruption", "Yavapai Point, AZ"),
    ("QA fixture: Halemaʻumaʻu activity", "Grand Canyon, Arizona"),
    ("QA fixture: Kaluapele and Grand Canyon", "Global"),
    ("QA fixture: Kilauea and Yavapai Point", "Grand Canyon National Park, Arizona"),
]


def event(title, region):
    # Live-shaped but wholly fictional input in an isolated test process.
    return dict(id="local-area-conflict", title=title, region=region, country="US",
                status="active", severity="high", synthetic=False)


@pytest.mark.parametrize("title,region", CONFLICTS)
@pytest.mark.parametrize("reverse_catalog", [False, True])
def test_conflicting_reviewed_areas_never_select_one_by_catalog_order(title, region, reverse_catalog):
    catalog = camera_catalog()
    if reverse_catalog:
        catalog.reverse()
    assert associated_cameras(event(title, region), catalog) == []


@pytest.mark.parametrize("title,region,expected", [
    ("QA fixture: Grand Canyon wildfire", "Grand Canyon National Park, Arizona", "nps-grand-canyon-yavapai"),
    ("QA fixture: Yavapai Point storm", "Grand Canyon, AZ", "nps-grand-canyon-yavapai"),
    ("QA fixture: Kilauea eruption", "Kilauea summit, Hawaii", "usgs-kilauea-v1"),
    ("QA fixture: Kīlauea and Halemaʻumaʻu", "Kaluapele, Hawaii", "usgs-kilauea-v1"),
    ("QA fixture: eruption update", "Kilauea summit, Hawaii", "usgs-kilauea-v1"),
    ("QA fixture: Grand Canyon conditions", "", "nps-grand-canyon-yavapai"),
])
def test_consistent_named_area_and_aliases_remain_eligible(title, region, expected):
    found = associated_cameras(event(title, region))
    assert [item["id"] for item in found] == [expected]
    assert "not evidence" in found[0]["association"]


def test_multiple_cameras_with_same_area_aliases_are_not_a_conflict():
    catalog = camera_catalog()
    second = dict(catalog[0], id="local-only-same-area-camera")
    # Matcher-only fixture; approved_camera still rejects this invented endpoint ID.
    found = associated_cameras(event("Grand Canyon / Yavapai Point", "Arizona"), catalog + [second])
    assert [item["id"] for item in found] == [catalog[0]["id"], second["id"]]


@pytest.mark.parametrize("title,region", [
    ("QA fixture: Grand", "Canyon"),
    ("QA fixture: notKilauea and Grand Canyonish", "Global"),
])
def test_matching_stays_within_word_and_field_boundaries(title, region):
    assert associated_cameras(event(title, region)) == []


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class LocalReply(QNetworkReply):
    def __init__(self, parent):
        super().__init__(parent)
        self.open(QIODevice.OpenModeFlag.ReadOnly)
        self.aborted = False

    def readData(self, maximum):
        return b""

    def abort(self):
        self.aborted = True
        self.setError(QNetworkReply.NetworkError.OperationCanceledError, "Local controlled cancellation")


@pytest.mark.parametrize("title,region", CONFLICTS[:2])
def test_actual_auto_camera_panel_constructs_no_request_for_conflict(app, monkeypatch, title, region):
    requests = []

    class LocalManager(QObject):
        def get(self, request):
            reply = LocalReply(self)
            requests.append((request.url().toString(), reply))
            return reply

    monkeypatch.setattr(snapshots, "QNetworkAccessManager", LocalManager)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    CameraSnapshot._attempts.clear()
    CameraSnapshot._images.clear()
    panel = MediaPanel()
    try:
        panel.auto_camera_check.setChecked(True)
        assert panel.auto_cameras
        panel.set_event(event(title, region))
        assert panel._camera_matches == []
        assert not requests
        assert all(tile.camera is None for tile in panel.tiles)
        assert "No reviewed camera" in panel.camera_status.text()
        # A subsequent consistent selection can connect under the same consent;
        # the fix must not disable the feature to satisfy the negative case.
        panel.set_event(event("QA fixture: Grand Canyon wildfire", "Grand Canyon National Park, Arizona"))
        assert len(requests) == 1
        assert requests[0][0] == camera_catalog()[0]["snapshot_url"]
        assert panel.tiles[0].camera is not None
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        CameraSnapshot._attempts.clear()
        CameraSnapshot._images.clear()
