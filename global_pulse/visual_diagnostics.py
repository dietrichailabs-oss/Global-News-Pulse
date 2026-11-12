"""Opt-in snapshot evidence from the actual application's Qt objects.

No font files, source/news text, environment values, user paths, or screenshots
from other applications are collected. Glyph coverage is a necessary diagnostic,
not a claim of visual acceptance or a substitute for inspecting the saved image.
"""
from __future__ import annotations

from PySide6.QtCore import qVersion
from PySide6.QtGui import QFontDatabase, QFontInfo, QRawFont
from PySide6.QtWidgets import QLabel, QPushButton, QTextBrowser

# English interface content must not silently become missing-glyph boxes. Special
# symbols have platform font fallback and are recorded separately, not certified.
PROBE_TEXT = "Global Pulse ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 .,!?()-:/"


def capture_diagnostics(app, window) -> dict:
    fonts = {}
    for widget in (window, *window.findChildren(QLabel),
                   *window.findChildren(QPushButton), *window.findChildren(QTextBrowser)):
        if not widget.isVisible():
            continue
        font = widget.font()
        key = font.toString()
        if key in fonts:
            continue
        raw = QRawFont.fromFont(font)
        info = QFontInfo(font)
        missing = sorted({ch for ch, glyph in zip(PROBE_TEXT, raw.glyphIndexesForString(PROBE_TEXT))
                          if not ch.isspace() and glyph == 0}) if raw.isValid() else sorted(set(PROBE_TEXT.strip()))
        fonts[key] = {"requested_family": font.family(), "resolved_family": info.family(),
                      "raw_family": raw.familyName(), "valid": raw.isValid(),
                      "pixel_size": info.pixelSize(), "missing_ascii_glyphs": missing}
    screen = window.screen()
    cards = {}
    for name in ("intel_browser", "evidence_status_text", "change_status_text"):
        widget = getattr(window, name, None)
        if widget is not None:
            cards[name] = {"viewport_height": widget.viewport().height(),
                           "line_spacing": widget.fontMetrics().lineSpacing(),
                           "minimum_height": widget.minimumHeight()}
    return {
        "schema_version": 1, "qt_version": qVersion(),
        "platform_backend": app.platformName(),
        "available_font_family_count": len(QFontDatabase.families()),
        "window_size": [window.width(), window.height()],
        "screen_size": [screen.geometry().width(), screen.geometry().height()] if screen else None,
        "logical_dpi": screen.logicalDotsPerInch() if screen else None,
        "device_pixel_ratio": window.devicePixelRatioF(),
        "fonts": list(fonts.values()), "status_cards": cards,
        "ascii_font_coverage": bool(fonts) and all(f["valid"] and not f["missing_ascii_glyphs"] for f in fonts.values()),
        "visual_acceptance": "NOT ESTABLISHED: inspect the actual saved application image",
        "native_notification_acceptance": "NOT RUN",
    }
