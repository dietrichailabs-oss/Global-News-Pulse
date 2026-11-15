"""Owner Issue64: meaningful, bounded, multi-domain world intelligence briefs.

No network or real-world event inference. Reports below are deliberately
synthetic and include a weather-saturated input.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtWidgets import QApplication

from global_pulse.brief_selection import (
    BRIEF_DOMAINS, balanced_brief_sections, brief_domain, overview_html,
)
from global_pulse.core import build_brief
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def item(i, category, severity="unassessed", *, text=None):
    date=(datetime.now(timezone.utc)-timedelta(minutes=i+1)).isoformat()
    return {
        "id": "brief-fixture-%d" % i,
        "title": text or "SYNTHETIC %s report %d" % (category,i),
        "category": category, "severity":severity,
        "region":"Global","verification":"unverified",
        "status":"active", "updated_at":date, "published_at":date,
        "recap":"A synthetic source statement; underlying claims unverified.",
        "synthetic":True, "report_count":1,
        "reports":[{"id":f"report-{i}", "source_id":"fixture-publication",
                    "publisher":"QA Source", "title":text or "QA test title",
                    "url":f"https://example.org/news/{i}", "published_at":date,
                    "retrieved_at":date, "publication_time_known":True,
                    "independence":"unknown"}],
    }


def many_weather():
    flood=[item(i,"Disaster","critical") for i in range(140)]
    other=[
        item(201,"Conflict",text="SYNTHETIC contested security statement"),
        item(202,"Unrest",text="SYNTHETIC civic protest bulletin"),
        item(203,"Health",text="SYNTHETIC disease health advisory"),
        item(204,"Government",text="SYNTHETIC policy announcement"),
        item(205,"Economy",text="SYNTHETIC economic report"),
        item(206,"Humanitarian",text="SYNTHETIC relief operations bulletin"),
        item(207,"Infrastructure",text="SYNTHETIC aviation infrastructure advisory"),
        item(208,"News",text="SYNTHETIC general public information"),
    ]
    return flood+other


def test_priority_brief_includes_nonweather_in_weather_flood():
    sections=balanced_brief_sections(many_weather(),per_domain=2,
                                     max_total=18,disaster_limit=2)
    buckets=dict(sections)
    assert set(buckets)==set(BRIEF_DOMAINS)
    assert len(buckets["Weather & disasters"])==2
    assert all(len(buckets[k])==1 for k in BRIEF_DOMAINS
               if k!="Weather & disasters")
    assert brief_domain(item(300,"health"))=="Health & disease"
    assert brief_domain(item(301,"PROTEST"))=="Unrest & civil affairs"


def test_world_overview_writes_source_coverage_not_verified_global_claims():
    page=overview_html(many_weather(),label="7-day local feed")
    assert page.count("SYNTHETIC Disaster report")<=2
    for keyword in ("contested security statement","civic protest",
                    "disease health advisory","policy announcement",
                    "economic report","relief operations",
                    "aviation infrastructure","general public information"):
        assert keyword in page
    assert "World intelligence overview" in page
    assert "Unverified reports are not independently confirmed" in page
    assert "pulse-event://open/brief-fixture-201" in page
    assert "not that no conflict, disease, or emergency exists" in page.lower()


def test_unknown_and_missing_sections_are_coverage_gaps_not_no_crisis_claims():
    page=overview_html([item(1,"Disaster","critical")])
    assert "Coverage gap" in page
    assert "No matching category records in this feed" in page
    assert "not that no conflict" in page
    assert page.count("SYNTHETIC Disaster report")==1


def test_brief_does_not_assume_headline_claims_or_inject_html():
    records=[item(1,"Government",text="<script>alert(1)</script> & policy news")]
    page=overview_html(records)
    assert "<script>" not in page
    assert "&amp;" in page
    assert brief_domain(item(2,"News",text="WAR started!"))=="General news"


def test_daily_and_weekly_export_briefs_are_category_balanced():
    events=many_weather()
    for period in ("daily","weekly"):
        markdown=build_brief(events,period)
        assert "## Conflict & security" in markdown
        assert "## Health & disease" in markdown
        assert "## Government & politics" in markdown
        assert "## Weather & disasters" in markdown
        assert "SYNTHETIC disease health advisory" in markdown
        assert "SYNTHETIC contested security statement" in markdown
        assert markdown.count("SYNTHETIC Disaster report")<=6
        assert "Not represented in supplied local records" not in markdown


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(app,tmp_path):
    controller=Controller(tmp_path,demo=True)
    date=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
    items=[]
    for i,category in enumerate(("Disaster","Health","Government","Economy")):
        items.append({
            "id":f"brief-ui-{i}","event_key":f"brief-ui:{i}",
            "source_id":"qa-brief-test",
            "publisher":"QA Synthetic Publication",
            "title":f"SYNTHETIC {category} specific headline",
            "summary":"Inert source metadata for an offline UI test.",
            "url":f"https://example.org/brief/{i}",
            "published_at":date,"retrieved_at":date,
            "region":"Global","country":"","category":category,
            "severity":"unassessed","synthetic":True,
        })
    stored=controller.store.ingest(items)
    window=MainWindow(controller)
    window.show()
    app.processEvents()
    window.refresh_data()
    ids={r.get("category"):r["id"] for r in stored}
    yield window,controller,ids
    window._force_close=True
    window.close()
    controller.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_sidebar_opens_global_overview_not_first_weather_detail(desktop,app):
    window,controller,ids=desktop
    assert window.intelligence_mode.currentIndex()==0
    assert window.overview_browser.openLinks() is False
    overview=window.overview_browser.toPlainText()
    assert "World intelligence overview" in overview
    assert "Health & disease" in overview
    assert "Government & politics" in overview
    assert "Economy & business" in overview
    assert "SYNTHETIC Health specific headline" in overview
    assert window._selected_id  # Detail exists but isn't mislabeled as overview.
    assert "Selected event" in [window.intelligence_mode.itemText(i)
                                for i in range(window.intelligence_mode.count())]


def test_map_and_local_overview_links_switch_to_event_evidence(desktop,app):
    window,controller,ids=desktop
    identity=ids["Health"]
    window._open_overview_event(QUrl(
        "pulse-event://open/" + quote(identity,safe="")))
    assert window.intelligence_mode.currentIndex()==1
    assert window._selected_id==identity
    assert "Health specific headline" in window.intel_browser.toPlainText()
    window.intelligence_mode.setCurrentIndex(0)
    window.refresh_data()
    assert window.intelligence_mode.currentIndex()==0
    assert "Health & disease" in window.overview_browser.toPlainText()
    window.world_map.event_selected.emit(ids["Government"])
    assert window.intelligence_mode.currentIndex()==1
    assert window._selected_id==ids["Government"]


def test_external_or_unknown_overview_links_do_not_navigate(desktop):
    window,controller,ids=desktop
    selected=window._selected_id
    window._open_overview_event(QUrl("https://example.org/bad"))
    window._open_overview_event(QUrl("pulse-event://open/unavailable"))
    assert window._selected_id==selected
