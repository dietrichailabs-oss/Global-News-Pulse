"""One owned GDELT attempt, or explicit offline archive cleanup; no descendants."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sqlite3
from .gdelt_batches import GdeltBatchCache
from .gdelt_poll import poll_latest_export
from .gdelt_schedule import Schedule, retention_days
from .archive_storage import cleanup, save_cleanup_status, StorageBlocked


def main(argv=None):
    parser = argparse.ArgumentParser(description='Global Pulse bounded GDELT worker')
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--token', default='')
    parser.add_argument('--retention-days', type=int, default=7)
    parser.add_argument('--consent-network', action='store_true')
    parser.add_argument('--cleanup-only', action='store_true')
    parser.add_argument('--cleanup-attempt', default='')
    args = parser.parse_args(argv)
    path = args.database
    if (not path.is_absolute() or path.is_symlink() or path.resolve() != path
        or path.name != 'global-pulse.sqlite3' or not path.is_file()):
        return 2
    if not args.cleanup_only and (not args.consent_network or not re.fullmatch(r'[0-9a-f]{32}', args.token)):
        return 2
    if args.cleanup_attempt and (not args.cleanup_only or not re.fullmatch(r'[0-9a-f]{32}', args.cleanup_attempt)):
        return 2
    schedule = Schedule(path)
    try:
        if not args.cleanup_only and schedule.status()['token'] != args.token:
            return 2
        with GdeltBatchCache(path) as cache:
            state = cleanup(cache, path, retention_days(args.retention_days))
            if args.cleanup_only and args.cleanup_attempt:
                state['attempt'] = args.cleanup_attempt
            save_cleanup_status(cache.connection, state)
            if args.cleanup_only:
                return 0
            result = poll_latest_export(cache)
            result['cached_rows'] = cache.status()['cached_rows']
            result['gap_detected'] = cache.has_unresolved_export_gap()
        schedule.finish(args.token, result)
        return 0
    except StorageBlocked as exc:
        try:
            if not args.cleanup_only:
                with sqlite3.connect(str(path), timeout=.25) as connection:
                    save_cleanup_status(connection, {'state': exc.code})
                schedule.finish(args.token, {'status': 'error', 'storage_blocked': True})
        except (sqlite3.Error, OSError, ValueError):
            pass
        return 3
    except Exception:
        try:
            if not args.cleanup_only:
                schedule.finish(args.token, {'status': 'error'})
            if not args.cleanup_only:
                with sqlite3.connect(str(path), timeout=.25) as connection:
                    save_cleanup_status(connection, {'state': 'storage_busy'})
        except (sqlite3.Error, OSError, ValueError):
            pass
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
