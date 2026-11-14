"""Durable, attempt-owned GDELT scheduling; no network or GUI dependencies."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import timezone
from email.utils import parsedate_to_datetime
import re
import secrets
import sqlite3
import time
from uuid import uuid4

INTERVAL = 900
MAX_EPOCH = 253402300799
_SCHEMA = """
CREATE TABLE IF NOT EXISTS gdelt_schedule (
 id INTEGER PRIMARY KEY CHECK(id=1), next_at INTEGER NOT NULL DEFAULT 0,
 failures INTEGER NOT NULL DEFAULT 0, suspended INTEGER NOT NULL DEFAULT 0,
 token TEXT, last_attempt INTEGER NOT NULL DEFAULT 0,
 last_success INTEGER NOT NULL DEFAULT 0, last_batch TEXT NOT NULL DEFAULT '',
 cached_rows INTEGER NOT NULL DEFAULT 0, gap INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'idle', http_status INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO gdelt_schedule(id) VALUES(1);
"""


def _now(value=None):
    value = int(time.time()) if value is None else value
    if type(value) is not int or not 0 <= value < MAX_EPOCH - 86400:
        raise ValueError("Invalid scheduling clock")
    return value


def retention_days(value):
    return value if type(value) is int and 1 <= value <= 365 else 7


def retry_after(value, now=None):
    """Parse bounded delta/date delays; huge valid delays never become early retries.

    The second return value requires explicit review for unrepresentable delays.
    No provider-controlled text is persisted or displayed.
    """
    moment = _now(now)
    if not isinstance(value, str) or not value:
        return 0, False
    if value.isascii() and value.isdecimal():
        if len(value) > 10:
            return MAX_EPOCH - moment, True
        seconds = int(value)
        return min(seconds, MAX_EPOCH - moment), seconds > MAX_EPOCH - moment
    if len(value) > 128:
        return 0, False
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0, min(MAX_EPOCH - moment, int(date.timestamp()) - moment)), False
    except (ValueError, TypeError, OverflowError, OSError):
        return 0, False


class Schedule:
    """Only this feature's singleton table is modified; no archive pruning here."""
    def __init__(self, database):
        self.database = str(database)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.database, timeout=0.25)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(_SCHEMA)
            yield connection
        finally:
            connection.close()

    def status(self):
        with self.db() as db:
            return dict(db.execute("SELECT * FROM gdelt_schedule WHERE id=1").fetchone())

    def claim(self, *, now=None, jitter=None):
        moment = _now(now)
        jitter = secrets.randbelow(31) if jitter is None else jitter
        if type(jitter) is not int or not 0 <= jitter <= 30:
            raise ValueError("Invalid scheduling jitter")
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT * FROM gdelt_schedule WHERE id=1").fetchone()
            if state['suspended'] or state['next_at'] > moment:
                return None
            token = uuid4().hex
            # Reserve the next network opportunity BEFORE starting a child.
            # A crash/reopen cannot reset this durable minimum interval.
            db.execute("UPDATE gdelt_schedule SET token=?,next_at=?,last_attempt=?,state='collecting' WHERE id=1",
                       (token, moment + INTERVAL + jitter, moment))
            return token

    def finish(self, token, result, *, now=None, cancelled=False):
        moment = _now(now)
        if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token):
            return False
        result = result if isinstance(result, dict) else {}
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM gdelt_schedule WHERE id=1").fetchone()
            if row['token'] != token:
                return False
            if cancelled:
                db.execute("UPDATE gdelt_schedule SET token=NULL,state='cancelled' WHERE id=1 AND token=?", (token,))
                return True
            outcome = result.get('status')
            success = outcome in ('complete', 'already_imported')
            busy = outcome == 'download_in_progress'
            failures = 0 if success else row['failures'] if busy else min(20, row['failures'] + 1)
            status = result.get('http_status', 0)
            status = status if type(status) is int and 100 <= status <= 599 else 0
            delay = result.get('retry_after_seconds', 0)
            # A delay saturated at HTTP receipt can exceed the remaining epoch
            # range by completion. Saturate again, never discard it as zero.
            # Strict integer admission still rejects booleans and malformed data.
            delay = min(delay, MAX_EPOCH - moment) if type(delay) is int and delay >= 0 else 0
            suspended = (not success and not busy and
                (status in (401, 403) or failures >= 5 or result.get('retry_after_unbounded') is True or result.get('storage_blocked') is True))
            backoff = INTERVAL if success or busy else min(21600, INTERVAL * 2 ** min(5, failures - 1))
            next_at = min(MAX_EPOCH, max(row['next_at'], moment + backoff, moment + delay))
            stamp = result.get('batch_timestamp', '')
            stamp = stamp if success and isinstance(stamp, str) and re.fullmatch(r'[0-9]{14}', stamp) else row['last_batch']
            count = result.get('cached_rows', row['cached_rows'])
            count = count if type(count) is int and 0 <= count <= 300000 else row['cached_rows']
            gap = result.get('gap_detected')
            gap = int(gap) if type(gap) is bool else row['gap']
            state = 'current' if success else 'busy' if busy else 'storage_paused' if result.get('storage_blocked') is True else 'suspended' if suspended else 'error'
            db.execute("UPDATE gdelt_schedule SET token=NULL,next_at=?,failures=?,suspended=?,last_success=?,"
                       "last_batch=?,cached_rows=?,gap=?,state=?,http_status=? WHERE id=1 AND token=?",
                       (next_at, failures, int(suspended), moment if success else row['last_success'],
                        stamp, count, gap, state, status, token))
            return True

    def recover_legacy_transport_failure(self):
        """Clear only the pre-fix never-successful 301/404 suspension.

        The old client could suspend a fresh archive after repeatedly treating
        GDELT publication lag/redirect behavior as a hard failure. Preserve
        next_at and all successful history; never reopen access denials or a
        collector that has previously imported data.
        """
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM gdelt_schedule WHERE id=1").fetchone()
            eligible=(row['token'] is None and bool(row['suspended'])
                      and row['last_success']==0 and row['cached_rows']==0
                      and row['http_status'] in (301,404))
            if not eligible:
                return False
            db.execute(
                "UPDATE gdelt_schedule SET suspended=0,failures=0,state='waiting' "
                "WHERE id=1 AND token IS NULL"
            )
            return True

    def review_retry(self):
        """Explicit user action; never shortens a provider delay or starts a fetch."""
        with self.db() as db, db:
            db.execute("UPDATE gdelt_schedule SET suspended=0,failures=0,state='waiting' WHERE id=1 AND token IS NULL")
