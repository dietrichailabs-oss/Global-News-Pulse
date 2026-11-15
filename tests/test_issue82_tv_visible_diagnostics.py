"""Issue82: readable Qt TV codec receipt; no network, video or audio proof."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import Qt,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QWidget
from global_pulse.single_media import Television
from global_pulse.media_widget import _MediaTile

def make():
    app=QApplication.instance() or QApplication([])
    return app,Television()

def close(app,tv):
    tv.stop()
    tv.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()

def test_codec_readout_is_plain_text_selectable_and_visible():
    app,tv=make()
    try:
        tv._requested=True
        tv._generation=5
        tv._observed(5,{"codecs":{"h264":"probably","vp9":"maybe"},
                        "time":0.0,"paused":True,"ready":0,"network":2,
                        "video_width":0,"video_height":0,"frames":0,
                        "controls_visible":False})
        d=tv.tv_diagnostics
        assert d.wordWrap()
        assert d.textFormat()==Qt.TextFormat.PlainText
        assert d.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
        assert d.minimumHeight()>=48
        assert "H.264 probably" in d.text()
        assert "YouTube controls hidden" in d.text()
        assert "Picture/audio not yet proven" in d.text()
        assert tv.note.maximumHeight()<=24
    finally:
        close(app,tv)

def test_decoder_error_readout_survives_internal_stop():
    app,tv=make()
    try:
        tv._requested=True
        tv._generation=3
        tv._observed(3,{"codecs":{"h264":"maybe"},"time":1.0,
                        "paused":False,"ready":0,"network":3,
                        "video_width":0,"video_height":0,"frames":0,
                        "error_code":3,"controls_visible":False})
        assert "VIDEO ERROR" in tv.tv_status.text()
        assert "HTMLMediaElement error 3" in tv.tv_diagnostics.text()
        assert tv._requested is False
    finally:
        close(app,tv)

def test_renderer_error_is_visible_without_playback_claim():
    app,tv=make()
    try:
        tv._requested=True
        tv._renderer_terminated(None,1)
        assert "RENDERER EXITED" in tv.tv_status.text()
        assert "renderer terminated" in tv.tv_diagnostics.text().lower()
    finally:
        close(app,tv)

def test_real_browser_slot_minimum_height_after_placeholder_hidden(monkeypatch):
    app,tv=make()
    try:
        fake=QWidget(tv)
        monkeypatch.setattr(_MediaTile,"_ensure_player",
                            lambda self:setattr(self,"view",fake))
        tv._ensure_player()
        assert fake.minimumHeight()>=180
        tv.view=None
    finally:
        close(app,tv)
