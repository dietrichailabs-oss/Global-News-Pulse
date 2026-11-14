"""QA-only negative tests for PR77 exact frozen HAM/TV/tray source.

Offline; no network requests or claims of live audio/video. Engineering tests
are separate; this branch must not edit a product/runtime line.
"""
from __future__ import annotations
import os
from datetime import datetime,timedelta,timezone
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.internet_radio import RadioPanel,_owner_legacy_websdr
from global_pulse.sdr_directory import public_receiver_url
from global_pulse.media_widget import youtube_player_navigation


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("source,type_,expected",[
    ("http://na5b.com:8901/","websdr",True),
    ("http://na5b.com:8901/","kiwi",False),
    ("http://na5b.com:8902/","websdr",False),
    ("http://www.na5b.com:8901/","websdr",False),
    ("http://other.example.org:8901/","websdr",False),
    ("https://na5b.com:8901/","websdr",False),
    ("https://receiver.example.org/","websdr",False),
])
def test_exact_origin_equality_is_required_for_legacy_sdr(source,type_,expected):
    assert _owner_legacy_websdr(public_receiver_url(source),type_) is expected


def test_http_receiver_validation_refuses_private_and_credentials():
    for source in (
        "http://user:pass@na5b.com:8901/",
        "http://localhost:8901/",
        "http://192.168.0.15:8901/",
        "http://127.0.0.1:8901/",
        "http://na5b.com:8901\\@localhost/",
    ):
        with pytest.raises(ValueError):
            public_receiver_url(source)


@pytest.mark.parametrize("alternate",[
    "https://www.youtube.com/watch?v=Y4M0i8HT7mc",
    "https://www.youtube.com/@NBCNews/live",
    "https://www.youtube.com/results?search_query=news",
    "https://www.youtube.com/shorts/Hz1cNNgtLtM",
    "https://www.youtube.com/embed/gTpn5Whu2ao",
    "http://www.youtube.com/watch?v=Hz1cNNgtLtM",
    "https://youtube.com.evil.example.org/watch?v=Hz1cNNgtLtM",
])
def test_full_watch_path_never_opens_another_video_or_page(alternate):
    assert not youtube_player_navigation(
        alternate,"Hz1cNNgtLtM",full_watch=True
    )


@pytest.fixture
def desktop(app,tmp_path):
    c=Controller(tmp_path,demo=True)
    at=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    rows=[{
        "id":f"qa-events-{i}","event_key":f"qa:issue76:{i}",
        "title":f"SYNTHETIC News {i}","summary":"No real crisis",
        "source_id":"qa-issue76","publisher":"Offline QA",
        "url":f"https://example.org/qa-76/{i}",
        "published_at":at,"retrieved_at":at,
        "category":"News","region":"Global",
        "country":"","synthetic":True,"severity":"unassessed",
    } for i in range(180)]
    c.store.ingest(rows)
    w=MainWindow(c)
    w.show()
    app.processEvents()
    yield w,c
    w._force_close=True;w.close();c.close();w.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_notification_storm_leaves_geo_and_selection_unmodified(desktop,monkeypatch,app):
    w,c=desktop
    seen=[]
    initial_ids=[str(x.get("id")) for x in w._events]
    monkeypatch.setattr(w.world_map,"set_events",lambda *a,**k:seen.append("full"))
    for n in range(120):
        c.notification_status=f"Notification delivery state {n}"
        c.notification_changed.emit()
        if n%25==0:app.processEvents()
    assert not seen
    assert [str(x.get("id")) for x in w._events]==initial_ids
    w.open_page(4)
    assert "119" in w.notification_label.text()


def test_fast_tab_roundtrip_avoids_repeated_database_reads(desktop,monkeypatch,app):
    w,c=desktop
    count=[]
    original=c.store.list_observations
    def observed(*a,**k):
        count.append("observations")
        return original(*a,**k)
    monkeypatch.setattr(c.store,"list_observations",observed)
    # Existing startup map pass may have already read observations.
    for i in range(40):
        w.open_page(2)
        w.open_page(0)
    app.processEvents()
    assert len(count)==1
    # New data is allowed to invalidate this cache, once.
    w.refresh_data()
    after_refresh=len(count)
    w.open_page(2)
    assert len(count)==after_refresh+1
    w.open_page(0);w.open_page(2)
    assert len(count)==after_refresh+1
