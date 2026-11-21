"""Source-registry actions bound to provider IDs, not mutable table rows."""
from __future__ import annotations

import html
import sqlite3
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTextBrowser

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
    filters = QHBoxLayout()
    window.source_search = QLineEdit()
    window.source_search.setPlaceholderText("Search all sources: name, ID, topic, country or publisher…")
    window.source_search.setClearButtonEnabled(True)
    window.source_search.setAccessibleName("Search the complete source registry")
    filters.addWidget(window.source_search, 1)
    window.source_filter = QComboBox()
    window.source_filter.setAccessibleName("Source collection filter")
    for text, key in (("All sources", "all"), ("Enabled collectors", "enabled"),
                      ("Available collectors", "available"), ("Off collectors", "off"),
                      ("Not checked", "unchecked"), ("Needs attention", "attention"),
                      ("Website / setup / unavailable", "unavailable")):
        window.source_filter.addItem(text, key)
    filters.addWidget(window.source_filter)
    filters.addWidget(button("Show all", lambda: reset_source_filters(window)))
    panel.layout.addLayout(filters)
    window.source_visible_count = label("", "Muted", True)
    panel.layout.addWidget(window.source_visible_count)
    window.source_table = QTableWidget(0, 10)
    window.source_table.setHorizontalHeaderLabels(["Source", "Type", "Collection", "Last result", "Last successful check", "Newest publication", "Next due", "Minimum interval", "Collection action", "Provider page"])
    window._configure_table(window.source_table)
    # This 10-column provider table can hold 512 admitted catalog entries.
    # ResizeToContents normally examines up to 1000 rows *per column* when
    # computing size hints, including the two real per-row action controls.
    # Keep the full model, selection, sorting and accessible source text, but
    # bound hidden-tab layout measurement to a representative 64 rows. Long
    # entries are still available through their actual cell text and details.
    window.source_table.horizontalHeader().setResizeContentsPrecision(64)
    window.source_table.setAccessibleName("Providers, collection controls and observed source health")
    window.source_table.itemSelectionChanged.connect(window._source_selected)
    panel.layout.addWidget(window.source_table, 3)
    # The batch collector is not a catalog publisher and has its own opt-in
    # and durable scheduling. It must be visible here without pretending that
    # every website mentioned in GDELT is another configured source feed.
    batches = QHBoxLayout()
    window.source_batch_status = label("GDELT batch collector: status not yet available", "Muted", True)
    batches.addWidget(window.source_batch_status, 1)
    batches.addWidget(button("Batch details", lambda: show_batch_source_details(window)))
    batches.addWidget(button("Batch settings", lambda: window.open_page(6)))
    panel.layout.addLayout(batches)
    window.source_browser = QTextBrowser()
    window.source_browser.setOpenExternalLinks(False)
    window.source_browser.anchorClicked.connect(lambda url: window.controller.open_url(url.toString()))
    panel.layout.addWidget(window.source_browser, 1)
    window.pages.addWidget(panel)
    window.source_search.textChanged.connect(lambda *_: apply_source_filters(window))
    window.source_filter.currentIndexChanged.connect(lambda *_: apply_source_filters(window))
    # Hidden row indexes do not identify providers after sorting. Reapply
    # only the in-memory display filter when the model rearranges its rows.
    window.source_table.model().layoutChanged.connect(lambda *_: apply_source_filters(window))
    # Reuse the already-recorded Settings status AFTER its existing signal
    # handlers run. This adds no SQL, source poll or network activity to idle
    # Sources refreshes, including during a collector-held Store lock.
    window._source_batch_timer = QTimer(window)
    window._source_batch_timer.setSingleShot(True)
    window._source_batch_timer.setInterval(0)
    window._source_batch_timer.timeout.connect(lambda: refresh_batch_source_status(window))
    for name in ("gdelt_status_changed", "data_changed"):
        signal = getattr(window.controller, name, None)
        if signal is not None:
            signal.connect(window._source_batch_timer.start)
    window._source_batch_timer.start()


def refresh_batch_source_status(window):
    """Show existing in-memory/recorded GDELT status, never query on Qt here."""
    controls = getattr(window, "gdelt_controls", None)
    service = getattr(window.controller, "_gdelt", None)
    if controls is None or service is None:
        text = "GDELT batch collector: recorded status not yet available; see Batch settings."
        detail = text
    else:
        enabled = getattr(controls, "_saved_enabled", False) is True
        active = bool(getattr(service, "active", False))
        running = getattr(service, "process", None) is not None
        current = ("worker running" if running else "active; waiting for next allowed check"
                   if active else "monitoring paused" if enabled else "off")
        recorded = controls.status_label.text()
        first_line = recorded.splitlines()[0] if recorded else "not yet available"
        text = ("GDELT 15-minute batches · " + ("Enabled" if enabled else "Off") +
                " · " + current + ". Recorded Settings status: " + first_line)
        detail = ("GDELT 15-minute batch archive — separate collector, not additional registered publishers.\n" +
                  "Configured: " + ("enabled" if enabled else "off") + "; current worker: " + current +
                  "\nRecorded collector status (no new request made by this view):\n" + recorded +
                  "\nCoded event records and linked websites are not verified incidents or independently configured source feeds.")
    if window.source_batch_status.text() != text:
        window.source_batch_status.setText(text)
    window.source_batch_status.setToolTip("<pre>" + html.escape(detail) + "</pre>")
    window._source_batch_details = detail


def show_batch_source_details(window):
    refresh_batch_source_status(window)
    window.source_table.clearSelection()
    window.source_table.setCurrentCell(-1, -1)
    window.source_browser.setPlainText(window._source_batch_details)


def reset_source_filters(window):
    blocked = window.source_search.blockSignals(True)
    window.source_search.clear()
    window.source_search.blockSignals(blocked)
    blocked = window.source_filter.blockSignals(True)
    window.source_filter.setCurrentIndex(0)
    window.source_filter.blockSignals(blocked)
    apply_source_filters(window)


def apply_source_filters(window):
    """Search every displayed registry row; never fetch or enable a source."""
    if not hasattr(window, "source_search"):
        return
    table = window.source_table
    query = window.source_search.text().strip().casefold()
    mode = window.source_filter.currentData() or "all"
    enabled = getattr(window, "_source_inventory_enabled", frozenset())
    states = getattr(window, "_source_inventory_states", {})
    matches = 0
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        source = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(source, dict):
            continue
        sid = source.get("id")
        available = capability(source)[0]
        state = states.get(sid) or {}
        status = str(state.get("status") or "").casefold()
        attention = (status in {"error", "failed", "denied", "rate_limited", "unavailable", "stale"}
                     or state.get("freshness") == "stale")
        admitted = (mode == "all" or mode == "enabled" and sid in enabled
                    or mode == "available" and available
                    or mode == "off" and available and sid not in enabled
                    or mode == "unavailable" and not available
                    or mode == "attention" and available and attention
                    or mode == "unchecked" and available and not state.get("last_attempt")
                    and not state.get("last_success") and status in {"", "not_checked"})
        searchable = " ".join(str(source.get(key) or "") for key in
                              ("id", "name", "publisher_origin_id", "country", "region",
                               "category", "homepage", "url")).casefold()
        visible = admitted and (not query or query in searchable)
        table.setRowHidden(row, not visible)
        matches += int(visible)
    window.source_visible_count.setText(
        f"Showing {matches} of {table.rowCount()} registry entries · {len(enabled)} enabled collectors. "
        "No rows are removed by search. GDELT batch collection is shown separately below.")


def _catalog_fingerprint(catalog):
    """Capture immutable provider metadata, not references to mutable dicts.

    Status polling never changes catalog metadata, so frequent updates reuse
    all widgets. Any same-ID access/URL/adapter/name change rebuilds actions,
    provider links and UserRole metadata before they can become misleading.
    """
    return tuple(tuple(sorted((str(key), repr(value)) for key, value in source.items()))
                 for source in catalog)


def _existing_source_rows(table):
    """Reuse cells and controls across live status pulses, even after sorting."""
    rows = {}
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        source = item.data(Qt.ItemDataRole.UserRole) if item else None
        sid = source.get("id") if isinstance(source, dict) else None
        if not sid or sid in rows:
            return {}
        rows[sid] = row
    return rows


def populate_sources(window, *, idle=False):
    from .ui import timestamp
    table = window.source_table
    current = table.item(table.currentRow(), 0)
    selected_id = (current.data(Qt.ItemDataRole.UserRole) or {}).get("id") if current else None
    catalog = list(window.controller.catalog)
    fingerprint = _catalog_fingerprint(catalog)
    if idle:
        # A truly unchanged persisted revision, catalog and monitoring state
        # cannot have changed source health or enabled preferences. Avoid even
        # a 512-source SQL scan on a no-op status pulse. A second nonblocking
        # check rejects writes arriving during this cheap identity comparison.
        previous = getattr(window, "_source_status_render_key", None)
        store = window.controller.store
        revision = store.content_revision_if_available()
        if revision is None:
            return False
        if (previous is not None and len(previous) == 4
                and previous[0] == revision and previous[1] == fingerprint
                and previous[3] == bool(window.controller.monitoring)
                and table.rowCount() == len(catalog)):
            confirmed = store.content_revision_if_available()
            if confirmed is None:
                return False
            if confirmed == revision:
                return True
        # The first nonblocking workspace probe cannot reserve the Store
        # RLock. Read enabled preferences, revision and all source health as
        # ONE atomic try-lock snapshot; BUSY retains the dirty tab for retry.
        snapshot = window.controller.store.source_status_snapshot_if_available(
            source["id"] for source in catalog)
        if snapshot is None:
            return False
        enabled = enabled_ids(catalog, snapshot["enabled_sources"])
        store_revision = snapshot["revision"]
    else:
        enabled = _effective(window)
        store_revision = window.controller.store.content_revision()
    # Status-only signals often repeat with no persisted source or registry
    # change. A full 10-column Qt table reconciliation in an idle timer can
    # stall the GUI even when every displayed value is identical. Use the
    # Store's same-connection + external-connection mutation revision to skip
    # unchanged work, never a time-based cache that could hide a real failure.
    # Catalog, enabled-source settings and monitoring state are independent
    # parts of the visible contract and must also invalidate this fast path.
    # General archive revisions include unrelated events and observations.
    # They cannot, by themselves, prove that any provider health row changed.
    visual_key = (fingerprint, frozenset(enabled),
                  bool(window.controller.monitoring))
    render_key = (store_revision, *visual_key)
    if (getattr(window, "_source_status_render_key", None) == render_key
            and table.rowCount() == len(catalog)):
        return True
    # Unchanged status skips Qt cell reconciliation. Passive work uses the
    # atomic try-lock snapshot, never a second blocking SQLite read.
    states = (snapshot["states"] if idle else
              window.controller.store.list_source_states(s["id"] for s in catalog))
    prior_states = getattr(window, "_source_status_last_states", None)
    prior_visual = getattr(window, "_source_status_visual_key", None)
    # Only a stable complete read can suppress UI work. A concurrent writer
    # invalidates this fast path, so the next status pulse can reconcile it.
    stable_snapshot = (idle or
                       window.controller.store.content_revision() == store_revision)
    if (stable_snapshot and prior_visual == visual_key
            and prior_states == states and table.rowCount() == len(catalog)):
        window._source_status_render_key = render_key
        return True
    old_rows = _existing_source_rows(table)
    reuse = (bool(old_rows) and set(old_rows) == {s["id"] for s in catalog}
             and getattr(window, "_source_registry_fingerprint", None) == fingerprint)
    refresh_details = (selected_id is not None and
                       (not reuse or prior_visual != visual_key or prior_states is None or
                        states.get(selected_id, {}) != prior_states.get(selected_id, {})))
    # Filter the exact state represented in the table, not a new blocking
    # preference/status read for each key press or source-status pulse.
    window._source_inventory_enabled = frozenset(enabled)
    window._source_inventory_states = states
    blocked = table.blockSignals(True)
    sorting = table.isSortingEnabled()
    selected_row = None
    try:
        table.setSortingEnabled(False)
        if not reuse:
            table.clearContents()
            table.setRowCount(len(catalog))
        collectable = 0
        for catalog_row, source in enumerate(catalog):
            sid = source["id"]
            row = old_rows[sid] if reuse else catalog_row
            available, kind, reason = capability(source)
            collectable += int(available)
            state = states.get(sid) or {}
            on = sid in enabled
            if (reuse and prior_visual == visual_key and prior_states is not None
                    and state == prior_states.get(sid, {})):
                # Only genuinely changed checkpoints require Qt cell work.
                # The source's metadata, enabled set, monitoring status and
                # physical table rows have already been checked above.
                if sid == selected_id:
                    selected_row = row
                continue
            collection = ("Enabled" if window.controller.monitoring else "Enabled; monitoring paused") if on else "Off" if available else "Not connected"
            values = [source.get("name", sid), kind, collection,
                      health_text(state) if available else reason,
                      timestamp(state.get("last_success")) if available else "—",
                      timestamp(state.get("latest_publication")) if state.get("latest_publication") else "Unknown",
                      timestamp(state.get("next_poll")) if on and state.get("next_poll") else "—",
                      str(max(1, int(source.get("min_interval", 600))) // 60) + " min" if available else "—"]
            for column, value in enumerate(values):
                if reuse:
                    item = table.item(row, column)
                    if item is None:
                        item = QTableWidgetItem()
                        table.setItem(row, column, item)
                    if item.text() != str(value):
                        item.setText(str(value))
                    if item.toolTip() != reason:
                        item.setToolTip(reason)
                else:
                    item = QTableWidgetItem(str(value))
                    item.setData(Qt.ItemDataRole.UserRole, source)
                    item.setToolTip(reason)
                    table.setItem(row, column, item)
            if reuse:
                action = table.cellWidget(row, 8)
                if available and isinstance(action, QPushButton):
                    desired = "Disable collection" if on else "Enable collection"
                    if action.text() != desired:
                        action.setText(desired)
                    action.setAccessibleName(desired + ": " + str(source.get("name", sid)))
                # Capability doesn't change without a catalog edit. A changed
                # catalog necessarily triggers a full widget rebuild.
            elif available:
                action = QPushButton("Disable collection" if on else "Enable collection")
                action.setProperty("source_id", sid)
                action.setAccessibleName(action.text() + ": " + str(source.get("name", sid)))
                # Compute target on click, not at construction: live collection
                # state can change without destroying 170 buttons.
                action.clicked.connect(
                    lambda checked=False, identity=sid: set_enabled(
                        window, identity, identity not in _effective(window)
                    )
                )
                table.setCellWidget(row, 8, action)
                table.setCellWidget(row, 9, _site_button(window, source))
            else:
                action = QLabel(kind)
                action.setTextFormat(Qt.TextFormat.PlainText)
                action.setWordWrap(True)
                action.setToolTip(reason)
                table.setCellWidget(row, 8, action)
                table.setCellWidget(row, 9, _site_button(window, source))
            if sid == selected_id:
                selected_row = row
        summary = (f"{collectable} automatic feeds · {len(enabled)} enabled · "
                   f"{len(catalog)-collectable} website/setup/unavailable entries (not collecting) · "
                   f"{len(catalog)} total registered entries, including sources never checked")
        if window.source_summary.text() != summary:
            window.source_summary.setText(summary)
        if not reuse:
            window._source_registry_fingerprint = fingerprint
            if selected_row is not None:
                table.selectRow(selected_row)
            else:
                table.clearSelection()
                table.setCurrentCell(-1, -1)
                window.source_browser.setPlainText("Select a provider to inspect access, attribution, limitations and its last recorded result.")
    finally:
        table.setSortingEnabled(sorting)
        table.blockSignals(blocked)
    apply_source_filters(window)
    # A Store write may occur while the table is being rendered. In that
    # case do not bless a mixed status snapshot as current: the next
    # coalesced source-status signal must be allowed to reconcile it.
    current_revision = (window.controller.store.content_revision_if_available()
                        if idle else window.controller.store.content_revision())
    if current_revision == store_revision:
        window._source_status_render_key = render_key
        window._source_status_last_states = states
        window._source_status_visual_key = visual_key
    else:
        window._source_status_render_key = None
        window._source_status_last_states = None
        window._source_status_visual_key = None
    if selected_row is not None and refresh_details:
        # A reused selected row can change collection/monitoring or receive a
        # new error/recovery without changing selection. Its detail pane must
        # not keep the old result or collection mode indefinitely.
        # Reuse this same batch snapshot, including on the passive idle path.
        source_selected(window, states=states)
    return current_revision == store_revision if idle else True


def source_selected(window, *, states=None):
    from .ui import timestamp
    item = window.source_table.item(window.source_table.currentRow(), 0)
    if item is None:
        return
    source = _source(window, (item.data(Qt.ItemDataRole.UserRole) or {}).get("id"))
    if not source:
        window.source_browser.setPlainText("This provider is no longer configured.")
        return
    _, kind, reason = capability(source)
    state = (states.get(source["id"], {}) if states is not None else
             window.controller.store.get_source_state(source["id"]) or {})
    title, url = source_link(source)
    esc = lambda value: html.escape(str(value or ""), quote=True)
    link = f"<p><a href='{esc(url)}'>{esc(title)}</a> (external browser)</p>" if url else ""
    collection = window.source_table.item(window.source_table.currentRow(), 2)
    fields = [("Source ID", source["id"]), ("Type", kind),
              ("Collection", collection.text() if collection else "Unknown"),
              ("Topic", source.get("category") or "Not specified"),
              ("Publisher coverage", source.get("country") or source.get("region") or "Not specified"),
              ("Next step", reason), ("Access", source.get("access")),
              ("License", source.get("license")), ("Attribution", source.get("attribution")),
              ("Limitation", source.get("limitation") or source.get("notes")),
              ("Last recorded result", health_text(state)),
              ("Last attempted check", timestamp(state.get("last_attempt"))),
              ("Last successful check", timestamp(state.get("last_success"))),
              ("Last failure", timestamp(state.get("last_failure"))),
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
