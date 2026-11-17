"""Regression for one-pass, source-faithful map-coverage counting.

Preserve exactly the old summary semantics across map filter changes, including
synthetic test rows. Never infer point coordinates from publisher country.
The test also enforces that a no-change summary does not rescan 5k reports.
"""
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from global_pulse.crisis_overlay import normalize_country
from global_pulse.map_evidence import incident_country
from global_pulse.map_widget import WorldMap, _map_category


def _old_summary_counts(world):
    allowed = None if world.categories is None else {
        _map_category(c) for c in world.categories
    }
    selected = [
        event for event in world.evidence_events
        if allowed is None or _map_category(event.get("category")) in allowed
    ]
    countries = {normalize_country(c["name"]) for c in world._countries}
    points = sum(world.has_location(event) for event in selected)
    unlocated = sum(
        not world.has_location(event)
        and not event.get("map_areas")
        and normalize_country(incident_country(event)) not in countries
        for event in selected
    )
    return points, unlocated


def _fixture():
    return [
        {"id":"known-point","country":"Ukraine","category":"Conflict",
         "latitude":49.1,"longitude":32.5,"synthetic":True},
        {"id":"unknown-point","country":"Not A Country","category":"Health",
         "latitude":10,"longitude":0,"synthetic":True},
        {"id":"unknown-area","country":"Not A Country","category":"Disaster",
         "map_areas":[{"source":"synthetic"}],"synthetic":True},
        {"id":"unknown-no-geometry","country":"Not A Country",
         "category":"News","synthetic":True},
        {"id":"known-no-geometry","country":"Ukraine","category":"News",
         "synthetic":True},
        {"id":"zero-coordinate","country":"Ukraine","category":"Economy",
         "latitude":0,"longitude":0,"synthetic":True},
        {"id":"invalid-coordinate","country":"Not A Country","category":"News",
         "latitude":95,"longitude":42,"synthetic":True},
    ]


def _check(world):
    points, unlocated = _old_summary_counts(world)
    assert (world._coverage_points, world._coverage_unlocated) == (points, unlocated)
    summary = world.coverage_summary()
    assert summary.startswith(f"{points} points")
    assert summary.endswith(f" · {unlocated} unlocated")


def test_summary_reuses_activity_pass_and_preserves_old_country_semantics():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        data = _fixture()
        # Use supplied evidence records, not publisher hints or invented pins.
        world.set_events(data, country_events=data)
        _check(world)
        # The coverage label must not rescan 5k map records when its evidence
        # and categories have not changed. The classifier still runs whenever
        # set_events or an explicit map-category filter invalidates the index.
        with patch("global_pulse.map_widget.incident_country",
                   side_effect=AssertionError("unexpected summary incident scan")):
            with patch.object(WorldMap, "has_location",
                              side_effect=AssertionError("unexpected summary point scan")):
                assert "points" in world.coverage_summary()

        for filter_set in ({"News"}, {"Conflict"}, {"Health"}, {"Economy"}, set(), None):
            world.categories = filter_set
            _check(world)
        world.categories = None
        world.set_events(data[:3], country_events=data[:3])
        _check(world)
        world.set_events([], country_events=[])
        _check(world)
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()


def test_no_click_large_coverage_label_is_cached_between_revisions():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        records = [
            {"id":f"synthetic-{i}", "category":"Conflict" if i%2 else "News",
             "country":"Unknown Synthetic", "synthetic":True}
            for i in range(5000)
        ]
        world.set_events(records)
        _check(world)
        with patch.object(WorldMap, "has_location", side_effect=AssertionError("repeat full scan")):
            for _ in range(50):
                assert "5,000" not in world.coverage_summary()  # label isn't a row count
        world.categories = {"Conflict"}
        _check(world)
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()
