"""Verify shipped WebEngine/PDF originals and bundle pinned source evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'packaging/licenses/qt-webengine-pdf'
SOURCE_SHA='61257967afd9803a1db6403e86ea25c4efff8fad479bda365a9d81bfd709f621'
SOURCE_COMMIT='d505fc23640d2bd6345e6483eb73daf4e19f5829'
REQUIRED={'Qt6WebEngineCore.dll','QtWebEngineProcess.exe','Qt6Pdf.dll'}


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def prepare(package, bundle=BUNDLE):
    package=Path(package).resolve(strict=True)
    bundle=Path(bundle).resolve(strict=True)
    mapping=json.loads((bundle/'SOURCE_MAP.json').read_text(encoding='utf-8'))
    source=mapping.get('source_archive',{})
    if source.get('sha256')!=SOURCE_SHA or source.get('git_commit')!=SOURCE_COMMIT or not mapping.get('source_download_verified'):
        raise ValueError('Corresponding-source identity is not reviewed')
    if mapping.get('source_sbom_mismatches') or not mapping.get('source_sbom_files_compared'):
        raise ValueError('Source/SBOM evidence is incomplete')
    for name,expected in mapping['documents'].items():
        path=bundle/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(bundle):
            raise ValueError('Missing or escaped Qt compliance document')
        if path.stat().st_size!=expected['bytes'] or digest(path)!=expected['sha256']:
            raise ValueError('Changed Qt compliance document: '+name)
    proof=json.loads((bundle/'QT_PE_SIGNATURE_ONLY_COMPARISON.json').read_text())
    if proof['total']!=10 or proof['equivalent']!=10:
        raise ValueError('Native source relationship differs from reviewed evidence')
    verified=[]
    for row in proof['comparisons']:
        if not row['same_except_signature_metadata'] or not row['all_sections_identical']:
            raise ValueError('An SDK/wheel native comparison failed')
        relative=Path('_internal')/row['wheel_path']
        target=package/relative
        if not target.exists(): continue
        if target.is_symlink() or not target.resolve().is_relative_to(package):
            raise ValueError('Escaped Qt library path')
        expected=row['wheel']
        if target.stat().st_size!=expected['bytes'] or digest(target)!=expected['raw_sha256']:
            raise ValueError('Shipped Qt binary differs from source-mapped wheel: '+str(relative))
        verified.append({'path':relative.as_posix(),'bytes':expected['bytes'],'sha256':expected['raw_sha256'],
                         'source_commit':SOURCE_COMMIT,'relationship':'Exact shipped raw digest; executable-byte equivalence to source-identified official SDK'})
    if not REQUIRED <= {Path(x['path']).name for x in verified}:
        raise ValueError('Required source-mapped WebEngine/PDF binaries missing')
    destination=package/'licenses/qt-open-source/corresponding-source'
    destination.mkdir(parents=True,exist_ok=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(package):
        raise ValueError('Escaped Qt evidence destination')
    for path in bundle.iterdir():
        if not path.is_file() or path.is_symlink(): raise ValueError('Unexpected Qt evidence item')
        shutil.copyfile(path,destination/path.name)
    receipt={'schema_version':1,'source_archive':source,'verified_shipped_binaries':verified,
             'status':'ENGINEERING_EXACT_BINARY_SOURCE_MAPPING_PASS_PENDING_QA',
             'raw_binary_bytes_changed':False,'public_release':'NOT_APPROVED',
             'other_qt_modules':'Existing Qt 6.12.0 core/PySide 6.12.0 mappings remain separate'}
    (destination/'PACKAGED_SOURCE_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    print(json.dumps(prepare(parser.parse_args().package),indent=2))
