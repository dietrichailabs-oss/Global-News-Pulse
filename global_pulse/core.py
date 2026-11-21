"""Local evidence store and deterministic, conservative intelligence processing.

No network access or language model is used here. Input descriptions remain
attributed excerpts; source independence must be supplied by a trusted adapter.
A government attribution is never promoted into proof of its underlying claim.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from uuid import UUID, uuid4, uuid5

from .map_evidence import normalize_map_fields, event_areas

from .lifecycle import (normalize_lifecycle, apply_lifecycle, is_expired, select_warning_event,
                        register_warning, canonical_event, SCHEMA as LIFECYCLE_SCHEMA)

UTC = timezone.utc
EVENT_NAMESPACE = UUID("5dbbb956-1647-4162-aaf4-d19c5b67d2bb")
SEVERITY = {"unassessed": 0, "informational": 1, "moderate": 2, "high": 3, "critical": 4}
IGNORED_WORDS = frozenset("a an the and or in on at to of for from with by as is are was were be has have had this that says said report reports breaking update latest live".split())
MAX_BATCH = 2000
MAX_REPORTS = 250_000
MAX_EVENTS = 50_000


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dt(value: Any, *, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid ISO 8601 timestamp") from exc
    elif default is not None:
        dt = default
    else:
        raise ValueError("Missing timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso(value: Any = None) -> str:
    return _dt(value, default=datetime.now(UTC)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "noscript"}:
            self.skip += 1
        if tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object", "noscript"} and self.skip:
            self.skip -= 1
        if tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


def plain_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "")[: max(limit * 4, 2000)]
    parser = _TextParser()
    try:
        parser.feed(text)
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]*>", " ", text)
    text = unescape(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def safe_public_url(value: Any) -> str:
    """Validate links as data, without making DNS or HTTP requests."""
    text = str(value or "").strip()
    if len(text) > 4096 or any(ord(c) < 32 for c in text) or "\\" in text:
        raise ValueError("Unsafe source URL")
    try:
        p = urlsplit(text)
        host = (p.hostname or "").lower().rstrip(".")
        port = p.port
    except ValueError as exc:
        raise ValueError("Invalid source URL") from exc
    if p.scheme not in {"https", "http"} or not host or p.username or p.password:
        raise ValueError("Only public HTTP(S) source links are accepted")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
        raise ValueError("Local network source links are not accepted")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid source hostname") from exc
        if not re.fullmatch(r"[a-z0-9.-]+", ascii_host):
            raise ValueError("Invalid source hostname")
        # Alternative IPv4 spellings should never be handed to a browser.
        if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9.]+)", ascii_host, re.I):
            raise ValueError("Ambiguous numeric source hostname")
    else:
        if not address.is_global:
            raise ValueError("Private network source links are not accepted")
    if port not in (None, 80, 443):
        raise ValueError("Nonstandard source URL port")
    return text


def canonical_url(value: str) -> str:
    p = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(query), ""))


def _record_key(report: dict) -> str:
    return sha256((report["source_id"] + "\0" + report["id"]).encode()).hexdigest()


def _normalise_claims(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    claims = {}
    for name, claim in list(raw.items())[:40]:
        if not isinstance(claim, dict) or "value" not in claim:
            continue
        value = claim["value"]
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, float) and not math.isfinite(value):
            continue
        name = plain_text(name, 80)
        if not name:
            continue
        claims[name] = {"value": plain_text(value, 240) if isinstance(value, str) else value,
                        "unit": plain_text(claim.get("unit"), 60),
                        "as_of": plain_text(claim.get("as_of"), 60),
                        "scope": plain_text(claim.get("scope", "event"), 120)}
    return claims


def _report_is_future(report: dict, stamp: str) -> bool:
    """Evaluate source times, never retrieval time, with the existing 10m tolerance.

    Re-evaluate rather than trusting a flag cached at first collection. A future
    revision time must not let a backdated publication circumvent eligibility.
    Invalid optional revision timestamps are not invented or used as evidence.
    """
    cutoff = _dt(stamp) + timedelta(minutes=10)
    for name in ("published_at", "source_updated_at"):
        if report.get(name):
            try:
                if _dt(report[name]) > cutoff:
                    return True
            except (ValueError, TypeError):
                continue
    return False


def _temporal_change(report: dict, stamp: str) -> dict:
    """A dated notice becoming eligible retains its correction/retraction policy.

    This records a derived eligibility transition, not a new provider message.
    """
    kind = "eligibility"
    if not report.get("future_dated"):
        if report.get("retraction_of") or report.get("kind") == "retraction" or report.get("status") == "retracted":
            kind = "retraction"
        elif report.get("correction_of") or report.get("kind") in {"correction", "cancellation", "warning_update"} or report.get("status") == "corrected":
            kind = "correction"
    return {"kind": kind, "report_id": report["id"], "record_key": report["record_key"],
            "publisher": "Global Pulse", "title": "Source-time eligibility re-evaluated; no new source report",
            "at": stamp, "temporal_reassessment": True}


def normalize_report(raw: dict, now: str | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("A source report must be an object")
    stamp = _iso(now)
    result: dict[str, Any] = {}
    for key, limit in (("id", 500), ("source_id", 150), ("publisher", 180), ("title", 500)):
        result[key] = plain_text(raw.get(key), limit)
        if not result[key]:
            raise ValueError(f"Missing report {key}")
    result["url"] = safe_public_url(raw.get("url"))
    result["retrieved_at"] = _iso(raw.get("retrieved_at") or stamp)
    result["publication_time_known"] = bool(raw.get("published_at")) and not raw.get("publication_time_unknown", False)
    result["publication_time_unknown"] = not result["publication_time_known"]
    result["published_at"] = _iso(raw.get("published_at") or result["retrieved_at"])
    # Future-dated provider records are retained with an explicit flag, not
    # silently treated as already witnessed developments.
    result["future_dated"] = _dt(result["published_at"]) > _dt(stamp) + timedelta(minutes=10)
    defaults = {"summary": "", "language": "und", "region": "Global", "country": "",
                "category": "News", "kind": "report", "origin_id": "", "event_key": "",
                "geo_precision": "unknown", "correction_of": "", "retraction_of": "",
                "official_scope": "statement", "source_country": ""}
    for key, default in defaults.items():
        result[key] = plain_text(raw.get(key, default), 4000 if key == "summary" else 500) or default
    result["language"] = result["language"].lower().replace("_", "-")
    result["independence"] = raw.get("independence") if raw.get("independence") in {"original", "syndicated", "unknown"} else "unknown"
    result["severity"] = str(raw.get("severity", "unassessed")).lower()
    if result["severity"] not in SEVERITY:
        result["severity"] = "unassessed"
    result["synthetic"] = raw.get("synthetic") is True
    result["official"] = raw.get("official") is True
    result["metadata_only"] = raw.get("metadata_only") is True
    result["claims"] = _normalise_claims(raw.get("claims"))
    result["latitude"] = result["longitude"] = None
    lat, lon = raw.get("latitude"), raw.get("longitude")
    if lat is not None and lon is not None:
        try:
            lat, lon = float(lat), float(lon)
            if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                result["latitude"], result["longitude"] = lat, lon
        except (ValueError, TypeError):
            pass
    if result["latitude"] is None:
        result["geo_precision"] = "unknown"
    elif result["geo_precision"] == "source_point":
        result["geo_precision"] = "approximate"
    elif result["geo_precision"] not in {"exact", "approximate", "regional", "country", "unknown"}:
        result["geo_precision"] = "unknown"
    result["media"] = []
    # A reviewed metadata-only source must not persist media even if a
    # hostile feed or alternate adapter supplies an embedded-media field.
    for media in ([] if result["metadata_only"] else (raw.get("media") or [])[:30]):
        if not isinstance(media, dict):
            continue
        try:
            media_url = safe_public_url(media.get("url"))
        except ValueError:
            continue
        media_record = {"url": media_url, "title": plain_text(media.get("title"), 300),
                        "provider": plain_text(media.get("provider"), 120),
                        "type": plain_text(media.get("type", "link"), 50),
                        "embed_allowed": media.get("embed_allowed") is True,
                        "status": plain_text(media.get("status", "availability unverified"), 120)}
        # Preserve a truthful tuned-station identity end-to-end. Directory
        # links without all three fields remain directories and cannot become
        # presets or event-follow targets merely by passing through storage.
        if "radio" in media_record["type"].lower() or "sdr" in media_record["type"].lower():
            receiver = plain_text(media.get("receiver"), 2048)
            frequency = plain_text(media.get("frequency"), 80)
            mode = plain_text(media.get("mode"), 40).upper()
            if receiver and frequency and mode:
                try:
                    receiver = safe_public_url(receiver)
                except ValueError:
                    # A media link may be public while a claimed receiver points
                    # at localhost/private infrastructure. Drop that tuned media
                    # item rather than carrying an unsafe station identity.
                    continue
                if (not re.fullmatch(r"[A-Za-z0-9 .,+/_-]+", frequency)
                        or not any(char.isdigit() for char in frequency)
                        or not re.fullmatch(r"[A-Z0-9 +/_-]+", mode)):
                    continue
                media_record.update({
                    "receiver": receiver,
                    "frequency": frequency,
                    "mode": mode,
                    "name": plain_text(media.get("name") or media.get("title"), 120),
                })
        result["media"].append(media_record)
    result["status"] = raw.get("status") if raw.get("status") in {"active", "corrected", "retracted"} else "active"
    try:
        result["retention_days"] = max(1, min(3650, int(raw.get("retention_days", 365))))
    except (TypeError, ValueError):
        result["retention_days"] = 365
    for key in ("english_title", "english_summary", "translation_label", "license_note",
                "source_license", "attribution", "byline", "source_updated_at"):
        if raw.get(key):
            result[key] = plain_text(raw[key], 2000)
    if raw.get("original_url"):
        result["original_url"] = safe_public_url(raw["original_url"])
    result["source_references"] = []
    for reference in (raw.get("source_references") or [])[:40]:
        if isinstance(reference, str):
            reference = {"url": reference}
        if not isinstance(reference, dict):
            continue
        link = reference.get("url") or reference.get("@id")
        try:
            url = safe_public_url(link) if link else ""
        except ValueError:
            url = ""
        identifier = plain_text(reference.get("identifier") or reference.get("id"), 500)
        if not url and not identifier:
            continue
        result["source_references"].append({"url": url, "id": identifier,
            "identifier": identifier, "sender": plain_text(reference.get("sender"), 300),
            "sent": plain_text(reference.get("sent"), 100),
            "publisher": plain_text(reference.get("publisher") or reference.get("name"), 200),
            "type": plain_text(reference.get("type", "source"), 100)})
    result.update(normalize_map_fields(raw))
    normalize_lifecycle(raw, result, stamp)
    result["future_dated"] = _report_is_future(result, stamp)
    result["record_key"] = _record_key(result)
    return result


def _report_fingerprint(report: dict) -> str:
    return _hash({k: v for k, v in report.items() if k not in {"retrieved_at", "future_dated", "expired"}})


def _tokens(value: str) -> set[str]:
    return {t for t in re.findall(r"[^\W_]+", value.lower(), re.UNICODE) if (len(t) > 1 or t.isdigit()) and t not in IGNORED_WORDS}


def _content_key(report: dict) -> str:
    return _hash({"title": plain_text(report["title"]).lower(),
                  "summary": plain_text(report["summary"]).lower(),
                  "claims": report.get("claims", {})})


def _evidence_reports(reports: list[dict], at: str | None = None) -> tuple[list[dict], list[dict]]:
    """Resolve eligible same-origin notices without losing deferred source data.

    Future notices cannot supersede present evidence. All derived annotations
    are rebuilt, including on muted-source projections and historical reads.
    """
    labelled = []
    for original in reports:
        report = {k: v for k, v in original.items()
                  if k not in {"evidence_status", "superseded_by", "unresolved_reference"}}
        future = _report_is_future(report, at) if at else bool(report.get("future_dated"))
        report["future_dated"] = future
        report["evidence_status"] = "future" if future else report.get("status", "active")
        labelled.append(report)
    for report in labelled:
        if report["future_dated"]:
            continue
        for field, status in (("correction_of", "corrected"), ("retraction_of", "retracted")):
            ref = report.get(field)
            if not ref:
                continue
            candidates = [r for r in labelled if r["record_key"] == ref or r["id"] == ref
                          or f"{r['source_id']}:{r['id']}" == ref]
            permitted = [r for r in candidates if not r["future_dated"] and
                         (r["source_id"] == report["source_id"]
                          or (r.get("origin_id") and r["origin_id"] == report.get("origin_id")))]
            if len(permitted) == 1 and permitted[0]["record_key"] != report["record_key"]:
                target = permitted[0]
                target["evidence_status"] = status
                target["superseded_by"] = report["record_key"]
            else:
                report["unresolved_reference"] = ref
    apply_lifecycle(labelled, at)
    active = [r for r in labelled if r["evidence_status"] == "active"
              and r["kind"] not in {"retraction", "commentary", "repost"}]
    return active, labelled


def _independent(reports: list[dict]) -> list[str]:
    origins: list[str] = []
    seen_content: set[str] = set()
    for report in reports:
        if report.get("independence") != "original" or not report.get("origin_id"):
            continue
        if report.get("kind") in {"social", "repost", "commentary", "video", "radio", "retraction"}:
            continue
        # Government sources contribute attribution and measurements separately;
        # a repeated government assertion does not corroborate its own claim.
        if report.get("official") and report.get("official_scope") != "measurement":
            continue
        content = _content_key(report)
        if content in seen_content:
            continue
        seen_content.add(content)
        if report["origin_id"] not in origins:
            origins.append(report["origin_id"])
    return sorted(origins)


def _conflicts(reports: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for report in reports:
        for metric, claim in report.get("claims", {}).items():
            key = (metric, claim.get("unit", ""), claim.get("as_of", ""), claim.get("scope", "event"))
            grouped[key].append({**claim, "report_id": report["id"], "record_key": report["record_key"],
                                 "publisher": report["publisher"], "source_id": report["source_id"],
                                 "origin_id": report.get("origin_id") or report["source_id"], "url": report["url"]})
    conflicts = []
    for (metric, unit, as_of, scope), claims in grouped.items():
        distinct = {_json(c["value"]) for c in claims}
        origins = {c["origin_id"] for c in claims}
        if len(distinct) < 2 or len(origins) < 2:
            continue
        temporal = bool(as_of)
        conflicts.append({"metric": metric, "unit": unit, "as_of": as_of, "scope": scope,
                          "kind": "conflicting_claims" if temporal else "potential_discrepancy",
                          "claims": claims,
                          "explanation": (f"Sources report different {metric.replace('_', ' ')} values for {as_of}; no value has been selected as true."
                                          if temporal else f"Different {metric.replace('_', ' ')} claims lack a shared observation time; they may describe revisions or different periods.")})
    return conflicts[:50]


def _excerpt(text: str, limit: int = 360) -> str:
    text = plain_text(text, limit + 200)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
    return text.rstrip(". ")


def _recap(reports: list[dict], verification: str, contradictions: list[dict], status: str) -> tuple[str, str]:
    eligible = [r for r in reports if not r.get("future_dated")]
    if not eligible:
        preferred = min(reports, key=lambda r: r["published_at"])
        return ("Future-dated report: " + (preferred.get("english_title") or preferred["title"]),
                "All associated source records are future-dated. They are retained for review, "
                "but do not establish a current event, significance, location or verification.")
    active = [r for r in eligible if r.get("evidence_status") == "active"]
    candidates = sorted(active or eligible,
                        key=lambda r: (bool(r.get("correction_of") or r.get("retraction_of")),
                                       r["language"].startswith("en") or bool(r.get("english_title")),
                                       r["published_at"]), reverse=True)
    preferred = candidates[0]
    english = preferred["language"].startswith("en") or bool(preferred.get("english_title"))
    title = preferred.get("english_title") or preferred["title"]
    source = preferred["publisher"]
    if status == "cancelled":
        summary = f"{source} cancelled the referenced warning. The original warning and the cancellation remain in the evidence history."
    elif status == "expired":
        summary = "The source-specified warning expiry has passed. This is not a new provider cancellation or a claim that the hazard is over."
    elif status == "pending" and eligible:
        summary = "This source notice refers to an unavailable or ambiguous earlier warning. Its original text and references are preserved; the lifecycle is not fully resolved."
    elif status == "retracted":
        summary = f"The reporting behind this event has been retracted or withdrawn. The original records and source notices remain available for review."
    elif not english:
        summary = f"{source} published a {preferred['language']} report. A reliable English translation is not available yet; consult the original source or use Translate."
    else:
        body = preferred.get("english_summary") or preferred.get("summary") or title
        # This is an attributed, bounded extract, not an invented synthesis.
        summary = f"{source} reports: “{_excerpt(body)}”."
        if preferred.get("official"):
            if preferred.get("official_scope") == "measurement":
                summary += " This is an official measurement; preliminary values may be revised."
            else:
                summary += " This confirms publication of the official statement, not every underlying claim."
        elif verification == "unverified":
            summary += " Independent corroboration has not been established."
        elif verification == "developing":
            summary += " At least two documented reporting origins are associated with this developing event."
        elif verification == "corroborated":
            summary += " Multiple documented reporting origins corroborate the event association; individual claims still require review."
    if contradictions:
        summary += " Sources contain conflicting or potentially differing claims; compare their evidence and observation times."
    if preferred.get("translation_label"):
        summary += " Machine-translated text."
    return title, summary


def _build_event(event_id: str, reports: list[dict], *, previous: dict | None, stamp: str,
                 changes: list[dict]) -> dict:
    active, labelled = _evidence_reports(reports, stamp)
    eligible = [r for r in labelled if not r["future_dated"]]
    origins = _independent(active)
    conflicts = _conflicts(active)
    official_measurements = [r for r in active if r.get("official") and r.get("official_scope") == "measurement"]
    if conflicts:
        verification = "developing" if len(origins) >= 2 else "unverified"
    elif official_measurements:
        verification = "official"
    elif len(origins) >= 3:
        verification = "corroborated"
    elif len(origins) >= 2:
        verification = "developing"
    else:
        verification = "unverified"
    status = "active" if active else "retracted" if eligible else "pending"
    warnings = [r for r in eligible if r.get("cap_message_type")]
    if warnings and not active:
        if any(r.get("cap_message_type") == "Cancel" and r.get("lifecycle_resolved") for r in warnings):
            status = "cancelled"
        elif any(r.get("evidence_status") == "expired" for r in warnings):
            status = "expired"
        else:
            status = "pending"
    title, recap = _recap(labelled, verification, conflicts, status)
    primary = sorted(active or eligible or labelled, key=lambda r: (r.get("official_scope") == "measurement",
                                                     r["published_at"]), reverse=True)[0]
    severity = max((r["severity"] for r in active or eligible), key=lambda s: SEVERITY[s], default="unassessed")
    geo_reports = [r for r in active or eligible if r.get("latitude") is not None]
    geo = geo_reports[0] if geo_reports else primary if eligible else {
        "latitude": None, "longitude": None, "geo_precision": "unknown"}
    if len(geo_reports) > 1:
        # Widely different locations cannot be collapsed into an invented pin.
        if any(abs(r["latitude"] - geo["latitude"]) > 2 or
               min(abs(r["longitude"] - geo["longitude"]), 360 - abs(r["longitude"] - geo["longitude"])) > 2
               for r in geo_reports[1:]):
            geo = {"latitude": None, "longitude": None, "geo_precision": "unknown"}
    official_attribution = any(r.get("official") for r in active)
    syndicated = sum(r["independence"] == "syndicated" for r in reports)
    reasons = [f"{len(origins)} documented independent reporting origin(s); unknown provenance is not counted."]
    if official_attribution:
        reasons.append("Official source attribution is present; statements and underlying factual claims are evaluated separately.")
    if syndicated:
        reasons.append(f"{syndicated} syndicated report(s) remain in the evidence trail and add no independent confirmation.")
    if len(reports) <= 5:
        reasons.append("Limited coverage within the monitored source set; this does not establish global underreporting.")
    if conflicts:
        reasons.append(f"{len(conflicts)} conflicting or potentially differing claim group(s) need review.")
    corrections = [r for r in eligible if not r.get("unresolved_reference") and
                   (r.get("correction_of") or r.get("retraction_of") or
                    r["kind"] in {"correction", "retraction", "cancellation", "warning_update"})]
    effective = {r["record_key"]: _content_key(r) + ":" + r["kind"] for r in corrections}
    prior_effective = (previous or {}).get("effective_notices", {})
    changed_keys = {c.get("record_key") for c in changes}
    changes = list(changes)
    for r in corrections:
        if previous is not None and effective[r["record_key"]] != prior_effective.get(r["record_key"]) and r["record_key"] not in changed_keys:
            changes.append({"kind": "retraction" if r["kind"] == "retraction" or r.get("retraction_of") else "correction",
                            "report_id": r["id"], "record_key": r["record_key"], "publisher": r["publisher"],
                            "title": "Stored source notice became effective", "at": stamp, "temporal_reassessment": True})
    # Durable, source-scoped peak significance. Older source data never lends
    # severity to another source, and expiration/retention clears the history.
    present_sources = {r["source_id"] for r in labelled}
    previous_history = (previous or {}).get("significance_history", {})
    history = {source: level for source, level in previous_history.items()
               if source in present_sources and isinstance(level, str) and level in SEVERITY}
    for key, item in previous_history.items():
        # Compatible read of local draft archives which temporarily keyed by
        # record identity; persisted representation remains source -> severity.
        if isinstance(item, dict):
            source, level = item.get("source_id"), item.get("severity")
            if source in present_sources and level in SEVERITY and SEVERITY[level] > SEVERITY.get(history.get(source), -1):
                history[source] = level
    for r in eligible:
        if not (r.get("official") or r.get("independence") == "original" and r.get("origin_id")):
            continue
        source = r["source_id"]
        if SEVERITY[r["severity"]] > SEVERITY.get(history.get(source), -1):
            history[source] = r["severity"]
    if len(eligible) != len(labelled):
        reasons.append(f"Future-dated source records remain reviewable but are excluded from current verification, significance, locations and corroboration. Deferred records: {len(labelled) - len(eligible)}.")
    if corrections:
        reasons.append("A correction or retraction is preserved in the timeline.")
    if geo.get("geo_precision") in {"country", "regional", "approximate", "unknown"}:
        reasons.append("Location is approximate or unavailable; no precise incident position is inferred.")
    material_reports = [r for r in active if (r.get("independence") == "original" and r.get("origin_id")) or r.get("official")]
    # Deduplicate syndicated and identical content in the alert key. Retrieval
    # times, report order, and mere count changes are deliberately excluded.
    evidence_signature = sorted({_hash({"origin": r.get("origin_id") or r["source_id"],
                                       "content": _content_key(r), "official": r.get("official"),
                                       "scope": r.get("official_scope")}) for r in material_reports})
    material = {"evidence": evidence_signature, "verification": verification, "severity": severity,
                "status": status, "origins": origins,
                "corrections": sorted({_hash({"source": r["source_id"], "id": r["id"], "content": _content_key(r)}) for r in corrections})}
    event = {"id": event_id, "merged_source_events": (previous or {}).get("merged_source_events", []), "significance_history": history, "effective_notices": effective, "evidence_policy_version": 3, "future_dated": not bool(eligible),
             "title": title, "recap": recap, "category": primary["category"],
             "region": primary["region"], "country": primary["country"],
             "latitude": geo.get("latitude"), "longitude": geo.get("longitude"),
             "geo_precision": geo.get("geo_precision", "unknown"), "severity": severity,
             "verification": verification,
             "verification_scope": "official measurement" if verification == "official" else "event association; inspect individual claims",
             "official_attribution": official_attribution, "status": status,
             "created_at": previous["created_at"] if previous else stamp, "updated_at": stamp,
             "published_at": min(r["published_at"] for r in reports),
             "publication_time_known": all(r.get("publication_time_known", True) for r in reports),
             "publication_time_unknown": any(not r.get("publication_time_known", True) for r in reports),
             "first_retrieved_at": previous.get("first_retrieved_at", stamp) if previous else stamp,
             "report_count": len(reports), "independent_origins": origins, "contradictions": conflicts,
             "reasons": reasons, "reports": labelled, "media": [], "synthetic": any(r["synthetic"] for r in reports),
             "revision": previous["revision"] + 1 if previous else 1,
             "material_signature": _hash(material), "changes": changes,
             "emerging": SEVERITY[severity] >= 2 and len(reports) <= 5 and (official_attribution or len(origins) >= 2),
             "dimensions": {"evidence_quality": "official measurement" if official_measurements else "source-attributed reports",
                            "source_independence": len(origins), "potential_significance": severity,
                            "historical_abnormality": "Insufficient local baseline for an abnormality claim.",
                            "coverage_volume": len(reports), "reporting_changes": len(changes),
                            "contradictory_information": len(conflicts)}}
    event["map_areas"] = event_areas(active)
    seen_media = set()
    for report in eligible:
        for media in report.get("media", []):
            if all(media.get(key) for key in ("receiver", "frequency", "mode")):
                identity = (media["url"], str(media["receiver"]), str(media["frequency"]), str(media["mode"]))
            else:
                identity = (media["url"],)
            if identity not in seen_media:
                seen_media.add(identity)
                event["media"].append(dict(media, report_id=report["id"]))
    return event


def alert_reason(event: dict, previous: dict | None = None) -> str | None:
    """Default policy, before user thresholds, quiet hours and delivery controls."""
    if event.get("future_dated") or all(r.get("future_dated") for r in event.get("reports", []) or [{}]):
        return None
    changes = event.get("changes", [])
    significant = SEVERITY.get(event.get("severity"), 0) >= 2 or any(SEVERITY.get(level, 0) >= 2 for level in event.get("significance_history", {}).values())
    if previous:
        significant |= SEVERITY.get(previous.get("severity"), 0) >= 2
    changed_records = {c.get("record_key"): c.get("kind") for c in changes}
    notices = [r for r in event.get("reports", [])
               if r.get("publication_time_known", True) and not r.get("future_dated")
               and not r.get("unresolved_reference")
               and (r.get("official") or (r.get("independence") == "original" and r.get("origin_id")))]
    if significant and any(changed_records.get(r.get("record_key")) == "retraction" for r in notices):
        return "Retraction: a source withdrew or retracted reporting on this event."
    if significant and any(changed_records.get(r.get("record_key")) == "correction" for r in notices):
        return "Correction: a source published a material correction to this event."
    if previous and previous.get("material_signature") == event.get("material_signature"):
        return None
    active = [r for r in event.get("reports", []) if r.get("evidence_status", "active") == "active" and not r.get("expired")
              and r.get("publication_time_known", True) and not r.get("future_dated")]
    if significant and any(r.get("official") for r in active):
        return "Official announcement: a significant attributed official update is available."
    if len(_independent(active)) >= 2:
        return "Developing event: at least two documented independent reporting origins are available."
    return None


def muted_source_ids(values: Any) -> set[str]:
    """Return only literal saved source IDs; ignore malformed JSON members.

    Local settings can contain non-string, including unhashable, values after
    import/corruption. These are not identities and must not abort alerts.
    Do not iterate scalar strings as a sequence of one-character source IDs.
    """
    if isinstance(values, (str, bytes, dict)) or not isinstance(values, Iterable):
        return set()
    return {source for source in values if isinstance(source, str)}


def notification_view(event: dict | None, muted_sources: Iterable[str] = ()) -> dict | None:
    """An alert-policy projection that excludes muted sources' evidence.

    The archive and feed retain the full source trail. This projection prevents
    a muted official report or critical impact from lending significance or
    confirmation to an otherwise unverified, unmuted repost.
    """
    if not event:
        return None
    muted = muted_source_ids(muted_sources)
    if not muted:
        return event
    reports = [r for r in event.get("reports", []) if r.get("source_id") not in muted]
    if not reports:
        return None
    keys = {r.get("record_key") for r in reports}
    changes = [c for c in event.get("changes", []) if c.get("record_key") in keys]
    projected = _build_event(event["id"], reports, previous=None,
                             stamp=event["updated_at"], changes=changes)
    sources = {r["source_id"] for r in reports}
    projected["significance_history"] = {source: level for source, level in event.get("significance_history", {}).items()
                                         if source not in muted and source in sources}
    projected["created_at"] = event["created_at"]
    projected["revision"] = event["revision"]
    return projected


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_states(source_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 id TEXT PRIMARY KEY, event_key TEXT NOT NULL DEFAULT '', synthetic INTEGER NOT NULL,
 category TEXT NOT NULL, region TEXT NOT NULL, country TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT NOT NULL,
 revision INTEGER NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_updated ON events(updated_at DESC);
CREATE INDEX IF NOT EXISTS events_key ON events(event_key, synthetic);
CREATE TABLE IF NOT EXISTS reports(
 record_key TEXT PRIMARY KEY, source_id TEXT NOT NULL, original_id TEXT NOT NULL,
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 canonical_url TEXT NOT NULL, published_at TEXT NOT NULL, first_seen TEXT NOT NULL,
 retrieved_at TEXT NOT NULL, fingerprint TEXT NOT NULL, retention_days INTEGER NOT NULL,
 body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reports_event ON reports(event_id);
CREATE INDEX IF NOT EXISTS reports_url ON reports(canonical_url);
CREATE INDEX IF NOT EXISTS reports_original ON reports(original_id);
CREATE TABLE IF NOT EXISTS report_revisions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, record_key TEXT NOT NULL REFERENCES reports(record_key) ON DELETE CASCADE,
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 seen_at TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS report_revisions_record ON report_revisions(record_key, id DESC);
CREATE TABLE IF NOT EXISTS event_revisions(
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE, revision INTEGER NOT NULL,
 at TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(event_id,revision));
CREATE INDEX IF NOT EXISTS event_revision_time ON event_revisions(at);
CREATE TABLE IF NOT EXISTS situations(
 event_id TEXT PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
 title TEXT NOT NULL, saved_at TEXT NOT NULL, last_visited_at TEXT,
 last_visited_revision INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS alerts(
 id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL, read_at TEXT, fingerprint TEXT NOT NULL UNIQUE, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS alerts_created ON alerts(created_at DESC);
CREATE TABLE IF NOT EXISTS observations(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, indicator TEXT NOT NULL, country TEXT NOT NULL,
 observation_date TEXT NOT NULL, first_seen TEXT NOT NULL, retrieved_at TEXT NOT NULL,
 fingerprint TEXT NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS observations_search ON observations(indicator,country,observation_date);
CREATE TABLE IF NOT EXISTS observation_revisions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
 at TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
"""


from .archive_storage import write_transaction

class Store:
    """Thread-safe local archive with immutable evidence revisions and FTS5.

    `last_ingest_errors` contains rejected record diagnostics without source
    content. Individual malformed records never prevent valid neighbors from
    being ingested. Database failures raise and roll back the complete batch.
    """

    def __init__(self, path: str | Path, mode: str | None = None):
        if mode not in {None, "live", "synthetic"}:
            raise ValueError("Archive mode must be live or synthetic")
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self.last_ingest_errors: list[dict] = []
        self.last_previous_events: dict[str, dict] = {}
        # Bounded, read-through current Economy evidence. No source content
        # leaves the process; every Store write or external SQLite commit
        # changes the exact token. Serialized data yields independent callers.
        self._observation_cache: tuple[tuple[int, int], str] | None = None
        self._conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if self._conn.execute("PRAGMA page_count").fetchone()[0] == 0:
            self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=15000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA + LIFECYCLE_SCHEMA)
        version = self._conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if version and int(version[0]) > 2:
            self._conn.close()
            raise ValueError("Archive schema is newer than this application; do not downgrade it")
        self._conn.execute("INSERT INTO metadata VALUES('schema_version','2') ON CONFLICT(key) DO UPDATE SET value='2'")
        self.fts_available = True
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS event_search USING fts5(event_id UNINDEXED,title,recap,source_text,tokenize='unicode61')")
        except sqlite3.OperationalError:
            self.fts_available = False
        self._conn.commit()
        if mode:
            existing_mode = self.get_setting("archive_mode")
            if existing_mode and existing_mode != mode:
                self.close()
                raise ValueError("Live and synthetic records require separate archives")
            self.set_setting("archive_mode", mode)

    def _select_event(self, report: dict, now: str) -> str:
        warning = select_warning_event(self, report, now)
        if warning is not None:
            return warning
        existing = self._conn.execute("SELECT event_id FROM reports WHERE record_key=?", (report["record_key"],)).fetchone()
        if existing:
            return existing[0]
        synthetic = int(report["synthetic"])
        if report["event_key"]:
            match = self._conn.execute("SELECT id FROM events WHERE event_key=? AND synthetic=? LIMIT 1", (report["event_key"], synthetic)).fetchone()
            if match:
                return match[0]
            # An explicit upstream event ID separates distinct incidents even
            # when their titles, magnitude and nearby geography look identical.
            seed = ("synthetic:" if synthetic else "live:") + "key:" + report["event_key"]
            return str(uuid5(EVENT_NAMESPACE, seed))
        for field in ("correction_of", "retraction_of"):
            if report.get(field):
                candidates = self._conn.execute("SELECT r.event_id,r.body FROM reports r JOIN events e ON r.event_id=e.id WHERE (r.original_id=? OR r.record_key=?) AND e.synthetic=? LIMIT 20",
                                                (report[field], report[field], synthetic)).fetchall()
                permitted = []
                for row in candidates:
                    target = json.loads(row["body"])
                    if target["source_id"] == report["source_id"] or (target.get("origin_id") and target["origin_id"] == report.get("origin_id")):
                        permitted.append(row["event_id"])
                if len(set(permitted)) == 1:
                    return permitted[0]
        same_url = self._conn.execute("SELECT r.event_id FROM reports r JOIN events e ON e.id=r.event_id WHERE r.canonical_url=? AND e.synthetic=? LIMIT 1",
                                      (canonical_url(report["url"]), synthetic)).fetchone()
        if same_url and (urlsplit(report["url"]).path.strip("/") or urlsplit(report["url"]).query):
            return same_url[0]
        # Deliberately conservative title similarity. No category, location or
        # time matches means no cross-source merge without an explicit event key.
        tokens = _tokens(report["title"])
        if len(tokens) >= 4:
            since = _iso(_dt(report["published_at"]) - timedelta(hours=24))
            until = _iso(_dt(report["published_at"]) + timedelta(hours=24))
            rows = self._conn.execute("SELECT id,body FROM events WHERE synthetic=? AND category=? AND published_at BETWEEN ? AND ? ORDER BY updated_at DESC LIMIT 500",
                                      (synthetic, report["category"], since, until)).fetchall()
            for row in rows:
                event = json.loads(row["body"])
                if not event:
                    # New events are materialized once at the end of the
                    # transaction. Their normalized reports are already stored,
                    # so derive a provisional matching view for later records
                    # in this same batch. Skipping these rows would split valid
                    # same-batch corroboration into separate events.
                    pending_reports = [json.loads(item[0]) for item in self._conn.execute(
                        "SELECT body FROM reports WHERE event_id=? ORDER BY published_at,record_key", (row["id"],))]
                    if not pending_reports:
                        continue
                    event = _build_event(row["id"], pending_reports, previous=None,
                                         stamp=now, changes=[])
                if event.get("country") and report["country"] and event["country"] != report["country"]:
                    continue
                if event["region"] != report["region"]:
                    continue
                other = _tokens(event["title"])
                union = tokens | other
                similarity = len(tokens & other) / len(union) if union else 0
                if similarity < .85:
                    continue
                numbers = re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)", report["title"])
                other_numbers = re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)", event["title"])
                if numbers != other_numbers:
                    continue
                if not report["country"] and (len(tokens) < 6 or tokens != other):
                    continue
                if event.get("latitude") is not None and report.get("latitude") is not None:
                    if abs(event["latitude"] - report["latitude"]) > 2 or abs(event["longitude"] - report["longitude"]) > 2:
                        continue
                return row["id"]
        seed = ("synthetic:" if synthetic else "live:") + ("key:" + report["event_key"] if report["event_key"] else report["record_key"])
        return str(uuid5(EVENT_NAMESPACE, seed))

    def _current_report_versions_unlocked(self, event_id: str, stamp: str) -> tuple[list[dict], list[int]]:
        """Project the most recent *eligible* version per source record.

        The reports table intentionally tracks the newest received version, even
        if its provider revision timestamp is still in the future. An older
        eligible revision must not disappear from current evidence meanwhile.
        The immutable report_revisions rows retain both versions. This is a
        read projection: it never rewrites source history or its timestamps.
        """
        reports, version_ids = [], []
        for row in self._conn.execute(
                "SELECT record_key,body FROM reports WHERE event_id=? ORDER BY published_at,record_key",
                (event_id,)):
            report = json.loads(row["body"])
            chosen_id = None
            if _report_is_future(report, stamp):
                # Only consult history when the latest received version is
                # deferred. The common eligible path remains one indexed lookup.
                for version in self._conn.execute(
                        "SELECT id,body FROM report_revisions "
                        "WHERE record_key=? AND event_id=? ORDER BY id DESC",
                        (row["record_key"], event_id)):
                    prior = json.loads(version["body"])
                    if not _report_is_future(prior, stamp):
                        report, chosen_id = prior, version["id"]
                        break
            if chosen_id is None:
                latest = self._conn.execute(
                    "SELECT max(id) FROM report_revisions WHERE record_key=? AND event_id=?",
                    (row["record_key"], event_id)).fetchone()
                chosen_id = latest[0] if latest else None
            # Refresh only projected eligibility/expiry; retain original
            # provider publication/revision times in every stored version.
            report["future_dated"] = _report_is_future(report, stamp)
            report["expired"] = is_expired(report, stamp)
            reports.append(report)
            if chosen_id is not None:
                version_ids.append(chosen_id)
        return reports, version_ids

    def ingest(self, reports: Iterable[dict], now: str | None = None) -> list[dict]:
        stamp = _iso(now)
        valid = []
        had_input = False
        self.last_ingest_errors = []
        for i, raw in enumerate(reports):
            had_input = True
            if i >= MAX_BATCH:
                self.last_ingest_errors.append({"index": i, "error": "Batch exceeds 2000 records; remaining records rejected"})
                break
            try:
                valid.append(normalize_report(raw, stamp))
            except (TypeError, ValueError) as exc:
                self.last_ingest_errors.append({"index": i, "error": str(exc)})
        touched: dict[str, list[dict]] = defaultdict(list)
        with self._lock, write_transaction(self._conn, self.path):
            self.last_previous_events = {}
            mode = self.get_setting("archive_mode")
            if valid and not mode:
                mode = "synthetic" if valid[0]["synthetic"] else "live"
                self._conn.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("archive_mode", _json(mode)))
            accepted = []
            for report in valid:
                if report["synthetic"] != (mode == "synthetic"):
                    self.last_ingest_errors.append({"error": "Live and synthetic records require separate archives"})
                else:
                    accepted.append(report)
            valid = accepted
            if had_input and not valid:
                return []  # Rejected input must not cause temporal/archive mutations.
            report_count = self._conn.execute("SELECT count(*) FROM reports").fetchone()[0]
            event_count = self._conn.execute("SELECT count(*) FROM events").fetchone()[0]
            for report in valid:
                key = report["record_key"]
                row = self._conn.execute("SELECT fingerprint,event_id,body FROM reports WHERE record_key=?", (key,)).fetchone()
                fingerprint = _report_fingerprint(report)
                if row and row["fingerprint"] == fingerprint:
                    prior_report = json.loads(row["body"])
                    if bool(prior_report.get("future_dated")) != report["future_dated"] or bool(prior_report.get("expired", False)) != bool(report.get("expired", False)):
                        event_id = row["event_id"]
                        if event_id not in touched:
                            self.last_previous_events[event_id] = self._get_event_unlocked(event_id)
                        touched[event_id].append(_temporal_change(report, stamp))
                    self._conn.execute("UPDATE reports SET retrieved_at=?,body=? WHERE record_key=?", (report["retrieved_at"], _json(report), key))
                    continue
                if not row and report_count >= MAX_REPORTS:
                    self.last_ingest_errors.append({"error": "Archive capacity reached; export and prune older records"})
                    continue
                # An updated record retains the identity of its original event.
                event_id = row["event_id"] if row else self._select_event(report, stamp)
                previous = self._conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
                if previous and event_id not in touched:
                    self.last_previous_events[event_id] = self._get_event_unlocked(event_id)
                if not previous:
                    if event_count >= MAX_EVENTS:
                        self.last_ingest_errors.append({"error": "Event archive capacity reached; export and prune older events"})
                        continue
                    # Placeholder is confined to the transaction and is replaced
                    # with a complete derived event before commit.
                    self._conn.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                       (event_id, report["event_key"], int(report["synthetic"]), report["category"], report["region"], report["country"], stamp, stamp, report["published_at"], 0, "{}"))
                    event_count += 1
                register_warning(self._conn, report, event_id)
                if row:
                    self._conn.execute("UPDATE reports SET fingerprint=?,published_at=?,retrieved_at=?,retention_days=?,body=? WHERE record_key=?",
                                       (fingerprint, report["published_at"], report["retrieved_at"], report["retention_days"], _json(report), key))
                else:
                    self._conn.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                       (key, report["source_id"], report["id"], event_id, canonical_url(report["url"]), report["published_at"], stamp, report["retrieved_at"], fingerprint, report["retention_days"], _json(report)))
                    report_count += 1
                self._conn.execute("INSERT INTO report_revisions(record_key,event_id,seen_at,fingerprint,body) VALUES(?,?,?,?,?)",
                                   (key, event_id, stamp, fingerprint, _json(report)))
                kind = "retraction" if report.get("retraction_of") or report["kind"] == "retraction" or report["status"] == "retracted" else (
                    "correction" if report.get("correction_of") or report["kind"] in {"correction", "cancellation", "warning_update"} or report["status"] == "corrected" else "updated" if row else "report")
                # A new future version of an already eligible record is stored
                # but is not yet an effective correction, retraction, or alert.
                # Temporal refresh will activate it once at the source-time
                # eligibility boundary, including on an otherwise empty poll.
                prior_eligible = bool(row) and any(
                    r["record_key"] == key and not r["future_dated"]
                    for r in self._current_report_versions_unlocked(event_id, stamp)[0])
                if not (report["future_dated"] and prior_eligible):
                    # A future-only record is archive evidence, not an effective
                    # correction/retraction. Never label an older eligible
                    # projection with the kind of a deferred incoming version.
                    if report["future_dated"]:
                        kind = "eligibility"
                    touched[event_id].append({"kind": kind, "report_id": report["id"], "record_key": key,
                                              "publisher": report["publisher"], "title": report["title"], "at": stamp})
            self._refresh_temporal_evidence_unlocked(stamp, touched)
            canonical_touched = defaultdict(list)
            for event_id, changes in touched.items():
                canonical_touched[canonical_event(self._conn, event_id)].extend(changes)
            touched = canonical_touched
            for event_id, changes in touched.items():
                self._rebuild(event_id, stamp, changes)
            return [self._get_event_unlocked(event_id) for event_id in touched]

    def _refresh_temporal_evidence_unlocked(self, stamp: str, touched: dict) -> None:
        """Compare effective versions, not only the newest received row's flags.

        A newest row can remain deferred while an intermediate version becomes
        eligible. The saved event revision identifies the previously effective
        inputs; compare those with the same projection used by _rebuild. Empty
        and unchanged polls therefore record each observed transition once.
        Source revisions and provider/retrieval timestamps are never invented.
        """
        cutoff = _iso(_dt(stamp) + timedelta(minutes=10))
        candidates = set(touched)
        after = ""
        while True:
            rows = self._conn.execute(
                "SELECT r.record_key,r.event_id,r.body FROM reports r "
                "WHERE r.record_key>? AND "
                "(r.body LIKE ? OR r.published_at>? OR r.body LIKE ?) ORDER BY r.record_key LIMIT 128",
                (after, '%"future_dated":true%', cutoff, '%"expires_at":%')).fetchall()
            if not rows:
                break
            after = rows[-1]["record_key"]
            for row in rows:
                candidates.add(row["event_id"])
                report = json.loads(row["body"])
                future = _report_is_future(report, stamp)
                expired = is_expired(report, stamp)
                if (future != bool(report.get("future_dated"))
                        or expired != bool(report.get("expired", False))):
                    report.update(future_dated=future, expired=expired)
                    self._conn.execute("UPDATE reports SET body=? WHERE record_key=?",
                                       (_json(report), row["record_key"]))

        for event_id in sorted(candidates):
            row = self._conn.execute("SELECT body,revision FROM events WHERE id=?", (event_id,)).fetchone()
            if not row or row["body"] == "{}":
                continue  # A new event is already in touched and has no prior snapshot.
            cached = json.loads(row["body"])
            saved = self._conn.execute(
                "SELECT body FROM event_revisions WHERE event_id=? AND revision=?",
                (event_id, row["revision"])).fetchone()
            if not saved:
                continue
            versions = json.loads(saved["body"])["report_versions"]
            prior_by_key = {}
            # Read in bounded groups; a large event must not exceed SQLite's
            # variable limit or require rewriting its immutable source versions.
            for offset in range(0, len(versions), 128):
                ids = versions[offset:offset + 128]
                for item in self._conn.execute(
                        "SELECT body FROM report_revisions WHERE id IN (%s)" % ",".join("?" * len(ids)), ids):
                    previous_report = json.loads(item["body"])
                    prior_by_key[previous_report["record_key"]] = previous_report
            current, _ = self._current_report_versions_unlocked(event_id, stamp)
            changed_keys = {c.get("record_key") for c in touched.get(event_id, [])}
            legacy = cached.get("evidence_policy_version", 0) < 2
            for report in current:
                key = report["record_key"]
                prior = prior_by_key.get(key)
                if prior is None or key in changed_keys:
                    continue  # A newly received effective record has its input change.
                version_changed = _report_fingerprint(prior) != _report_fingerprint(report)
                eligibility_changed = _report_is_future(prior, cached["updated_at"]) != report["future_dated"]
                expiry_changed = is_expired(prior, cached["updated_at"]) != report["expired"]
                if not (version_changed or eligibility_changed or expiry_changed or legacy):
                    continue
                if event_id not in self.last_previous_events:
                    # Use the saved snapshot: current rows may already contain
                    # incoming data which did not support the prior event header.
                    self.last_previous_events[event_id] = self._get_event_unlocked(
                        event_id, at=cached["updated_at"])
                if expiry_changed and not (version_changed or eligibility_changed):
                    change = {"kind": "expiry", "report_id": report["id"], "record_key": key,
                              "publisher": report["publisher"], "at": stamp,
                              "title": "Source-specified warning expiry reached; not a new source report"}
                else:
                    change = _temporal_change(report, stamp)
                touched[event_id].append(change)
                changed_keys.add(key)

    def _rebuild(self, event_id: str, stamp: str, changes: list[dict]) -> dict:
        row = self._conn.execute("SELECT body FROM events WHERE id=?", (event_id,)).fetchone()
        previous = json.loads(row[0]) if row and row[0] != "{}" else None
        reports, selected_revision_ids = self._current_report_versions_unlocked(event_id, stamp)
        retention_rebuild = any(c.get("kind") == "retention" for c in changes)
        if previous and ("significance_history" not in previous or retention_rebuild):
            # Backfill from retained source revisions after pruning; never revive
            # an expired record's significance or a future-dated source claim.
            history = {}
            for saved in self._conn.execute("SELECT body,seen_at FROM report_revisions WHERE event_id=? AND seen_at<=? ORDER BY id", (event_id, stamp)):
                original = json.loads(saved["body"])
                if (_report_is_future(original, saved["seen_at"])
                        or not (original.get("official") or original.get("independence") == "original")
                        or original.get("status", "active") != "active"
                        or original.get("kind") in {"retraction", "commentary", "repost"}):
                    continue
                source, level = original["source_id"], original["severity"]
                if SEVERITY[level] > SEVERITY.get(history.get(source), -1):
                    history[source] = level
            previous = dict(previous, significance_history=history)
        event = _build_event(event_id, reports, previous=previous, stamp=stamp, changes=changes)
        body = {k: v for k, v in event.items() if k not in {"reports", "timeline"}}
        self._conn.execute("UPDATE events SET category=?,region=?,country=?,updated_at=?,published_at=?,revision=?,body=? WHERE id=?",
                           (event["category"], event["region"], event["country"], stamp, event["published_at"], event["revision"], _json(body), event_id))
        self._conn.execute("INSERT INTO event_revisions VALUES(?,?,?,?)", (event_id, event["revision"], stamp, _json({"event": body, "report_versions": selected_revision_ids})))
        if self.fts_available:
            self._conn.execute("DELETE FROM event_search WHERE event_id=?", (event_id,))
            source_text = " ".join(f"{r['publisher']} {r['title']} {r['summary']}" for r in reports)
            self._conn.execute("INSERT INTO event_search(event_id,title,recap,source_text) VALUES(?,?,?,?)", (event_id, event["title"], event["recap"], source_text))
        return event

    def _get_event_unlocked(self, event_id: str, at: str | None = None, *, map_projection: bool = False) -> dict | None:
        event_id = canonical_event(self._conn, event_id, _iso(at) if at else None)
        if at:
            row = self._conn.execute("SELECT body,revision FROM event_revisions WHERE event_id=? AND at<=? ORDER BY revision DESC LIMIT 1", (event_id, _iso(at))).fetchone()
            if not row:
                return None
            saved = json.loads(row["body"])
            event = saved["event"]
            ids = saved["report_versions"]
            reports = [json.loads(r[0]) for r in self._conn.execute("SELECT body FROM report_revisions WHERE id IN (%s) ORDER BY id" % ",".join("?" * len(ids)), ids)] if ids else []
        else:
            row = self._conn.execute("SELECT body,revision FROM events WHERE id=?", (event_id,)).fetchone()
            if not row:
                return None
            event = json.loads(row["body"])
            reports, _ = self._current_report_versions_unlocked(event_id, event["updated_at"])
        if event.get("evidence_policy_version", 0) < 2 and reports:
            # Do not repeat a known E1 overstatement merely because it was
            # cached. Preserve the immutable stored record; annotate the read
            # projection and evaluate the original source versions at that time.
            recorded = event
            event = _build_event(event_id, reports, previous=None,
                                 stamp=recorded["updated_at"], changes=recorded.get("changes", []))
            for key in ("created_at", "first_retrieved_at", "revision"):
                if key in recorded:
                    event[key] = recorded[key]
            event["recorded_verification"] = recorded.get("verification")
            event["classification_recomputed"] = True
        _, event["reports"] = _evidence_reports(reports, event["updated_at"])
        if map_projection:
            # Read-only area context does not promote pending updates into alerts.
            from .warning_context import project_warning_context
            return project_warning_context(event, _iso(at) if at else utcnow())
        event["timeline"] = []
        for revision in self._conn.execute("SELECT at,revision,body FROM event_revisions WHERE event_id=? AND revision<=? ORDER BY revision", (event_id, row["revision"])):
            saved_revision = json.loads(revision["body"])
            snapshot = saved_revision["event"]
            recorded_verification = snapshot.get("verification")
            if snapshot.get("evidence_policy_version", 0) < 2:
                versions = saved_revision.get("report_versions", [])
                originals = [json.loads(r[0]) for r in self._conn.execute(
                    "SELECT body FROM report_revisions WHERE id IN (%s) ORDER BY id" %
                    ",".join("?" * len(versions)), versions)] if versions else []
                if originals:
                    snapshot = _build_event(event_id, originals, previous=None,
                        stamp=snapshot["updated_at"], changes=snapshot.get("changes", []))
            event["timeline"].append({"at": revision["at"], "timestamp": revision["at"], "revision": revision["revision"],
                                      "recorded_verification": recorded_verification,
                                      "title": snapshot["title"], "verification": snapshot["verification"], "severity": snapshot["severity"],
                                      "changes": snapshot.get("changes", []), "description": "; ".join(
                                          f"{c['publisher']}: {c['kind']} — {c['title']}" for c in snapshot.get("changes", []))})
        event["linked_event_histories"] = {}
        for linked in event.get("merged_source_events", []):
            snapshots = []
            for item in self._conn.execute("SELECT at,revision,body FROM event_revisions WHERE event_id=? AND at<=? ORDER BY revision", (linked, event["updated_at"])):
                body = json.loads(item["body"])["event"]
                snapshots.append({"original_event_id": linked, "at": item["at"], "revision": item["revision"],
                                  "title": body["title"], "status": body.get("status"), "changes": body.get("changes", [])})
            if snapshots:
                event["linked_event_histories"][linked] = snapshots
        return event

    def _map_evidence_page_unlocked(self, page: list[sqlite3.Row]) -> list[dict | None]:
        """Batch common stable map reports; preserve exact old projection for exceptions.

        Map country/category circles need every labelled source report, not
        merely the active subset. Historical, legacy, pending NWS, merged and
        deferred-source cases still take the original read-only projection.
        Called only while the Store lock is held.
        """
        saved = [(row, json.loads(row["body"])) for row in page]
        common = []
        expected_counts = {}
        remaining_reports = 8192  # Finite aggregate memory budget per page.
        for row, event in saved:
            count = event.get("report_count")
            if (event.get("status") != "active"
                    or type(event.get("evidence_policy_version")) is not int
                    or not 2 <= event["evidence_policy_version"] <= 3
                    or event.get("merged_source_events")
                    or event.get("map_areas")
                    or type(count) is not int or not 0 <= count <= 64
                    or count > remaining_reports):
                continue
            common.append(row["id"])
            expected_counts[row["id"]] = count
            remaining_reports -= count
        if common:
            placeholders = ",".join("?" for _ in common)
            # A tampered/stale event report_count must not cause an unbounded
            # group load or silently omit evidence. First verify the true
            # indexed row counts before fetching source bodies.
            actual_counts = {
                row["event_id"]: row["n"] for row in self._conn.execute(
                    "SELECT event_id,COUNT(*) AS n FROM reports WHERE event_id IN ("
                    + placeholders + ") GROUP BY event_id", common)
            }
            common = [identity for identity in common
                      if actual_counts.get(identity, 0) == expected_counts[identity]]
        common_ids = set(common)
        grouped = defaultdict(list)
        if common:
            # A page is at most 256 IDs; SQLite parameter bounds and ordering
            # are preserved. This replaces thousands of per-event/per-report
            # SELECT calls without inventing or discarding source evidence.
            sql = ("SELECT event_id,body FROM reports WHERE event_id IN (" +
                   ",".join("?" for _ in common) +
                   ") ORDER BY event_id,published_at,record_key")
            for row in self._conn.execute(sql, common):
                grouped[row["event_id"]].append(json.loads(row["body"]))
        output = []
        for row, event in saved:
            identity = row["id"]
            if identity not in common_ids:
                output.append(self._get_event_unlocked(identity, map_projection=True))
                continue
            at = event["updated_at"]
            reports = grouped.get(identity, [])
            # The latest received revision may still be future by provider time.
            # Only the old history-aware projection can select the earlier
            # eligible immutable report_revisions entry in that case.
            if any(_report_is_future(report, at) or report.get("source_id") == "nws"
                   for report in reports):
                output.append(self._get_event_unlocked(identity, map_projection=True))
                continue
            selected = []
            for raw in reports:
                report = dict(raw)
                report["future_dated"] = False
                report["expired"] = is_expired(report, at)
                selected.append(report)
            _, event["reports"] = _evidence_reports(selected, at)
            # project_warning_context is an identity projection for active
            # records; pending or area-bearing events took the original path.
            output.append(event)
        return output

    def get_event(self, event_id: str, at: str | None = None) -> dict | None:
        with self._lock:
            return self._get_event_unlocked(event_id, at)

    def _current_feed_page_unlocked(self, rows: list[sqlite3.Row]) -> list[dict]:
        """Hydrate a current top-feed page with bounded indexed batch reads.

        The old list_events path performed event alias lookup, event header,
        report history and full revision-timeline SQL separately for EVERY
        event. At 500 rows this delayed a genuine new collector revision beyond
        the owner 7-second no-click window despite a live Qt heartbeat.

        Only ordinary canonical, eligible, E2/E3 records take the batched
        projection. Future notices, historical policy, merges, absent/inexact
        counts and legacy revisions use the original complete per-event reader.
        Source, correction, retraction, chronology and identity are unchanged.
        Called under the same Store RLock as list_events.
        """
        results = []
        for offset in range(0, len(rows), 128):
            page = rows[offset:offset + 128]
            accepted = {}
            for row in page:
                event = json.loads(row["body"])
                count = event.get("report_count")
                if (event.get("id") != row["id"]
                        or type(event.get("evidence_policy_version")) is not int
                        or not 2 <= event["evidence_policy_version"] <= 3
                        or event.get("merged_source_events")
                        or type(count) is not int or not 0 <= count <= 64):
                    continue
                accepted[row["id"]] = event
            reports = defaultdict(list)
            histories = defaultdict(list)
            if accepted:
                ids = list(accepted)
                args = ",".join("?" for _ in ids)
                for item in self._conn.execute(
                        "SELECT event_id,body FROM reports WHERE event_id IN (" +
                        args + ") ORDER BY event_id,published_at,record_key", ids):
                    reports[item["event_id"]].append(json.loads(item["body"]))
                for item in self._conn.execute(
                        "SELECT event_id,at,revision,body FROM event_revisions "
                        "WHERE event_id IN (" + args +
                        ") ORDER BY event_id,revision", ids):
                    histories[item["event_id"]].append(item)
            for row in page:
                identity = row["id"]
                event = accepted.get(identity)
                if event is None:
                    results.append(self._get_event_unlocked(identity))
                    continue
                entries = reports.get(identity, [])
                snapshots = histories.get(identity, [])
                # A pending future publication may require an earlier eligible
                # immutable source revision, not the latest reports row.
                # Preserve that path in the canonical reference reader.
                if (len(entries) != event["report_count"] or not snapshots
                        or any(_report_is_future(report, event["updated_at"])
                               for report in entries)
                        or any(json.loads(item["body"])["event"].get(
                               "evidence_policy_version", 0) < 2
                               for item in snapshots)):
                    results.append(self._get_event_unlocked(identity))
                    continue
                selected = []
                for original in entries:
                    report = dict(original)
                    report["future_dated"] = False
                    report["expired"] = is_expired(report, event["updated_at"])
                    selected.append(report)
                _, event["reports"] = _evidence_reports(selected, event["updated_at"])
                event["timeline"] = []
                for item in snapshots:
                    saved = json.loads(item["body"])["event"]
                    event["timeline"].append({
                        "at": item["at"], "timestamp": item["at"],
                        "revision": item["revision"],
                        "recorded_verification": saved.get("verification"),
                        "title": saved["title"],
                        "verification": saved["verification"],
                        "severity": saved["severity"],
                        "changes": saved.get("changes", []),
                        "description": "; ".join(
                            f"{change['publisher']}: {change['kind']} — {change['title']}"
                            for change in saved.get("changes", [])),
                    })
                event["linked_event_histories"] = {}
                results.append(event)
        return results

    def list_events(self, query: str = "", category: str = "", region: str = "", since: str | None = None,
                    before: str | None = None, limit: int = 500,
                    map_view: bool = False, keep_significant: bool = False,
                    map_evidence: bool = False) -> list[dict]:
        map_view = bool(map_view or map_evidence)
        # map_evidence retains country/area/unlocated records without inventing points.
        # Map membership is independent of the bounded text-feed page. Explicit
        # search/category/region filters still apply; historical views stay strict.
        limit = max(1, min(int(limit), 5000 if map_view else 2000))
        query = plain_text(query, 500)
        with self._lock:
            if before:
                # Historical playback reconstructs what was stored at that time;
                # a later correction or headline never leaks into an old frame.
                rows = self._conn.execute("SELECT DISTINCT event_id FROM event_revisions WHERE at<=? ORDER BY at DESC LIMIT 5000", (_iso(before),))
                events = [self._get_event_unlocked(row[0], before, map_projection=map_evidence) for row in rows]
                words = _tokens(query)
                filtered = [e for e in events if e and (not category or e["category"].lower() == category.lower())
                            and (not region or region.lower() in {e["region"].lower(), e["country"].lower()})
                            and (not since or e["updated_at"] >= _iso(since))
                            and (not words or words <= _tokens(" ".join([e["title"], e["recap"]] + [r["title"] + " " + r["summary"] for r in e["reports"]])))]
                filtered = list({e["id"]: e for e in filtered}.values())
                if map_view:
                    filtered = [e for e in filtered if (e.get("status") == "active" or map_evidence and e.get("map_history_incomplete") is True) and
                                (map_evidence or (e.get("latitude") is not None and e.get("longitude") is not None))]
                return sorted(filtered, key=lambda e: e["updated_at"], reverse=True)[:limit]
            where, params = ["id NOT IN (SELECT alias_id FROM event_aliases)"], []
            if category:
                where.append("lower(category)=lower(?)")
                params.append(category)
            if region:
                where.append("(lower(region)=lower(?) OR lower(country)=lower(?))")
                params.extend((region, region))
            significant = ("json_extract(body,'$.status')='active' AND "
                           "json_extract(body,'$.severity') IN ('critical','high','moderate') AND "
                           "COALESCE(json_extract(body,'$.future_dated'),0)=0")
            if map_view:
                from .warning_context import PENDING_AREA_SQL
                where.append("(json_extract(body,'$.status')='active' OR " + PENDING_AREA_SQL + ")" if map_evidence else "json_extract(body,'$.status')='active'")
                if not map_evidence:
                    where.extend(["json_extract(body,'$.latitude') IS NOT NULL",
                                  "json_extract(body,'$.longitude') IS NOT NULL"])
            if since:
                where.append("(updated_at>=? OR (" + significant + "))" if map_view and keep_significant else "updated_at>=?")
                params.append(_iso(since))
            if query:
                terms = re.findall(r"[^\W_]+", query, re.UNICODE)
                if not terms:
                    return []
                if self.fts_available:
                    fts_query = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms[:30])
                    where.append("id IN (SELECT event_id FROM event_search WHERE event_search MATCH ?)")
                    params.append(fts_query)
                else:
                    for term in terms[:10]:
                        where.append("body LIKE ? ESCAPE '\\'")
                        params.append("%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
            order = ("CASE json_extract(body,'$.severity') WHEN 'critical' THEN 4 WHEN 'high' THEN 3 "
                     "WHEN 'moderate' THEN 2 WHEN 'informational' THEN 1 ELSE 0 END DESC,") if map_view else ""
            sql = ("SELECT body FROM events" if map_view and not map_evidence else
                   "SELECT id,body FROM events" if map_evidence else "SELECT id,body,revision FROM events") + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order + "updated_at DESC,id"
            if map_evidence:
                # PENDING_AREA_SQL is intentionally a broad cheap candidate filter:
                # source history, actual effective/end dates, and missing earlier
                # NWS bulletins must be checked at read time. Applying the user's
                # LIMIT to that *candidate* query drops eligible older warnings
                # when an ineligible newer candidate occupies the page.
                #
                # Page the frozen (Store-locked) ordered SQL set in finite slices,
                # counting only eligible projected events toward the display limit.
                # This reaches the end of the actual stored candidate set instead
                # of hiding later eligible areas behind a larger arbitrary cap.
                result = []
                page_size = min(256, max(32, limit))
                # One ordered, Store-locked cursor avoids re-sorting/re-reading
                # every earlier candidate for each subsequent OFFSET page. A
                # bounded fetchmany keeps materialized rows capped at 256 while
                # the original accepted-only limit and warning checks remain.
                cursor = self._conn.execute(sql, params)
                try:
                    while len(result) < limit:
                        page = cursor.fetchmany(page_size)
                        if not page:
                            break
                        for event in self._map_evidence_page_unlocked(page):
                            if event and (event.get("status") == "active" or
                                          event.get("map_history_incomplete") is True):
                                result.append(event)
                                if len(result) >= limit:
                                    break
                        if len(page) < page_size:
                            break
                finally:
                    cursor.close()
            else:
                page = self._conn.execute(sql + " LIMIT ?", [*params, limit]).fetchall()
                result = ([json.loads(row[0]) for row in page] if map_view
                          else self._current_feed_page_unlocked(page))
            if map_view:
                for item in result:
                    item["retained_on_map"] = bool(keep_significant and since and item["updated_at"] < _iso(since))
                    # This is a display annotation, never a new source assertion.
                    item["map_retention_note"] = ("Retained significant event; no newer status received. Last update "
                                                  + item["updated_at"]) if item["retained_on_map"] else ""
            return result


    def list_brief_events(self, *, since: str, per_domain: int = 9) -> list[dict]:
        """Bounded, category-balanced Brief read without a multi-second Store lock.

        Each event still goes through the canonical history/evidence projection.
        Ranking and source bytes must describe one exact committed Store revision.
        An unchanged source is hydrated with short, individually locked reads so
        the GUI can probe Store availability between them. If source content
        changes while reading, retry; on repeated contention use the original
        atomic path rather than return mixed or fabricated evidence.
        """
        from .brief_selection import _DOMAIN_ALIASES
        count = max(1, min(int(per_domain), 9))
        aliases = sorted(_DOMAIN_ALIASES.items())
        categories = "CASE lower(trim(category)) " + " ".join(
            "WHEN ? THEN ?" for _ in aliases
        ) + " ELSE ? END"
        params = [text for alias, domain in aliases for text in (alias, domain)]
        params.append("General news")
        sql = (
            "SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY "
            + categories +
            " ORDER BY CASE WHEN lower(COALESCE(json_extract(body,'$.status'),'active')) "
            "IN ('retracted','cancelled','canceled','expired','resolved','closed','ended') "
            "THEN 0 ELSE 1 END DESC, "
            "CASE lower(COALESCE(json_extract(body,'$.severity'),'unassessed')) "
            "WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'moderate' THEN 2 "
            "WHEN 'informational' THEN 1 ELSE 0 END DESC, "
            "updated_at DESC, id) AS brief_rank FROM events "
            "WHERE id NOT IN (SELECT alias_id FROM event_aliases) "
            "AND updated_at>=?) WHERE brief_rank<=?"
        )
        values = (*params, _iso(since), count)

        def revision_unlocked():
            # Catch this Store's own writes and other SQLite connections'
            # commits, including changes between individual evidence reads.
            return (self._conn.total_changes,
                    int(self._conn.execute("PRAGMA data_version").fetchone()[0]))

        for _attempt in range(2):
            with self._lock:
                source_revision = revision_unlocked()
                ids = [row[0] for row in self._conn.execute(sql, values)]
            events = []
            for identity in ids:
                with self._lock:
                    event = self._get_event_unlocked(identity)
                if event is not None:
                    events.append(event)
            with self._lock:
                if revision_unlocked() == source_revision:
                    return events

        # With continuous source mutations, preserve the old atomic read.
        # Never return partially mixed revisions just to pass a heartbeat test.
        with self._lock:
            ids = self._conn.execute(sql, values).fetchall()
            return [event for row in ids
                    if (event := self._get_event_unlocked(row[0])) is not None]

    def event_filter_options(self) -> dict[str, list[str]]:
        """Archive-wide selector metadata, independent of any rendered page.

        Read only distinct normalized columns, not thousands of full reports.
        Aliased events remain excluded just as in list_events. A selected value
        absent after pruning is preserved by the UI, never changed to All.
        """
        with self._lock:
            return {
                key: [row[0] for row in self._conn.execute(
                    f"SELECT DISTINCT {key} FROM events "
                    "WHERE id NOT IN (SELECT alias_id FROM event_aliases) "
                    f"AND {key} IS NOT NULL AND {key}<>'' ORDER BY {key}")]
                for key in ("category", "region")
            }

    def iter_events(self, batch_size: int = 100):
        """Yield every archived event in bounded batches, without UI limits.

        The identity list is captured at invocation. Concurrent new events are
        left for the next export; an event removed under retention is omitted.
        Individual evidence records are read while holding the store lock.
        """
        batch_size = max(1, min(int(batch_size), 1000))
        with self._lock:
            identities = [row[0] for row in self._conn.execute("SELECT id FROM events WHERE id NOT IN (SELECT alias_id FROM event_aliases) ORDER BY updated_at DESC,id")]
        for offset in range(0, len(identities), batch_size):
            with self._lock:
                batch = [self._get_event_unlocked(identity) for identity in identities[offset:offset + batch_size]]
            for event in batch:
                if event:
                    yield event

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key=?", (str(key),)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        encoded = _json(value)
        from .capacity_limits import MAX_USER_FEED_SETTING_BYTES
        limit = MAX_USER_FEED_SETTING_BYTES if key == "user_feeds" else 250_000
        if len(encoded.encode("utf-8")) > limit:
            raise ValueError("Setting is too large")
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(key)[:200], encoded))

    def set_settings_atomic(self, settings: dict[str, Any]) -> None:
        """Persist one plain settings snapshot with the existing size limits.

        Validation finishes before any SQL mutation. All rows commit together
        or roll back together; callers must not fan a layout snapshot into
        separate settings transactions or UI refresh signals.
        """
        if not isinstance(settings, dict):
            raise ValueError("Settings snapshot must be a dictionary")
        from .capacity_limits import MAX_USER_FEED_SETTING_BYTES
        encoded = []
        keys = set()
        for key, value in settings.items():
            name = str(key)[:200]
            if name in keys:
                raise ValueError("Settings snapshot contains overlapping keys")
            keys.add(name)
            payload = _json(value)
            limit = MAX_USER_FEED_SETTING_BYTES if key == "user_feeds" else 250_000
            if len(payload.encode("utf-8")) > limit:
                raise ValueError("Setting is too large")
            encoded.append((name, payload))
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                encoded)

    def get_source_state(self, source_id: str) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT body FROM source_states WHERE source_id=?", (source_id,)).fetchone()
            return json.loads(row[0]) if row else {}

    def list_source_states(self, source_ids: Iterable[str]) -> dict[str, dict]:
        """Read only requested provider health in bounded SQLite batches.

        An idle Sources repaint previously acquired the Store lock and ran a
        SELECT for every configured source. One batch per 400 IDs avoids that
        main-thread query fan-out, without caching error/retry checkpoints.
        """
        identities = list(dict.fromkeys(source_ids))
        if any(not isinstance(sid, str) or not sid for sid in identities):
            raise ValueError("Invalid source identity")
        states: dict[str, dict] = {}
        with self._lock:
            for start in range(0, len(identities), 400):
                batch = identities[start:start + 400]
                sql = ("SELECT source_id,body FROM source_states WHERE source_id IN (" +
                       ",".join("?" for _ in batch) + ")")
                for row in self._conn.execute(sql, batch):
                    states[row[0]] = json.loads(row[1])
        return states


    def source_status_snapshot_if_available(self, source_ids: Iterable[str]) -> dict | None:
        """Atomically read provider settings and health without waiting on Qt.

        An initial revision try-lock is not a lease: another collector may
        acquire the Store lock just before Sources health SELECTs. BUSY means
        defer (None), never display an empty or falsely healthy registry.
        No Qt widgets run under this short source-data lock.
        """
        if not self._lock.acquire(blocking=False):
            return None
        try:
            revision = (self._conn.total_changes,
                        int(self._conn.execute("PRAGMA data_version").fetchone()[0]))
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key=?", ("enabled_sources",)
            ).fetchone()
            enabled = json.loads(row[0]) if row else None
            states = self.list_source_states(source_ids)
            return {"revision": revision, "enabled_sources": enabled,
                    "states": states}
        finally:
            self._lock.release()

    def any_source_error(self, source_ids: Iterable[str]) -> bool:
        """One bounded, consistent source-state scan for the native tray icon.

        Query only explicitly enabled identities. A malformed stored state is
        conservatively considered an error; never silently report healthy.
        SQLite's parameter limit is respected for catalogs over 400 sources.
        """
        identities = list(source_ids)
        if any(not isinstance(item, str) or not item for item in identities):
            return True
        identities = list(dict.fromkeys(identities))
        if not identities:
            return False
        statuses = {"error", "rate_limited", "failed"}
        with self._lock:
            for start in range(0, len(identities), 400):
                batch = identities[start:start + 400]
                sql = ("SELECT body FROM source_states WHERE source_id IN (" +
                       ",".join("?" for _ in batch) + ")")
                for row in self._conn.execute(sql, batch):
                    try:
                        state = json.loads(row[0])
                    except (ValueError, TypeError):
                        return True
                    if not isinstance(state, dict):
                        return True
                    status = state.get("status")
                    if "status" in state and not isinstance(status, str):
                        return True  # Malformed list/dict/null cannot crash native tray.
                    if status in statuses:
                        return True
        return False

    def set_source_state(self, source_id: str, state: dict) -> None:
        encoded = _json(state)
        if len(encoded) > 100_000:
            raise ValueError("Source checkpoint is too large")
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO source_states VALUES(?,?) ON CONFLICT(source_id) DO UPDATE SET body=excluded.body", (source_id, encoded))

    def delete_source_state(self, source_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM source_states WHERE source_id=?", (str(source_id)[:200],))

    def saved_situation_ids(self) -> set[str]:
        """Read bookmark identities without loading every event timeline."""
        with self._lock:
            return {row[0] for row in self._conn.execute("SELECT event_id FROM situations")}

    def situation_state(self, event_id: str) -> dict | None:
        """Canonical current identity and persisted bookmark state, or missing."""
        with self._lock:
            identity = canonical_event(self._conn, str(event_id))
            if not self._conn.execute("SELECT 1 FROM events WHERE id=?", (identity,)).fetchone():
                return None
            saved = bool(self._conn.execute("SELECT 1 FROM situations WHERE event_id=?", (identity,)).fetchone())
            return {"event_id": identity, "saved": saved}

    def set_situation_saved(self, event_id: str, saved: bool) -> dict:
        """Set explicit state transactionally; repeated delivery is idempotent.

        An existing custom title, save date and last-visited revision survive
        repeated saves. Unstar removes only the bookmark, never source evidence.
        """
        if not isinstance(saved, bool):
            raise ValueError("Saved state must be boolean")
        with self._lock, self._conn:
            identity = canonical_event(self._conn, str(event_id))
            row = self._conn.execute("SELECT body FROM events WHERE id=?", (identity,)).fetchone()
            if not row:
                raise ValueError("Event does not exist")
            if saved:
                title = plain_text(json.loads(row[0]).get("title", "Saved situation"), 500)
                self._conn.execute(
                    "INSERT INTO situations(event_id,title,saved_at,last_visited_revision) VALUES(?,?,?,0) "
                    "ON CONFLICT(event_id) DO NOTHING", (identity, title, utcnow()))
            else:
                self._conn.execute("DELETE FROM situations WHERE event_id=?", (identity,))
            return {"event_id": identity, "saved": saved}

    def save_situation(self, event_id: str, title: str = "") -> dict:
        with self._lock, self._conn:
            event_id = canonical_event(self._conn, event_id)
            event = self._get_event_unlocked(event_id)
            if not event:
                raise ValueError("Event does not exist")
            self._conn.execute("INSERT INTO situations(event_id,title,saved_at,last_visited_revision) VALUES(?,?,?,0) ON CONFLICT(event_id) DO UPDATE SET title=excluded.title",
                               (event_id, plain_text(title or event["title"], 500), utcnow()))
            return {"event_id": event_id, "title": title or event["title"]}

    def remove_situation(self, event_id: str) -> None:
        with self._lock, self._conn:
            event_id = canonical_event(self._conn, event_id)
            self._conn.execute("DELETE FROM situations WHERE event_id=?", (event_id,))

    def list_situations(self) -> list[dict]:
        with self._lock:
            result = []
            for row in self._conn.execute("SELECT * FROM situations ORDER BY saved_at DESC"):
                item = dict(row)
                event = self._get_event_unlocked(row["event_id"])
                item.update(event=event, id=row["event_id"], region=event["region"], category=event["category"],
                            verification=event["verification"], severity=event["severity"],
                            new_revisions=max(0, event["revision"] - item["last_visited_revision"]))
                result.append(item)
            return result

    def visit_situation(self, event_id: str) -> dict:
        with self._lock, self._conn:
            event_id = canonical_event(self._conn, event_id)
            row = self._conn.execute("SELECT * FROM situations WHERE event_id=?", (event_id,)).fetchone()
            if not row:
                self.save_situation(event_id)
                row = self._conn.execute("SELECT * FROM situations WHERE event_id=?", (event_id,)).fetchone()
            event = self._get_event_unlocked(event_id)
            changes = [t for t in event["timeline"] if t["revision"] > row["last_visited_revision"]]
            result = {**dict(row), "event": event, "changes": changes,
                      "what_changed": "No changes since your last visit." if not changes else f"{len(changes)} event revision(s) since your last visit."}
            self._conn.execute("UPDATE situations SET last_visited_at=?,last_visited_revision=? WHERE event_id=?", (utcnow(), event["revision"], event_id))
            return result

    def add_alert(self, event: dict, reason: str) -> dict | None:
        reason = plain_text(reason, 1000)
        if not reason or not event.get("id"):
            return None
        kind = "retraction" if reason.lower().startswith("retraction") else "correction" if reason.lower().startswith("correction") else "official" if reason.lower().startswith("official") else "developing"
        fingerprint = _hash({"event_id": event["id"], "material": event.get("material_signature", ""), "kind": kind})
        stamp = utcnow()
        with self._lock, self._conn:
            if self._conn.execute("SELECT 1 FROM alerts WHERE fingerprint=?", (fingerprint,)).fetchone():
                return None
            if not self._conn.execute("SELECT 1 FROM events WHERE id=?", (event["id"],)).fetchone():
                raise ValueError("Cannot alert for an unknown event")
            latest = self._conn.execute("SELECT body,created_at FROM alerts WHERE event_id=? ORDER BY created_at DESC LIMIT 1", (event["id"],)).fetchone()
            try:
                cooldown = max(0, min(86400, int(self.get_setting("alert_cooldown_seconds", 1800))))
            except (ValueError, TypeError):
                cooldown = 1800
            if latest and kind not in {"correction", "retraction"}:
                last = json.loads(latest["body"])
                severity_increased = SEVERITY.get(event.get("severity"), 0) > SEVERITY.get(last.get("severity"), 0)
                if not severity_increased and (_dt(stamp) - _dt(latest["created_at"])).total_seconds() < cooldown:
                    return None
            alert = {"id": str(uuid4()), "event_id": event["id"], "title": event["title"], "headline": event["title"],
                     "region": event["region"], "country": event["country"], "severity": event["severity"],
                     "verification": event["verification"], "reason": reason, "kind": kind, "recap": event["recap"],
                     "created_at": stamp, "timestamp": stamp, "read": False, "read_at": None,
                     "synthetic": bool(event.get("synthetic")), "delivery_status": "saved; native delivery not yet attempted"}
            self._conn.execute("INSERT INTO alerts VALUES(?,?,?,?,?,?)", (alert["id"], event["id"], stamp, None, fingerprint, _json(alert)))
            return alert

    def list_alerts(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return [json.loads(row[0]) for row in self._conn.execute("SELECT body FROM alerts ORDER BY created_at DESC,rowid DESC LIMIT ?", (max(1, min(int(limit), 5000)),))]

    def mark_alert_read(self, alert_id: str) -> None:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT body FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if row:
                body = json.loads(row[0])
                body.update(read=True, read_at=utcnow())
                self._conn.execute("UPDATE alerts SET read_at=?,body=? WHERE id=?", (body["read_at"], _json(body), alert_id))

    def update_alert_delivery(self, alert_id: str, status: str) -> None:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT body FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if row:
                body = json.loads(row[0])
                body["delivery_status"] = plain_text(status, 500)
                self._conn.execute("UPDATE alerts SET body=? WHERE id=?", (_json(body), alert_id))

    def put_observations(self, observations: Iterable[dict]) -> int:
        """Store valid indicator revisions; return the count of material changes.

        A repeated fingerprint may advance retrieved_at for custody without
        rebuilding the full GUI map. New or corrected values remain visible.
        """
        stamp = utcnow()
        changed = 0
        with self._lock, write_transaction(self._conn, self.path):
            for index, raw in enumerate(observations):
                if index >= 5000:
                    break
                if not isinstance(raw, dict) or raw.get("value") is None:
                    continue
                mode = self.get_setting("archive_mode")
                synthetic = raw.get("synthetic") is True
                if mode and synthetic != (mode == "synthetic"):
                    continue
                if not mode:
                    self._conn.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("archive_mode", _json("synthetic" if synthetic else "live")))
                try:
                    value = float(raw["value"])
                    if not math.isfinite(value):
                        continue
                    source = plain_text(raw.get("source_id", "unknown"), 150)
                    indicator = plain_text(raw.get("indicator") or raw.get("indicator_id"), 200)
                    country = plain_text(raw.get("country") or raw.get("country_code"), 150)
                    date = plain_text(raw.get("observation_date") or raw.get("date") or raw.get("period"), 50)
                    if not indicator or not country or not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", date):
                        continue
                    url = safe_public_url(raw["url"]) if raw.get("url") else ""
                    retrieved = _iso(raw.get("retrieved_at") or stamp)
                    body = {"source_id": source, "indicator": indicator, "country": country, "date": date,
                            "observation_date": date, "value": value, "unit": plain_text(raw.get("unit"), 100),
                            "release_date": plain_text(raw.get("release_date"), 50), "retrieved_at": retrieved,
                            "url": url, "description": plain_text(raw.get("description") or raw.get("name"), 1000),
                            "synthetic": raw.get("synthetic") is True}
                    identity = _hash({"source": source, "indicator": indicator, "country": country, "date": date, "synthetic": body["synthetic"]})
                    for field in ("indicator_name", "country_code", "dataset_updated_at", "attribution", "source_note", "source_license"):
                        if raw.get(field):
                            body[field] = plain_text(raw[field], 2000)
                    body["id"] = identity
                    fingerprint = _hash({k: v for k, v in body.items() if k != "retrieved_at"})
                    row = self._conn.execute("SELECT fingerprint,body FROM observations WHERE id=?", (identity,)).fetchone()
                    if row and row["fingerprint"] == fingerprint:
                        self._conn.execute("UPDATE observations SET retrieved_at=?,body=? WHERE id=?", (retrieved, _json(body), identity))
                        continue
                    if row:
                        self._conn.execute("UPDATE observations SET retrieved_at=?,fingerprint=?,body=? WHERE id=?", (retrieved, fingerprint, _json(body), identity))
                    else:
                        self._conn.execute("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)", (identity, source, indicator, country, date, stamp, retrieved, fingerprint, _json(body)))
                    self._conn.execute("INSERT INTO observation_revisions(observation_id,at,fingerprint,body) VALUES(?,?,?,?)", (identity, stamp, fingerprint, _json(body)))
                    changed += 1
                except (ValueError, TypeError):
                    continue
        return changed

    def content_revision(self) -> tuple[int, int]:
        """Conservative SQLite mutation identity for volatile GUI read reuse.

        total_changes catches THIS Store connection's writes; data_version
        catches separate SQLite connections. Read both under the Store lock.
        A change invalidates a cached *view*; it is never treated as evidence
        of a changed event, a refreshed source, or a newer publication.
        """
        with self._lock:
            return (self._conn.total_changes,
                    int(self._conn.execute("PRAGMA data_version").fetchone()[0]))

    def content_revision_if_available(self) -> tuple[int, int] | None:
        """Nonblocking revision probe for a Qt event-loop callback.

        A worker can hold the Store RLock while importing or reading a large
        source batch. Never wait for that worker merely to decide whether a
        previously captured UI snapshot remains current. None means BUSY, not
        unchanged; callers must defer or discard, never accept a stale view.
        """
        if not self._lock.acquire(blocking=False):
            return None
        try:
            return (self._conn.total_changes,
                    int(self._conn.execute("PRAGMA data_version").fetchone()[0]))
        finally:
            self._lock.release()

    def list_observations(self, indicator: str = "", country: str = "") -> list[dict]:
        where, params = [], []
        if indicator:
            where.append("indicator=?")
            params.append(indicator)
        if country:
            where.append("country=?")
            params.append(country)
        with self._lock:
            # SQLite's data_version includes other connections' committed
            # writes, while total_changes covers this Store's own changes.
            # A cached current observation read is valid ONLY at this exact
            # token. Source corrections, retention and withdrawals all alter
            # it. Filtered queries deliberately retain their existing SQL.
            token = (self._conn.total_changes,
                     int(self._conn.execute("PRAGMA data_version").fetchone()[0]))
            if (not indicator and not country and self._observation_cache
                    and self._observation_cache[0] == token):
                return json.loads(self._observation_cache[1])
            sql = "SELECT id,body FROM observations" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY observation_date DESC,country LIMIT 10000"
            rows = self._conn.execute(sql, params).fetchall()
            # Old code issued one separate revision SELECT per observation:
            # 3,200 rows meant 3,200 SQLite round-trips on the Qt GUI thread.
            # Fetch revisions in bounded batches while retaining per-record
            # revision order, previous_value and the exact returned schema.
            revisions_by_id: dict[str, list[dict]] = {}
            for offset in range(0, len(rows), 400):
                chunk = rows[offset:offset + 400]
                identities = [row["id"] for row in chunk]
                placeholders = ",".join("?" for _ in identities)
                query = (
                    "SELECT observation_id,body FROM observation_revisions "
                    f"WHERE observation_id IN ({placeholders}) ORDER BY id"
                )
                for revision in self._conn.execute(query, identities):
                    revisions_by_id.setdefault(revision["observation_id"], []).append(
                        json.loads(revision["body"])
                    )
            result = []
            for row in rows:
                body = json.loads(row["body"])
                revisions = revisions_by_id.get(row["id"], [])
                body["revisions"] = revisions
                body["revision_count"] = len(revisions)
                body["previous_value"] = revisions[-2]["value"] if len(revisions) > 1 else None
                result.append(body)
            if not indicator and not country:
                # Cache at most a bounded serialized snapshot. The first read
                # occurs during the non-dismissable startup splash; subsequent
                # post-collection no-op signals do not re-run thousands of
                # SQLite history lookups merely to paint identical Economy.
                # Re-check after reading to avoid caching an external commit
                # that overlapped the read.
                ending = (self._conn.total_changes,
                          int(self._conn.execute("PRAGMA data_version").fetchone()[0]))
                if ending == token and len(result) <= 5000:
                    encoded = _json(result)
                    self._observation_cache = (
                        (token, encoded) if len(encoded.encode("utf-8")) <= 4_000_000
                        else None
                    )
                else:
                    self._observation_cache = None
            return result

    def prune(self, retention_days: int = 365, now: str | None = None) -> dict:
        days = max(1, min(3650, int(retention_days)))
        moment = _dt(now, default=datetime.now(UTC))
        stamp = _iso(moment)
        deleted_reports = 0
        affected: set[str] = set()
        with self._lock, self._conn:
            for row in self._conn.execute("SELECT record_key,event_id,first_seen,retention_days FROM reports").fetchall():
                if _dt(row["first_seen"]) < moment - timedelta(days=min(days, row["retention_days"])):
                    affected.add(row["event_id"])
                    self._conn.execute("DELETE FROM reports WHERE record_key=?", (row["record_key"],))
                    deleted_reports += 1
            if deleted_reports:
                # Translation settings are source-derived text. Conservatively
                # invalidate the complete cache when any underlying report
                # expires; a cache hit must never defeat a provider's retention.
                self._conn.execute("DELETE FROM settings WHERE key LIKE 'translation:%'")
            deleted_events = 0
            for event_id in affected:
                # Derived recaps and historical snapshots must expire with their
                # inputs; keeping an old summary would defeat source retention.
                self._conn.execute("DELETE FROM event_revisions WHERE event_id=?", (event_id,))
                # Merged identities must not retain source-derived summaries
                # after their underlying inputs reach the retention boundary.
                donors = [r[0] for r in self._conn.execute("SELECT alias_id FROM event_aliases WHERE canonical_id=?", (event_id,))]
                for donor in donors:
                    self._conn.execute("DELETE FROM events WHERE id=?", (donor,))
                self._conn.execute("DELETE FROM warning_identities WHERE event_id=?", (event_id,))
                for survivor in self._conn.execute("SELECT body FROM reports WHERE event_id=?", (event_id,)):
                    register_warning(self._conn, json.loads(survivor[0]), event_id)
                self._conn.execute("DELETE FROM alerts WHERE event_id=?", (event_id,))
                if self.fts_available:
                    self._conn.execute("DELETE FROM event_search WHERE event_id=?", (event_id,))
                if self._conn.execute("SELECT 1 FROM reports WHERE event_id=? LIMIT 1", (event_id,)).fetchone():
                    self._rebuild(event_id, stamp, [{"kind": "retention", "publisher": "Global Pulse", "title": "Expired source records removed under retention policy", "at": stamp}])
                else:
                    self._conn.execute("DELETE FROM warning_identities WHERE event_id=?", (event_id,))
                    self._conn.execute("DELETE FROM event_aliases WHERE canonical_id=? OR alias_id=?", (event_id, event_id))
                    self._conn.execute("DELETE FROM events WHERE id=?", (event_id,))
                    deleted_events += 1
            cutoff = _iso(moment - timedelta(days=days))
            removed_observations = self._conn.execute("DELETE FROM observations WHERE first_seen<?", (cutoff,)).rowcount
            return {"reports": deleted_reports, "events": deleted_events, "observations": removed_observations}

    def stats(self) -> dict:
        with self._lock:
            return {name: self._conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                    for name in ("events", "reports", "alerts", "situations", "observations")}

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.close()
                self._closed = True

    def close_after_shutdown(self, settings: dict, delivery_outcomes=(), *, lock_timeout=1.0) -> None:
        """Commit final UI/history state without a blocking WAL truncate.

        Called only by the shutdown finalizer after collection is gated and
        owned database children have actually exited. The existing Store lock
        protects an in-progress transaction; failure leaves the connection and
        singleton alive for an explicit retry. A busy reader may retain a WAL,
        which is durable SQLite state, not a reason to delay application exit.
        """
        encoded = [(str(key)[:200], _json(value)) for key, value in settings.items()]
        if any(len(value.encode("utf-8")) > 250_000 for _, value in encoded):
            raise ValueError("Shutdown setting is too large")
        if not self._lock.acquire(timeout=max(0.0, lock_timeout)):
            raise RuntimeError("An archive operation is still finishing; exit can be retried safely")
        try:
            if self._closed:
                return
            previous_timeout = self._conn.execute("PRAGMA busy_timeout").fetchone()[0]
            self._conn.execute("PRAGMA busy_timeout=250")
            try:
                # One transaction: do not lose half the layout or acknowledge
                # native submissions before their history outcome is durable.
                with self._conn:
                    self._conn.executemany(
                        "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        encoded)
                    for alert_id, status in delivery_outcomes:
                        row = self._conn.execute("SELECT body FROM alerts WHERE id=?", (alert_id,)).fetchone()
                        if row:
                            body = json.loads(row[0])
                            body["delivery_status"] = plain_text(status, 500)
                            self._conn.execute("UPDATE alerts SET body=? WHERE id=?", (_json(body), alert_id))
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                self._conn.close()
                self._closed = True
            finally:
                if not self._closed:
                    self._conn.execute(f"PRAGMA busy_timeout={int(previous_timeout)}")
        finally:
            self._lock.release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _markdown_text(value: Any) -> str:
    return plain_text(value, 8000).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("*", "\\*").replace("_", "\\_").replace("#", "\\#").replace("`", "\\`")


def build_brief(events: list[dict], period: str = "daily") -> str:
    if period not in {"daily", "weekly"}:
        raise ValueError("Brief period must be daily or weekly")
    limit = 80 if period == "weekly" else 60
    title = "Weekly" if period == "weekly" else "Daily"
    generated = utcnow()
    moment = _dt(generated)
    since = moment - timedelta(days=7 if period == "weekly" else 1)
    window = "last 7 days" if period == "weekly" else "last 24 hours"
    supplied = [e for e in events[:1500] if isinstance(e, dict)]
    synthetic = any(e.get("synthetic") for e in supplied)

    def text(value, length=300):
        from html import escape
        # Markdown may contain inline HTML. Entity-encoded source markup must
        # remain text even after plain_text has decoded its entities.
        return escape(_markdown_text(plain_text(value, length)), quote=False)

    def date(value):
        try:
            return _dt(value)
        except (TypeError, ValueError, OverflowError):
            return None

    def source_time(report):
        published = date(report.get("published_at"))
        if report.get("publication_time_known") is not False and published:
            return "source published " + _iso(published)
        retrieved = date(report.get("first_retrieved_at") or report.get("retrieved_at"))
        return ("publication time unknown; first retrieved " + _iso(retrieved)
                if retrieved else "publication time unknown; retrieval time unavailable")

    def period_changes(event):
        # This is the local revision trail, not an inferred real-world change.
        # Filter by the actual change timestamp, not the event's latest update.
        candidates = []
        for entry in event.get("timeline", [])[-40:]:
            if isinstance(entry, dict):
                candidates.extend((change, entry.get("at")) for change in
                                  entry.get("changes", [])[:20] if isinstance(change, dict))
        candidates.extend((change, event.get("updated_at")) for change in
                          event.get("changes", [])[:20] if isinstance(change, dict))
        found = {}
        for change, fallback in candidates:
            at = date(change.get("at") or fallback)
            if at is None or not since <= at <= moment:
                continue
            key = (at, str(change.get("kind")), str(change.get("publisher")),
                   str(change.get("report_id")), str(change.get("title")))
            found[key] = (at, change)
        return sorted(found.values(), key=lambda row: row[0], reverse=True)[:3]

    lines = [f"# Global Pulse — {title} intelligence brief", "", f"Generated: {generated}", "",
             f"**Reporting window (UTC):** {_iso(since)} through {_iso(moment)} — rolling {window}, not a calendar-day total.", "",
             "SYNTHETIC TRAINING DATA — NOT LIVE NEWS" if synthetic else "Source-linked summary of the supplied local monitoring records.", "",
             "The requested window uses local record updates; source publication dates may be older. "
             "Exact dates and any supplied historical context remain visible below. "
             "Coverage is limited to monitored sources, not all world events.", "",
             "**Read the labels separately:** UNASSESSED means the source has not supplied an importance/severity rating; "
             "it does not mean a story is false or that verification was completed. "
             "Evidence status describes source attribution and documented independent reporting. "
             "An official statement confirms its publication, not every underlying claim.", ""]
    # A single high-volume weather adapter can otherwise consume every slot
    # before one disease, conflict, infrastructure or government record appears.
    # These are source CATEGORY groupings, never invented news/crisis claims.
    from .brief_selection import balanced_brief_sections, BRIEF_DOMAINS
    grouped = balanced_brief_sections(
        supplied, per_domain=8 if period == "daily" else 9,
        max_total=limit, disaster_limit=3 if period == "daily" else 6
    )
    ranked = [(domain, event) for domain, items in grouped for event in items]
    selected = [event for _, event in ranked]
    supplied_count = len({str(e.get("id")) for e in supplied if e.get("id")})
    if not grouped:
        lines.extend(["No matching developments are stored for this period.", ""])
    else:
        evidence_counts = {key: 0 for key in ("official", "corroborated", "developing", "unverified")}
        for event in selected:
            evidence = str(event.get("verification") or "unverified")
            evidence_counts[evidence if evidence in evidence_counts else "unverified"] += 1
        publishers = {str(r.get("source_id") or r.get("publisher"))
                      for e in selected for r in e.get("reports", [])
                      if isinstance(r, dict) and (r.get("source_id") or r.get("publisher"))}
        unrated = sum(e.get("severity", "unassessed") == "unassessed" for e in selected)
        lines.extend([
            "## At a glance", "",
            f"**Included:** {len(selected)} of {supplied_count} supplied local records across {len(grouped)} topics; "
            f"{len(publishers)} source identities represented. This is a bounded sample, not a global event count.", "",
            f"**Evidence in this sample:** {evidence_counts['official']} official measurement(s), "
            f"{evidence_counts['corroborated']} corroborated event association(s), "
            f"{evidence_counts['developing']} developing association(s), "
            f"{evidence_counts['unverified']} unverified record(s). {unrated} have unassessed importance.", "",
        ])
        if supplied_count > len(selected):
            lines.extend([f"{supplied_count - len(selected)} additional supplied records are outside the displayed topic limits. "
                          "Use the feed or event archive for their complete evidence.", ""])
        lines.extend([
            "## Topic coverage", "",
            "Items are grouped by source category, then by importance and last recorded update. "
            "These sections do not establish worldwide coverage or verify a crisis.", ""
        ])
        present = {domain for domain, _ in grouped}
        absent = [domain for domain in BRIEF_DOMAINS if domain not in present]
        if absent:
            lines.extend(["**Not represented in supplied local records:** " +
                          ", ".join(absent) +
                          ". This is a coverage gap, not evidence that no events occurred.", ""])
        lines.extend([" | ".join(f"{domain}: {len(rows)}" for domain, rows in grouped), ""])
        by_day = defaultdict(list)
        for domain, event in ranked:
            at = date(event.get("updated_at"))
            if at:
                by_day[at.date().isoformat()].append(domain)
        if by_day:
            lines.extend(["### Selected local record updates by date (UTC)", "",
                          "These are archive update dates, not asserted event-occurrence or publication dates.", ""])
            for day, domains in sorted(by_day.items(), reverse=True):
                lines.append(f"- **{day}:** {len(domains)} selected record(s); " +
                             ", ".join(domain for domain in BRIEF_DOMAINS if domain in domains) + ".")
            lines.append("")
    current_domain = None
    for index, (domain, event) in enumerate(ranked, 1):
        if domain != current_domain:
            current_domain = domain
            lines.extend([f"## {domain}", ""])
        verification = str(event.get("verification") or "unverified")
        evidence_label = {
            "official": "Official measurement — source-attributed and potentially revisable",
            "corroborated": "Corroborated event association — individual claims still require review",
            "developing": "Developing association — independent confirmation remains incomplete",
            "unverified": "Unverified — independent corroboration has not been established",
        }.get(verification, "Unverified — assessment unavailable")
        origins = len(set(event.get("independent_origins") or []))
        reports = [r for r in event.get("reports", []) if isinstance(r, dict)]
        lines.extend([f"### {index}. {text(event.get('title') or 'Untitled source record', 260)}", "",
                      f"Severity: **{str(event.get('severity', 'unassessed')).upper() if event.get('severity') in SEVERITY else 'UNASSESSED'}** · {text(event.get('category') or 'News', 80)} · {text(event.get('region') or event.get('country') or 'Unspecified location', 120)}", "",
                      f"**Evidence:** {evidence_label}. {len(reports)} source record(s); {origins} documented independent origin(s). "
                      f"**Record status:** {text(event.get('status') or 'unknown', 40)}.", "",
                      text(event.get("recap") or "No source-provided recap is available; inspect the original reports.", 1000), "",
                      f"Last material record update: {text(event.get('updated_at') or 'unknown', 60)} · Local event: {text(event.get('id'), 100)}", ""])
        updated = date(event.get("updated_at"))
        if event.get("future_dated") or updated and updated > moment:
            lines.extend(["**Future-dated context:** retained for review, not evidence of a current development.", ""])
        elif updated and updated < since:
            lines.extend(["**Historical context:** this supplied record is outside the requested rolling window; it is not presented as new today.", ""])
        if event.get("official_attribution") and verification != "official":
            lines.extend(["**Official-source attribution:** an official publication is present; this does not independently verify its underlying claims.", ""])
        for reason in event.get("reasons", [])[:2]:
            lines.extend(["Evidence basis: " + text(reason, 280), ""])
        if event.get("emerging"):
            lines.extend(["**Emerging signal:** Limited coverage in the monitored source set. This is not a measurement of worldwide media coverage.", ""])
        for conflict in event.get("contradictions", [])[:5]:
            lines.extend([f"**Evidence discrepancy:** {text(conflict.get('explanation'), 400)}", ""])
        changes = period_changes(event)
        if changes:
            lines.extend(["**Recorded changes during this window:**", ""])
            for at, change in changes:
                lines.append(f"- {_iso(at)} — {text(change.get('publisher') or 'Source unlisted', 80)}: "
                             f"{text(change.get('kind') or 'update', 50)} — {text(change.get('title'), 240)}.")
            lines.append("")

        # Prefer current evidence, then show older/retracted/future records with
        # their state. This never changes the canonical verification result.
        reports = sorted(reports, key=lambda r: (
            not bool(r.get("future_dated")), r.get("evidence_status", "active") == "active",
            date(r.get("published_at")) or datetime.min.replace(tzinfo=UTC)), reverse=True)
        sources = []
        for report in reports:
            try:
                url = safe_public_url(report.get("url", "")).replace("(", "%28").replace(")", "%29").replace(" ", "%20").replace("<", "%3C").replace(">", "%3E").replace('"', "%22")
            except (TypeError, ValueError):
                continue
            sources.append((report, url))
            if len(sources) == 8:
                break
        detail_count = 0
        seen_details = set()
        for report, url in sources:
            summary = plain_text(report.get("english_summary") or report.get("summary") or "", 420)
            key = summary.casefold()
            if (not summary or key in seen_details or summary == report.get("title")
                    or report.get("future_dated") or report.get("evidence_status", "active") != "active"):
                continue
            seen_details.add(key)
            if detail_count == 0:
                lines.extend(["**Source-provided detail (attributed, not a new independent assessment):**", ""])
            label = ("machine-translated excerpt" if report.get("translation_label")
                     else "provided English excerpt" if report.get("english_summary") else "source excerpt")
            lines.append(f"- [{text(report.get('publisher') or report.get('source_id') or 'Source', 100)}]({url}) "
                         f"({source_time(report)}; {label}): “{text(summary, 420)}”")
            detail_count += 1
            if detail_count == 2:
                break
        if detail_count:
            lines.append("")
        if sources:
            lines.extend(["Sources:", ""])
        for report, url in sources:
            lines.append(f"- [{text(report.get('publisher') or report.get('source_id') or 'Source', 100)}: {text(report.get('title') or 'Original report', 260)}]({url}) — {source_time(report)}; {text(report.get('evidence_status') or 'active', 40)}; {text(report.get('independence') or 'unknown', 40)} provenance.")
            credit = " · ".join(text(report[k], 220) for k in ("byline", "attribution", "source_license") if report.get(k))
            if credit:
                lines.append(f"  Credit: {credit}")
        if len(reports) > len(sources):
            lines.append(f"{len(reports) - len(sources)} additional source record(s) are omitted by the link/safety budget; inspect the event archive for the complete evidence trail.")
        lines.append("")
    lines.extend(["## Verification notes", "", "Repeated syndication adds no independent confirmation. Conflicting claims are preserved without selecting a winner. Recaps use source-provided metadata and bounded attributed excerpts; no unavailable article details are inferred.", ""])
    return "\n".join(lines)
