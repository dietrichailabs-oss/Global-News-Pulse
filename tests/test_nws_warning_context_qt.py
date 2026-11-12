"""Actual Qt area layer and Controller signal checks; no physical desktop claim."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import socket
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QPixmap
from global_pulse.controller import Controller
from global_pulse.map_widget import WorldMap
from global_pulse.warning_context import project_warning_context
from test_nws_warning_context import NOW, stamp, derived_pending, update_record

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])
@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('No network in warning map tests')
    monkeypatch.setattr(socket,'getaddrinfo',denied);monkeypatch.setattr(socket.socket,'connect',denied)


def test_real_area_layer_draws_and_hits_labeled_pending_area(app):
    mapped=project_warning_context(derived_pending(),stamp(NOW))
    world=WorldMap();world.resize(900,450)
    try:
        world.set_events([],country_events=[mapped])
        visible=world.area_layer.visible()
        assert len(visible)==1 and visible[0][2]['context_only'] is True
        assert 'incomplete warning history' in world.coverage_summary()
        assert not world.country_activity
        found=world.area_layer.hit(world.point(-149.5,60.5))
        assert found and found[0]['id']==mapped['id'] and 'history incomplete' in found[1]['description']
        pixmap=QPixmap(900,450);painter=QPainter(pixmap)
        try:world.area_layer.paint(painter)
        finally:painter.end()
    finally:world.close()


def test_pending_events_cannot_render_unmarked_arbitrary_areas(app):
    event=project_warning_context(derived_pending(),stamp(NOW));event=copy.deepcopy(event)
    event['map_areas'][0].pop('context_only')
    world=WorldMap()
    try:
        world.set_events([],country_events=[event])
        assert world.area_layer.visible()==[]
    finally:world.close()


def test_real_controller_does_not_promote_context_into_native_alert(tmp_path,app):
    c=Controller(tmp_path);native=[];c.native_alert.connect(lambda *args:native.append(args));c.monitoring=True
    try:
        c._on_reports([update_record()])
        assert not native and not c.store.list_alerts()
        event=c.events()[0];assert event['status']=='pending'
        shown=c.store.list_events(map_evidence=True)
        assert len(shown)==1 and shown[0]['map_history_incomplete']
        assert c.event(event['id'])['status']=='pending'
    finally:c.close()
