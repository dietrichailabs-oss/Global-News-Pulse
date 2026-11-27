"""Complete 5k source inventory with bounded navigable Qt presentation."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from datetime import datetime,timezone,timedelta
from urllib.parse import quote
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication,QEvent,QUrl
from PySide6.QtWidgets import QApplication
from global_pulse.brief_selection import overview_documents,overview_html,critical_alerts,OVERVIEW_ALERT_PAGE_SIZE
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow
from test_r20_daily_brief_depth import item


def records(n=5000):
    now=datetime.now(timezone.utc).isoformat()
    return [item(i,"Disaster",severity="critical",updated_at=now) for i in range(n)] + [
        item(n+1,"Health",severity="high",title="FICTIONAL further health assessment")]


def test_complete_paginated_inventory_matches_full_critical_order_and_links():
    rows=records()
    docs=overview_documents(rows,label="offline test")
    full=overview_html(rows,label="offline test")
    assert docs["full"]==full
    expected=tuple(str(e["id"]) for e in critical_alerts(rows))
    assert len(expected)==5000
    pages=docs["pages"]
    assert len(pages)==51
    assert tuple(identity for _,ids,_ in pages for identity in ids)==expected
    for page,ids,caption in pages[:-1]:
        assert len(ids)<=OVERVIEW_ALERT_PAGE_SIZE
        assert page.count("pulse-event://open/")==len(ids)
        assert all("pulse-event://open/"+quote(identity,safe="")+"'" in page for identity in ids)
        assert "FICTIONAL further health assessment" not in page
    assert "FICTIONAL further health assessment" in pages[-1][0]
    assert pages[-1][2]=="Further assessments"
    assert full.count("pulse-event://open/")==5001
    small=overview_documents(records(3))
    assert len(small["pages"])==1 and small["pages"][0][0]==small["full"]


def test_real_qt_page_navigation_and_scope_change_keep_exact_event_links(tmp_path):
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    w=None
    try:
        w=MainWindow(ctl)
        w.show()
        rows=records(230)
        w._overview_events=rows
        w._update_world_overview(documents=overview_documents(rows))
        app.processEvents()
        assert w.overview_navigation.isVisible()
        assert w.overview_page_number.maximum()==4
        assert len(w._overview_pages[0][1])==100
        assert len(w._overview_visible_html)<len(w._overview_html_cached)
        assert not w.overview_previous.isEnabled()
        w.overview_page_number.setValue(3)
        assert w._overview_page_index==2
        identity=w._overview_pages[2][1][0]
        with patch.object(w,"navigate_event") as navigate:
            w._open_overview_event(QUrl("pulse-event://open/"+quote(identity,safe="")))
            navigate.assert_called_once_with(identity)
        w.intelligence_mode.setCurrentIndex(0)
        w.overview_assessments.click()
        assert "FICTIONAL further health assessment" in w.overview_browser.toPlainText()
        assert not w.overview_next.isEnabled()
        w.overview_page_number.setValue(2)
        anchor=w._overview_pages[1][1][0]
        fresh=item(99999,"Disaster",severity="critical",
                   updated_at=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat())
        w._overview_events=[fresh]+rows
        w._update_world_overview(documents=overview_documents(w._overview_events))
        assert anchor in w._overview_pages[w._overview_page_index][1]
        # Exact filtered scope switch discards stale page controls and links.
        w.category.addItem("Health","Health")
        w.category.setCurrentIndex(w.category.findData("Health"))
        w._overview_events=[rows[-1]]
        w._update_world_overview(documents=overview_documents(w._overview_events))
        assert w._overview_page_index==0
        assert w.overview_navigation.isHidden()
        assert "FICTIONAL further health assessment" in w.overview_browser.toPlainText()
        with patch.object(w,"navigate_event") as navigate:
            w._open_overview_event(QUrl("pulse-event://open/"+quote(identity,safe="")))
            navigate.assert_not_called()
    finally:
        if w is not None:
            w._force_close=True
            for name in ("_filter_refresh_timer","_workspace_warm_timer","_evidence_refresh_timer",
                         "_collection_refresh_timer","search_timer","_brief_clock_timer"):
                getattr(w,name).stop()
            w.media.shutdown();w.close();w.deleteLater()
        ctl.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
