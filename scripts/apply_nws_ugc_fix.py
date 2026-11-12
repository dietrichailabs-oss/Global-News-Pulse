"""Integrate only the exact PR57 map helper; no resolver/security changes."""
import ast
import hashlib
from pathlib import Path
import subprocess

BASE='d58329ff5581ac9d267262bed89c6e3beeae29ba'
path=Path('global_pulse/map_evidence.py')
raw=subprocess.check_output(['git','show',BASE+':'+path.as_posix()])
if path.read_bytes().replace(b'\r\n',b'\n') != raw:
    raise RuntimeError('Exact PR57 baseline map helper mismatch')
s=raw.decode('utf-8')

def change(old,new):
    global s
    if s.count(old)!=1:raise RuntimeError('Nonunique integration anchor: '+repr(old[:90]))
    s=s.replace(old,new,1)

change('    for name in ("onset_at", "ends_at", "effective_at"):', '''    if raw.get("area_zone_reference_basis") == "provider_ugc":
        from .nws_ugc import ugc_zone_urls
        reference_event = raw.get("area_zone_reference_event", "")
        expected = ugc_zone_urls(raw.get("area_geocodes"), reference_event)
        if expected and result["affected_zones"] == expected:
            result["area_zone_reference_basis"] = "provider_ugc"
            result["area_zone_reference_event"] = reference_event if isinstance(reference_event, str) and len(reference_event) <= 120 else ""
    for name in ("onset_at", "ends_at", "effective_at"):''')
change('    result = normalize_map_fields(raw)\n    result.setdefault("area_status", "no_provider_geometry")', '''    result = normalize_map_fields(raw)
    # UGC is an explicit provider zone identity, not a headline-derived location.
    # Supplied valid polygons and affectedZones always win. Use raw geocodes so
    # invalid/truncated neighbors cannot silently turn into complete coverage.
    if (not result.get("area_geometry") and not result.get("affected_zones")
            and properties.get("status") == "Actual"
            and properties.get("messageType", "Alert") in {"Alert", "Update"}):
        from .nws_ugc import ugc_zone_urls
        references = ugc_zone_urls(properties.get("geocode"), properties.get("event"))
        if references:
            result["affected_zones"] = references
            result["area_status"] = "zone_geometry_not_resolved"
            result["area_zone_reference_basis"] = "provider_ugc"
            event = properties.get("event", "")
            result["area_zone_reference_event"] = event if isinstance(event, str) and len(event) <= 120 else ""
    result.setdefault("area_status", "no_provider_geometry")''')
change('            zone_note = f" — NWS affected-zone boundaries: {done}/{total} zones"', '''            zone_note = f" — NWS affected-zone boundaries: {done}/{total} zones"
            if report.get("area_zone_reference_basis") == "provider_ugc":
                zone_note += " (source UGC references)"''')
ast.parse(s)
path.write_text(s,encoding='utf-8',newline='\n')
# Existing independent case bytes are not rewritten, relabeled or weakened.
qa=Path('tests/test_eng_replay_nws_qa62.py').read_bytes().replace(b'\r\n',b'\n')
identity=hashlib.sha1(b'blob '+str(len(qa)).encode()+b'\0'+qa).hexdigest()
if identity!='302fa902676eac86b0ccdc4775457a8151844a65':raise RuntimeError('Original QA blob mismatch')
print('GP_UGC_INTEGRATED_ORIGINAL_QA_BLOB='+identity)
