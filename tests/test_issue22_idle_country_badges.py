"""Engineering Qt regression: no passive source/category badge layout work.

Fictional country-attributed source counts and dated economy observations.
This is hosted Qt evidence, not physical Windows 11 or independent QA.
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from global_pulse.crisis_overlay import normalize_country
from global_pulse.map_widget import WorldMap


class CountingIndex(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lookups = 0

    def get(self, key, default=None):
        self.lookups += 1
        return super().get(key, default)


def paint(app, world):
    world.update()
    app.processEvents()
    shot = world.grab()
    assert not shot.isNull()
    return shot.toImage()


def fixture():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    world.resize(900, 540)
    world.set_events([], country_events=[], observations=[])
    countries = [c for c in world._countries
                 if c.get("label") and c["name"] != "Antarctica"][:55]
    assert len(countries) > 10
    index = CountingIndex({
        normalize_country(c["name"]): {
            "categories": {"Conflict": 2, "Government": 1, "Health": 3},
        }
        for c in countries
    })
    world.country_category_evidence = index
    world.economic_observations = {
        normalize_country(c["name"]): {"count": 7, "latest": "2025-01-01"}
        for c in countries
    }
    return app, world, index


def test_unchanged_real_qt_badges_reuse_layout_and_click_hits():
    app, world, index = fixture()
    try:
        world.show()
        paint(app, world)
        specs = world._country_badge_specs
        hits = world._country_badge_hits
        assert specs and hits and len(specs) == len(hits)
        assert index.lookups > 0
        assert any(category == "Economy" and "dated economic observation" in desc
                   for _point, _color, _name, category, desc in specs)
        assert any(category == "Conflict" and "source record" in desc
                   for _point, _color, _name, category, desc in specs)
        before = index.lookups
        times = []
        for _ in range(6):
            started = time.perf_counter()
            paint(app, world)
            times.append((time.perf_counter() - started) * 1000)
            assert world._country_badge_specs is specs
            assert world._country_badge_hits is hits
            assert index.lookups == before
        print("badge_specs=" + str(len(specs)) +
              " six_cached_real_qt_paints_ms=" +
              ",".join(f"{value:.3f}" for value in times))
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()


def test_source_view_filter_and_dpi_invalidation_without_stale_hits():
    app, world, index = fixture()
    try:
        world.show()
        paint(app, world)
        original = world._country_badge_specs
        assert original
        world.zoom_by(1.25)
        paint(app, world)
        zoomed = world._country_badge_specs
        assert zoomed is not original
        assert world._country_badge_hits
        world.categories = {"News"}
        paint(app, world)
        assert world._country_badge_specs is not zoomed
        assert world._country_badge_specs == ()
        assert world._country_badge_hits == []
        world.categories = None
        world.set_events([], country_events=[], observations=[])
        assert world._country_badge_specs == ()
        assert world._country_badge_hits == []
        paint(app, world)
        assert world._country_badge_specs == ()
        # A fresh exact-source country/dated-economy index, never an incident
        # point or synthetic crisis, must redraw badges after source change.
        world.country_category_evidence = CountingIndex({
            normalize_country(c["name"]): {"categories": {"Health": 2}}
            for c in world._countries if c.get("label")
        })
        world._country_badge_key = None  # emulate accepted source snapshot
        paint(app, world)
        assert any(category == "Health" for *_prefix, category, _descriptor
                   in world._country_badge_specs)
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()
