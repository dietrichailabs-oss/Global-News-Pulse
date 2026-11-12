"""Strict reconciliation of vendor Windows SPDX with an official source archive.

Raw-byte matches, reconstructed Windows-checkout bytes, and the one reviewed
release-marker difference remain distinct. Unknown differences are never waived.
"""
from __future__ import annotations
import hashlib
from pathlib import PurePosixPath
import re

SOURCE_COMMIT = 'd505fc23640d2bd6345e6483eb73daf4e19f5829'
TAG_VENDOR_SHA1 = '8eb01c346a92a2321c358ae8327d3b48c163b1b0'
TAG_ARCHIVE_SHA1 = '69e0ad2ee8a83188f56b5c88af84f2e5c6481a2d'
OMITTED_VCS_METADATA = {
    '.gitattributes': 'bdba026fe944e5153b41db46b2785cde5fa8b83f',
    '.gitignore': '42b9ebe1c4df841a3f612b7b27bd31c5e3524904',
}


def source_path(value):
    value = value.replace('\\', '/')
    if value.startswith('./'):
        value = value[2:]
    parts = PurePosixPath(value).parts
    if not parts or value.startswith('/') or ':' in value or '..' in parts or '\0' in value:
        raise ValueError('Unsafe source path')
    return '/'.join(parts)


def parse_source_spdx(text):
    checks = {}
    for block in re.split(r'(?m)(?=^FileName: )', text):
        name = re.search(r'^FileName: (.+)$', block, re.M)
        digest = re.search(r'^FileChecksum: SHA1: ([0-9a-fA-F]{40})\s*$', block, re.M)
        if name:
            if not digest:
                raise ValueError('Source entry without SHA1')
            path = source_path(name.group(1).strip())
            value = digest.group(1).lower()
            if path in checks:
                raise ValueError('Duplicate source identity')
            checks[path] = value
    if not checks:
        raise ValueError('No source inventory entries')
    return checks


def compare_source_bytes(path, data, expected):
    actual = hashlib.sha1(data).hexdigest()
    record = {'path': path, 'bytes': len(data), 'archive_sha1': actual, 'vendor_sha1': expected}
    if actual == expected:
        return {**record, 'comparison': 'EXACT_BYTES'}
    # This is a precisely recorded checkout transform, not a fuzzy content
    # comparison. The transformed bytes must match the vendor checksum exactly.
    # PDF test fixtures can contain high-bit bytes, so do not assume UTF-8.
    unix = data.replace(b'\r\n', b'\n')
    if b'\n' in unix and b'\r' not in unix:
        windows = unix.replace(b'\n', b'\r\n')
        windows_hash = hashlib.sha1(windows).hexdigest()
        if windows_hash == expected:
            return {**record, 'comparison': 'WINDOWS_CHECKOUT_EOL',
                    'windows_bytes': len(windows), 'windows_sha1': windows_hash}
    if (path == '.tag' and expected == TAG_VENDOR_SHA1 and actual == TAG_ARCHIVE_SHA1
            and data == (SOURCE_COMMIT + '\n').encode('ascii')):
        return {**record, 'comparison': 'REVIEWED_RELEASE_MARKER_DIFFERENCE',
                'reason': 'Archive exporter marker names the same immutable revision as both vendor binary SBOMs; not an executable source file. Original differing vendor checksum retained.',
                'source_commit': SOURCE_COMMIT}
    raise ValueError('Unresolved source checksum mismatch: ' + path)


def reviewed_missing(checks, seen):
    missing = sorted(set(checks) - set(seen))
    if {path: checks[path] for path in missing} != OMITTED_VCS_METADATA:
        raise ValueError('Unexpected missing source file or changed VCS metadata inventory')
    return [{'path': path, 'vendor_sha1': checks[path],
             'reason': 'Version-control checkout metadata excluded from official release archive; not runtime/build source.'}
            for path in missing]
