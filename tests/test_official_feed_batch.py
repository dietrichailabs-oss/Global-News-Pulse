"""Offline batch acceptance checks. Live evidence comes only from the separate audit."""
import json
import socket
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
import httpx
from global_pulse.sources import Collector, load_catalog, parse_feed
from global_pulse.source_availability import capability
from scripts.official_feed_batch import BASE, OUT, candidates, check_result

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**kw):raise AssertionError('Offline batch regressions must not contact providers')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)


def test_candidates_are_finite_documented_nonduplicated_sources():
    rows=candidates()
    assert len(rows)==6 and len({r['id'] for r in rows})==6
    assert len({r['url'] for r in rows})==6
    for s in rows:
        assert s['min_interval']>=3600 and s['country']==''
        assert s['license_url'].startswith('https://') and s['feed_documentation'].startswith('https://')
        assert s['metadata_only'] and s['official_scope']=='statement'
        assert capability(s)[0]

@pytest.mark.parametrize('bad',[{}, {'state':{'status':'available'},'reports':[]}, {'state':{'status':'stale'},'reports':[]}])
def test_status_without_current_linked_records_is_not_admission(bad):
    assert not check_result(candidates()[0],bad,datetime.now(timezone.utc))[0]

@pytest.mark.parametrize('age',[-3600,15*86400])
def test_future_and_old_reports_do_not_prove_current_feed(age):
    now=datetime.now(timezone.utc);s=candidates()[0]
    r=dict(source_id=s['id'],title='Synthetic date check',url='https://example.org/fixture',published_at=(now-timedelta(seconds=age)).isoformat())
    assert not check_result(s,{'state':{'status':'available'},'reports':[r]},now)[0]

@pytest.mark.parametrize('s',candidates(),ids=lambda s:s['id'])
def test_real_parser_preserves_attribution_without_invented_geography(s):
    host=s['article_domains'][0]
    body=f'''<rss version="2.0"><channel><item><guid>offline-only</guid><title>Published agency statement</title><link>https://{host}/fixture</link><pubDate>Wed, 11 Nov 2026 08:00:00 GMT</pubDate><description>Bounded synthetic text</description></item></channel></rss>'''.encode()
    rows=parse_feed(body,s,'2026-11-11T09:00:00Z')
    assert len(rows)==1
    r=rows[0]
    assert r['source_id']==s['id'] and r['attribution']==s['attribution']
    assert r['source_license']==s['license'] and r['country']==''
    assert r['latitude'] is None and r['longitude'] is None
    assert r['official'] is True

@pytest.mark.parametrize('s',candidates(),ids=lambda s:s['id'])
def test_new_feed_interval_and_retry_after_survive_real_collector(s):
    def handler(request):return httpx.Response(429,headers={'Retry-After':'7200'},request=request)
    def factory(**kwargs):return httpx.Client(transport=httpx.MockTransport(handler),**kwargs)
    now=datetime(2026,11,11,9,tzinfo=timezone.utc)
    result=Collector(s,client_factory=factory,now=lambda:now).collect({'configured_interval':300})
    state=result['state']
    assert state['status']=='rate_limited' and state['retry_after_seconds']>=7200
    assert not result['reports']


def test_integrated_catalog_adds_only_completed_live_passes():
    path=OUT/'live-check.json'
    assert path.exists(), 'Run the separate explicit live audit before this integration test'
    evidence=json.loads(path.read_text())
    assert evidence['complete'] is True and evidence['attempted']==6
    baseline=json.loads(subprocess.check_output(['git','show',BASE+':global_pulse/resources/sources.json']))['sources']
    current=load_catalog()
    assert current[:len(baseline)]==baseline
    added=current[len(baseline):]
    assert {s['id'] for s in added}==set(evidence['admitted_ids'])
    assert 1<=len(added)<=6
    receipts={r['id']:r for r in evidence['sources']}
    for s in added:
        r=receipts[s['id']]
        assert r['status']=='collector_store_pass' and r['current_linked_reports']>0
        assert r['sqlite_reopen_verified'] and r['stored_report_ids']>0
        assert s['enabled'] and capability(s)[0]
        assert s in candidates()
