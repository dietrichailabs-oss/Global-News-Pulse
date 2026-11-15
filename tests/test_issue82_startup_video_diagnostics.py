"""Owner Issue82: initializing must prepare local UI before interaction.

No live collection, no network, no media playback. Uses actual Controller,
SQLite and Qt with finite pending headline work as in the owner's cold start.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.__main__ import show_initializing,prepare_initial_dashboard
from global_pulse.single_media import Television


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _archive(n):
    # Deliberately reuse the proven unlocated cold-headline archive shape from
    # test_issue64_deferred_cold_headlines, with unique category/identity text.
    at=datetime.now(timezone.utc).isoformat()
    cats=("Disaster","Conflict","Unrest","Health","Government",
          "Economy","Humanitarian","Infrastructure","News")
    return [{
        "id":f"deferred-synthetic-{i}",
        "source_id":"offline-cold-profile",
        "event_key":f"deferred-synthetic:{i}",
        "title":f"SYNTHETIC UI profile {cats[i%len(cats)]} #{i}",
        "summary":"Fictional source evidence, no real-world event",
        "url":f"https://example.invalid/deferred/{i}",
        "published_at":at,"retrieved_at":at,
        "country":"","region":"Global",
        "category":cats[i%len(cats)],
        "severity":"unassessed","synthetic":True,
    } for i in range(n)]


def test_initial_splash_drains_cold_headlines_and_prepares_all_tabs(app,tmp_path):
    c=Controller(tmp_path,demo=True)
    w=None
    splash=None
    try:
        ingested=c.store.ingest(_archive(220))
        assert len(ingested)==220, c.store.last_ingest_errors[:3]
        assert len(c.events(limit=500))==220
        splash=show_initializing(app)
        w=MainWindow(c)
        # The controller and widgets are constructed but main window is still
        # deliberately hidden while initialization is being performed.
        assert not w.isVisible()
        assert len(w._events)==220
        assert set(range(1,6)).issubset(w._dirty_pages)
        assert c._headlines.deferred
        assert prepare_initial_dashboard(app,splash,w,c) is True
        assert not c._headlines.deferred
        assert not c._headlines.deferred_timer.isActive()
        assert not (w._dirty_pages & set(range(1,6)))
        assert w.pages.currentIndex()==0
        assert w.media.tv._requested is False
        assert w.media.radio.receiver_connected is False
        assert splash.isVisible()
        w.show()
        splash.finish(w)
        app.processEvents()
        assert not splash.isVisible()
        assert w.isVisible()
        assert "World intelligence overview" in w.overview_browser.toPlainText()
    finally:
        if w is not None:
            w._force_close=True
            w.media.shutdown()
            w.close()
        c.close()
        if w is not None:
            w.deleteLater()
        if splash is not None:
            splash.close()
            splash.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_second_tab_roundtrip_does_not_refetch_prepared_workspaces(app,tmp_path,monkeypatch):
    c=Controller(tmp_path,demo=True)
    w=None
    splash=None
    try:
        c.store.ingest(_archive(30))
        splash=show_initializing(app)
        w=MainWindow(c)
        prepare_initial_dashboard(app,splash,w,c)
        calls=[]
        original=w._populate_economy
        monkeypatch.setattr(w,"_populate_economy",
                            lambda *a,**k:(calls.append("economy"),original(*a,**k)))
        for _ in range(12):
            w.open_page(2)
            w.open_page(0)
        assert not calls
    finally:
        if w is not None:
            w._force_close=True;w.media.shutdown();w.close()
        c.close()
        if w is not None:w.deleteLater()
        if splash is not None:splash.close();splash.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_video_diagnostic_does_not_call_black_picture_playing(app):
    tv=Television()
    try:
        tv._requested=True
        tv._player_loaded=True
        tv._last_time=2.0
        payload={
            "time":3.0, "paused":False,"ready":4,"network":1,
            "video_width":0,"video_height":0,"frames":0,
            "controls_visible":False,
            "codecs":{"h264":"","vp9":"probably","av1":"maybe"}
        }
        tv._observed(tv._generation,payload)
        assert tv.tv_status.text()=="NO DECODED FRAMES · black video suspected"
        assert "H.264 not reported" in tv.note.text()
        assert "VP9 probably" in tv.note.text()
        assert "YouTube controls hidden" in tv.note.text()
        assert tv._had_playback is False
        tv._observed(tv._generation,{
            **payload,"time":4.0,"video_width":1920,
            "video_height":1080,"frames":10
        })
        assert tv.tv_status.text()=="VIDEO TIME ADVANCING · picture unverified"
        assert tv._had_playback is True
        assert "NOT confirmed" in tv.note.text()
    finally:
        tv.stop();tv.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("code,label",[
    (2,"network"),(3,"decoder"),(4,"unsupported media")
])
def test_player_media_error_code_is_visible_not_playing(app,code,label):
    tv=Television()
    try:
        tv._requested=True
        tv._observed(tv._generation,{"error_code":code})
        assert label in tv.tv_status.text()
        assert not tv._requested
        assert "code "+str(code) in tv.note.text()
    finally:
        tv.stop();tv.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_renderer_exit_reports_real_browser_failure(app):
    tv=Television()
    try:
        tv._requested=True
        tv._renderer_terminated(None,3)
        assert tv.tv_status.text().startswith("RENDERER EXITED")
        assert not tv._requested
    finally:
        tv.stop();tv.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
