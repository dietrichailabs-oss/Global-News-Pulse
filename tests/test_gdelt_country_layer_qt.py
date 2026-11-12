"""Engineering real Qt map/record controls, actual retained SQLite and importer."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import datetime,timedelta,timezone
import socket
import sys
import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.gdelt_batches import GdeltBatchCache
from global_pulse.gdelt_map_data import empty
from test_gdelt_batch_cache import event_row,payload,batch_from_archive

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def desktop(tmp_path,app,monkeypatch):
    def denied(*a,**k):raise AssertionError('No provider request from map display')
    monkeypatch.setattr(socket,'getaddrinfo',denied);monkeypatch.setattr(socket.socket,'connect',denied)
    errors=[];monkeypatch.setattr(sys,'excepthook',lambda *a:errors.append(a))
    c=Controller(tmp_path)
    now=datetime.now(timezone.utc);batchtime=now-timedelta(hours=1)
    batchtime=batchtime.replace(minute=(batchtime.minute//15)*15,second=0,microsecond=0)
    stamp=batchtime.strftime('%Y%m%d%H%M%S')
    rows=[event_row('1001',country='UP',day=batchtime.strftime('%Y%m%d'),date_added=stamp),
          event_row('1002',country='IR',day=batchtime.strftime('%Y%m%d'),date_added=stamp)]
    data=payload(rows,stamp=stamp)
    with GdeltBatchCache(c.store.path) as cache:
        cache.import_export(batch_from_archive(data,stamp=stamp),data,now=now.isoformat())
    w=MainWindow(c);w.show();app.processEvents()
    yield w,c,errors
    if w.gdelt_panel.dialog is not None:w.gdelt_panel.dialog.close()
    w._force_close=True;w.close();c.close();app.processEvents()
    assert not errors


def test_cached_rows_reach_actual_map_without_verified_events_or_alerts(desktop,app,monkeypatch):
    w,c,errors=desktop
    assert w.gdelt_panel.mapped_count==2
    assert w.world_map.gdelt_layer is w.gdelt_panel
    assert not w.world_map.events and not w.world_map.country_activity
    assert c.events()==[] and c.store.stats()['reports']==0 and not c.monitoring
    alerts=[];media=[];c.native_alert.connect(lambda *a:alerts.append(a))
    monkeypatch.setattr(w.media,'set_event',lambda *a:media.append(a))
    c.gdelt_status_changed.emit();app.processEvents()
    assert not alerts and not media
    assert not w.world_map.grab().isNull()
    assert 'not verified crises' in w.gdelt_panel.country_text('Ukraine')


def test_source_link_requires_explicit_click_and_record_is_labeled(desktop,app,monkeypatch):
    w,c,errors=desktop
    opened=[];monkeypatch.setattr(c,'open_url',lambda url:opened.append(url))
    panel=w.gdelt_panel;panel.show_records();app.processEvents()
    assert not opened and panel.record_list.count()==2
    assert 'CAMEO' in panel.record_list.item(0).text() and 'Event date' in panel.record_list.item(0).text()
    panel.record_list.setCurrentRow(0);app.processEvents()
    assert not opened and panel.open_original.isEnabled()
    panel.open_original.click()
    assert opened==['https://example.org/story'] and not c.monitoring


def test_toggle_off_restores_no_layer_and_persists_without_collection(desktop,app):
    w,c,errors=desktop
    panel=w.gdelt_panel;panel.enabled.setChecked(False);app.processEvents()
    assert panel.mapped_count==0 and not panel.details.isEnabled()
    assert c.get_setting('gdelt_map_visible') is False and not c.monitoring
    panel.enabled.setChecked(True);app.processEvents()
    assert panel.mapped_count==2 and c.get_setting('gdelt_map_visible') is True


@pytest.mark.parametrize('filters',[{'query':'Ukraine'},{'category':'War'},{'region':'Europe'},{'before':'2026-01-01T00:00:00Z'}])
def test_news_only_or_historical_filters_explicitly_hide_coded_layer(desktop,filters):
    w,c,errors=desktop
    w.gdelt_panel.refresh(filters)
    assert w.gdelt_panel.mapped_count==0 and w.gdelt_panel.snapshot['state']=='filtered'
    assert 'hidden' in w.gdelt_panel.status.text()
    w.gdelt_panel.refresh({})
    assert w.gdelt_panel.mapped_count==2


def test_unavailable_read_clears_old_map_layer(desktop,monkeypatch):
    w,c,errors=desktop
    monkeypatch.setattr('global_pulse.gdelt_map_panel.read_archive',lambda *a,**k:empty('unavailable','Read unavailable'))
    w.gdelt_panel.refresh({})
    assert w.gdelt_panel.mapped_count==0 and not w.gdelt_panel.details.isEnabled()
    assert 'unavailable' in w.gdelt_panel.status.text()


def test_selected_country_filters_plain_record_dialog(desktop,app):
    w,c,errors=desktop
    w.world_map.select_country('Ukraine');w.gdelt_panel.refresh({});w.gdelt_panel.show_records();app.processEvents()
    assert w.gdelt_panel.record_country.currentData()=='Ukraine'
    assert w.gdelt_panel.record_list.count()==1
    assert 'Ukraine' in w.gdelt_panel.record_list.item(0).text()


def test_demo_layer_never_reads_live_data(tmp_path,app,monkeypatch):
    from global_pulse.gdelt_map_panel import GdeltMapPanel
    from global_pulse.map_widget import WorldMap
    c=Controller(tmp_path,demo=True);m=WorldMap();panel=GdeltMapPanel(c,m)
    def denied(*a,**k):raise AssertionError('Demo cannot inspect live GDELT archive')
    monkeypatch.setattr('global_pulse.gdelt_map_panel.read_archive',denied)
    try:
        panel.refresh({});assert panel.snapshot['state']=='demo' and panel.mapped_count==0
    finally:panel.timer.stop();panel.close();m.close();c.close()
