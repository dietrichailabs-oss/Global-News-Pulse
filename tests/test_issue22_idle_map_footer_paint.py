"""Issue #22: repeated startup/idle map paints do not rescan 5,000 points.

Real Qt QPainter path, offline synthetic input. Engineering-only evidence:
not a release/smoothness or owner physical Windows verification.
"""
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication

from global_pulse.map_widget import WorldMap


def _event(index, valid=True):
    return {
        "id": f"FICTIONAL-coverage-{index}",
        "title": "FICTIONAL map footer performance fixture",
        "category": "News",
        "severity": "informational",
        "verification": "unverified",
        "latitude": float(index % 120 - 60) if valid else None,
        "longitude": float(index % 360 - 180) if valid else None,
    }


def test_real_qt_initial_idle_hover_and_expose_repaints_never_rescan_footer():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        world.resize(880, 520)
        # The 5000-record cap and location precision are real application
        # constraints; 3200 valid incident points, 1800 unlocated reports.
        points = [_event(i, i < 3200) for i in range(5000)]
        world.set_events(points, country_events=[], observations=[])
        assert world._footer_point_count == 3200
        assert world._footer_coverage_text().startswith(
            "3200 points / 0 reports assessed · 0 warning areas · 1.0×"
        )
        world.show()
        app.processEvents()
        assert not world.grab().isNull()
        assert world._cluster_view_key is not None
        repaint_ms = []
        # A cached point-cluster paint may still do legitimate painter work.
        # What it must NOT do is invoke has_location for all 5000 source
        # records merely to rebuild the footer on hover/expose/no-click.
        with patch.object(
            WorldMap, "has_location",
            side_effect=AssertionError("5k-point footer scan on Qt repaint"),
        ):
            for _ in range(6):
                begin = time.perf_counter()
                world.update()
                app.processEvents()
                assert not world.grab().isNull()
                repaint_ms.append((time.perf_counter()-begin)*1000)
                assert world._footer_point_count == 3200
        print(
            "map_footer_no_click_render_ms="
            + ",".join(f"{duration:.3f}" for duration in repaint_ms)
            + " repeated_footer_location_scans=0"
        )
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()


def test_footer_source_revision_5k_cap_category_warning_and_zoom_semantics():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        points = [_event(i, valid=i < 9) for i in range(11)]
        world.set_events(points, country_events=[], observations=[])
        assert world._footer_point_count == 9
        assert "9 points / 0 reports assessed" in world._footer_coverage_text()
        # These synthetic Qt paths stand in for already-validated areas:
        # footer counting remains live when the user changes layer filters.
        world.area_layer.paths = [
            (QPainterPath(), {"category": "Disaster"}, {"context_only": False}),
            (QPainterPath(), {"category": "Health"}, {"context_only": True}),
        ]
        assert "2 warning areas" in world._footer_coverage_text()
        world.categories = {"Health"}
        assert "1 warning areas" in world._footer_coverage_text()
        assert world._footer_point_count == 9  # original all-category total
        world.zoom = 1.8
        assert world._footer_coverage_text().endswith("1.8×")
        # Replacing source data must update the count, never reuse a stale
        # footer value; invalid coordinates must not become point markers.
        world.set_events([_event(20), _event(21, False)], country_events=[])
        assert world._footer_point_count == 1
        assert "1 points / 0 reports assessed · 1 warning areas · 1.8×" in (
            world._footer_coverage_text()
        )
        world.set_events([_event(i) for i in range(5100)], country_events=[])
        assert len(world.events) == 5000
        assert world._footer_point_count == 5000
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()
