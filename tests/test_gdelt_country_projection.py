"""Engineering: real cached EXPORT -> read-only country display, offline."""
from datetime import datetime,timezone
import socket
import sqlite3
import pytest
from global_pulse.core import Store
from global_pulse.gdelt_batches import GdeltBatchCache
from global_pulse.gdelt_map_data import project,read_archive,normalize_country
from test_gdelt_batch_cache import event_row,payload,batch_from_archive

NOW=datetime(2026,11,11,12,tzinfo=timezone.utc)
NAMES=['Ukraine','Iran','Germany','Gabon','China','Switzerland','United States of America','United Kingdom']

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('No network allowed for cached GDELT display')
    monkeypatch.setattr(socket,'getaddrinfo',denied);monkeypatch.setattr(socket.socket,'connect',denied)

@pytest.fixture
def archive(tmp_path):
    path=tmp_path/'global-pulse.sqlite3'
    with Store(path):pass
    return path


def seed(path,rows):
    data=payload(rows);batch=batch_from_archive(data)
    with GdeltBatchCache(path) as cache:
        result=cache.import_export(batch,data,now='2026-11-11T08:05:00+00:00')
        assert result['status']=='complete'


@pytest.mark.parametrize('code,name',[('UP','Ukraine'),('IR','Iran'),('GM','Germany'),('GB','Gabon'),('CH','China'),('SZ','Switzerland'),('US','United States of America'),('UK','United Kingdom')])
def test_explicit_fips_codes_not_iso_or_provider_coordinates(archive,code,name):
    seed(archive,[event_row(country=code)])
    result=read_archive(archive,NAMES,now=NOW)
    assert result['state']=='ready' and result['countries'][normalize_country(name)]['count']==1
    record=result['records'][0]
    assert record['country']==name and record['fips']==code
    assert not {'latitude','longitude','severity','verification','reports'} & record.keys()


def test_coded_material_conflict_and_protest_counts_remain_explicitly_unverified(archive):
    seed(archive,[event_row('2001',country='UP'),event_row('2002',country='IR')])
    with sqlite3.connect(archive) as c:
        c.execute("UPDATE gdelt_event_rows SET event_code='190',quad_class='4' WHERE global_event_id='2001'")
        c.execute("UPDATE gdelt_event_rows SET event_code='141',quad_class='3' WHERE global_event_id='2002'")
    result=read_archive(archive,NAMES,now=NOW)
    assert result['countries']['ukraine']['material_conflict']==1
    assert result['countries']['ukraine']['protest']==0
    assert result['countries']['iran']['material_conflict']==0
    assert result['countries']['iran']['protest']==1
    assert all('severity' not in record and 'verification' not in record for record in result['records'])


def test_exact_reopen_projection_does_not_mutate_source_evidence(archive):
    seed(archive,[event_row('1001',country='UP'),event_row('1002',country='IR')])
    with sqlite3.connect(archive) as connection:before='\n'.join(connection.iterdump())
    first=read_archive(archive,NAMES,now=NOW)
    second=read_archive(archive,NAMES,now=NOW)
    with sqlite3.connect(archive) as connection:after='\n'.join(connection.iterdump())
    assert first==second and len(first['countries'])==2 and before==after
    with Store(archive) as store:
        assert store.list_events()==[]
        assert store.stats()['reports']==0


@pytest.mark.parametrize('code',['XX','GV','LO'])
def test_unknown_and_conflicting_country_lookup_entries_stay_unlocated(archive,code):
    seed(archive,[event_row(country=code)])
    result=read_archive(archive,NAMES,now=NOW)
    assert result['unmapped']==1 and not result['countries']
    assert result['records'][0]['country']==''


@pytest.mark.parametrize('field,value',[('event_day','20200101'),('event_day','20261112'),('date_added','20261112120000'),('event_day','20261100')])
def test_stale_future_or_invalid_rows_not_promoted_to_current(archive,field,value):
    seed(archive,[event_row(country='UP')])
    with sqlite3.connect(archive) as c:c.execute('UPDATE gdelt_event_rows SET '+field+'=?',(value,))
    result=read_archive(archive,NAMES,now=NOW)
    assert not result['countries'] and not result['records']


def test_provider_quarter_hour_label_may_lead_wall_clock_by_one_interval(archive):
    stamp='20261111121500'
    data=payload([event_row(day='20261111',date_added=stamp,country='UP')],stamp=stamp)
    batch=batch_from_archive(data,stamp=stamp)
    with GdeltBatchCache(archive) as cache:
        assert cache.import_export(batch,data,now='2026-11-11T12:05:00+00:00')['status']=='complete'
    result=read_archive(archive,NAMES,now='2026-11-11T12:05:00Z')
    assert result['countries']['ukraine']['count']==1


def test_provider_label_more_than_one_interval_ahead_stays_hidden(archive):
    stamp='20261111123000'
    data=payload([event_row(day='20261111',date_added=stamp,country='UP')],stamp=stamp)
    batch=batch_from_archive(data,stamp=stamp)
    with GdeltBatchCache(archive) as cache:
        assert cache.import_export(batch,data,now='2026-11-11T12:05:00+00:00')['status']=='complete'
    result=read_archive(archive,NAMES,now='2026-11-11T12:05:00Z')
    assert not result['records']


def test_noncompleted_batch_has_no_display_authority(archive):
    seed(archive,[event_row(country='UP')])
    with sqlite3.connect(archive) as c:c.execute("UPDATE gdelt_batches SET status='failed'")
    assert not read_archive(archive,NAMES,now=NOW)['records']


def test_future_import_is_not_current_evidence(archive):
    seed(archive,[event_row(country='UP')])
    with sqlite3.connect(archive) as c:c.execute("UPDATE gdelt_batches SET imported_at='2026-11-12T00:00:00Z'")
    result=read_archive(archive,NAMES,now=NOW)
    assert result['invalid']==1 and not result['countries']


def test_untrusted_article_scheme_or_credentials_never_exposed_as_openable(archive):
    seed(archive,[event_row(country='UP')])
    with sqlite3.connect(archive) as c:c.execute("UPDATE gdelt_event_rows SET source_article_url='https://private:secret@example.org/story'")
    result=read_archive(archive,NAMES,now=NOW)
    assert result['invalid']==1 and result['records']==[]


def test_bounded_sample_is_labeled_and_counts_only_included_rows(archive):
    seed(archive,[event_row(str(1000+i),country='UP') for i in range(4)])
    with sqlite3.connect(archive) as c:result=project(c,NAMES,now=NOW,limit=2)
    assert result['truncated'] and result['examined']==2
    assert result['countries']['ukraine']['count']==2
    assert 'sample capped' in result['message']


def test_no_table_or_missing_file_does_not_create_schema_or_file(archive,tmp_path):
    assert read_archive(archive,NAMES,now=NOW)['state']=='missing'
    absent=tmp_path/'absent.sqlite3'
    assert read_archive(absent,NAMES,now=NOW)['state']=='missing' and not absent.exists()
    with sqlite3.connect(archive) as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='gdelt_event_rows'").fetchone()


def test_explicit_time_filter_limits_batch_window(archive):
    seed(archive,[event_row(country='UP')])
    assert not read_archive(archive,NAMES,since='2026-11-11T09:00:00Z',now=NOW)['records']
    assert read_archive(archive,NAMES,since='2026-11-10T00:00:00Z',now=NOW)['records']


def test_read_failure_returns_safe_empty_state_not_previous_data(archive):
    seed(archive,[event_row(country='UP')])
    with sqlite3.connect(archive) as c:c.execute('ALTER TABLE gdelt_event_rows RENAME COLUMN event_code TO broken')
    result=read_archive(archive,NAMES,now=NOW)
    assert result['state']=='unavailable' and not result['countries'] and not result['records']
