"""Read-only PE comparison; exclude only Authenticode table and PE checksum.

Never executes, modifies, signs, or repackages any downloaded binary. A mismatch
remains a mismatch; linker timestamps, code, resources and debug data stay in the
comparison. This evidence is not a certificate trust validation.
"""
from __future__ import annotations
import io
import json
import os
from pathlib import Path, PurePosixPath
import struct
import subprocess
import tempfile
import zipfile
from resolve_distribution_sources import OUT, get, sha, save, RECEIPTS


def pe_identity(data):
    if data[:2] != b'MZ' or len(data)<128:
        raise ValueError('Not a bounded PE image')
    nt=struct.unpack_from('<I',data,60)[0]
    if nt>len(data)-264 or data[nt:nt+4]!=b'PE\0\0':
        raise ValueError('Invalid PE header')
    opt=nt+24
    magic=struct.unpack_from('<H',data,opt)[0]
    if magic not in (0x10b,0x20b):
        raise ValueError('Unsupported PE optional header')
    check=opt+64
    directory=opt+(112 if magic==0x20b else 96)
    sec=directory+4*8
    offset,size=struct.unpack_from('<II',data,sec)
    if not offset or not size or offset%8 or offset<sec+8 or offset+size!=len(data):
        raise ValueError('Certificate must be an aligned final table; no arbitrary overlay is excluded')
    nsections=struct.unpack_from('<H',data,nt+6)[0]
    optional_size=struct.unpack_from('<H',data,nt+20)[0]
    table=opt+optional_size
    sections=[]
    for index in range(nsections):
        row=table+40*index
        if row+40>offset:
            raise ValueError('Section table outside unsigned payload')
        rawsize,rawpos=struct.unpack_from('<II',data,row+16)
        if rawpos+rawsize>offset:
            raise ValueError('Section overlaps certificate')
        sections.append({'name':data[row:row+8].split(b'\0')[0].decode('ascii','replace'),
                         'offset':rawpos,'bytes':rawsize,'sha256':sha(data[rawpos:rawpos+rawsize])})
    unsigned=bytearray(data[:offset])
    unsigned[check:check+4]=b'\0'*4
    unsigned[sec:sec+8]=b'\0'*8
    return {'raw_sha256':sha(data),'bytes':len(data),'unsigned_sha256':sha(unsigned),
            'excluded_ranges':[{'offset':check,'bytes':4,'kind':'PE checksum'},
                               {'offset':sec,'bytes':8,'kind':'certificate-table directory'},
                               {'offset':offset,'bytes':size,'kind':'final Authenticode table'}],
            'sections':sections}


def main():
    prior=json.loads((OUT/'EXACT_COMPARISON_RETRIEVAL.json').read_text())
    rows=[]
    with tempfile.TemporaryDirectory() as tmp:
        for module,distribution in [('qtpdf','PySide6-Pdf'),('qtwebengine','PySide6-WebEngine')]:
            meta=json.loads((OUT/(distribution+'-pypi.json')).read_text())
            entry=next(x for x in meta['urls'] if x['filename'].endswith('win_amd64.whl'))
            wheel_bytes=get(entry['url'])
            if sha(wheel_bytes)!=entry['digests']['sha256']:
                raise ValueError('Exact wheel hash differs')
            wheel=zipfile.ZipFile(io.BytesIO(wheel_bytes))
            evidence=next(x for x in prior['resources'] if x['url'].endswith('.7z') and '/'+module+'/' in x['url'])
            archive=Path(tmp)/(module+'.7z')
            archive.write_bytes(get(evidence['url']))
            if sha(archive.read_bytes())!=evidence['sha256']:
                raise ValueError('SDK archive changed')
            comparisons=json.loads((OUT/(module+'-sdk-wheel-comparison.json')).read_text())
            for record in comparisons:
                path=record['path']
                name=PurePosixPath(path).name
                if not name.lower().endswith(('.dll','.exe')):
                    continue
                matches=[x for x in wheel.namelist() if PurePosixPath(x).name.lower()==name.lower()]
                if len(matches)!=1:
                    raise ValueError('Ambiguous or missing wheel binary: '+name)
                sdk=subprocess.run(['7z','x','-so','-spd',str(archive),path],check=True,capture_output=True,timeout=180).stdout
                if sha(sdk)!=record['sha256']:
                    raise ValueError('SDK extraction identity changed')
                a,b=pe_identity(sdk),pe_identity(wheel.read(matches[0]))
                rows.append({'module':module,'sdk_path':path,'wheel_path':matches[0],
                             'sdk':a,'wheel':b,'same_except_signature_metadata':a['unsigned_sha256']==b['unsigned_sha256'],
                             'all_sections_identical':a['sections']==b['sections']})
    report={'source_commit':os.environ.get('GITHUB_SHA'),'run_id':os.environ.get('GITHUB_RUN_ID'),
            'method':'Only final certificate table, its directory entry and PE checksum excluded; no file changed',
            'comparisons':rows,'total':len(rows),'equivalent':sum(r['same_except_signature_metadata'] for r in rows),
            'certificate_trust':'NOT_EVALUATED','decision':'EVIDENCE_ONLY_PENDING_QA'}
    save('QT_PE_SIGNATURE_ONLY_COMPARISON.json',(json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps({'total':report['total'],'equivalent':report['equivalent'],'files':[{'path':r['sdk_path'],'equivalent':r['same_except_signature_metadata'],'sections':r['all_sections_identical']} for r in rows]},indent=2))


if __name__=='__main__':
    main()
