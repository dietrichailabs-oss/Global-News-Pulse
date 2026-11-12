"""Engineering named-column schema, independently assembled from primary PDF.

Reference: https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
Read/rendered 2026-11-11. These are engineering tests, not independent QA.
They deliberately do not import the old or PR83 helper's row constructor.
"""
from datetime import datetime,timezone
import hashlib
import importlib.util
import io
import socket
import sqlite3
import subprocess
import sys
import zipfile
import pytest
from global_pulse.gdelt_batches import GdeltBatchCache,parse_manifest,_row
from global_pulse.gdelt_map_data import read_archive

DATE_FIELDS=['GlobalEventID','Day','MonthYear','Year','FractionDate']
ACTOR_FIELDS=['Code','Name','CountryCode','KnownGroupCode','EthnicCode',
              'Religion1Code','Religion2Code','Type1Code','Type2Code','Type3Code']
ACTION_FIELDS=['IsRootEvent','EventCode','EventBaseCode','EventRootCode','QuadClass',
               'GoldsteinScale','NumMentions','NumSources','NumArticles','AvgTone']
GEO_FIELDS=['Type','FullName','CountryCode','ADM1Code','ADM2Code','Lat','Long','FeatureID']
COLUMNS=(DATE_FIELDS+[prefix+name for prefix in ('Actor1','Actor2') for name in ACTOR_FIELDS]
         +ACTION_FIELDS+[prefix+'Geo_'+name for prefix in ('Actor1','Actor2','Action') for name in GEO_FIELDS]
         +['DATEADDED','SOURCEURL'])
STAMP='20261111080000'
NOW=datetime(2026,11,11,12,tzinfo=timezone.utc)


def named_row(country='UP',place='Kyiv, Ukraine',identifier='171',stamp=STAMP):
    values={'GlobalEventID':identifier,'Day':stamp[:8],'MonthYear':stamp[:6],
            'Year':stamp[:4],'FractionDate':'2026.86','IsRootEvent':'1',
            'EventCode':'190','EventBaseCode':'190','EventRootCode':'19','QuadClass':'4',
            'GoldsteinScale':'-10','NumMentions':'1','NumSources':'1','NumArticles':'1','AvgTone':'-2',
            'Actor1Code':'USA','Actor1Name':'ACTOR ONE','Actor1CountryCode':'USA',
            'Actor2Code':'RUS','Actor2Name':'ACTOR TWO','Actor2CountryCode':'RUS',
            'Actor1Geo_Type':'1','Actor1Geo_FullName':'United States','Actor1Geo_CountryCode':'US',
            'Actor2Geo_Type':'1','Actor2Geo_FullName':'Russia','Actor2Geo_CountryCode':'RS',
            'ActionGeo_Type':'4','ActionGeo_FullName':place,'ActionGeo_CountryCode':country,
            'ActionGeo_ADM1Code':country+'00','ActionGeo_ADM2Code':'12345',
            'ActionGeo_Lat':'50.4501','ActionGeo_Long':'30.5234','ActionGeo_FeatureID':'123456',
            'DATEADDED':stamp,'SOURCEURL':'https://publisher.example.org/report/'+identifier}
    return [values.get(name,'') for name in COLUMNS]


def archive_bytes(rows,stamp=STAMP):
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(stamp+'.export.CSV','\n'.join('\t'.join(row) for row in rows)+'\n')
    data=memory.getvalue()
    batch=parse_manifest(f'{len(data)} {hashlib.md5(data).hexdigest()} https://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip')['export']
    return batch,data


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('Named-column validation is offline')
    monkeypatch.setattr(socket,'getaddrinfo',denied);monkeypatch.setattr(socket.socket,'connect',denied)


def test_named_codebook_has61_columns_and_correct_zero_based_geography():
    assert len(COLUMNS)==61 and len(set(COLUMNS))==61
    assert COLUMNS.index('ActionGeo_Type')==51
    assert COLUMNS.index('ActionGeo_FullName')==52
    assert COLUMNS.index('ActionGeo_CountryCode')==53
    assert COLUMNS.index('ActionGeo_ADM1Code')==54
    assert COLUMNS.index('ActionGeo_Lat')==56
    assert COLUMNS.index('DATEADDED')==59 and COLUMNS.index('SOURCEURL')==60


@pytest.mark.parametrize('country,place,name',[('UP','Kyiv, Ukraine','Ukraine'),('IR','Tehran, Iran','Iran'),('GM','Berlin, Germany','Germany')])
def test_named_row_real_import_reopen_projection_uses_action_not_actor( tmp_path,country,place,name):
    path=tmp_path/'global-pulse.sqlite3';batch,data=archive_bytes([named_row(country,place)])
    result=_row(named_row(country,place),batch)
    assert result[7:9]==(country,place)
    with GdeltBatchCache(path) as cache:
        assert cache.import_export(batch,data,now='2026-11-11T08:05:00Z')['added']==1
    layer=read_archive(path,['Ukraine','Iran','Germany','United States of America','Russia'],now=NOW)
    assert len(layer['countries'])==1 and layer['records'][0]['country']==name
    assert layer['records'][0]['location']==place
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT action_country_code,action_location FROM gdelt_event_rows').fetchone()==(country,place)


def load_historical(tmp_path,ref):
    source=subprocess.check_output(['git','show',ref+':global_pulse/gdelt_batches.py'])
    path=tmp_path/(ref[:8]+'.py');path.write_bytes(source)
    module_name='global_pulse._historical_'+ref[:8]
    spec=importlib.util.spec_from_file_location(module_name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[module_name]=module
    spec.loader.exec_module(module)
    return module


def test_prior_parent_is_correct_and_rejected_parser_reproduces_real_schema_failure(tmp_path):
    good=load_historical(tmp_path,'730d476b15b97e6ac8a3e794d44e1644d544ff3c')
    bad=load_historical(tmp_path,'b03d855ae1c5885208eb094706239322cb58f97c')
    try:
        batch,_=archive_bytes([named_row()])
        assert good._row(named_row(),batch)[7:9]==('UP','Kyiv, Ukraine')
        with pytest.raises(bad.GdeltBatchError,match='ActionGeo resolution'):
            bad._row(named_row(),batch)
        assert _row(named_row(),batch)[7:9]==('UP','Kyiv, Ukraine')
    finally:
        sys.modules.pop(good.__name__,None);sys.modules.pop(bad.__name__,None)
