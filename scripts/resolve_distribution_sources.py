"""Inspect exact SDK and official Qt extension artifacts without executing them."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/engineering/GP-ENG-FREEWARE-COMPLIANCE-001/upstream'
BASE = 'https://download.qt.io/online/qtsdkrepository/windows_x86/extensions/'
RECEIPTS = []


def sha(data):
    return hashlib.sha256(data).hexdigest()


def get(url, limit=400*1024*1024):
    req = urllib.request.Request(url, headers={'User-Agent':'GlobalPulse-Engineering-Compliance/1.0'})
    with urllib.request.urlopen(req, timeout=120) as response:
        if not response.url.startswith('https://'):
            raise ValueError('Non-HTTPS redirect')
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Size bound exceeded')
        RECEIPTS.append({'url':url,'final_url':response.url,'bytes':len(data),'sha256':sha(data)})
        return data


def save(name, data):
    (OUT/name).write_bytes(data)


def optional(name, url):
    try:
        save(name,get(url,4*1024*1024))
    except Exception as error:
        RECEIPTS.append({'url':url,'status':'LOOKUP_FAILED','error':str(error)[:300]})


def wheel_native(package):
    meta = json.loads((OUT/(package+'-pypi.json')).read_text())
    entry = next(x for x in meta['urls'] if x['filename'].endswith('win_amd64.whl'))
    data = get(entry['url'])
    if sha(data) != entry['digests']['sha256']:
        raise ValueError('Wheel hash mismatch')
    rows=[]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            name=PurePosixPath(item.filename).name
            if not name.lower().endswith(('.dll','.exe')):
                continue
            if item.file_size>350*1024*1024:
                raise ValueError('Native file too large')
            payload=archive.read(item)
            rows.append({'path':item.filename,'name':name,'bytes':len(payload),'sha256':sha(payload)})
    save(package+'-native-files.json',(json.dumps(rows,indent=2)+'\n').encode())
    return rows


def inspect_qt(module, wheel_rows, temp):
    directory=BASE+module+'/6120/61400/msvc2022_64/'
    package='extensions.'+module+'.6120.61400.win64_msvc2022_64'
    filename='6.12.0-0-202609281005'+module+'-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z'
    url=directory+package+'/'+filename
    optional(module+'-Updates.xml',directory+'Updates.xml')
    optional(module+'-source-Updates.xml',BASE+module+'/6120/61400/src_doc_examples/Updates.xml')
    optional(module+'-source-index.html',BASE+module+'/6120/61400/src_doc_examples/')
    archive=temp/(module+'.7z')
    archive.write_bytes(get(url))
    official_sha1=get(url+'.sha1',1024).decode().strip().split()[0]
    if hashlib.sha1(archive.read_bytes()).hexdigest()!=official_sha1:
        raise ValueError('Official Qt archive checksum mismatch')
    listing=subprocess.run(['7z','l','-slt',str(archive)],check=True,capture_output=True,text=True,timeout=120).stdout
    save(module+'-archive-list.txt',listing.encode())
    rows=[]
    names={x['name'].lower() for x in wheel_rows}
    selected=[]
    for block in listing.split('\n\n'):
        fields=dict(line.split(' = ',1) for line in block.splitlines() if ' = ' in line)
        path=fields.get('Path','')
        p=PurePosixPath(path.replace('\\','/'))
        if not path or p.is_absolute() or '..' in p.parts or ':' in path:
            continue
        # p7zip lists directories with Attributes=D, not always Folder=+.
        size=int(fields.get('Size','0'))
        if fields.get('Folder')=='+' or fields.get('Attributes','').startswith('D') or size<=0:
            continue
        name=p.name.lower()
        interesting=name in names or any(s in name for s in ('spdx','sbom','license','licence','notice','attribution')) or name in {'.tag','.gitmodules','.cmake.conf','chromium_version','config.summary'}
        if interesting and size<=350*1024*1024:
            selected.append((path,size))
    for path,size in selected:
        data=subprocess.run(['7z','x','-so','-spd',str(archive),path],check=True,capture_output=True,timeout=180).stdout
        if len(data)!=size:
            raise ValueError(f'Extracted size mismatch: {path}: expected {size}, observed {len(data)}')
        name=PurePosixPath(path.replace('\\','/')).name
        record={'path':path,'bytes':len(data),'sha256':sha(data)}
        matches=[x for x in wheel_rows if x['name'].lower()==name.lower() and x['sha256']==record['sha256']]
        record['exact_wheel_matches']=[x['path'] for x in matches]
        if size<8*1024*1024 and any(s in name.lower() for s in ('spdx','sbom','license','licence','notice','attribution')):
            evidence_name=module+'-'+re.sub(r'[^A-Za-z0-9_.-]','_',path)
            save(evidence_name,data)
            record['evidence_file']=evidence_name
        rows.append(record)
    save(module+'-sdk-wheel-comparison.json',(json.dumps(rows,indent=2)+'\n').encode())
    print('QT_BINARY_COMPARISON',module,json.dumps(rows),flush=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp)
        sdk=get('https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.net.ref/10.0.19041.57/microsoft.windows.sdk.net.ref.10.0.19041.57.nupkg',32*1024*1024)
        if sha(sdk)!='90b18f2cf7d7a23f5b0bfe2b86d8dda45881481f677ce36eccaf6e9ab50b6b4b':
            raise ValueError('SDK package identity mismatch')
        rows=[]
        with zipfile.ZipFile(io.BytesIO(sdk)) as archive:
            for name in ['lib/net8.0/Microsoft.Windows.SDK.NET.dll','lib/net8.0/WinRT.Runtime.dll']:
                data=archive.read(name)
                rows.append({'path':name,'bytes':len(data),'sha256':sha(data)})
        save('windows-sdk-exact-dlls.json',(json.dumps(rows,indent=2)+'\n').encode())
        rtf=OUT/'windows-sdk-license.rtf'
        if sha(rtf.read_bytes())!='dd07eb178e00c6bba4148457fc00ff77cd4887eb521d504186fe59c9ec8bbe62':
            raise ValueError('SDK license original mismatch')
        plain=subprocess.run(['unrtf','--text',str(rtf)],check=True,capture_output=True,timeout=30).stdout
        save('windows-sdk-license-converted.txt',plain)
        save('windows-sdk-conversion.json',(json.dumps({'input_sha256':sha(rtf.read_bytes()),'output_sha256':sha(plain),'tool':'unrtf --text','source_is_original_rtf':True},indent=2)+'\n').encode())
        inspect_qt('qtpdf',wheel_native('PySide6-Pdf'),temp)
        inspect_qt('qtwebengine',wheel_native('PySide6-WebEngine'),temp)
    save('EXACT_COMPARISON_RETRIEVAL.json',(json.dumps({'source_commit':os.environ.get('GITHUB_SHA'),'run_id':os.environ.get('GITHUB_RUN_ID'),'scope':'Binary/source-package evidence; no license clearance or product execution','resources':RECEIPTS},indent=2)+'\n').encode())


if __name__=='__main__':
    main()
