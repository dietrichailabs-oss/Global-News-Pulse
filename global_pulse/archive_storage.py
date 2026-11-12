"""News-archive byte budget, bounded write admission, and GDELT-only cleanup.

The allowance covers the shared SQLite database and its WAL/SHM/rollback files.
Ingestion reserves conservative journal/checkpoint headroom before writing. It is
not an OS quota over exports, model packs, other programs, or the whole data dir.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import time

GB = 1_000_000_000
CHOICES_GB = (5, 10, 15, 20, 30, 50, 100)
DEFAULT_GB = 30
CONTROL_RESERVE = 16 * 1024 * 1024
FREE_FLOOR = 256 * 1024 * 1024
IMPORT_HEADROOM = 128 * 1024 * 1024
MESSAGES = {
    'capacity': 'Archive collection paused: the selected size limit has insufficient database/journal working space. Clean disposable cache or increase the limit.',
    'low_disk': 'Archive collection paused: insufficient free space on this drive. Free disk space before resuming.',
    'unsafe_path': 'Archive collection paused: the archive or a SQLite sidecar redirects outside its expected file.',
    'cleanup_pending': 'Cleanup reached its bounded work limit. Collection remains paused; run cleanup again before resuming.',
    'protected': 'Collection paused: disposable cache cannot free enough space. Saved reporting is preserved. Increase the limit or free disk space.',
    'storage_busy': 'Archive storage is busy or unavailable. No new archive data was committed.',
}


class StorageBlocked(RuntimeError):
    def __init__(self, code='capacity'):
        self.code = code if code in MESSAGES else 'storage_busy'
        super().__init__(MESSAGES[self.code])


def size_gb(value):
    return value if type(value) is int and value in CHOICES_GB else DEFAULT_GB


def read_limit(connection):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone():
        return DEFAULT_GB
    row = connection.execute("SELECT value FROM settings WHERE key='archive_max_gb'").fetchone()
    try:
        return size_gb(json.loads(row[0])) if row else DEFAULT_GB
    except (ValueError, TypeError):
        return DEFAULT_GB


def footprint(database):
    path = Path(database).absolute()
    if path.resolve() != path:
        raise StorageBlocked('unsafe_path')
    sizes = {}
    for suffix in ('', '-wal', '-shm', '-journal'):
        candidate = Path(str(path) + suffix)
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            sizes[suffix or 'database'] = 0
            continue
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400 or info.st_nlink > 1):
            raise StorageBlocked('unsafe_path')
        sizes[suffix or 'database'] = info.st_size
    return sizes


def snapshot(connection, database):
    selected = read_limit(connection)
    limit = selected * GB
    files = footprint(database)
    page_size = connection.execute('PRAGMA page_size').fetchone()[0]
    pages = connection.execute('PRAGMA page_count').fetchone()[0]
    free_pages = connection.execute('PRAGMA freelist_count').fetchone()[0]
    disk_free = shutil.disk_usage(Path(database).absolute().parent).free
    used = sum(files.values())
    sidecars = used - files['database']
    # With cache_spill disabled, reserve one WAL frame per dirty page plus
    # checkpoint growth and small-control/SHM headroom. Existing sidecars count
    # in full. This intentionally can stop ingestion below the displayed cap.
    cap_pages = max(0, (limit - sidecars - CONTROL_RESERVE) // (2 * page_size + 24))
    disk_pages = max(0, (disk_free - FREE_FLOOR - CONTROL_RESERVE
                         + files['database']) // (2 * page_size + 24))
    page_limit = min(cap_pages, disk_pages)
    required_pages = max(pages, (files['database'] + page_size - 1) // page_size)
    reason = ('low_disk' if disk_pages < required_pages or disk_free < FREE_FLOOR else
              'capacity' if cap_pages < required_pages or used > limit else '')
    return dict(selected_gb=selected, limit_bytes=limit, used_bytes=used,
                files=files, free_disk_bytes=disk_free, page_size=page_size,
                pages=pages, free_pages=free_pages, page_limit=page_limit,
                reusable_bytes=free_pages * page_size,
                growth_room=max(0, page_limit - pages + free_pages) * page_size,
                state=reason or ('warning' if used >= limit * .8 else 'ready'),
                message=MESSAGES.get(reason, ''), can_collect=not reason)


@contextmanager
def write_transaction(connection, database):
    """Writer-locked admission plus a SQLite page ceiling; FULL rolls back batch.

    Callers must not start or commit an inner transaction. Small metadata
    controls remain available within the reserved headroom.
    """
    if str(database) == ':memory:':
        with connection:
            yield
        return
    if connection.in_transaction:
        raise StorageBlocked('storage_busy')
    original_limit = connection.execute('PRAGMA max_page_count').fetchone()[0]
    original_spill = connection.execute('PRAGMA cache_spill').fetchone()[0]
    try:
        connection.execute('PRAGMA cache_spill=OFF')
        connection.execute('BEGIN IMMEDIATE')
        state = snapshot(connection, database)
        if not state['can_collect']:
            raise StorageBlocked(state['state'])
        actual = connection.execute(f"PRAGMA max_page_count={state['page_limit']}").fetchone()[0]
        if actual > state['page_limit']:
            raise StorageBlocked('capacity')
        yield
        connection.commit()
    except BaseException as exc:
        connection.rollback()
        if isinstance(exc, sqlite3.Error) and getattr(exc, 'sqlite_errorcode', 0) == sqlite3.SQLITE_FULL:
            raise StorageBlocked('capacity') from exc
        raise
    finally:
        connection.execute(f'PRAGMA max_page_count={original_limit}')
        connection.execute(f'PRAGMA cache_spill={original_spill}')


def checkpoint(connection):
    if connection.in_transaction:
        raise StorageBlocked('storage_busy')
    if connection.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'wal':
        result = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if result and result[0]:
            raise StorageBlocked('storage_busy')


def _reclaim(connection, database):
    # Legacy databases retain reusable free pages. Never make an unbounded full
    # VACUUM/copy, replace a live database pathname, or unlink its journal.
    if connection.execute('PRAGMA auto_vacuum').fetchone()[0] == 2:
        with write_transaction(connection, database):
            connection.execute('PRAGMA incremental_vacuum(256)').fetchall()
    checkpoint(connection)


def cleanup(cache, database, days=7, *, now=None):
    """Only expired/oldest unpinned GDELT rows; checkpoints and Store untouched."""
    connection = cache.connection
    checkpoint(connection)
    removed = cache.prune(retention_days=days, now=now)
    _reclaim(connection, database)
    deadline = time.monotonic() + 30
    from .gdelt_batches import MAX_BATCH_ROWS
    keep_rows = max(0, cache.max_rows - MAX_BATCH_ROWS)
    for _ in range(600):
        state = snapshot(connection, database)
        count = connection.execute('SELECT COUNT(*) FROM gdelt_event_rows').fetchone()[0]
        if state['can_collect'] and state['growth_room'] >= IMPORT_HEADROOM and count <= keep_rows:
            return dict(removed_rows=removed, **state)
        if time.monotonic() >= deadline:
            raise StorageBlocked('cleanup_pending')
        amount = min(512, max(1, count - keep_rows)) if state['growth_room'] >= IMPORT_HEADROOM else 512
        with write_transaction(connection, database):
            cursor = connection.execute('''DELETE FROM gdelt_event_rows WHERE global_event_id IN (
                SELECT r.global_event_id FROM gdelt_event_rows r
                WHERE NOT EXISTS (SELECT 1 FROM gdelt_retained_rows p WHERE p.global_event_id=r.global_event_id)
                ORDER BY r.batch_timestamp,r.global_event_id LIMIT ?)''', (amount,))
        removed += cursor.rowcount
        _reclaim(connection, database)
        if cursor.rowcount == 0:
            raise StorageBlocked('protected')
    raise StorageBlocked('cleanup_pending')


def save_cleanup_status(connection, result):
    safe = {key: result.get(key) for key in ('state', 'removed_rows', 'used_bytes')}
    attempt = result.get('attempt')
    if (isinstance(attempt, str) and len(attempt) == 32
            and all(ch in '0123456789abcdef' for ch in attempt)):
        safe['attempt'] = attempt
    safe['at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connection:
        connection.execute('CREATE TABLE IF NOT EXISTS archive_storage_status(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        connection.execute('INSERT INTO archive_storage_status VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                           (json.dumps(safe),))


def last_cleanup(connection):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='archive_storage_status'").fetchone():
        return {}
    row = connection.execute('SELECT body FROM archive_storage_status WHERE id=1').fetchone()
    try:
        value = json.loads(row[0]) if row else {}
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


# The latest attempt is distinct from the last completed worker's cleanup
# receipt. A killed process may have committed earlier cleanup batches, so do
# not infer zero rows removed or replace its previous successful receipt.
CLEANUP_ATTEMPT_STATES = frozenset({
    'success', 'failed_start', 'failed_exit', 'timeout', 'cancelled',
    'missing_receipt', 'receipt_unavailable',
})


def save_cleanup_attempt(connection, token, state):
    if (not isinstance(token, str) or len(token) != 32
            or any(ch not in '0123456789abcdef' for ch in token)
            or state not in CLEANUP_ATTEMPT_STATES):
        raise ValueError('Invalid cleanup attempt receipt')
    receipt = {'attempt': token, 'state': state,
               'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    with connection:
        connection.execute('CREATE TABLE IF NOT EXISTS archive_cleanup_attempt('
                           'id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        connection.execute('INSERT INTO archive_cleanup_attempt VALUES(1,?) '
                           'ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                           (json.dumps(receipt),))


def last_cleanup_attempt(connection):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='archive_cleanup_attempt'").fetchone():
        return {}
    row = connection.execute('SELECT body FROM archive_cleanup_attempt WHERE id=1').fetchone()
    try:
        value = json.loads(row[0]) if row else {}
        if (not isinstance(value, dict) or value.get('state') not in CLEANUP_ATTEMPT_STATES
                or not isinstance(value.get('attempt'), str)):
            return {}
        return value
    except (ValueError, TypeError):
        return {}
