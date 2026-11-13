"""Bounded NWS affected-zone geometry, never geocoded guesses.

Called only in the existing NWS collection worker. Original alert polygons win.
Eight lookups maximum per poll, two-second shared pacing, bounded in-memory
positive/negative cache, explicit partial coverage and provider-wide cooldown.
"""
from __future__ import annotations
from collections import OrderedDict
import copy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import threading
import time
import httpx
from .map_evidence import normalize_geometry, valid_nws_zone, MAX_ZONE_REFS

MAX_REQUESTS = 8
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CACHE_BYTES = 4 * 1024 * 1024
MAX_CACHE_ENTRIES = 128
POLL_SECONDS = 30
UA = 'GlobalPulse/0.1 (Dietrich AI Labs; https://www.dietrichailabs.com; NWS affected-zone lookup)'


def _stamp(value):
    try:
        if not isinstance(value,str):return None
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (ValueError,OverflowError):return None


def _eligible(report, now):
    if not isinstance(report,dict) or report.get('official') is not True:return False
    if report.get('cap_message_type')=='Cancel' or report.get('kind') in {'retraction','cancellation'}:return False
    if report.get('status','active') not in {'','active'} or report.get('evidence_status','active')!='active':return False
    published=_stamp(report.get('published_at'))
    expiry=_stamp(report.get('expires_at'))
    return not report.get('future_dated') and not (published and published>now) and not (expiry and expiry<=now)


def _retry_seconds(value, now):
    if isinstance(value,str):
        if value.isascii() and value.isdigit():
            # An unrepresentably large delay is a refusal, not a shorter retry.
            return float('inf') if len(value)>12 else float(value)
        try:
            dt=parsedate_to_datetime(value)
            if dt.tzinfo is not None:return max(0,(dt-now).total_seconds())
        except (ValueError,TypeError,OverflowError):pass
    return 0.0


def _polygons(geometry):
    return [geometry['coordinates']] if geometry['type']=='Polygon' else geometry['coordinates']


class ZoneResolver:
    def __init__(self, *, clock=time.monotonic, sleep=time.sleep, now=None):
        self.clock=clock;self.sleep=sleep
        self.now=now or (lambda:datetime.now(timezone.utc))
        self.lock=threading.Lock();self.cache=OrderedDict();self.cache_bytes=0
        self.next_request=0.0;self.blocked_until=0.0

    def _put(self,url,geometry,retrieved,ttl):
        size=len(json.dumps(geometry,separators=(',',':')).encode()) if geometry else 0
        if size>MAX_CACHE_BYTES:return
        old=self.cache.pop(url,None)
        if old:self.cache_bytes-=old[3]
        self.cache[url]=(self.clock()+ttl,geometry,retrieved,size)
        self.cache_bytes+=size
        while len(self.cache)>MAX_CACHE_ENTRIES or self.cache_bytes>MAX_CACHE_BYTES:
            _,old=self.cache.popitem(last=False);self.cache_bytes-=old[3]

    def _get(self,url,client_factory,budget,deadline,stats):
        current=self.clock()
        cached=self.cache.get(url)
        if cached and cached[0]>current:
            self.cache.move_to_end(url);stats['cache_hits']+=1
            return (cached[1],cached[2]) if cached[1] else None
        if cached:
            self.cache.pop(url);self.cache_bytes-=cached[3]
        if budget[0]<=0 or current>=deadline or current<self.blocked_until:return None
        wait=max(0,self.next_request-current)
        if current+wait+3>=deadline:return None
        if wait:self.sleep(wait)
        if self.clock()>=deadline:return None
        budget[0]-=1;stats['requests']+=1
        self.next_request=self.clock()+2.0
        now=self.now();retrieved=now.isoformat(timespec='seconds').replace('+00:00','Z')
        try:
            with client_factory(timeout=httpx.Timeout(3.0,connect=2.0),follow_redirects=False,
                    headers={'User-Agent':UA,'Accept':'application/geo+json','Accept-Encoding':'identity'}) as client:
                with client.stream('GET',url) as response:
                    status=response.status_code
                    if status in {401,403,451}:
                        self.blocked_until=max(self.blocked_until,self.clock()+86400)
                        stats['provider_refusals']+=1
                    elif status in {429,503}:
                        self.blocked_until=max(self.blocked_until,self.clock()+max(3600,_retry_seconds(response.headers.get('retry-after'),now)))
                        stats['provider_refusals']+=1
                    if status!=200:
                        self._put(url,None,retrieved,86400 if status in {401,403,404,451} else 3600)
                        return None
                    if response.headers.get('content-encoding','identity').lower() not in {'','identity'}:
                        raise ValueError('Unexpected compressed zone transfer')
                    length=response.headers.get('content-length','')
                    if length.isdigit() and int(length)>MAX_RESPONSE_BYTES:raise ValueError('Zone response too large')
                    raw=bytearray()
                    # Do not buffer 64KiB before checking elapsed time: a slow
                    # drip must be checked at each delivered transport chunk.
                    for part in response.iter_bytes():
                        if self.clock()>=deadline or len(raw)+len(part)>MAX_RESPONSE_BYTES:
                            raise ValueError('Zone response bound exceeded')
                        raw.extend(part)
            payload=json.loads(raw)
            if not isinstance(payload,dict) or payload.get('type')!='Feature':raise ValueError('Expected zone Feature')
            props=payload.get('properties')
            if not isinstance(props,dict) or props.get('id')!=url.rsplit('/',1)[-1]:raise ValueError('Zone identity mismatch')
            for name in ('id','@id'):
                identity=payload.get(name)
                if identity is not None and identity!=url:raise ValueError('Zone URL identity mismatch')
            geometry=normalize_geometry(payload.get('geometry'))
            self._put(url,geometry,retrieved,86400)
            return geometry,retrieved
        except Exception:
            # A failed shape lookup must not discard the underlying alert.
            stats['lookup_failures']+=1
            self._put(url,None,retrieved,600)
            return None

    def enrich(self,reports, *, client_factory=None):
        if not isinstance(reports,list) or len(reports)>600:raise ValueError('Invalid NWS report batch')
        result=copy.deepcopy(reports)
        stats=dict(requests=0,cache_hits=0,lookup_failures=0,provider_refusals=0,
                   resolved_alerts=0,partial_alerts=0,unresolved_alerts=0,busy=False)
        if not self.lock.acquire(blocking=False):
            stats.update(busy=True,unresolved_alerts=sum(bool(r.get('affected_zones')) and not r.get('area_geometry') for r in result if isinstance(r,dict)))
            return result,stats
        try:
            factory=client_factory or httpx.Client
            deadline=self.clock()+POLL_SECONDS;budget=[MAX_REQUESTS];now=self.now()
            for report in result:
                if not _eligible(report,now):continue
                if report.get('area_geometry') and report.get('area_geometry_basis')!='nws_affected_zones':
                    try:normalize_geometry(report['area_geometry']);continue
                    except ValueError:pass
                refs=report.get('affected_zones',[])
                if (not isinstance(refs,list) or len(refs)>MAX_ZONE_REFS
                        or any(not valid_nws_zone(ref) for ref in refs)):
                    if refs and not report.get('area_geometry'):
                        report['area_status']='invalid_zone_references'
                        stats['unresolved_alerts']+=1
                    continue
                refs=list(dict.fromkeys(refs))
                if not refs:continue
                polygons=[];used=[]
                for url in refs:
                    found=self._get(url,factory,budget,deadline,stats)
                    if found is None:continue
                    geometry,retrieved=found
                    proposal={'type':'MultiPolygon','coordinates':polygons+_polygons(geometry)}
                    try:proposal=normalize_geometry(proposal)
                    except ValueError:continue
                    polygons=proposal['coordinates'];used.append({'url':url,'retrieved_at':retrieved})
                if used:
                    report.update(area_geometry={'type':'MultiPolygon','coordinates':polygons},
                        area_geometry_basis='nws_affected_zones',area_zone_sources=used,
                        area_status='provider_zone_geometry' if len(used)==len(refs) else 'partial_provider_zones')
                    stats['resolved_alerts']+=1
                    if len(used)<len(refs):stats['partial_alerts']+=1
                if len(used)<len(refs):stats['unresolved_alerts']+=1
            return result,stats
        finally:self.lock.release()


DEFAULT_RESOLVER=ZoneResolver()
