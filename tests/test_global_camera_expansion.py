"""Worldwide reviewed still-image bank and real-widget navigation, all offline.

Provider HTTP/image observations are recorded separately in the source review.
These tests do not claim live availability, video playback or Windows QA.
"""
from __future__ import annotations

from datetime import datetime
import os
import socket
from urllib.parse import urlsplit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import QApplication, QMessageBox

from global_pulse.camera_context import approved_camera, associated_cameras, camera_catalog
from global_pulse.media_widget import _MediaTile
from global_pulse.single_media import MediaPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline camera regression attempted a network/browser action")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(QNetworkAccessManager, "get", forbidden)
    monkeypatch.setattr(QDesktopServices, "openUrl", forbidden)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No)


@pytest.fixture
def panel(app):
    panel = MediaPanel()
    yield panel
    panel.shutdown()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def ids(tile):
    return [tile.selector.itemData(i)["id"] for i in range(tile.selector.count())
            if tile.selector.itemData(i)]


def select_camera(tile, identifier):
    index = next(i for i in range(tile.selector.count())
                 if (tile.selector.itemData(i) or {}).get("id") == identifier)
    tile.selector.setCurrentIndex(index)


def event(title, region="", country=""):
    return dict(id="offline-camera-area", title=title, region=region, country=country,
                status="active", severity="high", synthetic=False)


def test_bank_adds_twelve_sources_and_keeps_unavailable_legacy_entry_honest():
    catalog = camera_catalog()
    assert len(catalog) == 14
    assert len({item["id"] for item in catalog}) == 14
    assert len({item["snapshot_url"] for item in catalog}) == 14
    assert {item["continent"] for item in catalog} == {
        "North America", "South America", "Europe", "Oceania",
    }
    assert {item["country"] for item in catalog} == {"United States", "Chile", "Germany", "New Zealand"}
    responding = [item for item in catalog if item["review_status"] == "recent_image_verified"]
    unavailable = [item for item in catalog if item["review_status"] == "unavailable_at_review"]
    assert len(responding) == 13
    assert [item["id"] for item in unavailable] == ["usgs-kilauea-v1"]
    assert "403" in unavailable[0]["availability"]
    assert "Unavailable" in unavailable[0]["live_status"]
    assert "unavailable" in unavailable[0]["group"].lower()
    for item in responding:
        checked = datetime.fromisoformat(item["last_verified"].replace("Z", "+00:00"))
        modified = datetime.fromisoformat(item["image_last_modified_at_review"].replace("Z", "+00:00"))
        assert 0 <= (checked - modified).total_seconds() <= 20 * 60


def test_every_source_has_exact_https_image_rights_credit_and_dated_review():
    image_hosts = {"www.nps.gov", "volcanoes.usgs.gov", "images.geonet.org.nz",
                   "opendata.dwd.de", "www.eso.org"}
    for item in camera_catalog():
        assert item["type"] == "webcam"
        assert item["refresh_seconds"] == 900
        assert urlsplit(item["snapshot_url"]).hostname in image_hosts
        assert urlsplit(item["snapshot_url"]).path.endswith(".jpg")
        for key in ("url", "snapshot_url", "rights_url"):
            assert item[key].startswith("https://")
            assert "youtube" not in item[key] and "kiwisdr" not in item[key]
        for key in ("attribution", "license", "rights", "availability", "last_verified"):
            assert item[key]
        assert item["area_keywords"] and item["country_keywords"] and item["region_keywords"]
        assert not set(item["area_keywords"]) & {item["country"], item["continent"], "Global"}


def test_geonet_only_grants_reviewed_binary_exception_and_canonical_camera_links():
    geonet = [item for item in camera_catalog() if item["id"].startswith("geonet-")]
    assert len(geonet) == 6
    for item in geonet:
        assert item["allowed_content_types"] == ["image/jpeg", "application/octet-stream"]
        assert item["url"].rsplit("/", 1)[-1] == item["snapshot_url"].rsplit("/", 1)[-1][:-4]
        assert item["license_url"] == "https://creativecommons.org/licenses/by/3.0/nz/"
    for item in camera_catalog():
        if not item["id"].startswith("geonet-"):
            assert "application/octet-stream" not in item.get("allowed_content_types", [])
    supplied = dict(camera_catalog()[0], allowed_content_types=["application/octet-stream"])
    assert "application/octet-stream" not in approved_camera(supplied).get("allowed_content_types", [])
    assert approved_camera(dict(geonet[0], snapshot_url="https://example.org/injected.jpg")) is None


def test_both_ruapehu_views_remain_selectable_even_with_shared_source_page(app):
    # Same-camera event/catalog duplication collapses, but two approved image
    # identities must not collapse just because they share an operator page.
    cameras = [dict(item, url="https://www.geonet.org.nz/volcano/cameras")
               for item in camera_catalog() if item["id"].startswith("geonet-ruapehu-")]
    tile = _MediaTile()
    try:
        tile.media = cameras[:1]
        tile.set_catalog(cameras)
        assert ids(tile) == ["geonet-ruapehu-north", "geonet-ruapehu-south"]
        assert tile.select_relative(1)
        assert tile._current()["id"] == "geonet-ruapehu-south"
        assert tile.camera is None
    finally:
        tile.stop()
        tile.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("title,region,country,expected", [
    ("Mount Ruapehu conditions", "North Island, New Zealand", "NZ", {"geonet-ruapehu-north", "geonet-ruapehu-south"}),
    ("Taranaki Maunga cloud", "New Zealand", "New Zealand", {"geonet-taranaki"}),
    ("Mount Tongariro activity", "North Island", "NZ", {"geonet-tongariro"}),
    ("Whakaari conditions", "Bay of Plenty", "NZ", {"geonet-whakaari-tekaha"}),
    ("Raoul Island conditions", "Kermadec Islands", "New Zealand", {"geonet-raoul-island"}),
    ("Hohenpeißenberg weather", "Bavaria, Germany", "DE", {"dwd-hohenpeissenberg"}),
    ("Warnemünde weather", "Germany", "DE", {"dwd-warnemuende"}),
    ("Cerro Paranal weather", "Antofagasta, Chile", "CL", {"eso-paranal-panorama"}),
])
def test_new_named_areas_match_only_their_reviewed_geography(title, region, country, expected):
    found = associated_cameras(event(title, region, country))
    assert {item["id"] for item in found} == expected
    assert all("not evidence" in item["association"] for item in found)


@pytest.mark.parametrize("title,region,country", [
    ("New Zealand weather", "New Zealand", "NZ"),
    ("Taranaki regional weather", "Taranaki", "NZ"),
    ("Lindenberg weather", "Germany", "DE"),
    ("European storm", "Europe", ""),
    ("Atacama Desert weather", "Chile", "CL"),
    ("White Island weather", "Global", ""),
    ("Mount Ruapehu weather", "North Island", "Germany"),
    ("Ruapehu and Grand Canyon weather", "Global", ""),
    ("Taranaki Maunga update", "Cerro Paranal", "NZ"),
    ("Ruapehu University announcement", "New Zealand", "NZ"),
])
def test_new_areas_do_not_expand_ambiguous_or_conflicting_association(title, region, country):
    assert associated_cameras(event(title, region, country)) == []


def test_bank_visible_at_start_without_event_network_or_tv(panel):
    assert panel.tabs.currentWidget() is panel.radio
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == ["Radio", "Cameras"]
    assert len(ids(panel.camera)) == 14
    assert ids(panel.camera)[-1] == "usgs-kilauea-v1"
    assert "available manually" in panel.camera_status.text()
    assert "13 responded at the dated review; 1 unavailable" in panel.camera_status.text()
    assert "not continuous video" in panel.camera_status.text()
    assert not panel.auto_cameras and panel.camera.camera is None
    assert panel.radio._session is None


def test_search_and_region_filter_no_match_and_restore(panel):
    panel.camera_region.setCurrentText("Oceania")
    assert len(ids(panel.camera)) == 6
    panel.camera_search.setText("ruapehu")
    assert ids(panel.camera) == ["geonet-ruapehu-north", "geonet-ruapehu-south"]
    panel.camera_search.setText("Germany")
    assert ids(panel.camera) == [] and panel.camera._current() == {}
    assert "No reviewed camera matches" in panel.camera_attribution.text()
    panel.camera_region.setCurrentIndex(0)
    assert len(ids(panel.camera)) == 5
    panel.camera_search.setText("schmucke")
    assert ids(panel.camera) == ["dwd-schmuecke"]
    panel.camera_search.setText("Hohenpeissenberg")
    assert ids(panel.camera) == ["dwd-hohenpeissenberg"]
    panel.camera_search.clear()
    assert len(ids(panel.camera)) == 14
    assert panel.camera.camera is None


def test_filter_preserves_selected_camera_when_visible(panel):
    select_camera(panel.camera, "geonet-ruapehu-south")
    panel.camera_search.setText("GeoNet")
    assert panel.camera._current()["id"] == "geonet-ruapehu-south"
    panel.camera_search.clear()
    assert panel.camera._current()["id"] == "geonet-ruapehu-south"


def test_filters_never_autoconnect_even_when_auto_event_consent_exists(panel, monkeypatch):
    started = []
    monkeypatch.setattr(panel.camera, "connect_camera", lambda **kw: started.append(kw))
    panel.set_event(event("Mount Ruapehu conditions", "New Zealand", "NZ"))
    panel.tabs.setCurrentIndex(1)
    panel.restore_auto_cameras(True)
    panel.camera_region.setCurrentText("Oceania")
    panel.camera_search.setText("Ruapehu")
    panel.camera_search.clear()
    panel.camera.select_relative(1)
    assert started == []
    panel.stop()
    panel.camera_search.setText("GeoNet")
    assert started == [] and not panel.auto_cameras


def test_selected_credit_license_and_unavailable_status_visible(panel):
    select_camera(panel.camera, "eso-paranal-panorama")
    assert "ESO" in panel.camera_attribution.text()
    assert 'href="https://www.eso.org/public/outreach/webcams/"' in panel.camera_attribution.text()
    assert "CC BY 4.0" in panel.camera_attribution.text()
    assert "Checked 2026-11-22" in panel.camera_attribution.text()
    select_camera(panel.camera, "usgs-kilauea-v1")
    assert "Unavailable at review" in panel.camera_attribution.text()
    assert "403" in panel.camera_attribution.toolTip()


def test_feed_supplied_attribution_and_license_never_create_links(panel):
    supplied = dict(camera_catalog()[0], attribution="<script>bad</script>",
                    license="Injected", license_url="javascript:alert(1)")
    panel.camera.selector.addItem("Forced untrusted extra fields", supplied)
    panel.camera.selector.setCurrentIndex(panel.camera.selector.count() - 1)
    assert "U.S. National Park Service" in panel.camera_attribution.text()
    assert "script" not in panel.camera_attribution.text()
    assert "Injected" not in panel.camera_attribution.text()


def test_event_matching_stays_filtered_and_does_not_restart_radio(panel):
    panel.camera_region.setCurrentText("Europe")
    panel.set_event(event("Ruapehu conditions", "New Zealand", "NZ"))
    assert len(ids(panel.camera)) == 5
    assert all(identifier.startswith("dwd-") for identifier in ids(panel.camera))
    assert "none match selected event" in panel.camera_status.text()
    assert panel.radio._session is None and panel.camera.camera is None
