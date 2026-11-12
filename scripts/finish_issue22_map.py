"""Correct the map evidence projection found by the first executed integration run.

Run only immediately after the exact-base guarded apply_issue22_map script.
No cached source record or historical revision is rewritten by this correction.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Non-unique correction anchor: ' + old[:100])
    return text.replace(old, new, 1)


def main():
    path = ROOT / 'global_pulse/core.py'
    text = path.read_text(encoding='utf-8')
    text = replace(text,
        '    def _get_event_unlocked(self, event_id: str, at: str | None = None) -> dict | None:',
        '    def _get_event_unlocked(self, event_id: str, at: str | None = None, *, map_projection: bool = False) -> dict | None:')
    text = replace(text,
        '        _, event["reports"] = _evidence_reports(reports, event["updated_at"])\n        event["timeline"] = []',
        '        _, event["reports"] = _evidence_reports(reports, event["updated_at"])\n        if map_projection:\n            # Map evidence needs the actual source versions, not expensive timelines.\n            return event\n        event["timeline"] = []')
    text = replace(text,
        '                events = [self._get_event_unlocked(row[0], before) for row in rows]',
        '                events = [self._get_event_unlocked(row[0], before, map_projection=map_evidence) for row in rows]')
    text = replace(text,
        '            sql = ("SELECT body FROM events" if map_view else "SELECT id FROM events")',
        '            sql = ("SELECT body FROM events" if map_view and not map_evidence else "SELECT id FROM events")')
    text = replace(text,
        '            result = [(json.loads(row[0]) if map_view else self._get_event_unlocked(row[0]))',
        '            result = [(json.loads(row[0]) if map_view and not map_evidence else self._get_event_unlocked(row[0], map_projection=map_evidence))')
    compile(text, str(path), 'exec')
    path.write_text(text, encoding='utf-8', newline='\n')

    path = ROOT / 'global_pulse/map_evidence.py'
    text = path.read_text(encoding='utf-8')
    text = replace(text,
        '    if not isinstance(value, dict) or value.get("type") not in {"Polygon", "MultiPolygon"}:',
        '    if not isinstance(value, dict) or not isinstance(value.get("type"), str) or value.get("type") not in {"Polygon", "MultiPolygon"}:')
    text = replace(text,
        '    result = {"country_basis": basis if basis in COUNTRY_BASES else "unresolved"}',
        '    result = {"country_basis": basis if isinstance(basis, str) and basis in COUNTRY_BASES else "unresolved"}')
    text = replace(text,
        '    if raw.get("area_status") in {"invalid_or_unsupported_geometry", "zone_geometry_not_resolved", "no_provider_geometry"}:',
        '    if isinstance(raw.get("area_status"), str) and raw["area_status"] in {"invalid_or_unsupported_geometry", "zone_geometry_not_resolved", "no_provider_geometry"}:')
    text = replace(text,
        '        explicit = basis in {"provider_incident", "explicit_record"}',
        '        explicit = isinstance(basis, str) and basis in {"provider_incident", "explicit_record"}')
    helper = '''@lru_cache(maxsize=1)
def _country_names():
    try:
        data = json.loads((Path(__file__).with_name("resources") / "world_countries.geojson").read_text(encoding="utf-8"))
        return {str(f.get("properties", {}).get("name", "")).casefold() for f in data["features"]}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _compact_country(event):
    if event.get("country_basis") == "publisher_coverage":
        return ""
    country = str(event.get("country") or "").strip()
    if country:
        return country
    region = str(event.get("region") or "").strip()
    return region if region.casefold() in _country_names() else ""


'''
    text = replace(text, 'def incident_country(event):\n', helper + 'def incident_country(event):\n')
    text = replace(text, '''        if event.get("country_basis") == "publisher_coverage":
            return ""
        return str(event.get("country") or "").strip()
    if all''', '''        return _compact_country(event)
    if all''')
    text = replace(text,
        '        return "" if event.get("country_basis") == "publisher_coverage" else str(event.get("country") or "").strip()',
        '        return _compact_country(event)')
    compile(text, str(path), 'exec')
    path.write_text(text, encoding='utf-8', newline='\n')
    print('GP_MAP_PROJECTION_FIX: actual report versions retained; historical timelines excluded from map projection')


if __name__ == '__main__':
    main()
