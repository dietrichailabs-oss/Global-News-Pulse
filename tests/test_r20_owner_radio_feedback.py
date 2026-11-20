"""Physical R20 feedback: visible tuner, discoverable durable presets, honest directory."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from global_pulse.core import Store
from global_pulse.internet_radio import RadioPanel
from global_pulse.sdr_directory import public_receiver_url, parse_directory
from global_pulse.theme import STYLE


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app):
    widget=RadioPanel(confirm=lambda:False)
    yield widget
    widget.shutdown()
    widget.close()
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("size",[(960,640),(600,480)])
def test_core_ham_tuner_and_connect_are_above_small_viewport_fold(panel,app,size):
    panel.setStyleSheet(STYLE)
    panel.radio_tabs.setCurrentIndex(1)
    panel.resize(*size)
    panel.show()
    app.processEvents()
    assert panel.width()<=size[0] and panel.height()<=size[1]
    assert panel.ham_details_scroll.isHidden()
    controls=(panel.ham_frequency_display,panel.ham_back,panel.ham_step,
                    panel.ham_forward,panel.frequency,panel.tune_button,
                    panel.receiver_picker,panel.receiver_connect,panel.receiver_off)
    for control in controls:
        assert control.isVisible(),control.accessibleName()
        point=control.mapTo(panel,QPoint(0,0))
        assert point.y()>=0
        assert point.y()+control.height()<=size[1],(control.accessibleName(),point.y(),control.height())
        assert point.x()>=0
        assert point.x()+control.width()<=size[0],(control.accessibleName(),point.x(),control.width())

    panel.ham_details_toggle.setChecked(True)
    panel.advanced_scan.setChecked(True)
    # Drain the follow-up LayoutRequest events too: one offscreen event pass
    # could miss a minimum-size resize that the native Windows backend sees.
    for _ in range(3):
        app.processEvents()
    assert panel.height()<=size[1],"Opening details must not force the window off-screen"
    assert panel.ham_details_scroll.viewport().height()>0
    assert panel.ham_details_scroll.verticalScrollBar().maximum()>0
    for control in controls:
        assert control.isVisible(),control.accessibleName()
        point=control.mapTo(panel,QPoint(0,0))
        assert point.y()>=0 and point.x()>=0
        assert point.y()+control.height()<=size[1]
        assert point.x()+control.width()<=size[0]
        surface=panel.radio_tabs.widget(1)
        assert surface.rect().contains(QRect(control.mapTo(surface,QPoint(0,0)),control.size()))


def test_ham_expanded_details_keep_viewport_with_taller_font_metrics(panel,app):
    # A +1px body-font stress reproduces the former native-style minimum-size
    # growth on Linux too, without substituting any Qt platform backend.
    panel.setStyleSheet(STYLE.replace("font-size: 12px;","font-size: 13px;"))
    panel.radio_tabs.setCurrentIndex(1)
    panel.resize(600,480)
    panel.show()
    app.processEvents()
    panel.ham_details_toggle.setChecked(True)
    panel.advanced_scan.setChecked(True)
    for _ in range(3):
        app.processEvents()
    assert panel.width()<=600 and panel.height()<=480
    assert panel.minimumSizeHint().height()<=470,"Keep real minimum-height headroom for native font metrics"
    assert panel.ham_details_scroll.viewport().height()>=24,"Details must show a usable scrolling row"
    for control in (panel.ham_receiver_name,panel.ham_frequency_display,
                    panel.ham_frequency_detail,panel.ham_back,panel.ham_step,panel.ham_forward,panel.frequency,
                    panel.tune_button,panel.receiver_picker,panel.receiver_connect,
                    panel.receiver_off,panel.sdr_status,panel.ham_details_toggle):
        assert control.isVisible()
        point=control.mapTo(panel,QPoint(0,0))
        assert 0<=point.y() and point.y()+control.height()<=480
        assert 0<=point.x() and point.x()+control.width()<=600
        surface=panel.radio_tabs.widget(1)
        assert surface.rect().contains(QRect(control.mapTo(surface,QPoint(0,0)),control.size()))


def test_preset_save_is_explicit_and_survives_actual_sqlite_close_reopen(panel,app,tmp_path):
    path=tmp_path/"preset-roundtrip.sqlite3"
    store=Store(path)
    try:
        store.set_setting("radio_presets",[{"receiver":"https://legacy.example.org/"}])
        panel.configure_preferences(store.get_setting,store.set_setting)
        panel.selector.setCurrentIndex(panel.selector.findData("wqxr"))
        panel.preset_slot.setCurrentIndex(2)
        panel.preset_save.click()
        assert panel.presets[2]=="wqxr"
        assert "Saved preset 3" in panel.preset_status.text()
        assert "WQXR" in panel.preset_slot.itemText(2)
        assert store.get_setting("internet_radio_presets_v1")[2]=="wqxr"
    finally:
        store.close()
    reopened=Store(path)
    other=RadioPanel(confirm=lambda:False)
    try:
        other.configure_preferences(reopened.get_setting,reopened.set_setting)
        other.broadcast_category.setCurrentIndex(other.broadcast_category.findData("News & Talk"))
        other.preset_slot.setCurrentIndex(2)
        other.preset_recall.click()
        assert other.selector.currentData()=="wqxr"
        assert "Recalled preset 3" in other.preset_status.text()
        assert not other.power.isChecked() and other._session is None
        assert reopened.get_setting("radio_presets")==[{"receiver":"https://legacy.example.org/"}]
        other.preset_clear.click()
        assert other.presets[2] is None
        assert reopened.get_setting("internet_radio_presets_v1")[2] is None
    finally:
        other.shutdown();other.deleteLater();app.processEvents()
        reopened.close()


def test_missing_or_unconfirmed_persistence_never_reports_save_success(panel):
    assert not panel.save_preset(0)
    assert panel.presets==[None]*5
    assert "not confirmed" in panel.preset_status.text()
    panel.configure_preferences(lambda key,default=None:default,lambda key,value:None)
    assert not panel.save_preset(0)
    assert panel.presets==[None]*5
    assert "not confirmed" in panel.preset_status.text()
    assert not panel.clear_preset(0)


def test_storage_failure_does_not_escape_save_button_or_replace_presets(panel):
    import sqlite3
    def failed_write(key,value):
        raise sqlite3.OperationalError("database is locked")
    panel.configure_preferences(lambda key,default=None:["wqxr"]+[None]*4,failed_write)
    panel.preset_save.click()
    assert panel.presets==["wqxr"]+[None]*4
    assert "not confirmed" in panel.preset_status.text()


def test_empty_preset_explains_explicit_save_action(panel):
    panel.preset_buttons[1].click()
    assert panel.preset_slot.currentData()==1
    assert "empty" in panel.preset_status.text()
    assert "Save preset" in panel.preset_status.text()


def test_local_discovery_selects_only_reviewed_id_without_powering_on(panel):
    assert panel.local_radio.body.isHidden()
    assert panel.local_radio._reply is None
    panel.broadcast_category.setCurrentIndex(panel.broadcast_category.findData("Music"))
    panel.local_radio.station_selected.emit("wqxr")
    assert panel.selector.currentData()=="wqxr"
    assert panel.broadcast_category.currentData()=="All stations"
    assert not panel.power.isChecked() and panel._session is None
    panel.local_radio.station_selected.emit("https://unreviewed.example.org/audio.mp3")
    assert panel.selector.currentData()=="wqxr"
    panel.shutdown()
    assert panel.local_radio._closed
    panel.local_radio.station_selected.emit("wnyc_fm")
    assert panel.selector.currentData()=="wqxr"


def test_websdr_import_requires_permission_and_never_requests_restricted_dataset(panel,monkeypatch):
    requested=[]
    monkeypatch.setattr(panel.sdr_network,"get",lambda request:requested.append(request))
    assert panel.ham_selector.currentData()["id"]=="websdr"
    assert panel.receiver_refresh.text()=="Directory info"
    assert not panel.refresh_receiver_directory()
    assert requested==[]
    assert "permission" in panel.directory_summary.text()
    assert "Open directory" in panel.directory_summary.text()
    # Individual owner-supplied NA5B remains selectable, not an imported list.
    panel.receiver_picker.setCurrentIndex(1)
    assert panel.receiver_url.text()=="http://na5b.com:8901/"
    assert panel.receiver_connect.isEnabled()
    assert not panel.receiver_connected


def test_official_websdr_frameset_is_not_mistaken_for_receiver_directory():
    # Minimal structure observed at the public homepage. The full provider
    # dataset is NOT copied into tests or automatically requested.
    wrapper=b'<FRAMESET><FRAME name="top" src="http://websdr.ewi.utwente.nl/org/"></FRAMESET>'
    assert parse_directory("websdr",wrapper)==[]


def test_public_receiver_url_canonicalizes_host_without_relaxing_origin():
    assert public_receiver_url("http://NA5B.com:8901/")["url"]=="http://na5b.com:8901/"
    assert not public_receiver_url("http://NA5B.com:8901/")["embedded_candidate"]
    assert public_receiver_url("https://RADIO.example.org/rx")["url"]=="https://radio.example.org/rx"
    with pytest.raises(ValueError):
        public_receiver_url("https://admin:secret@RADIO.example.org/")


def test_directory_search_keeps_all_valid_returned_choices_including_browser_only(panel):
    import json
    content=json.dumps({"receivers":[
        {"url":f"https://receiver{i}.example.org/","name":f"Receiver {i}"}
        for i in range(75)
    ]+[{"url":"http://browser.example.org:8073/","name":"Browser only"}]}).encode()
    panel.sdr_directory_cache["kiwisdr"]=parse_directory("kiwisdr",content)
    panel.ham_selector.setCurrentIndex(1)
    assert panel.receiver_picker.count()==77
    assert panel.receiver_picker.isEditable()
    panel.receiver_picker.setCurrentIndex(76)
    assert not panel.receiver_connect.isEnabled()
    assert panel.receiver_external.isEnabled()
    assert not panel.receiver_browser_quick.isHidden()
    assert "browser-only" in panel.directory_summary.text()
    assert not panel.receiver_connected
