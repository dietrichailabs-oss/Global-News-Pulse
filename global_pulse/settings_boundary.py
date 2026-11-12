"""Read-side validation of legacy/imported preferences; no I/O or approval."""
from __future__ import annotations

import copy
import re
from datetime import datetime

SUPPORTED_INTERVALS = frozenset({300, 600, 1800, 3600})
from .capacity_limits import MAX_TOTAL_SOURCES


def _integer(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and len(value) <= 20:
        value = value.strip()
        if re.fullmatch(r"-?[0-9]{1,10}", value):
            return int(value)
    return None


def monitoring_interval(value):
    parsed = _integer(value)
    return parsed if parsed in SUPPORTED_INTERVALS else 600


def retention_days(value):
    parsed = _integer(value)
    return 365 if parsed is None else max(1, min(3650, parsed))


def quiet_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}", value):
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def quiet_hours_active(settings, now=None):
    if not isinstance(settings, dict) or settings.get("quiet_enabled", False) is not True:
        return False
    start = quiet_time(settings.get("quiet_start", "22:00"))
    end = quiet_time(settings.get("quiet_end", "07:00"))
    if start is None or end is None:
        return False
    current = (now or datetime.now().astimezone()).time().replace(tzinfo=None)
    if start == end:
        return True
    return start <= current < end if start < end else current >= start or current < end


def user_feeds(value, bundled_ids=()):
    """Ignore unsafe records without rewriting the stored preference.

    Only configurations compatible with make_user_feed are admitted; unknown
    fields do not confer official status or source-access approval. DNS checks
    remain in the unchanged collector, not the UI/startup thread.
    """
    from .sources import public_url

    if not isinstance(value, list):
        return []
    seen = set(bundled_ids)
    capacity = max(0, MAX_TOTAL_SOURCES - len(seen))
    result = []
    for source in value[:4000]:
        if len(result) >= capacity:
            break
        if not isinstance(source, dict):
            continue
        sid, name = source.get("id"), source.get("name")
        if not isinstance(sid, str) or not re.fullmatch(r"[a-z0-9_-]{1,80}", sid) or sid in seen:
            continue
        if not isinstance(name, str) or not name.strip() or len(name) > 1000:
            continue
        adapter, access = source.get("adapter"), source.get("access_status")
        if not isinstance(adapter, str) or adapter not in {"rss", "atom"}:
            continue
        if not isinstance(access, str) or access not in {"user_supplied", "unreviewed", "review_required", "restricted"}:
            continue
        if source.get("custom") is not True or type(source.get("enabled")) is not bool:
            continue
        if source.get("metadata_only") is not True or source.get("official") is not False or source.get("independence") != "unknown":
            continue
        domains = source.get("allowed_domains")
        if not isinstance(domains, list) or not 1 <= len(domains) <= 64 or any(not isinstance(d, str) or not d for d in domains):
            continue
        text_fields = ("status", "category", "region", "country", "language", "license", "access", "attribution", "homepage", "official_scope")
        if any(not isinstance(source[k], str) or len(source[k]) > 4096 for k in text_fields if k in source):
            continue
        domain_fields = ("article_domains", "upgrade_http_domains")
        if any(not isinstance(source[k], list) or len(source[k]) > 64 or any(not isinstance(d, str) for d in source[k]) for k in domain_fields if k in source):
            continue
        interval = _integer(source.get("min_interval", 600))
        keep_days = _integer(source.get("retention_days", 30))
        stale_days = _integer(source.get("stale_after_days", 90))
        if interval is None or not 300 <= interval <= 31_536_000 or keep_days is None or not 1 <= keep_days <= 3650 or stale_days is None or not 1 <= stale_days <= 3650:
            continue
        try:
            public_url(source.get("url"), domains, resolve=False)
        except (ValueError, TypeError, UnicodeError):
            continue
        result.append(copy.deepcopy(source))
        seen.add(sid)
    return result
