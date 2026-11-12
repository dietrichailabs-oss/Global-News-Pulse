"""Verify and package the exact Windows SDK redistribution evidence.

No license acceptance, network access, binary execution, re-signing, or release
approval occurs here. Unknown package versions/assets or modified bytes fail.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

SDK_VERSION = '10.0.19041.57'
SDK_ID = 'runtimepack.Microsoft.Windows.SDK.NET.Ref/' + SDK_VERSION
SDK_ARCHIVE_SHA256 = '90b18f2cf7d7a23f5b0bfe2b86d8dda45881481f677ce36eccaf6e9ab50b6b4b'
SDK_LICENSE_SHA256 = 'dd07eb178e00c6bba4148457fc00ff77cd4887eb521d504186fe59c9ec8bbe62'
BUNDLE_ROOT = Path(__file__).resolve().parents[1] / 'packaging/licenses/windows-sdk'
DOCUMENTS = {'SDK_LICENSE.rtf', 'SDK_TERMS.txt', 'SDK_REDIST.html', 'SDK_COMPONENT_NOTICE.txt'}
ASSETS = {'Microsoft.Windows.SDK.NET.dll', 'WinRT.Runtime.dll'}
SDK_ASSET_PINS = {'Microsoft.Windows.SDK.NET.dll': {'bytes': 24877600, 'sha256': '0ec371d93798852e36461c8adddbeadce0f963a04752f0b64e54fe19c1c834a7'}, 'WinRT.Runtime.dll': {'bytes': 528944, 'sha256': 'bcf3a14e8712a90837fc5c0d8c8a24696af2bd7f74e9767597ec81ededfb23db'}}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(root: Path, relative: str) -> Path:
    root = root.resolve(strict=True)
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('Missing or escaped evidence/runtime path: ' + relative)
    return path


def verify_record(path: Path, record: dict) -> None:
    if path.stat().st_size != record.get('bytes') or digest(path) != record.get('sha256'):
        raise ValueError('Exact byte identity mismatch: ' + path.name)


def load_bundle(root: Path) -> dict:
    path = checked_path(root, 'BUNDLE.json')
    if path.stat().st_size > 65536:
        raise ValueError('Oversized SDK bundle record')
    bundle = json.loads(path.read_text(encoding='utf-8'))
    if bundle.get('sdk_version') != SDK_VERSION or bundle.get('sdk_archive_sha256') != SDK_ARCHIVE_SHA256:
        raise ValueError('Unreviewed SDK identity')
    documents = bundle.get('documents', {})
    if set(documents) != DOCUMENTS:
        raise ValueError('SDK evidence document set differs')
    if documents['SDK_LICENSE.rtf'].get('sha256') != SDK_LICENSE_SHA256:
        raise ValueError('SDK governing license differs')
    if bundle.get('assets') != SDK_ASSET_PINS:
        raise ValueError('SDK asset allowlist differs')
    for name, record in documents.items():
        source = checked_path(root, name)
        if source.stat().st_size > 1024*1024:
            raise ValueError('Oversized SDK document')
        verify_record(source, record)
    return bundle


def prepare(deps: Path, nuget_root: Path, published: Path, *, bundle_root: Path = BUNDLE_ROOT) -> dict:
    bundle = load_bundle(bundle_root)
    published = published.resolve(strict=True)
    if deps.resolve().parent != published:
        raise ValueError('Dependency receipt is not from the published helper')
    document = json.loads(deps.read_text(encoding='utf-8-sig'))
    targets = document.get('targets', {})
    target_name = next((name for name in targets if name.lower().endswith('/win-x64')), None)
    if target_name is None:
        raise ValueError('Published Windows x64 target missing')
    target = targets[target_name]
    sdk_keys = [name for name in target if 'microsoft.windows.sdk.net.ref/' in name.lower()]
    if sdk_keys != [SDK_ID]:
        raise ValueError('Unreviewed or missing SDK dependency')
    metadata = target[SDK_ID]
    runtime = metadata.get('runtime', {})
    if metadata.get('native'):
        raise ValueError('Unexpected native asset in SDK projection package')
    names = [Path(name.replace('\\', '/')).name for name in runtime]
    if len(names) != len(set(names)) or not names or 'Microsoft.Windows.SDK.NET.dll' not in names or not set(names) <= ASSETS:
        raise ValueError('Unreviewed SDK runtime asset')
    package = nuget_root / 'microsoft.windows.sdk.net.ref' / SDK_VERSION
    archive = checked_path(package, 'microsoft.windows.sdk.net.ref.' + SDK_VERSION + '.nupkg')
    if digest(archive) != SDK_ARCHIVE_SHA256:
        raise ValueError('Restored SDK NuGet archive differs from reviewed original')
    verified = []
    for name in sorted(names):
        expected = bundle['assets'][name]
        original = checked_path(package, 'lib/net8.0/' + name)
        shipped = checked_path(published, name)
        verify_record(original, expected)
        verify_record(shipped, expected)
        verified.append({'file': name, 'source_relative': 'lib/net8.0/' + name,
                         'bytes': expected['bytes'], 'sha256': expected['sha256'],
                         'unmodified_from_exact_nuget': True})
    destination = published / 'licenses/windows-sdk'
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(published):
        raise ValueError('Escaped SDK evidence destination')
    copied = []
    for name in sorted(DOCUMENTS | {'BUNDLE.json'}):
        source = checked_path(bundle_root, name)
        output = destination / name
        if output.is_symlink():
            raise ValueError('Symlink evidence destination refused')
        shutil.copyfile(source, output)
        copied.append({'source_relative': 'reviewed-official-sdk-evidence/' + name,
                       'packaged_relative': output.relative_to(published).as_posix(),
                       'bytes': output.stat().st_size, 'sha256': digest(output)})
    notice_path = published / 'licenses/NATIVE_PACKAGE_NOTICES.json'
    notices = json.loads(notice_path.read_text(encoding='utf-8'))
    records = [r for r in notices['packages'] if r['package'] + '/' + r['version'] == SDK_ID]
    if len(records) != 1:
        raise ValueError('SDK absent or duplicated in native notice inventory')
    record = records[0]
    record['evidence_kind'] = 'official_sdk_license_redist_and_exact_unmodified_assets'
    record['notice_files'] = copied
    record['verified_runtime_files'] = verified
    record['downstream_terms'] = 'Installer terms page and content-bound first-use notification-component consent; independent QA pending'
    notices['external_license_reference_only'] = [
        {'package': r['package'], 'version': r['version']} for r in notices['packages']
        if r['evidence_kind'] == 'external_license_reference_only'
    ]
    notices['release_rights_status'] = (
        'HOLD: remaining external-only license reference' if notices['external_license_reference_only'] else
        'Official notice evidence collected; exact SDK distribution conditions implemented, pending independent QA; not public release approval'
    )
    notice_path.write_text(json.dumps(notices, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    receipt = {'schema_version': 1, 'sdk_identity': SDK_ID, 'target': target_name,
               'sdk_archive_sha256': SDK_ARCHIVE_SHA256, 'verified_runtime_files': verified,
               'documents': copied, 'status': 'ENGINEERING_BYTE_AND_DOCUMENT_CHECK_PASS',
               'independent_qa': 'PENDING', 'public_release': 'NOT_APPROVED',
               'scope': 'Only Microsoft SDK projection; no restriction imposed on LGPL/GPL or other separately licensed components'}
    (destination / 'SDK_DISTRIBUTION_RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deps', type=Path, required=True)
    parser.add_argument('--nuget-root', type=Path, required=True)
    parser.add_argument('--published', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.deps, args.nuget_root, args.published), indent=2))


if __name__ == '__main__':
    main()
