"""Issue82: visible bounded TV failure receipts survive Stop; offline real Qt."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
import global_pulse.single_media as media
from global_pulse.single_media import Television


def make():
    return QApplication.instance() or QApplication([]), Television()


def cleanup(app, tv):
    tv.stop()
    tv.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_provider_unavailable_remains_readable_after_session_stop():
    app, tv = make()
    try:
        tv._requested = True
        tv._generation = 7
        tv._player_loaded = True
        tv._observed(7, {
            "provider_error": "This video is unavailable",
            "codecs": {"h264": "probably", "vp9": "maybe"},
        })
        assert tv.tv_status.text().startswith("UNAVAILABLE")
        assert tv._requested is False
        assert "This video is unavailable" in tv.tv_diagnostics.text()
        assert "H.264 probably" in tv.tv_diagnostics.text()
        assert "Playback not verified" in tv.tv_diagnostics.text()
        assert tv.tv_diagnostics.text() != "TV OFF · no active media diagnostics"
        assert tv.tv_diagnostics.textFormat() == Qt.TextFormat.PlainText
        assert tv.tv_diagnostics.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    finally:
        cleanup(app, tv)


def test_provider_error_is_plain_text_and_length_bounded():
    app, tv = make()
    try:
        tv._requested = True
        tv._observed(tv._generation, {
            "provider_error": "<b>not available</b>" + ("X" * 10000),
            "codecs": {"h264": "maybe"},
        })
        assert "<b>not available</b>" in tv.tv_diagnostics.text()
        assert len(tv.tv_diagnostics.text()) <= 330
        assert tv.tv_status.text().startswith("UNAVAILABLE")
        assert not tv._requested
    finally:
        cleanup(app, tv)


def test_local_sandbox_refusal_has_readable_receipt_for_both_consent_paths(monkeypatch):
    app, tv = make()
    fake_messagebox = SimpleNamespace(
        StandardButton=SimpleNamespace(Yes=1, No=2),
        question=lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(media, "QMessageBox", fake_messagebox)
    monkeypatch.setenv("QTWEBENGINE_DISABLE_SANDBOX", "1")
    try:
        tv._saved = ["YE7VzlLtp-4"]
        tv._populate_channels()
        assert tv.selector.count() >= 1
        tv.selector.setCurrentIndex(0)
        tv.watch()
        assert tv.tv_status.text() == "ERROR"
        assert "startup refused" in tv.tv_diagnostics.text()
        assert not tv._requested
        assert tv.watch_full_page() is False
        assert "watch page startup refused" in tv.tv_diagnostics.text()
        assert not tv._requested
    finally:
        cleanup(app, tv)
