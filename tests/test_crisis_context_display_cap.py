"""Regression for owner-reported News/All crisis stripe loss.

Only fictional locally ingested source-shaped reports. No live geopolitical
assertion, network operation, or inference from publisher geography.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QListWidget

from global_pulse.core import Store
from global_pulse.crisis_overlay import build_country_activity, load_crisis_context, normalize_country
from global_pulse import map_widget


def report(identity, title, category, stamp, *, country="Ukraine",
           region="Europe", official=True, origin=None):
    return {
        "id": identity, "event_key": "crisis-cap:"+identity,
        "source_id": origin or "fixture-"+identity,
        "publisher": "FICTIONAL offline source", "origin_id": origin or "fixture-"+identity,
        "independence": "original", "kind": "report",
        "title": title, "summary": "Offline regression only",
        "url": "https://example.invalid/crisis-cap/"+identity,
        "published_at": stamp, "retrieved_at": stamp, "publication_time_known": True,
        "country": country, "country_basis": "provider_incident",
        "region": region, "category": category, "official": official,
        "severity": "informational", "synthetic": False,
    }


@pytest.fixture
def archive(tmp_path):
    now=datetime.now(timezone.utc)
    old=(now-timedelta(hours=3)).isoformat()
    recent=(now-timedelta(hours=1)).isoformat()
    with Store(tmp_path/"crisis-context.sqlite3", mode="live") as store:
        # Source evidence is deliberately older than the large ordinary page.
        # Use a small display cap in the fixture; production uses 5,000.
        source=[
            report("news","FICTIONAL armed conflict report in Ukraine","News",old),
            report("conflict","FICTIONAL shelling report in Sudan","Conflict",old,
                   country="Sudan",region="Africa"),
            report("stale","FICTIONAL armed conflict in France","News",
                   (now-timedelta(days=30)).isoformat(),country="France"),
        ]
        for row in source:
            assert store.ingest([row], now=row["published_at"])
        flood=[report("economy-"+str(i),f"FICTIONAL quarterly cereal output measure {i}",
                      "Economy",recent,country="Germany") for i in range(20)]
        assert len(store.ingest(flood,now=recent))==20
        yield store,now


def test_independent_context_survives_ordinary_page_cap_and_news_filter(archive):
    store,now=archive
    filters={"limit":3,"map_view":True,"map_evidence":True,
             "since":(now-timedelta(days=7)).isoformat(),"keep_significant":True}
    ordinary=store.list_events(**filters)
    news_filters=dict(filters,category="News")
    news=store.list_events(**news_filters)
    assert len(ordinary)==3 and {row["category"] for row in ordinary}=={"Economy"}
    assert build_country_activity(ordinary,now=now)=={}
    assert len(news)==1 and news[0]["category"]=="News"

    all_context=load_crisis_context(store,filters,ordinary,now=now)
    news_context=load_crisis_context(store,news_filters,news,now=now)
    assert len(all_context)==len(news_context)==2
    expected=build_country_activity(all_context,now=now)
    assert expected==build_country_activity(news_context,now=now)
    assert set(expected)=={normalize_country("Ukraine"),normalize_country("Sudan")}
    assert all(row["conflict"]>0 for row in expected.values())
    # The normal source row retains exact identity for neutral-ring credits.
    assert any(row is news[0] for row in news_context)
    assert len(store.list_crisis_context(now=now,limit=1))==1
    assert all(row["category"]!="Economy" for row in all_context)


def test_context_respects_region_and_does_not_query_current_during_replay(archive):
    store,now=archive
    filters={"limit":3,"map_view":True,"map_evidence":True,
             "category":"Economy","region":"Europe"}
    ordinary=store.list_events(**filters)
    context=load_crisis_context(store,filters,ordinary,now=now)
    assert set(build_country_activity(context,now=now))=={normalize_country("Ukraine")}
    dummy=Mock()
    assert load_crisis_context(dummy,dict(filters,before=now.isoformat()),ordinary,now=now) is None
    dummy.list_crisis_context.assert_not_called()
    full=store.list_events(map_evidence=True,limit=100)
    assert load_crisis_context(dummy,{"limit":100},full,now=now) is full
    dummy.list_crisis_context.assert_not_called()


def test_independent_stripes_preserve_separate_category_rings_and_clickable_sources(archive,monkeypatch):
    store,now=archive
    app=QApplication.instance() or QApplication([])
    world=map_widget.WorldMap()
    filters={"limit":3,"map_view":True,"map_evidence":True}
    ordinary=store.list_events(**filters)
    context=load_crisis_context(store,filters,ordinary,now=now)
    credits=set()
    classified=build_country_activity(context,now=now,single_record_credits=credits)
    country_rows=tuple({"name":str(c["name"]),"code":str(c.get("code") or "")} for c in world._countries)
    prepared={
        "category_key":None,"record_ids":tuple(id(row) for row in ordinary),
        "crisis_record_ids":tuple(id(row) for row in context),
        "activity":classified,"credits":credits,"country_rows":country_rows,
        "observation_ids":(),
        "evidence_index":map_widget.prepare_country_evidence(ordinary,[],country_rows,credits,None),
    }
    classifier=Mock(side_effect=AssertionError("Current prepared context reclassified on GUI"))
    monkeypatch.setattr(map_widget,"build_country_activity",classifier)
    try:
        world.set_events([],country_events=ordinary,crisis_events=context,preclassified_country=prepared)
        assert world.country_activity==classified
        assert not world.country_category_evidence_for("Sudan")
        world.categories={"Health"}
        assert world.country_activity_for("Sudan")["conflict"]>0
        assert not world.country_category_evidence_for("Germany")
        classifier.assert_not_called()
        assert world.show_country_evidence("Sudan",activity_context=True)
        listing=world.country_dialog.findChild(QListWidget,"country_evidence_results")
        assert listing.count()==1
        identity=listing.item(0).data(Qt.ItemDataRole.UserRole)
        assert identity in classified[normalize_country("Sudan")]["event_ids"]
        assert store.get_event(identity)["reports"][0]["official"]
    finally:
        if world.country_dialog is not None:
            world.country_dialog.close()
        world.close()
        world.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
