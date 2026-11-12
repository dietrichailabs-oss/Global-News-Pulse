"""Bounded public-upstream evidence retrieval; never executes downloaded bytes.

This is Engineering research, not a license grant or an independent QA result.
Accepted product source and dependency locks are not changed. Only small text
snapshots/receipts are retained; downloaded wheels and NuGet packages stay in the
disposable runner temp directory and are never committed or uploaded.
"""
from __future__ import annotations
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import time
import urllib.request
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/engineering/GP-ENG-FREEWARE-COMPLIANCE-001/upstream'
OUT.mkdir(parents=True, exist_ok=True)
RECORDS = []


def fetch(url, limit=2*1024*1024):
    request = urllib.request.Request(url, headers={'User-Agent': 'GlobalPulse-Engineering-Compliance/1.0', 'Accept': '*/*'})
    with urllib.request.urlopen(request, timeout=90) as response:
        if not response.url.startswith('https://'):
            raise ValueError('Non-HTTPS redirect refused')
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Response exceeds evidence size bound')
        return data, {'requested_url': url, 'final_url': response.url,
                      'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                      'content_type': response.headers.get('Content-Type', '')}


def capture(name, url, limit=2*1024*1024, persist=True):
    try:
        data, receipt = fetch(url, limit)
        receipt.update(name=name, retrieval='SUCCESS')
        if persist:
            (OUT / name).write_bytes(data)
        RECORDS.append(receipt)
        return data
    except Exception as error:
        RECORDS.append({'name': name, 'requested_url': url, 'retrieval': 'FAILED',
                        'error': type(error).__name__ + ': ' + str(error)[:500]})
        return None


def inspect_zip(name, data, pattern):
    if data is None:
        return None
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        records = []
        for item in archive.infolist():
            if not re.search(pattern, item.filename, re.I):
                continue
            record = {'path': item.filename, 'bytes': item.file_size}
            if item.file_size <= 16*1024*1024:
                payload = archive.read(item)
                record['sha256'] = hashlib.sha256(payload).hexdigest()
                if item.file_size <= 256*1024 and item.filename.lower().endswith(('.txt','.json','.xml','.nuspec','.conf','.cmake','.pri','metadata','license','notice')):
                    record['text'] = payload.decode('utf-8', 'replace')
            records.append(record)
        (OUT / (name + '-inventory.json')).write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
        return records


def main():
    capture('windows-sdk-license.rtf', 'https://aka.ms/WinSDKLicenseURL')
    capture('windows-sdk-redist.html', 'https://learn.microsoft.com/en-us/legal/windows-sdk/redist')
    capture('windows-sdk-license-repository.txt', 'https://raw.githubusercontent.com/microsoft/win32metadata/main/licenses/sdk_license.txt')
    sdk = capture('microsoft.windows.sdk.net.ref.10.0.19041.57.nupkg', 'https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.net.ref/10.0.19041.57/microsoft.windows.sdk.net.ref.10.0.19041.57.nupkg', 32*1024*1024, False)
    inspect_zip('windows-sdk-package', sdk, r'license|redist|notice|\.nuspec$|Microsoft\.Windows\.SDK\.NET\.dll$|WinRT\.Runtime\.dll$')
    for package, expected in [
        ('PySide6-WebEngine', 'f9b61b1d457a591ee590a6b80515f25a3e61e2576a2a0a70566380f9d9de4ab0'),
        ('PySide6-Pdf', '4971ba1a0ca15e7c29cfd808e9600aeb46b2305dad01456eb09fa3197166268e')]:
        metadata = capture(package + '-pypi.json', f'https://pypi.org/pypi/{package}/6.12.0.140/json')
        if metadata is None:
            continue
        wheels = [r for r in json.loads(metadata)['urls'] if r['filename'].endswith('win_amd64.whl')]
        if len(wheels) != 1 or wheels[0]['digests']['sha256'] != expected:
            raise ValueError('Exact reviewed wheel identity mismatch: ' + package)
        wheel = capture(wheels[0]['filename'], wheels[0]['url'], 256*1024*1024, False)
        if wheel is None:
            continue
        if hashlib.sha256(wheel).hexdigest() != expected:
            raise ValueError('Downloaded wheel SHA-256 mismatch: ' + package)
        inventory = inspect_zip(package, wheel, r'license|notice|copying|sbom|spdx|cyclone|attribution|provenance|\.dist-info/(METADATA|WHEEL)|qt\.conf|config.*\.h$')
        print('WHEEL_INSPECTION', package, len(inventory or []), flush=True)
    for name, url in [
        ('qtwebengine-official-index.html','https://download.qt.io/official_releases/qtwebengine/'),
        ('qtwebengine-development-index.html','https://download.qt.io/development_releases/qtwebengine/'),
        ('qtwebengine-6140-tags.json','https://api.github.com/repos/qt/qtwebengine/git/matching-refs/tags/v6.140'),
        ('qtwebengine-6113-tag.json','https://api.github.com/repos/qt/qtwebengine/git/ref/tags/v6.11.3'),
        ('qtwebengine-6140-rc-chromium.txt','https://raw.githubusercontent.com/qt/qtwebengine/v6.140.0-rc/CHROMIUM_VERSION'),
        ('qtwebengine-6140-rc-submodules.txt','https://raw.githubusercontent.com/qt/qtwebengine/v6.140.0-rc/.gitmodules'),
        ('qtwebengine-6140-rc-buildinfo.txt','https://raw.githubusercontent.com/qt/qtwebengine/v6.140.0-rc/.cmake.conf'),
    ]:
        capture(name, url)
    receipt = {'schema_version':1, 'observed_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'engineering_commit':os.environ.get('GITHUB_SHA'), 'run_id':os.environ.get('GITHUB_RUN_ID'),
               'accepted_product_base':'483520598d144c3941a8ec2b6ba5b6a3a0cce3ec',
               'status':'OBSERVATIONS_ONLY_NOT_RELEASE_ACCEPTANCE', 'resources': RECORDS}
    (OUT/'RETRIEVAL.json').write_text(json.dumps(receipt, indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt, indent=2), flush=True)
    # Failed optional lookups are preserved, not relabeled as successful source mapping.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
