"""Source-scoped CAP/NWS identity and warning lifecycle (no network effects).

Cancellation withdraws a warning, not the historical fact that it was issued.
References are inert identifiers: no URL is fetched to resolve them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid5

NS = UUID('5dbbb956-1647-4162-aaf4-d19c5b67d2bb')


def provider_id(source_id: str, identifier: str) -> str:
    return source_id + ':' + sha256(str(identifier).encode()).hexdigest()[:24]


def scope_identifier(identifier: str, sender: str = '') -> str:
    return sender + '\0' + identifier if sender else identifier


def normalize_lifecycle(raw: dict, result: dict, stamp: str) -> None:
    message = str(raw.get('cap_message_type', '')).title()
    if message not in {'Alert', 'Update', 'Cancel'}:
        return
    result['cap_message_type'] = message
    result['cap_status'] = str(raw.get('cap_status', 'Actual'))[:40]
    result['provider_sender'] = str(raw.get('provider_sender', ''))[:300]
    result['provider_identifier'] = str(raw.get('provider_identifier', ''))[:500]
    result['identity_aliases'] = list(dict.fromkeys([result['id']] + [
        str(x)[:500] for x in raw.get('identity_aliases', [])[:40]
        if isinstance(x, str) and x.startswith(result['source_id'] + ':')]))
    result['lifecycle_references'] = list(dict.fromkeys([
        str(x)[:500] for x in raw.get('lifecycle_references', [])[:40]
        if isinstance(x, str) and x.startswith(result['source_id'] + ':')]))
    result['reference_errors'] = bool(raw.get('reference_errors'))
    expiry = raw.get('expires_at')
    if expiry:
        try:
            d = datetime.fromisoformat(str(expiry).replace('Z', '+00:00'))
            if d.tzinfo is None:
                raise ValueError('Expiry timezone missing')
            result['expires_at'] = d.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        except (ValueError, TypeError):
            result['expires_at'] = ''
            result['expiry_invalid'] = True
    else:
        result['expires_at'] = ''
    result['expired'] = is_expired(result, stamp)
    if message == 'Cancel':
        result['kind'] = 'cancellation'
    elif message == 'Update':
        result['kind'] = 'warning_update'


def is_expired(report: dict, stamp: str | None) -> bool:
    if not stamp or not report.get('expires_at'):
        return bool(report.get('expired', False))
    try:
        return datetime.fromisoformat(report['expires_at'].replace('Z', '+00:00')) <= datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return False


def apply_lifecycle(reports: list[dict], stamp: str | None) -> None:
    aliases = {}
    for report in reports:
        for alias in report.get('identity_aliases', [report['id']]):
            aliases.setdefault((report['source_id'], alias), []).append(report)
        report.pop('lifecycle_resolved', None)
        if report.get('cap_message_type'):
            report['expired'] = is_expired(report, stamp)
            if report.get('future_dated'):
                continue
            if report.get('expiry_invalid'):
                report['evidence_status'] = 'pending'
            elif report['expired']:
                report['evidence_status'] = 'expired'
    for report in sorted(reports, key=lambda r: (r['published_at'], r['record_key'])):
        msg = report.get('cap_message_type')
        if not msg or report.get('future_dated'):
            continue
        refs = report.get('lifecycle_references', [])
        if msg not in {'Update', 'Cancel'}:
            continue
        found = []
        missing = bool(report.get('reference_errors')) or not refs
        for reference in refs:
            candidates = [r for r in aliases.get((report['source_id'], reference), [])
                          if r['record_key'] != report['record_key'] and not r.get('future_dated')
                          and r['published_at'] <= report['published_at']
                          and (not r.get('provider_sender') or not report.get('provider_sender')
                               or r['provider_sender'] == report['provider_sender'])]
            unique = {r['record_key']: r for r in candidates}
            if len(unique) == 1:
                found.append(next(iter(unique.values())))
            else:
                missing = True
        report['lifecycle_resolved'] = bool(found) and not missing
        if missing:
            report['unresolved_reference'] = ', '.join(refs) or 'Missing warning reference'
        # Known targets can be withdrawn even when another target is unavailable;
        # unresolved notices are never advertised as fully linked/verified alerts.
        for target in found:
            target['evidence_status'] = 'cancelled' if msg == 'Cancel' else 'superseded'
            target['superseded_by'] = report['record_key']
        if msg == 'Cancel':
            report['evidence_status'] = 'notice'
        elif missing:
            report['evidence_status'] = 'pending'


SCHEMA = '''
CREATE TABLE IF NOT EXISTS warning_identities (
 source_id TEXT NOT NULL, identity TEXT NOT NULL, synthetic INTEGER NOT NULL,
 event_id TEXT NOT NULL, PRIMARY KEY(source_id,identity,synthetic));
CREATE INDEX IF NOT EXISTS warning_identities_event ON warning_identities(event_id);
CREATE TABLE IF NOT EXISTS event_aliases (
 alias_id TEXT PRIMARY KEY, canonical_id TEXT NOT NULL, merged_at TEXT NOT NULL);
'''


def canonical_event(conn, event_id: str, at: str | None = None) -> str:
    seen = set()
    while event_id not in seen:
        seen.add(event_id)
        row = conn.execute('SELECT canonical_id,merged_at FROM event_aliases WHERE alias_id=?', (event_id,)).fetchone()
        if not row or at is not None and at < row['merged_at']:
            break
        event_id = row['canonical_id']
    return event_id


def select_warning_event(store, report: dict, stamp: str) -> str | None:
    if not report.get('cap_message_type'):
        return None
    conn = store._conn
    identifiers = list(dict.fromkeys(report.get('identity_aliases', [report['id']]) + report.get('lifecycle_references', [])))
    found = set()
    for identity in identifiers:
        for row in conn.execute('SELECT event_id FROM warning_identities WHERE source_id=? AND identity=? AND synthetic=?',
                                (report['source_id'], identity, int(report['synthetic']))):
            found.add(canonical_event(conn, row[0]))
        # Compatibility with already-stored E1 records, which lack the index.
        for row in conn.execute('SELECT r.event_id FROM reports r JOIN events e ON r.event_id=e.id WHERE r.source_id=? AND r.original_id=? AND e.synthetic=?',
                                (report['source_id'], identity, int(report['synthetic']))):
            found.add(canonical_event(conn, row[0]))
    if not found:
        seed = min(report.get('lifecycle_references') or [report['id']])
        return str(uuid5(NS, ('synthetic:' if report['synthetic'] else 'live:') + 'warning:' + seed))
    rows = [conn.execute('SELECT id,created_at FROM events WHERE id=?', (eid,)).fetchone() for eid in found]
    existing = [r for r in rows if r]
    if not existing:
        return min(found)
    destination = min(existing, key=lambda r: (r['created_at'], r['id']))['id']
    for old in sorted(found - {destination}):
        _merge(store, old, destination, stamp)
    return destination


def register_warning(conn, report: dict, event_id: str) -> None:
    if not report.get('cap_message_type'):
        return
    for identity in set(report.get('identity_aliases', [report['id']]) + report.get('lifecycle_references', [])):
        conn.execute('INSERT INTO warning_identities VALUES(?,?,?,?) ON CONFLICT(source_id,identity,synthetic) DO UPDATE SET event_id=excluded.event_id',
                     (report['source_id'], identity, int(report['synthetic']), event_id))


def _merge(store, old: str, target: str, stamp: str) -> None:
    """Join a late-arriving explicit source chain without losing prior identities.

    Old revision snapshots remain immutable. Old links redirect only from merge
    time onward. Neither headline similarity nor cross-source claims call here.
    """
    c = store._conn
    old_row = c.execute('SELECT body FROM events WHERE id=?', (old,)).fetchone()
    target_row = c.execute('SELECT body FROM events WHERE id=?', (target,)).fetchone()
    if old_row and target_row:
        old_body, target_body = json.loads(old_row[0]), json.loads(target_row[0])
        history = target_body.setdefault('significance_history', {})
        ranks = {'unassessed': 0, 'informational': 1, 'moderate': 2, 'high': 3, 'critical': 4}
        for source, level in old_body.get('significance_history', {}).items():
            if isinstance(level, str) and ranks.get(level, 0) > ranks.get(history.get(source), -1):
                history[source] = level
        target_body['merged_source_events'] = sorted(set(target_body.get('merged_source_events', []) + [old] + old_body.get('merged_source_events', [])))
        c.execute('UPDATE events SET body=? WHERE id=?', (json.dumps(target_body), target))
    c.execute('UPDATE reports SET event_id=? WHERE event_id=?', (target, old))
    c.execute('UPDATE report_revisions SET event_id=? WHERE event_id=?', (target, old))
    c.execute('UPDATE warning_identities SET event_id=? WHERE event_id=?', (target, old))
    c.execute('UPDATE event_aliases SET canonical_id=? WHERE canonical_id=?', (target, old))
    c.execute('INSERT OR REPLACE INTO event_aliases VALUES(?,?,?)', (old, target, stamp))
    for row in c.execute('SELECT id,body FROM alerts WHERE event_id=?', (old,)).fetchall():
        body = json.loads(row['body'])
        body['original_event_id'] = body['event_id']
        body['event_id'] = target
        c.execute('UPDATE alerts SET event_id=?,body=? WHERE id=?', (target, json.dumps(body), row['id']))
    saved = c.execute('SELECT * FROM situations WHERE event_id=?', (old,)).fetchone()
    if saved:
        c.execute('INSERT OR IGNORE INTO situations VALUES(?,?,?,?,?)',
                  (target, saved['title'], saved['saved_at'], saved['last_visited_at'], 0))
        c.execute('DELETE FROM situations WHERE event_id=?', (old,))
    if store.fts_available:
        c.execute('DELETE FROM event_search WHERE event_id=?', (old,))
