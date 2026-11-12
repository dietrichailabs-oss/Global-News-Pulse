"""One-time exact-baseline source integration; not a runtime monkey patch."""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    'global_pulse/core.py': '8fc49d47787ac92dbaad29fa11c89f36f74c23cc',
    'global_pulse/controller.py': '73b4487b17e771b94af938dc62ea96b2f4c35617',
    'global_pulse/ui.py': '4a5e7a9283e0821366736ccc85a6a7910b91d215',
}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected one exact source anchor')
    return text.replace(old, new, 1)


def replace_method(text, name, replacement):
    tree = ast.parse(text)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow')
    node = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    lines = text.splitlines(keepends=True)
    return ''.join(lines[:node.lineno-1]) + replacement + ''.join(lines[node.end_lineno:])


def main():
    original = {}
    for filename, expected in PINS.items():
        data = (ROOT / filename).read_bytes()
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if digest != expected:
            raise ValueError('Baseline drift: ' + filename)
        original[filename] = data.decode('utf-8')
    result = dict(original)
    methods = '''    def saved_situation_ids(self) -> set[str]:
        """Read bookmark identities without loading every event timeline."""
        with self._lock:
            return {row[0] for row in self._conn.execute("SELECT event_id FROM situations")}

    def situation_state(self, event_id: str) -> dict | None:
        """Canonical current identity and persisted bookmark state, or missing."""
        with self._lock:
            identity = canonical_event(self._conn, str(event_id))
            if not self._conn.execute("SELECT 1 FROM events WHERE id=?", (identity,)).fetchone():
                return None
            saved = bool(self._conn.execute("SELECT 1 FROM situations WHERE event_id=?", (identity,)).fetchone())
            return {"event_id": identity, "saved": saved}

    def set_situation_saved(self, event_id: str, saved: bool) -> dict:
        """Set explicit state transactionally; repeated delivery is idempotent.

        An existing custom title, save date and last-visited revision survive
        repeated saves. Unstar removes only the bookmark, never source evidence.
        """
        if not isinstance(saved, bool):
            raise ValueError("Saved state must be boolean")
        with self._lock, self._conn:
            identity = canonical_event(self._conn, str(event_id))
            row = self._conn.execute("SELECT body FROM events WHERE id=?", (identity,)).fetchone()
            if not row:
                raise ValueError("Event does not exist")
            if saved:
                title = plain_text(json.loads(row[0]).get("title", "Saved situation"), 500)
                self._conn.execute(
                    "INSERT INTO situations(event_id,title,saved_at,last_visited_revision) VALUES(?,?,?,0) "
                    "ON CONFLICT(event_id) DO NOTHING", (identity, title, utcnow()))
            else:
                self._conn.execute("DELETE FROM situations WHERE event_id=?", (identity,))
            return {"event_id": identity, "saved": saved}

'''
    result['global_pulse/core.py'] = replace_once(result['global_pulse/core.py'], '    def save_situation(self, event_id: str, title: str = "") -> dict:\n', methods + '    def save_situation(self, event_id: str, title: str = "") -> dict:\n')
    controller_method = '''    def set_situation_saved(self, identifier, saved):
        if self._closed:
            raise ValueError("Archive is closed")
        state = self.store.set_situation_saved(identifier, saved)
        self.data_changed.emit()
        return state

'''
    result['global_pulse/controller.py'] = replace_once(result['global_pulse/controller.py'], '    def save_situation(self, identifier):\n', controller_method + '    def save_situation(self, identifier):\n')
    ui = result['global_pulse/ui.py']
    ui = replace_once(ui, 'from .map_widget import WorldMap\n', 'from .map_widget import WorldMap\nfrom .situation_actions import SituationActions\n')
    ui = replace_once(ui, 'class MainWindow(QMainWindow):', 'class MainWindow(SituationActions, QMainWindow):')
    ui = replace_once(ui, 'category = str(e.get("category", "News")).upper()', 'category = ("★ SAVED / " if e.get("_situation_starred") else "") + str(e.get("category", "News")).upper()')
    ui = replace_once(ui, '        feed.layout.addWidget(self.feed_list,1)\n', '        self.feed_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)\n        self.feed_list.customContextMenuRequested.connect(self._show_feed_situation_menu)\n        feed.layout.addWidget(self.feed_list,1)\n')
    ui = replace_once(ui, 'self.save_button=button("☆ Save",self._save_selected,"Save the selected event as a Situation Room");intel.heading.addWidget(self.save_button)', 'self.save_button=button("☆ Star",self._toggle_selected_situation,"Star the selected event in Situations",checkable=True);intel.heading.addWidget(self.save_button)\n        self.save_button.setObjectName("situation_star")')
    ui = replace_once(ui, '        panel=Panel("SITUATION ROOMS")\n', '        panel=Panel("SITUATION ROOMS")\n        self.unstar_button=button("☆ Unstar selected",self._unstar_current_situation,"Remove the selected situation bookmark, keeping its evidence")\n        self.unstar_button.setEnabled(False);panel.heading.addWidget(self.unstar_button)\n')
    ui = replace_once(ui, '        self.situation_list.itemClicked.connect(self._visit_situation)\n', '        self.situation_list.itemClicked.connect(self._visit_situation)\n        self.situation_list.currentItemChanged.connect(self._sync_situation_remove)\n')
    ui = replace_once(ui, '        events=list(self._events)\n', '        events=list(self._events)\n        saved_ids=self.controller.store.saved_situation_ids()\n')
    ui = replace_once(ui, '            item=QListWidgetItem(str(e.get("title","Untitled event")));', '            e=dict(e,_situation_starred=str(e.get("id","")) in saved_ids)\n            item=QListWidgetItem(str(e.get("title","Untitled event")));')
    ui = replace_once(ui, '        for b in (self.save_button,self.original_button,self.translate_button):b.setEnabled(False)', '        for b in (self.save_button,self.original_button,self.translate_button):b.setEnabled(False)\n        self._sync_situation_star(None)')
    ui = replace_once(ui, 'self.save_button.setEnabled(True);self.original_button.setEnabled', 'self._sync_situation_star(event);self.original_button.setEnabled')
    ui = replace_method(ui, '_save_selected', '    def _save_selected(self):\n        if self._selected_id:\n            self._set_situation_star(self._selected_id, True)\n')
    ui = replace_method(ui, '_populate_situations', '    def _populate_situations(self):\n        self._refresh_saved_situations()\n')
    result['global_pulse/ui.py'] = ui
    for name, text in result.items():
        ast.parse(text, filename=name)
    for name, text in result.items():
        (ROOT/name).write_bytes(text.encode('utf-8'))
        print('GP_STAR_PATCH ' + name, flush=True)


if __name__ == '__main__':
    main()
