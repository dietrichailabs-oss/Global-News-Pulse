"""Conservative, category-balanced presentation of locally collected evidence.

Neither rankings nor sections assert that a crisis exists worldwide. No model,
network request, inference of event coordinates, or article scraping occurs.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import islice
from html import escape
from urllib.parse import quote

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


def brief_domain(record):
    """Use explicit provider/event category, never a guessed headline claim."""
    if not isinstance(record, dict):
        return "General news"
    category = str(record.get("category") or "News").strip().casefold()
    return _DOMAIN_ALIASES.get(category, "General news")


def _rank(item):
    status = str(item.get("status") or "active").casefold()
    severity = _SEVERITY_RANK.get(str(item.get("severity") or "").casefold(), 0)
    # ISO dates are comparable for common normalized UTC source records.
    # Missing or invalid metadata is older, never promoted into 'breaking'.
    changed = str(item.get("updated_at") or item.get("published_at") or "")
    return (status not in _INACTIVE, severity, changed,
            min(max(int(item.get("report_count") or 0), 0), 100))


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
    remaining = max_total
    selected = []
    for domain in BRIEF_DOMAINS:
        if remaining <= 0:
            break
        cap = min(per_domain, remaining)
        if domain == "Weather & disasters":
            cap = min(cap, disaster_limit)
        chosen = sorted(pools.get(domain, ()), key=_rank, reverse=True)[:cap]
        if chosen:
            selected.append((domain, chosen))
            remaining -= len(chosen)
    return selected


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
            bucket = pools[brief_domain(item)]
            bucket.append(item)
            bucket.sort(key=_rank, reverse=True)
            del bucket[per_domain:]
    return [item for domain in BRIEF_DOMAINS for item in pools.get(domain, ())]


def _source_time_label(report, event):
    """Never mislabel a retrieved/updated timestamp as publication time."""
    if report.get("publication_time_known") is not False and report.get("published_at"):
        return "source published " + escape(str(report["published_at"])[:19])
    fetched = report.get("first_retrieved_at") or report.get("retrieved_at")
    if fetched:
        return "first retrieved " + escape(str(fetched)[:19]) + " (publication unknown)"
    changed = event.get("updated_at")
    return ("record updated " + escape(str(changed)[:19]) +
            " (publication unknown)") if changed else "source publication unknown"


def overview_html(events, *, label="visible local feed"):
    """Compact HTML for a read-only sidebar, with local event detail links."""
    limited = list(events)[:1000]
    blocks = [
        "<h3 style='color:#eee9fa'>World intelligence overview</h3>",
        "<p style='color:#aeb9c9'>Category-balanced source headlines from the "
        + escape(label) +
        ". Unverified reports are not independently confirmed. "
        "Missing stories mean coverage is absent from these records, "
        "not that no conflict, disease, or emergency exists.</p>",
    ]
    sections = dict(balanced_brief_sections(limited, per_domain=2,
                                             max_total=16, disaster_limit=2))
    nonweather = sum(len(rows) for name, rows in sections.items()
                     if name != "Weather & disasters")
    for domain in BRIEF_DOMAINS:
        rows = sections.get(domain, ())
        color = _DOMAIN_COLOR[domain]
        blocks.append("<p style='margin:10px 0 3px'><b style='color:" +
                      color + "'>" + escape(domain) + "</b></p>")
        if not rows:
            blocks.append("<p style='margin:0 0 6px;color:#818d9f'>"
                          "No matching category records in this feed.</p>")
            continue
        for item in rows:
            title = escape(str(item.get("title") or "Untitled source record")[:200])
            identity = quote(str(item.get("id")), safe="")
            reports = item.get("reports") or []
            first = next((r for r in reports if isinstance(r, dict)), {})
            publisher = escape(str(first.get("publisher") or
                                   first.get("source_id") or
                                   item.get("publisher") or "Publisher unlisted")[:65])
            status = escape(str(item.get("verification") or "unverified")[:30])
            level = escape(str(item.get("severity") or "unassessed")[:30])
            lifecycle = escape(str(item.get("status") or "unknown")[:30])
            if item.get("retained_on_map"):
                lifecycle += " (retained; no newer status)"
            time_label = _source_time_label(first, item)
            blocks.append(
                "<p style='margin:0 0 9px'>"
                "<a style='color:#e5e3f2' href='pulse-event://open/" +
                identity + "'>" + title + "</a>"
                "<br><span style='color:#8d9aad;font-size:10px'>" +
                publisher + " · " + level + " · " + status +
                " · " + lifecycle + "<br>" + time_label + "</span></p>"
            )
    if nonweather == 0:
        blocks.append("<p style='color:#e4b576'><b>Coverage gap:</b> "
                      "no non-weather categories were represented in the "
                      "retrieved local feed. Broaden the monitored sources "
                      "or inspect the full archive; no events are fabricated.</p>")
    blocks.append("<p style='color:#909bb0;font-size:10px'>"
                  "Open any title to inspect its original sources, dates, "
                  "corrections, and evidence trail. The full feed may contain "
                  "additional reports not shown in this short overview.</p>")
    return "".join(blocks)
