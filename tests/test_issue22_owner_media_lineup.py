"""Owner-observed media lineup regressions for the physical Windows candidate.

Offline only: no stream, YouTube, camera, WebSDR or KiwiSDR connection occurs.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication,QMessageBox

from global_pulse.internet_radio import STATIONS,HAM_DIRECTORIES,RadioPanel
from global_pulse.single_media import Television,MediaPanel
from global_pulse.sources import load_media_catalog
from global_pulse.camera_context import camera_catalog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_direct_radio_lineup_is_expanded_and_documented():
    assert len(STATIONS) >= 9
    ids={item["id"] for item in STATIONS}
    assert {"wnyc_fm","wnyc_am","wqxr","new_sounds","operavore",
            "deutschlandfunk","deutschlandfunk_kultur",
            "deutschlandfunk_nova","deutschlandfunk_debatten"} <= ids
    for item in STATIONS:
        assert item["url"].startswith("https://")
        assert item["documentation"].startswith("https://")


def test_ham_sdr_receiver_directories_are_visible_without_starting_audio(app):
    panel=RadioPanel(confirm=lambda:False)
    try:
        assert panel.ham_selector.count()==len(HAM_DIRECTORIES)==2
        assert {panel.ham_selector.itemData(i)["id"] for i in range(panel.ham_selector.count())}=={"websdr","kiwisdr"}
        assert panel.status.text()=="OFF"
        assert panel._session is None
    finally:
        panel.shutdown();panel.deleteLater();app.processEvents()


def test_in_app_sdr_accepts_only_specific_public_https_receiver(app,monkeypatch):
    panel=RadioPanel(confirm=lambda:False)

    class FakeView:
        def __init__(self):
            self.loaded=[];self.shown=False;self.stopped=False;self.blank=False;self.deleted=False
        def load(self,url):
            self.loaded.append(url.toString())
        def show(self):
            self.shown=True
        def stop(self):
            self.stopped=True
        def setUrl(self,url):
            self.blank=url.toString()=="about:blank"
        def hide(self):
            pass
        def deleteLater(self):
            self.deleted=True

    try:
        monkeypatch.setattr(QMessageBox,"question",lambda *a,**k:QMessageBox.StandardButton.Yes)
        fake=FakeView()
        def ensure(host):
            assert host=="receiver.example.org"
            panel.receiver_host=host
            panel.receiver_view=fake
        monkeypatch.setattr(panel,"_ensure_receiver_view",ensure)

        panel.receiver_url.setText("https://receiver.example.org/")
        assert panel.connect_receiver()
        assert panel.receiver_connected
        assert fake.loaded==["https://receiver.example.org/"]
        assert fake.shown

        panel.disconnect_receiver()
        assert not panel.receiver_connected
        assert fake.stopped and fake.blank and fake.deleted
        assert panel.receiver_view is None
    finally:
        panel.shutdown();panel.deleteLater();app.processEvents()


@pytest.mark.parametrize("bad",[
    "http://receiver.example.org/",
    "https://receiver.example.org:8073/",
    "https://127.0.0.1/",
    "https://localhost/",
    "file:///etc/passwd",
    "javascript:alert(1)",
])
def test_in_app_sdr_rejects_unreviewed_transport_or_local_targets(app,bad):
    panel=RadioPanel(confirm=lambda:False)
    try:
        panel.receiver_url.setText(bad)
        assert not panel.connect_receiver()
        assert panel.receiver_view is None
        assert not panel.receiver_connected
    finally:
        panel.shutdown();panel.deleteLater();app.processEvents()


def test_radio_off_also_destroys_sdr_session(app):
    panel=RadioPanel(confirm=lambda:False)
    class FakeView:
        def stop(self):self.stopped=True
        def setUrl(self,url):self.blank=url.toString()=="about:blank"
        def hide(self):pass
        def deleteLater(self):self.deleted=True
    fake=FakeView();fake.stopped=fake.blank=fake.deleted=False
    try:
        panel.receiver_view=fake
        panel.receiver_connected=True
        panel.receiver_host="receiver.example.org"
        panel.off()
        assert not panel.receiver_connected
        assert panel.receiver_view is None
        assert fake.stopped and fake.blank and fake.deleted
        assert panel.status.text()=="OFF"
    finally:
        panel.shutdown();panel.deleteLater();app.processEvents()


def test_tv_exposes_exact_video_owner_test_candidates_without_promoting_verified_builtins(app):
    tv=Television()
    try:
        tv.set_catalog(load_media_catalog())
        assert tv._builtins==[]
        assert tv._test_candidates
        assert all(item.get("owner_test_candidate") is True for item in tv._test_candidates)
        assert all(item["title"].startswith("TEST · ") for item in tv._test_candidates)
        # Only exact video identities are admitted. Channel/live directory pages remain absent.
        assert all("watch?v=" in item["url"] or "youtu.be/" in item["url"] or "/live/" in item["url"]
                   for item in tv._test_candidates)
        assert tv.selector.count() >= len(tv._test_candidates)
        assert any("TEST · " in str(tv.selector.itemText(i)) for i in range(tv.selector.count()))
    finally:
        tv.stop();tv.deleteLater();app.processEvents()


def test_camera_bank_is_available_manually_without_event_match(app):
    panel=MediaPanel()
    try:
        reviewed=camera_catalog()
        assert len(reviewed)>=2
        panel.set_event(None)
        assert panel.camera.selector.count()>=len(reviewed)
        ids={panel.camera.selector.itemData(i).get("id") for i in range(panel.camera.selector.count())
             if isinstance(panel.camera.selector.itemData(i),dict)}
        assert {item["id"] for item in reviewed} <= ids
        assert "available manually" in panel.camera_status.text()
        assert panel.camera.camera is None
    finally:
        panel.shutdown();panel.deleteLater();app.processEvents()


def test_news_refresh_does_not_start_radio_tv_or_camera(app):
    panel=MediaPanel()
    try:
        panel.set_catalog(load_media_catalog())
        panel.set_event({"id":"owner-observed-fixture","status":"active","title":"Routine update",
                         "country":"","region":"Global","severity":"moderate","reports":[]})
        assert panel.radio.status.text()=="OFF"
        assert panel.radio._session is None
        assert panel.tv.tv_status.text()=="OFF"
        assert panel.tv.view is None
        assert panel.camera.camera is None
    finally:
        panel.shutdown();panel.deleteLater();app.processEvents()
