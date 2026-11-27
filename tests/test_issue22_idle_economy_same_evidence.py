"""Source-faithful no-click Economy prewarm: avoid redundant Qt model/chart work.

Synthetic 3,200-row fixtures; hosted offscreen/native CI is not physical Win11 acceptance.
"""
from copy import deepcopy
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def _close(app, window, controller):
    if window is not None:
        window._force_close = True
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer", "search_timer"):
            getattr(window, name).stop()
        window.media.shutdown()
        window.close()
        window.deleteLater()
    controller.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _queue_and_warm(window, controller, observations):
    # Exact revision-guarded worker handoff, not a stale cached SQL result.
    window._deferred_economy_observations = deepcopy(observations)
    window._deferred_economy_revision = controller.store.content_revision()
    window._dirty_pages.add(2)
    window._last_navigation_at = time.monotonic() - 3
    window._workspace_warm_timer.stop()
    window._warm_next_workspace()
    window._workspace_warm_timer.stop()
    assert 2 not in window._dirty_pages


def _observations():
    return [
        {
            "indicator": "SYNTHETIC-GDP",
            "indicator_name": "SYNTHETIC economic indicator",
            "country_name": f"Fictional Land {i % 8}",
            "date": f"2026-11-{(i % 28) + 1:02d}",
            "value": float(i),
            "source_id": "fictional-dataset",
            "description": "Synthetic data only",
            "attribution": "FICTIONAL TEST SOURCE",
            "source_license": "Synthetic test data",
            "url": "https://example.org/fictional",
        }
        for i in range(3200)
    ]


def test_no_click_economy_same_evidence_skips_chart_and_model_reset(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        rows = _observations()
        window._populate_economy(deepcopy(rows))
        assert window.economy_model.rowCount() == 3200

        # A feed/source revision may dirty Economy even though its sourced
        # observations are unchanged. Do not reset its model or chart pixmap.
        old_pixmap = window.economic_chart._chart_pixmap
        with patch.object(window.economy_model, "set_observations",
                          wraps=window.economy_model.set_observations) as model, \
             patch.object(window.economic_chart, "set_observations",
                          wraps=window.economic_chart.set_observations) as chart:
            _queue_and_warm(window, controller, rows)
            assert model.call_count == chart.call_count == 0
        assert window.economy_model.rowCount() == 3200
        assert window.economic_chart._chart_pixmap is old_pixmap

        # Corrected source value and attribution must repaint even when the
        # number of rows, selected indicator, and Store revision are identical.
        corrected = deepcopy(rows)
        corrected[0]["value"] = 999999.0
        corrected[0]["attribution"] = "CORRECTED FICTIONAL SOURCE"
        with patch.object(window.economy_model, "set_observations",
                          wraps=window.economy_model.set_observations) as model, \
             patch.object(window.economic_chart, "set_observations",
                          wraps=window.economic_chart.set_observations) as chart:
            _queue_and_warm(window, controller, corrected)
            assert model.call_count == chart.call_count == 1
        assert any(item.get("value") == 999999.0 for item in window.economy_model._rows)

        # An explicit queued map country always resolves and binds one real
        # country series, even if evidence bytes have not changed.
        window._pending_economic_country = "Fictional Land 3"
        with patch.object(window.economy_model, "set_observations",
                          wraps=window.economy_model.set_observations) as model:
            _queue_and_warm(window, controller, corrected)
            assert model.call_count == 1
        assert window._pending_economic_country is None
        assert window.economy_country.currentData() == "Fictional Land 3"
        assert window.economy_model.rowCount() == 400
        assert all(item["country_name"] == "Fictional Land 3"
                   for item in window.economy_model._rows)

        # Removing actual source records is not an identical-data repaint
        # skip; the displayed country loses precisely its withdrawn row.
        withdrawn = [o for o in corrected if o["country_name"] != "Fictional Land 3"]
        _queue_and_warm(window, controller, withdrawn)
        assert window.economy_country.findData("Fictional Land 3") == -1
        assert window.economy_model.rowCount() == len(withdrawn)
    finally:
        _close(app, window, controller)
