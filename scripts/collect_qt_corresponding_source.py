"""Pin official corresponding source and retain exact comparison distinctions.

Vendor Windows SPDX paths/EOLs are reconciled without changing source bytes.
The only reviewed export differences are pinned .tag and VCS-only metadata.
Unknown source/code/notice changes still stop preparation. No release approval.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import urllib.request
from source_inventory import SOURCE_COMMIT, parse_source_spdx, compare_source_bytes, reviewed_missing

ROOT=Path(__file__).resolve().parents[1]
UP=ROOT/'docs/engineering/GP-ENG-FREEWARE-COMPLIANCE-001/upstream'
DEST=ROOT/'packaging/licenses/qt-webengine-pdf'
SOURCE={'name':'Qt WebEngine / Qt PDF 6.140.0-rc complete source',
        'url':'https://download.qt.io/development_releases/qtwebengine/6.140.0-rc/qtwebengine-everywhere-src-6.140.0-rc.tar.xz',
        'bytes':580351144,'sha256':'61257967afd9803a1db6403e86ea25c4efff8fad479bda365a9d81bfd709f621',
        'git_commit':SOURCE_COMMIT,'git_tag':'v6.140.0-rc',
        'repository':'https://code.qt.io/qt/qtwebengine.git',
        'scope':'Qt WebEngine and Qt PDF, including bundled Chromium/PDFium source'}


def file_record(path):
    with path.open('rb') as stream:
        return {'bytes':path.stat().st_size,'sha256':hashlib.file_digest(stream,'sha256').hexdigest()}


def main():
    proof=json.loads((UP/'QT_PE_SIGNATURE_ONLY_COMPARISON.json').read_text())
    if proof['total']!=10 or proof['equivalent']!=10 or not all(r['same_except_signature_metadata'] and r['all_sections_identical'] for r in proof['comparisons']):
        raise ValueError('Exact executable-byte relationship not established')
    DEST.mkdir(parents=True,exist_ok=True)
    documents={}
    for path in sorted(UP.glob('*-sbom_*')):
        target=DEST/path.name; shutil.copyfile(path,target); documents[target.name]=file_record(target)
    for name in ['QT_PE_SIGNATURE_ONLY_COMPARISON.json','EXACT_COMPARISON_RETRIEVAL.json']:
        shutil.copyfile(UP/name,DEST/name); documents[name]=file_record(DEST/name)
    for module in ['qtwebengine','qtpdf']:
        sbom=json.loads((UP/(module+'-sbom_'+module+'-6.140.0.spdx.json')).read_text())
        package=next(p for p in sbom['packages'] if p['name']==module)
        if not package['downloadLocation'].endswith('@'+SOURCE_COMMIT):
            raise ValueError('SDK source revision does not match pinned source')
    source_checks=parse_source_spdx((UP/'qtwebengine-sbom_qtwebengine-6.140.0.source.spdx').read_text())
    notices=[]; comparisons=[]; seen=set(); expanded=0; notice_bytes=0; tag_verified=False
    with tempfile.TemporaryDirectory() as temporary:
        archive=Path(temporary)/'source.tar.xz'
        request=urllib.request.Request(SOURCE['url'],headers={'User-Agent':'GlobalPulse-Engineering-Compliance/1.0'})
        hasher=hashlib.sha256(); downloaded=0
        with urllib.request.urlopen(request,timeout=120) as response, archive.open('wb') as output:
            if not response.url.startswith('https://'): raise ValueError('Non-HTTPS source redirect')
            while chunk:=response.read(1024*1024):
                downloaded+=len(chunk)
                if downloaded>SOURCE['bytes']: raise ValueError('Source archive size changed')
                output.write(chunk); hasher.update(chunk)
        if downloaded!=SOURCE['bytes'] or hasher.hexdigest()!=SOURCE['sha256']:
            raise ValueError('Official corresponding-source archive digest mismatch')
        with tarfile.open(archive,mode='r|xz') as source:
            for member in source:
                if not member.isfile(): continue
                expanded+=member.size
                if expanded>12*1024**3: raise ValueError('Expanded source bound exceeded')
                p=PurePosixPath(member.name); parts=p.parts
                if p.is_absolute() or '..' in parts or not parts: raise ValueError('Unexpected source member path')
                if parts[0].startswith('qtwebengine-everywhere-src-'): parts=parts[1:]
                relative='/'.join(parts); base=parts[-1].lower()
                is_notice=base.startswith(('license','licence','copying','notice','copyright')) or base.endswith('.license')
                needs_check=relative in source_checks
                if not is_notice and not needs_check: continue
                if member.size>4*1024*1024: raise ValueError('Oversized notice/check file: '+relative)
                data=source.extractfile(member).read()
                if needs_check:
                    if relative in seen: raise ValueError('Duplicate source member: '+relative)
                    seen.add(relative)
                    comparisons.append(compare_source_bytes(relative,data,source_checks[relative]))
                    if relative=='.tag':tag_verified=data==(SOURCE_COMMIT+'\n').encode('ascii')
                if is_notice:
                    notice_bytes+=len(data)
                    if notice_bytes>32*1024*1024: raise ValueError('Source notice aggregate bound exceeded')
                    try: content=data.decode('utf-8'); encoding='utf-8'
                    except UnicodeDecodeError: content=data.decode('latin-1'); encoding='latin-1'
                    if '\x00' in content: raise ValueError('Binary license-like member requires review: '+relative)
                    notices.append({'path':relative,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'encoding':encoding,'text':content})
    omitted=reviewed_missing(source_checks,seen)
    exact=[r for r in comparisons if r['comparison']=='EXACT_BYTES']
    checkout=[r for r in comparisons if r['comparison']=='WINDOWS_CHECKOUT_EOL']
    metadata=[r for r in comparisons if r['comparison']=='REVIEWED_RELEASE_MARKER_DIFFERENCE']
    if not notices or not exact or not tag_verified or len(comparisons)!=len(source_checks)-len(omitted):
        raise ValueError('Incomplete source mapping')
    comparison_record={'schema_version':1,'source_commit':SOURCE_COMMIT,'source_archive_sha256':SOURCE['sha256'],
                       'exact_bytes':len(exact),'windows_checkout_eol':len(checkout),
                       'reviewed_metadata_differences':metadata,'omitted_vcs_metadata':omitted,
                       'unresolved_differences':[], 'files':comparisons}
    (DEST/'SOURCE_COMPARISON.json').write_text(json.dumps(comparison_record,indent=2)+'\n',encoding='utf-8')
    documents['SOURCE_COMPARISON.json']=file_record(DEST/'SOURCE_COMPARISON.json')
    header=('THIRD-PARTY SOURCE NOTICES — Qt WebEngine / Qt PDF 6.140.0-rc\n'
            'Source: '+SOURCE['url']+'\nSHA-256: '+SOURCE['sha256']+'\n'
            'Overinclusive corresponding-source notice collection; not every source-tree component is shipped. '
            'Vendor component inventories identify built components. These texts do not relicense Global Pulse.\n\n')
    aggregate=header+''.join('\n'+'='*78+'\nSOURCE FILE: '+n['path']+'\nSHA-256: '+n['sha256']+'\n\n'+n['text']+'\n' for n in notices)
    (DEST/'SOURCE-NOTICES.txt').write_text(aggregate,encoding='utf-8')
    documents['SOURCE-NOTICES.txt']=file_record(DEST/'SOURCE-NOTICES.txt')
    receipt={'schema_version':2,'source_archive':SOURCE,'source_download_verified':True,
             'source_sbom_files_compared':len(exact)+len(checkout),'source_sbom_exact_bytes':len(exact),
             'source_sbom_windows_checkout_eol':len(checkout),'source_sbom_mismatches':[],
             'reviewed_source_metadata_differences':metadata,'source_sbom_files_not_in_archive':omitted,
             'source_tag_verified':tag_verified,
             'notice_files':[{k:v for k,v in n.items() if k!='text'} for n in notices],
             'notice_bytes':notice_bytes,'proof_source_commit':proof['source_commit'],'proof_run_id':proof['run_id'],
             'binary_relationship':'10 native binaries identical outside Authenticode table, its directory entry and PE checksum; raw files remain distinct and unmodified',
             'certificate_trust':'NOT_EVALUATED_BY_SOURCE_MAPPING','documents':documents,
             'status':'ENGINEERING_CORRESPONDING_SOURCE_IDENTIFIED_PENDING_INDEPENDENT_QA',
             'public_release':'NOT_APPROVED'}
    (DEST/'SOURCE_MAP.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'source':SOURCE,'exact_source_files':len(exact),'windows_checkout_eol_files':len(checkout),
                     'reviewed_metadata_differences':metadata,'omitted_vcs_metadata':omitted,
                     'notices':len(notices),'notice_bytes':notice_bytes,'status':receipt['status']},indent=2),flush=True)


if __name__=='__main__':main()
