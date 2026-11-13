"""Issue #22: execute production Store, NWS parser, Qt map and desktop wiring.

Offline explicitly labeled fixtures in temporary stores. Not a live alert or
owner/Windows-client observation. No network or media sessions are started.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from datetime import datetime, timedelta, timezone
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from global_pulse.core import Store
from global_pulse.sources import load_catalog, parse_feed, parse_nws
from global_pulse.map_widget import WorldMap
from global_pulse.crisis_overlay import build_country_activity
from global_pulse.map_evidence import incident_country

APP = None


def instant(delta=0):
    return (datetime.now(timezone.utc) + timedelta(hours=delta)).isoformat(timespec='seconds').replace('+00:00', 'Z')


def country_report(**overrides):
    value = {'id': 'fixture-country', 'source_id': 'fixture-official', 'publisher': 'ISOLATED TEST FIXTURE',
             'url': 'https://example.org/fixture-country', 'title': 'TEST FIXTURE: armed conflict in Ukraine',
             'summary': 'Inert test, not reporting.', 'published_at': instant(-1), 'retrieved_at': instant(),
             'country': 'Ukraine', 'region': 'Europe', 'category': 'Conflict', 'official': True,
             'country_basis': 'provider_incident', 'severity': 'high'}
    value.update(overrides)
    return value


@pytest.fixture(scope='module')
def app():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


@pytest.fixture
def world(app):
    widget = WorldMap()
    widget.resize(1000, 500)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def warning(geometry=True, expires=None):
    shape = {'type': 'Polygon', 'coordinates': [[[-170, 70], [-150, 70], [-150, 76], [-170, 76], [-170, 70]]]}
    properties = {'id': 'https://api.weather.gov/alerts/fixture-alaska', 'status': 'Actual',
        'messageType': 'Alert', 'sender': 'fixture@weather.gov', 'event': 'Heavy Freezing Spray Warning',
        'headline': 'TEST FIXTURE: offshore warning, not a live bulletin', 'description': 'Isolated fixture.',
        'areaDesc': 'TEST offshore area', 'severity': 'Severe', 'sent': instant(-1),
        'onset': instant(-1), 'effective': instant(-1), 'expires': expires or instant(1), 'ends': instant(2),
        'affectedZones': ['https://api.weather.gov/zones/forecast/PKZ859'], 'geocode': {'UGC': ['PKZ859']}}
    source = next(row for row in load_catalog() if row['id'] == 'nws')
    return parse_nws({'features': [{'type': 'Feature', 'geometry': shape if geometry else None, 'properties': properties}]}, source, instant())[0]


def test_country_only_reaches_actual_map_but_never_becomes_point(tmp_path, world):
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        store.ingest([country_report()])
        points = store.list_events(map_view=True)
        evidence = store.list_events(map_evidence=True)
        assert points == [] and len(evidence) == 1
        world.set_events(points, country_events=evidence)
        assert world.country_activity_for('Ukraine')['conflict'] == 1
        assert world.visible_clusters() == []
        assert '1 countries with activity' in world.coverage_summary()


def test_evidence_queries_keep_explicit_filters_and_historical_boundaries(tmp_path):
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        when = instant()
        store.ingest([country_report()], now=when)
        assert len(store.list_events(map_evidence=True, category='Conflict', region='Europe')) == 1
        assert not store.list_events(map_evidence=True, category='Economy')
        assert not store.list_events(map_evidence=True, region='Asia')
        assert len(store.list_events(map_evidence=True, before=when)) == 1
        assert not store.list_events(map_view=True, before=when)


def test_source_freshness_rule_is_not_relaxed(tmp_path, world):
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        store.ingest([country_report(published_at=instant(-24*30))])
        world.set_events([], country_events=store.list_events(map_evidence=True))
        assert not world.country_activity_for('Ukraine')


def test_map_layers_apply_to_country_evidence(tmp_path, world):
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        store.ingest([country_report()])
        world.set_events([], country_events=store.list_events(map_evidence=True))
        world.categories = {'Economy'}
        assert not world.country_activity_for('Ukraine')
        world.categories = {'Conflict'}
        assert world.country_activity_for('Ukraine')['conflict'] == 1


def test_publisher_scope_and_legacy_catalog_default_cannot_create_stripes(tmp_path):
    source = next(row for row in load_catalog() if row['id'] == 'fcdo')
    feed = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>fixture</id>'
            '<title>TEST: statement about armed conflict</title><link href="https://www.gov.uk/fixture"/>'
            '<published>'+instant(-1)+'</published></entry></feed>').encode()
    raw = parse_feed(feed, source, instant())[0]
    assert raw['country_basis'] == 'publisher_coverage'
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        event = store.ingest([raw])[0]
        assert not incident_country(event)
        assert not build_country_activity([event])
    legacy = {'country': 'United Kingdom', 'reports': [{'source_id': 'fcdo', 'country': 'United Kingdom'}]}
    assert not incident_country(legacy)


def test_nws_polygon_survives_parser_store_and_clickable_map(tmp_path, world, app):
    raw = warning()
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        store.ingest([raw])
        evidence = store.list_events(map_evidence=True)
        assert len(evidence) == 1 and not store.list_events(map_view=True)
        report = evidence[0]['reports'][0]
        assert report['area_geometry'] == raw['area_geometry']
        assert report['affected_zones'] == raw['affected_zones']
        assert report['ends_at'] != report['expires_at']
        assert report['onset_at'] == raw['onset_at']
        world.set_events([], country_events=evidence)
        assert len(world.area_layer.paths) == 1
        assert world.area_layer.hit(world.point(-160, 73))[0]['id'] == evidence[0]['id']
        assert not world.area_layer.hit(world.point(0, 0))
        received = []
        world.event_selected.connect(received.append)
        world.repaint()
        app.processEvents()
        QTest.mouseClick(world, Qt.MouseButton.LeftButton, pos=world.point(-160, 73).toPoint())
        assert received == [evidence[0]['id']]
        assert '1 warning areas' in world.coverage_summary()


def test_dateline_shape_draws_at_edges_not_across_world(world):
    geometry = {'type': 'Polygon', 'coordinates': [[[170,65],[-170,65],[-170,75],[170,75],[170,65]]]}
    event = {'id': 'dateline-fixture', 'status': 'active', 'category': 'Disaster', 'map_areas': [{'geometry': geometry}]}
    world.set_events([], country_events=[event])
    assert world.area_layer.hit(world.point(179,70))
    assert world.area_layer.hit(world.point(-179,70))
    assert not world.area_layer.hit(world.point(0,70))
    world.categories = {'Economy'}
    assert not world.area_layer.hit(world.point(179,70))


def test_zone_only_warning_is_preserved_without_fake_alaska_pin(tmp_path, world):
    raw = warning(geometry=False)
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        store.ingest([raw])
        evidence = store.list_events(map_evidence=True)
        assert evidence[0]['reports'][0]['area_status'] == 'zone_geometry_not_resolved'
        assert not evidence[0]['map_areas']
        assert evidence[0]['latitude'] is None
        world.set_events([], country_events=evidence)
        assert not world.area_layer.paths


def test_expired_bulletin_is_not_reactivated_by_later_hazard_end(tmp_path):
    with Store(tmp_path/'isolated.sqlite3', mode='live') as store:
        event = store.ingest([warning(expires=instant(-0.5))])[0]
        assert event['status'] == 'expired'
        assert event['reports'][0]['ends_at'] > instant()
        assert not event['map_areas'] and not store.list_events(map_evidence=True)


def test_empty_coverage_explains_unknown_instead_of_no_crises(world):
    assert 'does not mean' in world.empty_coverage_message()
    world.set_events([], country_events=[{'id':'unknown','category':'News','country':'','reports':[]}])
    assert 'Reports collected' in world.empty_coverage_message()
    assert '1 unlocated' in world.coverage_summary()


def test_real_desktop_refresh_passes_country_evidence_separately(tmp_path, app):
    from global_pulse.controller import Controller
    from global_pulse.ui import MainWindow
    controller = Controller(tmp_path, demo=False)
    window = None
    try:
        controller.store.ingest([country_report()])
        window = MainWindow(controller)
        window.refresh_data()
        assert not controller.monitoring
        assert not window.world_map.events
        assert window.world_map.country_activity_for('Ukraine')['conflict'] == 1
        assert '1 countries with activity' in window.count_label.text()
    finally:
        if window is not None:
            window._force_close = True
            window.close()
            window.deleteLater()
        controller.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

def test_official_point_marker_is_a_circle_without_a_square_box(world, app):
    """Owner request: remove the rectangle around circular official pins.

    Compare the exact already-painted ocean background at four diagonal
    corners. The old official drawRect changes those corners; the circular
    outer ring cannot touch them. This is rendered Qt output, not a source
    grep or a claim of real-world point-location evidence.
    """
    world.set_events([])
    world.repaint()
    baseline = world.grab().toImage()
    point = world.point(0.0, 0.0)  # Inert test coordinate, not a claimed incident.
    marker = {
        "id": "synthetic-official-pin",
        "title": "Synthetic visual marker fixture",
        "latitude": 0.0,
        "longitude": 0.0,
        "verification": "official",
        "severity": "high",
        "category": "Disaster",
        "synthetic": True,
    }
    world.set_events([marker])
    world.repaint()
    app.processEvents()
    rendered = world.grab().toImage()
    x, y = round(point.x()), round(point.y())
    assert rendered.pixelColor(x, y).rgba() != baseline.pixelColor(x, y).rgba()
    for sign_x in (-1, 1):
        for sign_y in (-1, 1):
            for offset_x in (-1, 0, 1):
                for offset_y in (-1, 0, 1):
                    px = x + sign_x * 9 + offset_x
                    py = y + sign_y * 9 + offset_y
                    assert rendered.pixelColor(px, py).rgba() == baseline.pixelColor(px, py).rgba()
