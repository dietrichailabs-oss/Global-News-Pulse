"""Issue82 owner regression: large Economy datasets must not freeze tab navigation.

Synthetic/offline Qt: this does not claim a native Windows timing witness.
"""
from __future__ import annotations

import os
import statistics
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTableView
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

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
        controller.evidence_changed.emit()
        window.open_page(0)
    window._evidence_refresh_timer.stop()
    window._refresh_evidence_when_idle()
    assert not called, "Collector updates must not build 5k items between clicks"
    assert window._evidence_refresh_timer.isActive()
    window._evidence_refresh_timer.stop()
    window._last_navigation_at=time.monotonic()-2
    window._last_full_refresh_at=time.monotonic()-6
    window._refresh_evidence_when_idle()
    assert called == [1], "Once idle, the pending collector revision is applied"
    controller.data_changed.emit()
    assert called == [1], "Controller signals must not synchronously rebuild the map"
    assert window._evidence_refresh_timer.isActive()
    window._evidence_refresh_timer.stop()
    window._last_full_refresh_at=time.monotonic()-6
    window._refresh_evidence_when_idle()
    assert called == [1,1], "The coalesced settings revision must still become visible"


def test_collector_bursts_are_spaced_to_protect_video_and_tab_input(desktop, monkeypatch):
    window, controller = desktop
    assert window.prepare_initial_workspaces()
    calls=[]
    monkeypatch.setattr(window,"refresh_data",lambda:calls.append(time.monotonic()))
    window._last_navigation_at=time.monotonic()-10
    window._last_full_refresh_at=time.monotonic()
    for _ in range(120):
        controller.data_changed.emit()
        controller.evidence_changed.emit()
    window._evidence_refresh_timer.stop()
    window._refresh_evidence_when_idle()
    assert calls==[], "Fast collector bursts must not force repeated GUI work"
    assert window._evidence_refresh_timer.isActive()
    window._evidence_refresh_timer.stop()
    window._last_full_refresh_at=time.monotonic()-6
    window._refresh_evidence_when_idle()
    assert len(calls)==1


def test_repeated_fast_navigation_on_preloaded_sqlite_economy(desktop, app, monkeypatch):
    """Actual SQLite read plus 6,400 persisted records, then fast tab paints.

    Timings are synthetic CI measurements, not claimed owner Win11 results.
    Nothing in a tab click is allowed to query SQLite or reload economic rows.
    """
    window, controller = desktop
    sample = observations(6400)
    for i, record in enumerate(sample):
        record["country"] = f"C{i % 200:03d}"
        record["date"] = str(1980 + (i // 200))
        record["synthetic"] = True
    for offset in range(0, len(sample), 1600):
        assert controller.store.put_observations(sample[offset:offset+1600]) == min(1600, len(sample)-offset)
    window._dirty_pages.add(2)
    assert window.prepare_initial_workspaces()
    assert window.economy_model.rowCount() >= 6400

    def forbidden(*args, **kwargs):
        raise AssertionError("Tab click synchronously queried 6400 economic rows")

    monkeypatch.setattr(controller.store, "list_observations", forbidden)
    heartbeat = []
    timer = QTimer(window)
    timer.setInterval(16)
    timer.timeout.connect(lambda: heartbeat.append(time.perf_counter()))
    timer.start()
    durations = []
    indexes = [0,2,1,2,3,2,4,2,5,2] * 12
    try:
        for step, index in enumerate(indexes):
            began = time.perf_counter()
            window.open_page(index)
            app.processEvents()
            durations.append(time.perf_counter() - began)
            if step % 8 == 0:
                QTest.qWait(18)
    finally:
        timer.stop()
    assert heartbeat, "The event loop must still dispatch timer heartbeats"
    max_gap=max((later-earlier for earlier,later in zip(heartbeat,heartbeat[1:])),default=0)
    print("\nSynthetic preloaded SQLite tab navigation: "
          f"max_switch_ms={max(durations)*1000:.1f}, "
          f"median_switch_ms={statistics.median(durations)*1000:.1f}, "
          f"max_heartbeat_gap_ms={max_gap*1000:.1f}, "
          f"switches={len(durations)}, heartbeat_ticks={len(heartbeat)}")
    # A one-second UI stall is the specific owner regression. Use a wide
    # CI threshold; measured owner hardware latency remains unverified.
    assert max(durations) < 0.5, f"A fast tab switch stalled {max(durations):.3f}s"
    assert statistics.median(durations) < 0.1
