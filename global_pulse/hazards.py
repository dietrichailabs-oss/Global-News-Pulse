"""Finite natural-hazard display taxonomy; no geocoding, collection or impact inference."""
from __future__ import annotations
import re

HAZARD_LABELS = {
    "earthquake": "Earthquakes",
    "cyclone": "Hurricanes / tropical cyclones",
    "tornado": "Tornadoes",
    "flood": "Floods",
    "tsunami": "Tsunamis",
    "storm": "Severe storms / wind",
    "wildfire": "Wildfires",
    "volcano": "Volcanoes",
    "winter": "Winter weather",
    "heat_drought": "Heat / drought",
    "landslide": "Landslides / avalanches",
    "other": "Other disaster reports",
}
HAZARD_KEYS = tuple(HAZARD_LABELS)
GDACS_TYPES = {"EQ":"earthquake","TC":"cyclone","FL":"flood","TS":"tsunami",
               "WF":"wildfire","VO":"volcano","DR":"heat_drought"}
EONET_TYPES = {"earthquakes":"earthquake","severeStorms":"storm","floods":"flood",
               "wildfires":"wildfire","volcanoes":"volcano","snow":"winter",
               "tempExtremes":"heat_drought","drought":"heat_drought","landslides":"landslide"}
_PATTERNS = tuple((kind,re.compile(pattern,re.I)) for kind,pattern in (
    ("earthquake",r"\b(?:earthquakes?|aftershocks?|seismic swarm|temblor)\b"),
    ("cyclone",r"\b(?:hurricanes?|typhoons?|tropical (?:cyclones?|storms?|depressions?)|post-tropical cyclones?)\b"),
    ("tornado",r"\b(?:tornado(?:es)?|waterspouts?)\b"),
    ("flood",r"\b(?:flood(?:s|ing)?|storm surge|inundation)\b"),
    ("tsunami",r"\btsunamis?\b"),
    ("wildfire",r"\b(?:wildfires?|brush fires?|forest fires?|bushfires?|fire weather|red flag warning)\b"),
    ("volcano",r"\b(?:volcan(?:o|oes|ic)|lava flow|ashfall)\b"),
    ("winter",r"\b(?:blizzards?|snow(?:storm|fall)?|ice storm|freezing rain|winter (?:storm|weather)|extreme cold|wind chill|frost|freeze)\b"),
    ("heat_drought",r"\b(?:droughts?|heatwaves?|heat waves?|extreme heat|excessive heat|heat advisory)\b"),
    ("landslide",r"\b(?:landslides?|mudslides?|debris flows?|avalanches?)\b"),
    ("storm",r"\b(?:thunderstorms?|severe storms?|high winds?|gales?|dust storms?|hailstorms?|hail|wind advisory|squall|lightning)\b"),
))
_CATEGORIES = {"disaster","natural disaster","weather","hazards"}
_SOURCES = {"usgs","eonet","nws","gdacs","nhc_atlantic_outlook",
            "nhc_east_pacific_outlook","jma_weather_updates","jma_eqvol_updates"}

def canonical_hazard_types(value):
    if not isinstance(value,(list,tuple,set,frozenset)):
        return ()
    values={item for item in value if isinstance(item,str)}
    return tuple(kind for kind in HAZARD_KEYS if kind in values)

def text_hazard_types(title):
    if not isinstance(title,str):
        return ()
    matches=[kind for kind,pattern in _PATTERNS if pattern.search(title[:1000])]
    if "cyclone" in matches and "storm" in matches:
        matches.remove("storm")
    return canonical_hazard_types(matches)

def report_hazard_types(report):
    if not isinstance(report,dict):
        return ()
    if "hazard_types" in report:
        return canonical_hazard_types(report["hazard_types"])
    source=str(report.get("source_id") or "")
    category=str(report.get("category") or "").strip().casefold()
    if category not in _CATEGORIES and source not in _SOURCES:
        return ()
    if source=="gdacs":
        parts=str(report.get("event_key") or "").split(":")
        if len(parts)>2 and parts[0]=="gdacs" and parts[1].upper() in GDACS_TYPES:
            return (GDACS_TYPES[parts[1].upper()],)
    title=str(report.get("title") or "")
    if source=="usgs":
        if re.search(r"\b(?:explosion|blast|quarry|mine collapse)\b",title,re.I):
            return ("other",)
        if re.match(r"^\s*M\s*[-+]?\d+(?:\.\d+)?\b",title,re.I):
            return ("earthquake",)
    return text_hazard_types(title) or ("other",)

def event_hazard_types(event):
    reports=event.get("reports")
    if isinstance(reports,list) and reports:
        active=[r for r in reports if isinstance(r,dict) and not r.get("future_dated")
                and not r.get("expired") and r.get("evidence_status","active")=="active"]
        return canonical_hazard_types([k for r in active for k in report_hazard_types(r)])
    return report_hazard_types(event)

def area_hazard_types(event,area):
    for report in event.get("reports",[]) or ():
        if (isinstance(report,dict) and area.get("report_id")
                and report.get("id")==area["report_id"]
                and report.get("source_id")==area.get("source_id")):
            return report_hazard_types(report)
    return event_hazard_types(event)

def hazard_visible(types,disabled):
    return not types or any(kind not in disabled for kind in types)
