"""GP-UI-002 actual Qt geometry and snapshot diagnostics; no live media/network."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from global_pulse.visual_diagnostics import capture_diagnostics


@pytest.fixture
def workspace(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = MainWindow(controller)
    # Test layout at exact requested sizes, independently of host screen limits.
    # Native frozen/installed smoke separately maps real Windows windows.
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    app.processEvents()
    yield app, window, controller
    window._force_close = True
    window.close()
    controller.close()


@pytest.mark.parametrize('size', [(1440, 940), (1280, 800), (960, 640)])
@pytest.mark.parametrize('selected', [False, True])
def test_status_cards_have_readable_viewports_without_forcing_window_growth(workspace, size, selected):
    app, window, controller = workspace
    if selected:
        controller.load_fixture(Path(__file__).parent / 'fixtures' / 'crisis.json')
        window.navigate_event(controller.events()[0]['id'])
    window.resize(*size)
    app.processEvents()
    app.processEvents()
    assert (window.width(), window.height()) == size
    assert window.lower_split.sizes()[2] / sum(window.lower_split.sizes()) < .25
    assert window.intel_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    for browser in (window.intel_browser, window.evidence_status_text, window.change_status_text):
        assert browser.viewport().height() >= 3 * browser.fontMetrics().lineSpacing()
        window.intel_scroll.ensureWidgetVisible(browser)
        app.processEvents()
        point = browser.mapTo(window.intel_scroll.viewport(), browser.rect().center())
        assert 0 <= point.y() <= window.intel_scroll.viewport().height()
    # A small display must scroll cards instead of collapsing their text to zero.
    if size == (960, 640):
        assert window.intel_scroll.verticalScrollBar().maximum() > 0


def test_tiny_splitter_drag_cannot_destroy_status_text_viewports(workspace):
    app, window, _ = workspace
    window.resize(960, 640)
    window.intel_stack.setSizes([1000, 1, 1])
    app.processEvents()
    app.processEvents()
    for browser in (window.evidence_status_text, window.change_status_text):
        assert browser.viewport().height() >= 3 * browser.fontMetrics().lineSpacing()


def test_visual_diagnostics_report_actual_backend_and_resolved_fonts(workspace):
    app, window, _ = workspace
    result = capture_diagnostics(app, window)
    assert result['platform_backend'] == app.platformName()
    assert result['available_font_family_count'] > 0
    assert result['fonts'] and result['ascii_font_coverage']
    assert all(font['valid'] and not font['missing_ascii_glyphs'] for font in result['fonts'])
    assert set(result['status_cards']) == {'intel_browser', 'evidence_status_text', 'change_status_text'}
    assert result['visual_acceptance'].startswith('NOT ESTABLISHED')
    assert result['native_notification_acceptance'] == 'NOT RUN'


def test_displayed_minimum_window_keeps_readable_cards(tmp_path):
    """A real shown source window at the supported minimum, without layout isolation.

    This covers the current backend only, not Snap or mixed-monitor acceptance.
    """
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = MainWindow(controller)
    try:
        window.resize(960, 640)
        window.show()
        app.processEvents()
        window.resize(960, 640)
        app.processEvents()
        assert not window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        assert window.isVisible()
        assert (window.width(), window.height()) == (960, 640)
        result = capture_diagnostics(app, window)
        assert result['ascii_font_coverage']
        for card in result['status_cards'].values():
            assert card['viewport_height'] >= 3 * card['line_spacing']
    finally:
        window._force_close = True
        window.close()
        controller.close()


def test_explicit_synthetic_selected_snapshot_renders_real_fixture(tmp_path):
    """Exercise the real CLI and isolated SQLite archive, not an image mock."""
    import json
    import sqlite3
    import subprocess
    import sys

    image = tmp_path / "selected-960x640.png"
    archive = tmp_path / "isolated-demo"
    fixture = Path(__file__).parent / "fixtures" / "crisis.json"
    command = [sys.executable, "-m", "global_pulse", "--demo", "--fixture", str(fixture),
               "--snapshot-first-fixture-event", "--snapshot-size", "960x640",
               "--data-dir", str(archive), "--no-start", "--skip-setup",
               "--snapshot", str(image)]
    finished = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert finished.returncode == 0, finished.stderr[-1500:]
    assert image.is_file() and image.read_bytes()[:8] == bytes([137,80,78,71,13,10,26,10])
    diagnostics = json.loads(image.with_suffix(".json").read_text(encoding="utf-8"))
    assert diagnostics["synthetic_fixture"] is True
    assert diagnostics["synthetic_selected_event"] is True
    assert diagnostics["synthetic_banner_visible"] is True
    assert diagnostics["requested_snapshot_size"] == [960, 640]
    assert diagnostics["window_size"] == [960, 640]
    assert diagnostics["ascii_font_coverage"]
    # Demo mode intentionally uses a separate synthetic.sqlite3 database.
    # Assert existence before opening: sqlite3.connect otherwise creates an
    # empty live-named database and the test fails with a misleading missing table.
    synthetic_db = archive / "synthetic.sqlite3"
    assert synthetic_db.is_file(), f"Missing isolated synthetic archive: {synthetic_db}"
    assert not (archive / "global-pulse.sqlite3").exists()
    with sqlite3.connect(synthetic_db) as db:
        assert db.execute("SELECT count(*) FROM reports").fetchone()[0] > 0
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] > 0


@pytest.mark.parametrize("unscoped", [
    ["--snapshot-first-fixture-event"],
    ["--snapshot-size", "960x640"],
])
def test_synthetic_snapshot_flags_reject_unscoped_use(unscoped):
    """No population/selection flags can activate in production mode."""
    import subprocess
    import sys
    finished = subprocess.run([sys.executable, "-m", "global_pulse", *unscoped],
                              capture_output=True, text=True, timeout=20)
    assert finished.returncode != 0
    assert "requires --demo, --fixture and --snapshot" in finished.stderr
