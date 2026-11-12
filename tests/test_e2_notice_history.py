"""Durable notice regressions using the actual QObject controller and SQLite."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.core import Store, alert_reason, notification_view

T=datetime(2026,11,8,10,tzinfo=timezone.utc)
def iso(day): return (T+timedelta(days=day)).isoformat().replace('+00:00','Z')
def record(day=0,kind='report',**kw):
    r=dict(id='a', source_id='authority',publisher='Synthetic authority',title='Fictional harbor notice',
           summary='Synthetic content version '+str(day),url='https://authority.example/a',published_at=iso(day),
           event_key='notice-chain',country='Norland',region='Harbor',category='Infrastructure',
           language='en',kind=kind,severity='high' if day==0 else 'informational',
           official=True,official_scope='statement',independence='original',origin_id='authority',synthetic=True)
    r.update(kw);return r

@pytest.fixture(scope='module')
def app(): return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('separate', [False,True])
@pytest.mark.parametrize('restart', [False,True])
def test_twelve_material_notices_keep_durable_significance(app,tmp_path,separate,restart):
    c=Controller(tmp_path,demo=True)
    try:
        for day in range(13):
            kind='report' if day==0 else 'retraction' if day==12 else 'correction'
            changes={}
            if separate and day:
                changes=dict(id=f'notice-{day}',url=f'https://authority.example/notice/{day}')
                changes['retraction_of' if kind=='retraction' else 'correction_of']='a' if day==1 else f'notice-{day-1}'
            c._on_reports([record(day,kind,**changes)],allow_synthetic=True,now=iso(day))
            assert len(c.store.list_alerts())==day+1
            c._on_reports([record(day,kind,**changes)],allow_synthetic=True,now=iso(day))
            assert len(c.store.list_alerts())==day+1
            if restart:
                c.close();c=Controller(tmp_path,demo=True)
        assert len(c.events())==1
        assert len(c.events()[0]['timeline'])==13
    finally:c.close()

@pytest.mark.parametrize('setting,value', [('muted_sources',['authority']),('countries',['Elsewhere']),('categories',['Economy']),('alert_threshold','critical')])
def test_durable_history_honors_current_preferences(app,tmp_path,setting,value):
    c=Controller(tmp_path,demo=True)
    try:
        c._on_reports([record()],allow_synthetic=True,now=iso(0))
        c._on_reports([record(1,'correction')],allow_synthetic=True,now=iso(1))
        c.set_setting(setting,value)
        c._on_reports([record(2,'retraction')],allow_synthetic=True,now=iso(2))
        assert len(c.store.list_alerts())==2
    finally:c.close()


def test_ordinary_downgrade_does_not_erase_history(app,tmp_path):
    c=Controller(tmp_path,demo=True)
    try:
        c._on_reports([record()],allow_synthetic=True,now=iso(0))
        c._on_reports([record(1)],allow_synthetic=True,now=iso(1))
        c._on_reports([record(2,'correction')],allow_synthetic=True,now=iso(2))
        assert any(a['kind']=='correction' for a in c.store.list_alerts())
    finally:c.close()


def test_low_only_notice_chain_stays_feed_only(app,tmp_path):
    c=Controller(tmp_path,demo=True)
    try:
        for day in range(5):
            c._on_reports([record(day,'correction' if day else 'report',severity='informational')],allow_synthetic=True,now=iso(day))
        assert not c.store.list_alerts()
    finally:c.close()


def test_muted_projection_does_not_invent_changes(tmp_path):
    with Store(tmp_path/'s.sqlite',mode='synthetic') as s:
        s.ingest([record()],now=iso(0))
        s.ingest([record(1,'correction')],now=iso(1))
        other=record(2,source_id='other',id='other',kind='commentary',official=False,origin_id='')
        e=s.ingest([other],now=iso(2))[0]
        projected=notification_view(e,['irrelevant-source'])
        assert not any(c['kind']=='correction' for c in projected['changes'])
