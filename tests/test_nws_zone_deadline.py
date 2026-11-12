"""Slow-drip deadline check using actual httpx streaming, no network."""
from datetime import datetime, timezone
import math
import httpx
from global_pulse.nws_zone_resolver import ZoneResolver, _retry_seconds


def test_slow_drip_checked_before_large_chunk_accumulates():
    elapsed=[0.0]
    class Drip(httpx.SyncByteStream):
        delivered=0
        closed=False
        def __iter__(self):
            for _ in range(100000):
                elapsed[0]+=1
                self.delivered+=1
                yield b' '
        def close(self):self.closed=True
    stream=Drip()
    def handler(request):return httpx.Response(200,stream=stream,request=request)
    def factory(**kwargs):return httpx.Client(transport=httpx.MockTransport(handler),**kwargs)
    now=datetime(2026,11,11,9,tzinfo=timezone.utc)
    resolver=ZoneResolver(clock=lambda:elapsed[0],sleep=lambda n:None,now=lambda:now)
    original={'id':'slow-fixture','official':True,'affected_zones':['https://api.weather.gov/zones/forecast/PKZ801']}
    reports,stats=resolver.enrich([original],client_factory=factory)
    assert stream.delivered==30 and stream.closed
    assert reports==[original] and stats['lookup_failures']==1
    assert not resolver.lock.locked()


def test_large_retry_after_is_not_shortened():
    now=datetime(2026,11,11,tzinfo=timezone.utc)
    assert _retry_seconds('7200',now)==7200
    assert math.isinf(_retry_seconds('9'*200,now))
