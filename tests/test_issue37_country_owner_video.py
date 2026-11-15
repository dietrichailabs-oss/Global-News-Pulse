"""Issue37: search country archive beyond first 30 and test owner video ID.

All geo records are synthetic and explicitly country attributed. No network.
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QPushButton

from global_pulse.map_widget import WorldMap
from global_pulse.single_media import Television
from global_pulse.media_widget import youtube_id


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_us_archive_searches_beyond_first_thirty_without_fake_points(app):
    world=WorldMap()
    now=datetime.now(timezone.utc).isoformat()
    records=[]
    for index in range(45):
        title=("FAA nationwide aircraft ground stop" if index==44
               else f"Storm warning number {index}")
        category="Government" if index==44 else "Disaster"
        records.append({
            "id":f"sample-{index}", "title":title, "category":category,
            "country":"United States of America",
            "country_basis":"provider_incident", "synthetic":False,
            "status":"active", "map_areas":[],
            "latitude":None,"longitude":None,
            "reports":[{"id":f"report-{index}","title":title,
                        "source_id":"synthetic-offline-faa" if index==44 else "synthetic-nws",
                        "country":"United States of America",
                        "country_basis":"provider_incident",
                        "published_at":now,"publication_time_known":True,
                        "category":category,"evidence_status":"active"}],
        })
    try:
        world.set_events([],country_events=records)
        entry=world.country_evidence_for("United States of America")
        assert entry["count"]==45
        assert len(entry["events"])==45
        assert world.show_country_evidence("United States of America")
        dialog=world.country_dialog
        search=dialog.findChild(QLineEdit,"country_evidence_search")
        listing=dialog.findChild(QListWidget,"country_evidence_results")
        assert search is not None and listing is not None
        assert listing.count()==30
        search.setText("FAA")
        assert listing.count()==1
        assert "ground stop" in listing.item(0).text()
        assert "sample-44"==listing.item(0).data(Qt.ItemDataRole.UserRole)
        search.setText("never-seen")
        assert listing.count()==0
        results=[]
        world.global_search_requested.connect(results.append)
        search.setText("ground stop")
        global_button=dialog.findChild(QPushButton,"country_search_full_archive")
        assert global_button is not None
        global_button.click()
        assert results==["ground stop"]
        # Neither map clicks nor the search manufactured precise US coordinates.
        assert world.coverage_summary().startswith("0 points")
    finally:
        if world.country_dialog:
            world.country_dialog.close()
        world.close()
        world.deleteLater()
        app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_owner_exact_youtube_video_is_opt_in_unverified(app,monkeypatch):
    tv=Television()
    calls=[]
    try:
        monkeypatch.setattr(tv,"watch",lambda:calls.append("watch"))
        assert tv.test_owner_video() is True
        assert calls==["watch"]
        assert youtube_id(tv._current()["url"])=="b0ZhJhN_Sn8"
        assert "LIVE" not in tv.tv_status.text()
        assert "unverified" in tv.tv_status.text().lower()
        assert tv.test_owner_video() is True
        assert len([tv.selector.itemData(index)
                    for index in range(tv.selector.count())
                    if youtube_id((tv.selector.itemData(index) or {}).get("url",""))=="b0ZhJhN_Sn8"])==1
    finally:
        tv.stop()
        tv.deleteLater()
        app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
