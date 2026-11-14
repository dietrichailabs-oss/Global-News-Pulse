"""QA-only offscreen Qt stress for Issue58 projected geometry reuse.

Exact product ancestor e05fa657ebd3ad1bc5ba3703115a8f1b635d1271.
No product source changes, no live events, no network or Windows11 UI claims.
"""
from __future__ import annotations
import os
import statistics
import time
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
    widget.resize(1600, 760)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _points(count=5000):
    """Synthetic known-coordinate markers, never real-world incident claims."""
    return [{
        "id": "qa-%d" % i,
        "longitude": -170 + (i % 34) * 9.7,
        "latitude": -45 + (i % 17) * 6.4,
        "category": ["News", "Disaster", "Government", "Economy"][i % 4],
        "severity": ["high", "moderate", "informational"][i % 3],
        "verification": ["official", "developing", "unverified"][i % 3],
    } for i in range(count)]


def test_sixty_hover_and_evidence_repaints_do_not_reproject_static_country_paths(world):
    world.events=_points()
    world.grab()
    paths=world._mapped_country_paths()
    assert len(paths)==len(world._countries)>100
    durations=[]
    for i in range(60):
        world._hover_country=("France" if i % 2 else "Canada")
        start=time.perf_counter()
        world.grab()
        durations.append((time.perf_counter()-start)*1000)
        assert world._mapped_country_paths() is paths
    assert world.visible_clusters() # real point path still renders
    print("QA_MAP_HOVER_REPAINT_MS_P50=%.3f P_MAX=%.3f" %
          (statistics.median(durations),max(durations)),flush=True)


def test_pan_and_zoom_invalidate_projection_exactly_once_per_view(world):
    world.events=_points(200)
    world.grab()
    first=world._mapped_country_paths()
    for i in range(12):
        world.pan_x=0.01*i
        world.pan_y=-0.006*i
        world.grab()
        next_paths=world._mapped_country_paths()
        if i:
            assert next_paths is not first
        assert next_paths is world._mapped_country_paths()
        first=next_paths
    world.zoom=2.0
    zoom=world._mapped_country_paths()
    assert zoom is not first
    world.grab()
    assert zoom is world._mapped_country_paths()


def test_country_badge_provenance_and_cluster_pin_survive_cached_hover(world):
    record={
        "id":"qa-government-source", "title":"Synthetic transport notice",
        "category":"Government","country":"United States of America",
        "country_basis":"provider_incident",
        "status":"active","latitude":None,"longitude":None,"map_areas":[],
        "reports":[{
            "id":"qa-government-source-report",
            "title":"Synthetic transport notice",
            "source_id":"qa-offline-source",
            "country":"United States of America",
            "country_basis":"provider_incident",
            "category":"Government","official":False,
            "evidence_status":"active",
            "published_at":"2026-11-13T17:00:00Z",
            "publication_time_known":True,
        }],
    }
    world.set_events([],country_events=[record])
    world.grab()
    assert world.visible_clusters()==[]
    assert world._country_badge_hits
    paths=world._mapped_country_paths()
    world._hover_country="United States of America"
    world.grab()
    assert world._mapped_country_paths() is paths
    assert world.country_category_evidence_for("United States of America")["count"]==1
    assert all(h[3]=="Government" for h in world._country_badge_hits)
