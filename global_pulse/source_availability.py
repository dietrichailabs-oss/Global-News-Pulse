"""Shared source capability and display state. No network or access approval."""
from __future__ import annotations

from .sources import SUPPORTED_ADAPTERS, public_url


def capability(source: dict) -> tuple[bool, str, str]:
    """Separate configured capability from evidence of a successful fetch."""
    status = str(source.get("status") or "").casefold()
    # Legacy registry ID for the *same* exact endpoint is not a second feed.
    # Keep the canonical poller only; this is explicitly unavailable for
    # independent collection even though its adapter and URL are valid.
    if str(source.get("disabled_reason") or "").casefold().startswith("duplicate exact feed url"):
        return False, "Duplicate feed", "The exact feed is already collected by its canonical source entry."
    if status in {"requires_approval", "credentials_required"}:
        return False, "Setup required", "Provider approval or credentials are required; collection is not configured."
    if status in {"unavailable", "disabled", "restricted"}:
        return False, "Unavailable", "This integration is unavailable; enabling a switch cannot connect it."
    adapter = source.get("adapter")
    if adapter in {None, "manual"} or status == "manual_only":
        return False, "Website only", "Open the provider website. This entry does not automatically collect reports."
    if adapter not in SUPPORTED_ADAPTERS:
        return False, "Not integrated", "No supported collector is installed for this provider."
    if source.get("access_status") not in {"reviewed_public", "user_supplied"}:
        return False, "Review required", "Source access has not been configured for collection. Open the website for information."
    try:
        public_url(source.get("url"), source.get("allowed_domains"), resolve=False)
    except (ValueError, TypeError, UnicodeError):
        return False, "Unavailable", "The configured feed address is missing or invalid."
    return True, "Automatic feed", "Collection is supported. Availability and publication freshness depend on the provider."


def available_ids(catalog: list[dict]) -> set[str]:
    """All configured collectors with approved public/user-supplied access."""
    return {s["id"] for s in catalog if capability(s)[0]}


def enabled_ids(catalog: list[dict], preference: object) -> set[str]:
    available = available_ids(catalog)
    if preference is None:
        # New profiles default to EVERY actually collectable source; the
        # historical catalog 'enabled' bit is not a user opt-out.
        return available
    requested = ({v for v in preference if isinstance(v, str)}
                 if isinstance(preference, list) else set())
    return available & requested


def migrate_all_available_sources_once(store, catalog: list[dict]) -> bool:
    """Once per installed profile, honor the owner's enable-all upgrade request.

    Preserve the previous setting for recovery, and never repeat the reset:
    subsequent per-provider user opt-outs must survive restart. This touches
    only local settings; it neither starts monitoring nor fetches a provider.
    Excluded/duplicated/unintegrated entries remain unavailable.
    """
    marker = "source_enable_all_upgrade_v1"
    backup = "enabled_sources_before_enable_all_v1"
    if store.get_setting(marker, False) is True:
        return False

    previous = store.get_setting("enabled_sources", None)
    if previous is not None:
        # Back up before changing the active list. On a partial migration,
        # preserve the FIRST original values and re-apply the desired set.
        if store.get_setting(backup, None) is None:
            store.set_setting(backup, previous)
        store.set_setting("enabled_sources", sorted(available_ids(catalog)))
    # A None preference already means all eligible and needs no list rewrite.
    # Write completion LAST so interrupted upgrades retry on next startup.
    store.set_setting(marker, True)
    return previous is not None


def source_link(source: dict) -> tuple[str, str]:
    """Prefer the real homepage; do not label an RSS document as a website."""
    for field, title in (("homepage", "Open website"), ("url", "Open feed" if capability(source)[0] else "Open website")):
        try:
            return title, public_url(source.get(field), resolve=False)
        except (ValueError, TypeError, UnicodeError):
            pass
    return "No public link", ""


def health_text(state: dict) -> str:
    """Describe the last recorded result, not a promise that a feed is live."""
    status = str(state.get("status") or "").casefold()
    if status == "rate_limited":
        return "Rate limited; waiting for provider retry"
    if status == "denied":
        # A failed 401/403 attempt supersedes an earlier successful or
        # stale-publication result. Never report it as "Not checked".
        return "Provider denied access; retry deferred"
    if status == "unavailable":
        # HTTP 503 is a failed current check, even when a previous
        # last_success and latest_publication remain in archived state.
        return "Provider temporarily unavailable; retry scheduled"
    if status == "error":
        return "Last check failed"
    if status == "stale" or state.get("freshness") == "stale":
        return "Feed reachable; reporting is stale"
    if status in {"available", "not_modified"} and state.get("last_success"):
        if state.get("freshness") == "no reports":
            return "Feed reachable; no reports in the latest response"
        if state.get("freshness") == "observations received":
            return "Feed reachable; indicator observations received; release freshness unverified"
        if not state.get("latest_publication"):
            return "Last check succeeded; publication freshness unknown"
        return "Last check succeeded" if status == "available" else "Last check: no change"
    return "Not checked"
