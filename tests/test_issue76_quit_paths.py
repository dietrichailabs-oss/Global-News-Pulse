"""Issue76: all desktop exits must run the same ordered Qt quit signal.

This verifies the true entrypoint's three alternative exit paths and exercises
the actual Qt signal dispatch. Offline; no live media, provider or OS tray claim.
"""
from __future__ import annotations

import ast
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMenu
from global_pulse.controller import Controller

SOURCE = Path(__file__).resolve().parents[1] / "global_pulse" / "__main__.py"


def _functions():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    main = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    nested = {
        n.name: n for n in ast.walk(main)
        if isinstance(n, ast.FunctionDef)
    }
    return main, nested


def _calls(node, expression):
    return [
        n for n in ast.walk(node) if isinstance(n, ast.Call)
        and ast.unparse(n.func) == expression
    ]


def test_close_window_without_tray_uses_ordered_quit_signal():
    _, funcs = _functions()
    close_window = funcs["close_window"]
    selection = next(
        n for n in close_window.body if isinstance(n, ast.If)
        and "close_to_tray" in ast.unparse(n.test)
    )
    assert len(selection.orelse) == 1
    assert isinstance(selection.orelse[0], ast.Expr)
    assert ast.unparse(selection.orelse[0].value) == "controller.quit()"
    assert not _calls(close_window, "shutdown")


def test_snapshot_and_native_app_finally_also_request_signal():
    main, funcs = _functions()
    snapshot = funcs["snapshot"]
    assert len(_calls(snapshot, "controller.quit")) == 1
    assert not _calls(snapshot, "shutdown")
    app_finally = next(
        n for n in main.body if isinstance(n, ast.Try)
        and any("app.exec()" in ast.unparse(x) for x in n.body)
    )
    guard = next(n for n in app_finally.finalbody if isinstance(n, ast.If))
    assert ast.unparse(guard.test) == "not shutting_down"
    assert len(guard.body) == 1
    assert ast.unparse(guard.body[0]) == "controller.quit()"
    assert not _calls(app_finally, "shutdown")


def test_real_entrypoint_registers_timer_menu_shutdown_in_order():
    main, _ = _functions()
    connections = [
        ast.unparse(n.value.args[0]) for n in main.body
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and ast.unparse(n.value.func) == "controller.quit_requested.connect"
    ]
    assert connections == ["tray_refresh_timer.stop", "menu.hide", "shutdown"]


def test_real_qt_quit_signal_stops_pending_tray_and_hides_menu(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    timer = QTimer()
    menu = QMenu()
    try:
        timer.start(60000)
        menu.show()
        app.processEvents()
        seen = []
        controller.quit_requested.connect(timer.stop)
        controller.quit_requested.connect(menu.hide)
        controller.quit_requested.connect(
            lambda: seen.append((timer.isActive(), menu.isVisible()))
        )
        assert timer.isActive()
        assert menu.isVisible()
        controller.quit()
        assert seen == [(False, False)]
    finally:
        timer.stop()
        menu.hide()
        controller.close()
        menu.close()
        menu.deleteLater()
        timer.deleteLater()
        app.processEvents()
