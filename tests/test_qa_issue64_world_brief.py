"""QA-only adversarial World Overview and evidence navigation, frozen source.

No network, model calls, fictional current crises or physical Windows claims.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QUrl
from PySide6.QtWidgets import QApplication

from global_pulse.brief_selection import (
    balanced_brief_sections, brief_domain, overview_html,
)
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def record(i, category, severity="unassessed", **overrides):
    at=(datetime.now(timezone.utc)-timedelta(minutes=i+1)).isoformat()
    data=dict(
        id=f"qa-intel-{i}",
        title=f"SYNTHETIC {category} item {i}",
        category=category, severity=severity,
        status="active", verification="unverified",
        updated_at=at, published_at=at, report_count=1,
        reports=[dict(id=f"qa-report-{i}",source_id="qa-journal",
                      publisher="QA Journal",title=f"QA story {i}",
                      published_at=at,retrieved_at=at,
                      publication_time_known=True,
                      url=f"https://example.org/qa/{i}")],
    )
    data.update(overrides)
    return data


def test_high_severity_weather_cannot_hide_health_conflict_government():
    rows=[record(i,"Disaster","critical") for i in range(350)]
    rows.extend([
        record(400,"Health",text="health"),record(401,"Government"),
        record(402,"Conflict"),record(403,"Humanitarian"),record(404,"Economy"),
        record(405,"Infrastructure"),record(406,"Unrest"),
    ])
    sections=dict(balanced_brief_sections(rows,per_domain=3,
                                           max_total=30,disaster_limit=3))
    assert len(sections["Weather & disasters"])==3
    assert "Health & disease" in sections
    assert "Conflict & security" in sections
    assert "Unrest & civil affairs" in sections
    assert "Government & politics" in sections
    page=overview_html(rows)
    assert "SYNTHETIC Health item 400" in page
    assert "SYNTHETIC Conflict item 402" in page
    assert page.count("SYNTHETIC Disaster item")<=2


def test_expired_and_unknown_publication_are_labeled():
    expired=record(1,"Health",status="expired")
    expired["reports"][0]["publication_time_known"]=False
    expired["reports"][0]["published_at"]=""
    page=overview_html([expired])
    assert "expired" in page
    assert "first retrieved" in page
    assert "publication unknown" in page
    assert "source published" not in page
    assert "not that no conflict" in page


def test_claims_in_unclassified_headlines_are_not_promoted_to_confirmed_conflict():
    item=record(1,"News",title="<img onerror=alert(1)> WAR BREAKS OUT?")
    assert brief_domain(item)=="General news"
    page=overview_html([item])
    assert "<img" not in page
    assert "&lt;img" in page
    assert "Unverified reports are not independently confirmed" in page


def test_duplicate_record_ids_do_not_repeat_across_world_sections():
    item1=record(1,"Government")
    item2=dict(item1,category="Disaster")
    groups=balanced_brief_sections([item1,item2],per_domain=3,max_total=12)
    assert sum(len(rows) for _domain,rows in groups)==1


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(app,tmp_path):
    c=Controller(tmp_path,demo=True)
    at=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
    events=c.store.ingest([{
        "id":f"qa-brief-side-{i}","source_id":"qa-source",
        "publisher":"QA Synthetic","title":f"SYNTHETIC {cat} report",
        "summary":"Nothing happened: fixture only",
        "event_key":f"qa-brief:{i}",
        "url":f"https://example.org/brief/{i}",
        "published_at":at,"retrieved_at":at,
        "region":"Global","category":cat,"synthetic":True,
        "severity":"unassessed",
    } for i,cat in enumerate(("Disaster","Health","Government"))])
    window=MainWindow(c)
    window.show()
    app.processEvents()
    window.refresh_data()
    yield window,c,events
    window._force_close=True
    window.close()
    c.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_normal_monitor_refresh_preserves_world_overview_view_and_clicked_event(desktop):
    window,controller,events=desktop
    assert window.intelligence_mode.currentIndex()==0
    contents=window.overview_browser.toPlainText()
    assert "Health & disease" in contents and "Government & politics" in contents
    selected=next(r["id"] for r in events if r["category"]=="Health")
    window._open_overview_event(QUrl("pulse-event://open/"+selected))
    assert window.intelligence_mode.currentIndex()==1
    assert window._selected_id==selected
    assert "Health report" in window.intel_browser.toPlainText()
    window.intelligence_mode.setCurrentIndex(0)
    window.refresh_data()
    assert window.intelligence_mode.currentIndex()==0
    assert window._selected_id==selected


def test_overview_presentation_does_not_trigger_extra_per_category_store_reads(desktop,monkeypatch):
    window,controller,_=desktop
    original=controller.events
    count=[]
    def monitored(*args,**kwargs):
        count.append(kwargs)
        return original(*args,**kwargs)
    monkeypatch.setattr(controller,"events",monitored)
    window._update_world_overview()
    assert not count  # uses already available bounded report snapshot
    assert window.overview_browser.toPlainText()
