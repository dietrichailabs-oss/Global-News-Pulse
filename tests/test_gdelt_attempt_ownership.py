"""Engineering regressions: real SQLite ownership interleavings and bounded HTTP.

No live downloads. Independent suites are replayed separately without changes.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import socket
import sqlite3
import zipfile
import httpx
import pytest
from global_pulse.gdelt_batches import GdeltBatchCache, GdeltBatchError, MANIFEST_URL, SCHEMA, parse_manifest
from global_pulse.gdelt_poll import poll_latest_export, _bounded_get

START = datetime(2026, 11, 11, 8, tzinfo=timezone.utc)

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError('No real network in ownership regression')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)


def data(identifier='1'):
    stamp = '20261111080000'
    filename = stamp + '.export.CSV.zip'
    fields = [''] * 61
    fields[0], fields[1], fields[26], fields[29] = identifier, '20261110', '043', '3'
    fields[59], fields[60] = stamp, 'https://publisher.example/test/' + identifier
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename[:-4], '\t'.join(fields) + '\n')
    payload = out.getvalue()
    manifest = f'{len(payload)} {hashlib.md5(payload).hexdigest()} https://data.gdeltproject.org/gdeltv2/{filename}\n'
    return parse_manifest(manifest)['export'], payload, manifest.encode('ascii')


def snapshot(cache):
    return cache.connection.execute('SELECT * FROM gdelt_batches').fetchall()


@pytest.mark.parametrize('action', ['late_error', 'good_import', 'bad_import'])
def test_superseded_attempt_cannot_modify_successor_or_rows(tmp_path, action):
    batch, payload, _ = data()
    with GdeltBatchCache(tmp_path/'db') as old, GdeltBatchCache(tmp_path/'db') as new, GdeltBatchCache(tmp_path/'db') as third:
        assert old.reserve(batch, now=START) is True
        old_token = old.reservation_token(batch)
        assert new.reserve(batch, now=START+timedelta(minutes=3)) is True
        new_token = new.reservation_token(batch)
        assert old_token != new_token
        before = snapshot(new)
        if action == 'late_error':
            old.record_fetch_error(batch, 'GDELT endpoint returned HTTP 503', attempt=old_token)
        else:
            with pytest.raises(GdeltBatchError, match='superseded'):
                old.import_export(batch, payload if action == 'good_import' else b'bad', attempt=old_token)
        assert snapshot(new) == before
        assert third.reserve(batch, now=START+timedelta(minutes=3, seconds=1)) is False
        assert new.status()['cached_rows'] == 0
        assert new.import_export(batch, payload, attempt=new_token)['added'] == 1
        completed = snapshot(new)
        old.record_fetch_error(batch, 'GDELT late error', attempt=old_token)
        assert snapshot(new) == completed


def test_unowned_direct_import_and_error_cannot_adopt_foreign_token(tmp_path):
    batch, payload, _ = data()
    with GdeltBatchCache(tmp_path/'db') as owner, GdeltBatchCache(tmp_path/'db') as stranger:
        assert owner.reserve(batch)
        assert stranger.reservation_token(batch) is None
        before = snapshot(owner)
        stranger.record_fetch_error(batch, 'GDELT unowned error')
        with pytest.raises(GdeltBatchError, match='another attempt'):
            stranger.import_export(batch, payload)
        assert snapshot(owner) == before and owner.status()['cached_rows'] == 0


def test_same_connection_new_generation_rejects_old_captured_handle(tmp_path):
    batch, payload, _ = data()
    with GdeltBatchCache(tmp_path/'db') as cache:
        assert cache.reserve(batch, now=START)
        old_token = cache.reservation_token(batch)
        assert cache.reserve(batch, now=START+timedelta(minutes=3))
        new_token = cache.reservation_token(batch)
        before = snapshot(cache)
        cache.record_fetch_error(batch, 'GDELT stale callback', attempt=old_token)
        with pytest.raises(GdeltBatchError):
            cache.import_export(batch, payload, attempt=old_token)
        assert snapshot(cache) == before
        assert cache.reservation_token(batch) == new_token
        assert cache.import_export(batch, payload, attempt=new_token)['status'] == 'complete'


@pytest.mark.parametrize('response', ['success', 'http_error', 'giant_header'])
@pytest.mark.parametrize('same_connection', [False, True])
def test_real_poller_keeps_per_call_handle_during_takeover(tmp_path, response, same_connection):
    batch, payload, manifest = data()
    with GdeltBatchCache(tmp_path/'db') as cache, GdeltBatchCache(tmp_path/'db') as other:
        successor = cache if same_connection else other
        before = []
        def handler(request):
            if str(request.url) == MANIFEST_URL:
                return httpx.Response(200, content=manifest)
            assert successor.reserve(batch, now=datetime.now(timezone.utc)+timedelta(minutes=4))
            before[:] = snapshot(successor)
            if response == 'http_error':
                return httpx.Response(503)
            headers = {'Content-Length':'9'*5000} if response == 'giant_header' else {}
            return httpx.Response(200, content=payload, headers=headers)
        with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
            result = poll_latest_export(cache, client=client)
        assert result['status'] == 'error' and len(result['error']) <= 160
        assert snapshot(successor) == before
        assert successor.status()['cached_rows'] == 0
        assert successor.import_export(batch, payload)['status'] == 'complete'


def test_takeover_during_zip_validation_is_rechecked_inside_transaction(tmp_path, monkeypatch):
    import global_pulse.gdelt_batches as module
    batch, payload, _ = data()
    with GdeltBatchCache(tmp_path/'db') as old, GdeltBatchCache(tmp_path/'db') as new:
        assert old.reserve(batch, now=START)
        real = module.zipfile.ZipFile
        class InterleavedZip(real):
            def infolist(self):
                assert new.reserve(batch, now=START+timedelta(minutes=3))
                return super().infolist()
        monkeypatch.setattr(module.zipfile, 'ZipFile', InterleavedZip)
        with pytest.raises(GdeltBatchError, match='superseded'):
            old.import_export(batch, payload)
        assert new.status()['latest_batch']['status'] == 'downloading'
        assert new.status()['cached_rows'] == 0


def test_same_owner_failure_releases_and_retry_gets_fresh_token(tmp_path):
    batch, payload, _ = data()
    with GdeltBatchCache(tmp_path/'db') as cache:
        assert cache.reserve(batch)
        previous = cache.reservation_token(batch)
        with pytest.raises(GdeltBatchError):
            cache.import_export(batch, b'bad', attempt=previous)
        assert cache.status()['latest_batch']['status'] == 'error'
        assert cache.connection.execute('SELECT lease_until,lease_token FROM gdelt_batches').fetchone() == (None,None)
        assert cache.reserve(batch)
        assert cache.reservation_token(batch) != previous
        assert cache.import_export(batch, payload)['status'] == 'complete'


def test_changed_payload_successor_keeps_its_own_fingerprint(tmp_path):
    first, first_payload, _ = data('1')
    newer, newer_payload, _ = data('22222')
    with GdeltBatchCache(tmp_path/'db') as old, GdeltBatchCache(tmp_path/'db') as new:
        assert old.reserve(first, now=START)
        assert new.reserve(newer, now=START+timedelta(minutes=3))
        before = snapshot(new)
        old.record_fetch_error(first, 'GDELT delayed error')
        assert snapshot(new) == before
        with pytest.raises(GdeltBatchError):
            old.import_export(first, first_payload)
        assert new.import_export(newer, newer_payload)['added'] == 1
        assert new.connection.execute('SELECT advertised_md5,advertised_bytes FROM gdelt_batches').fetchone() == (newer.advertised_md5,newer.advertised_bytes)


def test_legacy_schema_migration_preserves_rows_and_active_exclusion(tmp_path):
    batch, payload, _ = data()
    db = tmp_path/'db'
    legacy = SCHEMA.replace(' lease_token TEXT,','')
    conn = sqlite3.connect(db)
    conn.executescript(legacy)
    conn.execute('INSERT INTO gdelt_batches(filename,kind,batch_timestamp,source_url,advertised_bytes,advertised_md5,status,lease_until) VALUES(?,?,?,?,?,?,?,?)',
                 (batch.filename,batch.kind,batch.timestamp,batch.url,batch.advertised_bytes,batch.advertised_md5,'downloading',(START+timedelta(minutes=3)).isoformat()))
    conn.commit();conn.close()
    with GdeltBatchCache(db) as cache:
        assert 'lease_token' in {r[1] for r in cache.connection.execute('PRAGMA table_info(gdelt_batches)')}
        assert cache.reserve(batch, now=START+timedelta(seconds=179)) is False
        assert cache.reserve(batch, now=START+timedelta(minutes=3)) is True
        assert cache.import_export(batch,payload)['status'] == 'complete'
    with GdeltBatchCache(db) as cache:
        assert cache.is_complete(batch) and cache.status()['cached_rows'] == 1


@pytest.mark.parametrize('header', ['9'*5000, '0'*5000, '', '+12', '-12', '12, 12', '1e4', 'abc', '99999999999999999999'])
def test_header_validation_is_bounded_and_never_leaks_input(header):
    def handler(request):
        return httpx.Response(200, content=b'abc', headers={'Content-Length':header})
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        with pytest.raises(GdeltBatchError) as failure:
            _bounded_get(client,MANIFEST_URL,8192)
        assert len(str(failure.value)) <= 160
        assert not header or len(header) < 3 or header not in str(failure.value)


@pytest.mark.parametrize('header', [None,'3','0003'])
def test_missing_and_small_valid_lengths_keep_bounded_streaming(header):
    class Stream(httpx.SyncByteStream):
        def __iter__(self):yield b'abc'
    def handler(request):
        return httpx.Response(200,stream=Stream(),headers={} if header is None else {'Content-Length':header})
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        assert _bounded_get(client,MANIFEST_URL,8192) == b'abc'


def test_lying_small_header_still_cannot_bypass_streaming_cap():
    class Stream(httpx.SyncByteStream):
        def __iter__(self):yield b'x'*8193
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,stream=Stream(),headers={'Content-Length':'1'})),trust_env=False) as client:
        with pytest.raises(GdeltBatchError,match='size limit'):
            _bounded_get(client,MANIFEST_URL,8192)
