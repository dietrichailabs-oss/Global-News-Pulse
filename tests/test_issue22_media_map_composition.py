"""Issue #22 composed desktop evidence: single media plus retained source/map path.
Offline only. Engineering regression, not independent QA or playback proof.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.map_widget import WorldMap
from global_pulse.single_media import MediaPanel
from global_pulse.internet_radio import RadioPanel


def _desktop(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = MainWindow(controller)
    return app, controller, window


def _close(app, controller, window):
    window.media.shutdown()
    window._force_close = True
    window.close()
    controller.close()
    window.deleteLater()
    app.processEvents()


def test_main_window_uses_single_tv_radio_and_real_world_map(tmp_path):
    app, controller, window = _desktop(tmp_path)
    try:
        assert isinstance(window.media, MediaPanel)
        assert isinstance(window.world_map, WorldMap)
        assert len(window.media.tiles) == 1
        assert window.media.tiles[0] is window.media.tv
        assert isinstance(window.media.radio, RadioPanel)
        assert [window.media.tabs.tabText(i) for i in range(3)] == ["TV", "Radio", "Cameras"]
        assert window.media.tv._builtins == []
        assert window.media.tv.tv_status.text() == "OFF"
        assert window.media.radio.status.text() == "OFF"
        assert window.media.radio._session is None
    finally:
        _close(app, controller, window)


def test_map_navigation_refresh_cannot_activate_off_radio(tmp_path):
    app, controller, window = _desktop(tmp_path)
    try:
        assert window.world_map.select_country("Ukraine")
        window.media.tabs.setCurrentIndex(1)
        window.media.radio.selector.setCurrentIndex(1)
        controller.data_changed.emit()
        app.processEvents()
        assert window.world_map.selected_country == "Ukraine"
        assert window.media.radio.status.text() == "OFF"
        assert window.media.radio._session is None
        assert not window.media.radio.power.isChecked()
        window.media.stop()
        assert window.media.radio.status.text() == "OFF"
    finally:
        _close(app, controller, window)

def test_startup_initializer_is_visible_until_real_desktop_is_ready(tmp_path):
    """A painted initialization notice precedes Store/UI loading, then closes.

    This checks the actual Qt display/lifecycle in offscreen mode, not physical
    Windows 11 responsiveness or whether a long Store migration can still stall.
    """
    from global_pulse.__main__ import show_initialization_splash

    app = QApplication.instance() or QApplication([])
    splash = show_initialization_splash(app)
    assert splash.isVisible()
    assert splash.accessibleName() == "Global Pulse initializing"
    assert "INITIALIZING GLOBAL PULSE" in splash.message()
    assert "local archive" in splash.message()

    controller = None
    window = None
    try:
        controller = Controller(tmp_path, demo=True)
        window = MainWindow(controller)
        assert splash.isVisible(), "Do not expose partially initialized controls"
        window.show()
        splash.finish(window)
        app.processEvents()
        assert not splash.isVisible()
        assert window.isVisible()
        assert isinstance(window.world_map, WorldMap)
    finally:
        splash.close()
        if window is not None:
            _close(app, controller, window)
        elif controller is not None:
            controller.close()
