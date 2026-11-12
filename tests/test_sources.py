from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import threading
import time

import httpx
import pytest
from defusedxml.common import DefusedXmlException

from global_pulse.sources import (
    Collector, Scheduler, canonical_url, iso, load_catalog, make_user_feed,
    parse_eonet, parse_feed, parse_nws, parse_usgs, parse_worldbank, plain,
    public_url, retry_after,
)

NOW = datetime(2026, 11, 8, 22, 0, tzinfo=timezone.utc)
STAMP = '2026-11-08T22:00:00Z'


def source(**overrides):
    s = dict(id='test',name='Test publisher',url='https://example.org/rss',adapter='rss',enabled=True,
             min_interval=600,allowed_domains=['example.org'],category='News',region='Global',
             access_status='reviewed_public',license='Synthetic test',attribution='Test',language='en')
    s.update(overrides)
    return s


def factory(handler):
    return lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs)


RSS = b'''<rss version="2.0"><channel><item><guid>stable-1</guid>
<title>Regional report</title><link>https://example.org/story</link>
<pubDate>Sun, 08 Nov 2026 20:00:00 GMT</pubDate>
<description>&lt;p&gt;A road is closed.&lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;</description>
</item></channel></rss>'''


def test_catalog_has_reviewed_free_core_and_explicit_restrictions():
    catalog = load_catalog()
    assert len(catalog) >= 20
    assert all(s['access_status'] == 'reviewed_public' for s in catalog if s['enabled'])
    assert len({s['region'] for s in catalog if s['enabled']}) >= 4
    for key in ['bbc','reliefweb','x','facebook','tousitv']:
        assert not next(s for s in catalog if s['id'] == key)['enabled']
    assert any(s['adapter'] == 'worldbank' and s['min_interval'] >= 86400 for s in catalog)


@pytest.mark.parametrize('url',['http://example.org','file:///etc/passwd','javascript:alert(1)',
                                    'https://localhost/a','https://127.0.0.1/a','https://10.0.0.1',
                                    'https://[::1]/','https://example.org:444/','https://user:pass@example.org',
                                    'https://host.internal/a','https://example.org/\nfoo'])
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_domain_suffix_attack_rejected():
    with pytest.raises(ValueError):
        public_url('https://example.org.attacker.test/rss',['example.org'])


def test_custom_feed_dns_private_rejected(monkeypatch):
    monkeypatch.setattr('global_pulse.sources.socket.getaddrinfo',lambda *a,**k:[(0,0,0,'',('10.1.2.3',443))])
    with pytest.raises(ValueError):
        make_user_feed('https://feeds.example.org/rss','User feed')


def test_custom_feed_unknown_independence_and_metadata_only(monkeypatch):
    monkeypatch.setattr('global_pulse.sources.socket.getaddrinfo',lambda *a,**k:[(0,0,0,'',('8.8.8.8',443))])
    s = make_user_feed('https://example.org/rss','<b>My feed</b>')
    assert s['metadata_only'] and s['independence'] == 'unknown'
    r = parse_feed(RSS,s,STAMP)[0]
    assert r['summary'] == '' and not r['official']


def test_rss_sanitization_stable_identity_and_no_invented_independence():
    r = parse_feed(RSS,source(),STAMP)[0]
    assert r['summary'] == 'A road is closed.'
    assert r['published_at'] == '2026-11-08T20:00:00Z'
    assert r['independence'] == 'unknown' and r['origin_id'] == ''
    assert r['id'] == parse_feed(RSS,source(),'2026-11-09T22:00:00Z')[0]['id']


def test_atom_rdf_and_missing_publication_time():
    atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>a</id><title>Notice</title><link href="https://example.org/a"/><updated>2026-11-08T21:00:00Z</updated></entry></feed>'
    r=parse_feed(atom,source(adapter='atom'),STAMP)[0]
    assert r['published_at'] == '' and r['publication_time_unknown']
    assert r['source_updated_at'] == '2026-11-08T21:00:00Z'
    rdf=b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"><item><title>T</title><link>https://example.org/t</link></item></rdf:RDF>'
    assert len(parse_feed(rdf,source(),STAMP))==1


def test_xml_entities_and_html_error_page_rejected():
    bad=b'<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss><channel><item><title>&xxe;</title></item></channel></rss>'
    with pytest.raises(DefusedXmlException):
        parse_feed(bad,source(),STAMP)
    with pytest.raises(ValueError):
        parse_feed(b'<html><title>Server error</title></html>',source(),STAMP)


def test_truncation_no_full_article_and_untrusted_media_not_loaded():
    assert len(plain('<p>'+('a'*5000)+'</p>'))==1000
    assert 'secret' not in plain('<style>secret</style>real')
    r=parse_feed(RSS.replace(b'https://example.org/story',b'javascript:alert(1)'),source(),STAMP)
    assert r == []


def test_usgs_preserves_measurement_and_source_geolocation():
    p={'type':'FeatureCollection','features':[{'id':'us123','geometry':{'type':'Point','coordinates':[140.1,38.2,12]},'properties':{'title':'M 6.3 — offshore','mag':6.3,'magType':'mww','time':1794153600000,'url':'https://earthquake.usgs.gov/a','status':'preliminary'}}]}
    r=parse_usgs(p,source(id='usgs',article_domains=['earthquake.usgs.gov']),STAMP)[0]
    assert r['official_scope']=='measurement' and r['claims']['magnitude']['value']==6.3
    assert r['geo_precision']=='source_point' and r['latitude']==38.2
    assert 'not inferred' in r['summary'] and r['event_key']=='usgs:us123'


def test_eonet_does_not_claim_independent_confirmation():
    p={'events':[{'id':'E1','title':'Wildfire','link':'https://example.org/e1','geometry':[{'date':'2026-11-06T00:00:00Z','type':'Point','coordinates':[10,20]}],'sources':[{'id':'USGS','url':'https://earthquake.usgs.gov/a'}]}]}
    r=parse_eonet(p,source(),STAMP)[0]
    assert r['independence']=='unknown' and r['official_scope']=='statement'
    assert r['severity']=='unassessed'


def test_nws_filters_exercise_messages_and_does_not_invent_polygon_point():
    p={'features':[{'id':'https://api.weather.gov/alerts/1','properties':{'status':'Exercise','headline':'test'}},
                   {'id':'https://api.weather.gov/alerts/2','properties':{'status':'Actual','headline':'Storm','sent':STAMP,'severity':'Severe','areaDesc':'Coastal county'}}]}
    r=parse_nws(p,source(),STAMP)
    assert len(r)==1 and r[0]['severity']=='high' and r[0]['latitude'] is None


def test_cap_actual_only():
    cap=b'<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><identifier>a</identifier><sent>2026-11-08T20:00:00Z</sent><status>Actual</status><msgType>Alert</msgType><info><headline>Warning</headline><severity>Severe</severity><web>https://example.org/a</web></info></alert>'
    assert parse_feed(cap,source(adapter='cap'),STAMP)[0]['severity']=='high'
    assert parse_feed(cap.replace(b'Actual',b'Test'),source(adapter='cap'),STAMP)==[]


def test_worldbank_separates_observation_release_and_retrieval_dates():
    p=[{'lastupdated':'2026-10-31','pages':1},[{'indicator':{'id':'FP.CPI.TOTL.ZG','value':'Inflation'},'country':{'id':'ZA','value':'South Africa'},'countryiso3code':'ZAF','date':'2025','value':4.5,'unit':''},{'date':'2024','value':None}]]
    r=parse_worldbank(p,source(unit='annual %'),STAMP)
    assert len(r)==1 and r[0]['observation_date']=='2025'
    assert r[0]['release_date'] is None and r[0]['dataset_updated_at']=='2026-10-31'
    assert r[0]['retrieved_at']==STAMP and r[0]['unit']=='annual %'


def test_success_conditional_headers_and_checkpoint():
    def handle(request):
        assert request.headers['if-none-match']=='abc'
        assert request.headers['if-modified-since']=='Sun, 08 Nov 2026 20:00:00 GMT'
        assert 'GlobalPulse' in request.headers['user-agent']
        return httpx.Response(200,content=RSS,headers={'ETag':'def','Cache-Control':'max-age=1800'})
    r=Collector(source(),client_factory=factory(handle),now=lambda:NOW).collect({'etag':'abc','last_modified':'Sun, 08 Nov 2026 20:00:00 GMT'})
    assert len(r['reports'])==1 and r['state']['etag']=='def'
    assert r['state']['next_poll']=='2026-11-08T22:30:00Z' and r['state']['last_success']==STAMP


def test_304_has_no_repeated_data_and_resets_failures():
    r=Collector(source(),client_factory=factory(lambda r:httpx.Response(304)),now=lambda:NOW).collect({'failures':4})
    assert r['reports']==[] and r['state']['status']=='not_modified' and r['state']['failures']==0


@pytest.mark.parametrize('header,seconds',[('3600',3600),('Sun, 08 Nov 2026 23:00:00 GMT',3600)])
def test_retry_after_seconds_and_date_never_shortened(header,seconds):
    r=Collector(source(),client_factory=factory(lambda r:httpx.Response(429,headers={'Retry-After':header})),now=lambda:NOW).collect()
    assert r['state']['status']=='rate_limited' and r['state']['retry_after_seconds']>=seconds
    assert r['reports']==[]


def test_error_failure_isolation_redacts_request_url():
    r=Collector(source(),client_factory=factory(lambda r:httpx.Response(403)),now=lambda:NOW).collect()
    # An HTTP403 is an explicit finite access denial, not a generic error.
    assert r['state']['last_failure']==STAMP and r['state']['status']=='denied'
    assert r['state']['retry_after_seconds'] >= 86400
    assert 'https://' not in r['state']['error']
    assert r['state']['next_poll']>='2026-11-09T22:00:00Z'


def test_redirect_to_private_or_unapproved_domain_is_never_followed():
    calls=[]
    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(302,headers={'location':'https://127.0.0.1/private'})
    r=Collector(source(),client_factory=factory(handle),now=lambda:NOW).collect()
    assert len(calls)==1 and r['state']['status']=='error'


def test_payload_limit_after_decompression(monkeypatch):
    monkeypatch.setattr('global_pulse.sources.MAX_BYTES',16)
    r=Collector(source(),client_factory=factory(lambda r:httpx.Response(200,content=RSS)),now=lambda:NOW).collect()
    assert r['state']['status']=='error' and r['reports']==[]


def test_disabled_source_performs_no_http():
    def no_calls(**kw):
        raise AssertionError('must not connect')
    assert Collector(source(enabled=False),client_factory=no_calls).collect()['state']['status']=='disabled'


class MemoryStore:
    def __init__(self): self.states={}
    def get_source_state(self,sid): return dict(self.states.get(sid,{}))
    def set_source_state(self,sid,state): self.states[sid]=dict(state)


def test_scheduler_bounded_no_overlap_pause_generation_and_stop():
    store=MemoryStore()
    began=threading.Event(); release=threading.Event(); received=[]; calls=[]
    class Blocking:
        def __init__(self,s): self.s=s
        def collect(self,state):
            calls.append(self.s['id']);began.set();release.wait(2)
            return {'reports':[{'id':'r'}],'observations':[],'state':{'status':'available','next_poll':iso(NOW+timedelta(days=3650))}}
    scheduler=Scheduler(store,received.append,collector_factory=Blocking,max_workers=1)
    scheduler.set_sources([source()])
    scheduler.start();assert began.wait(1)
    scheduler.poll_now();scheduler._tick()
    assert len(calls)==1
    scheduler.pause();release.set()
    for thread in list(scheduler._workers.values()):thread.join(1)
    assert received==[] and store.states=={}
    start=time.monotonic();scheduler.stop();assert time.monotonic()-start<2.2


def test_scheduler_respects_persisted_backoff_after_restart():
    store=MemoryStore();store.states['test']={'status':'rate_limited','next_poll':iso(datetime.now(timezone.utc)+timedelta(hours=1))}
    calls=[]
    class NoPoll:
        def __init__(self,s): calls.append(s)
    scheduler=Scheduler(store,lambda r:None,collector_factory=NoPoll)
    scheduler.set_sources([source()]);scheduler._tick();scheduler.poll_now();scheduler._tick()
    assert calls==[]


def test_gzip_expansion_is_bounded_before_decode_allocation(monkeypatch):
    import gzip
    monkeypatch.setattr('global_pulse.sources.MAX_BYTES',1024)
    packed=gzip.compress(b'x'*100000)
    r=Collector(source(),client_factory=factory(lambda q:httpx.Response(200,stream=httpx.ByteStream(packed),headers={'Content-Encoding':'gzip'})),now=lambda:NOW).collect()
    assert r['state']['status']=='error' and 'size limit' in r['state']['error']


def test_publication_staleness_survives_304():
    old=RSS.replace(b'08 Nov 2026',b'08 Nov 2024')
    r=Collector(source(),client_factory=factory(lambda q:httpx.Response(200,content=old)),now=lambda:NOW).collect()
    assert r['state']['status']=='stale'
    unchanged=Collector(source(),client_factory=factory(lambda q:httpx.Response(304)),now=lambda:NOW).collect(r['state'])
    assert unchanged['state']['status']=='stale'


def test_nws_http_web_link_falls_back_to_real_https_record():
    p={'features':[{'id':'https://api.weather.gov/alerts/abc','properties':{'id':'urn:oid:abc','status':'Actual','headline':'Warning','web':'http://www.weather.gov/','sent':STAMP}}]}
    r=parse_nws(p,source(),STAMP)
    assert len(r)==1 and r[0]['url']=='https://api.weather.gov/alerts/abc'


def test_gdacs_http_original_preserved_with_reviewed_https_equivalent():
    rss=b'<rss><channel><item><title>Earthquake report</title><link>http://www.gdacs.org/report.aspx?eventid=1</link></item></channel></rss>'
    r=parse_feed(rss,source(id='gdacs',url='https://www.gdacs.org/xml/rss.xml',adapter='gdacs',upgrade_http_domains=['www.gdacs.org']),STAMP)[0]
    assert r['url'].startswith('https://') and r['original_url'].startswith('http://')
    assert r['independence']=='unknown'


def test_unreviewed_source_cannot_be_enabled():
    scheduler=Scheduler(MemoryStore(),lambda r:None)
    with pytest.raises(ValueError):
        scheduler.set_sources([source(access_status='review_required')])


def test_shared_host_rate_limit_restored_from_peer_checkpoint():
    store=MemoryStore();store.states['limited']={'status':'rate_limited','next_poll':iso(datetime.now(timezone.utc)+timedelta(hours=1))}
    calls=[]
    class NoPoll:
        def __init__(self,s): calls.append(s)
    scheduler=Scheduler(store,lambda r:None,collector_factory=NoPoll)
    scheduler.set_sources([source(id='fresh'),source(id='limited')]);scheduler._tick()
    assert calls==[]


def test_mixed_hex_ipv4_hostname_is_not_treated_as_public_dns():
    with pytest.raises(ValueError):
        public_url('https://0x7f.0.0.1/private')
