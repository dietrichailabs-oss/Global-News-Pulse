"""Map painting/cache and heavy clustered point regression (synthetic, offline).

The Qt widget must not build country QPainterPaths on every hover or allocate
a QTransform for each of 5,000 incident candidates. This does not constitute
physical Windows 11 latency or live incident verification.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.map_widget import WorldMap


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def world(app):
    widget=WorldMap()
    widget.resize(1300,620)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_country_geometries_cache_during_hover_but_invalidate_on_view_change(world):
    first=world._mapped_country_paths()
    assert len(first)==len(world._countries)
    assert first is world._mapped_country_paths()
    world._hover_country="France"
    world.grab()
    assert world._mapped_country_paths() is first
    world.selected_country="Canada"
    world.grab()
    assert world._mapped_country_paths() is first

    world.pan_x = 0.1
    moved = world._mapped_country_paths()
    assert moved is not first
    assert len(moved)==len(first)
    assert moved is world._mapped_country_paths()

    world.zoom = 1.5
    zoomed=world._mapped_country_paths()
    assert zoomed is not moved
    world.resize(1320,640)
    resized=world._mapped_country_paths()
    assert resized is not zoomed
    world.grab()
    assert world._mapped_country_paths() is resized


def test_many_real_coordinate_candidates_use_one_transform_per_cluster_pass(world,monkeypatch):
    # Synthetic inert points, not actual events; spatial cluster count and
    # grouping are still the identical production path.
    points = [{
        "id": "fixture-%d" % i, "latitude": 10.0 + (i % 10) * .01,
        "longitude": -70.0 + (i % 10) * .01, "category": "Government",
        "severity": "moderate", "verification": "unverified",
    } for i in range(5000)]
    world.events=points
    real_transform=world._transform
    calls=[]
    def counted():
        calls.append("transform")
        return real_transform()
    monkeypatch.setattr(world,"_transform",counted)
    clusters=world.visible_clusters()
    assert clusters
    assert len(calls)==1
    assert sum(len(group) for group in clusters)==5000
    assert len(clusters) <= 5


def test_viewport_clipping_preserves_legitimate_event_hit_testing(world):
    event={
        "id":"synthetic-event","latitude":40.0,"longitude":-74.0,
        "category":"Infrastructure","severity":"high","verification":"official"
    }
    world.events=[event]
    world.zoom=1.0
    world.pan_x=0.0
    world.pan_y=0.0
    world.grab()
    assert world.visible_clusters()
    first=world._mapped_country_paths()
    world._hover_country="United States of America"
    world.grab()
    assert world._mapped_country_paths() is first
    world.zoom=3.0
    world.pan_x=0.4
    world.grab()   # all offscreen polygons can be clipped, but no Qt exception
    assert world._mapped_country_paths() is not first
