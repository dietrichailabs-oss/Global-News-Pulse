"""R20 owner's digital radio layout and bounded offline station/SDR tests."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from global_pulse.internet_radio import (
    BROADCAST_CATEGORIES,
    OWNER_TEST_WEBDR_ORIGIN,
    STATIONS,
    RadioPanel,
    station,
)
from global_pulse.sdr_directory import parse_directory


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app):
    radio = RadioPanel(confirm=lambda: False)
    yield radio
    radio.shutdown()
    radio.deleteLater()
    app.processEvents()


def test_broadcast_has_separate_tab_and_truthful_frequencies(panel):
    assert panel.radio_tabs.count() == 2
    assert "AM / FM" in panel.radio_tabs.tabText(0)
    assert "HAM" in panel.radio_tabs.tabText(1)
    assert panel.frequency_display.text() == "FM · 93.9 MHz"
    assert station("wnyc_am")["dial"] == "AM · 820 kHz"
    assert station("fip")["dial"] == "INTERNET STREAM"
    assert "requested" in panel.ham_frequency_display.accessibleName().lower()
    assert len(STATIONS) >= 18
    assert len({row["id"] for row in STATIONS}) == len(STATIONS)
    assert all(row["category"] in BROADCAST_CATEGORIES for row in STATIONS)
    assert all(row["url"].startswith("https://") for row in STATIONS)
    assert all(row["documentation"].startswith("https://") for row in STATIONS)


def test_broadcast_genre_filter_and_real_previous_next_buttons(panel):
    genre_index = panel.broadcast_category.findData("Music")
    panel.broadcast_category.setCurrentIndex(genre_index)
    assert panel.selector.count() >= 3
    assert all(station(panel.selector.itemData(i))["category"] == "Music"
               for i in range(panel.selector.count()))
    assert panel.frequency_display.text() == "INTERNET STREAM"
    first_id = panel.selector.currentData()
    panel.next.click()
    assert panel.selector.currentData() != first_id
    panel.previous.click()
    assert panel.selector.currentData() == first_id
    assert panel.status.text() == "OFF"
    assert panel._session is None


def test_preset_recalls_station_hidden_by_current_filter(panel):
    panel.presets[0] = "wqxr"
    panel.broadcast_category.setCurrentIndex(
        panel.broadcast_category.findData("News & Talk")
    )
    assert panel.selector.findData("wqxr") == -1
    assert panel.recall_preset(0)
    assert panel.broadcast_category.currentData() == "All stations"
    assert panel.selector.currentData() == "wqxr"
    assert panel.frequency_display.text() == "FM · 105.9 MHz"
    assert panel.status.text() == "OFF"


def test_ham_step_keys_change_exact_requested_frequency_without_auto_connect(panel, monkeypatch):
    panel._select_na5b_test()
    assert panel.receiver_url.text() == OWNER_TEST_WEBDR_ORIGIN
    assert panel.sdr_state == "OFF"
    assert not panel.receiver_connected
    assert panel.ham_frequency_display.text() == "7.100 MHz"
    assert "NA5B" in panel.ham_bands.text()
    target_values = []

    def capture_requested_tune(target):
        target_values.append(target)
        panel.frequency.setText(f"{target:g}")
        return True

    monkeypatch.setattr(panel, "tune_receiver", capture_requested_tune)
    panel.ham_forward.click()
    assert target_values == [7105.0]
    assert panel.ham_frequency_display.text() == "7.105 MHz"
    assert "7105 kHz" in panel.ham_frequency_detail.text()
    panel.ham_back.click()
    assert target_values == [7105.0, 7100.0]
    assert panel.ham_frequency_display.text() == "7.100 MHz"
    assert "7100 kHz" in panel.ham_frequency_detail.text()
    assert panel.sdr_state == "OFF"
    assert not panel.receiver_connected


def test_operator_bands_are_only_reported_when_directory_supplies_them(panel):
    data = json.dumps({"receivers": [
        {"url": "https://radio.example.org/", "name": "Example SDR",
         "bands": ["20 m", "40 m", "6 m", "20 m", "\nUnsafe"]},
    ]}).encode()
    rows = parse_directory("kiwisdr", data)
    assert len(rows) == 1
    assert rows[0]["bands"] == ["20 m", "40 m", "6 m"]
    panel.sdr_directory_cache["kiwisdr"] = rows
    panel.ham_selector.setCurrentIndex(1)
    panel._change_receiver_directory()
    panel.receiver_picker.setCurrentIndex(1)
    assert panel.ham_receiver_name.text() == "Example SDR"
    assert "20 m · 40 m · 6 m" in panel.ham_bands.text()
    assert "Exact bounds/availability" in panel.ham_bands.text()
    assert not panel.receiver_connected


def test_ham_advanced_scan_starts_hidden_and_stays_explicit(panel):
    assert panel.scan_controls.isHidden()
    assert not panel.scan_timer.isActive()
    panel.advanced_scan.click()
    assert not panel.scan_controls.isHidden()
    assert not panel.scan_timer.isActive()
    panel.advanced_scan.click()
    assert panel.scan_controls.isHidden()
