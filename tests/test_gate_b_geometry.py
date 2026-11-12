import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.ui import MainWindow, geometry_has_useful_screen_overlap, recovered_window_rect


def test_geometry_overlap_accepts_usefully_visible_saved_frame():
    screens=[QRect(0,0,1920,1080),QRect(1920,0,2560,1440)]
    assert geometry_has_useful_screen_overlap(QRect(100,100,1200,800),screens)
    assert geometry_has_useful_screen_overlap(QRect(2000,120,1200,800),screens)


def test_geometry_overlap_rejects_fully_offscreen_and_tiny_sliver():
    screens=[QRect(0,0,1920,1080)]
    assert not geometry_has_useful_screen_overlap(QRect(5000,5000,1200,800),screens)
    assert not geometry_has_useful_screen_overlap(QRect(1880,100,1200,800),screens)
    assert geometry_has_useful_screen_overlap(QRect(1800,100,1200,800),screens)


def test_recovered_window_rect_centers_and_fits_oversized_geometry():
    available=QRect(100,50,1600,900)
    recovered=recovered_window_rect(QRect(9000,9000,3000,2000),available,QSize(960,640))
    assert recovered==QRect(100,50,1600,900)
    normal=recovered_window_rect(QRect(9000,9000,1100,700),available,QSize(960,640))
    assert normal.width()==1100 and normal.height()==700
    assert available.contains(normal)


def test_restore_guard_moves_unreachable_window_to_current_screen(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=MainWindow(controller)
    try:
        window.setGeometry(50000,50000,1100,700)
        assert window._ensure_window_on_screen()
        screens=[screen.availableGeometry() for screen in QApplication.screens()]
        assert geometry_has_useful_screen_overlap(window.frameGeometry(),screens)
    finally:
        window._force_close=True
        window.close()
        controller.close()
