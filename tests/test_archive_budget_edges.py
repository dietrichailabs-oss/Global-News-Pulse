"""Engineering byte-pressure and writer serialization supplements, offline."""
from datetime import datetime, timezone
import sqlite3
import pytest
from global_pulse import archive_storage as storage
from global_pulse.core import Store
from global_pulse.gdelt_batches import GdeltBatchCache
from test_archive_storage import small_budget
from test_gdelt_batch_cache import event_row, payload, batch_from_archive


def test_repeated_writes_never_commit_past_managed_budget(tmp_path, monkeypatch):
    small_budget(monkeypatch)
    path = tmp_path/'global-pulse.sqlite3'
    with Store(path) as store:
        store.set_setting('archive_max_gb', 5)
        with store._conn:
            store._conn.execute('CREATE TABLE pressure(id INTEGER PRIMARY KEY, body BLOB)')
        committed = 0
        for identifier in range(200):
            try:
                with storage.write_transaction(store._conn, path):
                    store._conn.execute('INSERT INTO pressure VALUES(?,?)', (identifier, b'x'*100_000))
            except storage.StorageBlocked:
                break
            committed += 1
            assert sum(storage.footprint(path).values()) <= 5*1024*1024
        else:
            pytest.fail('Finite test did not encounter its real SQLite write ceiling')
        assert 0 < committed < 200
        assert store._conn.execute('SELECT COUNT(*) FROM pressure').fetchone()[0] == committed
        assert sum(storage.footprint(path).values()) <= 5*1024*1024
    with Store(path) as store:
        assert store._conn.execute('SELECT COUNT(*) FROM pressure').fetchone()[0] == committed


def test_cleanup_responds_to_byte_headroom_not_only_row_count(tmp_path, monkeypatch):
    small_budget(monkeypatch)
    path = tmp_path/'global-pulse.sqlite3'
    with Store(path) as store, GdeltBatchCache(path) as cache:
        store.set_setting('archive_max_gb', 5)
        raw = payload([event_row(str(1000+i)) for i in range(1500)])
        batch = batch_from_archive(raw)
        cache.import_export(batch, raw)
        storage.checkpoint(cache.connection)
        before = storage.snapshot(cache.connection, path)
        assert before['can_collect']
        assert cache.status()['cached_rows'] < cache.max_rows-100000
        # Demand slightly more byte headroom than currently available. The row
        # ceiling is deliberately nowhere near pressure; actual SQLite pages
        # must become reusable/reclaimed to meet this requested margin.
        monkeypatch.setattr(storage, 'IMPORT_HEADROOM', before['growth_room'] + 64*1024)
        state = storage.cleanup(cache, path, 365, now=datetime(2026,11,11,tzinfo=timezone.utc))
        assert 0 < state['removed_rows'] <= 1500
        assert state['growth_room'] >= storage.IMPORT_HEADROOM
        assert cache.is_complete(batch)
        assert state['used_bytes'] <= 5*1024*1024


def test_second_writer_cannot_enter_budget_transaction_during_first(tmp_path):
    path = tmp_path/'global-pulse.sqlite3'
    with Store(path) as store, sqlite3.connect(path, timeout=.01) as other:
        with storage.write_transaction(store._conn, path):
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                with storage.write_transaction(other, path):
                    pytest.fail('Competing writer was admitted before the first committed')
        assert not other.in_transaction
        with storage.write_transaction(other, path):
            other.execute('SELECT 1')


def test_lower_than_existing_footprint_preserves_data_and_refuses_ingestion(tmp_path, monkeypatch):
    small_budget(monkeypatch)
    path = tmp_path/'global-pulse.sqlite3'
    with Store(path) as store:
        with store._conn:
            store._conn.execute('CREATE TABLE retained_payload(id INTEGER PRIMARY KEY,body BLOB)')
        with storage.write_transaction(store._conn, path):
            store._conn.execute('INSERT INTO retained_payload VALUES(1,?)',(b'k'*(6*1024*1024),))
        storage.checkpoint(store._conn)
        store.set_setting('archive_max_gb',5)
        before = store._conn.execute('SELECT length(body) FROM retained_payload').fetchone()[0]
        state = storage.snapshot(store._conn,path)
        assert not state['can_collect'] and state['used_bytes']>state['limit_bytes']
        with pytest.raises(storage.StorageBlocked):
            with storage.write_transaction(store._conn,path):
                store._conn.execute('DELETE FROM retained_payload')
        assert store._conn.execute('SELECT length(body) FROM retained_payload').fetchone()[0]==before
