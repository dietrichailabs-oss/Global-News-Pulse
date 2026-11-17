"""No-click collector refresh must reuse feed rows without losing evidence/Star."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _reports(count=40):
    now=datetime.now(timezone.utc).isoformat()
    return [{
        "id":f"feed-id-{i}",
        "event_key":f"feed-key-{i}",
        "title":f"SYNTHETIC feed event {i}",
        "summary":"Local fake evidence; not an actual world event",
        "source_id":"synthetic-offline",
        "publisher":"Synthetic fixture",
        "url":f"https://example.invalid/synthetic/{i}",
        "published_at":now,"retrieved_at":now,
        "country":"","region":"Global","category":"News",
        "synthetic":True,"severity":"unassessed",
    } for i in range(count)]


def _close(app,window,controller):
    if window is not None:
        for name in ("_workspace_warm_timer","_evidence_refresh_timer",
                     "_collection_refresh_timer"):
            getattr(window,name).stop()
        window._force_close=True
        window.media.shutdown()
        window.close()
        window.deleteLater()
    controller.close()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_idle_feed_refresh_reuses_items_and_preserves_star_source_and_scroll(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        assert len(controller.store.ingest(_reports())) >= 35
        window=MainWindow(controller)
        window.show()
        app.processEvents()
        window.refresh_data()
        assert window.feed_list.count() >= 35
        before=[window.feed_list.item(i) for i in range(window.feed_list.count())]
        rows=[item.data(Qt.ItemDataRole.UserRole) for item in before]
        target=before[10]
        window._selected_id=str(rows[10]["id"])
        window.feed_list.setCurrentItem(target)
        app.processEvents()
        window.feed_list.verticalScrollBar().setValue(4)
        offset=window.feed_list.verticalScrollBar().value()

        # Test the real idle full refresh, not only the helper. No rows may be
        # instantiated when the store's visible feed identities are unchanged.
        with patch("global_pulse.ui.QListWidgetItem",
                   side_effect=AssertionError("recreated unchanged feed row")):
            window.refresh_data()
        assert [window.feed_list.item(i) for i in range(len(before))]==before
        assert window.feed_list.currentItem() is target
        assert window._selected_id==str(rows[10]["id"])
        assert window.feed_list.verticalScrollBar().value()==offset
        assert window.feed_list.item(10).data(Qt.ItemDataRole.UserRole)["id"]==rows[10]["id"]

        # Correction/translation and Star overlays must update the *same*
        # record object rather than being silently dropped by this fast path.
        new=list(window._events)
        new[10]=dict(new[10],title="SYNTHETIC corrected headline")
        window._events=new
        with patch.object(controller,"headline_view",wraps=controller.headline_view):
            window._populate_feed()
        assert window.feed_list.item(10) is target
        assert window.feed_list.item(10).data(Qt.ItemDataRole.UserRole)["title"]=="SYNTHETIC corrected headline"
        assert "corrected" in window.feed_list.item(10).text()
        # An explicitly cleared selection must not rebind a stale Star.
        window._selected_id=""
        window._feed_explicitly_cleared=True
        window._populate_feed()
        assert window.feed_list.currentItem() is None
        assert window._selected_id==""
        # A genuine changed order is allowed to rebuild, with correct IDs.
        window._events=list(reversed(window._events))
        window._populate_feed()
        assert window.feed_list.item(0).data(Qt.ItemDataRole.UserRole)["id"]==window._events[0]["id"]
    finally:
        _close(app,window,controller)
