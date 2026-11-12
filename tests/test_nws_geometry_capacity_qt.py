"""Actual Qt map-area aggregate budget and painting with captured NWS boundary."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import time
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter,QPixmap
from global_pulse.map_widget import WorldMap
from global_pulse.map_area_layer import WarningAreaLayer
from global_pulse.map_evidence import wrapped_polygons
from test_nws_geometry_capacity import captured, circle

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def displayed(shape,identity):
    return {'id':str(identity),'status':'active','category':'Weather','severity':'unassessed',
      'reports':[],'map_areas':[{'geometry':shape,'description':'Captured official boundary, offline test','source_id':'nws'}]}


def test_actual_captured_shape_paints_with_unchanged_total_budget(app):
    world=WorldMap();world.resize(1000,600)
    assert WarningAreaLayer.MAX_VERTICES==100000 and WarningAreaLayer.MAX_AREAS==200
    try:
        shape=captured();start=time.perf_counter()
        world.set_events([],country_events=[displayed(shape,i) for i in range(20)])
        visible=world.area_layer.visible()
        assert len(visible)==9 and world.area_layer.omitted==11
        points=sum(len(r) for _p,_e,a in visible for poly in wrapped_polygons(a['geometry']) for r in poly)
        assert points==90846 and points<=100000
        pixmap=QPixmap(1000,600);painter=QPainter(pixmap)
        try:world.area_layer.paint(painter)
        finally:painter.end()
        elapsed=time.perf_counter()-start
        print('GP_QT_GEOMETRY_RESOURCE '+json.dumps({'areas_requested':20,'areas_renderable':len(visible),'vertices':points,'seconds':elapsed}),flush=True)
        assert elapsed<10
    finally:world.close()


def test_full_capacity_areas_cannot_overrun_global_render_budget(app):
    world=WorldMap()
    try:
        shape=circle(16384)
        world.set_events([],country_events=[displayed(shape,i) for i in range(8)])
        assert len(world.area_layer.visible())==6
        assert world.area_layer.omitted==2
        assert 6*16384<=100000<7*16384
    finally:world.close()
