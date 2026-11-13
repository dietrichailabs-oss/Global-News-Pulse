"""Bounded public-source collection and checkpointed, independent scheduling.

Network I/O occurs exclusively in Scheduler worker threads (or an explicit CLI
collection call). Providers are data, never Python plugins or executable code.
"""
from __future__ import annotations

import copy
import hashlib
import html
import ipaddress
import json
import logging
import math
import re
import socket
import threading
import time
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from defusedxml import ElementTree as SafeET

from .lifecycle import provider_id, scope_identifier
from .map_evidence import nws_map_fields
from .capacity_limits import MAX_TOTAL_SOURCES

LOG = logging.getLogger(__name__)
UTC = timezone.utc
MAX_BYTES = 6 * 1024 * 1024
MAX_ITEMS = 600
MAX_SUMMARY = 1000
USER_AGENT = "GlobalPulse/0.1 (Dietrich AI Labs; https://www.dietrichailabs.com)"
RESOURCE_DIR = Path(__file__).with_name("resources")
SUPPORTED_ADAPTERS = {"rss", "atom", "gdacs", "usgs", "eonet", "nws", "cap", "worldbank", "swpc", "gdelt_doc", "who_don", "manual"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(value: Any = None) -> str:
    """Normalize known timestamps; missing/invalid source dates remain missing."""
    if value is None or value == "":
        return ""
    try:
        if isinstance(value, datetime):
            d = value
        elif isinstance(value, (int, float)):
            if not math.isfinite(value):
                return ""
            d = datetime.fromtimestamp(value / 1000 if value > 100000000000 else value, UTC)
        else:
            s = str(value).strip()
            try:
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError, OSError):
        return ""


def timestamp(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0.0


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "iframe", "object", "svg"}:
            self.skip += 1
        elif tag.lower() in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "iframe", "object", "svg"}:
            self.skip = max(0, self.skip - 1)
        elif tag.lower() in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value: Any, limit: int = MAX_SUMMARY) -> str:
    p = _PlainText()
    try:
        p.feed(str(value or "")[:100000])
        text = " ".join("".join(p.parts).split())
    except Exception:
        text = re.sub(r"<[^>]*>", " ", str(value or ""))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text[:limit].rstrip()


def public_url(url: Any, allowed_domains: list[str] | None = None, *, resolve: bool = False) -> str:
    """Validate HTTPS/public host syntax, and optionally check DNS answers.

    Fetches only use reviewed catalog domains and checked redirect targets.
    User feeds must additionally pass public DNS validation. A local enterprise
    proxy remains responsible for its own resolution and egress policy.
    """
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 for c in url) or "\\" in url:
        raise ValueError("Invalid URL")
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTPS URLs without credentials are allowed")
    if parsed.port not in (None, 443):
        raise ValueError("Only the standard HTTPS port is allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")) or "." not in host:
        raise ValueError("Local hosts are not permitted")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid hostname") from exc
        numeric_host = r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*"
        if not re.fullmatch(r"[a-z0-9.-]+", ascii_host) or re.fullmatch(numeric_host, ascii_host, re.I):
            raise ValueError("Ambiguous or invalid hostname")
    if address is not None and not address.is_global:
        raise ValueError("Private, loopback and reserved addresses are not permitted")
    if allowed_domains and host not in {d.lower().rstrip(".") for d in allowed_domains}:
        raise ValueError("Source domain is not allowlisted")
    if resolve and address is None:
        try:
            answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError("Public DNS verification unavailable") from exc
        if not answers or any(not ipaddress.ip_address(a[4][0]).is_global for a in answers):
            raise ValueError("Source resolves to a non-public address")
    clean_host = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", clean_host, parsed.path or "/", parsed.query, ""))


def safe_link(value: Any, base: str = "", domains: list[str] | None = None) -> str:
    try:
        return public_url(urljoin(base, str(value or "")), domains)
    except ValueError:
        return ""


def canonical_url(value: str) -> str:
    p = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ""))


def load_catalog(path: str | Path | None = None) -> list[dict]:
    doc = json.loads(Path(path or RESOURCE_DIR / "sources.json").read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise ValueError("Unsupported source catalog version")
    result = doc.get("sources", [])
    if not isinstance(result, list) or len(result) > MAX_TOTAL_SOURCES:
        raise ValueError("Source catalog is invalid or too large")
    seen = set()
    for source in result:
        if not isinstance(source, dict) or not re.fullmatch(r"[a-z0-9_-]{1,80}", str(source.get("id", ""))):
            raise ValueError("Invalid source identity")
        if source["id"] in seen:
            raise ValueError("Duplicate source identity")
        seen.add(source["id"])
        if source.get("adapter") not in SUPPORTED_ADAPTERS:
            raise ValueError("Unsupported adapter")
        if "publisher_origin_id" in source and (not isinstance(source["publisher_origin_id"], str) or not re.fullmatch(r"[a-z0-9_-]{1,80}", source["publisher_origin_id"])):
            raise ValueError("Invalid publisher origin identity")
        public_url(source["url"], source.get("allowed_domains"))
        if source.get("enabled") and source.get("access_status") != "reviewed_public":
            raise ValueError("An unreviewed source cannot be enabled by the bundled catalog")
        if int(source.get("min_interval", 600)) < 60:
            raise ValueError("Polling interval below safety minimum")
    return copy.deepcopy(result)


def load_media_catalog() -> list[dict]:
    return json.loads((RESOURCE_DIR / "media_catalog.json").read_text(encoding="utf-8"))["entries"]


def make_user_feed(url: str, name: str, *, category: str = "News", region: str = "Global", min_interval: int = 600, validate_dns: bool = True) -> dict:
    """User explicitly supplies a public feed and is shown source-rights settings.

    Adding a feed is not a permission grant to republish its content. Unknown
    feeds default to headline/link metadata only and no independence assertion.
    """
    url = public_url(url, resolve=validate_dns)
    host = urlsplit(url).hostname
    return {"id": "user_" + hashlib.sha256(url.encode()).hexdigest()[:16],
            "name": plain(name, 100) or host, "category": plain(category, 50),
            "region": plain(region, 80), "url": url, "adapter": "rss", "enabled": True,
            "min_interval": max(300, int(min_interval)), "allowed_domains": [host],
            "access": "User-configured public feed; no authentication",
            "access_status": "user_supplied", "license": "User must verify permitted personal use; no redistribution clearance",
            "attribution": name, "status": "not_checked", "metadata_only": True,
            "language": "und",  # No publisher-language evidence: never assume English.
            "official": False, "independence": "unknown", "custom": True,
            "retention_days": 30}


def _base(source: dict, raw_id: Any, title: Any, url: Any, published: Any, retrieved: str) -> dict:
    original_url = str(url or "")
    parsed = urlsplit(original_url)
    if parsed.scheme == "http" and parsed.hostname in source.get("upgrade_http_domains", []):
        url = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    url = safe_link(url, source["url"], source.get("article_domains"))
    identity = str(raw_id or canonical_url(url) or plain(title, 240))[:4096]
    return {"id": source["id"] + ":" + hashlib.sha256(identity.encode()).hexdigest()[:24],
            "source_id": source["id"], "publisher": source["name"], "title": plain(title, 300),
            "url": url, "original_url": original_url, "published_at": iso(published), "retrieved_at": retrieved,
            "language": source.get("language") or "und", "region": source.get("region", "Global"),
            "country": source.get("country", ""), "category": source.get("category", "News"),
            "source_country": source.get("country", ""), "country_basis": "publisher_coverage",
            "kind": "report", "origin_id": (source.get("publisher_origin_id") or source["id"]) if source.get("independence") == "original" else "",
            "independence": source.get("independence", "unknown"), "event_key": "",
            "severity": "unassessed", "latitude": None, "longitude": None,
            "geo_precision": "unknown", "claims": {}, "media": [], "summary": "",
            "official": bool(source.get("official", False)),
            "official_scope": source.get("official_scope", "statement"),
            "synthetic": False, "retention_days": int(source.get("retention_days", 365)),
            "source_license": source.get("license", ""), "attribution": source.get("attribution", source["name"])}


def _language(text: str, fallback: str) -> str:
    if fallback != "und":
        return fallback
    for pattern, language in ((r"[\u0900-\u097f]", "hi"), (r"[\u0600-\u06ff]", "ar"),
                              (r"[\u3040-\u30ff]", "ja"), (r"[\u0400-\u04ff]", "ru")):
        if len(re.findall(pattern, text)) > 3:
            return language
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        return detect(text[:1000]) if len(text) > 40 else "und"
    except Exception:
        return "und"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(node, *names: str) -> str:
    for name in names:
        for element in node:
            if _local(element.tag) == name.lower() and element.text:
                return element.text.strip()
    return ""


def _number(value: Any) -> float | None:
    try:
        val = float(value)
        return val if math.isfinite(val) else None
    except (ValueError, TypeError):
        return None


def _point(report: dict, longitude: Any, latitude: Any, precision="source_point"):
    lat, lon = _number(latitude), _number(longitude)
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        report.update(latitude=lat, longitude=lon, geo_precision=precision)


def parse_feed(data: bytes, source: dict, retrieved: str) -> list[dict]:
    if len(data) > MAX_BYTES:
        raise ValueError("Feed exceeds size limit")
    root = SafeET.fromstring(data)
    if _local(root.tag) not in {"rss", "feed", "rdf", "alert"}:
        raise ValueError("Response is not an RSS, Atom or CAP feed")
    if _local(root.tag) == "alert":
        return parse_cap(root, source, retrieved)
    language = source.get("language") or "und"
    items = [n for n in root.iter() if _local(n.tag) in {"item", "entry"}][:MAX_ITEMS]
    result = []
    for node in items:
        title = _child(node, "title")
        # A small set of reviewed feeds (currently Statistics Canada) wrap
        # human-readable title text in harmless inline markup. Do not broaden
        # generic XML interpretation: opt in per source and still sanitize the
        # bounded itertext result through plain().
        if not title and source.get("nested_feed_text"):
            title_node = next((n for n in node if _local(n.tag) == "title"), None)
            if title_node is not None:
                title = plain(" ".join(title_node.itertext()), 300)
        link = _child(node, "link")
        if not link:
            link = next((n.get("href", "") for n in node if _local(n.tag) == "link" and n.get("rel", "alternate") == "alternate"), "")
        rid = _child(node, "guid", "id") or link
        published = _child(node, "pubdate", "published", "date")
        updated = _child(node, "updated")
        # Atom's "updated" is not normally equivalent to publication time.
        # Use it as publication evidence only for specifically reviewed feeds
        # whose publisher documents/uses it as the release timestamp.
        if not published and source.get("updated_is_publication_time"):
            published = updated
        report = _base(source, rid, title, link, published, retrieved)
        if not report["title"] or not report["url"]:
            continue
        summary = _child(node, "description", "summary")
        report["metadata_only"] = bool(source.get("metadata_only"))
        report["summary"] = "" if report["metadata_only"] else plain(summary)
        report["language"] = _language(report["title"] + " " + report["summary"], language)
        report["source_updated_at"] = iso(updated)
        report["publication_time_unknown"] = not bool(report["published_at"])
        report["summary_truncated"] = len(plain(summary, 100001)) > MAX_SUMMARY
        point = _child(node, "point").split()
        if len(point) == 2:
            _point(report, point[1], point[0])
        else:
            _point(report, _child(node, "long", "lon"), _child(node, "lat"))
        if source["adapter"] == "gdacs":
            report["severity"] = {"red": "high", "orange": "moderate", "green": "informational"}.get(_child(node, "alertlevel").lower(), "unassessed")
            report["country"] = plain(_child(node, "country"), 100)
            report["country_basis"] = "provider_incident"
            event_id = _child(node, "eventid")
            if event_id:
                report["event_key"] = "gdacs:" + _child(node, "eventtype") + ":" + event_id
            report["official_scope"] = "statement"
            report["independence"] = "unknown"  # GDACS can reuse agency inputs.
            report["origin_id"] = ""
        for n in node:
            if _local(n.tag) in {"source", "creator", "author"}:
                report["byline"] = plain(" ".join(n.itertext()), 160)
            if _local(n.tag) == "videoid" and re.fullmatch(r"[A-Za-z0-9_-]{11}", n.text or ""):
                report["media"].append({"type": "youtube", "video_id": n.text,
                                         "url": "https://www.youtube.com/watch?v=" + n.text,
                                         "title": report["title"], "provider": "YouTube", "live_status": "unknown"})
        result.append(report)
    return result


def parse_cap(root, source: dict, retrieved: str) -> list[dict]:
    identifier, sent = _child(root, "identifier"), _child(root, "sent")
    sender = _child(root, "sender")
    status, message = _child(root, "status"), _child(root, "msgtype").title()
    if status.lower() != "actual" or message not in {"Alert", "Update", "Cancel"} or not identifier:
        return []
    info = next((n for n in root if _local(n.tag) == "info"), None)
    if info is None and message != "Cancel":
        return []
    def value(*names):
        return _child(info, *names) if info is not None else ""
    title = value("headline", "event") or "Warning cancellation"
    r = _base(source, scope_identifier(identifier, sender), title,
              value("web") or source["url"], sent, retrieved)
    r.update(summary=plain(value("description") or _child(root, "note")), kind="announcement", official=bool(source.get("official", False)),
             severity={"extreme": "critical", "severe": "high", "moderate": "moderate", "minor": "informational"}.get(value("severity").lower(), "unassessed"),
             cap_status=status, cap_message_type=message, provider_sender=sender,
             provider_identifier=identifier, identity_aliases=[r["id"]], lifecycle_references=[],
             source_references=[], reference_errors=False, event_key="cap:" + r["id"],
             expires_at=value("expires"))
    r["language"] = value("language").split("-")[0] or r["language"]
    r["cap_references"] = _child(root, "references")
    entries = r["cap_references"].split()
    r["reference_errors"] = len(entries) > 40
    for entry in entries[:40]:
        pieces = entry.split(",")
        if len(pieces) != 3 or not pieces[1] or not iso(pieces[2]) or sender and pieces[0] != sender:
            r["reference_errors"] = True
            continue
        r["lifecycle_references"].append(provider_id(source["id"], scope_identifier(pieces[1], pieces[0])))
        r["source_references"].append({"identifier": pieces[1], "sender": pieces[0], "sent": iso(pieces[2]), "type": "cap_lifecycle"})
    return [r] if r["title"] and r["url"] else []


def parse_usgs(payload: dict, source: dict, retrieved: str) -> list[dict]:
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("Invalid USGS GeoJSON contract")
    result = []
    for f in payload["features"][:MAX_ITEMS]:
        if not isinstance(f, dict):
            continue
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        mag = _number(p.get("mag"))
        r = _base(source, f.get("id"), p.get("title") or f"Earthquake reported: {p.get('place', 'location unspecified')}", p.get("url"), p.get("time"), retrieved)
        if not r["url"]:
            continue
        r.update(event_key="usgs:" + str(f.get("id")), official=True, official_scope="measurement", kind="measurement")
        r["source_updated_at"] = iso(p.get("updated"))
        r["region"] = plain(p.get("place"), 160) or "Global"
        r["summary"] = f"USGS reports {plain(p.get('title') or p.get('place'), 250)}. "
        r["summary"] += "Measurement status: " + plain(p.get("status") or "unspecified", 60) + ". Impact estimates are not inferred from magnitude."
        if mag is not None:
            r["claims"]["magnitude"] = {"value": mag, "unit": plain(p.get("magType") or "magnitude", 40), "as_of": r["published_at"]}
        r["severity"] = {"red": "critical", "orange": "high", "yellow": "moderate", "green": "informational"}.get(p.get("alert"), "high" if mag is not None and mag >= 6 else "moderate" if mag is not None and mag >= 4.5 else "informational")
        r["severity_basis"] = "USGS PAGER alert" if p.get("alert") else "Measured magnitude; not a casualty or damage estimate"
        coords = g.get("coordinates", [])
        if g.get("type") == "Point" and len(coords) >= 2:
            _point(r, coords[0], coords[1])
            if len(coords) > 2 and _number(coords[2]) is not None:
                r["claims"]["depth"] = {"value": _number(coords[2]), "unit": "km", "as_of": r["published_at"]}
        result.append(r)
    return result


def parse_eonet(payload: dict, source: dict, retrieved: str) -> list[dict]:
    if not isinstance(payload.get("events"), list):
        raise ValueError("Invalid EONET contract")
    result = []
    for e in payload["events"][:MAX_ITEMS]:
        geometry = e.get("geometry") or []
        latest = max(geometry, key=lambda x: timestamp(x.get("date")), default={})
        earliest = min(geometry, key=lambda x: timestamp(x.get("date")), default={})
        r = _base(source, e.get("id"), e.get("title"), e.get("link") or "https://eonet.gsfc.nasa.gov/api/v3/events/" + str(e.get("id", "")), earliest.get("date"), retrieved)
        r.update(event_key="eonet:" + str(e.get("id")), kind="catalog_entry", official=True,
                 official_scope="statement", independence="unknown", origin_id="")
        r["summary"] = plain(e.get("description")) or "NASA EONET lists this natural event. Open the linked catalog record to inspect the original reporting sources."
        r["closed_at"] = iso(e.get("closed"))
        r["source_updated_at"] = iso(latest.get("date"))
        r["source_references"] = [{"source": plain(s.get("id"), 100), "url": safe_link(s.get("url"))} for s in (e.get("sources") or [])[:30]]
        r["subcategories"] = [plain(c.get("title"), 60) for c in (e.get("categories") or [])]
        r["severity"] = "unassessed"  # Catalog presence is not an impact measure.
        coords = latest.get("coordinates") or []
        if latest.get("type") == "Point" and len(coords) >= 2:
            _point(r, coords[0], coords[1])
        if latest.get("magnitudeValue") is not None:
            r["claims"]["magnitude"] = {"value": latest.get("magnitudeValue"), "unit": latest.get("magnitudeUnit") or "unknown", "as_of": iso(latest.get("date"))}
        result.append(r)
    return result


def parse_nws(payload: dict, source: dict, retrieved: str) -> list[dict]:
    if not isinstance(payload.get("features"), list):
        raise ValueError("Invalid NWS alert contract")
    result = []
    for f in payload["features"][:MAX_ITEMS]:
        if not isinstance(f, dict) or not isinstance(f.get("properties"), dict):
            continue
        p = f["properties"]
        message = str(p.get("messageType", "Alert")).title()
        if p.get("status") != "Actual" or message not in {"Alert", "Update", "Cancel"}:
            continue
        rid = p.get("id") or f.get("id")
        if not rid:
            continue
        link = safe_link(p.get("web")) or safe_link(p.get("@id")) or safe_link(f.get("id"))
        title = p.get("headline") or p.get("event") or ("Warning cancellation" if message == "Cancel" else "")
        r = _base(source, rid, title, link, p.get("sent"), retrieved)
        if not r["url"] or not r["title"]:
            continue
        r.update(event_key="nws:" + str(rid), summary=plain(p.get("description")), kind="announcement", official=True,
                 cap_status="Actual", cap_message_type=message, provider_sender=plain(p.get("sender"), 300),
                 provider_identifier=str(rid), lifecycle_references=[], reference_errors=False,
                 identity_aliases=list(dict.fromkeys(provider_id(source["id"], value) for value in
                     [rid, p.get("@id"), f.get("id"), p.get("identifier")] if value)))
        r["region"] = plain(p.get("areaDesc"), 180) or "United States"
        r["severity"] = {"Extreme": "critical", "Severe": "high", "Moderate": "moderate", "Minor": "informational"}.get(p.get("severity"), "unassessed")
        r["expires_at"] = p.get("expires") or ""
        r["certainty"] = plain(p.get("certainty"), 60)
        r["instruction"] = plain(p.get("instruction"))
        references = p.get("references") or []
        if not isinstance(references, list):
            references = []
            r["reference_errors"] = True
        r["reference_errors"] |= len(references) > 40
        r["source_references"] = references[:40]
        for ref in references[:40]:
            if not isinstance(ref, dict):
                r["reference_errors"] = True
                continue
            if r["provider_sender"] and ref.get("sender") and ref["sender"] != r["provider_sender"]:
                r["reference_errors"] = True
                continue
            # identifier and @id are alternative forms of one reference, not
            # two warnings. Prefer the publisher's stable identifier when given.
            ids = [ref.get("identifier") or ref.get("id") or ref.get("@id") or ref.get("url")]
            if not any(ids):
                r["reference_errors"] = True
            r["lifecycle_references"].extend(provider_id(source["id"], x) for x in ids if x)
        r["geo_precision"] = "area_unspecified"
        r.update(nws_map_fields(f, p))
        result.append(r)
    return result


def parse_who_don(payload: dict, source: dict, retrieved: str) -> list[dict]:
    """Parse WHO Disease Outbreak News API metadata without copying article bodies."""
    rows = payload.get("value", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("Invalid WHO Disease Outbreak News contract")
    result = []
    for item in rows[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        title = plain(item.get("OverrideTitle") or item.get("Title"), 300)
        published = item.get("PublicationDateAndTime") or item.get("PublicationDate")
        identity = item.get("DonId") or item.get("Id") or item.get("UrlName")
        item_url = item.get("ItemDefaultUrl") or (
            "/emergencies/disease-outbreak-news/item/" + str(item.get("UrlName") or "")
        )
        report = _base(source, identity, title, item_url, published, retrieved)
        if not report["title"] or not report["url"] or not report["published_at"]:
            continue
        # WHO's API exposes large narrative fields. Keep only bounded title /
        # summary metadata for discovery and attribution; open the WHO page for
        # the full text.
        summary = plain(item.get("Summary"), 600)
        if not summary:
            summary = plain(item.get("Overview"), 600)
        report.update(
            summary=summary,
            metadata_only=True,
            kind="announcement",
            official=True,
            official_scope="statement",
            independence="original",
            origin_id=source.get("publisher_origin_id") or source["id"],
            severity="unassessed",
            source_updated_at=iso(item.get("LastModified")),
        )
        result.append(report)
    return result


@lru_cache(maxsize=1)
def _map_iso3_codes() -> set[str]:
    try:
        doc = json.loads((RESOURCE_DIR / "world_countries.geojson").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    return {
        str((feature.get("properties") or {}).get("code") or "").upper()
        for feature in doc.get("features", [])
        if re.fullmatch(r"[A-Z]{3}", str((feature.get("properties") or {}).get("code") or "").upper())
    }


def parse_worldbank(payload: list, source: dict, retrieved: str) -> list[dict]:
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], dict) or not isinstance(payload[1], list):
        raise ValueError("Invalid World Bank indicator contract")
    metadata, rows = payload[0], payload[1]
    result = []
    for row in rows[:2000]:
        value = _number(row.get("value"))
        if value is None:
            continue
        country = row.get("country") or {}
        indicator = row.get("indicator") or {}
        year = str(row.get("date", ""))
        if not re.fullmatch(r"\d{4}", year):
            continue
        indicator_id = str(indicator.get("id") or source.get("indicator", ""))
        country_code = str(row.get("countryiso3code") or "").upper()
        # country/all also returns World Bank aggregates and regions. Admit only
        # ISO3 identities represented by the bundled offline country map.
        if country_code not in _map_iso3_codes():
            continue
        result.append({"id": f"wb:{country_code}:{indicator_id}:{year}", "source_id": source["id"],
                       "indicator": indicator_id, "indicator_name": plain(indicator.get("value"), 200),
                       "country": plain(country.get("value"), 100), "country_code": country_code,
                       "date": year, "observation_date": year, "value": value,
                       "unit": plain(row.get("unit") or source.get("unit") or "not specified", 100),
                       "release_date": None, "dataset_updated_at": str(metadata.get("lastupdated", "")),
                       "retrieved_at": retrieved,
                       "url": f"https://data.worldbank.org/indicator/{indicator_id}?locations={country.get('id', '')}",
                       "attribution": source.get("attribution", "World Bank"),
                       "description": source.get("indicator_description", ""),
                       "source_note": "Annual observation; dataset update date is not this observation's release date. No crisis classification inferred."})
    return result


def parse_swpc(payload: list, source: dict, retrieved: str) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError("Invalid SWPC alerts contract")
    result = []
    for item in payload[:MAX_ITEMS]:
        message = plain(item.get("message"), MAX_SUMMARY)
        if not message:
            continue
        r = _base(source, str(item.get("product_id")) + ":" + str(item.get("issue_datetime")), message.split(".")[0][:200], source["homepage"], item.get("issue_datetime"), retrieved)
        r.update(summary=message, kind="announcement", official=True, severity="unassessed")
        result.append(r)
    return result


def retry_after(value: str | None, now: datetime | None = None) -> int | None:
    if not value:
        return None
    try:
        seconds = int(value)
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            seconds = math.ceil((dt - (now or utcnow())).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, seconds)  # Never cap a provider's requested delay downward.


def bounded_body(response: httpx.Response, started: float) -> bytes:
    """Limit compressed wire bytes and expansion before allocating the result."""
    if response.is_stream_consumed:
        # Test/custom transports may provide an already decoded in-memory body.
        # Real Collector responses are obtained through Client.stream().
        if len(response.content) > MAX_BYTES:
            raise ValueError("Decoded response exceeds size limit")
        return response.content
    encoding = response.headers.get("content-encoding", "identity").lower().strip()
    if encoding not in {"identity", "", "gzip", "deflate"}:
        raise ValueError("Unsupported compressed response; identity requested")
    decoder = zlib.decompressobj(31 if encoding == "gzip" else zlib.MAX_WBITS) if encoding in {"gzip", "deflate"} else None
    content = bytearray()
    raw_size = 0
    for raw in response.iter_raw(chunk_size=65536):
        raw_size += len(raw)
        if raw_size > MAX_BYTES:
            raise ValueError("Response exceeds wire size limit")
        block = decoder.decompress(raw, MAX_BYTES - len(content) + 1) if decoder else raw
        content.extend(block)
        if len(content) > MAX_BYTES or decoder and decoder.unconsumed_tail:
            raise ValueError("Decoded response exceeds size limit")
        if time.monotonic() - started > 25:
            raise TimeoutError("Collection wall-time budget exceeded")
    if decoder:
        if not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid or concatenated compressed response")
        content.extend(decoder.flush(MAX_BYTES - len(content) + 1))
    if len(content) > MAX_BYTES:
        raise ValueError("Decoded response exceeds size limit")
    return bytes(content)


def _gdelt_country_names() -> list[str]:
    """Return the offline map's country labels for rotating local-press discovery."""
    path = RESOURCE_DIR / "world_countries.geojson"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    names = []
    for feature in doc.get("features", []):
        name = str((feature.get("properties") or {}).get("name", "")).strip()
        if name and name != "Antarctica" and name not in names:
            names.append(name)
    return names


def _gdelt_country_token(name: str) -> str:
    # GDELT sourcecountry accepts collapsed country names. Keep ASCII letters
    # only; explicit aliases cover common Natural Earth/GDELT naming differences.
    aliases = {
        "United States of America": "unitedstates",
        "Czechia": "czechrepublic",
        "Dem. Rep. Congo": "democraticrepublicofthecongo",
        "eSwatini": "eswatini",
        "Bosnia and Herz.": "bosniaandherzegovina",
        "Central African Rep.": "centralafricanrepublic",
        "Dominican Rep.": "dominicanrepublic",
        "Eq. Guinea": "equatorialguinea",
        "S. Sudan": "southsudan",
        "Solomon Is.": "solomonislands",
    }
    value = aliases.get(name, name)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z]", "", value)


def gdelt_request_url(source: dict, state: dict) -> tuple[str, int, list[str]]:
    countries = source.get("countries")
    if not isinstance(countries, list) or not countries:
        countries = _gdelt_country_names()
    countries = [str(name) for name in countries if _gdelt_country_token(str(name))]
    if not countries:
        raise ValueError("GDELT country rotation is empty")
    batch_size = max(1, min(12, int(source.get("country_batch_size", 8))))
    cursor = int(state.get("country_cursor", 0)) % len(countries)
    batch = [countries[(cursor + offset) % len(countries)] for offset in range(min(batch_size, len(countries)))]
    query = "(" + " OR ".join("sourcecountry:" + _gdelt_country_token(name) for name in batch) + ")"
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max(10, min(250, int(source.get("max_records", 150))))),
        "sort": "datedesc",
        "timespan": str(source.get("timespan", "6h")),
    }
    base = str(source.get("url", "https://api.gdeltproject.org/api/v2/doc/doc"))
    return base + "?" + urlencode(params), (cursor + len(batch)) % len(countries), batch


def _gdelt_seen_date(value: object) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}T\d{6}Z", text):
        try:
            return iso(datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
        except ValueError:
            return ""
    return iso(text)


def parse_gdelt_doc(payload: dict, source: dict, retrieved: str) -> list[dict]:
    articles = payload.get("articles", []) if isinstance(payload, dict) else []
    if not isinstance(articles, list):
        raise ValueError("Invalid GDELT article list")
    reports = []
    seen = set()
    for item in articles[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        url = safe_link(item.get("url", ""), domains=None)
        title = plain(item.get("title"), 300)
        if not url or not title:
            continue
        key = canonical_url(url)
        if key in seen:
            continue
        seen.add(key)
        url = key
        report = _base(source, key, title, url, _gdelt_seen_date(item.get("seendate")), retrieved)
        report["publisher"] = plain(item.get("domain"), 120) or source["name"]
        report["source_country"] = plain(item.get("sourcecountry"), 80)
        report["country"] = ""
        report["language"] = plain(item.get("language"), 30) or "und"
        report["summary"] = "World-press discovery metadata from GDELT; open the original publisher for article content."
        report["metadata_only"] = True
        report["independence"] = "unknown"
        report["origin_id"] = ""
        report["official"] = False
        reports.append(report)
    return reports


class Collector:
    def __init__(self, source: dict, *, client_factory=None, now=None, zone_resolver=None):
        self.source = copy.deepcopy(source)
        self.client_factory = client_factory or httpx.Client
        self.now = now or utcnow
        self.zone_resolver = zone_resolver

    def collect(self, state: dict | None = None) -> dict:
        state = dict(state or {})
        current = self.now()
        current_iso = iso(current)
        interval = max(60, int(self.source.get("min_interval", 600)), int(state.get("configured_interval", 600)))
        result = {"reports": [], "observations": [], "state": state}
        state.update(last_attempt=current_iso, error="")
        if self.source.get("adapter") == "manual" or not self.source.get("enabled", False):
            state.update(status="disabled", next_poll=iso(current + timedelta(seconds=interval)))
            return result
        headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json, application/json, application/rss+xml, application/atom+xml, application/xml;q=0.9", "Accept-Encoding": "identity"}
        for old_key, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
            if (not (self.source.get("adapter") == "nws" and state.get("nws_zones_pending"))
                    and state.get(old_key) and len(str(state[old_key])) < 4096 and "\n" not in str(state[old_key])):
                headers[header] = str(state[old_key])
        try:
            adapter = self.source["adapter"]
            gdelt_next_cursor = None
            gdelt_batch = None
            if adapter == "gdelt_doc":
                dynamic_url, gdelt_next_cursor, gdelt_batch = gdelt_request_url(self.source, state)
                url = public_url(dynamic_url, self.source.get("allowed_domains"), resolve=False)
            else:
                url = public_url(self.source["url"], self.source.get("allowed_domains"), resolve=bool(self.source.get("custom")))
            started = time.monotonic()
            with self.client_factory(timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=False, headers=headers) as client:
                for redirects in range(4):
                    with client.stream("GET", url) as response:
                        state["http_status"] = response.status_code
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if redirects == 3:
                                raise ValueError("Too many redirects")
                            url = public_url(urljoin(url, response.headers.get("location", "")), self.source.get("allowed_domains"), resolve=bool(self.source.get("custom")))
                            continue
                        if response.status_code == 304:
                            # No new reports arrived, but a once-recent cached
                            # publication still ages while the provider serves
                            # 304. Preserve its exact source timestamp and
                            # validators; only advance derived freshness.
                            cached_raw = state.get("latest_publication")
                            cached_publication = iso(cached_raw)
                            if cached_raw and not cached_publication:
                                # Persisted state is not trusted merely because it
                                # is nonempty. Invalid source-time evidence cannot
                                # survive a 304 and drive freshness/UI claims.
                                state.pop("latest_publication", None)
                                if state.get("freshness") in {"recent", "stale"}:
                                    state["freshness"] = "publication dates unavailable"
                                state["error"] = ""
                            stale = state.get("freshness") == "stale"
                            if cached_publication and state.get("freshness") == "recent":
                                age_days = (current.timestamp() - timestamp(cached_publication)) / 86400
                                if age_days > int(self.source.get("stale_after_days", 90)):
                                    stale = True
                                    state["freshness"] = "stale"
                                    state["error"] = "Feed unchanged; newest publication is " + cached_publication
                            state.update(last_success=current_iso, status="stale" if stale else "not_modified", failures=0, error=state.get("error", "") if stale else "", next_poll=iso(current + timedelta(seconds=interval)))
                            return result
                        if response.status_code in {429, 503}:
                            delay = retry_after(response.headers.get("retry-after"), current)
                            failures = min(12, int(state.get("failures", 0)) + 1)
                            delay = max(interval, delay or 0, min(86400, interval * 2 ** failures))
                            state.update(last_failure=current_iso, status="rate_limited" if response.status_code == 429 else "unavailable", failures=failures, error=f"HTTP {response.status_code}; retry scheduled", retry_after_seconds=delay, next_poll=iso(current + timedelta(seconds=delay)))
                            return result
                        if response.status_code in {401, 403}:
                            # Denials are not invitations to change credentials,
                            # rotate endpoints or retry a sibling source immediately.
                            # A finite, persisted host circuit protects the origin.
                            failures = min(12, int(state.get("failures", 0)) + 1)
                            delay = max(86400, retry_after(response.headers.get("retry-after"), current) or 0)
                            state.update(last_failure=current_iso, status="denied", failures=failures,
                                         error=f"HTTP {response.status_code}; source access denied; retry deferred",
                                         retry_after_seconds=delay,
                                         next_poll=iso(current + timedelta(seconds=delay)))
                            return result
                        response.raise_for_status()
                        length = response.headers.get("content-length", "")
                        if length.isdigit() and int(length) > MAX_BYTES:
                            raise ValueError("Response exceeds size limit")
                        body = bounded_body(response, started)
                        response_headers = dict(response.headers)
                        break
                else:
                    raise ValueError("Redirect failure")
            if adapter in {"rss", "atom", "gdacs", "cap"}:
                result["reports"] = parse_feed(body, self.source, current_iso)
            else:
                payload = json.loads(body)
                if adapter == "worldbank":
                    result["observations"] = parse_worldbank(payload, self.source, current_iso)
                else:
                    if adapter == "who_don":
                        result["reports"] = parse_who_don(payload, self.source, current_iso)
                    elif adapter == "gdelt_doc":
                        result["reports"] = parse_gdelt_doc(payload, self.source, current_iso)
                        state["country_cursor"] = gdelt_next_cursor
                        state["country_batch"] = gdelt_batch
                    else:
                        parser = {"usgs": parse_usgs, "eonet": parse_eonet, "nws": parse_nws, "swpc": parse_swpc}.get(adapter)
                        if parser is None:
                            raise ValueError("Unsupported adapter")
                        result["reports"] = parser(payload, self.source, current_iso)
                        if adapter == "nws":
                            from .nws_zone_resolver import DEFAULT_RESOLVER
                            resolver = self.zone_resolver or DEFAULT_RESOLVER
                            result["reports"], zone_state = resolver.enrich(result["reports"], client_factory=self.client_factory)
                            state["nws_zone_resolution"] = zone_state
                            state["nws_zones_pending"] = bool(zone_state["unresolved_alerts"])
            cache_control = response_headers.get("cache-control", "")
            max_age = re.search(r"(?:^|,)\s*max-age=(\d+)", cache_control)
            if max_age:
                interval = max(interval, min(7 * 86400, int(max_age.group(1))))
            state.update(last_success=current_iso, status="available", failures=0,
                         count=len(result["reports"]) + len(result["observations"]),
                         etag=response_headers.get("etag", ""), last_modified=response_headers.get("last-modified", ""),
                         next_poll=iso(current + timedelta(seconds=interval)), bytes_received=len(body), error="")
            # A new HTTP 200 response supersedes the *previous response's*
            # publication summary. Never carry an old "recent" or "stale"
            # publication into an undated/empty replacement feed. HTTP 304
            # takes a separate path above and retains its cached evidence.
            state.pop("latest_publication", None)
            dates = [r["published_at"] for r in result["reports"] if r.get("published_at")]
            if dates:
                state["latest_publication"] = max(dates)
                age_days = max(0, (current.timestamp() - timestamp(max(dates))) / 86400)
                state["freshness"] = "stale" if age_days > int(self.source.get("stale_after_days", 90)) else "recent"
                if state["freshness"] == "stale":
                    state["status"] = "stale"
                    state["error"] = "Feed retrieved, but newest publication is " + max(dates)
            elif result["reports"]:
                state["freshness"] = "publication dates unavailable"
            elif result["observations"]:
                # Indicators have observation dates, not necessarily
                # publication/release dates. They are not an empty feed.
                state["freshness"] = "observations received"
            else:
                state["freshness"] = "no reports"
        except Exception as exc:
            failures = min(12, int(state.get("failures", 0)) + 1)
            # Do not include exception request URLs or proxy credentials in diagnostics.
            if isinstance(exc, httpx.HTTPStatusError):
                error = f"HTTP {exc.response.status_code}"
            elif isinstance(exc, (httpx.TimeoutException, TimeoutError)):
                error = "Source request timed out"
            elif isinstance(exc, httpx.RequestError):
                error = "Source network connection unavailable"
            elif isinstance(exc, ValueError):
                error = "Invalid source response or URL: " + plain(str(exc), 160)
            else:
                error = "Collection failed: " + type(exc).__name__
            state.update(last_failure=current_iso, status="error", failures=failures, error=error,
                         next_poll=iso(current + timedelta(seconds=min(86400, interval * 2 ** failures))))
        return result


class Scheduler:
    """At most four daemon collectors; persisted wall-clock due dates; no catch-up.

    Pausing invalidates in-flight callback generations so a completed request
    cannot create new-monitoring alerts. Stop returns within the requested
    timeout, and daemon workers cannot keep an explicitly exited app alive.
    """
    def __init__(self, store, on_reports: Callable, on_status: Callable | None = None,
                 on_observations: Callable | None = None, interval=600, *, collector_factory=Collector, max_workers=4):
        self.store = store
        self.on_reports = on_reports
        self.on_status = on_status
        self.on_observations = on_observations
        self.interval = max(300, int(interval))
        self.sources = load_catalog()
        self.collector_factory = collector_factory
        self.max_workers = max(1, min(4, int(max_workers)))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.RLock()
        self._paused = False
        self._generation = 0
        self._thread = None
        self._workers: dict[str, threading.Thread] = {}
        self._last_started: dict[str, float] = {}
        self._global_next = 0.0
        self._host_next: dict[str, float] = {}
        # One-process conservative fallback for severely corrupt persisted
        # host-circuit state. Keyed by exact persisted evidence so repeated
        # scheduler ticks do not extend the fallback forever.
        self._corrupt_host_recovery: dict[str, tuple[tuple[str, str, str, str], float]] = {}

    @property
    def paused(self):
        return self._paused

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="GlobalPulseScheduler", daemon=True)
            self._thread.start()

    def pause(self):
        with self._lock:
            self._paused = True
            self._generation += 1
        self._wake.set()

    def resume(self):
        with self._lock:
            self._paused = False
        self._wake.set()

    def set_interval(self, seconds):
        with self._lock:
            self.interval = max(300, int(seconds))
        self._wake.set()

    def set_sources(self, catalog):
        if not isinstance(catalog, list) or len(catalog) > MAX_TOTAL_SOURCES:
            raise ValueError(f"At most {MAX_TOTAL_SOURCES} sources are allowed")
        with self._lock:
            for s in catalog:
                if s.get("enabled") and s.get("access_status") not in {"reviewed_public", "user_supplied"}:
                    raise ValueError("Source access review is required before enabling collection")
            self.sources = copy.deepcopy(catalog)
            self._generation += 1
        self._wake.set()

    def poll_now(self):
        # A refresh wakes the scheduler, without bypassing provider/cache/backoff dates.
        self._wake.set()

    def stop(self, timeout=2.0):
        with self._lock:
            self._stop.set()
            self._wake.set()
            self._generation += 1
            threads = ([self._thread] if self._thread else []) + list(self._workers.values())
        end = time.monotonic() + max(0, timeout)
        for thread in threads:
            if thread and thread is not threading.current_thread():
                thread.join(max(0, end - time.monotonic()))

    def _run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                LOG.exception("Scheduler tick failed")
            self._wake.wait(1.0)
            self._wake.clear()

    def _persisted_host_due(self, source: dict, saved: dict, wall_now: float) -> float:
        """Return a conservative wall-clock due time for persisted host holds.

        A valid absolute next_poll remains authoritative. If that timestamp is
        corrupt, reconstruct from last_failure + retry_after_seconds. Denials
        retain their 24-hour minimum. Reconstructed corrupt values are capped
        to 30 days; a valid provider-supplied absolute next_poll is never
        truncated. If both absolute and failure timestamps are corrupt, apply
        one bounded fallback per unchanged persisted-state signature so normal
        scheduler ticks cannot create an endless sliding lock.
        """
        status = str(saved.get("status") or "")
        if status not in {"rate_limited", "unavailable", "denied"}:
            return 0.0

        absolute_due = timestamp(saved.get("next_poll"))
        if absolute_due > 0:
            return absolute_due

        try:
            raw_delay = float(saved.get("retry_after_seconds") or 0)
        except (TypeError, ValueError, OverflowError):
            raw_delay = 0.0
        if not math.isfinite(raw_delay) or raw_delay < 0:
            raw_delay = 0.0

        source_floor = max(300, int(source.get("min_interval") or self.interval))
        minimum = 86400 if status == "denied" else source_floor
        # Corrupt-state reconstruction is bounded. Normal, valid next_poll
        # above still honors a longer provider Retry-After without truncation.
        delay = min(30 * 86400, max(float(minimum), raw_delay))

        failure_at = timestamp(saved.get("last_failure"))
        if failure_at > 0:
            return failure_at + delay

        sid = str(source.get("id") or "")
        signature = (
            status,
            str(saved.get("next_poll") or ""),
            str(saved.get("last_failure") or ""),
            str(saved.get("retry_after_seconds") or ""),
        )
        cached = self._corrupt_host_recovery.get(sid)
        if cached and cached[0] == signature:
            return cached[1]
        due = wall_now + delay
        self._corrupt_host_recovery[sid] = (signature, due)
        return due

    def _tick(self):
        with self._lock:
            self._workers = {k: t for k, t in self._workers.items() if t.is_alive()}
            if self._paused or self._stop.is_set() or time.monotonic() < self._global_next:
                return
            # Reconstruct per-host throttles from persistent provider responses,
            # so restarting does not let a sibling adapter evade Retry-After.
            states = {s["id"]: self.store.get_source_state(s["id"]) for s in self.sources}
            wall_now, monotonic_now = time.time(), time.monotonic()
            for peer in self.sources:
                saved = states[peer["id"]]
                if saved.get("status") in {"rate_limited", "unavailable", "denied"}:
                    due = self._persisted_host_due(peer, saved, wall_now)
                    remaining = due - wall_now
                    if remaining > 0:
                        host = urlsplit(peer["url"]).hostname or ""
                        self._host_next[host] = max(self._host_next.get(host, 0), monotonic_now + remaining)
            for source in self.sources:
                if len(self._workers) >= self.max_workers:
                    break
                sid = source["id"]
                if not source.get("enabled") or source.get("adapter") == "manual" or sid in self._workers:
                    continue
                state = states[sid]
                if timestamp(state.get("next_poll")) > time.time():
                    continue
                host = urlsplit(source["url"]).hostname or ""
                if time.monotonic() < self._host_next.get(host, 0):
                    continue
                state["configured_interval"] = self.interval
                generation = self._generation
                worker = threading.Thread(target=self._collect, args=(copy.deepcopy(source), state, generation), name="GPCollect-" + sid, daemon=True)
                self._workers[sid] = worker
                self._last_started[sid] = time.monotonic()
                self._global_next = time.monotonic() + 0.5
                self._host_next[host] = time.monotonic() + 2.0
                worker.start()
                break  # Smooth global pacing instead of burst submission.

    def _collect(self, source, state, generation):
        try:
            result = self.collector_factory(source).collect(state)
            with self._lock:
                if self._stop.is_set():
                    return
                fresh = generation == self._generation and not self._paused
                if fresh:
                    self.store.set_source_state(source["id"], result["state"])
                # On pause, do not advance checkpoints past data never delivered.
                if result["state"].get("status") in {"rate_limited", "unavailable", "denied"}:
                    # Share the actual persisted due time across same-host feeds.
                    # This includes 503 Retry-After and 401/403 access denials,
                    # not merely 429. Do not derive an earlier retry from a
                    # malformed cache or let app restart bypass the circuit.
                    self._global_next = max(self._global_next, time.monotonic() + 5)
                    host = urlsplit(source["url"]).hostname or ""
                    remaining = max(0.0, timestamp(result["state"].get("next_poll")) - time.time())
                    self._host_next[host] = max(self._host_next.get(host, 0), time.monotonic() + remaining)
                if fresh and self.on_status:
                    self.on_status(source["id"], result["state"])
                if fresh and result["state"].get("status") in {"available", "not_modified", "stale"}:
                    # Even an empty/304 response can advance eligibility of
                    # already archived future-dated evidence. This is a derived
                    # time check, not invented source content or catch-up news.
                    self.on_reports(result["reports"])
                if fresh and result["observations"] and self.on_observations:
                    self.on_observations(result["observations"])
        except Exception:
            LOG.exception("Collector callback failed for source %s", source.get("id", "unknown"))
