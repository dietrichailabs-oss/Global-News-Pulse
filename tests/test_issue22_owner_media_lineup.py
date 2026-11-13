"""Owner-observed media lineup regressions for the physical Windows candidate.

Offline only: no stream, YouTube, camera, WebSDR or KiwiSDR connection occurs.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication,QMessageBox

from global_pulse.internet_radio import STATIONS,HAM_DIRECTORIES,RadioPanel,AudioSession
from global_pulse.single_media import Television,MediaPanel
from global_pulse.sources import load_media_catalog
from global_pulse.camera_context import camera_catalog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_direct_radio_lineup_is_news_talk_only_and_documented():
    ids={item["id"] for item in STATIONS}
    assert ids=={"wnyc_fm","wnyc_am","deutschlandfunk",
                 "deutschlandfunk_nova","deutschlandfunk_debatten"}
    assert not {"wqxr","new_sounds","operavore","deutschlandfunk_kultur"} & ids
    for item in STATIONS:
        assert item["url"].startswith("https://")
        assert item["documentation"].startswith("https://")
        assert "News" in item["language"]


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
        assert fake.loaded==["https://receiver.example.org/?f=7100usb"]
        assert fake.shown

        panel.disconnect_receiver()
        assert not panel.receiver_connected
        assert fake.stopped and fake.blank and fake.deleted
        assert panel.receiver_view is None
    finally:
        panel.shutdown();panel.deleteLater();app.processEvents()


def test_sdr_tuner_generates_receiver_native_frequency_parameters(app,monkeypatch):
    panel=RadioPanel(confirm=lambda:False)
    try:
        panel.receiver_url.setText("https://receiver.example.org/rx")
        panel.frequency.setText("14200.5")
        panel.mode.setCurrentIndex(panel.mode.findData("usb"))
        kiwi,host=panel._tuned_receiver_url()
        assert host=="receiver.example.org"
        assert kiwi=="https://receiver.example.org/rx?f=14200.5usb"

        panel.receiver_type.setCurrentIndex(panel.receiver_type.findData("websdr"))
        panel.mode.setCurrentIndex(panel.mode.findData("lsb"))
        websdr,_=panel._tuned_receiver_url("7200")
        assert websdr=="https://receiver.example.org/rx?tune=7200lsb"
    finally:
        panel.shutdown();panel.deleteLater();app.processEvents()


def test_sdr_scan_steps_bounded_range_and_stops(app,monkeypatch):
    panel=RadioPanel(confirm=lambda:False)
    tuned=[]
    try:
        monkeypatch.setattr(panel,"tune_receiver",lambda frequency=None:(tuned.append(float(frequency)) or True))
        panel.scan_start.setText("7000")
        panel.scan_end_edit.setText("7010")
        panel.scan_step_edit.setText("5")
        panel.scan_dwell.setText("1")
        assert panel.start_scan()
        assert tuned==[7000.0]
        panel._scan_next();panel._scan_next();panel._scan_next()
        assert tuned==[7000.0,7005.0,7010.0]
        assert not panel.scan_timer.isActive()
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


def test_decoded_radio_buffer_without_system_output_fails_closed(app, monkeypatch):
    """A headless decoder is not truthful audible PLAYING."""
    class Buffer:
        def isValid(self): return True
        def frameCount(self): return 512

    class Output:
        def __init__(self): self.muted = False
        def setMuted(self, value): self.muted = value

    class Player:
        def __init__(self): self.stopped = False; self.cleared = False
        def stop(self): self.stopped = True
        def setSource(self, url): self.cleared = url.isEmpty()

    session = AudioSession("wnyc_fm")
    events = []
    session.changed.connect(lambda state, detail: events.append((state, detail)))
    monkeypatch.setattr(AudioSession, "_has_audio_output", staticmethod(lambda: False))
    try:
        session.active = True
        session.state = "CONNECTING"
        session.output = Output()
        session.player = Player()
        session._buffer(Buffer())
        assert session.state == "ERROR"
        assert [state for state, _ in events] == ["ERROR"]
        assert "audio-output" in events[0][1]
        assert session.closed and not session.active
        assert session.output.muted and session.player.stopped and session.player.cleared
        assert session.buffers == 0 and session.frames == 0
        # A delayed decoder signal cannot reactivate a released session.
        session._buffer(Buffer())
        assert len(events) == 1
    finally:
        session.stop()
        session.deleteLater()
        app.processEvents()


def test_decoded_radio_buffer_with_available_output_can_mark_playing(app, monkeypatch):
    """Positive decoder path keeps the existing real-frame liveness contract."""
    class Buffer:
        def isValid(self): return True
        def frameCount(self): return 256

    session = AudioSession("wnyc_fm")
    monkeypatch.setattr(AudioSession, "_has_audio_output", staticmethod(lambda: True))
    try:
        session.active = True
        session.state = "CONNECTING"
        session._buffer(Buffer())
        assert session.state == "PLAYING"
        assert session.buffers == 1 and session.frames == 256
        assert session.last_frame > 0
        session.stop()
        assert session.state == "OFF"
    finally:
        session.deleteLater()
        app.processEvents()


def test_radio_watchdog_disconnects_after_audio_device_hot_unplug(app, monkeypatch):
    """Once playback was real, losing the output must stop even without new buffers."""
    import time

    class Output:
        def __init__(self): self.muted = False
        def setMuted(self, value): self.muted = value

    class Player:
        def __init__(self): self.stopped = self.cleared = False
        def stop(self): self.stopped = True
        def setSource(self, url): self.cleared = url.isEmpty()

    session = AudioSession("wnyc_fm")
    seen = []
    session.changed.connect(lambda state, detail: seen.append((state, detail)))
    monkeypatch.setattr(AudioSession, "_has_audio_output", staticmethod(lambda: False))
    try:
        session.active = True
        session.state = "PLAYING"
        session.frames = 256
        session.buffers = 1
        session.last_frame = time.monotonic()
        session.output = Output()
        session.player = Player()
        # There is no new _buffer signal after hot-unplug. The watchdog alone
        # must shut down the player and clear its network stream.
        session._watch()
        assert session.state == "ERROR"
        assert session.closed and not session.active
        assert session.output.muted and session.player.stopped and session.player.cleared
        assert [s for s, _ in seen] == ["ERROR"]
        assert "disconnected" in seen[0][1]
        session._watch()  # late timer callback cannot restart it
        assert len(seen) == 1
    finally:
        session.stop()
        session.deleteLater()
        app.processEvents()


def test_radio_watchdog_keeps_recent_audio_when_output_remains_available(app, monkeypatch):
    """Hot-unplug detection must not terminate valid fresh decoded playback."""
    import time

    session = AudioSession("wnyc_fm")
    monkeypatch.setattr(AudioSession, "_has_audio_output", staticmethod(lambda: True))
    try:
        session.active = True
        session.state = "PLAYING"
        session.frames = 256
        session.buffers = 1
        session.last_frame = time.monotonic()
        session._watch()
        assert session.active and not session.closed
        assert session.state == "PLAYING"
        assert session.buffers == 1
    finally:
        session.stop()
        session.deleteLater()
        app.processEvents()
