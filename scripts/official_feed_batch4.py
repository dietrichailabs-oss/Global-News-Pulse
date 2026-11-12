"""Issue #22 official-source admission batch 4.

Candidates are SEC press releases, Federal Reserve Board press releases, and
EPA compliance/enforcement news releases. A source is admitted only after the
production Collector returns at least one current, non-future, dated HTTPS-linked
report and the production Store preserves report identity across SQLite reopen.
No article bodies are fetched.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

BASE = "c9f472e58ac61ea57749fb51dbebe21cf056c2a7"
CATALOG = Path("global_pulse/resources/sources.json")
OUT = Path("docs/engineering/GP-OFFICIAL-FEEDS-BATCH4-20261111")


def candidate(sid, name, url, homepage, category, documentation, policy, basis, domains):
    return {
        "id": sid,
        "name": name,
        "url": url,
        "homepage": homepage,
        "adapter": "rss",
        "category": category,
        "region": "North America",
        "country": "United States",
        "language": "en",
        "enabled": True,
        "min_interval": 3600,
        "allowed_domains": domains,
        "access": "Publisher-documented public RSS; no account or API key",
        "access_status": "reviewed_public",
        "license": basis,
        "license_url": policy,
        "attribution": name + "; original link retained; feed text may be abridged; no endorsement",
        "status": "not_checked",
        "authentication": "None",
        "review_date": "2026-11-11",
        "review_scope": "Engineering metadata/feed admission; independent QA pending",
        "retention_days": 90,
        "stale_after_days": 14,
        "official": True,
        "official_scope": "statement",
        "independence": "original",
        "metadata_only": True,
        "article_domains": domains,
        "feed_documentation": documentation,
        "limitation": (
            "Official statements are attributable to the issuing agency, not independent "
            "confirmation of every claim. Third-party media/full articles are excluded. "
            "Publisher location is not incident geography."
        ),
    }


def candidates():
    return [
        candidate(
            "sec_press",
            "U.S. Securities and Exchange Commission — Press Releases",
            "https://www.sec.gov/news/pressreleases.rss",
            "https://www.sec.gov/newsroom/press-releases",
            "Economy",
            "https://www.sec.gov/about/rss-feeds",
            "https://www.sec.gov/about/privacy",
            "SEC expressly publishes a press-release RSS feed. Integration is limited to feed headline/link metadata with SEC attribution and no full-article/media republication claim.",
            ["www.sec.gov"],
        ),
        candidate(
            "federal_reserve_press",
            "Federal Reserve Board — All Press Releases",
            "https://www.federalreserve.gov/feeds/press_all.xml",
            "https://www.federalreserve.gov/newsevents/pressreleases.htm",
            "Economy",
            "https://www.federalreserve.gov/feeds/feeds.htm",
            "https://www.federalreserve.gov/disclaimer.htm",
            "Federal Reserve Board expressly publishes RSS feeds for all press releases. Integration uses headline/link metadata only with Board attribution.",
            ["www.federalreserve.gov"],
        ),
        candidate(
            "epa_enforcement_news",
            "U.S. EPA — Compliance and Enforcement News Releases",
            "https://www.epa.gov/newsreleases/search/rss/news_releases_language/en/subject/compliance-and-enforcement-226191",
            "https://www.epa.gov/newsroom",
            "Government",
            "https://echo.epa.gov/aggregator/sources/1",
            "https://www.epa.gov/web-policies-and-procedures",
            "EPA exposes a public RSS endpoint for compliance/enforcement news. Integration uses supplied headline/link metadata only with EPA attribution.",
            ["www.epa.gov"],
        ),
    ]


def atomic_json(path: Path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def eligible_reports(source, result, now):
    state = result.get("state") or {}
    accepted = []
    for report in result.get("reports") or []:
        if not isinstance(report, dict):
            continue
        if report.get("source_id") != source["id"] or not report.get("title"):
            continue
        if not str(report.get("url", "")).startswith("https://"):
            continue
        try:
            stamp = datetime.fromisoformat(str(report.get("published_at")).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age = (now - stamp.astimezone(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            continue
        if 0 <= age <= 14 * 86400:
            accepted.append(report)
    return state.get("status") == "available" and bool(accepted), accepted


def audit():
    from global_pulse.core import Store
    from global_pulse.sources import Collector, load_catalog, utcnow

    baseline = json.loads(subprocess.check_output(["git", "show", BASE + ":" + CATALOG.as_posix()]))
    working = json.loads(CATALOG.read_text(encoding="utf-8"))
    if working != baseline:
        raise RuntimeError("Runtime source catalog differs from accepted PR93 baseline; reconcile rather than overwrite")

    existing_ids = {s["id"] for s in baseline["sources"]}
    existing_urls = {s["url"] for s in baseline["sources"]}
    proposals = candidates()
    if any(s["id"] in existing_ids or s["url"] in existing_urls for s in proposals):
        raise RuntimeError("Batch 4 duplicates an existing runtime provider identity or endpoint")

    receipts, admitted = [], []
    for source in proposals:
        now = utcnow()
        receipt = {
            "id": source["id"],
            "name": source["name"],
            "feed_url": source["url"],
            "feed_documentation": source["feed_documentation"],
            "policy_url": source["license_url"],
            "checked_at": now.isoformat(),
            "minimum_poll_seconds": source["min_interval"],
            "article_fetches": 0,
            "status": "not_checked",
        }
        try:
            result = Collector(source, now=lambda: now).collect({"configured_interval": source["min_interval"]})
            state = result.get("state") or {}
            reports = result.get("reports") or []
            receipt.update(
                http_status=state.get("http_status"),
                collector_status=state.get("status"),
                parsed_reports=len(reports),
                bytes_received=state.get("bytes_received"),
                reporting_freshness=state.get("freshness"),
                newest_publication=state.get("latest_publication"),
                next_poll=state.get("next_poll"),
            )
            okay, current = eligible_reports(source, result, now)
            receipt["current_linked_reports"] = len(current)
            if not okay:
                receipt["status"] = "not_admitted"
            else:
                with tempfile.TemporaryDirectory(prefix="gp-official4-") as folder:
                    db_path = Path(folder) / "live.sqlite3"
                    store = Store(db_path, mode="live")
                    try:
                        store.ingest(reports)
                        events = store.list_events(limit=2000)
                        seen = {
                            report["id"]
                            for event in events
                            for report in event.get("reports", [])
                            if report.get("source_id") == source["id"]
                        }
                        assert seen and any(report["id"] in seen for report in current)
                        receipt["stored_report_ids"] = len(seen)
                        receipt["stored_events"] = len(events)
                        receipt["parsed_identity_sha256"] = hashlib.sha256(
                            "\n".join(sorted(report["id"] for report in reports)).encode()
                        ).hexdigest()
                    finally:
                        store.close()
                    reopened = Store(db_path, mode="live")
                    try:
                        restored = reopened.list_events(limit=2000)
                        restored_ids = {
                            report["id"]
                            for event in restored
                            for report in event.get("reports", [])
                            if report.get("source_id") == source["id"]
                        }
                        assert restored_ids == seen
                        receipt["sqlite_reopen_verified"] = True
                    finally:
                        reopened.close()
                receipt["status"] = "collector_store_pass"
                admitted.append(copy.deepcopy(source))
        except Exception as exc:
            receipt.update(status="not_admitted", error_type=type(exc).__name__, error=str(exc)[:240])

        receipts.append(receipt)
        atomic_json(OUT / "live-check.json", {"baseline": BASE, "complete": False, "sources": receipts})
        print("GP_OFFICIAL4_FEED", json.dumps(receipt, sort_keys=True), flush=True)
        time.sleep(5)

    report = {
        "baseline": BASE,
        "complete": True,
        "attempted": len(receipts),
        "admitted_count": len(admitted),
        "admitted_ids": [s["id"] for s in admitted],
        "sources": receipts,
        "article_fetches": 0,
        "sustained_reliability_verified": False,
        "packaged_windows_verified": False,
        "physical_windows11_verified": False,
        "limits": "One bounded sequential Collector/Store observation per endpoint; not sustained reliability, legal certification or release acceptance.",
    }
    atomic_json(OUT / "live-check.json", report)
    if not admitted:
        raise RuntimeError("No batch-4 source passed current dated Collector + Store + SQLite reopen admission")

    baseline["sources"].extend(admitted)
    baseline["catalog_version"] = "2026.11.11.official4"
    baseline["reviewed_at"] = "2026-11-11"
    atomic_json(CATALOG, baseline)
    load_catalog(CATALOG)
    print("GP_OFFICIAL4_ADMITTED", len(admitted), ",".join(s["id"] for s in admitted), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--consent-network", action="store_true")
    args = parser.parse_args()
    if not args.consent_network:
        parser.error("Explicit --consent-network required")
    audit()
