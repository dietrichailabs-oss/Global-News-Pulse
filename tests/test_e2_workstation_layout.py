"""Real Qt layout, controls and inert four-tile media integration; no live playback."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.media_widget import MediaPanel

@pytest.fixture
def workstation(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path, demo=True)
    window=MainWindow(controller)
    # Pure layout matrix, not window-manager/display-resolution acceptance.
    # Native Windows limits top-level sizes to the runner screen; keep the
    # exact large geometry assertions without modifying that desktop.
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1440,940);window.show();app.processEvents()
    yield app,window,controller
    window._force_close=True;window.close();controller.close()

def test_default_404020_composition_and_stacked_sidebar(workstation):
    app,w,c=workstation
    sizes=w.lower_split.sizes();total=sum(sizes)
    assert .37 < sizes[0]/total < .43
    assert .37 < sizes[1]/total < .43
    assert .17 < sizes[2]/total < .23
    assert w.intel_stack.count()==3
    assert len(w.media.tiles)==4
    assert w.media.grid.rowCount()==2 and w.media.grid.columnCount()==2
    assert w.map_overlay.isVisible() and len(w.layer_checks)>=5
    assert w.map_overlay.mapTo(w.world_map.parentWidget(),w.map_overlay.rect().topLeft()).x()<20

def test_persistent_layer_controls_and_compact_time_controls(workstation):
    app,w,c=workstation
    for check in w.layer_checks.values():check.setChecked(False)
    assert w.world_map.categories==set()
    w.map_period_buttons[3].click()
    assert w.time_range.currentIndex()==3
    assert sum(b.isChecked() for b in w.map_period_buttons)==1
    w.layer_button.click();assert not w.map_overlay.isVisible()
    w.save_layout()
    assert not c.get_setting("map_layers_visible")
    w._reset_layout();app.processEvents()
    assert w.world_map.categories is None and w.map_overlay.isVisible()
    assert all(check.isChecked() for check in w.layer_checks.values())

def test_four_tiles_do_not_autoconnect_and_stop_on_replacement(workstation,monkeypatch):
    app,w,c=workstation
    items=[dict(url=f"https://www.youtube.com/watch?v=ABCDEF{i:05d}",title=f"Fixture {i}",provider="Synthetic fixture",type="youtube") for i in range(4)]
    w.media.set_catalog([]);w.media.set_event({"media":items})
    for tile in w.media.tiles:
        assert tile.view is None and tile.profile is None
        assert tile.selector.count()==1
    # Unchanged refresh must not interrupt an explicitly chosen player.
    stops=[]
    for i,tile in enumerate(w.media.tiles):
        monkeypatch.setattr(tile,"stop",lambda index=i:stops.append(index))
    w.media.set_event({"media":items})
    assert stops==[]
    w.media.set_event(None)
    assert set(stops)==set(range(4))

def test_category_controls_keep_original_links_and_honest_empty_states(workstation):
    app,w,c=workstation
    w.media.set_catalog([
        {"url":"https://camera.example.org/","title":"Public camera directory","type":"webcam"},
        {"url":"https://radio.example.org/","title":"Public radio","type":"radio"},
    ])
    w.media._filter("Radio")
    assert w.media.tiles[0]._current()["url"]=="https://radio.example.org/"
    assert all(not t.view for t in w.media.tiles)
    assert all(not t._current() for t in w.media.tiles[1:])
    assert "not connected" in w.media.tiles[0].display.text().lower()

def test_media_watch_declined_never_constructs_player(workstation,monkeypatch):
    app,w,c=workstation
    tile=w.media.tiles[0];tile.media=[{"url":"https://www.youtube.com/watch?v=abcdefghijk","title":"Synthetic player test"}];tile.catalog=[];tile._populate()
    calls=[]
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k:QMessageBox.StandardButton.No)
    monkeypatch.setattr(tile,"_ensure_player",lambda:calls.append("connect"))
    tile.watch()
    assert calls==[] and tile.view is None

def test_sidebar_values_come_from_selected_event(workstation):
    app,w,c=workstation
    c.load_fixture(Path(__file__).parent/"fixtures"/"crisis.json")
    event=c.events()[0];w.navigate_event(event["id"]);app.processEvents()
    assert str(event["report_count"])+" source records" in w.evidence_status_text.toPlainText()
    assert "revision "+str(event["revision"]) in w.change_status_text.toPlainText()
    assert "FICTIONAL TRAINING EVENT" in w.intel_browser.toPlainText()
    assert "probability" not in w.evidence_status_text.toPlainText().lower()

@pytest.mark.parametrize("width,height",[(960,640),(1280,800),(1920,1080)])
def test_map_and_panels_remain_accessible_at_window_sizes(workstation,width,height):
    app,w,c=workstation
    w.resize(width,height);app.processEvents()
    assert w.width()==width and w.height()==height
    assert w.world_map.height()>=100
    assert w.intel_stack.sizes()[0]>30
    assert w.media_scroll.widgetResizable()
    assert all(tile.selector.isEnabled() for tile in w.media.tiles)
