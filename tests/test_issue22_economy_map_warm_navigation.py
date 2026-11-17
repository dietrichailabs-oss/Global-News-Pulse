"""Source-bound Economy map navigation when idle workspace warming is enabled.

Offline synthetic Store/Qt regression only. No claims about real economic
conditions, physical Windows 11 latency, map incidents or independent QA.
"""
from __future__ import annotations

import os
import time
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _observations():
    return [{
        "indicator":"wb_inflation",
        "indicator_name":"Synthetic inflation test",
        # Mirror the World Bank parser: country is the published full name;
        # country_code is the separate ISO-style location identifier.
        "country":name,
        "country_code":f"T{i:03d}",
        "date":"2025",
        "value":float(i+1),
        "source_id":"offline-economy-fixture",
        "url":f"https://example.invalid/economy/{i}",
        "synthetic":True,
    } for i,name in enumerate(("Test Country East","Test Country West"))]


def _close(app,window,controller):
    if window is not None:
        window._workspace_warm_timer.stop()
        window._evidence_refresh_timer.stop()
        window._force_close=True
        window.media.shutdown()
        window.close()
    controller.close()
    if window is not None:
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_new_economy_observations_map_click_defers_stale_controls_without_sql(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        window=MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        assert window._background_warm_enabled
        assert controller.store.put_observations(_observations())==2
        window.open_page(0)
        window.refresh_data()
        window._workspace_warm_timer.stop()
        assert 2 in window._dirty_pages
        assert window.economy_country.findText("Test Country West")<0

        def forbidden(*args,**kwargs):
            raise AssertionError("A map country click cannot synchronously read Economy SQLite")

        with monkeypatch.context() as p:
            p.setattr(controller.store,"list_observations",forbidden)
            window._open_economic_country("Test Country East")
            window._open_economic_country("Test Country West")
        assert window.pages.currentIndex()==2
        assert window._pending_economic_country=="Test Country West"
        assert 2 in window._dirty_pages
        assert "Preparing" in window.status_label.text()
        window._workspace_warm_timer.stop()
        window._last_navigation_at=time.monotonic()-3
        window._warm_next_workspace()
        window._workspace_warm_timer.stop()
        assert 2 not in window._dirty_pages
        assert window._pending_economic_country is None
        assert window.economy_country.currentText()=="Test Country West"
        assert window.economy_model.rowCount()==1
        assert "dated sourced observations" in window.status_label.text()
        assert window.economy_model.url_at(0).endswith("/1")
        # On a current, prewarmed Economy page another map-country click
        # only switches already materialized rows, never reads SQLite.
        with monkeypatch.context() as p:
            p.setattr(controller.store,"list_observations",forbidden)
            window._open_economic_country("Test Country East")
        assert window.economy_country.currentText()=="Test Country East"
        assert window.economy_model.url_at(0).endswith("/0")
    finally:
        _close(app,window,controller)


def test_visible_economy_refresh_consumes_pending_map_country(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        window=MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        assert controller.store.put_observations(_observations())==2
        window.open_page(0)
        window.refresh_data()
        window._workspace_warm_timer.stop()
        assert 2 in window._dirty_pages
        window._open_economic_country("Test Country West")
        assert window._pending_economic_country=="Test Country West"
        # A material revision may arrive while the deferred workspace is
        # pending. Its visible Economy refresh must honor the latest click.
        window.refresh_data()
        window._workspace_warm_timer.stop()
        assert window._pending_economic_country is None
        assert 2 not in window._dirty_pages
        assert window.economy_country.currentText()=="Test Country West"
        assert window.economy_model.rowCount()==1
        assert "no longer in the local archive" not in window.status_label.text()
    finally:
        _close(app,window,controller)
