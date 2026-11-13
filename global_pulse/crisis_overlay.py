"""Conservative, source-derived humanitarian activity overlays for the offline map.

These helpers do not declare a legal state of war or crisis. They summarize recent
non-synthetic reporting already accepted into Global Pulse and require either
official sourcing or independently corroborated reporting before a country
receives a stripe. Freshness is based on source evidence time, never local
ingest/rebuild time.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .map_evidence import incident_country, structured_incident_country

UTC = timezone.utc

CONFLICT_PATTERNS = (
    r"\bwar\b", r"\barmed conflict\b", r"\bfighting\b", r"\bclashes?\b",
    r"\bair[ -]?strikes?\b", r"\bshelling\b", r"\bbombard(?:ment|ed|ing)\b",
    r"\boffensive\b", r"\bmissile(?:s| strikes?| attacks?)?\b",
    r"\b(?:drone|rocket|military|armed) (?:strikes?|attacks?)\b",
    r"\b(?:launch|launched|launches|fresh|renewed|retaliatory|deadly|overnight).{0,45}\bstrikes?\b",
    r"\bstrikes? on .{0,45}\b(?:power grid|energy infrastructure|military targets?|civilian infrastructure)\b",
    r"\b(?:killed|injured|wounded).{0,55}\battacks?\b",
    r"\battacks?.{0,55}\b(?:killed|injured|wounded)\b",
    r"\b(?:armed|military|regional|cross-border) conflict\b",
    r"\bconflict (?:in|between|with)\b",
    r"\binvasion\b", r"\bcombat\b", r"\bceasefire violation\b",
)
# A bare "war" in a headline is not invariably armed conflict. Keep
# nonmilitary economic/health idioms out of the crisis stripe unless separate
# military evidence or an explicit conflict category is present.
NONMILITARY_WAR_PATTERNS = (
    r"\b(?:trade|tariff|price|currency|bidding|marketing|platform|culture) wars?\b",
    r"\bwar on (?:cancer|poverty|drugs|disease|inflation|hunger|climate change|obesity)\b",
    r"\bwar chest\b",
    r"\bwar for talent\b",
    r"\bwar of words\b",
)

UNREST_PATTERNS = (
    r"\bprotests?\b", r"\bdemonstrations?\b", r"\bcivil unrest\b",
    r"\briots?\b", r"\bmass rally\b", r"\banti-government rally\b",
    r"\bviolent unrest\b", r"\bprotesters?\b",
)
MIGRATION_PATTERNS = (
    r"\brefugees?\b", r"\bforced displacement\b", r"\bdisplaced people\b",
    r"\binternally displaced\b", r"\bdisplacement crisis\b",
    r"\bmigration crisis\b", r"\bmigrant crisis\b", r"\bmass displacement\b",
    r"\bpopulation exodus\b", r"\basylum influx\b",
)

CATEGORY_HINTS = {
    "conflict": {"conflict", "war", "security"},
    "unrest": {"protest", "civil unrest", "unrest"},
    "migration": {"migration", "displacement", "refugee"},
}

ALIASES = {
    "unitedstates": "unitedstatesofamerica",
    "usa": "unitedstatesofamerica",
    "us": "unitedstatesofamerica",
    "czechrepublic": "czechia",
    "turkiye": "turkey",
    "ivorycoast": "cotedivoire",
    "cotedivoire": "cotedivoire",
    "democraticrepublicofthecongo": "demrepcongo",
    "drcongo": "demrepcongo",
    "drc": "demrepcongo",
    "republicofthecongo": "congo",
    "southsudan": "southsudan",
}


def normalize_country(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    key = re.sub(r"[^a-z0-9]+", "", text.casefold())
    return ALIASES.get(key, key)


def _word_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


@lru_cache(maxsize=1)
def _country_text_phrases() -> tuple[tuple[str, str], ...]:
    """Country names allowed as explicit source-text evidence.

    This is deliberately not a general geocoder. It reads only the bundled
    offline country names and a few unambiguous long-form aliases. Two-letter
    abbreviations such as US/UK are excluded from source-text inference.
    """
    values: dict[str, str] = {}
    try:
        data = json.loads(
            (Path(__file__).with_name("resources") / "world_countries.geojson")
            .read_text(encoding="utf-8")
        )
        for feature in data.get("features", []):
            name = str(feature.get("properties", {}).get("name", "")).strip()
            phrase = _word_text(name)
            key = normalize_country(name)
            if len(phrase) >= 4 and key:
                values[phrase] = key
    except (OSError, ValueError, TypeError):
        pass
    aliases = {
        "united states": "unitedstatesofamerica",
        "united states of america": "unitedstatesofamerica",
        "czech republic": "czechia",
        "turkiye": "turkey",
        "ivory coast": "cotedivoire",
        "democratic republic of the congo": "demrepcongo",
        "dr congo": "demrepcongo",
        "republic of the congo": "congo",
        "south sudan": "southsudan",
    }
    values.update(aliases)
    return tuple(sorted(values.items(), key=lambda item: (-len(item[0]), item[0])))


def _explicit_text_country(event: dict) -> str:
    """Return exactly one country named in eligible source text, or unknown.

    Publisher country/region metadata is never consulted here. If source text
    names multiple countries, the event remains geographically ambiguous.
    """
    matches: set[str] = set()
    for record in _semantic_records(event):
        text = _word_text(" ".join(str(record.get(key, "") or "")
                                  for key in ("title", "recap", "summary")))
        if not text:
            continue
        padded = " " + text + " "
        claimed_spans: list[tuple[int, int]] = []
        # Longest phrases match first. South Sudan is not Sudan, nor the
        # Democratic Republic of the Congo the Republic of the Congo.
        # Separate non-overlapping countries still make location ambiguous.
        for phrase, key in _country_text_phrases():
            token = " " + phrase + " "
            cursor = 0
            while True:
                index = padded.find(token, cursor)
                if index < 0:
                    break
                start, end = index + 1, index + 1 + len(phrase)
                if not any(start < right and left < end
                           for left, right in claimed_spans):
                    claimed_spans.append((start, end))
                    matches.add(key)
                    if len(matches) > 1:
                        return ""
                cursor = index + 1
    return next(iter(matches)) if len(matches) == 1 else ""


def _independent_report_origins(event: dict) -> set[str]:
    return {
        str(report.get("origin_id")).strip()
        for report in _active_reports(event)
        if str(report.get("origin_id") or "").strip()
        and report.get("independence", "original") in ("", "original", None)
        and report.get("kind", "report") not in
        {"social", "repost", "commentary", "video", "radio", "retraction"}
    }


def _timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _semantic_records(event: dict) -> list[dict]:
    """Use eligible report text when source records exist, not cached headlines.

    A withdrawn/future report is kept for history but cannot lend crisis terms
    through either its own text or a stale aggregate event caption/category.
    Compact legacy views with only official/time flags retain their existing
    event-caption fallback; complete source records never take that fallback.
    """
    reports = event.get("reports")
    has_source_records = isinstance(reports, list) and any(
        isinstance(report, dict) and any(key in report for key in
            ("id", "source_id", "title", "summary", "category"))
        for report in reports
    )
    return _active_reports(event) if has_source_records else [event]


def _event_text(event: dict) -> str:
    parts = []
    for record in _semantic_records(event):
        parts.extend(record.get(key, "") for key in ("title", "recap", "summary", "category"))
    return " ".join(str(part or "") for part in parts).casefold()


def _unknown_source_time(report: dict) -> bool:
    """A provider explicitly lacking a date cannot borrow ingestion freshness.

    An actual dated source update is acceptable when publication time is
    explicitly unknown. Legacy compact fixtures without this flag preserve
    their historical event-level timestamp behavior.
    """
    return (report.get("publication_time_known") is False
            and _timestamp(report.get("source_updated_at")) is None)


def _missing_claimed_publication_time(report: dict) -> bool:
    """An explicitly claimed publication date must contain actual dated evidence.

    Do not mistake a later source-page update for a known publication date;
    reports without this explicit flag keep their legacy compatibility.
    """
    return (report.get("publication_time_known") is True
            and _timestamp(report.get("published_at")) is None)


def _active_reports(event: dict) -> list[dict]:
    reports = event.get("reports", []) if isinstance(event.get("reports"), list) else []
    active = []
    for report in reports:
        if not isinstance(report, dict) or report.get("future_dated"):
            continue
        if str(report.get("evidence_status", "active")).casefold() not in {"", "active"}:
            continue
        if _unknown_source_time(report) or _missing_claimed_publication_time(report):
            # Missing or malformed explicitly claimed publication evidence
            # cannot lend topical terms, independent origins or official status.
            continue
        active.append(report)
    return active


def _evidence_timestamp(event: dict) -> datetime | None:
    """Use provider/source evidence time, never the local Store rebuild time."""
    stamps: list[datetime] = []
    for report in _active_reports(event):
        # A known publication time is the conservative default. Source update
        # time is only a fallback when publication time was not actually known;
        # a later page refresh must not make old reporting look newly current.
        if report.get("publication_time_known", True):
            stamp = _timestamp(report.get("published_at"))
        else:
            stamp = _timestamp(report.get("source_updated_at") or report.get("published_at"))
        if stamp is not None:
            stamps.append(stamp)
    if stamps:
        return max(stamps)
    source_records = event.get("reports")
    if isinstance(source_records, list) and any(
            isinstance(report, dict) and "publication_time_known" in report
            for report in source_records):
        # With explicit source-time metadata, never borrow aggregate event
        # timestamps when all eligible source times are missing.
        # Legacy fixtures without an explicit flag preserve earlier behavior.
        return None
    # Prebuilt/legacy views without explicit unknown-date source records still
    # expose an event publication/creation time; updated_at is local rebuild time.
    return _timestamp(event.get("published_at") or event.get("created_at"))


def _credible(event: dict) -> bool:
    if event.get("synthetic") or event.get("historical_view"):
        return False
    if str(event.get("status", "active")).casefold() in {
        "retracted", "resolved", "closed", "ended", "cancelled", "expired", "pending"
    }:
        return False
    reports = _active_reports(event)
    if any(report.get("official") for report in reports):
        return True
    origins = event.get("independent_origins", [])
    if isinstance(origins, list):
        distinct = {str(origin).strip() for origin in origins if str(origin).strip()}
        source_records = event.get("reports")
        if isinstance(source_records, list) and any(
                isinstance(r, dict) and str(r.get("origin_id") or "").strip()
                for r in source_records):
            # A saved aggregate can outlive corrections and retractions. Only
            # active, original source records with matching origin identities
            # may support an independent-correspondent claim. Syndicated and
            # commentary records do not become independent by being counted.
            qualified = {
                str(r.get("origin_id")).strip() for r in reports
                if str(r.get("origin_id") or "").strip()
                and r.get("independence", "original") in ("", "original", None)
                and r.get("kind", "report") not in
                {"social", "repost", "commentary", "video", "radio", "retraction"}
            }
            distinct &= qualified
        elif isinstance(source_records, list) and any(
                isinstance(r, dict) and
                (_unknown_source_time(r) or _missing_claimed_publication_time(r))
                for r in source_records):
            # Legacy source records without individual origin IDs can still
            # have unknown timestamps: those records cannot lend an origin.
            distinct &= {str(r.get("origin_id") or "").strip() for r in reports}
        if len(distinct) >= 2:
            return True
    # Raw report count and a generic verification label are not evidence of
    # independence. Repeated/syndicated coverage must not create a stripe.
    return False


def _topical_kinds(event: dict) -> set[str]:
    """Identify topical kinds without deciding whether evidence is corroborated."""
    categories = {str(record.get("category", "")).casefold() for record in _semantic_records(event)}
    text = _event_text(event)
    kinds: set[str] = set()
    for kind, hints in CATEGORY_HINTS.items():
        if categories & hints:
            kinds.add(kind)
    if any(re.search(pattern, text) for pattern in CONFLICT_PATTERNS):
        # Bare "war" also appears in economic and public-health reporting.
        separate_armed_evidence = bool(categories & CATEGORY_HINTS["conflict"]) or any(
            re.search(pattern, text) for pattern in CONFLICT_PATTERNS[1:]
        )
        nonmilitary_idiom = any(re.search(pattern, text) for pattern in NONMILITARY_WAR_PATTERNS)
        if separate_armed_evidence or not nonmilitary_idiom:
            kinds.add("conflict")
    if any(re.search(pattern, text) for pattern in UNREST_PATTERNS):
        kinds.add("unrest")
    if any(re.search(pattern, text) for pattern in MIGRATION_PATTERNS):
        kinds.add("migration")
    return kinds


def classify_event(event: dict) -> set[str]:
    """Return conservative overlay kinds supported by eligible report text."""
    return _topical_kinds(event) if _credible(event) else set()


def _recent_report_scope(event: dict, now: datetime, max_age_days: int) -> dict | None:
    """Constrain a country stripe to *recent source reports*, not the freshest
    unrelated report attached to the same aggregate event.

    Legacy compact events without report-level dates retain their existing
    event-time behavior. Real dated records are filtered without modifying
    stored evidence; stale, retracted, future and undated records are retained
    in the Store but cannot lend current topical text or corroboration.
    """
    records = event.get("reports")
    if not isinstance(records, list) or not any(
            isinstance(r, dict)
            and any(k in r for k in ("id", "source_id", "title", "summary", "category"))
            and ("publication_time_known" in r
                 or _timestamp(r.get("published_at")) is not None
                 or _timestamp(r.get("source_updated_at")) is not None)
            for r in records):
        return event

    eligible: list[dict] = []
    for report in _active_reports(event):
        if report.get("publication_time_known", True):
            stamp = _timestamp(report.get("published_at"))
        else:
            stamp = _timestamp(report.get("source_updated_at") or report.get("published_at"))
        if stamp is None:
            continue
        age_seconds = (now - stamp).total_seconds()
        if -3600 <= age_seconds <= max(1, int(max_age_days)) * 86400:
            eligible.append(report)

    if not eligible:
        return None

    scoped = dict(event, reports=eligible)
    if any(isinstance(r, dict) and str(r.get("origin_id") or "").strip()
           for r in records):
        # Aggregated independence may refer to old/retracted observations.
        # Keep only individual original origins still present in this window.
        recent_origins = {
            str(r.get("origin_id")).strip() for r in eligible
            if str(r.get("origin_id") or "").strip()
            and r.get("independence", "original") in ("", "original", None)
            and r.get("kind", "report") not in
            {"social", "repost", "commentary", "video", "radio", "retraction"}
        }
        aggregate_origins = event.get("independent_origins", [])
        scoped["independent_origins"] = [
            origin for origin in (aggregate_origins if isinstance(aggregate_origins, list) else [])
            if str(origin).strip() in recent_origins
        ]
    return scoped


def build_country_activity(events: Iterable[dict], *, now: datetime | None = None, max_age_days: int = 14) -> dict[str, dict]:
    """Aggregate recent supported activity by country without losing split-source corroboration.

    Existing event-level official/two-origin rules remain authoritative. A second
    pass allows two independent original publishers in *separate* recent events
    to corroborate the same topical country activity. Country evidence must still
    be provider/record structured data or exactly one country explicitly named in
    eligible source text. Publisher-country defaults never qualify.
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    result: dict[str, dict] = {}
    candidates: list[tuple[dict, datetime, str, set[str]]] = []

    for raw in events:
        if not isinstance(raw, dict):
            continue
        event = _recent_report_scope(raw, now, max_age_days)
        if event is None or event.get("synthetic") or event.get("historical_view"):
            continue
        if str(event.get("status", "active")).casefold() in {
            "retracted", "resolved", "closed", "ended", "cancelled", "expired", "pending"
        }:
            continue
        stamp = _evidence_timestamp(event)
        if stamp is None or (now - stamp).total_seconds() < -3600:
            continue
        if (now - stamp).total_seconds() > max(1, int(max_age_days)) * 86400:
            continue

        structured_country = normalize_country(structured_incident_country(event))
        text_country = _explicit_text_country(event) if not structured_country else ""
        country = structured_country or text_country
        kinds = _topical_kinds(event)
        if not country or not kinds:
            continue
        candidates.append((event, stamp, country, kinds))

        # Preserve the already-accepted strict event-level path. When the
        # location itself came only from one explicit country in source text,
        # keep that basis visible rather than calling it structured evidence.
        if not _credible(event):
            continue
        entry = result.setdefault(country, {
            "conflict": 0, "unrest": 0, "migration": 0,
            "latest": "", "event_ids": [], "titles": [], "basis": {},
        })
        for kind in kinds:
            entry[kind] += 1
            entry["basis"][kind] = (
                "official_text_country"
                if text_country and any(report.get("official") for report in _active_reports(event))
                else "event_level"
            )
        iso = stamp.isoformat(timespec="seconds").replace("+00:00", "Z")
        entry["latest"] = max(entry["latest"], iso)
        identity = str(event.get("id", ""))
        if identity and len(entry["event_ids"]) < 20 and identity not in entry["event_ids"]:
            entry["event_ids"].append(identity)
        title = str(event.get("title", "")).strip()
        if title and len(entry["titles"]) < 5 and title not in entry["titles"]:
            entry["titles"].append(title)

    # Real feeds often store separate one-source events. Corroborate them at the
    # country/topic level instead of requiring the Store to have merged them.
    grouped: dict[tuple[str, str], dict] = {}
    for event, stamp, country, kinds in candidates:
        reports = _active_reports(event)
        official = any(report.get("official") for report in reports)
        origins = _independent_report_origins(event)
        for kind in kinds:
            row = grouped.setdefault((country, kind), {
                "official": False, "origins": set(), "event_ids": [], "titles": [], "latest": "",
            })
            row["official"] = row["official"] or official
            row["origins"].update(origins)
            identity = str(event.get("id", ""))
            if identity and identity not in row["event_ids"]:
                row["event_ids"].append(identity)
            title = str(event.get("title", "")).strip()
            if title and title not in row["titles"]:
                row["titles"].append(title)
            iso = stamp.isoformat(timespec="seconds").replace("+00:00", "Z")
            row["latest"] = max(row["latest"], iso)

    for (country, kind), row in grouped.items():
        existing = result.get(country)
        if existing and existing[kind] > 0:
            continue
        if not row["official"] and len(row["origins"]) < 2:
            continue
        entry = result.setdefault(country, {
            "conflict": 0, "unrest": 0, "migration": 0,
            "latest": "", "event_ids": [], "titles": [], "basis": {},
        })
        entry[kind] = max(1, len(row["event_ids"]))
        entry["basis"][kind] = "official_text_country" if row["official"] else "cross_event_independent"
        entry["latest"] = max(entry["latest"], row["latest"])
        for identity in row["event_ids"]:
            if len(entry["event_ids"]) >= 20:
                break
            if identity not in entry["event_ids"]:
                entry["event_ids"].append(identity)
        for title in row["titles"]:
            if len(entry["titles"]) >= 5:
                break
            if title not in entry["titles"]:
                entry["titles"].append(title)

    return result
