"""No-click source refresh must not reset identical Selected Event/Camera Qt widgets.

Offline synthetic data, hosted Qt only; neither physical Win11 fluidity nor
real video/audio or source rights are established by these tests.
"""
import copy
import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _fixture(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    now=datetime.now(timezone.utc).isoformat()
    rows=controller.store.ingest([{
        "id":"synthetic-selected-idle",
        "event_key":"offline-selected-idle",
        "title":"FICTIONAL unchanged selected report",
        "summary":"Test fixture only, never real news",
        "source_id":"offline-test",
        "publisher":"Fictional publisher",
        "url":"https://example.invalid/no-click",
        "published_at":now,
        "retrieved_at":now,
        "region":"Global",
        "category":"News",
        "severity":"high",
        "synthetic":True,
    }])
    assert len(rows)==1
    event=controller.event(rows[0]["id"])
    assert event and event.get("reports")
    window=MainWindow(controller)
    window._background_warm_enabled=True
    window._workspace_warm_timer.stop()
    window._evidence_refresh_timer.stop()
    window._collection_refresh_timer.stop()
    return app,controller,window,event


def _close(app,controller,window):
    window._force_close=True
    for name in ("_workspace_warm_timer","_evidence_refresh_timer",
                 "_collection_refresh_timer","search_timer"):
        getattr(window,name).stop()
    window.media.shutdown()
    window.close()
    window.deleteLater()
    controller.close()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_identical_passive_selected_evidence_never_reflows_brief_or_camera(tmp_path):
    app,controller,window,event=_fixture(tmp_path)
    try:
        with patch.object(window,"_render_event",wraps=window._render_event) as render:
            assert window._render_idle_selection(
                event,english_enabled=True,starred_override=False) is True
            assert "FICTIONAL unchanged selected report" in window.intel_browser.toPlainText()
            assert window._render_idle_selection(
                copy.deepcopy(event),english_enabled=True,starred_override=False) is False
            assert window._render_idle_selection(
                copy.deepcopy(event),english_enabled=True,starred_override=False) is False
            assert render.call_count==1, "Unchanged map revisions reflowed selected QTextBrowser/media"
    finally:
        _close(app,controller,window)


def test_nested_source_correction_star_and_language_still_repaint(tmp_path):
    app,controller,window,event=_fixture(tmp_path)
    try:
        assert window._render_idle_selection(
            event,english_enabled=True,starred_override=False)
        revised=copy.deepcopy(event)
        revised["reports"][0]["title"]="FICTIONAL revised evidence title"
        with patch.object(window,"_render_event",wraps=window._render_event) as render:
            assert window._render_idle_selection(
                revised,english_enabled=True,starred_override=False)
            assert "FICTIONAL revised evidence title" in window.intel_browser.toPlainText()
            assert window._render_idle_selection(
                revised,english_enabled=True,starred_override=True)
            assert window._render_idle_selection(
                revised,english_enabled=False,starred_override=True)
            assert render.call_count==3
            assert window._render_idle_selection(
                revised,english_enabled=False,starred_override=True) is False
    finally:
        _close(app,controller,window)


def test_empty_selection_is_idempotent_and_new_selection_restarts_media_context(tmp_path):
    app,controller,window,event=_fixture(tmp_path)
    try:
        with patch.object(window,"_render_empty_brief",wraps=window._render_empty_brief) as empty, \
             patch.object(window.media,"set_event",wraps=window.media.set_event) as media:
            assert window._render_idle_selection(None,english_enabled=True,starred_override=None)
            assert window._render_idle_selection(None,english_enabled=True,starred_override=None) is False
            assert empty.call_count==1
            assert media.call_count==1
            assert window._render_idle_selection(
                event,english_enabled=True,starred_override=False)
            assert media.call_count==2
            assert window._render_idle_selection(
                event,english_enabled=True,starred_override=False) is False
            assert media.call_count==2
            assert window._render_idle_selection(None,english_enabled=True,starred_override=None)
            assert media.call_count==3
    finally:
        _close(app,controller,window)


def test_translation_only_redraw_does_not_mask_required_media_update(tmp_path):
    app,controller,window,event=_fixture(tmp_path)
    try:
        window._render_event(event,update_media=False,
                             english_enabled=True,starred_override=False)
        with patch.object(window.media,"set_event",wraps=window.media.set_event) as media:
            assert window._render_idle_selection(
                event,english_enabled=True,starred_override=False)
            assert media.call_count==1
            assert window._render_idle_selection(
                event,english_enabled=True,starred_override=False) is False
            assert media.call_count==1
    finally:
        _close(app,controller,window)


def test_snapshot_cache_is_frozen_against_nested_source_mutation(tmp_path):
    app,controller,window,event=_fixture(tmp_path)
    try:
        original=copy.deepcopy(event)
        assert window._render_idle_selection(
            event,english_enabled=True,starred_override=False)
        event["reports"][0]["title"]="FICTIONAL corrected nested title"
        assert window._render_idle_selection(
            event,english_enabled=True,starred_override=False)
        assert window._render_idle_selection(
            original,english_enabled=True,starred_override=False)
        assert window._render_idle_selection(
            original,english_enabled=True,starred_override=False) is False
    finally:
        _close(app,controller,window)
