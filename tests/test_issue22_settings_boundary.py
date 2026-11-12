"""Engineering settings regressions using local SQLite/Qt; no live services."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import socket
from datetime import datetime
import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller, in_quiet_hours
from global_pulse.core import Store
from global_pulse.settings_boundary import monitoring_interval, retention_days, user_feeds
from global_pulse.sources import make_user_feed, load_catalog

@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Settings tests must stay offline')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)

@pytest.mark.parametrize('bad', [None, [], {}, True, False, 600.5, 'invalid', '9' * 100])
def test_bad_numeric_settings_use_safe_defaults(bad):
    assert monitoring_interval(bad) == 600
    assert retention_days(bad) == 365

@pytest.mark.parametrize('value', [300, 600, 1800, 3600, '300', ' 3600 '])
def test_supported_intervals_preserved(value):
    assert monitoring_interval(value) == int(value)

@pytest.mark.parametrize(('value', 'expected'), [(0, 1), (-2, 1), (30, 30), ('365', 365), (5000, 3650)])
def test_retention_range_preserved(value, expected):
    assert retention_days(value) == expected

@pytest.mark.parametrize('enabled', ['false', 'true', 1, 0, None, [], {}])
def test_only_literal_true_enables_quiet_hours(enabled):
    assert not in_quiet_hours(dict(quiet_enabled=enabled, quiet_start='00:00', quiet_end='00:00'))

@pytest.mark.parametrize('bad', [None, [], {}, 700, '7:00', '07:0', '24:00', '00:60', '07:00 ', '０７:００'])
def test_bad_time_does_not_suppress_notifications(bad):
    assert not in_quiet_hours(dict(quiet_enabled=True, quiet_start=bad, quiet_end='00:00'))
    assert not in_quiet_hours(dict(quiet_enabled=True, quiet_start='00:00', quiet_end=bad))

@pytest.mark.parametrize(('hour', 'expected'), [(6, True), (7, False), (12, False), (22, True), (23, True)])
def test_overnight_boundaries(hour, expected):
    assert in_quiet_hours(dict(quiet_enabled=True, quiet_start='22:00', quiet_end='07:00'), datetime(2026, 11, 11, hour)) is expected

def test_daytime_and_all_day_windows():
    for hour in (0, 6, 12, 23):
        assert in_quiet_hours(dict(quiet_enabled=True, quiet_start='07:00', quiet_end='07:00'), datetime(2026, 11, 11, hour))
    assert in_quiet_hours(dict(quiet_enabled=True, quiet_start='09:00', quiet_end='17:00'), datetime(2026, 11, 11, 12))
    assert not in_quiet_hours(dict(quiet_enabled=True, quiet_start='09:00', quiet_end='17:00'), datetime(2026, 11, 11, 17))

@pytest.mark.parametrize('change', [dict(id=[]), dict(adapter=[]), dict(access_status={}), dict(allowed_domains=[None]), dict(url='https://127.0.0.1/feed'), dict(official=True), dict(metadata_only=False), dict(custom=False), dict(enabled='true'), dict(min_interval={}), dict(retention_days=[]), dict(status={}), dict(name=None)])
def test_bad_custom_records_do_not_gain_access(change):
    feed = make_user_feed('https://news.example.org/feed', 'Example', validate_dns=False)
    feed.update(change)
    assert user_feeds([feed]) == []

def test_valid_feed_keeps_values_and_does_not_alias_input():
    feed = make_user_feed('https://news.example.org/feed', 'Example', validate_dns=False)
    feed['enabled'] = False
    original = copy.deepcopy(feed)
    out = user_feeds([feed, 'legacy', {'name': 'broken'}, feed])
    assert out == [original]
    out[0]['allowed_domains'].append('other.example.org')
    assert feed == original
    blocked = dict(feed, access_status='review_required')
    assert user_feeds([blocked])[0]['access_status'] == 'review_required'

def test_bundled_identity_cannot_be_overridden_and_bound_preserved():
    feed = make_user_feed('https://news.example.org/feed', 'Example', validate_dns=False)
    assert user_feeds([feed], [feed['id']]) == []
    # The feature raises the explicit bound to512, not unlimited admission.
    assert user_feeds([feed], [str(i) for i in range(511)]) == [feed]
    assert user_feeds([feed], [str(i) for i in range(512)]) == []

def test_real_reopen_preserves_valid_feed_and_raw_invalid_preferences(tmp_path, app):
    valid = make_user_feed('https://news.example.org/feed', 'Example', validate_dns=False)
    raw = [None, {'name': 'broken'}, valid]
    store = Store(tmp_path / 'global-pulse.sqlite3', mode='live')
    store.set_setting('user_feeds', raw)
    store.set_setting('interval', {'legacy': 300})
    store.set_setting('retention_days', [])
    store.close()
    c = Controller(tmp_path)
    try:
        assert c.scheduler.interval == 600
        assert c.get_setting('retention_days') == 365
        assert c.catalog[-1] == valid
        assert c.store.get_setting('user_feeds') == raw
        assert c.store.get_setting('interval') == {'legacy': 300}
        c._prune_archive()
        assert c.store.get_setting('retention_days') == []
        assert not c.monitoring
    finally:
        c.close()

def test_feed_edit_after_invalid_storage_is_safe_and_no_dns(tmp_path, app):
    store = Store(tmp_path / 'global-pulse.sqlite3', mode='live')
    store.set_setting('user_feeds', True)
    store.close()
    c = Controller(tmp_path)
    try:
        c.add_user_feed('https://news.example.org/feed', 'Example')
        sid = c.catalog[-1]['id']
        assert c.catalog[-1]['access_status'] == 'user_supplied'
        c.remove_user_feed(sid)
        assert c.get_setting('user_feeds') == []
    finally:
        c.close()
