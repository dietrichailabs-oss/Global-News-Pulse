"""Engineering scheduler tests: real disposable SQLite, controlled time/HTTP."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import socket
import threading
import httpx
import pytest
from global_pulse.gdelt_schedule import Schedule, retry_after, retention_days, INTERVAL, MAX_EPOCH
from global_pulse.gdelt_batches import GdeltBatchCache
from global_pulse.gdelt_poll import poll_latest_export
from global_pulse.gdelt_worker import main as worker_main

NOW=1794409200
spec=importlib.util.spec_from_file_location('gdelt_eng_fixtures',Path(__file__).with_name('test_gdelt_poll.py'))
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('No live provider requests in scheduler regression')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)

@pytest.mark.parametrize('value,expected',[(7,7),(1,1),(365,365),(0,7),(366,7),(True,7),('30',7),(None,7),({},7)])
def test_retention_settings_boundary(value,expected):assert retention_days(value)==expected

@pytest.mark.parametrize('value,seconds',[('900',900),('3600',3600),('0',0),('bad',0),('-1',0),('',0),(None,0),('١٢',0)])
def test_retry_after_bounded_inputs(value,seconds):assert retry_after(value,NOW)==(seconds,False)

def test_retry_after_date_and_giant_number():
    assert retry_after('Wed, 11 Nov 2026 17:00:00 GMT',1794409200)[0]>=0
    delay,suspended=retry_after('9'*5000,NOW)
    assert suspended and delay==MAX_EPOCH-NOW

def test_claim_survives_restart_pause_and_clock_rollback(tmp_path):
    p=tmp_path/'archive.sqlite3';s=Schedule(p)
    token=s.claim(now=NOW,jitter=0)
    assert token and s.status()['next_at']==NOW+INTERVAL
    assert Schedule(p).claim(now=NOW+899,jitter=0) is None
    assert Schedule(p).claim(now=NOW-100,jitter=0) is None
    assert s.finish(token,{},now=NOW+10,cancelled=True)
    assert Schedule(p).claim(now=NOW+899,jitter=0) is None
    assert Schedule(p).claim(now=NOW+900,jitter=0)

def test_expired_schedule_generation_cannot_change_successor(tmp_path):
    s=Schedule(tmp_path/'archive');old=s.claim(now=NOW,jitter=0)
    new=s.claim(now=NOW+900,jitter=0);before=s.status()
    assert new!=old and not s.finish(old,{'status':'error'},now=NOW+901)
    assert s.status()==before
    assert s.finish(new,{'status':'complete','batch_timestamp':'20261111151500','cached_rows':1556},now=NOW+902)
    state=s.status();assert state['cached_rows']==1556 and state['failures']==0
    assert state['last_success']==NOW+902 and state['next_at']>=NOW+1802

def test_six_real_threads_only_one_scheduled_owner(tmp_path):
    path=tmp_path/'archive';Schedule(path).status()
    barrier=threading.Barrier(6);results=[];errors=[]
    def run():
        try:
            barrier.wait(timeout=5);results.append(Schedule(path).claim(now=NOW,jitter=0))
        except Exception as exc:errors.append(exc)
    threads=[threading.Thread(target=run) for _ in range(6)]
    for t in threads:t.start()
    for t in threads:t.join(5)
    assert not errors and not any(t.is_alive() for t in threads)
    assert len([r for r in results if r])==1

def test_backoff_circuit_and_manual_review_do_not_shorten_provider_delay(tmp_path):
    s=Schedule(tmp_path/'archive');now=NOW
    for i in range(5):
        token=s.claim(now=now,jitter=0);assert token
        assert s.finish(token,{'status':'error','http_status':503},now=now)
        row=s.status();assert row['failures']==i+1
        assert row['next_at']>=now+900*2**i
        now=row['next_at']
    assert row['suspended'] and s.claim(now=now+999999,jitter=0) is None
    s.review_retry();assert s.status()['next_at']==row['next_at']
    assert s.claim(now=now-1,jitter=0) is None
    assert s.claim(now=now,jitter=0)

@pytest.mark.parametrize('status',[401,403])
def test_access_refusal_suspends_without_automatic_retry(tmp_path,status):
    s=Schedule(tmp_path/'archive');t=s.claim(now=NOW,jitter=0)
    s.finish(t,{'status':'error','http_status':status},now=NOW)
    assert s.status()['suspended'] and s.claim(now=NOW+86400,jitter=0) is None

def test_upgrade_recovers_only_never_successful_legacy_404_suspension(tmp_path):
    p=tmp_path/'archive';s=Schedule(p)
    with s.db() as db,db:
        db.execute("UPDATE gdelt_schedule SET suspended=1,failures=5,state='suspended',http_status=404,next_at=? WHERE id=1",
                   (NOW+3600,))
    assert s.recover_legacy_transport_failure()
    row=s.status()
    assert not row['suspended'] and row['failures']==0 and row['state']=='waiting'
    assert row['next_at']==NOW+3600
    assert s.claim(now=NOW+3599,jitter=0) is None
    assert s.claim(now=NOW+3600,jitter=0)


@pytest.mark.parametrize("status",[301,404])
def test_upgrade_recovery_does_not_touch_prior_success_or_cached_rows(tmp_path,status):
    p=tmp_path/f'archive-{status}';s=Schedule(p)
    with s.db() as db,db:
        db.execute("UPDATE gdelt_schedule SET suspended=1,failures=5,state='suspended',http_status=?,last_success=?,cached_rows=10 WHERE id=1",
                   (status,NOW))
    before=s.status()
    assert not s.recover_legacy_transport_failure()
    assert s.status()==before


def test_upgrade_recovery_never_reopens_access_denial(tmp_path):
    p=tmp_path/'archive';s=Schedule(p)
    with s.db() as db,db:
        db.execute("UPDATE gdelt_schedule SET suspended=1,failures=1,state='suspended',http_status=403 WHERE id=1")
    before=s.status()
    assert not s.recover_legacy_transport_failure()
    assert s.status()==before


def test_long_retry_after_persists_and_toggle_cannot_override(tmp_path):
    p=tmp_path/'archive';s=Schedule(p);t=s.claim(now=NOW,jitter=0)
    s.finish(t,{'status':'error','http_status':429,'retry_after_seconds':172800},now=NOW)
    s.review_retry()
    assert Schedule(p).claim(now=NOW+172799,jitter=0) is None
    assert Schedule(p).claim(now=NOW+172800,jitter=0)

def test_giant_delay_remains_deferred_even_after_manual_review(tmp_path):
    s=Schedule(tmp_path/'archive');t=s.claim(now=NOW,jitter=0)
    s.finish(t,{'status':'error','retry_after_seconds':MAX_EPOCH-NOW,'retry_after_unbounded':True},now=NOW)
    s.review_retry();assert s.status()['next_at']==MAX_EPOCH
    assert s.claim(now=NOW+86400,jitter=0) is None

def test_busy_is_not_success_and_gap_is_preserved_on_failure(tmp_path):
    s=Schedule(tmp_path/'archive');t=s.claim(now=NOW,jitter=0)
    s.finish(t,{'status':'complete','gap_detected':True},now=NOW)
    t=s.claim(now=NOW+900,jitter=0)
    s.finish(t,{'status':'download_in_progress'},now=NOW+900)
    assert s.status()['last_success']==NOW and s.status()['gap']==1
    assert s.status()['failures']==0

def test_status_does_not_persist_untrusted_text_or_foreign_tables(tmp_path):
    s=Schedule(tmp_path/'archive');t=s.claim(now=NOW,jitter=0)
    with s.db() as db,db:
        db.execute('CREATE TABLE saved_situations(id TEXT)');db.execute("INSERT INTO saved_situations VALUES('keep')")
    s.finish(t,{'status':'<script>','error':'password=secret','batch_timestamp':'https://secret','cached_rows':True},now=NOW)
    assert 'secret' not in str(s.status()) and s.status()['cached_rows']==0
    with s.db() as db:assert db.execute('SELECT * FROM saved_situations').fetchall()[0][0]=='keep'

@pytest.mark.parametrize('where',['manifest','archive'])
def test_actual_poller_returns_retry_metadata_without_repeating_requests(tmp_path,where):
    raw=helpers.archive_for(helpers.STAMP);manifest=helpers.manifest_for(helpers.STAMP,raw);calls=[]
    def handle(request):
        calls.append(str(request.url));is_manifest=str(request.url).endswith('.txt')
        if is_manifest==(where=='manifest'):return httpx.Response(429,headers={'Retry-After':'7200'})
        return httpx.Response(200,content=manifest if is_manifest else raw)
    with GdeltBatchCache(tmp_path/'archive') as cache,httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result=poll_latest_export(cache,client=client)
        assert result['status']=='error' and result['retry_after_seconds']==7200
        assert result['http_status']==429 and len(calls)==(1 if where=='manifest' else 2)

def test_worker_consent_and_token_gate_precede_network(tmp_path,monkeypatch):
    p=tmp_path/'global-pulse.sqlite3';s=Schedule(p);s.status()
    assert worker_main(['--database',str(p),'--token','f'*32])==2
    assert worker_main(['--database',str(p),'--token','f'*32,'--consent-network'])==2

def test_worker_import_and_retention_leave_other_evidence_untouched(tmp_path,monkeypatch):
    p=tmp_path/'global-pulse.sqlite3';s=Schedule(p);token=s.claim()
    with s.db() as db,db:
        db.execute('CREATE TABLE saved_situations(id TEXT)');db.execute("INSERT INTO saved_situations VALUES('keep')")
    import global_pulse.gdelt_worker as worker
    original=worker.poll_latest_export
    raw=helpers.archive_for(helpers.STAMP);manifest=helpers.manifest_for(helpers.STAMP,raw)
    def poll(cache):
        with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=manifest if str(r.url).endswith('.txt') else raw))) as client:
            return original(cache,client=client)
    monkeypatch.setattr(worker,'poll_latest_export',poll)
    assert worker_main(['--database',str(p),'--token',token,'--consent-network'])==0
    state=s.status();assert state['state']=='current' and state['cached_rows']==1 and state['token'] is None
    with s.db() as db:assert db.execute('SELECT id FROM saved_situations').fetchone()[0]=='keep'
