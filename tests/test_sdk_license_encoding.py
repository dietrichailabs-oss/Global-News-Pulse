"""License text encoding must preserve every original byte on round-trip."""
import hashlib
import pytest
from scripts.normalize_sdk_license_text import convert


def test_cp1252_accents_and_quotes_become_utf8_without_text_loss():
    raw='Garanties limitées; “Microsoft”.\r\n'.encode('cp1252')
    output=convert(raw,hashlib.sha256(raw).hexdigest())
    assert output.decode('utf-8')=='Garanties limitées; “Microsoft”.\r\n'
    assert output.decode('utf-8').encode('cp1252')==raw


def test_unknown_input_hash_rejected():
    with pytest.raises(ValueError):convert(b'changed license', '0'*64)


def test_invalid_cp1252_byte_never_replaced_silently():
    raw=b'bad\x81'
    with pytest.raises(UnicodeDecodeError):convert(raw,hashlib.sha256(raw).hexdigest())
