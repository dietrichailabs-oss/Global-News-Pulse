"""Issue22: no-click country labels keep exactly the same view layout.

Real Qt/QPainter and bounded 5,000-record synthetic data; no network,
no claims about physical Windows11 animation, independent QA, or media.
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from global_pulse.map_widget import WorldMap


def _record(number):
    return {
        "id": f"FICTIONAL-label-{number}",
        "title": "FICTIONAL label layout fixture",
        "category": "News",
        "severity": "informational",
        "verification": "unverified",
        "latitude": (number % 120) - 60,
        "longitude": (number % 360) - 180,
    }


def _paint(app, world):
    world.update()
    app.processEvents()
    result = world.grab()
    assert not result.isNull()


def test_real_qt_5000_source_events_reuse_label_geometry_on_passive_paints():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        world.resize(880, 520)
        world.set_events([_record(i) for i in range(5000)],
                         country_events=[], observations=[])
        world.show()
        _paint(app, world)
        labels = world._country_label_specs
        key = world._country_label_key
        assert key is not None
        assert labels and all(name and rect.width() > 0 for rect, name in labels)
        assert len(labels) <= len(world._countries)

        elapsed = []
        for _ in range(6):
            before = time.perf_counter()
            _paint(app, world)
            elapsed.append((time.perf_counter() - before) * 1000)
            assert world._country_label_key == key
            assert world._country_label_specs is labels
        print("cached_country_labels=" + str(len(labels)) +
              " passive_5000_record_paints_ms=" +
              ",".join(f"{v:.3f}" for v in elapsed))
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()


def test_real_qt_zoom_resize_and_labels_toggle_keep_exact_layout():
    app = QApplication.instance() or QApplication([])
    world = WorldMap()
    try:
        world.resize(800, 490)
        world.set_events([_record(i) for i in range(100)],
                         country_events=[], observations=[])
        world.show()
        _paint(app, world)
        first_key = world._country_label_key
        first_labels = world._country_label_specs
        assert first_labels

        world.zoom_by(1.3)
        _paint(app, world)
        zoomed_key = world._country_label_key
        zoomed_labels = world._country_label_specs
        assert zoomed_key != first_key
        assert zoomed_labels is not first_labels

        world.resize(930, 580)
        _paint(app, world)
        resized_key = world._country_label_key
        assert resized_key != zoomed_key

        # No geography/labels changed: new source evidence should invalidate
        # source-dependent backdrop, but not reset static label placement.
        preserved = world._country_label_specs
        world.set_events([_record(i) for i in range(200, 300)],
                         country_events=[], observations=[])
        _paint(app, world)
        assert world._country_label_specs is preserved

        world.labels = False
        _paint(app, world)
        assert world._country_label_specs is preserved
        world.labels = True
        _paint(app, world)
        assert world._country_label_specs is preserved
    finally:
        world.close()
        world.deleteLater()
        app.processEvents()
