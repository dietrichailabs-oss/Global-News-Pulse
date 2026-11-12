"""Adversarial engineering checks for external-link and translation boundaries."""
from pathlib import Path
import hashlib
import json
import zipfile

import pytest

from global_pulse.security import safe_url, event_id, atomic_text, csv_cell
from global_pulse.translation import Translator, TranslationUnavailable


@pytest.mark.parametrize('url',[
    'https://0177.0.0.1/private', 'https://0x7f000001/private',
    'https://2130706433/private', 'https://127.1/private',
    'https://intranet/private', 'https://server.lan/private',
    'https://example.org\\@127.0.0.1/private',
])
def test_external_open_rejects_browser_ambiguous_local_hosts(url):
    with pytest.raises(ValueError):
        safe_url(url)


@pytest.mark.parametrize('value',['../event','event/../../x','x" onclick="a','x\nrun','x'*129,''])
def test_notification_event_identifiers_are_not_path_or_command_fragments(value):
    with pytest.raises(ValueError):
        event_id(value)


def test_atomic_export_refuses_existing_symlink(tmp_path):
    target=tmp_path/'original.txt';target.write_text('unchanged')
    alias=tmp_path/'alias.txt'
    try:alias.symlink_to(target)
    except OSError:pytest.skip('symlink creation unsupported by this account')
    with pytest.raises(ValueError):atomic_text(alias,'replacement')
    assert target.read_text()=='unchanged'


@pytest.mark.parametrize('value',['=SUM(1,2)',' +cmd','\t=HYPERLINK("x")','@function','-2+3'])
def test_csv_export_quotes_formula_cells(value):
    assert csv_cell(value).startswith("'")


def _archive(tmp_path,entries):
    archive=tmp_path/'model.argosmodel'
    with zipfile.ZipFile(archive,'w') as z:
        for path,data in entries.items():z.writestr(path,data)
    return archive


def _model_translator(tmp_path,archive):
    tr=Translator(tmp_path/'data')
    tr.catalog={'zz':{'key':'reviewed-model','url':'https://example.org/model','size_bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}}
    return tr


def test_model_archive_rejects_path_traversal_even_when_hash_matches_review(tmp_path):
    archive=_archive(tmp_path,{'package/../escaped.bin':b'x'})
    tr=_model_translator(tmp_path,archive)
    with pytest.raises(ValueError,match='path'):
        tr.install_archive(archive,'zz')
    assert not (tmp_path/'escaped.bin').exists()


def test_model_archive_drops_executable_and_pickle_assets(tmp_path):
    archive=_archive(tmp_path,{'package/model/model.bin':b'test','package/model/config.json':b'{}','package/sentencepiece.model':b'tokens','package/metadata.json':json.dumps({'from_code':'zz','to_code':'en'}),'package/evil.py':b'raise RuntimeError()','package/stanza/model.pt':b'pickle'})
    tr=_model_translator(tmp_path,archive);tr.install_archive(archive,'zz')
    result=tr.root/'reviewed-model'
    assert (result/'model/model.bin').read_bytes()==b'test'
    assert not (result/'evil.py').exists() and not (result/'stanza').exists()


def test_model_size_and_hash_required_before_extract(tmp_path):
    archive=_archive(tmp_path,{'package/metadata.json':'{}'})
    tr=_model_translator(tmp_path,archive);tr.catalog['zz']['sha256']='0'*64
    with pytest.raises(ValueError,match='integrity'):
        tr.install_archive(archive,'zz')
    assert not (tr.root/'reviewed-model').exists()


def test_translation_missing_model_does_not_download(tmp_path,monkeypatch):
    tr=Translator(tmp_path)
    monkeypatch.setattr(tr,'download',lambda *a,**k:pytest.fail('silent download'))
    with pytest.raises(TranslationUnavailable):
        tr.translate('A source excerpt with sufficient length.','zz')


def test_diagnostic_redaction_removes_entire_bearer_credential():
    from global_pulse.security import redact
    text=redact('Authorization: Bearer secret-value-123')
    assert 'secret-value-123' not in text


def test_external_open_rejects_mixed_hex_ipv4_notation():
    with pytest.raises(ValueError):
        safe_url('https://0x7f.0.0.1/private')
