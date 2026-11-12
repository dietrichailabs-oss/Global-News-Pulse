"""Engineering byte-budget tests: real temporary SQLite, no provider network."""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace
import pytest
from global_pulse import archive_storage as storage
from global_pulse.core import Store
from global_pulse.gdelt_batches import GdeltBatchCache
from global_pulse.gdelt_schedule import Schedule
from global_pulse import gdelt_worker
from test_core import report, STAMP
from test_gdelt_batch_cache import event_row, payload, batch_from_archive


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Storage tests must not use a provider or socket')
    monkeypatch.setattr(socket, 'getaddrinfo', denied)
    monkeypatch.setattr(socket.socket, 'connect', denied)


@pytest.mark.parametrize('value', storage.CHOICES_GB)
def test_exact_choices_persist_without_preallocating(tmp_path, value):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path) as store:
        store.set_setting('archive_max_gb',value)
        state=storage.snapshot(store._conn,path)
        assert state['selected_gb']==value and state['limit_bytes']==value*1_000_000_000
        assert state['used_bytes']<2_000_000
    with Store(path) as store:
        assert storage.read_limit(store._conn)==value
        assert store.get_setting('archive_max_gb')==value


@pytest.mark.parametrize('bad',[None,True,False,'30',30.0,0,-1,6,200,[],{}])
def test_malformed_saved_limit_defaults_without_rewriting(tmp_path,bad):
    with Store(tmp_path/'archive.sqlite3') as store:
        store.set_setting('archive_max_gb',bad)
        assert storage.read_limit(store._conn)==30
        assert store.get_setting('archive_max_gb')==bad


def test_usage_includes_actual_sidecars_not_models_or_exports(tmp_path):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path) as store:
        store.set_setting('archive_max_gb',30)
        (tmp_path/'export.csv').write_bytes(b'private export')
        (tmp_path/'models').mkdir();(tmp_path/'models'/'model.bin').write_bytes(b'not archive')
        state=storage.snapshot(store._conn,path)
        expected={suffix or 'database':Path(str(path)+suffix).stat().st_size if Path(str(path)+suffix).exists() else 0
                  for suffix in ('','-wal','-shm','-journal')}
        assert state['files']==expected and state['used_bytes']==sum(expected.values())
        assert expected['-wal']>0 and expected['-shm']>0


def small_budget(monkeypatch):
    # Test-only unit scaling gives real page-ceiling/rollback evidence without
    # allocating gigabytes. Product constants and user-facing units stay intact.
    monkeypatch.setattr(storage,'GB',1024*1024)
    monkeypatch.setattr(storage,'CONTROL_RESERVE',16*1024)
    monkeypatch.setattr(storage,'FREE_FLOOR',0)
    monkeypatch.setattr(storage,'IMPORT_HEADROOM',64*1024)


def test_page_ceiling_rolls_back_entire_incoming_transaction(tmp_path,monkeypatch):
    small_budget(monkeypatch)
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path) as store:
        store.set_setting('archive_max_gb',5)
        store._conn.execute('CREATE TABLE payloads(id INTEGER PRIMARY KEY,body BLOB)');store._conn.commit()
        with storage.write_transaction(store._conn,path):
            store._conn.execute('INSERT INTO payloads VALUES(1,?)',(b'original',))
        with pytest.raises(storage.StorageBlocked,match='size limit'):
            with storage.write_transaction(store._conn,path):
                store._conn.execute('INSERT INTO payloads VALUES(2,?)',(b'x'*100_000,))
                store._conn.execute('INSERT INTO payloads VALUES(3,?)',(b'x'*(4*1024*1024),))
        assert store._conn.execute('SELECT * FROM payloads').fetchall()[0][0]==1
        assert store._conn.execute('SELECT COUNT(*) FROM payloads').fetchone()[0]==1
        assert not store._conn.in_transaction
        assert storage.snapshot(store._conn,path)['used_bytes'] <= 5*1024*1024
    with Store(path) as store:
        assert store._conn.execute('SELECT body FROM payloads').fetchone()[0]==b'original'


def test_normal_news_and_economic_ingestion_use_budget(tmp_path,monkeypatch):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path) as store:
        monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:SimpleNamespace(free=0))
        with pytest.raises(storage.StorageBlocked,match='free space'):
            store.ingest([report()],now=STAMP)
        assert store.stats()['reports']==0 and store.stats()['events']==0
        assert store.get_setting('archive_mode') is None
        with pytest.raises(storage.StorageBlocked):
            store.put_observations([{'id':'o','value':1}])
        assert store.stats()['observations']==0


def test_expired_cleanup_preserves_pins_saved_situations_and_checkpoint(tmp_path):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path) as store:
        event=store.ingest([report()],now=STAMP)[0]
        store.save_situation(event['id'],'Keep this evidence')
        before={table:[tuple(r) for r in store._conn.execute('SELECT * FROM '+table)]
                for table in ('events','reports','report_revisions','event_revisions','situations','settings')}
        export=tmp_path/'export.json';export.write_text('personal export')
        with GdeltBatchCache(path) as cache:
            archive=payload([event_row('1001'),event_row('1002')]);batch=batch_from_archive(archive)
            cache.import_export(batch,archive)
            with cache.connection:
                cache.connection.execute('INSERT INTO gdelt_retained_rows VALUES(?)',('1001',))
            state=storage.cleanup(cache,path,1,now=datetime(2026,11,20,tzinfo=timezone.utc))
            assert state['removed_rows']==1
            assert [r[0] for r in cache.connection.execute('SELECT global_event_id FROM gdelt_event_rows')]==['1001']
            assert cache.is_complete(batch)
            assert cache.import_export(batch,archive)['status']=='already_imported'
        assert before=={table:[tuple(r) for r in store._conn.execute('SELECT * FROM '+table)] for table in before}
        assert export.read_text()=='personal export'
    with Store(path) as store:
        assert store.saved_situation_ids()=={event['id']}
        assert store.get_event(event['id'])['reports'][0]['title']==report()['title']


def test_size_cleanup_discards_oldest_unpinned_rows_first(tmp_path,monkeypatch):
    import global_pulse.gdelt_batches as batches
    monkeypatch.setattr(batches,'MAX_BATCH_ROWS',2)
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path),GdeltBatchCache(path,max_rows=5) as cache:
        # Build before tightening the test parser row bound.
        monkeypatch.setattr(batches,'MAX_BATCH_ROWS',100000)
        archive=payload([event_row(str(i)) for i in range(1001,1006)]);batch=batch_from_archive(archive)
        cache.import_export(batch,archive)
        with cache.connection:cache.connection.execute('INSERT INTO gdelt_retained_rows VALUES(?)',('1001',))
        monkeypatch.setattr(batches,'MAX_BATCH_ROWS',2)
        storage.cleanup(cache,path,365,now=datetime(2026,11,11,tzinfo=timezone.utc))
        rows=[r[0] for r in cache.connection.execute('SELECT global_event_id FROM gdelt_event_rows ORDER BY global_event_id')]
        assert rows==['1001','1004','1005']
        assert cache.is_complete(batch)


def test_protected_only_pressure_pauses_instead_of_deleting(tmp_path,monkeypatch):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path),GdeltBatchCache(path,max_rows=2) as cache:
        archive=payload([event_row()]);cache.import_export(batch_from_archive(archive),archive)
        with cache.connection:cache.connection.execute('INSERT INTO gdelt_retained_rows VALUES(?)',('1001',))
        with pytest.raises(storage.StorageBlocked,match='preserved'):
            storage.cleanup(cache,path,365,now=datetime(2026,11,11,tzinfo=timezone.utc))
        assert cache.status()['cached_rows']==1


def test_worker_preflight_low_disk_makes_zero_requests_and_suspends(tmp_path,monkeypatch):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path):pass
    schedule=Schedule(path);token=schedule.claim(jitter=0)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda _:SimpleNamespace(free=0))
    calls=[]
    monkeypatch.setattr(gdelt_worker,'poll_latest_export',lambda *a,**k:calls.append(a))
    assert gdelt_worker.main(['--database',str(path),'--token',token,'--consent-network'])==3
    assert not calls and schedule.status()['suspended']==1
    assert schedule.status()['state']=='storage_paused'
    with sqlite3.connect(path) as connection:
        assert storage.last_cleanup(connection)['state']=='low_disk'


def test_explicit_cleanup_only_never_polls_or_alters_request_schedule(tmp_path,monkeypatch):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path):pass
    schedule=Schedule(path);token=schedule.claim(jitter=0)
    schedule.finish(token,{'status':'error','http_status':403});before=schedule.status()
    def denied(*args,**kwargs):raise AssertionError('Offline cleanup must never poll')
    monkeypatch.setattr(gdelt_worker,'poll_latest_export',denied)
    assert gdelt_worker.main(['--database',str(path),'--cleanup-only'])==0
    assert schedule.status()==before
    with sqlite3.connect(path) as connection:
        assert storage.last_cleanup(connection)['removed_rows']==0


def test_unsafe_sidecar_refused_without_touching_it(tmp_path):
    path=tmp_path/'x.sqlite3';path.write_bytes(b'archive')
    sidecar=Path(str(path)+'-journal');sidecar.mkdir();marker=sidecar/'owner.txt';marker.write_text('keep')
    with pytest.raises(storage.StorageBlocked,match='redirects'):
        storage.footprint(path)
    assert marker.read_text()=='keep'


def test_legacy_database_is_not_rebuilt_or_replaced(tmp_path):
    path=tmp_path/'global-pulse.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE legacy(value TEXT)');connection.execute("INSERT INTO legacy VALUES('keep')")
    with Store(path),GdeltBatchCache(path) as cache:
        assert cache.connection.execute('PRAGMA auto_vacuum').fetchone()[0]==0
        storage.cleanup(cache,path)
        assert cache.connection.execute('PRAGMA auto_vacuum').fetchone()[0]==0
        assert cache.connection.execute('SELECT value FROM legacy').fetchone()[0]=='keep'


def test_cleanup_deadline_preserves_remaining_rows(tmp_path,monkeypatch):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path),GdeltBatchCache(path,max_rows=1) as cache:
        archive=payload([event_row()]);cache.import_export(batch_from_archive(archive),archive)
        times=iter([0,31]);monkeypatch.setattr(storage.time,'monotonic',lambda:next(times))
        with pytest.raises(storage.StorageBlocked,match='bounded work limit'):
            storage.cleanup(cache,path,365,now=datetime(2026,11,11,tzinfo=timezone.utc))
        assert cache.status()['cached_rows']==1
