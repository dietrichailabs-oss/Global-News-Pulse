"""Physical R20 feedback: visible tuner, discoverable durable presets, honest directory."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QUrl, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from global_pulse.core import Store
from global_pulse.internet_radio import RadioPanel, _owner_legacy_websdr, _receiver_origin_matches
from global_pulse.sdr_directory import (
    public_receiver_url, parse_directory, curated_websdr_receivers,
    curated_receiver_for_url, CURATED_WEBDR_HTTP_ORIGINS,
)
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
    controls=(panel.ham_frequency_display,panel.ham_back,panel.ham_step,panel.ham_band,
                    panel.ham_forward,panel.frequency,panel.tune_button,
                    panel.receiver_list,panel.receiver_search,panel.receiver_connect,panel.receiver_off)
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
                    panel.ham_frequency_detail,panel.ham_back,panel.ham_step,panel.ham_band,panel.ham_forward,panel.frequency,
                    panel.tune_button,panel.receiver_list,panel.receiver_search,panel.receiver_connect,
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
    assert "browser-only" in panel.directory_summary.text().lower()
    assert not panel.receiver_connected


def _select_curated(panel, identifier):
    index=next(i for i in range(panel.receiver_picker.count())
               if (panel.receiver_picker.itemData(i) or {}).get("id")==identifier)
    panel.receiver_picker.setCurrentIndex(index)
    return panel.receiver_picker.currentData()


def test_visible_receiver_names_load_without_network_or_popup(app,monkeypatch):
    from PySide6.QtNetwork import QNetworkAccessManager
    network=[]
    loads=[]
    monkeypatch.setattr(QNetworkAccessManager,"get",lambda *args:network.append(args))
    monkeypatch.setattr(RadioPanel,"_load_receiver_url",lambda *args,**kwargs:loads.append(args))
    widget=RadioPanel(confirm=lambda:False)
    try:
        widget.setStyleSheet(STYLE)
        widget.radio_tabs.setCurrentIndex(1)
        widget.resize(600,480)
        widget.show()
        app.processEvents()
        view=widget.receiver_list
        assert view.isVisible() and widget.receiver_search.isVisible()
        assert widget.receiver_picker.isHidden(),"The empty-looking combo is no longer the primary selector"
        assert view.isRowHidden(0),"Never display the placeholder instead of names"
        assert view.model().rowCount()==len(curated_websdr_receivers())+1
        assert view.model().index(1,0).data().startswith("NA5B")
        assert view.model().index(2,0).data()=="University of Twente"
        assert view.model().index(2,1).data()=="0.000–29.160 MHz"
        assert view.visualRect(view.model().index(1,0)).intersects(view.viewport().rect())
        assert view.visualRect(view.model().index(2,0)).intersects(view.viewport().rect())
        assert not widget.receiver_connect.isEnabled() and not widget.receiver_connected
        assert network==[] and loads==[]
        assert view.mapTo(widget,QPoint(0,0)).y()>widget.ham_selector.mapTo(widget,QPoint(0,0)).y()
    finally:
        widget.shutdown();widget.close();widget.deleteLater();app.processEvents()


def test_visible_row_click_selects_and_connect_button_owns_request(panel,app,monkeypatch):
    loads=[]
    monkeypatch.setattr(panel,"_load_receiver_url",lambda url,host,**kwargs:loads.append((url,host,kwargs)) or True)
    panel.radio_tabs.setCurrentIndex(1)
    panel.resize(600,480);panel.show();app.processEvents()
    model=panel.receiver_list.model()
    row=next(i for i in range(1,model.rowCount())
             if (model.index(i,0).data(Qt.ItemDataRole.UserRole) or {}).get("id")=="georgia")
    index=model.index(row,0)
    panel.receiver_list.scrollTo(index);app.processEvents()
    QTest.mouseClick(panel.receiver_list.viewport(),Qt.MouseButton.LeftButton,
                     pos=panel.receiver_list.visualRect(index).center())
    assert panel.receiver_picker.currentIndex()==row
    assert panel.receiver_list.selectionModel().isRowSelected(row)
    assert panel.receiver_url.text()=="http://sdrgeorgia.sytes.net:8902/"
    assert panel.frequency.text()=="26976"
    assert panel.receiver_connect.isEnabled() and not panel.receiver_connected
    assert loads==[],"A row click selects, it must not auto-connect"
    panel.receiver_connect.click()
    assert loads==[("http://sdrgeorgia.sytes.net:8902/?tune=26976usb",
                    "sdrgeorgia.sytes.net",{"require_consent":True})]


def test_visible_receiver_filter_and_provider_return_keep_truthful_selection(panel,monkeypatch):
    loads=[]
    monkeypatch.setattr(panel,"_load_receiver_url",lambda *args,**kwargs:loads.append(args) or True)
    _select_curated(panel,"twente")
    panel.receiver_search.setText("Enschede")
    visible=[i for i in range(1,panel.receiver_picker.count()) if not panel.receiver_list.isRowHidden(i)]
    assert len(visible)==1
    assert panel.receiver_picker.itemData(visible[0])["id"]=="twente"
    assert panel.receiver_connect.isEnabled()
    panel.receiver_search.setText("No such receiver 93b1")
    assert "No matching receivers" in panel.directory_summary.text()
    assert all(panel.receiver_list.isRowHidden(i) for i in range(panel.receiver_picker.count()))
    assert not panel.receiver_connect.isEnabled()
    panel.receiver_search.clear()
    assert not panel.receiver_list.isRowHidden(1)
    panel.ham_selector.setCurrentIndex(1)
    assert panel.receiver_picker.count()==1
    assert "No receivers loaded" in panel.directory_summary.text()
    assert not panel.receiver_connect.isEnabled() and panel.receiver_url.text()==""
    panel.ham_selector.setCurrentIndex(0)
    assert panel.receiver_picker.currentData()["id"]=="twente"
    assert panel.receiver_url.text()=="http://websdr.ewi.utwente.nl:8901/"
    assert panel.receiver_connect.isEnabled()
    assert panel.receiver_list.selectionModel().isRowSelected(panel.receiver_picker.currentIndex())
    assert loads==[] and not panel.receiver_connected


def test_reviewed_high_windows_do_not_expand_generic_receiver_or_scan_step_limits(panel,monkeypatch):
    for raw in ("500001","1296000","2321000","nan","inf","-1"):
        with pytest.raises(ValueError):
            RadioPanel._frequency_value(raw)
    loads=[]
    monkeypatch.setattr(panel,"_load_receiver_url",lambda *args,**kwargs:loads.append(args) or True)
    _select_curated(panel,"goonhilly")
    assert panel._choose_receiver_band(2)
    assert panel.frequency.text()=="1296000"
    assert panel.ham_frequency_display.text().startswith("1296.000 MHz")
    assert not loads and not panel.receiver_connected
    assert panel.tune_receiver(1298000)
    assert loads[-1][0].startswith("https://vhf-goonhilly.batc.org.uk/?tune=1298000usb")
    count=len(loads)
    assert not panel.step_receiver(1),"Cannot cross a reviewed upper edge"
    for frequency in (500001,1000000,1295999,1298001,2319999,2321001,float("nan"),float("inf")):
        assert not panel.tune_receiver(frequency)
    assert len(loads)==count
    assert panel._choose_receiver_band(3)
    assert panel.frequency.text()=="2320000"
    panel.scan_start.setText("2320000");panel.scan_end_edit.setText("2321000")
    panel.scan_step_edit.setText("100");panel.scan_dwell.setText("3")
    assert panel.start_scan()
    panel.stop_scan()
    panel.scan_step_edit.setText("600000")
    assert not panel.start_scan(),"The generic scan-step contract remains capped"
    panel.receiver_url.setText("https://unreviewed.example.org/")
    panel._selected_receiver_bands({"ranges_khz":((0,3000000),)})
    with pytest.raises(ValueError):
        panel._tuned_receiver_url(1296000)
    panel.receiver_url.setText("https://prefix.vhf-goonhilly.batc.org.uk/")
    with pytest.raises(ValueError):
        panel._tuned_receiver_url(1296000)
    panel.receiver_url.setText("https://vhf-goonhilly.batc.org.uk:443/")
    assert panel._tuned_receiver_url(2321000)[0].endswith("?tune=2321000usb")
    panel.receiver_type.setCurrentIndex(panel.receiver_type.findData("kiwi"))
    with pytest.raises(ValueError):
        panel._tuned_receiver_url(2321000)


def test_curated_receiver_facts_are_individual_links_not_a_central_feed_copy():
    rows={row["id"]:row for row in curated_websdr_receivers()}
    assert set(rows)=={"na5b","twente","georgia","utah1","utah2","utah4","utah5",
                      "maasbree_low","maasbree_high","maasbree_2m","kfs1","kfs2",
                      "g0xbu1","g0xbu2","df0hte","goonhilly","pardinho","oa6dxv"}
    assert rows["twente"]["url"]=="http://websdr.ewi.utwente.nl:8901/"
    assert rows["twente"]["name"]=="University of Twente"
    assert rows["twente"]["ranges_khz"]==((0.0,29160.0),)
    assert "supplied by owner" in rows["twente"]["provenance"]
    assert rows["georgia"]["url"]=="http://sdrgeorgia.sytes.net:8902/"
    assert rows["georgia"]["ranges_khz"]==((26976.0,29024.0),)
    assert rows["georgia"]["documentation"]=="https://narg.ge/websdr-tbilisi/"
    assert rows["utah1"]["url"]=="http://websdr1.sdrutah.org:8901/index1a.html"
    assert rows["utah2"]["url"]=="http://websdr2.sdrutah.org:8902/index1a.html"
    assert rows["utah4"]["url"]=="http://websdr4.sdrutah.org:8904/"
    assert rows["utah5"]["url"]=="http://websdr5.sdrutah.org:8905/"
    assert rows["na5b"]["ranges_khz"]==(),"Do not invent numeric bounds from band names"
    for row in rows.values():
        assert row["name"] and row["location"] and row["provenance"]
        assert row["documentation"] and row["provider"]=="websdr"
        assert "availability unverified" in row["reason"]
        assert row["embedded_candidate"]==row["url"].startswith("https://"),"Curating HTTP is not blanket HTTPS admission"
        for start,end in row["ranges_khz"]:
            assert 0<=start<end<=(2321000 if row["id"]=="goonhilly" else 500000)
    # Source table's internally inconsistent 20m end is retained as printed,
    # not silently 'corrected' from a center/bandwidth calculation.
    assert (13766.0,14354.0) in rows["utah2"]["ranges_khz"]
    assert "inconsistent" in rows["utah2"]["provenance"]


def test_all_curated_receivers_are_offline_searchable_with_ranges_and_no_autoconnect(panel,monkeypatch):
    requested=[]
    monkeypatch.setattr(panel.sdr_network,"get",lambda request:requested.append(request))
    assert panel.receiver_picker.count()==len(curated_websdr_receivers())+1
    for source in curated_websdr_receivers():
        item=_select_curated(panel,source["id"])
        text=panel.receiver_picker.currentText()
        assert text.startswith(source["name"])
        assert source["url"] in panel.receiver_picker.toolTip()
        assert panel.receiver_picker.lineEdit().cursorPosition()==0
        assert item["ranges_khz"]==source["ranges_khz"]
        assert panel.receiver_url.text()==source["url"]
        assert panel.receiver_connect.isEnabled()
        assert not panel.receiver_connected and panel.sdr_state=="OFF"
        assert panel.ham_band.isEnabled()==bool(source["ranges_khz"])
        if source["ranges_khz"]:
            assert "Listed coverage" in panel.ham_bands.text()
            assert source["documentation"] in panel.ham_bands.text()
            current=float(panel.frequency.text())
            assert any(low<=current<=high for low,high in source["ranges_khz"])
            if len(source["ranges_khz"])>1:
                assert f"{len(source['ranges_khz'])} ranges" in panel.receiver_picker.model().index(panel.receiver_picker.currentIndex(),1).data()
        else:
            coverage=panel.receiver_picker.model().index(panel.receiver_picker.currentIndex(),1).data()
            if source["bands"]:
                assert all(band in coverage for band in source["bands"])
            else:
                assert "Range not listed" in coverage
    assert not panel.refresh_receiver_directory()
    assert requested==[]


@pytest.mark.parametrize("larger_font",[False,True])
def test_curated_names_ranges_and_core_controls_fit_small_window(panel,app,larger_font):
    style=STYLE.replace("font-size: 12px;","font-size: 13px;") if larger_font else STYLE
    panel.setStyleSheet(style)
    panel.radio_tabs.setCurrentIndex(1)
    panel.resize(600,480)
    panel.show()
    panel.ham_details_toggle.setChecked(True)
    panel.advanced_scan.setChecked(True)
    for source in curated_websdr_receivers():
        _select_curated(panel,source["id"])
        for _ in range(3):
            app.processEvents()
        assert panel.width()<=600 and panel.height()<=480,source["id"]
        assert panel.minimumSizeHint().height()<=470
        assert panel.ham_details_scroll.viewport().height()>=24
        for control in (panel.ham_receiver_name,panel.ham_frequency_display,
                        panel.ham_back,panel.ham_step,panel.ham_band,panel.ham_forward,
                        panel.frequency,panel.tune_button,panel.receiver_list,panel.receiver_search,
                        panel.receiver_connect,panel.receiver_off):
            assert control.isVisible(),source["id"]
            surface=panel.radio_tabs.widget(1)
            assert surface.rect().contains(QRect(control.mapTo(surface,QPoint(0,0)),control.size()))


@pytest.mark.parametrize("identifier",[row["id"] for row in curated_websdr_receivers()
                                       if row["url"].startswith("http://")])
def test_every_curated_http_origin_requires_specific_consent_before_a_request(panel,monkeypatch,identifier):
    source=_select_curated(panel,identifier)
    attempted=[]
    prompts=[]
    monkeypatch.setattr(panel,"_ensure_receiver_view",lambda host:attempted.append(host))
    def refuse(*args,**kwargs):
        prompts.append(args[2])
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox,"question",refuse)
    assert not panel.connect_receiver()
    assert len(prompts)==1
    assert source["host"] in prompts[0]
    assert "unencrypted HTTP" in prompts[0] and "manually" in prompts[0]
    assert not attempted and not panel.receiver_connected


@pytest.mark.parametrize("host,port",sorted(CURATED_WEBDR_HTTP_ORIGINS))
def test_curated_http_admission_never_admits_another_host_port_scheme_or_kind(host,port):
    exact=f"http://{host}:{port}/"
    assert _owner_legacy_websdr(public_receiver_url(exact),"websdr")
    assert not _owner_legacy_websdr(public_receiver_url(exact),"kiwi")
    for url in (f"http://{host}/",f"http://{host}:{port+10}/",
                f"https://{host}:{port}/",f"http://prefix.{host}:{port}/"):
        assert not _owner_legacy_websdr(public_receiver_url(url),"websdr")
    assert _receiver_origin_matches(QUrl(exact),host,"http","ws",port,main=True)
    assert not _receiver_origin_matches(QUrl(f"http://{host}/"),host,"http","ws",port)
    assert not _receiver_origin_matches(QUrl(f"ws://{host}:{port}/"),host,"http","ws",port,main=True)
    assert not _receiver_origin_matches(QUrl(f"http://other.example.org:{port}/"),host,"http","ws",port)


def test_georgia_tuning_and_steps_stay_inside_its_listed_window(panel,monkeypatch):
    _select_curated(panel,"georgia")
    assert panel.frequency.text()=="26976"
    assert panel.ham_band.currentText()=="26.976–29.024 MHz"
    requested=[]
    monkeypatch.setattr(panel,"_load_receiver_url",lambda url,host,**kwargs:requested.append((url,host)) or True)
    assert panel.tune_receiver(29024)
    assert requested[-1]==("http://sdrgeorgia.sytes.net:8902/?tune=29024usb","sdrgeorgia.sytes.net")
    count=len(requested)
    assert not panel.step_receiver(1)
    assert not panel.tune_receiver(7100)
    assert len(requested)==count and panel.frequency.text()=="29024"
    assert "Outside this receiver's listed coverage" in panel.ham_note.text()
    assert panel.step_receiver(-1)
    assert panel.frequency.text()=="29019"
    assert len(requested)==count+1


def test_range_selection_is_local_and_scan_cannot_cross_receiver_gaps(panel,monkeypatch):
    _select_curated(panel,"utah1")
    requested=[]
    monkeypatch.setattr(panel,"_load_receiver_url",lambda *args,**kwargs:requested.append(args) or True)
    panel.ham_band.setCurrentIndex(4)
    assert panel._choose_receiver_band(4)
    assert panel.frequency.text()=="3366"
    assert panel.scan_start.text()=="3366" and panel.scan_end_edit.text()=="4134"
    assert requested==[] and not panel.receiver_connected
    panel.scan_start.setText("125")
    panel.scan_end_edit.setText("2564")
    assert not panel.start_scan()
    assert "one listed receiver range" in panel.ham_note.text()
    assert requested==[] and not panel.scan_timer.isActive()
    assert not panel.tune_receiver(3000),"Unlisted gaps cannot be tuned as supported coverage"
    assert requested==[]


def test_manual_curated_url_keeps_ranges_but_remote_metadata_cannot_change_them(panel):
    _select_curated(panel,"twente")
    panel.receiver_url.setText("http://websdr.ewi.utwente.nl:8901/?tune=123am")
    assert panel._known_receiver_ranges()==((0.0,29160.0),)
    panel._selected_receiver_bands({"ranges_khz":((0,500000),),"bands":["Everything"]})
    assert panel.ham_band.count()==1 and panel.ham_band.currentText()=="0.000–29.160 MHz"
    with pytest.raises(ValueError,match="listed coverage"):
        panel._tuned_receiver_url(40000)
    other=curated_receiver_for_url("http://sdrgeorgia.sytes.net:8902/")
    other["ranges_khz"]=((0,500000),)
    assert curated_receiver_for_url(other["url"])["ranges_khz"]==((26976.0,29024.0),)


@pytest.mark.parametrize("old_state",["ON","CONNECTING"])
def test_switching_curated_receiver_stops_previous_session_without_autoconnect(panel,monkeypatch,old_state):
    _select_curated(panel,"twente")
    actions=[]
    class OldView:
        def stop(self): actions.append("stopped")
        def setUrl(self,url): actions.append(url.toString())
        def hide(self): actions.append("hidden")
        def deleteLater(self): actions.append("destroyed")
    panel.receiver_view=OldView()
    panel.receiver_connected=True
    panel.receiver_origin=("http",8901,"websdr.ewi.utwente.nl")
    panel._sdr_state_change(old_state)
    panel._pending_tune=("http://websdr.ewi.utwente.nl:8901/?tune=7200usb","websdr.ewi.utwente.nl")
    panel.sdr_load_watch.start(20000)
    requested=[]
    monkeypatch.setattr(panel,"_load_receiver_url",lambda *args,**kwargs:requested.append(args) or True)
    _select_curated(panel,"georgia")
    assert not panel.receiver_connected and panel.sdr_state=="OFF"
    assert "OFF" in panel.sdr_status.text()
    assert panel._pending_tune is None and not panel.sdr_load_watch.isActive()
    assert panel.receiver_view is None
    assert actions==["stopped","about:blank","hidden","destroyed"]
    assert requested==[] and panel.frequency.text()=="26976"


def test_range_selector_tracks_tuning_without_losing_explicit_overlap_choice(panel,monkeypatch):
    _select_curated(panel,"utah2")
    requested=[]
    monkeypatch.setattr(panel,"_load_receiver_url",lambda *args,**kwargs:requested.append(args) or True)
    panel.frequency.setText("28584")
    panel.ham_band.setCurrentIndex(5)  # 10m lower window ends here.
    assert panel.step_receiver(1)
    assert panel.frequency.text()=="28589" and panel.ham_band.currentIndex()==6
    assert len(requested)==1
    panel.frequency.setText("28240")
    assert panel.ham_band.currentIndex()==6,"Keep current valid overlapping window"
    panel.ham_band.setCurrentIndex(5)
    panel.frequency.setText("28245")
    assert panel.ham_band.currentIndex()==5,"Keep another explicitly chosen valid overlap"
    panel.frequency.setText("30000")
    assert panel.ham_band.currentIndex()==-1,"Out-of-range request must not show a valid selected window"
    assert len(requested)==1,"Editing a requested frequency must not connect"
