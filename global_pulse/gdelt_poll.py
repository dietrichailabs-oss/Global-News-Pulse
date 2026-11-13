"""Explicit, opt-in GDELT 2.0 manifest/export poll with bounded HTTPS transport.

This does not silently activate a background collector or reinterpret GDELT-coded
events as verified eyewitness reports. The caller schedules checks and surfaces
returned states, including gaps and source errors.
"""
from __future__ import annotations

from datetime import datetime
import re
import time
import httpx
from .gdelt_http import GdeltHTTPError

from .gdelt_batches import (
    GdeltBatchCache, GdeltBatchError, MANIFEST_URL, MASTER_LIST_URL,
    MAX_MANIFEST_BYTES, MAX_ARCHIVE_BYTES, parse_manifest,
)

_HEADERS = {
    "User-Agent": "GlobalPulse/0.1 (public GDELT event-batch cache)",
    "Accept": "text/plain,application/zip;q=0.9",
    "Accept-Encoding": "identity",
}


def _bounded_get(client: httpx.Client, url: str, limit: int) -> bytes:
    """Fetch one reviewed GDELT URL with a tiny same-URL replication retry.

    GDELT occasionally publishes the manifest entry before an edge serves the
    corresponding archive, which can yield a short-lived 404. Retry only the
    exact same URL and only a small transient status set; never switch to the
    DOC search API, rotate hosts, or hide a persistent failure.
    """
    # Same-turn retries are deliberately limited to GDELT's observed
    # publication-lag 404. Rate limits and 5xx responses return immediately to
    # the durable scheduler so Retry-After/backoff is honored rather than
    # hammering the provider.
    for attempt in range(3):
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code != 200:
                if response.status_code == 404 and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise GdeltHTTPError(response.status_code, response.headers.get("retry-after"))
            header = response.headers.get("content-length")
            if header is not None:
                # Reject before int(): hostile input cannot hit Python's integer
                # conversion limit. Missing length still uses the streaming cap.
                if not (1 <= len(header) <= 20 and header.isascii() and header.isdecimal()):
                    raise GdeltBatchError("GDELT response has invalid Content-Length")
                if int(header) > limit:
                    raise GdeltBatchError("GDELT response exceeds size limit")
            body = bytearray()
            for part in response.iter_bytes(64 * 1024):
                if len(body) + len(part) > limit:
                    raise GdeltBatchError("GDELT response exceeds size limit")
                body.extend(part)
            if not body:
                raise GdeltBatchError("GDELT endpoint returned empty response")
            return bytes(body)
    raise GdeltBatchError("GDELT transient retry exhausted")


_MASTER_TAIL_BYTES = 64 * 1024


def _master_tail(client: httpx.Client) -> bytes:
    """Read only the final 64 KiB of GDELT's official master list.

    The full list is roughly hundreds of megabytes and is never downloaded.
    A server that ignores Range is rejected before its body is consumed.
    """
    with client.stream(
        "GET", MASTER_LIST_URL, follow_redirects=False,
        headers={"Range": f"bytes=-{_MASTER_TAIL_BYTES}"},
    ) as response:
        if response.status_code != 206:
            raise GdeltHTTPError(response.status_code, response.headers.get("retry-after"))
        content_range = str(response.headers.get("content-range") or "")
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
        if not match:
            raise GdeltBatchError("GDELT master-list range response is invalid")
        start, end, total = map(int, match.groups())
        if start < 0 or end < start or total <= end or end - start + 1 > _MASTER_TAIL_BYTES:
            raise GdeltBatchError("GDELT master-list range exceeds bounded tail")
        body = bytearray()
        for part in response.iter_bytes(16 * 1024):
            if len(body) + len(part) > _MASTER_TAIL_BYTES:
                raise GdeltBatchError("GDELT master-list tail exceeds size limit")
            body.extend(part)
        if not body:
            raise GdeltBatchError("GDELT master-list tail is empty")
        # A 206 status alone is not proof of the complete official byte range.
        # Reject truncated or padded bodies before parsing apparent master rows.
        if len(body) != end - start + 1:
            raise GdeltBatchError("GDELT master-list Content-Range body length mismatch")
        # Unless this range starts at byte zero, its first line can be partial.
        if start:
            split = body.find(b"\n")
            if split < 0:
                raise GdeltBatchError("GDELT master-list tail contains no complete line")
            body = body[split + 1:]
        return bytes(body)


def _fallback_export_from_master(client: httpx.Client, before_timestamp: str):
    """Newest checksum-bearing published EXPORT strictly before a missing latest."""
    try:
        text = _master_tail(client).decode("ascii")
    except UnicodeDecodeError as exc:
        raise GdeltBatchError("GDELT master-list tail is not ASCII") from exc
    candidates = []
    for line in text.splitlines():
        if ".export.CSV.zip" not in line:
            continue
        try:
            batch = parse_manifest(line).get("export")
        except GdeltBatchError:
            continue
        if batch and batch.timestamp < before_timestamp and batch.advertised_bytes <= MAX_ARCHIVE_BYTES:
            candidates.append(batch)
    if not candidates:
        raise GdeltBatchError("GDELT master list has no earlier bounded EXPORT fallback")
    return max(candidates, key=lambda item: item.timestamp)


def poll_latest_export(cache: GdeltBatchCache, *, client: httpx.Client | None = None) -> dict:
    """Check one manifest, import at most one *new* EXPORT batch.

    Caller owns pacing (GDELT's 15-minute publication is not a license to
    hammer a different DOC search API). No catch-up or GKG/Mentions claims.
    Missing older intervals are explicitly flagged for later bounded recovery.
    """
    if client is None:
        with httpx.Client(timeout=httpx.Timeout(30, connect=6),
                          follow_redirects=False, trust_env=False,
                          headers=_HEADERS) as owned:
            return poll_latest_export(cache, client=owned)
    prior = cache.connection.execute(
        "SELECT MAX(batch_timestamp) FROM gdelt_batches WHERE status='complete' AND kind='export'"
    ).fetchone()[0]
    batch = None
    attempt = ""  # No owned attempt until reserve succeeds.
    try:
        manifest = parse_manifest(_bounded_get(client, MANIFEST_URL, MAX_MANIFEST_BYTES))
        batch = manifest.get("export")
        if batch is None:
            raise GdeltBatchError("GDELT manifest does not publish an EXPORT batch")
        result = {
            "kind": "export", "batch_timestamp": batch.timestamp,
            "manifest_url": MANIFEST_URL, "dataset": "GDELT 2.0 coded events",
            "gap_detected": cache.has_unresolved_export_gap(batch.timestamp),
        }
        if cache.is_complete(batch):
            return dict(result, status="already_imported", downloaded=False)
        # Check advertised metadata before issuing any archive request.
        if batch.advertised_bytes > MAX_ARCHIVE_BYTES:
            raise GdeltBatchError("GDELT advertised batch exceeds configured archive cap")
        if not cache.reserve(batch):
            return dict(result, status="already_imported" if cache.is_complete(batch)
                        else "download_in_progress", downloaded=False)
        attempt = cache.reservation_token(batch)
        if not attempt:
            raise GdeltBatchError("GDELT reservation identity unavailable")
        try:
            archive = _bounded_get(client, batch.url, MAX_ARCHIVE_BYTES)
        except GdeltHTTPError as exc:
            if exc.status != 404:
                raise
            # lastupdate.txt can briefly lead the readable object. Preserve the
            # failed newest attempt, then fall back only to an earlier EXPORT
            # independently listed by the official checksum-bearing master list.
            listed_batch = batch
            cache.record_fetch_error(listed_batch, str(exc), attempt=attempt)
            attempt = ""
            fallback = _fallback_export_from_master(client, listed_batch.timestamp)
            batch = fallback
            result.update(
                batch_timestamp=batch.timestamp,
                listed_batch_timestamp=listed_batch.timestamp,
                replication_pending=True,
                recovered_from_master_list=True,
                gap_detected=cache.has_unresolved_export_gap(batch.timestamp),
            )
            if cache.is_complete(batch):
                return dict(result, status="already_imported", downloaded=False)
            if not cache.reserve(batch):
                return dict(
                    result,
                    status="already_imported" if cache.is_complete(batch) else "download_in_progress",
                    downloaded=False,
                )
            attempt = cache.reservation_token(batch)
            if not attempt:
                raise GdeltBatchError("GDELT fallback reservation identity unavailable")
            archive = _bounded_get(client, batch.url, MAX_ARCHIVE_BYTES)
        imported = cache.import_export(batch, archive, attempt=attempt)
        return dict(result, **imported, downloaded=True)
    except (GdeltBatchError, httpx.HTTPError, OSError) as exc:
        # Never persist request URLs or platform proxy credentials.
        reason = (str(exc) if isinstance(exc, GdeltBatchError)
                  else "GDELT network connection unavailable")
        if batch is not None:
            cache.record_fetch_error(batch, reason, attempt=attempt)
        return {"status": "error", "error": reason, "batch_timestamp": batch.timestamp if batch else None,
                "kind": "export", "downloaded": False,
                **(exc.schedule_fields() if isinstance(exc, GdeltHTTPError) else {})}
