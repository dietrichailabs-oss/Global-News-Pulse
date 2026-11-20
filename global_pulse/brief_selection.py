"""Conservative, category-balanced presentation of locally collected evidence.

Neither rankings nor sections assert that a crisis exists worldwide. No model,
network request, inference of event coordinates, or article scraping occurs.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import islice
from html import escape
from urllib.parse import quote, urlsplit

# These are presentation headings, not a new upstream source classifier.
BRIEF_DOMAINS = (
    "Conflict & security",
    "Unrest & civil affairs",
    "Health & disease",
    "Government & politics",
    "Economy & business",
    "Humanitarian",
    "Infrastructure",
    "General news",
    "Weather & disasters",
)
_DOMAIN_ALIASES = {
    "conflict": "Conflict & security",
    "war": "Conflict & security",
    "security": "Conflict & security",
    "military": "Conflict & security",
    "unrest": "Unrest & civil affairs",
    "protest": "Unrest & civil affairs",
    "migration": "Unrest & civil affairs",
    "civil unrest": "Unrest & civil affairs",
    "health": "Health & disease",
    "disease": "Health & disease",
    "outbreak": "Health & disease",
    "public health": "Health & disease",
    "government": "Government & politics",
    "politics": "Government & politics",
    "policy": "Government & politics",
    "economy": "Economy & business",
    "business": "Economy & business",
    "finance": "Economy & business",
    "humanitarian": "Humanitarian",
    "infrastructure": "Infrastructure",
    "transportation": "Infrastructure",
    "aviation": "Infrastructure",
    "news": "General news",
    "general": "General news",
    "disaster": "Weather & disasters",
    "weather": "Weather & disasters",
    "natural disaster": "Weather & disasters",
}
_SEVERITY_RANK = {"critical": 4, "high": 3, "moderate": 2,
                  "informational": 1, "unassessed": 0}
_INACTIVE = {"retracted", "cancelled", "canceled", "expired", "resolved", "closed", "ended"}
_DOMAIN_COLOR = {
    "Conflict & security":"#e77482",
    "Unrest & civil affairs":"#ebbe72",
    "Health & disease":"#70d693",
    "Government & politics":"#b89bec",
    "Economy & business":"#5ecbbf",
    "Humanitarian":"#f0b97e",
    "Infrastructure":"#75adef",
    "General news":"#bec6dc",
    "Weather & disasters":"#e3ca78",
}
# These document-title forms identify routine regulatory paperwork, not a
# claim about the medicine, its safety, or a disease. Keep their source category
# and full archive records; only separate them from situation-focused cards.
_ROUTINE_MEDICINE_TITLES = (
    "opinion/decision on a paediatric investigation plan",
    "opinion/decision on a pediatric investigation plan",
    "orphan designation:",
    "decision on the application for modification of an agreed pip",
)


def brief_domain(record):
    """Use explicit provider/event category, never a guessed headline claim."""
    if not isinstance(record, dict):
        return "General news"
    category = str(record.get("category") or "News").strip().casefold()
    return _DOMAIN_ALIASES.get(category, "General news")


def _overview_domain(record):
    """Allow one explicit publisher topic, never a guessed headline category.

    The existing UN Peace and Security feed is stored as general News. Its
    exact configured source ID, original publisher identity and article host
    support an overview topic heading; no event/Store category is rewritten.
    Generic UN/Crisis Group news and similarly named publishers do not qualify.
    """
    domain = brief_domain(record)
    if domain != "General news" or str(record.get("category") or "").casefold() not in {"news", "general"}:
        return domain
    for report in islice(record.get("reports") or (), 100):
        if not isinstance(report, dict):
            continue
        if (report.get("source_id") != "un_peace_security"
                or report.get("origin_id") != "un_news"
                or report.get("official") is not True
                or report.get("official_scope") != "statement"):
            continue
        try:
            source = urlsplit(str(report.get("url") or ""))
            if (source.scheme == "https" and source.hostname == "news.un.org"
                    and source.port in {None, 443} and not source.username and not source.password):
                return "Conflict & security"
        except ValueError:
            continue
    return domain


def _rank(item):
    status = str(item.get("status") or "active").casefold()
    severity = _SEVERITY_RANK.get(str(item.get("severity") or "").casefold(), 0)
    # ISO dates are comparable for common normalized UTC source records.
    # Missing or invalid metadata is older, never promoted into 'breaking'.
    changed = str(item.get("updated_at") or item.get("published_at") or "")
    return (status not in _INACTIVE, severity, changed,
            min(max(int(item.get("report_count") or 0), 0), 100))


def _routine_medicine_notice(item):
    """Recognize narrow document forms, never guess an incident category.

    A safety warning, outbreak report or mixed-source event must not be hidden
    because its publisher also issues regulatory notices. Require the event
    title and every supplied report title to identify the same paperwork kind.
    """
    if brief_domain(item) != "Health & disease":
        return False
    titles = [str(item.get("title") or "").strip().casefold()]
    titles.extend(str(report.get("title") or "").strip().casefold()
                  for report in islice(item.get("reports") or (), 100)
                  if isinstance(report, dict) and report.get("title"))
    return bool(titles[0]) and all(
        title.startswith(_ROUTINE_MEDICINE_TITLES) for title in titles)


def _overview_rank(item):
    # Do this BEFORE the two-per-topic candidate truncation. Otherwise two
    # freshly collected EMA application notices evict older disease evidence
    # and the renderer never sees the more useful local record.
    return (not _routine_medicine_notice(item), *_rank(item))


def balanced_brief_sections(events, *, per_domain=3, max_total=30,
                            disaster_limit=3):
    """Select a small, auditable cross-domain set, not the first N weather rows.

    Input is already-bounded local event records. Never infer a crisis when a
    category is missing. Each identifier can appear in only one section.
    """
    if per_domain < 1 or max_total < 1 or disaster_limit < 0:
        raise ValueError("Brief limits must be positive")
    pools = defaultdict(list)
    seen = set()
    for item in list(events)[:1500]:
        if not isinstance(item, dict):
            continue
        identity = str(item.get("id") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        pools[brief_domain(item)].append(item)
    # Allocate one place to every represented category before spending the
    # remaining budget. Otherwise eight busy categories can exhaust max_total
    # and hide the final category entirely despite a 'balanced' label.
    ranked = {}
    for domain in BRIEF_DOMAINS:
        cap = per_domain
        if domain == "Weather & disasters":
            cap = min(cap, disaster_limit)
        ranked[domain] = sorted(pools.get(domain, ()), key=_rank, reverse=True)[:cap]
    chosen = defaultdict(list)
    remaining = max_total
    for position in range(per_domain):
        for domain in BRIEF_DOMAINS:
            if remaining and position < len(ranked[domain]):
                chosen[domain].append(ranked[domain][position])
                remaining -= 1
        if not remaining:
            break
    return [(domain, chosen[domain]) for domain in BRIEF_DOMAINS if chosen[domain]]


def overview_evidence_candidates(feed_events, map_evidence, *, per_domain=2):
    """Bounded source-attributed cross-domain selection from EXISTING reads.

    A 500-row recent feed may contain only weather although older Health or
    Conflict reporting remains in the same refresh's 5,000-row map inventory.
    Keep original source/date/status and all explicit user filters; the map
    inventory is already fetched, so this introduces zero Store/network calls.
    Retained significant evidence is dated, never presented as fresh news.
    """
    if not 1 <= per_domain <= 3:
        raise ValueError("Overview domain cap must be between one and three")
    pools = defaultdict(list)
    seen = set()
    for inventory in (feed_events, map_evidence):
        for item in islice(inventory or (), 5000):
            if not isinstance(item, dict):
                continue
            identity = str(item.get("id") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            bucket = pools[_overview_domain(item)]
            bucket.append(item)
            bucket.sort(key=_overview_rank, reverse=True)
            del bucket[per_domain:]
    return [item for domain in BRIEF_DOMAINS for item in pools.get(domain, ())]


def _source_time_label(report, event):
    """Never mislabel a retrieved/updated timestamp as publication time."""
    if report.get("publication_time_known") is not False and report.get("published_at"):
        return "source published " + escape(str(report["published_at"])[:40])
    fetched = report.get("first_retrieved_at") or report.get("retrieved_at")
    if fetched:
        return "first retrieved " + escape(str(fetched)[:40]) + " (publication unknown)"
    changed = event.get("updated_at")
    return ("record updated " + escape(str(changed)[:40]) +
            " (publication unknown)") if changed else "source publication unknown"


def _overview_card(item):
    """Render bounded existing evidence; no generated world-event narrative."""
    title = escape(str(item.get("title") or "Untitled source record")[:260])
    identity = quote(str(item.get("id")), safe="")
    reports = [report for report in islice(item.get("reports") or (), 100)
               if isinstance(report, dict)]
    # Never attribute current detail to an older withdrawn report just because
    # it happens to be first in the association's history.
    first = next((r for r in reports if not r.get("future_dated") and
                  r.get("evidence_status", "active") == "active"),
                 reports[0] if reports else {})
    publisher = escape(str(first.get("publisher") or first.get("source_id") or
                           item.get("publisher") or "Publisher unlisted")[:100])
    verification = str(item.get("verification") or "unverified")
    evidence = {
        "official": "official measurement (potentially revisable)",
        "corroborated": "corroborated event association; review individual claims",
        "developing": "developing association; confirmation incomplete",
        "unverified": "unverified; independent corroboration not established",
    }.get(verification, "unverified; evidence assessment unavailable")
    level = escape(str(item.get("severity") or "unassessed")[:30])
    lifecycle = escape(str(item.get("status") or "unknown")[:30])
    if item.get("retained_on_map"):
        lifecycle += " (retained; no newer status)"
    region = str(item.get("country") or item.get("region") or "").strip()
    location = (" · Record region: " + escape(region[:100])) if region else ""
    detail = ""
    # Canonical recaps already preserve publisher attribution, retractions,
    # unknown translations and evidence caveats. Display that bounded existing
    # detail rather than inventing a new summary from the headline.
    recap = " ".join(str(item.get("recap") or "").split())
    if recap and recap != str(item.get("title") or ""):
        detail = "<br><span style='color:#d2d8e2'>" + escape(recap[:650])
        if len(recap) > 650:
            detail += "…"
        detail += "</span>"
    if item.get("future_dated"):
        detail += ("<br><b style='color:#e4b576'>Future-dated source context; "
                   "not evidence of a current development.</b>")
    if _overview_domain(item) != brief_domain(item):
        detail += ("<br><span style='color:#aeb9c9'>Grouped by source topic: "
                   "United Nations News — Peace and Security. A topic grouping "
                   "does not establish an active conflict.</span>")
    official = ""
    if item.get("official_attribution") and verification != "official":
        official = ("<br>Official publication present; publication alone does not "
                    "verify every underlying claim.")
    return (
        "<p style='margin:0 0 12px'>"
        "<a style='color:#e5e3f2' href='pulse-event://open/" + identity + "'>" +
        title + "</a>" + detail +
        "<br><span style='color:#aeb9c9;font-size:11px'>" + publisher +
        " · Importance: " + level + location + "<br>Evidence: " + evidence +
        official + "<br>Record status: " + lifecycle + " · " +
        _source_time_label(first, item) + "</span></p>"
    )


def overview_html(events, *, label="visible local feed"):
    """Compact HTML for a read-only sidebar, with local event detail links."""
    limited = list(events)[:1000]
    # A direct renderer call must apply the same presentation policy as the
    # worker's shortlist, without mutating canonical records or reading Store.
    shortlist = overview_evidence_candidates(limited, ())
    routine = [item for item in shortlist if _routine_medicine_notice(item)]
    situations = [item for item in shortlist if not _routine_medicine_notice(item)]
    blocks = [
        "<h3 style='color:#eee9fa'>World intelligence overview</h3>",
        "<p style='color:#aeb9c9'>Category-balanced source headlines from the "
        + escape(label) +
        ". Unverified reports are not independently confirmed. "
        "Missing stories mean coverage is absent from these records, "
        "not that no conflict, disease, or emergency exists.</p>",
        "<p style='color:#aeb9c9'>Unassessed describes unrated importance, "
        "not whether a report is true. Official publication and independent "
        "corroboration are shown separately.</p>",
    ]
    # The normal Daily Brief uses canonical categories. This overview alone
    # honors the narrowly attributed publisher-topic fallback above. Allocate
    # one place per represented topic before filling the unchanged 16-card cap.
    # Background notices are part of that same total, not an extra allowance.
    topic_rows = defaultdict(list)
    for item in situations:
        topic_rows[_overview_domain(item)].append(item)
    sections = defaultdict(list)
    remaining = 16 - len(routine)
    for position in range(2):
        for domain in BRIEF_DOMAINS:
            if remaining and position < len(topic_rows[domain]):
                sections[domain].append(topic_rows[domain][position])
                remaining -= 1
    nonweather = sum(len(rows) for name, rows in sections.items()
                     if name != "Weather & disasters")
    for domain in BRIEF_DOMAINS:
        rows = sections.get(domain, ())
        color = _DOMAIN_COLOR[domain]
        blocks.append("<p style='margin:10px 0 3px'><b style='color:" +
                      color + "'>" + escape(domain) + "</b></p>")
        if not rows:
            if domain == "Health & disease" and routine:
                blocks.append(
                    "<p style='margin:0 0 6px;color:#aeb9c9'>"
                    "Only routine medicines/regulatory notices are represented "
                    "in this selected health sample; they are listed separately "
                    "below, not presented as outbreak or incident coverage.</p>")
                continue
            blocks.append("<p style='margin:0 0 6px;color:#818d9f'>"
                          "No matching category records in this feed. "
                          "This local coverage gap is not a worldwide all-clear.</p>")
            continue
        for item in rows:
            blocks.append(_overview_card(item))
    if routine:
        blocks.append("<p style='margin:12px 0 3px'><b style='color:#bec6dc'>"
                      "Routine medicines/regulatory notices</b></p>"
                      "<p style='color:#aeb9c9'>Application and designation "
                      "paperwork, separated from health-incident coverage. "
                      "Original Health categories and source records remain "
                      "unchanged in the feed and archive.</p>")
        blocks.extend(_overview_card(item) for item in routine)
    if nonweather == 0:
        blocks.append("<p style='color:#e4b576'><b>Coverage gap:</b> "
                      "no situation-focused non-weather records were selected "
                      "for this overview. Routine paperwork is not incident "
                      "coverage. Broaden the monitored sources "
                      "or inspect the full archive; no events are fabricated.</p>")
    blocks.append("<p style='color:#909bb0;font-size:10px'>"
                  "Open any title to inspect its original sources, dates, "
                  "corrections, and evidence trail. The full feed may contain "
                  "additional reports not shown in this short overview.</p>")
    return "".join(blocks)
