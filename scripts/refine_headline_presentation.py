"""Refine the integrated headline view before freezing it for regression.

Keep translation completion presentation-only, preserve reading position, and
migrate an Engineering test's old fixed capacity with both new edge checks.
Original independent QA files are not changed.
"""
import ast
from pathlib import Path
import subprocess


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Nonunique presentation anchor: ' + repr(old[:100]))
    return text.replace(old, new, 1)

p = Path('global_pulse/ui.py')
s = p.read_text(encoding='utf-8')
s = replace(s, '    def _render_event(self,event):', '    def _render_event(self,event, *, update_media=True):')
s = replace(s, '        if hasattr(self.media,"set_event"):self.media.set_event(dict(event,historical_view=bool(self._history_at)))', '        if update_media and hasattr(self.media,"set_event"):self.media.set_event(dict(event,historical_view=bool(self._history_at)))')
s = replace(s, '        # Presentation only: do not refetch sources or recompute the world map.\n        self._populate_feed()\n        if self._selected_id:\n            event=self._selected_event()\n            if event:self._render_event(event)', '        # Presentation only: no collection, map reload, or media retuning.\n        feed_scroll=self.feed_list.verticalScrollBar().value()\n        brief_scroll=self.intel_browser.verticalScrollBar().value()\n        self._populate_feed()\n        if self._selected_id:\n            event=self._selected_event()\n            if event:self._render_event(event,update_media=False)\n        self.feed_list.verticalScrollBar().setValue(feed_scroll)\n        self.intel_browser.verticalScrollBar().setValue(brief_scroll)')
s = replace(s, '        if not hasattr(self,"feed_list"):return\n        events=list(self._events)', '        if not hasattr(self,"feed_list"):return\n        if hasattr(self,"english_headlines"):\n            was_blocked=self.english_headlines.blockSignals(True)\n            self.english_headlines.setChecked(self.controller.get_setting("english_headlines",True) is True)\n            self.english_headlines.blockSignals(was_blocked)\n        events=list(self._events)')
s = replace(s, 'item.setToolTip(view["label"]+"\\nOriginal: "+view["original"]+"\\n"+str(e.get("recap","")))', 'item.setToolTip("<div style=\'white-space:pre-wrap\'>"+esc(view["label"]+"\\nOriginal: "+view["original"]+"\\n"+str(e.get("recap","")))+"</div>")')
ast.parse(s)
p.write_text(s,encoding='utf-8',newline='\n')
p = Path('tests/test_issue22_settings_boundary.py')
raw = subprocess.check_output(['git','show','c8ea0b99def1465d301832f1e659cf883dcfec6c:'+str(p)])
if p.read_bytes() != raw:
    raise RuntimeError('Settings Engineering baseline test mismatch')
s=raw.decode('utf-8')
s=replace(s, '    assert user_feeds([feed], [str(i) for i in range(200)]) == []', '    # The feature raises the explicit bound to512, not unlimited admission.\n    assert user_feeds([feed], [str(i) for i in range(511)]) == [feed]\n    assert user_feeds([feed], [str(i) for i in range(512)]) == []')
ast.parse(s)
p.write_text(s,encoding='utf-8',newline='\n')
print('GP_PRESENTATION_NO_MEDIA_RETUNE_AND_511_512_EDGE_ASSERTIONS')
