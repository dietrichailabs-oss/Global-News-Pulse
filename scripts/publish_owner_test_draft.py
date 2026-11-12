"""Deliver an owner-requested test package, never publish a public release.

Requires completed build/smoke receipts and a private repository. Uploads only
an explicit artifact allowlist to a new draft. No branch merge, tag publication,
certificate/trust-store change, or license acceptance. No blind write retries.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

REPOSITORY = 'dietrichailabs-oss/GlobalNewsPulse'
BRANCH = 'refs/heads/eng/owner-quick-test-20261110'
FILES = (
    'GlobalPulse-0.1.1-E2-windows-x64-setup.exe',
    'GlobalPulse-0.1.1-E2-windows-x64-portable.zip',
    'MANIFEST.json', 'SBOM.cdx.json', 'SHA256SUMS.txt',
    'WINDOWS_BUILD_RECORD.json', 'WINDOWS_SMOKE.json',
    'ENGINEERING_CANDIDATE.json', 'internal-tests.xml',
    'OWNER_TEST_SIGNING.json',
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Refusing credential-bearing API redirect')


def record(path):
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'filename': path.name, 'bytes': path.stat().st_size, 'sha256': sha}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_artifacts(root, source):
    if not re.fullmatch('[0-9a-f]{40}', source):
        raise ValueError('Exact source commit required')
    for name in FILES:
        path = root / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise ValueError('Required original artifact missing: ' + name)
    build = read_json(root / 'WINDOWS_BUILD_RECORD.json')
    smoke = read_json(root / 'WINDOWS_SMOKE.json')
    candidate = read_json(root / 'ENGINEERING_CANDIDATE.json')
    if build['source_commit'] != source or build['source_worktree_dirty']:
        raise ValueError('Build source/clean-tree mismatch')
    if smoke.get('status') != 'PASS':
        raise ValueError('Frozen/installer smoke did not pass')
    if (candidate.get('source_commit') != source or
            candidate.get('status') != 'BUILT_AND_ENGINEERING_SMOKE_TESTED_PENDING_INDEPENDENT_QA'):
        raise ValueError('Successful candidate receipt is missing')
    for item in candidate['files']:
        name = item['filename']
        if Path(name).name != name or name not in FILES + ('native-packages.lock.json',):
            raise ValueError('Unexpected candidate artifact name')
        if record(root / name) != item:
            raise ValueError('Original candidate artifact changed: ' + name)
    xml = ET.parse(root / 'internal-tests.xml').getroot()
    suites = [e for e in xml.iter('testsuite') if not list(e.iterfind('testsuite'))]
    if not suites:
        raise ValueError('Test receipt lacks a suite')
    totals = {key: sum(int(e.get(key, '0')) for e in suites)
              for key in ('tests', 'failures', 'errors', 'skipped')}
    if totals['tests'] < 593 or any(totals[key] for key in ('failures', 'errors', 'skipped')):
        raise ValueError('Required test coverage did not pass completely')
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--readme', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or os.environ.get('GITHUB_REF') != BRANCH:
        raise ValueError('Owner delivery is restricted to its exact repository and branch')
    root = args.artifacts.resolve(strict=True)
    source = os.environ['GITHUB_SHA']
    totals = validate_artifacts(root, source)
    token = os.environ['GP_OWNER_DELIVERY_TOKEN']
    opener = urllib.request.build_opener(NoRedirect())
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'GlobalPulse-Owner-Test-Delivery'}
    api = 'https://api.github.com/repos/' + REPOSITORY

    def request(url, method='GET', value=None, path=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc not in {'api.github.com', 'uploads.github.com'}:
            raise ValueError('Non-GitHub upload/API destination refused')
        local_headers = dict(headers)
        if path is None:
            data = json.dumps(value).encode('utf-8') if value is not None else None
            if data is not None:
                local_headers['Content-Type'] = 'application/json'
            req = urllib.request.Request(url, data=data, headers=local_headers, method=method)
            with opener.open(req, timeout=120) as response:
                return json.load(response)
        local_headers['Content-Type'] = 'application/octet-stream'
        local_headers['Content-Length'] = str(path.stat().st_size)
        with path.open('rb') as stream:
            req = urllib.request.Request(url, data=stream, headers=local_headers, method=method)
            with opener.open(req, timeout=900) as response:
                return json.load(response)

    repository = request(api)
    if repository.get('private') is not True or repository.get('full_name') != REPOSITORY:
        raise ValueError('Refusing owner binaries outside the private repository')
    run = os.environ['GITHUB_RUN_ID']
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    if not run.isdecimal() or not attempt.isdecimal():
        raise ValueError('Invalid workflow identity')
    tag = f'owner-test-{source[:12]}-{run}-{attempt}'
    start = root / 'START_HERE.md'
    shutil.copyfile(args.readme, start)
    names = list(FILES) + ['START_HERE.md']
    if (root / 'native-packages.lock.json').is_file():
        names.append('native-packages.lock.json')
    originals = [record(root / name) for name in names]
    if sum(r['bytes'] for r in originals) > 900 * 1024 * 1024:
        raise ValueError('Owner delivery exceeds bounded size')
    receipt = {'schema_version': 1, 'source_commit': source,
               'workflow_run': run, 'workflow_attempt': attempt,
               'scope': 'Private owner quick test; NOT public release or independent QA approval',
               'tests': totals, 'hosted_windows_smoke': 'PASS',
               'physical_windows_client': 'OWNER_TEST_PENDING',
               'signing': read_json(root / 'OWNER_TEST_SIGNING.json'),
               'files': originals, 'public_release': 'HOLD'}
    (root / 'TEST_PACKAGE_RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    (root / 'OWNER_SHA256SUMS.txt').write_text(
        ''.join(r['sha256'] + '  ' + r['filename'] + '\n' for r in originals), encoding='utf-8')
    names += ['TEST_PACKAGE_RECEIPT.json', 'OWNER_SHA256SUMS.txt']
    body = (f'Private owner test for Mark. Source `{source}`. '
            'NOT a public release; no merge or signing approval inferred.\n\n'
            'Upload incomplete until the final asset-verification note appears.')
    release = request(api + '/releases', 'POST', {
        'tag_name': tag, 'target_commitish': source,
        'name': 'Global Pulse — Mark private quick test — ' + source[:8],
        'body': body, 'draft': True, 'prerelease': True, 'make_latest': 'false'})
    if release.get('draft') is not True or release.get('published_at') is not None:
        raise ValueError('Unexpected non-draft release response')
    upload = release['upload_url'].split('{', 1)[0]
    expected_upload = 'https://uploads.github.com/repos/' + REPOSITORY + '/releases/' + str(release['id']) + '/assets'
    if upload != expected_upload:
        raise ValueError('Unexpected release asset endpoint')
    assets = []
    for name in names:
        path = root / name
        expected = record(path)
        asset = request(upload + '?name=' + urllib.parse.quote(name, safe=''), 'POST', path=path)
        if (asset.get('state') != 'uploaded' or asset.get('size') != expected['bytes'] or
                asset.get('digest') != 'sha256:' + expected['sha256']):
            raise ValueError('Uploaded asset identity mismatch: ' + name)
        assets.append({**expected, 'id': asset['id'], 'url': asset['browser_download_url']})
        print('GP_OWNER_ASSET ' + json.dumps(assets[-1]), flush=True)
    body = (f'## Private owner test — {source[:8]}\n\n'
            '**Download the setup EXE for installation, or the portable ZIP for extraction.** '
            'Use one copy at a time. Read START_HERE.md.\n\n'
            f'Exact source: `{source}`. Workflow `{run}`, attempt `{attempt}`.\n\n'
            f'**{totals["tests"]} source tests passed; 0 failures/errors/skips.** '
            'Hosted Windows frozen/installer smoke passed. All uploaded file sizes and SHA-256 digests verified.\n\n'
            '**Unsigned private engineering test build.** No signing certificate/trust-store changes. '
            'Self-signing remains the owner-selected eventual route.\n\n'
            'Physical-client behavior and independent release/compliance review remain pending. '
            '**Public release HOLD. This entry remains an unpublished draft.**\n\n'
            'Upload complete: ' + str(len(assets)) + ' verified assets.')
    updated = request(api + '/releases/' + str(release['id']), 'PATCH',
                      {'body': body, 'draft': True, 'prerelease': True, 'make_latest': 'false'})
    final = request(api + '/releases/' + str(release['id']))
    if not final.get('draft') or final.get('published_at') is not None:
        raise ValueError('Draft status changed unexpectedly')
    remote = {a['name']: a for a in final['assets']}
    for expected in assets:
        item = remote.get(expected['filename'], {})
        if item.get('size') != expected['bytes'] or item.get('digest') != 'sha256:' + expected['sha256']:
            raise ValueError('Final asset readback mismatch')
    print('GP_OWNER_DELIVERY ' + json.dumps({'release_id': final['id'], 'draft': True,
          'url': final['html_url'], 'source_commit': source, 'assets': assets,
          'tests': totals, 'public_release': 'HOLD'}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit('GitHub delivery failed with HTTP ' + str(error.code) + '; no blind write retry performed.')
