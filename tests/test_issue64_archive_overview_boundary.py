"""Issue64 regression: 500-row recent-feed saturation must not hide sourced
cross-domain records already present in the same bounded map evidence read.
All inputs are synthetic; assertions say nothing about current world crises.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtWidgets import QApplication

from global_pulse.brief_selection import (
    brief_domain, overview_evidence_candidates, overview_html,
)
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def synthetic_record(number, category, *, severity="unassessed", retained=False):
    at=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    return {
        "id":f"archive-boundary-{number}",
        "category":category, "status":"active",
        "title":f"SYNTHETIC {category} archive source {number}",
        "severity":severity, "updated_at":at,
        "verification":"unverified", "report_count":1,
        "retained_on_map":retained,
        "reports":[{"publisher":"QA Synthetic Publication",
                    "published_at":at,"publication_time_known":True}],
    }


def test_501_weather_rows_do_not_hide_older_sourced_nonweather_inventory():
    weather=[synthetic_record(i,"Disaster",severity="critical")
             for i in range(501)]
    health=synthetic_record(700,"Health",retained=True)
    assert all(brief_domain(e)!="Health & disease" for e in weather[:500])
    selected=overview_evidence_candidates(weather[:500],weather+[health])
    assert any(e["id"]==health["id"] for e in selected)
    assert len(selected)<=18
    page=overview_html(selected,label="synthetic filtered feed and map evidence")
    assert "SYNTHETIC Health archive source 700" in page
    assert "retained; no newer status" in page
    assert "QA Synthetic Publication" in page
    assert "pulse-event://open/archive-boundary-700" in page
    assert page.count("SYNTHETIC Disaster archive source")<=2
    assert "independently confirmed" in page
    assert "SYNTHETIC" in page


def test_candidate_selector_preserves_filters_identities_and_boundedness():
    event=synthetic_record(2,"Health")
    dup=dict(event,title="An older duplicate")
    filtered=overview_evidence_candidates([event], [dup])
    assert filtered==[event]
    assert overview_evidence_candidates([],[])==[]
    assert len(overview_evidence_candidates(
        [synthetic_record(i,"Disaster") for i in range(1501)],
        [synthetic_record(6000,"Government")]))==3


def _report(index, category, retrieved):
    return {
        "id":f"archive-report-{index}",
        "event_key":f"archive-event:{index}",
        "source_id":"qa-boundary",
        "publisher":"QA Synthetic Publication",
        "title":f"SYNTHETIC {category} evidence {index}",
        "summary":"Inert local report, no verified real-world claim.",
        "url":f"https://example.org/archive-boundary/{index}",
        "category":category, "severity":"unassessed",
        "region":"Global","country":"",
        "published_at":retrieved,"retrieved_at":retrieved,
        "synthetic":True,
    }


def test_real_store_feed_map_to_sidebar_and_safe_deep_link(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        older=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        newer=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
        saved=controller.store.ingest([_report(900,"Health",older)],now=older)
        health_id=saved[0]["id"]
        # 501 distinct newer source-attributed events occupy the 500-row feed.
        controller.store.ingest([_report(i,"Disaster",newer)
                                 for i in range(501)],now=newer)
        window=MainWindow(controller)
        window.show()
        app.processEvents()
        window.time_range.setCurrentIndex(3)  # All; no implicit filter broadening.
        window.refresh_data()
        assert len(window._events)==500
        assert health_id not in {e["id"] for e in window._events}
        assert health_id in {e["id"] for e in window._overview_events}
        assert "SYNTHETIC Health evidence 900" in window.overview_browser.toPlainText()
        old_status=window.intelligence_mode.currentIndex()
        window._open_overview_event(QUrl("https://example.org/unsafe"))
        assert window.intelligence_mode.currentIndex()==old_status
        window._open_overview_event(
            QUrl("pulse-event://open/"+quote(health_id,safe="")))
        assert window.intelligence_mode.currentIndex()==1
        assert window._selected_id==health_id
        assert "SYNTHETIC Health evidence 900" in window.intel_browser.toPlainText()
    finally:
        if window is not None:
            window._force_close=True
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
        controller.close()
