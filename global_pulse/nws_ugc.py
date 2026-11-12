"""Resolve complete NWS UGC codes to canonical zone references, not coordinates.

Only explicit publisher geocode fields are interpreted. A matching zone Feature
must still pass the unchanged NWS resolver's HTTP/identity/geometry checks.
Fire/public zone numbering can overlap, so unknown land-zone event types are
left unresolved. No requests, caches, files or geocoding service in this helper.
"""
from __future__ import annotations
import re

MAX_UGC_REFS = 128
MARINE_PREFIXES = frozenset('AM AN GM LC LE LH LM LO LS PH PK PM PS PZ SL'.split())
LAND_PREFIXES = frozenset(('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI '
    'MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY '
    'AS GU MP PR VI FM MH PW').split())
FIRE_EVENTS = frozenset({'Red Flag Warning', 'Fire Weather Watch'})
# Deliberately explicit: do not guess a land-zone family from a news headline.
PUBLIC_EVENTS = frozenset({
    'Flood Warning', 'Flood Watch', 'Flood Advisory', 'Flood Statement',
    'Flash Flood Warning', 'Flash Flood Watch', 'Flash Flood Statement',
    'Coastal Flood Warning', 'Coastal Flood Watch', 'Coastal Flood Advisory', 'Coastal Flood Statement',
    'Lakeshore Flood Warning', 'Lakeshore Flood Watch', 'Lakeshore Flood Advisory', 'Lakeshore Flood Statement',
    'Winter Storm Warning', 'Winter Storm Watch', 'Winter Weather Advisory',
    'Blizzard Warning', 'Blizzard Watch', 'Ice Storm Warning', 'Snow Squall Warning',
    'High Wind Warning', 'High Wind Watch', 'Wind Advisory', 'Extreme Wind Warning',
    'Dense Fog Advisory', 'Freezing Fog Advisory', 'Dense Smoke Advisory',
    'Extreme Cold Warning', 'Extreme Cold Watch', 'Cold Weather Advisory',
    'Wind Chill Warning', 'Wind Chill Watch', 'Wind Chill Advisory',
    'Excessive Heat Warning', 'Excessive Heat Watch', 'Heat Advisory',
    'Extreme Heat Warning', 'Extreme Heat Watch',
    'Freeze Warning', 'Freeze Watch', 'Hard Freeze Warning', 'Hard Freeze Watch', 'Frost Advisory',
    'High Surf Warning', 'High Surf Advisory', 'Rip Current Statement', 'Beach Hazards Statement',
    'Dust Storm Warning', 'Blowing Dust Warning', 'Blowing Dust Advisory', 'Ashfall Advisory',
    'Hurricane Warning', 'Hurricane Watch', 'Tropical Storm Warning', 'Tropical Storm Watch',
    'Storm Surge Warning', 'Storm Surge Watch', 'Tsunami Warning', 'Tsunami Watch', 'Tsunami Advisory',
    'Severe Thunderstorm Warning', 'Severe Thunderstorm Watch', 'Tornado Warning', 'Tornado Watch',
})
_CODE = re.compile(r'([A-Z]{2})([CZ])([0-9]{3})', flags=re.ASCII)


def ugc_zone_urls(geocodes: object, event: object = '') -> list[str]:
    """All-or-none conversion of bounded, unambiguous complete UGC references.

    C is county, Z with a documented marine prefix is marine. Land Z needs a
    known official event family. 000/all, compressed UGC strings/ranges, unknown
    prefixes, invalid neighbors and oversized inputs do not become partial
    implicit authority. Valid existing affectedZones URLs take precedence in
    the caller and never pass through this conversion.
    """
    if not isinstance(geocodes, dict):
        return []
    values = geocodes.get('UGC')
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_UGC_REFS:
        return []
    name = event if isinstance(event, str) and len(event) <= 120 else ''
    result = []
    for value in values:
        if not isinstance(value, str) or len(value) != 6:
            return []
        match = _CODE.fullmatch(value)
        if match is None or match[3] == '000':
            return []
        prefix, kind = match[1], match[2]
        if prefix in MARINE_PREFIXES and kind == 'Z':
            family = 'marine'
        elif prefix in LAND_PREFIXES and kind == 'C':
            family = 'county'
        elif prefix in LAND_PREFIXES and kind == 'Z':
            if name in FIRE_EVENTS:
                family = 'fire'
            elif name in PUBLIC_EVENTS:
                family = 'forecast'
            else:
                return []
        else:
            return []
        url = f'https://api.weather.gov/zones/{family}/{value}'
        if url not in result:
            result.append(url)
    return result
