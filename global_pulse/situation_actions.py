"""Explicit, identity-bound Situation Room controls. No collection or playback."""
from __future__ import annotations

import sqlite3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem, QMenu


class SituationActions:
    """Small MainWindow mixin; persistence remains in Store/Controller."""

    def _sync_situation_star(self, event=None):
        identity = str((event or {}).get("id") or "")
        try:
            state = self.controller.store.situation_state(identity) if identity else None
        except (sqlite3.Error, RuntimeError):
            state = None
        saved = bool(state and state["saved"])
        self.save_button.setProperty("event_id", state["event_id"] if state else "")
        self.save_button.setChecked(saved)
        self.save_button.setText("★ Starred" if saved else "☆ Star")
        self.save_button.setEnabled(state is not None)
        action = "Unstar this situation" if saved else "Star this situation"
        self.save_button.setAccessibleName(action)
        self.save_button.setToolTip(
            action + ". Saved in Situations across restarts. "
            "This follows the current event, not a frozen historical snapshot."
            if state else "Select an archived event to star it in Situations."
        )

    def _toggle_selected_situation(self, checked=False):
        # The button is bound to the event that was actually rendered. A stale
        # control must not operate on a different newly selected event.
        target = str(self.save_button.property("event_id") or "")
        try:
            state = self.controller.store.situation_state(self._selected_id)
        except (sqlite3.Error, RuntimeError):
            state = None
        if not target or not state or target != state["event_id"]:
            self._sync_situation_star(state and {"id": state["event_id"]})
            self.status_label.setText("Selection changed or the event is no longer archived. Select the event and try again.")
            return
        self._set_situation_star(target, bool(checked))

    def _set_situation_star(self, event_id, saved):
        try:
            result = self.controller.set_situation_saved(str(event_id), saved)
        except (ValueError, sqlite3.Error, RuntimeError):
            self._sync_situation_star({"id": self._selected_id})
            self.status_label.setText("Could not change the star. The event may no longer be archived or the archive is unavailable.")
            return False
        self._sync_situation_star({"id": self._selected_id})
        self.status_label.setText(
            "Starred in Situations. It will stay saved after restart."
            if result["saved"] else
            "Unstarred. The event and its evidence remain in the archive."
        )
        return True

    def _show_feed_situation_menu(self, position):
        item = self.feed_list.itemAt(position)
        if item is None:
            return
        record = item.data(Qt.ItemDataRole.UserRole) or {}
        identity = str(record.get("id") or "")
        state = self.controller.store.situation_state(identity)
        if state is None:
            return
        # Snapshot the clicked row's canonical identity and desired state,
        # never the mutable current selection or a row index.
        target, desired = state["event_id"], not state["saved"]
        menu = QMenu(self.feed_list)
        action = menu.addAction("☆ Unstar situation" if state["saved"] else "★ Star situation")
        action.triggered.connect(lambda checked=False, eid=target, save=desired: self._set_situation_star(eid, save))
        try:
            menu.exec(self.feed_list.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def _sync_situation_remove(self, *_):
        self.unstar_button.setEnabled(self.situation_list.currentItem() is not None)

    def _unstar_current_situation(self):
        item = self.situation_list.currentItem()
        if item is not None:
            identity = str(item.data(Qt.ItemDataRole.UserRole) or "")
            self._set_situation_star(identity, False)

    def _refresh_saved_situations(self):
        old = self.situation_list.currentItem()
        selected = str(old.data(Qt.ItemDataRole.UserRole) or "") if old is not None else ""
        restored = False
        blocked = self.situation_list.blockSignals(True)
        try:
            self.situation_list.clear()
            for saved in self.controller.store.list_situations():
                identity = str(saved.get("event_id") or saved.get("id") or "")
                event = saved.get("event") or {}
                title = saved.get("title") or event.get("title") or "Saved situation"
                text = f"★ {title}\n{event.get('region') or 'Global'} · {event.get('verification', 'unverified')}"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, identity)
                self.situation_list.addItem(item)
                if identity == selected:
                    self.situation_list.setCurrentItem(item)
                    restored = True
        finally:
            self.situation_list.blockSignals(blocked)
        self._sync_situation_remove()
        if not self.situation_list.count():
            self.situation_browser.setPlainText("No starred situations. Select an event in Monitor and choose ☆ Star, or right-click a feed item and choose Star situation.")
        elif not restored:
            self.situation_browser.setPlainText("Select a starred situation to inspect its evidence and changes. Unstar removes only the saved bookmark, not the underlying event.")
