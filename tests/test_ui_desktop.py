"""Meaningful desktop integration checks. Windows native acceptance is separate."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.map_widget import WorldMap


@pytest.fixture(scope="module")
def qtapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(qtapp, tmp_path):
    controller = Controller(tmp_path, demo=True)
    window = MainWindow(controller)
    window.show()
    qtapp.processEvents()
    yield window, controller
    window._force_close = True
    window.close()
    controller.close()


def load_scenario(controller):
    scenario=json.loads((Path(__file__).parent/"fixtures"/"crisis.json").read_text())
    for stage in scenario["stages"]:
        controller.store.ingest(stage["reports"],now=stage["at"])
        controller.store.put_observations(stage.get("observations",[]))
    controller.data_changed.emit()
    return controller.events()[0]



def test_economy_only_country_circle_navigates_real_economy_filter(desktop, qtapp):
    window, controller = desktop
    controller.store.put_observations([{
        "source_id": "world_bank", "indicator": "GDP growth",
        "country": "United States of America", "observation_date": "2025",
        "value": 1.0, "unit": "percent",
        "release_date": "2026-01-01",
        "retrieved_at": "2026-11-13T20:00:00Z",
        "url": "https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG",
    }])
    window.world_map.set_events([], country_events=[],
                                observations=controller.store.list_observations())
    window.world_map.grab()
    hits = [hit for hit in window.world_map._country_badge_hits
            if hit[2] == "United States of America" and hit[3] == "Economy"]
    assert len(hits) == 1
    point = hits[0][0].toPoint()
    QTest.mouseClick(window.world_map, Qt.MouseButton.LeftButton, pos=point)
    qtapp.processEvents()
    assert window.pages.currentIndex() == 2
    assert window.economy_country.currentText() == "United States of America"
    assert "dated sourced observations" in window.status_label.text()

def test_real_empty_archive_has_no_simulated_events(desktop, qtapp):
    window,controller=desktop
    assert window.feed_list.count()==0
    assert window.feed_empty.isVisible()
    assert len(window.world_map._countries)==177
    assert len(window.world_map.events)==0
    assert "Connect the evidence" in window.intel_browser.toPlainText()
    assert not window.save_button.isEnabled()


def test_real_fixture_selection_source_trail_and_escaping(desktop,qtapp):
    window,controller=desktop
    event=load_scenario(controller)
    window.navigate_event(event["id"]);qtapp.processEvents()
    text=window.intel_browser.toPlainText()
    assert "FICTIONAL TRAINING EVENT" in text
    assert "SOURCE TRAIL" in text
    assert "Fictional" in text
    assert window._selected_id==event["id"]
    assert window.world_map.selected_event==event["id"]
    assert window.save_button.isEnabled()


def test_source_trail_labels_outlet_country_as_provenance_not_event_location(desktop, qtapp):
    window, controller = desktop
    raw = {
        "id": "gdelt-ui-provenance",
        "source_id": "gdelt_world_press",
        "publisher": "example.fr",
        "title": "French outlet metadata record",
        "url": "https://example.fr/world/story",
        "retrieved_at": "2026-11-09T22:00:00Z",
        "published_at": "2026-11-09T21:00:00Z",
        "summary": "Metadata-only discovery record.",
        "language": "fr",
        "region": "Global",
        "country": "",
        "source_country": "France",
        "category": "News",
        "kind": "report",
        "origin_id": "",
        "independence": "unknown",
        "event_key": "gdelt:ui-provenance",
        "severity": "unassessed",
        "claims": {},
        "media": [],
        "official": False,
        "synthetic": True,
        "metadata_only": True,
        "retention_days": 30,
    }
    event = controller.store.ingest([raw], now="2026-11-09T22:00:00Z")[0]
    controller.data_changed.emit()
    window.navigate_event(event["id"])
    qtapp.processEvents()
    text = window.intel_browser.toPlainText()
    assert "Outlet/source country (not event location): France" in text
    assert "Metadata-only discovery record" in text
    assert event["country"] == ""


def test_deep_link_restores_main_window_and_exact_event(desktop,qtapp):
    window,controller=desktop
    event=load_scenario(controller)
    window.open_page(3);window.hide()
    window.navigate_event(event["id"]);qtapp.processEvents()
    assert window.isVisible()
    assert window.pages.currentIndex()==0
    assert window._selected_id==event["id"]


def test_historical_view_does_not_show_later_retraction(desktop,qtapp):
    window,controller=desktop
    event=load_scenario(controller)
    window.navigate_event(event["id"])
    window.time_range.setCurrentIndex(3)
    window.history_slider.setValue(0);qtapp.processEvents()
    snapshot=window._selected_event()
    assert snapshot and snapshot["revision"]==1
    assert snapshot["verification"]=="unverified"
    assert len(snapshot["reports"])==1
    assert not any(r.get("kind")=="retraction" for r in snapshot["reports"])
    assert window.world_map.events[0]["revision"]==1
    # Native activation must leave historical playback and select current event.
    window.navigate_event(event["id"])
    assert window.history_slider.value()==1000
    assert window._selected_event()["revision"]>1


def test_search_filters_actual_local_archive(desktop,qtapp):
    window,controller=desktop
    load_scenario(controller)
    window.search.setText("zzzzNoSuchStory");window.refresh_data()
    assert window.feed_list.count()==0
    window.search.clear();window.refresh_data()
    assert window.feed_list.count()>0


def test_situation_changes_and_economy_show_stored_data(desktop,qtapp):
    window,controller=desktop
    event=load_scenario(controller)
    window.navigate_event(event["id"]);window._save_selected();window.open_page(1)
    assert window.situation_list.count()==1
    window._visit_situation(window.situation_list.item(0))
    assert "What changed since my last visit" in window.situation_browser.toPlainText()
    window._visit_situation(window.situation_list.item(0))
    assert "No newer recorded changes" in window.situation_browser.toPlainText()
    window.open_page(2)
    assert window.economy_table.rowCount()>0
    assert window.economic_chart.observations


def test_external_access_limitations_cannot_be_enabled_in_settings(desktop):
    window,controller=desktop
    for i,source in enumerate(controller.catalog):
        if source.get("access_status")=="review_required":
            assert not window.source_preferences.cellWidget(i,0).isEnabled()


def test_all_workspaces_and_settings_with_real_scenario(desktop,qtapp):
    window,controller=desktop
    controller.load_fixture(Path(__file__).parent/"fixtures"/"crisis.json")
    window.resize(960,640)
    for index in range(7):
        window.open_page(index);qtapp.processEvents()
        assert window.pages.currentIndex()==index
    assert "Global Pulse" in window.brief_browser.toPlainText()
    assert window.source_table.rowCount()==len(controller.catalog)
    assert window.alert_list.count()>0
    window.setting_interval.setCurrentIndex(2)
    window.setting_countries.setText("Japan, South Africa")
    window.setting_quiet.setChecked(True)
    window.setting_threshold.setCurrentIndex(3)
    window._save_settings()
    assert controller.get_setting("interval")==1800
    assert controller.get_setting("countries")==["Japan","South Africa"]
    assert controller.get_setting("quiet_enabled") is True
    assert controller.get_setting("alert_threshold")=="high"
    assert "Settings saved" in window.settings_result.text()


def test_all_map_layers_can_be_disabled_and_state_restored(qtapp):
    world=WorldMap();world.resize(1000,350)
    world.set_events([{"id":"one","latitude":1,"longitude":1,"category":"Disaster"}])
    assert len(world.visible_clusters())==1
    world.categories=set()
    assert world.visible_clusters()==[]
    state=world.view_state()
    copy=WorldMap();copy.restore_view(state)
    assert copy.categories==set()
    world.close();copy.close()


def test_close_handler_and_persisted_view(desktop,qtapp):
    window,controller=desktop
    calls=[]
    # Bootstrap, not QWidget.closeEvent, owns one deferred save. Model that
    # queued persistence without exercising a real OS tray in offscreen Qt.
    window.set_close_handler(lambda:(calls.append("close"),QTimer.singleShot(0,window.save_layout)))
    window.world_map.zoom_by(2)
    window.close();qtapp.processEvents()
    assert calls==["close"]
    assert window.isVisible() # Bootstrap decides hide or exit; Qt did not destroy it.
    assert controller.get_setting("map_view")["zoom"]==2.0
    assert controller.get_setting("window_geometry")


def test_close_handler_does_not_block_ui_with_layout_database_write(desktop):
    window,_=desktop
    calls=[]
    window.save_layout=lambda:calls.append("unexpected synchronous save")
    window.set_close_handler(lambda:calls.append("handler"))
    window.close()
    assert calls==["handler"]
    assert window.isVisible()


def test_small_window_map_stays_inside_panel(desktop,qtapp):
    window,controller=desktop
    window.resize(960,640);qtapp.processEvents()
    assert window.width()==960 and window.height()==640
    position=window.world_map.mapTo(window.map_panel,window.world_map.rect().bottomLeft())
    assert position.y()<window.map_panel.height()
    assert window.world_map.height()>=100


def test_offline_map_navigation_and_geographic_uncertainty(qtapp):
    world=WorldMap();world.resize(1000,350);world.show();qtapp.processEvents()
    assert world.select_country("Japan")
    assert world.selected_country=="Japan"
    assert world.zoom>1
    world.reset_view();assert world.zoom==1
    assert not world.select_country("Imaginary country")
    # Unknown coordinates must never be invented; zero is a valid supplied value.
    world.set_events([{"id":"unknown","latitude":None,"longitude":None},
                      {"id":"known","latitude":0.0,"longitude":0.0,"severity":"high","verification":"unverified"}])
    clusters=world.visible_clusters()
    assert len(clusters)==1 and clusters[0][0][0]["id"]=="known"
    world.close()
