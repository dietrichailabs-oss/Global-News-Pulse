"""Independent offline expanded-source scheduler/load checks for PR17."""
from __future__ import annotations
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from global_pulse.sources import Scheduler, load_catalog, iso

class MemoryStore:
    def __init__(self):
        self.states={}
    def get_source_state(self,sid):
        return dict(self.states.get(sid,{}))
    def set_source_state(self,sid,state):
        self.states[sid]=dict(state)

def test_exact_127_enabled_catalog_fits_bounded_scheduler():
    catalog=load_catalog()
    enabled=[s for s in catalog if s.get("enabled")]
    assert len(catalog)==170
    assert len(enabled)==127
    scheduler=Scheduler(MemoryStore(),lambda _:None,max_workers=4)
    scheduler.set_sources(catalog)
    assert scheduler.max_workers==4
    assert len([s for s in scheduler.sources if s.get("enabled")])==127
    assert not scheduler._workers

def test_scheduler_never_exceeds_four_live_collectors_under_pressure():
    catalog=load_catalog()
    store=MemoryStore()
    release=threading.Event()
    lock=threading.Lock()
    active=0
    peak=0
    started=[]

    class BlockingCollector:
        def __init__(self,source):
            self.source=source
        def collect(self,state):
            nonlocal active,peak
            with lock:
                active+=1
                peak=max(peak,active)
                started.append(self.source["id"])
            release.wait(3)
            with lock:
                active-=1
            return {"reports":[],"observations":[],"state":{
                "status":"available",
                "next_poll":iso(datetime.now(timezone.utc)+timedelta(days=1)),
            }}

    scheduler=Scheduler(store,lambda _:None,collector_factory=BlockingCollector,max_workers=4)
    scheduler.set_sources(catalog)
    try:
        # Force repeated due ticks while workers are deliberately blocked.
        # _tick itself must still enforce max_workers and starts only one source
        # per tick instead of bursting the full catalog.
        for _ in range(20):
            scheduler._global_next=0.0
            scheduler._tick()
        time.sleep(0.2)
        assert 1 <= len(started) <= 4
        assert peak <= 4
        assert len([t for t in scheduler._workers.values() if t.is_alive()]) <= 4
    finally:
        release.set()
        scheduler.stop(timeout=3)

def test_persisted_statcan_host_denial_survives_scheduler_restart():
    catalog=load_catalog()
    store=MemoryStore()
    target=next(s for s in catalog if s["id"]=="statcan_prices")
    host=urlsplit(target["url"]).hostname
    now=datetime.now(timezone.utc)
    due=now+timedelta(hours=24)
    store.states[target["id"]]={
        "status":"denied",
        "last_failure":iso(now),
        "retry_after_seconds":86400,
        "next_poll":iso(due),
    }

    for _ in range(2):
        scheduler=Scheduler(store,lambda _:None,max_workers=4)
        scheduler.set_sources(catalog)
        try:
            scheduler._global_next=0.0
            scheduler._tick()
            assert host in scheduler._host_next
            assert scheduler._host_next[host] > time.monotonic()+23*3600
        finally:
            scheduler.stop(timeout=2)

def test_quarantined_sources_do_not_enter_enabled_scheduler_pool():
    catalog=load_catalog()
    c={s["id"]:s for s in catalog}
    for identity in (
        "india_pib","gdelt_world_press",
        "nz_economic_growth","nz_energy","nz_foreign_affairs","nz_health",
        "nz_infrastructure","nz_national_security","nz_trade",
    ):
        assert c[identity]["enabled"] is False
        assert c[identity]["status"]=="disabled"
