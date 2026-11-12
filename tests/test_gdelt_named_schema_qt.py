"""Named61-column source -> actual Store/importer -> real Qt map and source list."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import datetime,timedelta,timezone
import socket
import sys
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.gdelt_batches import GdeltBatchCache
from test_gdelt_named_schema import named_row,archive_bytes


def test_official_named_shape_reaches_actual_map_and_record_dialog(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    def denied(*a,**k):raise AssertionError('Named-schema desktop test cannot use network')
    monkeypatch.setattr(socket,'getaddrinfo',denied);monkeypatch.setattr(socket.socket,'connect',denied)
    errors=[];monkeypatch.setattr(sys,'excepthook',lambda *a:errors.append(a))
    c=Controller(tmp_path)
    now=datetime.now(timezone.utc);past=now-timedelta(hours=1)
    past=past.replace(minute=(past.minute//15)*15,second=0,microsecond=0)
    stamp=past.strftime('%Y%m%d%H%M%S')
    rows=[named_row('UP','Kyiv, Ukraine','171',stamp),named_row('IR','Tehran, Iran','172',stamp)]
    batch,data=archive_bytes(rows,stamp)
    with GdeltBatchCache(c.store.path) as cache:
        assert cache.import_export(batch,data,now=now.isoformat())['added']==2
    w=MainWindow(c);w.show();app.processEvents()
    opened=[];monkeypatch.setattr(c,'open_url',opened.append)
    try:
        assert w.gdelt_panel.mapped_count==2 and c.events()==[] and not c.monitoring
        assert w.world_map.grab().isNull() is False
        w.world_map.select_country('Ukraine');w.gdelt_panel.refresh({});w.gdelt_panel.show_records();app.processEvents()
        assert w.gdelt_panel.record_list.count()==1
        assert 'Kyiv, Ukraine' in w.gdelt_panel.record_list.item(0).text()
        assert not opened
        w.gdelt_panel.record_list.setCurrentRow(0);w.gdelt_panel.open_original.click()
        assert opened==['https://publisher.example.org/report/171']
        assert not errors
    finally:
        if w.gdelt_panel.dialog is not None:w.gdelt_panel.dialog.close()
        w._force_close=True;w.close();c.close();app.processEvents()
