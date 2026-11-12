"""Bounded, local GDELT 2.0 batch cache. No network requests or UI activation.

Stage one deliberately admits only the published event EXPORT batches; the
manifest's Mentions and GKG entries remain unimported until separately parsed.
Rows are GDELT-coded *observations*, not independently verified news reports,
and their geocodes are not promoted to precise incident map pins.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit
import zipfile
from uuid import uuid4


MANIFEST_URL = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
HOST = "data.gdeltproject.org"
MAX_MANIFEST_BYTES = 8192
MAX_ARCHIVE_BYTES = 24 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 96 * 1024 * 1024
MAX_BATCH_ROWS = 100_000
MAX_CACHED_ROWS = 300_000
KINDS = ("export", "mentions", "gkg")
_FILE = re.compile(r"(?P<stamp>[0-9]{14})\.(?P<kind>export\.CSV|mentions\.CSV|gkg\.csv)\.zip\Z")
_CHECKSUM = re.compile(r"[0-9a-fA-F]{32}\Z")


class GdeltBatchError(ValueError):
    """Bounded, non-URL-bearing error suitable for local status presentation."""


@dataclass(frozen=True)
class GdeltBatch:
    filename: str
    kind: str
    timestamp: str
    url: str
    advertised_bytes: int
    advertised_md5: str


def _stamp(value: str) -> datetime:
    try:
        result = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise GdeltBatchError("Invalid GDELT batch timestamp") from exc
    if result.minute not in (0, 15, 30, 45) or result.second:
        raise GdeltBatchError("GDELT batch is not on a 15-minute boundary")
    return result


def parse_manifest(raw: str | bytes) -> dict[str, GdeltBatch]:
    """Parse the published 3-line update listing, never an arbitrary download URL."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_MANIFEST_BYTES:
            raise GdeltBatchError("GDELT manifest exceeds size limit")
        try:
            raw = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise GdeltBatchError("GDELT manifest is not ASCII") from exc
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise GdeltBatchError("GDELT manifest exceeds size limit")
    entries: dict[str, GdeltBatch] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3:
            raise GdeltBatchError("Malformed GDELT manifest entry")
        size_text, checksum, raw_url = parts
        if len(size_text) > 15 or not size_text.isascii() or not size_text.isdecimal() or not _CHECKSUM.fullmatch(checksum):
            raise GdeltBatchError("Invalid GDELT manifest size or digest")
        try:
            parsed = urlsplit(raw_url)
            if parsed.scheme not in ("http", "https") or parsed.hostname != HOST or parsed.port is not None:
                raise GdeltBatchError("Unexpected GDELT batch host")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise GdeltBatchError("Unsafe GDELT archive URL")
        except ValueError as exc:
            raise GdeltBatchError("Invalid GDELT archive URL") from exc
        prefix = "/gdeltv2/"
        if not parsed.path.startswith(prefix) or "/" in parsed.path[len(prefix):]:
            raise GdeltBatchError("Unexpected GDELT archive path")
        filename = parsed.path[len(prefix):]
        match = _FILE.fullmatch(filename)
        if not match:
            raise GdeltBatchError("Unexpected GDELT archive name")
        _stamp(match.group("stamp"))
        kind = {"export.CSV": "export", "mentions.CSV": "mentions", "gkg.csv": "gkg"}[match.group("kind")]
        if kind in entries:
            raise GdeltBatchError("Duplicate GDELT manifest dataset")
        size = int(size_text)
        if size < 1:
            raise GdeltBatchError("Invalid GDELT advertised archive size")
        # The GDELT listing may contain HTTP links; constrain host/path, then
        # upgrade exactly those links to HTTPS without following redirects.
        entries[kind] = GdeltBatch(filename, kind, match.group("stamp"),
                                    f"https://{HOST}{parsed.path}", size, checksum.lower())
    if not entries or set(entries) - set(KINDS):
        raise GdeltBatchError("No supported GDELT manifest entries")
    return entries


SCHEMA = """
CREATE TABLE IF NOT EXISTS gdelt_batches (
 filename TEXT PRIMARY KEY, kind TEXT NOT NULL, batch_timestamp TEXT NOT NULL,
 source_url TEXT NOT NULL, advertised_bytes INTEGER NOT NULL, advertised_md5 TEXT NOT NULL,
 status TEXT NOT NULL, imported_at TEXT, lease_until TEXT, lease_token TEXT, records_seen INTEGER NOT NULL DEFAULT 0,
 records_added INTEGER NOT NULL DEFAULT 0, records_rejected INTEGER NOT NULL DEFAULT 0,
 records_duplicate INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
 parser_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS gdelt_batches_status ON gdelt_batches(status,batch_timestamp);
CREATE TABLE IF NOT EXISTS gdelt_event_rows (
 global_event_id TEXT PRIMARY KEY, filename TEXT NOT NULL REFERENCES gdelt_batches(filename),
 batch_timestamp TEXT NOT NULL, event_day TEXT NOT NULL, date_added TEXT NOT NULL,
 event_code TEXT NOT NULL, quad_class TEXT NOT NULL,
 action_country_code TEXT NOT NULL, action_location TEXT NOT NULL,
 action_latitude REAL, action_longitude REAL,
 source_article_url TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS gdelt_event_rows_batch ON gdelt_event_rows(batch_timestamp);
"""


def _article_url(raw: str) -> str:
    url = raw.strip()
    if len(url) > 2048 or any(ord(c) < 32 for c in url):
        raise GdeltBatchError("Invalid GDELT source attribution URL")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise GdeltBatchError("Invalid GDELT source attribution URL")
    return url


def _geo(value: str, *, latitude: bool) -> float | None:
    if not value.strip():
        return None
    try:
        n = float(value)
    except ValueError as exc:
        raise GdeltBatchError("Invalid GDELT geocode") from exc
    import math
    if not math.isfinite(n) or not (-90 <= n <= 90 if latitude else -180 <= n <= 180):
        raise GdeltBatchError("Invalid GDELT geocode")
    return n


def _row(fields: list[str], batch: GdeltBatch) -> tuple:
    # GDELT 2.0 EXPORT codebook has exactly 61 TAB-separated columns.
    if len(fields) != 61 or not re.fullmatch(r"[0-9]{1,20}", fields[0]):
        raise GdeltBatchError("Invalid GDELT event record")
    if not re.fullmatch(r"[0-9]{8}", fields[1]) or not re.fullmatch(r"[0-9]{14}", fields[59]):
        raise GdeltBatchError("Invalid GDELT event dates")
    # Validate calendar dates; DATEADDED, not event day, identifies feed freshness.
    try:
        datetime.strptime(fields[1], "%Y%m%d")
        datetime.strptime(fields[59], "%Y%m%d%H%M%S")
    except ValueError as exc:
        raise GdeltBatchError("Invalid GDELT event date") from exc
    if not re.fullmatch(r"[0-9]{1,4}", fields[26]) or fields[29] not in ("1", "2", "3", "4"):
        raise GdeltBatchError("Invalid GDELT CAMEO classification")
    return (fields[0], batch.filename, batch.timestamp, fields[1], fields[59],
            fields[26], fields[29], fields[53][:12], fields[52][:256],
            _geo(fields[56], latitude=True), _geo(fields[57], latitude=False),
            _article_url(fields[60]))


from .archive_storage import write_transaction, StorageBlocked


class GdeltBatchCache:
    """Separate GDELT-only tables in the existing SQLite archive.

    Never deletes Global Pulse reports, events, saved Situations, observations,
    settings, or exports. No archive is fetched without an explicit caller.
    """

    def __init__(self, database: str | Path, *, max_rows: int = MAX_CACHED_ROWS):
        self.database = str(database)
        self.max_rows = max(1, min(MAX_CACHED_ROWS, int(max_rows)))
        self._leases: dict[str, str] = {}
        self.connection = sqlite3.connect(str(database), timeout=15)
        self.connection.execute("PRAGMA busy_timeout=15000")
        if self.connection.execute("PRAGMA page_count").fetchone()[0] == 0:
            self.connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA + "\nCREATE TABLE IF NOT EXISTS gdelt_retained_rows(global_event_id TEXT PRIMARY KEY REFERENCES gdelt_event_rows(global_event_id) ON DELETE RESTRICT);")
        # Additive migration, serialized with competing cache constructors.
        # Legacy active leases without a token stay excluded until expiry.
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in self.connection.execute("PRAGMA table_info(gdelt_batches)")}
            for name in ("lease_until", "lease_token"):
                if name not in columns:
                    self.connection.execute(f"ALTER TABLE gdelt_batches ADD COLUMN {name} TEXT")

    def close(self) -> None:
        self._leases.clear()
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def status(self) -> dict:
        row = self.connection.execute(
            "SELECT filename,kind,batch_timestamp,imported_at,records_seen,"
            "records_added,records_rejected,records_duplicate,error,status "
            "FROM gdelt_batches ORDER BY batch_timestamp DESC LIMIT 1"
        ).fetchone()
        count = self.connection.execute("SELECT COUNT(*) FROM gdelt_event_rows").fetchone()[0]
        return {"cached_rows": count, "latest_batch": dict(zip(
            ("filename", "kind", "timestamp", "imported_at", "seen", "added",
             "rejected", "duplicates", "error", "status"), row)) if row else None}

    def has_unresolved_export_gap(self, latest: str | None = None) -> bool:
        """Historic publication discontinuities remain visible across restarts.

        Only an actually completed 15-minute EXPORT checkpoint closes a gap;
        merely observing a newer manifest or finishing a later adjacent batch
        does not fabricate completion for missed intervals.
        """
        timestamps = [row[0] for row in self.connection.execute(
            "SELECT batch_timestamp FROM gdelt_batches WHERE status='complete' "
            "AND kind='export' ORDER BY batch_timestamp")]
        if latest and (not timestamps or latest > timestamps[-1]):
            timestamps.append(latest)
        for previous, following in zip(timestamps, timestamps[1:]):
            try:
                gap = _stamp(following) - _stamp(previous)
            except GdeltBatchError:
                return True
            if gap.total_seconds() > 15 * 60:
                return True
        return False

    def is_complete(self, batch: GdeltBatch) -> bool:
        row = self.connection.execute(
            "SELECT status FROM gdelt_batches WHERE filename=?", (batch.filename,)
        ).fetchone()
        return bool(row and row[0] == "complete")

    @staticmethod
    def _validate_batch(batch: GdeltBatch) -> None:
        if not isinstance(batch, GdeltBatch):
            raise GdeltBatchError("GDELT batch identity is invalid")
        verified = parse_manifest(
            f"{batch.advertised_bytes} {batch.advertised_md5} {batch.url}\n"
        ).get(batch.kind)
        if verified != batch:
            raise GdeltBatchError("GDELT batch identity differs from manifest")

    def reservation_token(self, batch: GdeltBatch) -> str | None:
        """Return this connection's handle; callers must capture it per attempt.

        This does not read/adopt another connection's token from the database.
        An expired lease permits takeover; only the current generation can
        transition the row, even if a superseded operation finishes later.
        """
        return self._leases.get(batch.filename)

    def _owns_attempt(self, batch: GdeltBatch, token: str | None) -> bool:
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            return False
        row = self.connection.execute(
            "SELECT kind,batch_timestamp,source_url,advertised_bytes,advertised_md5,"
            "status,lease_token FROM gdelt_batches WHERE filename=?", (batch.filename,)
        ).fetchone()
        return bool(row and row[:5] == (batch.kind, batch.timestamp, batch.url,
                    batch.advertised_bytes, batch.advertised_md5)
                    and row[5] in {"downloading", "processing"} and row[6] == token)

    def reserve(self, batch: GdeltBatch, *, now: datetime | None = None) -> bool:
        """Atomically acquire one generation; stale callers never own its successor."""
        self._validate_batch(batch)
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expiry = (moment + timedelta(minutes=3)).isoformat()
        token = uuid4().hex
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT status,lease_until FROM gdelt_batches WHERE filename=?",
                (batch.filename,)).fetchone()
            if row and (row[0] == "complete" or
                        (row[0] in {"downloading", "processing"} and row[1]
                         and row[1] > moment.isoformat())):
                return False
            self.connection.execute(
                "INSERT INTO gdelt_batches(filename,kind,batch_timestamp,source_url,"
                "advertised_bytes,advertised_md5,status,error,lease_until,lease_token) "
                "VALUES(?,?,?,?,?,?,'downloading','',?,?) "
                "ON CONFLICT(filename) DO UPDATE SET status='downloading',"
                "error='',lease_until=excluded.lease_until,lease_token=excluded.lease_token,"
                "source_url=excluded.source_url,advertised_bytes=excluded.advertised_bytes,"
                "advertised_md5=excluded.advertised_md5",
                (batch.filename, batch.kind, batch.timestamp, batch.url,
                 batch.advertised_bytes, batch.advertised_md5, expiry, token))
        self._leases[batch.filename] = token
        return True

    def import_export(self, batch: GdeltBatch, archive: bytes, *, now: str | None = None,
                      attempt: str | None = None) -> dict:
        if batch.kind != "export":
            raise GdeltBatchError("Only GDELT EXPORT import is implemented")
        self._validate_batch(batch)
        if self.is_complete(batch):
            return {"status": "already_imported", "filename": batch.filename}
        token = self.reservation_token(batch) if attempt is None else attempt
        if token is None:
            # Compatibility for explicit offline imports: acquire the same
            # protected reservation rather than bypassing an active downloader.
            if not self.reserve(batch):
                if self.is_complete(batch):
                    return {"status": "already_imported", "filename": batch.filename}
                raise GdeltBatchError("GDELT batch is owned by another attempt")
            token = self.reservation_token(batch)
        if not self._owns_attempt(batch, token):
            raise GdeltBatchError("GDELT batch attempt was superseded")
        try:
            if not isinstance(archive, bytes) or not (0 < len(archive) <= MAX_ARCHIVE_BYTES):
                raise GdeltBatchError("GDELT download exceeds archive size limit")
            if len(archive) != batch.advertised_bytes:
                raise GdeltBatchError("GDELT archive size mismatch")
            if hashlib.md5(archive).hexdigest() != batch.advertised_md5:
                raise GdeltBatchError("GDELT archive digest mismatch")
            with zipfile.ZipFile(io.BytesIO(archive), "r") as zipped:
                members = zipped.infolist()
                expected_name = batch.filename.removesuffix(".zip")
                if len(members) != 1 or members[0].filename != expected_name or members[0].is_dir():
                    raise GdeltBatchError("GDELT ZIP has unexpected member/path")
                if not 0 < members[0].file_size <= MAX_UNCOMPRESSED_BYTES:
                    raise GdeltBatchError("GDELT expanded archive exceeds size limit")
                if members[0].compress_size > MAX_ARCHIVE_BYTES:
                    raise GdeltBatchError("GDELT ZIP entry exceeds compressed size limit")
                with zipped.open(members[0]) as extracted:
                    # SQLite transaction is all-or-nothing for normalized rows AND
                    # the durable batch-completed checkpoint.
                    with write_transaction(self.connection, self.database):
                        if self.is_complete(batch):
                            return {"status": "already_imported", "filename": batch.filename}
                        # Recheck after BEGIN IMMEDIATE: ownership may have
                        # changed while ZIP validation ran outside the write lock.
                        if not self._owns_attempt(batch, token):
                            raise GdeltBatchError("GDELT batch attempt was superseded")
                        changed = self.connection.execute(
                            "UPDATE gdelt_batches SET status='processing',error='' "
                            "WHERE filename=? AND lease_token=?", (batch.filename, token))
                        if changed.rowcount != 1:
                            raise GdeltBatchError("GDELT batch attempt was superseded")
                        before = self.connection.execute(
                            "SELECT COUNT(*) FROM gdelt_event_rows").fetchone()[0]
                        seen = added = rejected = duplicate = 0
                        stream = io.TextIOWrapper(extracted, encoding="utf-8", errors="replace", newline="")
                        for fields in csv.reader(stream, delimiter="\t"):
                            seen += 1
                            if seen > MAX_BATCH_ROWS:
                                raise GdeltBatchError("GDELT batch row limit exceeded")
                            try:
                                values = _row(fields, batch)
                            except (GdeltBatchError, ValueError):
                                rejected += 1
                                continue
                            cursor = self.connection.execute(
                                "INSERT OR IGNORE INTO gdelt_event_rows VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                values)
                            if cursor.rowcount:
                                added += 1
                                if before + added > self.max_rows:
                                    raise GdeltBatchError("GDELT local row cap reached; prune or increase cap")
                            else:
                                duplicate += 1
                        if not seen:
                            raise GdeltBatchError("GDELT export contains no records")
                        imported_at = now or datetime.now(timezone.utc).isoformat()
                        self.connection.execute(
                            "UPDATE gdelt_batches SET status='complete',lease_until=NULL,lease_token=NULL,imported_at=?,"
                            "records_seen=?,records_added=?,records_rejected=?,"
                            "records_duplicate=?,error='' WHERE filename=? AND lease_token=?",
                            (imported_at, seen, added, rejected, duplicate, batch.filename, token))
            if self._leases.get(batch.filename) == token:
                self._leases.pop(batch.filename, None)
            return {"status": "complete", "filename": batch.filename,
                    "seen": seen, "added": added, "rejected": rejected, "duplicates": duplicate}
        except StorageBlocked:
            try:
                self.record_fetch_error(batch, "GDELT archive storage budget reached", attempt=token)
            except sqlite3.Error:
                pass
            raise
        except (GdeltBatchError, zipfile.BadZipFile, csv.Error, RuntimeError, OSError, EOFError) as exc:
            # No partial rows/checkpoint survive a failed import. Only a bounded,
            # generic error message enters local diagnostics; never archive URLs.
            reason = str(exc) if isinstance(exc, GdeltBatchError) else "Invalid GDELT ZIP payload"
            self.record_fetch_error(batch, reason, attempt=token)
            raise GdeltBatchError(reason) from exc

    def record_fetch_error(self, batch: GdeltBatch, error: str, *,
                           attempt: str | None = None) -> None:
        """A failure can release only its own current reservation.

        None supports existing per-connection callers. Polling passes an explicit
        captured token (or empty string when no reservation was acquired).
        Unowned metadata failures may create a missing error row, never modify
        an existing checkpoint, successor lease, or another attempt's failure.
        """
        self._validate_batch(batch)
        token = self.reservation_token(batch) if attempt is None else attempt
        safe = str(error)[:160]
        if not (safe.startswith("GDELT ") or safe.startswith("Only GDELT ")):
            safe = "GDELT fetch failed"
        changed = False
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if token:
                if self._owns_attempt(batch, token):
                    cursor = self.connection.execute(
                        "UPDATE gdelt_batches SET status='error',error=?,lease_until=NULL,"
                        "lease_token=NULL WHERE filename=? AND lease_token=?",
                        (safe, batch.filename, token))
                    changed = cursor.rowcount == 1
            else:
                self.connection.execute(
                    "INSERT INTO gdelt_batches(filename,kind,batch_timestamp,source_url,"
                    "advertised_bytes,advertised_md5,status,error) VALUES(?,?,?,?,?,?,'error',?) "
                    "ON CONFLICT(filename) DO NOTHING",
                    (batch.filename, batch.kind, batch.timestamp, batch.url,
                     batch.advertised_bytes, batch.advertised_md5, safe))
        if changed and self._leases.get(batch.filename) == token:
            self._leases.pop(batch.filename, None)

    def prune(self, *, retention_days: int = 7, now: datetime | None = None) -> int:
        days = max(1, min(365, int(retention_days)))
        boundary = ((now or datetime.now(timezone.utc)).astimezone(timezone.utc)
                    - timedelta(days=days)).strftime("%Y%m%d%H%M%S")
        # Never erase successful batch checkpoints, even when their cached rows
        # expire, or a replay would silently reimport expired data.
        with write_transaction(self.connection, self.database):
            cursor = self.connection.execute(
                "DELETE FROM gdelt_event_rows WHERE batch_timestamp < ? AND global_event_id NOT IN (SELECT global_event_id FROM gdelt_retained_rows)", (boundary,))
            return cursor.rowcount
