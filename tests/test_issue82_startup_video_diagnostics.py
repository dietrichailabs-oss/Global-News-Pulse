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
from global_pulse.ui import MainWindow, EconomicChart
from global_pulse.__main__ import show_initializing,prepare_initial_dashboard


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
        "publisher":"Synthetic Publisher",
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
        assert not hasattr(w.media, "tv")
        assert w.media.camera.camera is None
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


@pytest.mark.parametrize("size", [(960, 640), (1440, 940)])
def test_splash_primes_real_size_first_economy_paint_before_interaction(
    app, tmp_path, monkeypatch, size,
):
    """Cold 6,400-row SQLite first paints belong under splash, not a tab click."""
    c = Controller(tmp_path, demo=True)
    w = None
    splash = None
    try:
        records = [{
            "indicator": "wb_inflation",
            "country": f"C{i % 200:03d}",
            "country_name": f"Country {i % 200:03d}",
            "date": str(1990 + (i // 200)),
            "value": float(i % 500) / 10,
            "previous_value": None,
            "synthetic": True,
            "source_id": "wb_inflation",
            "url": f"https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG?locations={i % 200}",
        } for i in range(6400)]
        for offset in range(0, len(records), 1600):
            assert c.store.put_observations(records[offset:offset + 1600]) == 1600
        splash = show_initializing(app)
        w = MainWindow(c)
        w.resize(*size)
        paints = []
        original_paint = EconomicChart._paint_chart

        def counted(self, painter):
            paints.append(1)
            return original_paint(self, painter)

        monkeypatch.setattr(EconomicChart, "_paint_chart", counted)
        assert not w.isVisible()
        assert prepare_initial_dashboard(app, splash, w, c)
        assert w.isVisible() and splash.isVisible()
        assert w.pages.currentIndex() == 0
        assert w._initial_painted_pages == set(range(7))
        assert len(w._observations) >= 6400
        assert w.economy_model.rowCount() >= 6400
        assert paints, "Full-size Economy raster must be painted during startup"
        chart = w.economic_chart
        key = (chart.width(), chart.height(), chart.devicePixelRatioF())
        assert chart._chart_cache_key == key
        assert chart._chart_pixmap is not None
        world = w.world_map
        assert world._projected_view_key == (
            world.width(), world.height(), world.zoom, world.pan_x, world.pan_y
        )
        warm_count = len(paints)
        # The first owner click after splash is removed must reuse warm raster.
        splash.finish(w)
        w.open_page(2)
        app.processEvents()
        chart.grab()
        assert len(paints) == warm_count, "First Economy click repainted the entire chart"
        assert chart._chart_cache_key == key
        w.open_page(0)
        app.processEvents()
        assert world._projected_view_key == (
            world.width(), world.height(), world.zoom, world.pan_x, world.pan_y
        )
        assert not hasattr(w.media, "tv")
        assert w.media.camera.camera is None
        assert w.media.radio.receiver_connected is False
    finally:
        if w is not None:
            w._force_close = True
            w.media.shutdown()
            w.close()
            w.deleteLater()
        c.close()
        if splash is not None:
            splash.close()
            splash.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
