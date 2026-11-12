"""Issue #22 official-source admission batch 2.

Only official FTC, Census Bureau and DOJ Antitrust RSS endpoints are considered.
A source is admitted only after the production Collector returns current dated
HTTPS-linked reports and the production Store preserves their identities across
SQLite close/reopen. No article body is fetched.
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

BASE = "9401c80dda45435ee38b2f8b708d7fb62281e49f"
CATALOG = Path("global_pulse/resources/sources.json")
OUT = Path("docs/engineering/GP-OFFICIAL-FEEDS-BATCH2-20261111")


def candidate(sid, name, url, homepage, category, documentation, policy, basis):
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
        "allowed_domains": [url.split("/")[2]],
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
        "article_domains": [url.split("/")[2]],
        "feed_documentation": documentation,
        "limitation": (
            "Official agency statements are attributable to that agency, not independent "
            "confirmation of every claim. Third-party photos/graphics and full articles "
            "are excluded. Publisher location is not an incident location."
        ),
    }


def candidates():
    return [
        candidate(
            "ftc_press",
            "Federal Trade Commission — Press Releases",
            "https://www.ftc.gov/feeds/press-release.xml",
            "https://www.ftc.gov/news-events/news/press-releases",
            "Government",
            "https://www.ftc.gov/stay-connected/rss",
            "https://search.ftc.gov/policy-notices/website-policy",
            "Most FTC-authored website material is U.S. Government work in the public domain; attribute FTC and exclude identified third-party material, seals and implied endorsement.",
        ),
        candidate(
            "census_press",
            "U.S. Census Bureau — News Releases",
            "https://www.census.gov/content/census/en/newsroom/press-releases.xml",
            "https://www.census.gov/newsroom.html",
            "Economy",
            "https://www.census.gov/about/contact-us/feeds.html",
            "https://www2.census.gov/foia/ds_policies/ds027.pdf",
            "Census Bureau employee works generally are not subject to U.S. copyright; cite Census Bureau. This integration uses RSS headline/link metadata only and excludes third-party/multimedia material.",
        ),
        candidate(
            "doj_antitrust_news",
            "U.S. Department of Justice Antitrust Division — News",
            "https://www.justice.gov/news/rss?field_component=376&require_all=0&search_api_language=en&show_public_archived=0&type%5B0%5D=image_gallery&type%5B1%5D=press_release&type%5B2%5D=speech&type%5B3%5D=youtube_video",
            "https://www.justice.gov/atr",
            "Government",
            "https://www.justice.gov/atr/news-feeds",
            "https://www.justice.gov/legalpolicies",
            "Unless otherwise indicated, DOJ website information is public domain; cite DOJ and exclude third-party photos/graphics and protected seals.",
        ),
    ]


def atomic_json(path: Path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def eligible_reports(source, result, now):
    state = result.get("state") or {}
    reports = result.get("reports") or []
    accepted = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        if report.get("source_id") != source["id"] or not report.get("title"):
            continue
        if not str(report.get("url", "")).startswith("https://"):
            continue
        raw = report.get("published_at")
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
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

    baseline_bytes = subprocess.check_output(["git", "show", BASE + ":" + CATALOG.as_posix()])
    baseline = json.loads(baseline_bytes)
    working = json.loads(CATALOG.read_text(encoding="utf-8"))
    if working != baseline:
        raise RuntimeError("Runtime source catalog differs from selected corrected baseline; reconcile rather than overwrite")
    existing_ids = {source["id"] for source in baseline["sources"]}
    existing_urls = {source["url"] for source in baseline["sources"]}
    proposals = candidates()
    if any(source["id"] in existing_ids or source["url"] in existing_urls for source in proposals):
        raise RuntimeError("Batch 2 duplicates an existing runtime provider identity or endpoint")

    receipts = []
    admitted = []
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
        result = Collector(source, now=lambda: now).collect({"configured_interval": source["min_interval"]})
        state = result["state"]
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
            try:
                with tempfile.TemporaryDirectory(prefix="gp-official2-") as folder:
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
                receipt.update(status="store_failed", error_type=type(exc).__name__)
        receipts.append(receipt)
        atomic_json(OUT / "live-check.json", {"baseline": BASE, "complete": False, "sources": receipts})
        print("GP_OFFICIAL2_FEED", json.dumps(receipt, sort_keys=True), flush=True)
        time.sleep(5)

    report = {
        "baseline": BASE,
        "complete": True,
        "attempted": len(receipts),
        "admitted_count": len(admitted),
        "admitted_ids": [source["id"] for source in admitted],
        "sources": receipts,
        "article_fetches": 0,
        "sustained_reliability_verified": False,
        "packaged_windows_verified": False,
        "physical_windows11_verified": False,
        "limits": "One bounded sequential Collector/Store observation per endpoint; not sustained reliability, legal certification or release acceptance.",
    }
    atomic_json(OUT / "live-check.json", report)
    if not admitted:
        raise RuntimeError("No batch-2 source passed current dated Collector + Store + SQLite reopen admission")

    baseline["sources"].extend(admitted)
    baseline["catalog_version"] = "2026.11.11.official2"
    baseline["reviewed_at"] = "2026-11-11"
    atomic_json(CATALOG, baseline)
    load_catalog(CATALOG)
    print("GP_OFFICIAL2_ADMITTED", len(admitted), ",".join(source["id"] for source in admitted), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--consent-network", action="store_true")
    args = parser.parse_args()
    if not args.consent_network:
        parser.error("Explicit --consent-network required")
    audit()
