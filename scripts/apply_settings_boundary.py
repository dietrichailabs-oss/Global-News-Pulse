"""Integrate only the exact reviewed Controller baseline; reject other edits."""
from pathlib import Path
import ast
import hashlib
import subprocess

BASE = '11a779c53ff70b6ea25db7501dba3667d8164ed0'
path = Path('global_pulse/controller.py')
raw = subprocess.check_output(['git', 'show', BASE + ':' + path.as_posix()])
assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == '50356c18f037487eee64271e419bc486544d21fc'
text = raw.decode('utf-8')
start = text.index('def in_quiet_hours(settings, now=None):')
end = text.index('\n\nclass Controller', start)
text = text[:start] + '''def in_quiet_hours(settings, now=None):
    from .settings_boundary import quiet_hours_active
    return quiet_hours_active(settings, now)
''' + text[end:]

def replace(old, new):
    global text
    assert text.count(old) == 1, ('Unexpected integration target', old)
    text = text.replace(old, new)

replace('self.catalog = load_catalog() + self.store.get_setting("user_feeds", [])', '''bundled = load_catalog()
        self._bundled_source_ids = {source["id"] for source in bundled}
        self.catalog = bundled + self.get_setting("user_feeds", [])''')
replace('''    def get_setting(self, key, default=None):
        return self.store.get_setting(key, default)''', '''    def get_setting(self, key, default=None):
        from .settings_boundary import monitoring_interval, retention_days, user_feeds
        value = self.store.get_setting(key, default)
        if key == "interval":
            return monitoring_interval(value)
        if key == "retention_days":
            return retention_days(value)
        if key == "user_feeds":
            return user_feeds(value, self._bundled_source_ids)
        return value''')
replace('feeds = self.store.get_setting("user_feeds", [])', 'feeds = self.get_setting("user_feeds", [])')
replace('feeds = list(self.store.get_setting("user_feeds", []))', 'feeds = self.get_setting("user_feeds", [])')
replace('''        feeds.append(source)
        self.store.set_setting("user_feeds", feeds)''', '''        from .settings_boundary import MAX_TOTAL_SOURCES
        if len(self.catalog) >= MAX_TOTAL_SOURCES:
            raise ValueError("Source catalog is full")
        feeds.append(source)
        self.store.set_setting("user_feeds", feeds)''')
old_tree, new_tree = ast.parse(raw), ast.parse(text)
old_class = next(n for n in old_tree.body if isinstance(n, ast.ClassDef) and n.name == 'Controller')
new_class = next(n for n in new_tree.body if isinstance(n, ast.ClassDef) and n.name == 'Controller')
allowed = {'__init__', 'get_setting', 'add_user_feed', 'remove_user_feed'}
for before, after in zip(old_class.body, new_class.body, strict=True):
    if not isinstance(before, ast.FunctionDef) or before.name not in allowed:
        assert ast.dump(before) == ast.dump(after), 'Unrelated Controller method changed'
expected = text.encode('utf-8')
assert path.read_bytes() in (raw, expected), 'Controller has unrelated changes; reconcile rather than overwrite'
path.write_bytes(expected)
print('GP_SETTINGS_INTEGRATED_NO_PROVIDER_ADMISSION')
