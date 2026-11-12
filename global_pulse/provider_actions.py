"""Source-registry actions bound to provider IDs, not mutable table rows."""
from __future__ import annotations

import html
import sqlite3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTextBrowser

from .source_availability import capability, enabled_ids, health_text, source_link


def _source(window, source_id):
    return next((s for s in window.controller.catalog if s.get("id") == source_id), None)


def _effective(window):
    return enabled_ids(window.controller.catalog, window.controller.get_setting("enabled_sources", None))


def _site_button(window, source):
    title, url = source_link(source)
    control = QPushButton(title)
    control.setEnabled(bool(url))
    control.setAccessibleName(title + ": " + str(source.get("name", source["id"])))
    control.setProperty("source_id", source["id"])
    control.setToolTip("Opens your external browser; it does not enable collection." if url else "No valid public address is configured.")
    control.clicked.connect(lambda checked=False, sid=source["id"]: open_site(window, sid))
    return control


def open_site(window, source_id):
    source = _source(window, source_id)
    url = source_link(source)[1] if source else ""
    if not url:
        window.status_label.setText("This provider is no longer configured or has no valid public address.")
        return False
    opened = window.controller.open_url(url)
    window.status_label.setText("Opened provider in your browser; collection settings are unchanged." if opened else "The provider page could not be opened.")
    return bool(opened)


def set_enabled(window, source_id, enabled):
    try:
        window.controller.set_source_enabled(source_id, enabled)
    except (ValueError, RuntimeError, sqlite3.Error):
        window.status_label.setText("Could not change collection. The provider may be unavailable or the archive is not writable.")
        populate_sources(window)
        return False
    # Synchronize this source only. Other unsaved Settings selections survive.
    for row in range(window.source_preferences.rowCount()):
        check = window.source_preferences.cellWidget(row, 0)
        if isinstance(check, QCheckBox) and check.property("source_id") == source_id:
            check.setChecked(enabled)
    populate_sources(window)
    window.status_label.setText(
        "Collection enabled; provider intervals and retry delays still apply."
        if enabled and window.controller.monitoring else
        "Collection enabled, but monitoring is paused. Choose Resume to collect."
        if enabled else "Collection disabled. Existing reports remain in the archive."
    )
    return True


def build_sources(window):
    from .ui import Panel, label, button
    panel = Panel("SOURCE REGISTRY & HEALTH")
    panel.heading.addWidget(button("Add public feed…", window._add_user_feed))
    panel.heading.addWidget(button("Remove selected custom feed", window._remove_user_feed))
    panel.layout.addWidget(label("Automatic feeds can collect reports. Website-only entries open in your browser; they are not connected feeds. Enabling does not override pause, access rules or provider retry limits.", "Muted", True))
    window.source_summary = label("", "Muted", True)
    panel.layout.addWidget(window.source_summary)
    window.source_table = QTableWidget(0, 10)
    window.source_table.setHorizontalHeaderLabels(["Source", "Type", "Collection", "Last result", "Last successful check", "Newest publication", "Next due", "Minimum interval", "Collection action", "Provider page"])
    window._configure_table(window.source_table)
    window.source_table.setAccessibleName("Providers, collection controls and observed source health")
    window.source_table.itemSelectionChanged.connect(window._source_selected)
    panel.layout.addWidget(window.source_table, 3)
    window.source_browser = QTextBrowser()
    window.source_browser.setOpenExternalLinks(False)
    window.source_browser.anchorClicked.connect(lambda url: window.controller.open_url(url.toString()))
    panel.layout.addWidget(window.source_browser, 1)
    window.pages.addWidget(panel)


def populate_sources(window):
    from .ui import timestamp
    table = window.source_table
    current = table.item(table.currentRow(), 0)
    selected_id = (current.data(Qt.ItemDataRole.UserRole) or {}).get("id") if current else None
    enabled = _effective(window)
    catalog = list(window.controller.catalog)
    blocked = table.blockSignals(True)
    sorting = table.isSortingEnabled()
    selected_row = None
    try:
        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(len(catalog))
        collectable = 0
        for row, source in enumerate(catalog):
            sid = source["id"]
            available, kind, reason = capability(source)
            collectable += int(available)
            state = window.controller.store.get_source_state(sid) or {}
            on = sid in enabled
            collection = ("Enabled" if window.controller.monitoring else "Enabled; monitoring paused") if on else "Off" if available else "Not connected"
            values = [source.get("name", sid), kind, collection,
                      health_text(state) if available else reason,
                      timestamp(state.get("last_success")) if available else "—",
                      timestamp(state.get("latest_publication")) if state.get("latest_publication") else "Unknown",
                      timestamp(state.get("next_poll")) if on and state.get("next_poll") else "—",
                      str(max(1, int(source.get("min_interval", 600))) // 60) + " min" if available else "—"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, source)
                item.setToolTip(reason)
                table.setItem(row, column, item)
            if available:
                action = QPushButton("Disable collection" if on else "Enable collection")
                action.setProperty("source_id", sid)
                action.setAccessibleName(action.text() + ": " + str(source.get("name", sid)))
                action.clicked.connect(lambda checked=False, identity=sid, target=not on: set_enabled(window, identity, target))
            else:
                action = QLabel(kind)
                action.setTextFormat(Qt.TextFormat.PlainText)
                action.setWordWrap(True)
                action.setToolTip(reason)
            table.setCellWidget(row, 8, action)
            table.setCellWidget(row, 9, _site_button(window, source))
            if sid == selected_id:
                selected_row = row
        window.source_summary.setText(f"{collectable} automatic feeds · {len(enabled)} enabled · {len(catalog)-collectable} website/setup/unavailable entries (not collecting)")
        if selected_row is not None:
            table.selectRow(selected_row)
        else:
            table.clearSelection()
            table.setCurrentCell(-1, -1)
            window.source_browser.setPlainText("Select a provider to inspect access, attribution, limitations and its last recorded result.")
    finally:
        table.setSortingEnabled(sorting)
        table.blockSignals(blocked)
    if selected_row is not None:
        source_selected(window)


def source_selected(window):
    from .ui import timestamp
    item = window.source_table.item(window.source_table.currentRow(), 0)
    if item is None:
        return
    source = _source(window, (item.data(Qt.ItemDataRole.UserRole) or {}).get("id"))
    if not source:
        window.source_browser.setPlainText("This provider is no longer configured.")
        return
    _, kind, reason = capability(source)
    state = window.controller.store.get_source_state(source["id"]) or {}
    title, url = source_link(source)
    esc = lambda value: html.escape(str(value or ""), quote=True)
    link = f"<p><a href='{esc(url)}'>{esc(title)}</a> (external browser)</p>" if url else ""
    fields = [("Type", kind), ("Next step", reason), ("Access", source.get("access")),
              ("License", source.get("license")), ("Attribution", source.get("attribution")),
              ("Limitation", source.get("limitation") or source.get("notes")),
              ("Last result", health_text(state)), ("Last failure", timestamp(state.get("last_failure"))),
              ("Last error", state.get("error") or "None recorded"),
              ("Newest publication", timestamp(state.get("latest_publication")) if state.get("latest_publication") else "Unknown; retrieval does not prove fresh reporting")]
    window.source_browser.setHtml(f"<h3>{esc(source.get('name', source['id']))}</h3>" + link + "<p>" + "<br>".join(f"<b>{esc(k)}:</b> {esc(v)}" for k, v in fields) + "</p>")


def populate_preferences(window):
    catalog = list(window.controller.catalog)
    enabled = _effective(window)
    muted = window.controller.get_setting("muted_sources", [])
    table = window.source_preferences
    table.setColumnCount(6)
    table.setHorizontalHeaderLabels(["Collect", "Mute alerts", "Source", "Availability / next step", "Last result", "Provider page"])
    table.setRowCount(len(catalog))
    for row, source in enumerate(catalog):
        available, kind, reason = capability(source)
        if available:
            control = QCheckBox("Collect")
            control.setChecked(source["id"] in enabled)
            control.setAccessibleName("Collect from " + str(source.get("name", source["id"])))
        else:
            control = QLabel(kind)
            control.setTextFormat(Qt.TextFormat.PlainText)
            control.setWordWrap(True)
            control.setEnabled(False)  # Read-only explanation, not an inert switch.
        control.setProperty("source_id", source["id"])
        control.setToolTip(reason)
        table.setCellWidget(row, 0, control)
        mute = QCheckBox()
        mute.setChecked(source["id"] in muted)
        mute.setAccessibleName("Mute alerts from " + str(source.get("name", source["id"])))
        table.setCellWidget(row, 1, mute)
        table.setItem(row, 2, QTableWidgetItem(str(source.get("name", source["id"]))))
        table.setItem(row, 3, QTableWidgetItem(reason))
        table.setItem(row, 4, QTableWidgetItem(health_text(window.controller.store.get_source_state(source["id"]) or {}) if available else "Not connected"))
        table.setCellWidget(row, 5, _site_button(window, source))
