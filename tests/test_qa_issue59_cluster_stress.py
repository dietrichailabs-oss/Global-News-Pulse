"""QA-only exact-source 5k-event hover/cluster cache stress.

Product source frozen at 50747372afc612c7a7013ce10dac5dc5d19044d8.
No live incidents or physical Windows11 performance claim.
"""
import os
import time
import statistics
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
from global_pulse.map_widget import WorldMap


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_fifty_repaints_with_5000_incidents_reuse_unchanged_cluster_identity(app):
    world=WorldMap()
    world.resize(1600,760)
    world.show()
    app.processEvents()
    try:
        events=[{
            "id":f"qa-stress-{i}",
            "longitude":-165+(i%60)*5.3,
            "latitude":-52+(i%20)*5.0,
            "category":"Government" if i%2 else "Disaster",
            "severity":"moderate","verification":"unverified",
        } for i in range(5000)]
        world.set_events(events)
        world.grab()
        cached=world.visible_clusters()
        assert len(cached)>10
        original=world._cluster_view_key
        durations=[]
        for n in range(50):
            world.selected_event=str(n)
            world._hover_country="United States of America" if n%2 else "France"
            started=time.perf_counter()
            world.grab()
            durations.append((time.perf_counter()-started)*1000)
            assert world.visible_clusters() is cached
            assert world._cluster_view_key==original
        print("QA_ISSUE59_5K_HOVER_P50_MS=%.3f MAX_MS=%.3f" %
              (statistics.median(durations),max(durations)),flush=True)
        world.categories={"Government"}
        world.grab()
        assert world.visible_clusters() is not cached
        subset=world.visible_clusters()
        assert sum(len(group) for group in subset)==2500
        world.set_events(events[:40])
        assert world.visible_clusters() is not subset
        assert sum(len(group) for group in world.visible_clusters())==20
    finally:
        world.close()
        world.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_pan_and_zoom_during_hover_never_reuse_stale_cluster_centers(app):
    world=WorldMap()
    world.resize(1400,650)
    world.show()
    app.processEvents()
    try:
        event={"id":"qa-map-point", "longitude":15.0,"latitude":47.0,
               "category":"Infrastructure","severity":"high",
               "verification":"official"}
        world.set_events([event])
        baseline=world.visible_clusters()
        assert len(baseline)==1
        first=baseline[0][0][1]
        world.pan_x=0.03
        panned=world.visible_clusters()
        assert panned is not baseline
        assert len(panned)==1
        assert panned[0][0][1]!=first
        world.zoom=1.25
        zoomed=world.visible_clusters()
        assert zoomed is not panned
        assert len(zoomed)==1
        assert zoomed[0][0][1]!=panned[0][0][1]
    finally:
        world.close()
        world.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
