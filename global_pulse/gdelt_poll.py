"""Explicit, opt-in GDELT 2.0 manifest/export poll with bounded HTTPS transport.

This does not silently activate a background collector or reinterpret GDELT-coded
events as verified eyewitness reports. The caller schedules checks and surfaces
returned states, including gaps and source errors.
"""
from __future__ import annotations

from datetime import datetime
import httpx
from .gdelt_http import GdeltHTTPError

from .gdelt_batches import (
    GdeltBatchCache, GdeltBatchError, MANIFEST_URL, MAX_MANIFEST_BYTES,
    MAX_ARCHIVE_BYTES, parse_manifest,
)

_HEADERS = {
    "User-Agent": "GlobalPulse/0.1 (public GDELT event-batch cache)",
    "Accept": "text/plain,application/zip;q=0.9",
    "Accept-Encoding": "identity",
}


def _bounded_get(client: httpx.Client, url: str, limit: int) -> bytes:
    # Caller-supplied GDELT HTTPS URLs are validated by parse_manifest; the
    # manifest URL is a constant. Redirects are never followed.
    with client.stream("GET", url, follow_redirects=False) as response:
        if response.status_code != 200:
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
