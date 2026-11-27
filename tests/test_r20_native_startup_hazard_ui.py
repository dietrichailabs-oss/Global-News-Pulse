"""Owner-visible startup, window chrome and persistent hazard selection."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import sys

from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from global_pulse.__main__ import show_initializing,prepare_initial_dashboard
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow

def test_startup_never_traverses_visible_unmasked_tabs(tmp_path):
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    splash=show_initializing(app)
    w=None
    try:
        w=MainWindow(ctl)
        changes=[]
        w.pages.currentChanged.connect(lambda index:changes.append(
            (index,w.isVisible(),w.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen),
             w.windowOpacity())))
        assert prepare_initial_dashboard(app,splash,w,ctl)
        assert changes
        assert all(not visible or (masked and opacity==0.0)
                   for _,visible,masked,opacity in changes),changes
        assert w.pages.currentIndex()==0
        assert w.isVisible() and not w.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        assert w.windowOpacity()==1.0
        assert w._initial_painted_pages==set(range(7))
        splash.finish(w)
        app.processEvents()
        assert w.world_map._projected_view_key==(
            w.world_map.width(),w.world_map.height(),w.world_map.zoom,
            w.world_map.pan_x,w.world_map.pan_y)
        if sys.platform=="win32":
            assert not w.windowFlags() & Qt.WindowType.FramelessWindowHint
            assert w.titlebar.maximize_button.isHidden()
            assert "nativeEvent" not in MainWindow.__dict__
        w.showNormal()
        w.resize(1100,760)
        app.processEvents()
        assert not w.isMaximized() and not w.isFullScreen()
        assert w.category.width()>=w.category.minimumWidth()>=135
        assert w.region.width()>=w.region.minimumWidth()>=125
        state=w.windowState()
        w.open_page(2);w.open_page(0)
        app.processEvents()
        assert w.windowState()==state
    finally:
        if w is not None:
            w._force_close=True
            w.media.shutdown()
            w.close()
            w.deleteLater()
        ctl.close()
        splash.close()
        splash.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()

def test_hazard_rows_have_persistent_checked_highlight_and_sync(tmp_path):
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    w=MainWindow(ctl)
    try:
        w.show()
        w.hazard_menu.popup(w.hazard_button.mapToGlobal(w.hazard_button.rect().bottomLeft()))
        app.processEvents()
        action=w.hazard_actions["earthquake"]
        other=w.hazard_actions["cyclone"]
        assert action.control.isVisible() and action.control.isChecked()
        assert action.control.text().startswith("✓")
        assert "QToolButton:checked:enabled" in action.control.styleSheet()
        QTest.mouseClick(action.control,Qt.MouseButton.LeftButton)
        assert not action.isChecked() and not action.control.isChecked()
        assert not action.control.text().startswith("✓")
        assert other.control.isChecked()
        assert "earthquake" in w.world_map.disabled_hazards()
        assert w.hazard_menu.isVisible()
        QTest.mouseClick(action.control,Qt.MouseButton.LeftButton)
        assert action.isChecked() and action.control.isChecked()
        assert action.control.text().startswith("✓")
        QTest.mouseClick(w.hazard_master.control,Qt.MouseButton.LeftButton)
        assert not action.control.isEnabled()
        assert not action.control.text().startswith("✓")
        QTest.mouseClick(w.hazard_master.control,Qt.MouseButton.LeftButton)
        assert action.control.isEnabled() and action.control.isChecked()
        w.hazard_menu.hide()
    finally:
        w._force_close=True
        w.media.shutdown()
        w.close()
        w.deleteLater()
        ctl.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
