"""Offline source-to-map hazard markers and per-type visibility.
No live incident claim or provider request is made by these fictional fixtures.
"""
from datetime import datetime, timezone
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from global_pulse.core import Store, normalize_report
from global_pulse.hazards import (HAZARD_KEYS, canonical_hazard_types, event_hazard_types,
                                  report_hazard_types, text_hazard_types)
from global_pulse.hazard_icons import hazard_icon
from global_pulse.map_widget import WorldMap
from global_pulse.sources import parse_usgs, parse_eonet

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def world(app):
    w=WorldMap()
    w.resize(1600,700)
    w.show()
    app.processEvents()
    try:
        yield w
    finally:
        w.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()

def point(identity,kind,longitude,latitude=0):
    result=dict(id=identity,title="Fictional "+identity,category="Disaster" if kind else "Government",
                severity="moderate",verification="official",status="active",latitude=latitude,
                longitude=longitude,geo_precision="exact",synthetic=True)
    if kind:
        result["hazard_types"]=[kind]
    return result

def members(w):
    return {e["id"] for group in w.visible_clusters() for e,_ in group}

def test_each_hazard_has_distinct_marker_and_independent_toggle(world):
    rows=[point(kind,kind,-165+i*27) for i,kind in enumerate(HAZARD_KEYS)]
    rows.append(point("ordinary",None,164,50))
    world.set_events(rows)
    specs=world._visible_cluster_paint_specs()
    assert {s["hazard"] for s in specs if s["hazard"]}==set(HAZARD_KEYS)
    assert all(not hazard_icon(kind).isNull() for kind in HAZARD_KEYS)
    world.grab()
    assert members(world)=={row["id"] for row in rows}
    world.set_hazard_layer("earthquake",False)
    assert "earthquake" not in members(world)
    assert "cyclone" in members(world) and "ordinary" in members(world)
    assert "12 points" in world._footer_coverage_text()
    world.grab()
    assert not any(e["id"]=="earthquake" for _,_,group in world._hits for e,_ in group)
    world.set_hazards_enabled(False)
    assert members(world)=={"ordinary"}
    world.set_hazards_enabled(True)
    assert "earthquake" not in members(world)
    assert "cyclone" in members(world)
    world.reset_hazard_layers()
    assert len(members(world))==len(rows)

def test_mixed_clusters_never_mislabel_other_types(world):
    rows=[point("quake","earthquake",20),point("hurricane","cyclone",20)]
    world.set_events(rows)
    specs=world._visible_cluster_paint_specs()
    assert len(specs)==1 and specs[0]["size"]==2 and not specs[0]["hazard"]
    assert "Earthquakes" in world.cluster_tooltip(specs[0]["group"])
    assert "Hurricanes" in world.cluster_tooltip(specs[0]["group"])
    world.set_hazard_layer("earthquake",False)
    assert world._visible_cluster_paint_specs()[0]["hazard"]=="cyclone"

def test_warning_toggle_preserves_geometry_and_hides_hit_target(world):
    area={"geometry":{"type":"Polygon","coordinates":[[[10,10],[15,10],[15,15],[10,15],[10,10]]]},
          "source_id":"nws","report_id":"warn","description":"Fictional flood warning"}
    event={"id":"warning","title":"Fictional flood warning","status":"active",
           "category":"Disaster","severity":"high","hazard_types":["flood"],"map_areas":[area]}
    world.set_events([],country_events=[event])
    assert not world.visible_clusters()
    assert len(world.area_layer.visible())==1
    position=world.point(12,12)
    assert world.area_layer.hit(position)[0]["id"]=="warning"
    world.set_hazard_layer("flood",False)
    assert not world.area_layer.visible() and world.area_layer.hit(position) is None
    assert world.area_layer.paths[0][2]["geometry"]==area["geometry"]
    world.set_hazard_layer("flood",True)
    assert len(world.area_layer.visible())==1

def test_saved_preferences_round_trip_and_ignore_unknown_keys(world):
    world.set_hazard_layer("earthquake",False)
    world.set_hazard_layer("flood",False)
    world.set_hazards_enabled(False)
    state=world.view_state()
    world.reset_hazard_layers()
    world.restore_view(state)
    assert not world.hazards_enabled and not world.hazard_layers["earthquake"]
    assert not world.hazard_layers["flood"] and world.hazard_layers["cyclone"]
    world.restore_view({"hazard_layers":{"unknown":False,"earthquake":"false"}})
    assert world.hazards_enabled and set(world.hazard_layers)==set(HAZARD_KEYS)
    assert all(world.hazard_layers.values())
    with pytest.raises(ValueError):
        world.set_hazard_layer("unknown",False)

def test_classification_does_not_use_unrelated_news_or_inactive_reports():
    assert not report_hazard_types({"title":"Hurricane preparedness bill","category":"Government"})
    assert report_hazard_types({"title":"M 6.3 - offshore","category":"Disaster","source_id":"usgs"})==("earthquake",)
    assert report_hazard_types({"title":"M 4.8 quarry blast","category":"Disaster","source_id":"usgs"})==("other",)
    assert report_hazard_types({"title":"Regional update","category":"Disaster","source_id":"gdacs",
                                "event_key":"gdacs:TC:fixture"})==("cyclone",)
    assert text_hazard_types("Tropical Storm Warning")==("cyclone",)
    assert not canonical_hazard_types([{"a":1},"invented",3])
    event={"title":"Old earthquake","category":"Disaster","hazard_types":["earthquake"],
           "reports":[{"title":"Old earthquake","category":"Disaster","evidence_status":"retracted"}]}
    assert event_hazard_types(event)==()
    event["reports"].append({"title":"Flood warning","category":"Disaster","evidence_status":"active"})
    assert event_hazard_types(event)==("flood",)

def test_source_metadata_survives_normalization_and_compact_map_projection(tmp_path):
    stamp=datetime.now(timezone.utc).isoformat()
    source={"id":"usgs","name":"Fictional USGS adapter fixture","category":"Disaster",
            "url":"https://earthquake.usgs.gov/","article_domains":["earthquake.usgs.gov"],
            "independence":"original"}
    payload={"type":"FeatureCollection","features":[
        {"id":"fictional-1","geometry":{"type":"Point","coordinates":[20,30,12]},
         "properties":{"type":"earthquake","title":"M 5.0 — fictional offshore","time":stamp,
                       "mag":5.0,"url":"https://earthquake.usgs.gov/fictional-1"}},
        {"id":"fictional-2","geometry":{"type":"Point","coordinates":[30,40,12]},
         "properties":{"type":"quarry blast","title":"M 4.5 — fictional blast","time":stamp,
                       "mag":4.5,"url":"https://earthquake.usgs.gov/fictional-2"}}]}
    rows=parse_usgs(payload,source,stamp)
    assert [row["hazard_types"] for row in rows]==[["earthquake"],["other"]]
    assert normalize_report(dict(rows[0],hazard_types=["earthquake","bad"]),now=stamp)["hazard_types"]==["earthquake"]
    with Store(tmp_path/"hazards.sqlite3",mode="live") as store:
        assert len(store.ingest(rows,now=stamp))==2
        points=store.list_events(map_view=True)
        assert len(points)==2
        assert {tuple(r["hazard_types"]) for r in points}=={("earthquake",),("other",)}
        assert all("reports" not in r for r in points)
        assert {(r["longitude"],r["latitude"]) for r in points}=={(20,30),(30,40)}
    eonet=dict(source,id="eonet",name="Fictional EONET fixture",url="https://eonet.gsfc.nasa.gov/",
               article_domains=["eonet.gsfc.nasa.gov"])
    event={"id":"fictional-storm","title":"Fictional Hurricane Sample",
           "categories":[{"id":"severeStorms","title":"Severe Storms"}],
           "link":"https://eonet.gsfc.nasa.gov/fixture",
           "geometry":[{"type":"Point","coordinates":[-30,20],"date":stamp}]}
    assert parse_eonet({"events":[event]},eonet,stamp)[0]["hazard_types"]==["cyclone"]

def test_window_menu_has_all_controls_and_does_not_change_news_scope(app,tmp_path):
    from global_pulse.controller import Controller
    from global_pulse.ui import MainWindow
    ctl=Controller(tmp_path,demo=True)
    w=MainWindow(ctl)
    try:
        scope=w._archive_scope_key()
        assert set(w.hazard_actions)==set(HAZARD_KEYS)
        assert w.hazard_master.isChecked()
        w.hazard_actions["earthquake"].setChecked(False)
        assert "earthquake" in w.world_map.disabled_hazards()
        assert w._archive_scope_key()==scope
        assert w.hazard_actions["cyclone"].isChecked()
        w.hazard_master.setChecked(False)
        assert not w.hazard_actions["cyclone"].isEnabled()
        w.hazard_master.setChecked(True)
        assert not w.hazard_actions["earthquake"].isChecked()
    finally:
        w._force_close=True
        for timer in (w._filter_refresh_timer,w._workspace_warm_timer,w._evidence_refresh_timer,
                      w._collection_refresh_timer,w.search_timer):
            timer.stop()
        w.media.shutdown()
        w.close()
        ctl.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
