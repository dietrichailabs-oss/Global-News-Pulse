from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QMenu, QMessageBox, QSplashScreen, QSystemTrayIcon, QVBoxLayout

from . import __version__, BUILD_ID
from .security import event_id, redact


def data_directory():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "DietrichAILabs" / "GlobalPulse"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "global-pulse"


def pulse_icon(state="active", size=64):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = size / 64
    painter.scale(scale, scale)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#12141b"))
    painter.drawRoundedRect(1, 1, 62, 62, 14, 14)
    painter.setPen(QPen(QColor("#936bf4"), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(9, 9, 46, 46)
    painter.drawEllipse(18, 18, 28, 28)
    painter.drawLine(32, 32, 49, 15)
    painter.drawLine(32, 9, 32, 14)
    painter.drawLine(9, 32, 14, 32)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor({"active": "#aa88ff", "paused": "#a3acba", "alerts": "#f1bd53", "error": "#fa6b6e"}.get(state, "#aa88ff")))
    painter.drawEllipse(27, 27, 10, 10)
    if state != "active":
        painter.drawEllipse(43, 43, 15, 15)
    painter.end()
    return QIcon(pixmap)


def onboarding(controller, parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Welcome to Global Pulse")
    dialog.setMinimumWidth(460)
    layout = QVBoxLayout(dialog)
    heading = QLabel("Choose what you want to follow")
    heading.setStyleSheet("font-size:22px; font-weight:600; color:#b49bff")
    layout.addWidget(heading)
    note = QLabel("Free public sources are preconfigured. Reports, watchlists and history stay on this computer. No account or API key is required.")
    note.setWordWrap(True)
    layout.addWidget(note)
    grid = QGridLayout()
    categories = sorted({s["category"] for s in controller.catalog if s.get("enabled")})
    checks = []
    for i, category in enumerate(categories):
        box = QCheckBox(category)
        box.setChecked(True)
        checks.append(box)
        grid.addWidget(box, i // 2, i % 2)
    layout.addLayout(grid)
    detail = QLabel("Source collection defaults to 10 minutes and respects each provider's limits. Closing the dashboard keeps monitoring in the tray when a tray is available. Exit Completely stops it.")
    detail.setWordWrap(True)
    layout.addWidget(detail)
    monitor = QCheckBox("Start monitoring public sources")
    monitor.setChecked(True)
    layout.addWidget(monitor)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        controller.set_setting("categories", [box.text() for box in checks if box.isChecked()])
        controller.set_setting("setup_complete", True)
        return monitor.isChecked()
    return False



class _StartupSplash(QSplashScreen):
    """Non-dismissible notice painted before opening heavy local source data."""

    def mousePressEvent(self, event):
        # Splash clicks during slow loading must not expose an unfinished UI.
        event.accept()


def show_initializing(app):
    background = QPixmap(560, 186)
    background.fill(QColor("#17161e"))
    painter = QPainter(background)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#9169d9"), 2))
    painter.drawRoundedRect(5, 5, 550, 176, 14, 14)
    painter.end()
    splash = _StartupSplash(background, Qt.WindowType.WindowStaysOnTopHint)
    splash.setAccessibleName("Global Pulse initializing")
    splash.showMessage(
        "INITIALIZING GLOBAL PULSE\n"
        "Preparing your local archive and source settings.\n"
        "The dashboard will open when its data is ready.",
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        QColor("#eee8f7")
    )
    splash.show()
    # Draw before Controller construction or SQLite/Qt resource setup.
    app.processEvents()
    return splash


def prepare_initial_dashboard(app, splash, window, controller):
    """Finish bounded LOCAL UI startup work before showing the dashboard.

    First load has already queried the local archive and painted the map
    while MainWindow was constructed. Cold headlines deliberately queue
    language identification after the first paint; drain that finite queue
    while the non-dismissable splash remains visible, rather than running
    500 Qt ticks against the newly interactive main window. Pre-populate
    all deferred local workspace tables now; no network/media is opened.
    Ongoing live collection is NOT a startup prerequisite.
    """
    splash.showMessage(
        "INITIALIZING GLOBAL PULSE\n"
        "Preparing local source tables and intelligence views...",
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        QColor("#eee8f7"),
    )
    app.processEvents()
    if hasattr(window, "prepare_initial_workspaces"):
        window.prepare_initial_workspaces()
    headlines = getattr(controller, "_headlines", None)
    if headlines is not None and not getattr(headlines, "closed", False):
        pending = getattr(headlines, "deferred", None)
        # MAX_DEFERRED is intentionally finite (512). No provider access,
        # model installation or article-body processing is permitted here.
        limit = int(getattr(headlines, "MAX_DEFERRED", 512)) + 8
        initial = len(pending) if pending is not None else 0
        for processed in range(limit):
            if not pending:
                break
            if processed % 24 == 0:
                splash.showMessage(
                    "INITIALIZING GLOBAL PULSE\n"
                    f"Preparing source headlines {processed}/{initial}...",
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    QColor("#eee8f7"),
                )
                app.processEvents()
            headlines._drain_deferred()
        if pending:
            # Fail closed: never show a dashboard marked ready if a changed
            # worker implementation breaks the finite startup invariant.
            raise RuntimeError("Initial local headline queue did not settle")
        headlines.deferred_timer.stop()
    app.processEvents()
    splash.showMessage(
        "GLOBAL PULSE READY\n"
        "Local archive, workspaces and headline queue prepared.\n"
        "Live source collection remains subject to provider availability.",
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        QColor("#eee8f7"),
    )
    return True


def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    if values[:1] == ["--gdelt-worker"]:
        from .gdelt_worker import main as gdelt_main
        return gdelt_main(values[1:])
    parser = argparse.ArgumentParser(description="Global Pulse · Dietrich AI Labs")
    parser.add_argument("--version", action="version", version=f"Global Pulse {__version__} ({BUILD_ID})")
    parser.add_argument("--data-dir", type=Path, help="Use a separate application data directory")
    parser.add_argument("--activate", default="", help="Open an exact event in the existing instance")
    parser.add_argument("--demo", action="store_true", help="Explicit synthetic review mode; no live collection or Windows alerts")
    parser.add_argument("--fixture", type=Path, help="Synthetic fixture, permitted only with --demo")
    parser.add_argument("--snapshot", type=Path, help="Render one UI snapshot and exit; no monitoring")
    parser.add_argument("--snapshot-first-fixture-event", action="store_true",
                        help="Select a synthetic fixture event for an explicit demo snapshot")
    parser.add_argument("--snapshot-size", metavar="WIDTHxHEIGHT",
                        help="Explicit synthetic snapshot dimensions (960x640 to 1920x1080)")
    parser.add_argument("--no-start", action="store_true", help="Open with monitoring paused")
    parser.add_argument("--skip-setup", action="store_true", help="Engineering automation: skip interest dialog")
    args = parser.parse_args(argv)
    if args.fixture and not args.demo:
        parser.error("--fixture requires --demo")
    if args.snapshot_first_fixture_event and not (args.demo and args.fixture and args.snapshot):
        parser.error("--snapshot-first-fixture-event requires --demo, --fixture and --snapshot")
    snapshot_size = None
    if args.snapshot_size is not None:
        if not (args.demo and args.fixture and args.snapshot):
            parser.error("--snapshot-size requires --demo, --fixture and --snapshot")
        dimensions = args.snapshot_size.lower().split("x")
        if len(dimensions) != 2 or any(not x.isdecimal() for x in dimensions):
            parser.error("--snapshot-size must be WIDTHxHEIGHT in whole pixels")
        snapshot_size = tuple(map(int, dimensions))
        if not (960 <= snapshot_size[0] <= 1920 and 640 <= snapshot_size[1] <= 1080):
            parser.error("--snapshot-size is outside the supported 960x640 to 1920x1080 review range")
    if args.activate:
        event_id(args.activate)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Global Pulse")
    app.setOrganizationName("Dietrich AI Labs")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(pulse_icon())
    app.setQuitOnLastWindowClosed(False)
    directory = (args.data_dir or data_directory()).resolve()
    if args.demo and not args.data_dir:
        directory = directory / "synthetic-review"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    log = logging.getLogger("global_pulse")
    log.setLevel(logging.WARNING)
    handler = RotatingFileHandler(directory / "diagnostics.log", maxBytes=256000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    from .single_instance import SingleInstance
    instance = SingleInstance(directory)
    try:
        if not instance.acquire(args.activate):
            return 0
    except RuntimeError as error:
        QMessageBox.warning(None, "Global Pulse", str(error))
        return 1
    splash = show_initializing(app)
    controller = None
    try:
        from .controller import Controller, in_quiet_hours
        from .native_notifications import NativeNotifications
        from .ui import MainWindow
        controller = Controller(directory, demo=args.demo)
        splash.showMessage(
            "INITIALIZING GLOBAL PULSE\nPreparing the world map, media, and reports…",
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            QColor("#eee8f7")
        )
        app.processEvents()
        window = MainWindow(controller)
        window.setWindowIcon(pulse_icon())
    except BaseException:
        splash.close()
        if controller is not None:
            try:
                controller.close()
            except Exception:
                logging.getLogger("global_pulse").exception(
                    "Controller cleanup failed during initial desktop construction"
                )
        instance.close()
        handler.close()
        log.removeHandler(handler)
        raise
    def native_allowed():
        return controller.monitoring and controller.get_setting("notifications_enabled", True) and not in_quiet_hours({key: controller.get_setting(key, default) for key, default in [("quiet_enabled",False),("quiet_start","22:00"),("quiet_end","07:00")]})

    notifier = NativeNotifications(enabled=not args.demo, predicate=native_allowed)
    controller.native_alert.connect(notifier.notify)
    def notification_status_only(status):
        if not controller._closed:
            controller.notification_status = status
            controller.notification_changed.emit()

    notifier.status_changed.connect(notification_status_only)

    def delivered(identifier, status):
        if not controller._closed:
            controller.store.update_alert_delivery(identifier, status)
            # Delivery state changes the Alerts card, not the event archive,
            # source clustering or 5,000-point world map.
            controller.notification_changed.emit()

    notifier.delivery_changed.connect(delivered)

    def activate(identifier=""):
        window.showNormal() if window.isMinimized() else window.show()
        window.raise_()
        window.activateWindow()
        if identifier:
            window.navigate_event(identifier)

    instance.activated.connect(activate)
    notifier.activated.connect(activate)
    tray = QSystemTrayIcon(pulse_icon(), app)
    tray.setToolTip("Global Pulse · monitoring paused")
    menu = QMenu()
    menu.addAction("Open Global Pulse", lambda: activate())
    menu.addSeparator()
    menu.addAction("Pause Monitoring", controller.pause)
    menu.addAction("Resume Monitoring", controller.resume)
    mute = menu.addAction("Mute Notifications")
    mute.setCheckable(True)
    mute.setChecked(not controller.get_setting("notifications_enabled", True))
    mute.toggled.connect(lambda value: controller.set_setting("notifications_enabled", not value))
    menu.addAction("View Alerts", lambda: (activate(), window.open_page(4)))
    menu.addAction("Open Settings", lambda: (activate(), window.open_page(6)))
    menu.addSeparator()
    menu.addAction("Exit Completely", controller.quit)
    tray.setContextMenu(menu)
    # Keep the native Windows right-click menu. Some taskbar overflow icons
    # swallow the first context click; single LEFT click now offers the same
    # menu via non-blocking popup, with double click still restoring the app.
    def tray_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            menu.hide()
            activate()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            if not menu.isVisible() and not controller._closed:
                menu.popup(QCursor.pos())
    tray.activated.connect(tray_activated)
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()

    shutting_down = False
    tray_last_state = None
    tray_last_tip = None
    tray_pending_menu = False

    def update_tray(*_):
        nonlocal tray_last_state, tray_last_tip, tray_pending_menu
        if shutting_down or controller._closed:
            return
        # Replacing Explorer's icon while its native context popup is open
        # can make right-click/Exit Completely appear unreliable.
        if menu.isVisible():
            tray_pending_menu = True
            return
        tray_pending_menu = False
        unread = any(not a.get("read", False) for a in controller.store.list_alerts(limit=50))
        enabled = (s["id"] for s in controller.catalog if s.get("enabled"))
        errors = controller.store.any_source_error(enabled)
        state = "alerts" if unread else "paused" if not controller.monitoring else "error" if errors else "active"
        if state != tray_last_state:
            tray.setIcon(pulse_icon(state))
            tray_last_state = state
        tip = "Global Pulse · " + ("monitoring active" if controller.monitoring else "monitoring paused")
        if tip != tray_last_tip:
            tray.setToolTip(tip)
            tray_last_tip = tip

    # Collector events, source health and native alerts arrive in bursts.
    # Never restart a pending first-due refresh or scan per enabled source.
    tray_refresh_timer = QTimer(tray)
    tray_refresh_timer.setSingleShot(True)
    tray_refresh_timer.setInterval(700)
    tray_refresh_timer.timeout.connect(update_tray)

    def schedule_tray(*_):
        if shutting_down or controller._closed:
            return
        if not tray_refresh_timer.isActive():
            tray_refresh_timer.start()

    def menu_hidden():
        nonlocal tray_pending_menu
        if not tray_pending_menu:
            return
        tray_pending_menu = False
        # Defer beyond menu.hide()'s synchronous quit signal. Shutdown may be
        # called next; schedule_tray checks it before any Store access.
        QTimer.singleShot(0, schedule_tray)

    menu.aboutToHide.connect(menu_hidden)
    controller.data_changed.connect(schedule_tray)
    controller.evidence_changed.connect(schedule_tray)
    controller.source_status_changed.connect(schedule_tray)
    controller.notification_changed.connect(schedule_tray)
    controller.alert_received.connect(schedule_tray)

    def shutdown():
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        window.save_layout()
        for widget in window.findChildren(QWidget):
            if widget.__class__.__name__ == "MediaPanel":
                widget.shutdown()
        notifier.stop()
        try:
            controller.close()
        except RuntimeError as error:
            shutting_down = False
            window.show()
            QMessageBox.critical(window, "Full exit not completed", str(error) + ". The window remains available; retry Exit Completely.")
            return
        instance.close()
        window.set_close_handler(None)
        window._force_close = True
        window.close()
        tray.hide()
        app.quit()

    # Imported here to avoid including a GUI object in the pure helper functions.
    from PySide6.QtWidgets import QWidget
    # Keep GUI-only cleanup on the quit signal rather than adding
    # more hidden closure dependencies to the native shutdown body.
    # The latter also has an independent camera/consent lifecycle test.
    controller.quit_requested.connect(tray_refresh_timer.stop)
    controller.quit_requested.connect(menu.hide)
    controller.quit_requested.connect(shutdown)

    tray_save_pending = False

    def persist_tray_layout():
        nonlocal tray_save_pending
        tray_save_pending = False
        if shutting_down or getattr(controller, "_closed", False):
            return
        try:
            window.save_layout()
        except (OSError, RuntimeError, ValueError) as error:
            logging.warning("Could not persist tray layout: %s", error)

    def close_window():
        nonlocal tray_save_pending
        if shutting_down:
            return
        if controller.get_setting("close_to_tray", True) and tray.isVisible():
            first_close = not controller.get_setting("tray_explained", False)
            # Hide before any database write; no duplicated synchronous saves.
            window.hide()
            if not tray_save_pending:
                tray_save_pending = True
                QTimer.singleShot(0, persist_tray_layout)
            if first_close:
                def show_tray_notice():
                    if shutting_down or getattr(controller, "_closed", False):
                        return
                    try:
                        controller.set_setting("tray_explained", True)
                    except (OSError, RuntimeError, ValueError):
                        logging.warning("Could not save tray explanation flag")
                    if QSystemTrayIcon.supportsMessages():
                        tray.showMessage(
                            "Global Pulse keeps monitoring",
                            "Global Pulse is now in the system tray. Double-click to reopen, "
                            "or choose Exit Completely from the tray menu.",
                            QSystemTrayIcon.MessageIcon.Information, 5000
                        )
                QTimer.singleShot(0, show_tray_notice)
        else:
            controller.quit()

    window.set_close_handler(close_window)
    if args.fixture:
        controller.load_fixture(args.fixture)
    if args.snapshot_first_fixture_event:
        fixture_events = controller.events()
        if not fixture_events:
            raise ValueError("Synthetic snapshot fixture contains no selectable events")
        window.navigate_event(fixture_events[0]["id"])
    if snapshot_size is not None:
        window.resize(*snapshot_size)
    # Never reveal an interactive dashboard until its expensive local
    # workspace construction AND deferred cold headline queue have settled.
    # This cannot and does not preload live media or future source updates.
    try:
        prepare_initial_dashboard(app, splash, window, controller)
    except BaseException:
        # Failure before app.exec() must not strand a singleton lock, splash,
        # translation thread, media session, or open local SQLite handles.
        splash.close()
        try:
            window.media.shutdown()
            window._force_close=True
            window.close()
            controller.close()
        finally:
            instance.close()
            handler.close()
            log.removeHandler(handler)
        raise
    window.show()
    splash.finish(window)
    if args.activate:
        QTimer.singleShot(150, lambda: activate(args.activate))
    if args.snapshot:
        def snapshot():
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            from .visual_diagnostics import capture_diagnostics
            diagnostics = capture_diagnostics(app, window)
            if args.demo and args.fixture:
                diagnostics["synthetic_fixture"] = True
                diagnostics["synthetic_selected_event"] = bool(getattr(window, "_selected_id", None))
                diagnostics["synthetic_banner_visible"] = any(
                    "SYNTHETIC TRAINING SCENARIO" in widget.text() and widget.isVisible()
                    for widget in window.findChildren(QLabel))
                diagnostics["requested_snapshot_size"] = list(snapshot_size) if snapshot_size else None
            diagnostics["image_saved"] = window.grab().save(str(args.snapshot))
            args.snapshot.with_suffix(".json").write_text(
                json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8")
            controller.quit()
        QTimer.singleShot(800, snapshot)
    elif args.demo:
        controller.status_changed.emit("SYNTHETIC REVIEW · collection disabled")
    else:
        def begin():
            from .distribution_terms import accept_windows_sdk_terms
            if accept_windows_sdk_terms(controller, window):
                notifier.start()
            else:
                notifier.status_changed.emit("Windows notifications off — Microsoft component terms not accepted")
            if args.no_start:
                return
            should_start = True
            if not args.skip_setup and not controller.get_setting("setup_complete", False):
                should_start = onboarding(controller, window)
            if should_start:
                controller.start()
        QTimer.singleShot(50, begin)

    try:
        result = app.exec()
    finally:
        if not shutting_down:
            controller.quit()
        handler.close()
        log.removeHandler(handler)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
