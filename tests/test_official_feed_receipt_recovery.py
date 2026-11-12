"""Offline recovery verification; never mislabel as a repeated live audit."""
import copy
import json
import socket
import pytest
from scripts.official_feed_batch import candidates, atomic_json
from scripts.recover_official_feed_batch import admitted_from_receipts, RECOVERY_PATH

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Receipt recovery cannot contact publishers')
    monkeypatch.setattr(socket, 'getaddrinfo', denied)
    monkeypatch.setattr(socket.socket, 'connect', denied)


def test_json_output_is_lf_and_roundtrips_unicode(tmp_path):
    path = tmp_path/'nested'/'result.json'
    document = {'source': 'Test — agency', 'rows': [1, 2]}
    atomic_json(path, document)
    assert b'\r' not in path.read_bytes()
    assert json.loads(path.read_text(encoding='utf-8')) == document
    assert not path.with_name(path.name+'.tmp').exists()


def test_recovery_keeps_original_outcomes_and_does_not_mutate_receipts():
    document = json.loads(RECOVERY_PATH.read_text(encoding='utf-8'))
    before = copy.deepcopy(document)
    rows = admitted_from_receipts(document, candidates())
    assert [row['id'] for row in rows] == ['bls_latest', 'un_geneva']
    assert document == before


@pytest.mark.parametrize('mutation', ['duplicate', 'missing', 'false_success', 'wrong_url', 'no_reopen', 'wrong_job'])
def test_recovery_rejects_changed_or_incomplete_success_evidence(mutation):
    document = json.loads(RECOVERY_PATH.read_text(encoding='utf-8'))
    if mutation == 'duplicate': document['sources'][-1] = copy.deepcopy(document['sources'][0])
    elif mutation == 'missing': document['sources'].pop()
    elif mutation == 'false_success': document['sources'][0]['status'] = 'collector_store_pass'
    elif mutation == 'wrong_url': document['sources'][2]['feed_url'] = 'https://example.org/not-the-audited-feed'
    elif mutation == 'no_reopen': document['sources'][2]['sqlite_reopen_verified'] = False
    else: document['original_job_id'] = 1
    with pytest.raises(ValueError):
        admitted_from_receipts(document, candidates())
