"""Integrate only successfully collected official feeds; no article scraping.

Run the explicit network audit once. Its per-source receipts are journaled after
each completed source. Publisher feed/attribution documentation is recorded below.
No model downloads, owner profile, media, settings or release files are touched.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone

BASE = '1881bd1dd9fe285b75d84e3a12b5c2762cc47972'
CATALOG = Path('global_pulse/resources/sources.json')
OUT = Path('docs/engineering/GP-OFFICIAL-FEEDS-20261111')
OGL = 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/'


def candidate(sid, name, url, home, category, domains, policy, basis, documentation, *, adapter='rss', article_domains=None):
    return dict(id=sid, name=name, url=url, homepage=home, adapter=adapter,
        category=category, region='Global', country='', language='en',
        enabled=True, min_interval=3600, allowed_domains=domains,
        access='Publisher-documented public RSS/Atom; no account or API key',
        access_status='reviewed_public', license=basis, license_url=policy,
        attribution=name+'; original link retained; feed text may be abridged; no endorsement',
        status='not_checked', authentication='None', review_date='2026-11-11',
        review_scope='Engineering feed-metadata integration; independent QA review pending',
        retention_days=90, stale_after_days=14, official=True,
        official_scope='statement', independence='original', metadata_only=True,
        article_domains=article_domains or domains, feed_documentation=documentation,
        limitation='Official statements are attributable to this agency, not independent confirmation of every claim. Publisher location is not an incident location. No photos or full articles fetched.')


def candidates():
    return [
      candidate('fed_press', 'Federal Reserve Board — Press Releases',
        'https://www.federalreserve.gov/feeds/press_all.xml', 'https://www.federalreserve.gov/newsevents/pressreleases.htm', 'Economy', ['www.federalreserve.gov'],
        'https://www.federalreserve.gov/disclaimer.htm',
        'Board-created information is public domain unless otherwise indicated. Cite the Federal Reserve Board; exclude third-party photos, graphics and trademarks.',
        'https://www.federalreserve.gov/feeds/feeds.htm'),
      candidate('bea_releases', 'U.S. Bureau of Economic Analysis — Releases',
        'https://apps.bea.gov/rss/rss.xml', 'https://www.bea.gov/news/current-releases', 'Economy', ['apps.bea.gov','www.bea.gov'],
        'https://www.bea.gov/help/faq/145',
        'BEA information is public domain unless otherwise stated; cite U.S. Bureau of Economic Analysis. No logos, graphics or third-party material copied.',
        'https://apps.bea.gov/rss/rss.xml', article_domains=['www.bea.gov','apps.bea.gov','bea.gov']),
      candidate('bls_latest', 'U.S. Bureau of Labor Statistics — Latest Indicators',
        'https://www.bls.gov/feed/bls_latest.rss', 'https://www.bls.gov/bls/newsrels.htm', 'Economy', ['www.bls.gov'],
        'https://www.bls.gov/opub/copyright-information.htm',
        'BLS published text/data is public domain; cite BLS. Previously copyrighted images and the BLS emblem are excluded.',
        'https://www.bls.gov/feed/'),
      candidate('un_geneva', 'United Nations Geneva — Press Items',
        'https://www.ungeneva.org/news-media/press-items-list/rss.xml', 'https://www.ungeneva.org/en/news-media', 'News', ['www.ungeneva.org'],
        'https://www.ungeneva.org/en/news-media/rss',
        'UN Geneva expressly offers RSS for readers and displaying its latest news. Integrate only supplied headline/link metadata with UN Geneva attribution; no full-article or media republication claim.',
        'https://www.ungeneva.org/en/news-media/rss'),
      candidate('ukhsa_news', 'UK Health Security Agency — News',
        'https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=uk-health-security-agency',
        'https://www.gov.uk/government/organisations/uk-health-security-agency', 'Health', ['www.gov.uk'],
        'https://www.gov.uk/help/terms-conditions',
        'Contains public sector information licensed under the Open Government Licence v3.0 ('+OGL+'). Cite UKHSA; exclude stated third-party material, logos and photos. Feed excerpts may be abridged.',
        'https://www.gov.uk/search/news-and-communications?organisations%5B%5D=uk-health-security-agency', adapter='atom'),
      candidate('uk_home_office_news', 'UK Home Office — News',
        'https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=home-office',
        'https://www.gov.uk/government/organisations/home-office', 'Government', ['www.gov.uk'],
        'https://www.gov.uk/help/terms-conditions',
        'Contains public sector information licensed under the Open Government Licence v3.0 ('+OGL+'). Cite UK Home Office; exclude stated third-party material, logos and photos. Feed excerpts may be abridged.',
        'https://www.gov.uk/search/news-and-communications?organisations%5B%5D=home-office', adapter='atom'),
    ]


def check_result(source, result, now):
    """A current feed must parse actual dated linked records, not an HTML200."""
    state = result.get('state') or {}
    reports = result.get('reports') or []
    good = []
    for r in reports:
        if not isinstance(r, dict) or r.get('source_id') != source['id'] or not r.get('title'):
            continue
        if not str(r.get('url','')).startswith('https://'):
            continue
        try:
            stamp = datetime.fromisoformat(r['published_at'].replace('Z','+00:00'))
            age = (now-stamp).total_seconds()
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= age <= 14*86400:
            good.append(r)
    return state.get('status') == 'available' and bool(good), good


def atomic_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    os.replace(temporary,path)


def audit():
    from global_pulse.sources import Collector, utcnow
    from global_pulse.core import Store
    raw = CATALOG.read_bytes()
    expected = subprocess.check_output(['git','show',BASE+':'+CATALOG.as_posix()])
    if raw != expected:
        raise RuntimeError('Source catalog no longer matches the chosen baseline; reconcile rather than overwrite')
    baseline = json.loads(raw)
    ids = {s['id'] for s in baseline['sources']}
    endpoints = {s['url'] for s in baseline['sources']}
    proposals = candidates()
    if any(s['id'] in ids or s['url'] in endpoints for s in proposals):
        raise RuntimeError('Batch duplicates an existing provider identity or endpoint')
    results=[]; accepted=[]; refused_hosts=set()
    for source in proposals:
        host=urlsplit(source['url']).hostname
        receipt=dict(id=source['id'],name=source['name'],feed_url=source['url'],
            checked_at=utcnow().isoformat(),policy_url=source['license_url'],
            feed_documentation=source['feed_documentation'],status='not_checked',
            article_fetches=0,minimum_poll_seconds=3600)
        if host in refused_hosts:
            receipt['status']='deferred_after_origin_refusal'
        else:
            now=utcnow()
            result=Collector(source, now=lambda:now).collect({'configured_interval':3600})
            state=result['state']; reports=result['reports']
            receipt.update(http_status=state.get('http_status'),collector_status=state.get('status'),
                parsed_reports=len(reports),bytes_received=state.get('bytes_received'),
                next_poll=state.get('next_poll'),last_success=state.get('last_success'),
                reporting_freshness=state.get('freshness'),newest_publication=state.get('latest_publication'))
            if state.get('http_status') in {401,403,429,451}:
                refused_hosts.add(host)
            ok,current=check_result(source,result,now)
            receipt['current_linked_reports']=len(current)
            if not ok:
                receipt['status']='not_admitted'
            else:
                # Use the real production Store in a disposable live-mode DB;
                # no fabricated fixture or owner history participates here.
                try:
                    with tempfile.TemporaryDirectory(prefix='gp-official-store-') as folder:
                        path=Path(folder)/'live.sqlite3'
                        store=Store(path,mode='live')
                        try:
                            changed=store.ingest(reports)
                            events=store.list_events(limit=2000)
                            seen={r['id'] for e in events for r in e.get('reports',[]) if r.get('source_id')==source['id']}
                            assert seen and any(r['id'] in seen for r in current)
                            receipt['stored_report_ids']=len(seen)
                            receipt['stored_events']=len(events)
                            receipt['parsed_identity_sha256']=hashlib.sha256('\n'.join(sorted(r['id'] for r in reports)).encode()).hexdigest()
                        finally:
                            store.close()
                        reopened=Store(path,mode='live')
                        try:
                            restored=reopened.list_events(limit=2000)
                            restored_ids={r['id'] for e in restored for r in e.get('reports',[]) if r.get('source_id')==source['id']}
                            assert seen==restored_ids
                            receipt['sqlite_reopen_verified']=True
                        finally:
                            reopened.close()
                    receipt['status']='collector_store_pass'
                    accepted.append(copy.deepcopy(source))
                except Exception as exc:
                    receipt.update(status='store_failed',error_type=type(exc).__name__)
        results.append(receipt)
        atomic_json(OUT/'live-check.json',dict(baseline=BASE,complete=False,sources=results))
        print('GP_OFFICIAL_FEED',json.dumps(receipt,sort_keys=True),flush=True)
        time.sleep(5)
    report=dict(baseline=BASE,complete=True,attempted=len(results),admitted_ids=[s['id'] for s in accepted],
        admitted_count=len(accepted),sources=results,zero_throttle_guarantee=False,
        sustained_reliability_verified=False,packaged_windows_verified=False,
        limits='One consented sequential collection through actual Collector and Store. No article fetches, fake points, GUI playback, sustained uptime or independent QA inferred.')
    atomic_json(OUT/'live-check.json',report)
    if not accepted:
        raise RuntimeError('No feed passed collection, current linked records and SQLite reopen; no catalog change')
    baseline['sources'].extend(accepted)
    baseline['catalog_version']='2026.11.11.official1'
    baseline['reviewed_at']='2026-11-11'
    atomic_json(CATALOG,baseline)
    from global_pulse.sources import load_catalog
    load_catalog(CATALOG)
    print('GP_OFFICIAL_ADMITTED',len(accepted),','.join(s['id'] for s in accepted),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--consent-network',action='store_true')
    args=parser.parse_args()
    if not args.consent_network:parser.error('Explicit --consent-network required')
    audit()
