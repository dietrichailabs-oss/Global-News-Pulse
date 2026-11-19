"""Issue22: static country geometry is not re-rasterized on every no-click map paint.

Uses real Qt/QPainter on installed host, synthetic bounded map data and no
network. Engineering-only regression, not physical Windows11 acceptance.
"""
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from global_pulse.map_widget import WorldMap


def _record(index, located=True):
    return {
        "id": f"FICTIONAL-backdrop-{index}",
        "title": "FICTIONAL map paint fixture",
        "category": "News",
        "severity": "informational",
        "verification": "unverified",
        "latitude": float(index % 120 - 60) if located else None,
        "longitude": float(index % 360 - 180) if located else None,
    }


def _paint(app, world):
    world.update()
    app.processEvents()
    image = world.grab()
    assert not image.isNull()
    return image


def test_real_qt_5000_records_no_click_reuses_exact_backdrop():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        world.resize(880, 520)
        world.set_events(
            [_record(index, index < 3200) for index in range(5000)],
            country_events=[], observations=[],
        )
        world.show()
        first = _paint(app, world)
        assert not first.isNull()
        key = world._country_backdrop_key
        backing = world._country_backdrop_pixmap
        assert key is not None and backing is not None and not backing.isNull()

        measurements = []
        # In the old Qt path every idle/hover/expose paint walked and
        # rasterized every visible country outline, even at the same view.
        with patch.object(
            world, "_paint_country_backdrop",
            side_effect=AssertionError("unchanged country geometry re-rasterized on Qt"),
        ):
            for _ in range(6):
                begin = time.perf_counter()
                _paint(app, world)
                measurements.append((time.perf_counter() - begin) * 1000)
                assert world._country_backdrop_key == key
                assert world._country_backdrop_pixmap is backing
        print("country_backdrop_cached_repaint_ms=" +
              ",".join(f"{duration:.3f}" for duration in measurements) +
              " repeated_geometry_rasterizations=0")
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()


def test_real_qt_source_hover_selection_categories_and_view_invalidate_backdrop():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        world.resize(800, 490)
        world.set_events([_record(i) for i in range(100)],
                         country_events=[], observations=[])
        world.show()
        _paint(app, world)
        first = world._country_backdrop_pixmap
        assert first is not None
        with patch.object(world, "_paint_country_backdrop",
                          wraps=world._paint_country_backdrop) as repaint_geography:
            _paint(app, world)
            assert repaint_geography.call_count == 0

            world._hover_country = "France"
            _paint(app, world)
            assert repaint_geography.call_count == 1
            hover_pixmap = world._country_backdrop_pixmap
            assert hover_pixmap is not first

            world.selected_country = "France"
            _paint(app, world)
            assert repaint_geography.call_count == 2

            world.categories = {"Conflict"}
            _paint(app, world)
            assert repaint_geography.call_count == 3

            world.set_crisis_layer("conflict", False)
            _paint(app, world)
            assert repaint_geography.call_count == 4

            world.zoom_by(1.2)
            _paint(app, world)
            assert repaint_geography.call_count == 5

            # Real corrected source must not retain the old country backing.
            world.set_events([_record(300), _record(301, False)],
                             country_events=[], observations=[])
            assert world._country_backdrop_key is None
            _paint(app, world)
            assert repaint_geography.call_count == 6

            _paint(app, world)
            assert repaint_geography.call_count == 6
        assert world._footer_point_count == 1
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()
