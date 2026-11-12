"""Engineering provenance guard; correct original schema versus rejected prototype.

Version1/no column is the correct original52/53 geography. Prototype2 is the
rejected off-by-one implementation, not a correction. No source rows rewritten.
"""
import sqlite3
import pytest
from global_pulse.gdelt_map_data import read_archive
from test_gdelt_country_projection import seed,NOW,NAMES,archive,offline
from test_gdelt_batch_cache import event_row


def set_version(path,version):
    with sqlite3.connect(path) as c:
        columns={row[1] for row in c.execute('PRAGMA table_info(gdelt_batches)')}
        if 'parser_version' not in columns:
            c.execute('ALTER TABLE gdelt_batches ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1')
        c.execute('UPDATE gdelt_batches SET parser_version=?',(version,))


@pytest.mark.parametrize('version',[2,3])
def test_rejected_or_unknown_parser_version_excluded_and_preserved(archive,version):
    seed(archive,[event_row(country='UP')]);set_version(archive,version)
    with sqlite3.connect(archive) as c:before='\n'.join(c.iterdump())
    result=read_archive(archive,NAMES,now=NOW)
    with sqlite3.connect(archive) as c:after='\n'.join(c.iterdump())
    assert result['legacy_batches']==1 and not result['records'] and not result['countries']
    assert 'preserved but excluded' in result['message'] and before==after


def test_correct_original_version1_is_not_falsely_excluded(archive):
    seed(archive,[event_row(country='UP')]);set_version(archive,1)
    result=read_archive(archive,NAMES,now=NOW)
    assert result['legacy_batches']==0 and result['records'][0]['country']=='Ukraine'


def test_valid_looking_rejected_prototype_cannot_bypass_version_guard(archive):
    seed(archive,[event_row(country='IR')]);set_version(archive,2)
    with sqlite3.connect(archive) as c:
        c.execute("UPDATE gdelt_event_rows SET action_country_code='UP',action_location='4'")
    result=read_archive(archive,NAMES,now=NOW)
    assert result['records']==[] and result['legacy_batches']==1
