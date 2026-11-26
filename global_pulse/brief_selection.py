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
# Same existing map inventory bound, plus the bounded feed/brief candidate pool.
MAX_PRIORITY_RECORDS = 5500
MAX_CRITICAL_ALERTS = 5000
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


def is_active_critical(item):
    """Map red is recorded critical importance, never inferred verification."""
    return (isinstance(item,dict) and bool(item.get("id"))
            and str(item.get("status") or "active").casefold()=="active"
            and str(item.get("severity") or "").casefold()=="critical"
            and not item.get("future_dated"))


def priority_rank(item):
    # Current developments precede historical/withdrawn/future context.
    # Within each state the recorded importance, then date, decides order.
    current=(str(item.get("status") or "active").casefold() not in _INACTIVE
             and not item.get("future_dated"))
    return (current, *_rank(item))


def priority_heading(item):
    if (str(item.get("status") or "active").casefold() in _INACTIVE
            or item.get("future_dated")):
        return "Historical or withdrawn context"
    return {"critical":"Critical alerts", "high":"High priority",
            "moderate":"Moderate priority", "informational":"Informational updates"
            }.get(str(item.get("severity") or "").casefold(),"Unassessed importance")


def critical_alerts(events):
    seen=set()
    rows=[]
    for item in islice(events or (),MAX_PRIORITY_RECORDS):
        if not is_active_critical(item):
            continue
        identity=str(item["id"])
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(item)
    return sorted(rows,key=priority_rank,reverse=True)[:MAX_CRITICAL_ALERTS]


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
    for item in islice(events, MAX_PRIORITY_RECORDS):
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
    critical = []
    # Prefer the canonical map-evidence projection for a critical record
    # already present in both exact-revision inventories; other feed rows
    # retain their original source identity and bounded selection.
    map_red={str(row["id"]):row for row in islice(map_evidence or (),5000)
             if is_active_critical(row)}
    for inventory in (feed_events, map_evidence):
        for item in islice(inventory or (), MAX_PRIORITY_RECORDS):
            if not isinstance(item, dict):
                continue
            identity = str(item.get("id") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            item=map_red.get(identity,item)
            if is_active_critical(item):
                critical.append(item)
                continue
            bucket = pools[_overview_domain(item)]
            bucket.append(item)
            bucket.sort(key=_overview_rank, reverse=True)
            del bucket[per_domain:]
    return (critical_alerts(critical) +
            [item for domain in BRIEF_DOMAINS for item in pools.get(domain, ())])


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


def _compact_critical_card(item):
    """One source-linked line per additional red alert, not a new claim."""
    title=escape(str(item.get("title") or "Untitled source record")[:260])
    identity=quote(str(item.get("id")),safe="")
    location=escape(str(item.get("country") or item.get("region") or "Location unspecified")[:100])
    verification=escape(str(item.get("verification") or "unverified")[:32])
    updated=escape(str(item.get("updated_at") or item.get("published_at") or "unknown")[:40])
    retained=" · retained; no newer status" if item.get("retained_on_map") else ""
    return ("<p style='margin:2px 0 5px'><b style='color:#f06475'>CRITICAL</b> · "
            "<a style='color:#e5e3f2' href='pulse-event://open/"+identity+"'>"+title+"</a>"
            "<br><span style='color:#aeb9c9;font-size:10px'>"+location+" · "+verification+
            " · record update "+updated+retained+"</span></p>")


def overview_html(events, *, label="visible local feed"):
    """Compact live intelligence, red alerts first, then rated importance."""
    shortlist = overview_evidence_candidates(list(islice(events,MAX_PRIORITY_RECORDS)), ())
    red=critical_alerts(shortlist)
    ordinary=[item for item in shortlist if not is_active_critical(item)]
    routine = [item for item in ordinary if _routine_medicine_notice(item)]
    situations = [item for item in ordinary if not _routine_medicine_notice(item)]
    blocks = [
        "<h3 style='color:#eee9fa'>World intelligence overview</h3>",
        "<p style='color:#aeb9c9'>Priority-ranked source headlines from the "
        + escape(label) +
        ". Unverified reports are not independently confirmed. "
        "Missing stories mean coverage is absent from these records, "
        "not that no conflict, disease, or emergency exists.</p>",
        "<p style='color:#aeb9c9'>Unassessed describes unrated importance, "
        "not whether a report is true. Official publication and independent "
        "corroboration are shown separately.</p>",
        "<p style='margin:12px 0 3px'><b style='color:#f06475'>Critical alerts — immediate attention</b></p>",
    ]
    if red:
        blocks.append("<p style='color:#aeb9c9'>"+str(len(red))+
                      " active critical record(s) in this bounded local inventory; red indicates importance, not confirmed claims.</p>")
        # Give the first few alerts fuller source context; list every other
        # red alert compactly and retain its exact event link.
        blocks.extend(_overview_card(item) if index<3 else _compact_critical_card(item)
                      for index,item in enumerate(red))
    else:
        blocks.append("<p style='color:#818d9f'>No active critical alerts in the supplied local scope. This is not a worldwide all-clear.</p>")
    topic_rows=defaultdict(list)
    for item in situations:
        topic_rows[_overview_domain(item)].append(item)
    selected=[]
    remaining=16-len(routine)
    for position in range(2):
        for domain in BRIEF_DOMAINS:
            if remaining and position<len(topic_rows[domain]):
                selected.append(topic_rows[domain][position])
                remaining-=1
    selected.sort(key=priority_rank,reverse=True)
    heading=None
    for item in selected:
        priority=priority_heading(item)
        if priority!=heading:
            heading=priority
            blocks.append("<p style='margin:12px 0 4px'><b style='color:#e6d6fa'>"+escape(heading)+"</b></p>")
        domain=_overview_domain(item)
        blocks.append("<p style='margin:5px 0 1px'><b style='color:"+_DOMAIN_COLOR[domain]+"'>"+
                      escape(domain)+"</b></p>")
        blocks.append(_overview_card(item))
    present={_overview_domain(item) for item in red+selected}
    absent=[domain for domain in BRIEF_DOMAINS if domain not in present]
    if absent:
        blocks.append("<p style='margin:12px 0 3px'><b style='color:#aeb9c9'>Coverage gaps</b></p>")
    for domain in absent:
        blocks.append("<p style='margin:5px 0 3px'><b style='color:"+_DOMAIN_COLOR[domain]+"'>"+escape(domain)+"</b></p>")
        if domain=="Health & disease" and routine:
            blocks.append(
                "<p style='margin:0 0 6px;color:#aeb9c9'>"
                "Only routine medicines/regulatory notices are represented "
                "in this selected health sample; they are listed separately "
                "below, not presented as outbreak or incident coverage.</p>")
        else:
            blocks.append("<p style='margin:0 0 6px;color:#818d9f'>"
                          "No matching category records in this feed. "
                          "This local coverage gap is not a worldwide all-clear.</p>")
    if routine:
        blocks.append("<p style='margin:12px 0 3px'><b style='color:#bec6dc'>"
                      "Routine medicines/regulatory notices</b></p>"
                      "<p style='color:#aeb9c9'>Application and designation "
                      "paperwork, separated from health-incident coverage. "
                      "Original Health categories and source records remain "
                      "unchanged in the feed and archive.</p>")
        blocks.extend(_overview_card(item) for item in routine)
    if not any(_overview_domain(item)!="Weather & disasters" for item in red+selected):
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
