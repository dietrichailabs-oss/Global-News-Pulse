"""Issue31: fixed opt-in TV embed UI state regressions (no network)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton
from global_pulse.single_media import Television
from global_pulse.media_widget import youtube_id


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_fixed_test_video_can_be_selected_without_autoplay(app, monkeypatch):
    tv = Television()
    invoked = []
    try:
        monkeypatch.setattr(tv, "watch", lambda: invoked.append(True))
        assert tv.test_tv_player() is True
        assert invoked == [True]
        assert youtube_id(tv._current().get("url", "")) == "YE7VzlLtp-4"
        assert "LIVE" not in tv.tv_status.text()
        buttons = [x for x in tv.findChildren(QPushButton)
                   if x.text() == "Open on YouTube"]
        assert len(buttons) == 1
        assert not buttons[0].isHidden()
    finally:
        tv.stop()
        tv.deleteLater()
        app.processEvents()


def test_no_green_or_playing_on_load_success_without_video_progress(app):
    tv = Television()
    try:
        tv._requested = True
        tv._tv_load_finished(True)
        assert tv.tv_status.text() == "PLAYER LOADED · press Play"
        assert "PLAYING" not in tv.tv_status.text()
        tv._observed(tv._generation, {"missing": True})
        assert tv.tv_status.text() == "PLAYER LOADED · waiting for video"
        tv._tv_load_finished(False)
        assert tv.tv_status.text().startswith("ERROR")
        assert "YouTube" in tv.tv_status.text()
    finally:
        tv.stop()
        tv.deleteLater()
        app.processEvents()


def test_initial_paused_video_does_not_rearm_deadline(app, monkeypatch):
    tv = Television()
    try:
        tv._requested = True
        tv._progress_at = 100.0
        tv._last_time = 0.0
        tv._had_playback = False
        monkeypatch.setattr("global_pulse.single_media.time.monotonic", lambda: 135.0)
        tv._observed(tv._generation, {"time": 0.0, "paused": True, "ready": 3})
        assert tv.tv_status.text().startswith("PAUSED")
        assert tv._progress_at == 100.0
        assert tv._had_playback is False
        # Playback progression is the only proof of actual in-app playing.
        tv._observed(tv._generation, {"time": 1.0, "paused": False, "ready": 4})
        assert tv.tv_status.text() == "PLAYING"
        assert tv._had_playback is True
        assert tv._progress_at == 135.0
    finally:
        tv.stop()
        tv.deleteLater()
        app.processEvents()


def test_live_channel_page_not_accepted_as_fixed_video_identity():
    assert youtube_id("https://www.youtube.com/@BBCNews/live") is None
    assert youtube_id("https://www.youtube.com/watch?v=YE7VzlLtp-4") == "YE7VzlLtp-4"
