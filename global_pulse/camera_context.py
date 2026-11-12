"""Trusted public landscape snapshots; never infer a camera witnessed an event."""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path


def camera_catalog():
    return json.loads((Path(__file__).with_name('resources')/'context_cameras.json').read_text())['entries']


def _words(value):
    return ' '.join(re.findall(r'[a-z0-9]+', unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()))


def associated_cameras(event, catalog=None):
    """Match reviewed named areas, not a continent or invented incident position."""
    event=event or {}
    if event.get('status','active')!='active' or event.get('future_dated'):
        return []
    title=_words(event.get('title',''))
    region=_words(event.get('region',''))
    country=_words(event.get('country',''))
    # An organization's reused place name is not evidence of a landscape area.
    # Without richer verified geography, ambiguous names remain unmatched.
    if set((title+' '+region).split()) & {'university','college','campus','school','hotel','restaurant','company','corporation'}:
        return []
    entries=list(camera_catalog() if catalog is None else catalog)
    area_sets=[{_words(a) for a in item.get('area_keywords',[]) if len(_words(a))>=4}
               for item in entries]
    # Every explicitly named reviewed area must agree before choosing a camera.
    # Do not let a valid region hide a conflicting title (or choose whichever
    # area happens to appear first in the registry). Same-area aliases and
    # multiple cameras sharing those aliases remain valid.
    mentioned={area for areas in area_sets for area in areas
               if any(' '+area+' ' in ' '+field+' ' for field in (title,region))}
    if not mentioned:
        return []
    result=[]
    for item,areas in zip(entries,area_sets):
        if not mentioned.issubset(areas):
            continue
        countries={_words(value) for value in item.get('country_keywords',[])}
        if country and country not in countries:
            continue
        # Each supplied geographic component must agree with the reviewed area
        # or its known broader context. Phoenix/Kauai/etc. cannot be hidden by a
        # generic Arizona/Hawaii token, and unreviewed context fails closed.
        regions={_words(value) for value in item.get('region_keywords',[]) + item.get('area_keywords',[])}
        parts=[_words(value) for value in re.split(r'[,;/|]+',str(event.get('region',''))) if _words(value)]
        if any(part not in regions for part in parts):
            continue
        result.append(dict(item, association='Area context only — not evidence of this incident'))
    return result[:4]


def approved_camera(item):
    """Event/feed-supplied URLs cannot add remote endpoints to the trusted registry."""
    return next((entry for entry in camera_catalog()
                 if entry['id']==item.get('id') and entry['snapshot_url']==item.get('snapshot_url')),None)
