"""Issue82 owner regression: large Economy datasets must not freeze tab navigation.

Synthetic/offline Qt: this does not claim a native Windows timing witness.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTableView

from global_pulse.controller import Controller
from global_pulse.ui import EconomicChart, EconomicTableModel, MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def desktop(app, tmp_path):
    controller = Controller(tmp_path, demo=True)
    window = MainWindow(controller)
    window.show()
    app.processEvents()
    yield window, controller
    window._workspace_warm_timer.stop()
    window._evidence_refresh_timer.stop()
    window.media.shutdown()
    window._force_close = True
    window.close()
    controller.close()
    window.deleteLater()
    app.processEvents()


def observations(count=12000):
    return [
        {
            "indicator": "wb_inflation",
            "country": f"C{i % 180:03d}",
            "country_name": f"Country {i % 180:03d}",
            "date": f"{2010 + (i % 16)}",
            "value": float(i % 500) / 10,
            "previous_value": None,
            "source_id": "wb_inflation",
            "url": f"https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG?locations={i % 180}",
        }
        for i in range(count)
    ]


def test_large_economy_table_uses_virtual_model_not_per_cell_widgets(desktop):
    window, _ = desktop
    sample = observations()
    assert window.prepare_initial_workspaces()
    assert isinstance(window.economy_table, QTableView)
    assert isinstance(window.economy_model, EconomicTableModel)
    window._observations_by_indicator = {"wb_inflation": sample}
    window.indicator_combo.clear()
    window.indicator_combo.addItem("Inflation", "wb_inflation")
    window._populate_economic_selection()
    assert window.economy_model.rowCount() == len(sample)
    assert window.economy_model.columnCount() == 9
    # On a populated table, source identity remains attached to the row.
    assert window.economy_model.url_at(0).startswith("https://data.worldbank.org/")
    assert window.economy_model.data(window.economy_model.index(0, 0)) != "Missing"
    assert not hasattr(window.economy_table, "setRowCount"), "No QTableWidget 108k-item allocation"


def test_chart_reuses_raster_when_navigating_without_data_or_size_changes(desktop, app, monkeypatch):
    window, _ = desktop
    window.prepare_initial_workspaces()
    window.open_page(2)
    chart = window.economic_chart
    chart.set_observations(observations(2200))
    draws = []
    original = EconomicChart._paint_chart

    def counted(self, painter):
        draws.append(1)
        return original(self, painter)

    monkeypatch.setattr(EconomicChart, "_paint_chart", counted)
    chart.grab()  # First paint generates the cached raster.
    assert draws
    painted = len(draws)
    for _ in range(12):
        window.open_page(1)
        window.open_page(2)
        chart.grab()
        app.processEvents()
    assert len(draws) == painted, "Unchanged Economy chart must not redraw all countries"


def test_live_revision_waits_for_navigation_idle(desktop, monkeypatch):
    window, controller = desktop
    window.prepare_initial_workspaces()
    called = []
    monkeypatch.setattr(window, "refresh_data", lambda:called.append(1))
    for _ in range(20):
        window.open_page(2)
        controller.data_changed.emit()
        window.open_page(0)
    window._evidence_refresh_timer.stop()
    window._refresh_evidence_when_idle()
    assert not called, "Collector updates must not build 5k items between clicks"
    assert window._evidence_refresh_timer.isActive()
    window._evidence_refresh_timer.stop()
    window._last_navigation_at=time.monotonic()-2
    window._refresh_evidence_when_idle()
    assert called == [1], "Once idle, the pending collector revision is applied"
