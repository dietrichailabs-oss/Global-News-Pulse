"""Issue64 regression: 500-row recent-feed saturation must not hide sourced
cross-domain records already present in the same bounded map evidence read.
All inputs are synthetic; assertions say nothing about current world crises.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent, QUrl, Qt
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


def test_explicit_archive_evidence_keeps_selected_event_across_refresh(tmp_path):
    """Keep an older source visible without overriding explicit user controls."""
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        old=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        recent=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
        identity=controller.store.ingest([_report(995,"Health",old)],now=old)[0]["id"]
        controller.store.ingest([_report(i,"Disaster",recent) for i in range(501)],now=recent)
        window=MainWindow(controller)
        window.show()
        app.processEvents()
        window.time_range.setCurrentIndex(3)
        window.refresh_data()
        assert identity not in {str(e["id"]) for e in window._events}
        window._open_overview_event(QUrl("pulse-event://open/"+quote(identity,safe="")))
        assert window._archive_selection_id==identity
        # Re-clicking the same archive story must not drop its pin:
        # the next normal collector refresh must still show its evidence.
        window.navigate_event(identity)
        assert window._archive_selection_id==identity
        assert window._selected_id==identity
        window.refresh_data()
        assert window._selected_id==identity
        assert identity in {str(e["id"]) for e in window._events}
        assert "SYNTHETIC Health evidence 995" in window.intel_browser.toPlainText()
        assert any(str(window.feed_list.item(i).data(Qt.ItemDataRole.UserRole).get("id"))==identity
                   for i in range(window.feed_list.count()))
        # Choosing a normal feed row relinquishes the archived selection.
        window.feed_list.setCurrentRow(1)
        assert window._selected_id!=identity
        assert not window._archive_selection_id
        window.refresh_data()
        assert identity not in {str(e["id"]) for e in window._events}
        # New explicit archive navigation may pin again, but text filters win.
        window.navigate_event(identity)
        assert window._archive_selection_id==identity
        window.search.setText("zzz-archive-scope-unmatched")
        window.refresh_data()
        assert not window._archive_selection_id
        assert window._selected_id!=identity
        assert identity not in {str(e["id"]) for e in window._events}
    finally:
        if window is not None:
            window._force_close=True
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
        controller.close()


def test_explicit_feed_selection_survives_newer_collector_page_eviction(tmp_path):
    """A clicked ordinary feed story must not silently switch Star to newer news.

    Start with the actual source row inside the latest 500, then collect two
    newer records that push it outside the page without changing user scope.
    Only the explicit choice is retained; selecting another row releases it.
    """
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        old=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        recent=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
        later=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        identity=controller.store.ingest([_report(997,"Health",old)],now=old)[0]["id"]
        controller.store.ingest([_report(i,"Disaster",recent) for i in range(499)],now=recent)
        window=MainWindow(controller)
        window.show()
        app.processEvents()
        window.time_range.setCurrentIndex(3)
        window.refresh_data()
        assert len(window._events)==500
        assert identity in {str(e["id"]) for e in window._events}
        row=next(i for i in range(window.feed_list.count())
                 if str(window.feed_list.item(i).data(Qt.ItemDataRole.UserRole).get("id"))==identity)
        window.feed_list.setCurrentRow(row)
        assert window._selected_id==identity
        assert window._explicit_feed_selection_id==identity
        assert not window._archive_selection_id  # Initially an ordinary feed row.
        controller.store.ingest([_report(i,"Disaster",later) for i in (700,701)],now=later)
        window.refresh_data()
        assert window._selected_id==identity
        assert window._archive_selection_id==identity
        assert identity in {str(e["id"]) for e in window._events}
        assert len(window._events)==500
        assert "SYNTHETIC Health evidence 997" in window.intel_browser.toPlainText()
        assert window.save_button.isEnabled()
        window.refresh_data()
        assert window._selected_id==identity
        # A deliberate different-row selection must release the one-row pin.
        window.feed_list.setCurrentRow(1)
        assert window._selected_id!=identity
        assert not window._archive_selection_id
        window.refresh_data()
        assert identity not in {str(e["id"]) for e in window._events}
    finally:
        if window is not None:
            window._force_close=True
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
        controller.close()


def test_missing_pinned_archive_report_never_rebinds_star_to_unrelated_story(tmp_path):
    """When local retention removes a selected archived row, do not auto-star news."""
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,demo=True)
    window=None
    try:
        old=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        newer=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
        identity=controller.store.ingest([_report(998,"Health",old)],now=old)[0]["id"]
        controller.store.ingest([_report(i,"Disaster",newer) for i in range(501)],now=newer)
        window=MainWindow(controller)
        window.show()
        app.processEvents()
        window.time_range.setCurrentIndex(3)
        window.refresh_data()
        window.navigate_event(identity)
        assert window._archive_selection_id==identity
        assert window._selected_id==identity
        # Model an archive record removed by retention between poll cycles.
        # All other newly collected records remain available in the feed.
        original_event=controller.event
        controller.event=lambda event_id: (
            None if str(event_id)==identity else original_event(event_id)
        )
        window.refresh_data()
        assert window._selected_id==""
        assert window._archive_selection_id==""
        assert window._explicit_feed_selection_id==""
        assert window._feed_explicitly_cleared
        assert window.feed_list.currentItem() is None
        assert not window.save_button.isEnabled()
        assert "Select an event" in window.intel_browser.toPlainText()
        # Continued collection cannot silently re-select another story.
        window.refresh_data()
        assert window._selected_id==""
        assert not window.save_button.isEnabled()
        assert window.feed_list.currentItem() is None
    finally:
        if window is not None:
            window._force_close=True
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
        controller.close()
