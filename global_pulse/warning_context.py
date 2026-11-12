"""Area-only display context for a current NWS Update with missing history.

This does NOT change report/event lifecycle, source verification, alerts, point
locations, country activity, or stored evidence. The update's own bounded area
may be displayed with a persistent incomplete-history label. Invalid references,
expired/future/withdrawn reports and other kinds of pending news stay excluded.
"""
from __future__ import annotations
from datetime import datetime, timezone
from .map_evidence import normalize_geometry

# A bounded SQL candidate filter, not an evidence acceptance rule. Every returned
# pending candidate must still pass the report/time checks below on read.
PENDING_AREA_SQL = """(json_extract(body,'$.status')='pending' AND EXISTS (
 SELECT 1 FROM reports AS wr WHERE wr.event_id=events.id
 AND json_extract(wr.body,'$.source_id')='nws'
 AND json_extract(wr.body,'$.cap_message_type')='Update'
 AND json_extract(wr.body,'$.cap_status')='Actual'
 AND json_extract(wr.body,'$.official')=1
 AND json_extract(wr.body,'$.area_geometry') IS NOT NULL))"""
LABEL = 'Official warning update; earlier bulletin unavailable — history incomplete'


def _time(value):
    if not isinstance(value,str) or not 1 <= len(value) <= 80:
        return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (TypeError,ValueError,OverflowError):
        return None


def current_update_context(report, at):
    if not isinstance(report,dict):return False
    if (report.get('source_id')!='nws' or report.get('official') is not True
            or report.get('cap_status')!='Actual' or report.get('cap_message_type')!='Update'
            or report.get('kind')!='warning_update' or report.get('evidence_status')!='pending'
            or report.get('status','active')!='active' or report.get('future_dated')
            or report.get('expired') or report.get('expiry_invalid') or report.get('reference_errors')
            or report.get('superseded_by') or not report.get('unresolved_reference')):
        return False
    refs=report.get('lifecycle_references')
    if not isinstance(refs,list) or not 1 <= len(refs) <= 40 or not all(isinstance(r,str) and r.startswith('nws:') for r in refs):
        return False
    now,published,expires=_time(at),_time(report.get('published_at')),_time(report.get('expires_at'))
    if now is None or published is None or expires is None or not published <= now < expires:
        return False
    for key in ('source_updated_at','effective_at'):
        if report.get(key):
            value=_time(report[key])
            if value is None or value > now:return False
    if report.get('ends_at'):
        end=_time(report['ends_at'])
        if end is None or end <= now:return False
    return bool(report.get('area_geometry'))


def project_warning_context(event, at):
    """New display dictionary only; source records and pending state unchanged."""
    if not isinstance(event,dict) or event.get('status')!='pending':return event
    reports=event.get('reports')
    if not isinstance(reports,list):return event
    areas=[]
    for report in reports[:512]:
        if len(areas)>=32:break
        if not current_update_context(report,at):continue
        try:geometry=normalize_geometry(report.get('area_geometry'))
        except (ValueError,TypeError):continue
        zone_based=report.get('area_geometry_basis')=='nws_affected_zones'
        zone_note=''
        if zone_based:
            done=len(report.get('area_zone_sources',[]));total=len(report.get('affected_zones',[]))
            zone_note=f'; official zone boundaries {done}/{total}'
            if done < total:zone_note+=' (partial area; other zones unresolved)'
        description=(LABEL+'; bulletin expires '+str(report.get('expires_at'))
                     +'; hazard end '+str(report.get('ends_at') or 'not supplied')+zone_note)
        areas.append({'geometry':geometry,'source_id':report.get('source_id',''),
                      'report_id':report.get('id',''),'url':report.get('url',''),
                      'description':description,'context_only':True,
                      'basis':'provider_affected_zone_geometry' if zone_based else 'provider_alert_geometry'})
    if not areas:return event
    return dict(event,map_areas=areas,map_history_incomplete=True,map_context_label=LABEL,
                latitude=None,longitude=None,geo_precision='unknown')
