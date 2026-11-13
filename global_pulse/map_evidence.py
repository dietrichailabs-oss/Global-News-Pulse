"""Bounded map evidence. Country/area knowledge never manufactures a point.

Pure data helpers: no network, geocoding service, or owner archive access.
NWS bulletin expiry remains distinct from the provider's hazard end time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

MAX_AREA_POINTS = 16384  # Supports the observed 10,094-point NWS area; still bounded.
MAX_AREA_POLYGONS = 64
MAX_ZONE_REFS = 128
COUNTRY_BASES = {"provider_incident", "publisher_coverage", "explicit_record", "unresolved"}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _unwrap(ring, anchor=None):
    result = []
    for longitude, latitude in ring:
        x = float(longitude)
        if result:
            while x - result[-1][0] > 180:
                x -= 360
            while x - result[-1][0] < -180:
                x += 360
        result.append([x, float(latitude)])
    if max(p[0] for p in result) - min(p[0] for p in result) >= 360:
        raise ValueError("Area wraps around the globe")
    if result[0] != result[-1]:
        raise ValueError("Area ring has inconsistent dateline winding")
    if anchor is not None:
        center = sum(p[0] for p in result[:-1]) / (len(result) - 1)
        shift = round((anchor - center) / 360) * 360
        result = [[x + shift, y] for x, y in result]
    return result


def normalize_geometry(value):
    """Copy bounded 2D Polygon/MultiPolygon data; reject bad geometry, not news."""
    if not isinstance(value, dict) or not isinstance(value.get("type"), str) or value.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Expected Polygon or MultiPolygon")
    coordinates = value.get("coordinates")
    polygons = [coordinates] if value["type"] == "Polygon" else coordinates
    if not isinstance(polygons, list) or not 1 <= len(polygons) <= MAX_AREA_POLYGONS:
        raise ValueError("Invalid polygon count")
    result, count = [], 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not 1 <= len(polygon) <= 64:
            raise ValueError("Invalid area rings")
        rings = []
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("Area ring needs four positions")
            count += len(ring)
            if count > MAX_AREA_POINTS:
                raise ValueError("Area point budget exceeded")
            copied = []
            for position in ring:
                if not isinstance(position, (list, tuple)) or len(position) not in (2, 3):
                    raise ValueError("Invalid area position")
                x, y = position[:2]
                if not _number(x) or not _number(y) or not -180 <= x <= 180 or not -90 <= y <= 90:
                    raise ValueError("Invalid area coordinate")
                copied.append([float(x), float(y)])
            if copied[0] != copied[-1] or len({tuple(p) for p in copied[:-1]}) < 3:
                raise ValueError("Unclosed or degenerate area ring")
            unwrapped = _unwrap(copied)
            area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(unwrapped, unwrapped[1:]))
            if abs(area) < 1e-12:
                raise ValueError("Zero-area ring")
            rings.append(copied)
        result.append(rings)
    return {"type": value["type"], "coordinates": result[0] if value["type"] == "Polygon" else result}


def wrapped_polygons(value):
    """Unwrap across +/-180 and create edge copies, preserving polygon holes."""
    geometry = normalize_geometry(value)
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    for polygon in polygons:
        exterior = _unwrap(polygon[0])
        anchor = sum(p[0] for p in exterior[:-1]) / (len(exterior) - 1)
        rings = [exterior] + [_unwrap(ring, anchor) for ring in polygon[1:]]
        for shift in (-360, 0, 360):
            left = min(p[0] for p in exterior) + shift
            right = max(p[0] for p in exterior) + shift
            if right < -180 or left > 180:
                continue
            yield [[[x + shift, y] for x, y in ring] for ring in rings]


def _timestamp(value):
    if not isinstance(value, str) or not value or len(value) > 80:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return ""
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return ""


def valid_nws_zone(value):
    if not isinstance(value, str) or len(value) > 250 or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.netloc == "api.weather.gov"
                and not parsed.query and not parsed.fragment
                and bool(re.fullmatch(r"/zones/(?:forecast|county|fire|marine)/[A-Z]{2}[CZ][0-9]{3}", parsed.path)))
    except ValueError:
        return False


def normalize_map_fields(raw):
    basis = raw.get("country_basis")
    result = {"country_basis": basis if isinstance(basis, str) and basis in COUNTRY_BASES else "unresolved"}
    if isinstance(raw.get("area_status"), str) and raw["area_status"] in {"invalid_or_unsupported_geometry", "zone_geometry_not_resolved", "no_provider_geometry"}:
        result["area_status"] = raw["area_status"]
    if "area_geometry" in raw:
        try:
            result["area_geometry"] = normalize_geometry(raw["area_geometry"])
            result["area_status"] = "provider_geometry"
        except ValueError:
            result["area_status"] = "invalid_or_unsupported_geometry"
    zones = raw.get("affected_zones", [])
    if isinstance(zones, list):
        result["affected_zones"] = list(dict.fromkeys(z for z in zones[:MAX_ZONE_REFS] if valid_nws_zone(z)))
    else:
        result["affected_zones"] = []
    if "area_geometry" not in result and result["affected_zones"]:
        result["area_status"] = "zone_geometry_not_resolved"
    # Derived zone boundaries retain their exact NWS URLs and partial status.
    if raw.get("area_geometry_basis") == "nws_affected_zones" and "area_geometry" in result:
        supplied = raw.get("area_zone_sources", [])
        sources = []
        seen = set()
        if isinstance(supplied, list):
            for item in supplied[:MAX_ZONE_REFS]:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                stamp = _timestamp(item.get("retrieved_at"))
                if valid_nws_zone(url) and url in result["affected_zones"] and url not in seen and stamp:
                    seen.add(url)
                    sources.append({"url": url, "retrieved_at": stamp})
        if sources:
            result["area_geometry_basis"] = "nws_affected_zones"
            result["area_zone_sources"] = sources
            result["area_status"] = "provider_zone_geometry" if len(sources) == len(result["affected_zones"]) else "partial_provider_zones"
    geocodes = raw.get("area_geocodes", {})
    result["area_geocodes"] = {}
    if isinstance(geocodes, dict):
        for key, pattern in (("UGC", r"[A-Z]{2}[CZ][0-9]{3}"), ("SAME", r"[0-9]{6}")):
            values = geocodes.get(key, [])
            if isinstance(values, list):
                result["area_geocodes"][key] = list(dict.fromkeys(
                    v for v in values[:MAX_ZONE_REFS] if isinstance(v, str) and re.fullmatch(pattern, v)))
    if raw.get("area_zone_reference_basis") == "provider_ugc":
        from .nws_ugc import ugc_zone_urls
        reference_event = raw.get("area_zone_reference_event", "")
        expected = ugc_zone_urls(raw.get("area_geocodes"), reference_event)
        if expected and result["affected_zones"] == expected:
            result["area_zone_reference_basis"] = "provider_ugc"
            result["area_zone_reference_event"] = reference_event if isinstance(reference_event, str) and len(reference_event) <= 120 else ""
    for name in ("onset_at", "ends_at", "effective_at"):
        value = _timestamp(raw.get(name))
        if value:
            result[name] = value
    return result


def nws_map_fields(feature, properties):
    raw = {"country_basis": "provider_incident", "affected_zones": properties.get("affectedZones", []),
           "area_geocodes": properties.get("geocode", {}), "onset_at": properties.get("onset"),
           "ends_at": properties.get("ends"), "effective_at": properties.get("effective")}
    if feature.get("geometry") is not None:
        raw["area_geometry"] = feature["geometry"]
    result = normalize_map_fields(raw)
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
    result.setdefault("area_status", "no_provider_geometry")
    return result


@lru_cache(maxsize=1)
def _publisher_countries():
    """Legacy catalog defaults are coverage, not newly asserted incident locations."""
    path = Path(__file__).with_name("resources") / "sources.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))["sources"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {r["id"]: str(r.get("country", "")).casefold() for r in rows
            if r.get("country") and r.get("adapter") not in {"nws", "gdacs"}}


@lru_cache(maxsize=1)
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


def _country_identity(value):
    """Compare country names without confusing publisher scope for incidents.

    Matching a publisher hint is a negative provenance check only; this
    normalization must never create an incident country by itself.
    """
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    key = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return {
        "us": "unitedstatesofamerica",
        "usa": "unitedstatesofamerica",
        "unitedstates": "unitedstatesofamerica",
        "uk": "unitedkingdom",
        "gb": "unitedkingdom",
        "greatbritain": "unitedkingdom",
        "turkiye": "turkey",
        "czechrepublic": "czechia",
        "ivorycoast": "cotedivoire",
    }.get(key, key)


def _word_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


@lru_cache(maxsize=1)
def _country_text_phrases():
    """Return longest-first explicit country phrases from the bundled map.

    This is a conservative country-level evidence helper, not a geocoder.
    Publisher/source geography is intentionally excluded and no coordinates are
    manufactured. Short abbreviations such as US/UK are not accepted from text.
    """
    path = Path(__file__).with_name("resources") / "world_countries.geojson"
    values = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for feature in data.get("features", []):
            props = feature.get("properties") or {}
            name = str(props.get("name") or "").strip()
            phrase = _word_text(name)
            if name and len(phrase) >= 4:
                values[phrase] = name
    except (OSError, ValueError, TypeError):
        return ()
    aliases = {
        "united states": "United States of America",
        "united states of america": "United States of America",
        "czech republic": "Czechia",
        "turkiye": "Turkey",
        "ivory coast": "Côte d'Ivoire",
        "democratic republic of the congo": "Dem. Rep. Congo",
        "dr congo": "Dem. Rep. Congo",
        "republic of the congo": "Congo",
        "south sudan": "South Sudan",
    }
    values.update(aliases)
    return tuple(sorted(values.items(), key=lambda item: (-len(item[0]), item[0])))


def explicit_text_country(event):
    """Return exactly one country explicitly named in eligible source text.

    Longest phrases claim their spans first, preventing South Sudan from also
    matching Sudan. Separate non-overlapping country names remain ambiguous.
    """
    reports = event.get("reports")
    records = reports if isinstance(reports, list) and reports else [event]
    matches = {}
    for record in records:
        if not isinstance(record, dict) or record.get("future_dated"):
            continue
        if str(record.get("evidence_status", "active")).casefold() not in {"", "active"}:
            continue
        text = _word_text(" ".join(str(record.get(key, "") or "")
                                  for key in ("title", "summary", "recap")))
        if not text:
            continue
        padded = " " + text + " "
        claimed = []
        for phrase, country in _country_text_phrases():
            token = " " + phrase + " "
            cursor = 0
            while True:
                index = padded.find(token, cursor)
                if index < 0:
                    break
                start, end = index + 1, index + 1 + len(phrase)
                if not any(start < right and left < end for left, right in claimed):
                    claimed.append((start, end))
                    matches[_country_identity(country)] = country
                    if len(matches) > 1:
                        return ""
                cursor = index + 1
    return next(iter(matches.values())) if len(matches) == 1 else ""


def structured_incident_country(event):
    """Return country supported by structured record fields only."""
    reports = event.get("reports")
    if not isinstance(reports, list) or not reports:
        return _compact_country(event)
    if all(isinstance(r, dict) and "country" not in r and "source_id" not in r for r in reports):
        return _compact_country(event)
    countries = {}
    defaults = _publisher_countries()
    for report in reports:
        if not isinstance(report, dict) or report.get("future_dated"):
            continue
        if report.get("evidence_status", "active") not in {"", "active"}:
            continue
        country = str(report.get("country") or "").strip()
        basis = report.get("country_basis")
        if not country or basis == "publisher_coverage":
            continue
        explicit = isinstance(basis, str) and basis in {"provider_incident", "explicit_record"}
        source_id = report.get("source_id")
        source_default = defaults.get(source_id) if isinstance(source_id, str) else ""
        if not explicit and (
            (source_default and _country_identity(source_default) == _country_identity(country))
            or (report.get("source_country")
                and _country_identity(report["source_country"]) == _country_identity(country))
        ):
            # Publisher geography is coverage, not an attributable incident.
            # Format and country-name aliases must not bypass this exclusion.
            continue
        countries[_country_identity(country)] = country
    if len(countries) == 1:
        return next(iter(countries.values()))
    return ""


def incident_country(event):
    """Return one attributable country or unknown; never a publisher fallback.

    Structured provider/record geography wins. When it is absent, exactly one
    explicit country named in eligible source title/summary text may support a
    country-level map boundary. No point coordinates are manufactured.
    """
    structured = structured_incident_country(event)
    return structured or explicit_text_country(event)


def event_areas(reports):
    """Render only active authoritative geometries; originals remain in reports."""
    result = []
    for report in reports:
        if len(result) >= 32:
            break
        if not isinstance(report, dict) or not report.get("official") or report.get("future_dated"):
            continue
        if report.get("evidence_status", "active") != "active" or not report.get("area_geometry"):
            continue
        try:
            geometry = normalize_geometry(report["area_geometry"])
        except ValueError:
            continue
        zone_based = report.get("area_geometry_basis") == "nws_affected_zones"
        zone_note = ""
        if zone_based:
            done = len(report.get("area_zone_sources", []))
            total = len(report.get("affected_zones", []))
            zone_note = f" — NWS affected-zone boundaries: {done}/{total} zones"
            if report.get("area_zone_reference_basis") == "provider_ugc":
                zone_note += " (source UGC references)"
            if done < total:
                zone_note += " (partial area; other zones unresolved)"
        result.append({"geometry": geometry, "source_id": report.get("source_id", ""),
                       "report_id": report.get("id", ""), "url": report.get("url", ""),
                       "description": str(report.get("region", ""))[:350] + zone_note,
                       "basis": "provider_affected_zone_geometry" if zone_based else "provider_alert_geometry"})
    return result
