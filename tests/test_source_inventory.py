"""Offline evidence-reconciliation regressions; no network or legal acceptance."""
import hashlib
import pytest
from scripts.source_inventory import (SOURCE_COMMIT, TAG_VENDOR_SHA1,
    OMITTED_VCS_METADATA, source_path, parse_source_spdx,
    compare_source_bytes, reviewed_missing)


def test_windows_inventory_path_matches_archive_path():
    assert source_path('./src\\core\\file.cpp') == 'src/core/file.cpp'


@pytest.mark.parametrize('path', ['../secret', 'src/../secret', '/absolute', 'C:\\absolute'])
def test_unsafe_source_path_refused(path):
    with pytest.raises(ValueError):
        source_path(path)


def test_raw_bytes_are_separate_from_windows_checkout_equivalence():
    data = b'first\nsecond\n'
    exact = compare_source_bytes('src/a.cpp', data, hashlib.sha1(data).hexdigest())
    transformed = compare_source_bytes('src/a.cpp', data, hashlib.sha1(data.replace(b'\n', b'\r\n')).hexdigest())
    assert exact['comparison'] == 'EXACT_BYTES'
    assert transformed['comparison'] == 'WINDOWS_CHECKOUT_EOL'
    assert transformed['archive_sha1'] != transformed['vendor_sha1']


def test_high_bit_fixture_eol_match_still_requires_exact_vendor_checksum():
    data = b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\nfixture\n'
    vendor = hashlib.sha1(data.replace(b'\n', b'\r\n')).hexdigest()
    assert compare_source_bytes('tests/fixture.pdf', data, vendor)['comparison'] == 'WINDOWS_CHECKOUT_EOL'
    with pytest.raises(ValueError):
        compare_source_bytes('tests/fixture.pdf', data + b'changed', vendor)


def test_whitespace_or_code_change_never_accepted_as_eol_only():
    with pytest.raises(ValueError):
        compare_source_bytes('src/a.cpp', b'changed\n', hashlib.sha1(b'original\r\n').hexdigest())


def test_release_marker_exception_is_exact_path_and_both_identities():
    data = (SOURCE_COMMIT + '\n').encode()
    assert compare_source_bytes('.tag', data, TAG_VENDOR_SHA1)['comparison'] == 'REVIEWED_RELEASE_MARKER_DIFFERENCE'
    for path, content, expected in [('src/a.cpp', data, TAG_VENDOR_SHA1), ('.tag', b'other\n', TAG_VENDOR_SHA1), ('.tag', data, '0'*40)]:
        with pytest.raises(ValueError):
            compare_source_bytes(path, content, expected)


def test_missing_runtime_source_never_hidden_by_vcs_exemption():
    records = reviewed_missing(dict(OMITTED_VCS_METADATA), set())
    assert len(records) == 2
    with pytest.raises(ValueError):
        reviewed_missing({**OMITTED_VCS_METADATA, 'src/a.cpp': '0'*40}, set())


def test_spdx_windows_paths_and_checksum_binding():
    text = 'FileName: ./src\\a.cpp\nSPDXID: A\nFileChecksum: SHA1: ' + 'a'*40 + '\n'
    assert parse_source_spdx(text) == {'src/a.cpp': 'a'*40}
    with pytest.raises(ValueError):
        parse_source_spdx(text + text)
    with pytest.raises(ValueError):
        parse_source_spdx('FileName: ./src/a.cpp\n')
