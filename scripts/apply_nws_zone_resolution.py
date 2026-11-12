"""Exact-baseline NWS integration. Freeze the resulting application before tests."""
import ast
from pathlib import Path
import subprocess
BASE='1881bd1dd9fe285b75d84e3a12b5c2762cc47972'

def load(path):
    raw=subprocess.check_output(['git','show',BASE+':'+path])
    if Path(path).read_bytes()!=raw:raise RuntimeError('NWS integration baseline mismatch: '+path)
    return raw.decode('utf-8')

def change(text,old,new):
    if text.count(old)!=1:raise RuntimeError('Nonunique NWS integration anchor: '+repr(old[:100]))
    return text.replace(old,new,1)

def save(path,text):
    ast.parse(text,filename=path)
    Path(path).write_text(text,encoding='utf-8',newline='\n')

p='global_pulse/sources.py';s=load(p)
s=change(s,'    def __init__(self, source: dict, *, client_factory=None, now=None):','    def __init__(self, source: dict, *, client_factory=None, now=None, zone_resolver=None):')
s=change(s,'        self.now = now or utcnow\n','        self.now = now or utcnow\n        self.zone_resolver = zone_resolver\n')
s=change(s,'            if state.get(old_key) and len(str(state[old_key])) < 4096 and "\\n" not in str(state[old_key]):','            if (not (self.source.get("adapter") == "nws" and state.get("nws_zones_pending"))\n                    and state.get(old_key) and len(str(state[old_key])) < 4096 and "\\n" not in str(state[old_key])):')
s=change(s,'                        result["reports"] = parser(payload, self.source, current_iso)\n','                        result["reports"] = parser(payload, self.source, current_iso)\n                        if adapter == "nws":\n                            from .nws_zone_resolver import DEFAULT_RESOLVER\n                            resolver = self.zone_resolver or DEFAULT_RESOLVER\n                            result["reports"], zone_state = resolver.enrich(result["reports"], client_factory=self.client_factory)\n                            state["nws_zone_resolution"] = zone_state\n                            state["nws_zones_pending"] = bool(zone_state["unresolved_alerts"])\n')
save(p,s)
p='global_pulse/map_evidence.py';s=load(p)
s=change(s,'    geocodes = raw.get("area_geocodes", {})','    # Derived zone boundaries retain their exact NWS URLs and partial status.\n    if raw.get("area_geometry_basis") == "nws_affected_zones" and "area_geometry" in result:\n        supplied = raw.get("area_zone_sources", [])\n        sources = []\n        seen = set()\n        if isinstance(supplied, list):\n            for item in supplied[:MAX_ZONE_REFS]:\n                if not isinstance(item, dict):\n                    continue\n                url = item.get("url")\n                stamp = _timestamp(item.get("retrieved_at"))\n                if valid_nws_zone(url) and url in result["affected_zones"] and url not in seen and stamp:\n                    seen.add(url)\n                    sources.append({"url": url, "retrieved_at": stamp})\n        if sources:\n            result["area_geometry_basis"] = "nws_affected_zones"\n            result["area_zone_sources"] = sources\n            result["area_status"] = "provider_zone_geometry" if len(sources) == len(result["affected_zones"]) else "partial_provider_zones"\n    geocodes = raw.get("area_geocodes", {})')
s=change(s,'        result.append({"geometry": geometry, "source_id": report.get("source_id", ""),','        zone_based = report.get("area_geometry_basis") == "nws_affected_zones"\n        zone_note = ""\n        if zone_based:\n            done = len(report.get("area_zone_sources", []))\n            total = len(report.get("affected_zones", []))\n            zone_note = f" — NWS affected-zone boundaries: {done}/{total} zones"\n            if done < total:\n                zone_note += " (partial area; other zones unresolved)"\n        result.append({"geometry": geometry, "source_id": report.get("source_id", ""),')
s=change(s,'                       "description": str(report.get("region", ""))[:500],\n                       "basis": "provider_alert_geometry"})','                       "description": str(report.get("region", ""))[:350] + zone_note,\n                       "basis": "provider_affected_zone_geometry" if zone_based else "provider_alert_geometry"})')
save(p,s)
print('GP_NWS_ZONE_LOOKUP_INTEGRATED_WITH_PROVENANCE_AND_PARTIAL_STATUS')
