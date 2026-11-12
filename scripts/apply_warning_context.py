"""Guarded read-side map integration; lifecycle and alert rules stay unchanged."""
import ast
from pathlib import Path
import subprocess
BASE='e9eccee2f25d072cef9bc2463368f25180782368'

def original(name):
    raw=subprocess.check_output(['git','show',BASE+':'+name])
    if Path(name).read_bytes().replace(b'\r\n',b'\n')!=raw:raise RuntimeError('Exact baseline mismatch: '+name)
    return raw.decode('utf-8')

def edit(text,old,new):
    if text.count(old)!=1:raise RuntimeError('Nonunique context anchor: '+repr(old[:90]))
    return text.replace(old,new,1)

def write(name,text):
    ast.parse(text,filename=name);Path(name).write_text(text,encoding='utf-8',newline='\n')

name='global_pulse/core.py';text=original(name)
text=edit(text,'            # Map evidence needs the actual source versions, not expensive timelines.\n            return event', '            # Read-only area context does not promote pending updates into alerts.\n            from .warning_context import project_warning_context\n            return project_warning_context(event, _iso(at) if at else utcnow())')
text=edit(text,'filtered = [e for e in filtered if e.get("status") == "active" and\n', 'filtered = [e for e in filtered if (e.get("status") == "active" or map_evidence and e.get("map_history_incomplete") is True) and\n')
text=edit(text,'                where.append("json_extract(body,\'$.status\')=\'active\'")\n                if not map_evidence:', '                from .warning_context import PENDING_AREA_SQL\n                where.append("(json_extract(body,\'$.status\')=\'active\' OR " + PENDING_AREA_SQL + ")" if map_evidence else "json_extract(body,\'$.status\')=\'active\'")\n                if not map_evidence:')
text=edit(text,'            if map_view:\n                for item in result:', '            if map_evidence:\n                result = [e for e in result if e and (e.get("status") == "active" or e.get("map_history_incomplete") is True)]\n            if map_view:\n                for item in result:')
write(name,text)
name='global_pulse/map_area_layer.py';text=original(name)
text=edit(text,'            if event.get("status", "active") != "active" or event.get("future_dated"):\n                continue', '            context = event.get("status") == "pending" and event.get("map_history_incomplete") is True\n            if (event.get("status", "active") != "active" and not context) or event.get("future_dated"):\n                continue')
text=edit(text,'            for area in event.get("map_areas", [])[:32]:\n                try:', '            for area in event.get("map_areas", [])[:32]:\n                if context and (not isinstance(area, dict) or area.get("context_only") is not True):\n                    continue\n                try:')
text=edit(text,'            color = QColor(SEVERITY.get(event.get("severity"), SEVERITY["unassessed"]))', '            context = _area.get("context_only") is True\n            color = QColor(SEVERITY.get("unassessed" if context else event.get("severity"), SEVERITY["unassessed"]))')
text=edit(text,'            fill.setAlpha(55)', '            fill.setAlpha(20 if context else 55)')
text=edit(text,'            painter.setPen(pen)', '            if context:pen.setStyle(Qt.PenStyle.DashLine)\n            painter.setPen(pen)')
write(name,text)
name='global_pulse/map_widget.py';text=original(name)
text=edit(text,'        return f"{points} points · {areas} warning areas', '        incomplete = sum(area.get("context_only") is True for _path, _event, area in self.area_layer.visible())\n        if incomplete:suffix += f" · {incomplete} area(s) have incomplete warning history"\n        return f"{points} points · {areas} warning areas')
write(name,text)
print('GP_WARNING_CONTEXT_READ_SIDE_ONLY_NO_LIFECYCLE_OR_ALERT_PROMOTION')
