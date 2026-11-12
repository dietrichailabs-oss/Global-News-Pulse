"""Narrow vendor-SPDX false-positive regression; no provider/credential access."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('gp_scan_test', ROOT / 'scripts/package_manifest.py')
pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)
IDENTIFIER = 'SPDXRef-PackagedFile-qt-module-WebEngineCore-sk-pak-b42d-RelWithDebInfo-872898bf869d'


@pytest.mark.parametrize('field', ['SPDXID', 'relatedSpdxElement'])
@pytest.mark.parametrize('mode', ['RelWithDebInfo', 'Debug'])
def test_reviewed_locale_field_is_not_a_secret(field, mode):
    data = ('"' + field + '": "' + IDENTIFIER.replace('RelWithDebInfo', mode) + '"').encode()
    assert not pack.contains_embedded_credential(data, pack.QT_VENDOR_SPDX_PATH)


@pytest.mark.parametrize('token', [b'sk-' + b'A' * 40, b'sk-proj-' + b'B' * 40,
    b'ghp_' + b'C' * 40, b'AKIA' + b'D' * 16, b'-----BEGIN PRIVATE KEY-----'])
def test_real_key_in_same_vendor_document_is_still_rejected(token):
    data = ('"SPDXID": "' + IDENTIFIER + '"').encode() + b'\n' + token
    assert pack.contains_embedded_credential(data, pack.QT_VENDOR_SPDX_PATH)


@pytest.mark.parametrize('data', [
    ('"comment": "' + IDENTIFIER + '"').encode(),
    ('"SPDXID": "' + IDENTIFIER + '-changed"').encode(),
    ('"SPDXID": "' + IDENTIFIER.replace('b42d', 'aaaa') + '"').encode(),
])
def test_unreviewed_context_is_not_exempted(data):
    assert pack.contains_embedded_credential(data, pack.QT_VENDOR_SPDX_PATH)


def test_other_file_is_not_exempted():
    data = ('"SPDXID": "' + IDENTIFIER + '"').encode()
    assert pack.contains_embedded_credential(data, 'licenses/other.json')


def test_exact_committed_vendor_inventory_is_safe_without_rewriting_it(tmp_path):
    original = ROOT / 'packaging/licenses/qt-webengine-pdf/qtwebengine-sbom_qtwebengine-6.140.0.spdx.json'
    data = original.read_bytes()
    assert any(pattern.search(data) for pattern in pack.SECRET_PATTERNS)
    assert not pack.contains_embedded_credential(data, pack.QT_VENDOR_SPDX_PATH)
    runtime = tmp_path / 'runtime'
    target = runtime / pack.QT_VENDOR_SPDX_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    assert pack.scan(runtime, require_complete=False)['status'] == 'PASS'
    assert target.read_bytes() == data
    secret = b'sk-' + b'Z' * 40
    target.write_bytes(data + b'\n' + secret)
    with pytest.raises(ValueError) as error:
        pack.scan(runtime, require_complete=False)
    assert 'potential embedded credential' in str(error.value)
    assert secret.decode() not in str(error.value)
