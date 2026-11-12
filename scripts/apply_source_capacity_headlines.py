"""One-time exact-baseline integration; resulting product is committed before tests."""
from __future__ import annotations
import ast
from pathlib import Path
import subprocess

BASE = 'c8ea0b99def1465d301832f1e659cf883dcfec6c'
LANG = '386dc5f9b2375016e1449a84ac237a223275bb5b'


def original(path):
    raw = subprocess.check_output(['git', 'show', BASE + ':' + path])
    if Path(path).read_bytes() != raw:
        raise RuntimeError('Exact baseline mismatch: ' + path)
    return raw.decode('utf-8')


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Integration anchor is not unique: ' + repr(old[:100]))
    return text.replace(old, new, 1)


def save(path, text):
    if path.endswith('.py'):
        ast.parse(text, filename=path)
    Path(path).write_text(text, encoding='utf-8', newline='\n')


p = 'global_pulse/settings_boundary.py'
s = original(p)
s = replace(s, 'MAX_TOTAL_SOURCES = 200  # The existing catalog bound; expansion is separate.', 'from .capacity_limits import MAX_TOTAL_SOURCES')
save(p, s)
p = 'global_pulse/sources.py'
s = original(p)
s = replace(s, 'from .map_evidence import nws_map_fields', 'from .map_evidence import nws_map_fields\nfrom .capacity_limits import MAX_TOTAL_SOURCES')
if s.count('len(result) > 200') != 1 or s.count('len(catalog) > 200') != 1:
    raise RuntimeError('Unexpected source capacity boundaries')
s = s.replace('len(result) > 200', 'len(result) > MAX_TOTAL_SOURCES')
s = s.replace('len(catalog) > 200', 'len(catalog) > MAX_TOTAL_SOURCES')
s = replace(s, 'raise ValueError("At most 200 sources are allowed")', 'raise ValueError(f"At most {MAX_TOTAL_SOURCES} sources are allowed")')
save(p, s)
p = 'global_pulse/core.py'
s = original(p)
s = replace(s, '        if len(encoded) > 250_000:\n            raise ValueError("Setting is too large")', '        from .capacity_limits import MAX_USER_FEED_SETTING_BYTES\n        limit = MAX_USER_FEED_SETTING_BYTES if key == "user_feeds" else 250_000\n        if len(encoded.encode("utf-8")) > limit:\n            raise ValueError("Setting is too large")')
save(p, s)
p = 'global_pulse/controller.py'
s = original(p)
s = replace(s, '    translation_ready = Signal(str, str)', '    translation_ready = Signal(str, str)\n    feed_translation_changed = Signal()')
s = replace(s, '        self.translator = Translator(self.data_dir)', '        self.translator = Translator(self.data_dir)\n        from .headline_translation import HeadlineTranslations\n        self._headlines = HeadlineTranslations(self.translator, self._workers,\n            lambda: self.get_setting("english_headlines", True), self)\n        self._headlines.changed.connect(self.feed_translation_changed.emit)')
s = replace(s, '        if key in {"countries", "categories", "muted_sources", "enabled_sources"}:\n            if not isinstance(value, list) or len(value) > 300:', '        if key == "english_headlines" and type(value) is not bool:\n            raise ValueError("English headlines requires a boolean")\n        if key in {"countries", "categories", "muted_sources", "enabled_sources"}:\n            from .capacity_limits import MAX_TOTAL_SOURCES\n            limit = MAX_TOTAL_SOURCES if key in {"muted_sources", "enabled_sources"} else 300\n            if not isinstance(value, list) or len(value) > limit:')
s = replace(s, '        self.store.set_setting(key, value)\n        if key == "interval":', '        self.store.set_setting(key, value)\n        if key == "english_headlines" and not value:\n            self._headlines.cancel_pending()\n        if key == "interval":')
s = replace(s, '    def events(self, **filters):', '    def headline_view(self, event):\n        return self._headlines.view(event)\n\n    def events(self, **filters):')
s = replace(s, '    def _translation_complete(self, rid, language, text, error):\n        if rid in self._model_jobs:', '    def _translation_complete(self, rid, language, text, error):\n        if self._headlines.complete(rid, language, text, error):\n            return\n        if rid in self._model_jobs:')
s = replace(s, '        self._workers.close()\n        self._translation_pending.clear()', '        self._headlines.close()\n        self._workers.close()\n        self._translation_pending.clear()')
save(p, s)
p = 'global_pulse/ui.py'
s = original(p)
s = replace(s, 'str(e.get("title", "Untitled event"))[:180]', 'str(e.get("_display_title", e.get("title", "Untitled event")))[:180]')
s = replace(s, 'painter.fontMetrics().elidedText(report_time(e),Qt.TextElideMode.ElideRight,rect.width())', 'painter.fontMetrics().elidedText(str(e.get("_translation_label", "")) + " · " + report_time(e),Qt.TextElideMode.ElideRight,rect.width())')
s = replace(s, '        controller.translation_ready.connect(self._translation_done)', '        controller.translation_ready.connect(self._translation_done)\n        if hasattr(controller, "feed_translation_changed"):\n            controller.feed_translation_changed.connect(self._refresh_translated_headlines)')
s = replace(s, '        feed=Panel("NEWS & EVENT FEED");self.feed_count=label("0","Count");feed.heading.addWidget(self.feed_count)', '        feed=Panel("NEWS & EVENT FEED");self.feed_count=label("0","Count");feed.heading.addWidget(self.feed_count)\n        self.english_headlines=QCheckBox("English headlines")\n        self.english_headlines.setToolTip("Translate displayed headlines locally using installed models. No automatic model downloads. Original source evidence is preserved.")\n        self.english_headlines.setChecked(self.controller.get_setting("english_headlines",True) is True)\n        self.english_headlines.toggled.connect(lambda value:self.controller.set_setting("english_headlines",value))\n        feed.heading.addWidget(self.english_headlines)')
s = replace(s, '            item=QListWidgetItem(str(e.get("title","Untitled event")));item.setData(Qt.ItemDataRole.UserRole,e);item.setToolTip(str(e.get("recap","")));self.feed_list.addItem(item)', '            view=self.controller.headline_view(e) if hasattr(self.controller,"headline_view") else {"title":str(e.get("title","Untitled event")),"original":str(e.get("title","")),"label":"Original headline"}\n            e=dict(e,_display_title=view["title"],_translation_label=view["label"])\n            item=QListWidgetItem(view["title"]);item.setData(Qt.ItemDataRole.UserRole,e);item.setToolTip(view["label"]+"\\nOriginal: "+view["original"]+"\\n"+str(e.get("recap","")));self.feed_list.addItem(item)')
s = replace(s, '    def _render_empty_brief(self):', '    def _refresh_translated_headlines(self):\n        # Presentation only: do not refetch sources or recompute the world map.\n        self._populate_feed()\n        if self._selected_id:\n            event=self._selected_event()\n            if event:self._render_event(event)\n\n    def _render_empty_brief(self):')
s = replace(s, '    def _render_event(self,event):\n        severity=', '    def _render_event(self,event):\n        view=self.controller.headline_view(event) if hasattr(self.controller,"headline_view") else {"title":str(event.get("title","")),"original":str(event.get("title","")),"label":"Original headline"}\n        severity=')
s = replace(s, "{esc(event.get('title'))}</h3>", "{esc(view['title'])}</h3>")
s = replace(s, '        if event.get("synthetic"):parts.append', '        parts.append(f"<p>{esc(view[\'label\'])}</p>")\n        if view["title"] != view["original"]:parts.append(f"<p><b>Original headline:</b> {esc(view[\'original\'])}</p>")\n        if event.get("synthetic"):parts.append')
save(p, s)
# Copy exactly the already reviewed language-routing/model-layout candidate.
# No model files are downloaded; pinned catalog metadata stays separate.
for p in ('global_pulse/translation.py', 'global_pulse/language_codes.py', 'global_pulse/model_layout.py', 'global_pulse/resources/translation_models.json'):
    data = subprocess.check_output(['git','show',LANG+':'+p])
    if p.endswith('.py'):ast.parse(data.decode('utf-8'),filename=p)
    Path(p).write_bytes(data)
print('GP_CAPACITY_512_AND_LOCAL_HEADLINES_INTEGRATED_NO_NEW_PROVIDER_ACTIVATION')
