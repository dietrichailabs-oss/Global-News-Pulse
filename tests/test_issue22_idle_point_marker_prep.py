"""Issue22: cached point-cluster paint metadata survives no-click Qt repaints.

This exercises real Qt/QPainter and 5,000 fictional points with no network.
It is Engineering evidence, not native owner Win11 or independent QA.
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from global_pulse.map_widget import WorldMap


TRACKED = {"severity", "verification", "geo_precision", "id"}


class CountingRecord(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.marker_reads = 0

    def get(self, key, default=None):
        if key in TRACKED:
            self.marker_reads += 1
        return super().get(key, default)


def _record(i, *, severity="informational"):
    return CountingRecord(
        id=f"FICTIONAL-point-{i}", title="Fictional point only",
        category="News", severity=severity,
        verification="unverified", geo_precision="precise",
        latitude=(i % 120) - 60, longitude=(i % 360) - 180,
    )


def _paint(app, world):
    world.update()
    app.processEvents()
    image = world.grab()
    assert not image.isNull()
    return image.toImage()


def test_real_qt_5000_point_markers_prepare_only_on_changed_view():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        world.resize(880, 520)
        records = [_record(i) for i in range(5000)]
        world.set_events(records, country_events=[], observations=[])
        world.show()
        _paint(app, world)
        specs = world._cluster_paint_specs
        key = world._cluster_paint_key
        assert key is not None and specs
        assert sum(m["size"] for m in specs) <= 5000
        assert all(m["members"] and m["radius"] > 0 and m["group"]
                   for m in specs)
        before_reads = sum(r.marker_reads for r in records)
        assert before_reads > 0

        milliseconds = []
        for _ in range(6):
            start = time.perf_counter()
            _paint(app, world)
            milliseconds.append(1000 * (time.perf_counter() - start))
            assert world._cluster_paint_key == key
            assert world._cluster_paint_specs is specs
            # No repeat severity rank, selected-ID scan, or representative
            # metadata lookup on unchanged idle/expose Qt paints.
            assert sum(r.marker_reads for r in records) == before_reads
        print("cached_cluster_markers=" + str(len(specs)) +
              " six_5000_point_paints_ms=" +
              ",".join(f"{v:.3f}" for v in milliseconds))
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()


def test_real_qt_selection_remains_live_and_view_source_filters_invalidate():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        world.resize(800, 490)
        records = [_record(i) for i in range(180)]
        world.set_events(records, country_events=[], observations=[])
        world.show()
        before_image = _paint(app, world)
        specs = world._cluster_paint_specs
        assert specs
        selected_id = next(iter(specs[0]["members"]))
        world.select_event(selected_id)
        after_image = _paint(app, world)
        # Selection ring is live even when all cluster metadata is reused.
        assert world._cluster_paint_specs is specs
        assert before_image != after_image
        assert any(selected_id in m["members"] for m in specs)

        world.zoom_by(1.3)
        _paint(app, world)
        zoomed = world._cluster_paint_specs
        assert zoomed is not specs

        world.categories = {"Economy"}
        _paint(app, world)
        assert world._cluster_paint_specs is not zoomed
        assert world._cluster_paint_specs == ()

        world.categories = None
        world.set_events([_record(i + 1000, severity="critical")
                          for i in range(180)], country_events=[], observations=[])
        _paint(app, world)
        assert world._cluster_paint_specs
        assert world._cluster_paint_specs is not specs
        assert not any(selected_id in m["members"]
                       for m in world._cluster_paint_specs)
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()
