"""One-shot deterministic preparation of the reviewed freeware compliance patch.

Runs only on the isolated Engineering branch. Checks original blobs before
editing and never changes dependency locks, native binaries, or the accepted PR.
The generated patch is committed before Windows validation; generation is not a
release or an independent QA decision.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
UP=ROOT/'docs/engineering/GP-ENG-FREEWARE-COMPLIANCE-001/upstream'
EXPECTED={
 'scripts/build_windows.ps1':'b45087bc8ffd25efe792fe069423da75cda443dd',
 'global_pulse/__main__.py':'6b24bef921b909c3f8b98871da78c6774bbbb3a7',
 'packaging/GlobalPulse.iss':'913492d448ef63765c310d8382e6d82e59597e4e',
 '.github/workflows/windows-private-candidate.yml':'1724f07a477844a825245b38bc3d249d2e324f1c',
 'scripts/sdk_distribution.py':'1494876b8f011efb479799771246cacb73ad26e0',
 'global_pulse/distribution_terms.py':'7fff1f0b997270223917f142dc8c63d95f1a4246',
 'tests/test_sdk_distribution.py':'dba842d5d67ec9bc66704494dfd2600c360b2824',
}
SDK_ASSETS={
 'Microsoft.Windows.SDK.NET.dll':{'bytes':24877600,'sha256':'0ec371d93798852e36461c8adddbeadce0f963a04752f0b64e54fe19c1c834a7'},
 'WinRT.Runtime.dll':{'bytes':528944,'sha256':'bcf3a14e8712a90837fc5c0d8c8a24696af2bd7f74e9767597ec81ededfb23db'},
}


def record(path):
 data=path.read_bytes()
 return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def replace(path,old,new,count=1):
 file=ROOT/path; text=file.read_text(encoding='utf-8')
 if text.count(old)!=count: raise ValueError('Unexpected edit target: '+path+' / '+repr(old))
 file.write_text(text.replace(old,new),encoding='utf-8',newline='\n')


def write_json(path,value):
 path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def main():
 for path,expected in EXPECTED.items():
  actual=subprocess.check_output(['git','hash-object',path],cwd=ROOT,text=True).strip()
  if actual!=expected: raise ValueError('Unreviewed patch input: '+path)
 sdk=ROOT/'packaging/licenses/windows-sdk'; sdk.mkdir(parents=True,exist_ok=True)
 for name,original,expected in [
  ('SDK_LICENSE.rtf','windows-sdk-license.rtf','dd07eb178e00c6bba4148457fc00ff77cd4887eb521d504186fe59c9ec8bbe62'),
  ('SDK_REDIST.html','windows-sdk-redist.html','e0c8f0dc979f8703374bcd21ed16e65a90fab5986e1cc4241fca05ff20525d10')]:
  if record(UP/original)['sha256']!=expected: raise ValueError('Official SDK evidence changed')
  shutil.copyfile(UP/original,sdk/name)
 converted=(UP/'windows-sdk-license-converted.txt').read_text(encoding='utf-8')
 conversion=json.loads((UP/'windows-sdk-conversion.json').read_text())
 if record(UP/'windows-sdk-license-converted.txt')['sha256']!=conversion['output_sha256']:
  raise ValueError('SDK text conversion identity mismatch')
 terms='''GLOBAL PULSE — MICROSOFT NOTIFICATION COMPONENT TERMS

Global Pulse is provided free of charge by Dietrich AI Labs.

These terms concern only the bundled Microsoft Windows SDK projection used by
Global Pulse's Windows notification helper. They do not place the application,
Qt, PySide, Chromium, PDFium, or other separately licensed components under a
Microsoft license. Each third-party component keeps its own license and notices.
In particular, no provision here restricts the replacement, modification,
relinking, or reverse-engineering rights granted for an LGPL-covered component.

The Microsoft component is supplied as unmodified object code as part of this
Windows application, solely for the application's use of Windows APIs. Microsoft
copyright and other notices must be preserved. No Microsoft endorsement is claimed.
Use of the Microsoft component is subject to the applicable Microsoft terms
reproduced below. To the extent a restriction is unenforceable under applicable
law, that law controls. Do not use or redistribute the Microsoft component outside
its permitted scope or under a license that overrides Microsoft's conditions.

By choosing Agree for the Microsoft component, you agree to the protections and
conditions of the Microsoft component terms below. Declining in the application
leaves ordinary news and local alert history available, but does not start the
Windows notification helper. Acceptance is stored locally for this exact text;
there is no account, payment, telemetry, or online acceptance request.

The following is a readable conversion of the original Microsoft terms linked
by the exact NuGet package. The original SDK_LICENSE.rtf is included alongside
this file and remains the authoritative original. SDK_REDIST.html preserves the
official permitted-file list, including Microsoft.Windows.SDK.NET.Ref.

--- ORIGINAL MICROSOFT TERMS (READABLE CONVERSION) ---

'''+converted
 (sdk/'SDK_TERMS.txt').write_text(terms,encoding='utf-8-sig')
 notice='''Microsoft Windows SDK for .NET projection — distribution evidence

Package: Microsoft.Windows.SDK.NET.Ref 10.0.19041.57
Copyright (c) Microsoft Corporation. All rights reserved.
Official package: https://www.nuget.org/packages/Microsoft.Windows.SDK.NET.Ref/10.0.19041.57
Governing terms: https://aka.ms/WinSDKLicenseURL
Permitted-file list: https://learn.microsoft.com/en-us/legal/windows-sdk/redist

The official REDIST list permits unmodified listed projection DLLs to accompany
an application that calls Windows Runtime APIs, subject to the SDK terms.
Global Pulse provides significant primary news-monitoring functionality and uses
these files only for its Windows notification component. This is not an SDK
resale, stand-alone SDK distribution, MIT relicensing, or Microsoft endorsement.

The build verifies the exact NuGet archive and both selected original/published
DLL identities. Installer and first native-component use expose the accompanying
component-specific terms. Microsoft terms do not override separately licensed
LGPL/GPL components. Distributor responsibilities, including the agreement's
indemnity and downstream-protection requirements, continue to apply; being free
of charge is not a waiver. No new developer agreement is accepted by this script.

Independent QA must verify the final candidate. This notice is evidence and
implementation documentation, not a legal opinion or public-release approval.
'''
 (sdk/'SDK_COMPONENT_NOTICE.txt').write_text(notice,encoding='utf-8')
 bundle={'schema_version':1,'sdk_version':'10.0.19041.57',
  'sdk_archive_sha256':'90b18f2cf7d7a23f5b0bfe2b86d8dda45881481f677ce36eccaf6e9ab50b6b4b',
  'assets':SDK_ASSETS,'documents':{p.name:record(p) for p in sdk.iterdir() if p.is_file() and p.name!='BUNDLE.json'},
  'official_license_url':'https://aka.ms/WinSDKLicenseURL',
  'official_redist_url':'https://learn.microsoft.com/en-us/legal/windows-sdk/redist',
  'status':'ENGINEERING_IMPLEMENTATION_PENDING_EXACT_WINDOWS_BUILD_AND_QA'}
 write_json(sdk/'BUNDLE.json',bundle)
 replace('scripts/sdk_distribution.py',"ASSETS = {'Microsoft.Windows.SDK.NET.dll', 'WinRT.Runtime.dll'}", "ASSETS = {'Microsoft.Windows.SDK.NET.dll', 'WinRT.Runtime.dll'}\nSDK_ASSET_PINS = "+repr(SDK_ASSETS))
 replace('scripts/sdk_distribution.py',"if set(bundle.get('assets', {})) != ASSETS:","if bundle.get('assets') != SDK_ASSET_PINS:")
 replace('tests/test_sdk_distribution.py',"    archive=b'FAKE NUGET ARCHIVE FOR UNIT TEST ONLY'", "    monkeypatch.setattr(sdk,'SDK_ASSET_PINS',{name:record(data) for name,data in assets.items()})\n    archive=b'FAKE NUGET ARCHIVE FOR UNIT TEST ONLY'")
 replace('global_pulse/distribution_terms.py',"    if record.get('sdk_version') != '10.0.19041.57':", "    if not isinstance(record, dict) or not isinstance(record.get('documents'), dict):\n        raise ValueError('Malformed Microsoft component terms record')\n    if record.get('sdk_version') != '10.0.19041.57':")
 replace('global_pulse/distribution_terms.py',"    if len(data) != expected.get('bytes') or identity != expected.get('sha256'):","    if not isinstance(expected, dict) or len(data) != expected.get('bytes') or identity != expected.get('sha256'):")
 replace('global_pulse/distribution_terms.py',"    return dialog.exec() == QDialog.DialogCode.Accepted", "    accepted = dialog.exec() == QDialog.DialogCode.Accepted\n    dialog.deleteLater()\n    return accepted")
 replace('global_pulse/__main__.py','        def begin():\n            notifier.start()',
  '        def begin():\n            from .distribution_terms import accept_windows_sdk_terms\n            if accept_windows_sdk_terms(controller, window):\n                notifier.start()\n            else:\n                notifier.status_changed.emit("Windows notifications off — Microsoft component terms not accepted")')
 replace('packaging/GlobalPulse.iss','[Setup]\n','[Setup]\nInfoBeforeFile={#PackageRoot}\\notifications\\licenses\\windows-sdk\\SDK_TERMS.txt\n')
 replace('scripts/build_windows.ps1',"    Write-Host 'Freezing the application from the explicit PyInstaller specification.'", "    Write-Host 'Verifying exact Microsoft SDK redistribution evidence and unmodified payloads.'\n    Invoke-Checked -File $buildPython -Arguments @(\n        'scripts\\sdk_distribution.py', '--deps',$depsPath,\n        '--nuget-root',$nugetRoot, '--published',$nativeRoot\n    )\n\n    Write-Host 'Freezing the application from the explicit PyInstaller specification.'")
 replace('scripts/build_windows.ps1',"    Invoke-Checked -File $buildPython -Arguments @($helper,'scan',$packageRoot)","    Invoke-Checked -File $buildPython -Arguments @('scripts\\qt_distribution.py','--package',$packageRoot)\n    Invoke-Checked -File $buildPython -Arguments @($helper,'scan',$packageRoot)")
 path='.github/workflows/windows-private-candidate.yml'
 replace(path,'branches: [eng/e2-qa-corrections-20261108, eng/release-integration-20261110]',
  'branches: [eng/e2-qa-corrections-20261108, eng/release-integration-20261110, eng/freeware-compliance-20261110]')
 replace(path,"|| github.ref == 'refs/heads/eng/release-integration-20261110')", "|| github.ref == 'refs/heads/eng/release-integration-20261110' || github.ref == 'refs/heads/eng/freeware-compliance-20261110')")
 replace(path,"        if: github.ref == 'refs/heads/eng/release-integration-20261110'", "        if: github.ref == 'refs/heads/eng/release-integration-20261110' || github.ref == 'refs/heads/eng/freeware-compliance-20261110'")
 replace(path,"github.ref != 'refs/heads/eng/release-integration-20261110'", "github.ref != 'refs/heads/eng/release-integration-20261110' && github.ref != 'refs/heads/eng/freeware-compliance-20261110'",count=3)
 qt=ROOT/'packaging/licenses/qt-webengine-pdf'
 source=json.loads((qt/'SOURCE_MAP.json').read_text())
 oldpath=ROOT/'packaging/licenses/QT-WEBENGINE-PDF-6.140-SOURCE-STATUS.json'
 historical=json.loads(oldpath.read_text())
 write_json(oldpath,{'schema_version':2,'component_line':'Qt WebEngine / Qt PDF 6.140',
  'source_commit':source['source_archive']['git_commit'],'source_archive':source['source_archive'],
  'evidence_bundle':'qt-open-source/corresponding-source/SOURCE_MAP.json',
  'binary_relationship':source['binary_relationship'],
  'decision':'CORRESPONDING_SOURCE_IDENTIFIED_ENGINEERING_CHECK_PENDING_INDEPENDENT_QA',
  'reason':'The exact official SDK source inventory identifies the RC commit. All ten compared wheel binaries match that SDK executable payload outside signing metadata. A final-named tag is not assumed or required for this observed build.',
  'historical_unresolved_lookup':historical,'public_release':'NOT_APPROVED'})
 compliance=ROOT/'packaging/licenses/QT-6.12.0-OPEN-SOURCE-COMPLIANCE.json'
 document=json.loads(compliance.read_text())
 document['schema_version']=3
 document['exact_source_archives'].append(source['source_archive'])
 document['webengine_pdf_release_line']['corresponding_source_status']='Exact official RC source pinned and downloaded; vendor SDK SBOM and signature-only executable relationship verified; independent QA pending'
 document['webengine_inventory']['complete_inventory_status']='Vendor SPDX component inventories and corresponding-source notice texts bundled under qt-open-source/corresponding-source; QA pending'
 document['status']='ENGINEERING SOURCE MAPPING AND SDK DISTRIBUTION IMPLEMENTATION PREPARED; EXACT WINDOWS BUILD AND INDEPENDENT QA REQUIRED'
 write_json(compliance,document)
 current='''# Current freeware compliance candidate — 2026-11-10

Global Pulse is provided free of charge. This does not change the application's
source-code licensing or remove third-party obligations.

WebEngine/PDF 6.140 source is identified as official RC commit
`d505fc23640d2bd6345e6483eb73daf4e19f5829`. The complete source archive, exact
SHA-256, vendor build/component inventories, source-file checks and bundled
notices are recorded in `licenses/qt-open-source/corresponding-source/SOURCE_MAP.json`.
The raw SDK and wheel binaries are distinct signed files; their compared executable
payloads are identical. No library was changed or downgraded. The earlier failure
to locate a final-named tag is historical, not a continuing reason to wait for one.

The Windows SDK permission is documented by Microsoft's official REDIST list and
the exact package-linked SDK license. Its selected DLLs remain unmodified. The
installer exposes the included Microsoft-only terms, and first native-notification
use requires affirmative local acceptance of their exact text. Declining does not
prevent news or local alert-history use. These terms do not restrict LGPL library
replacement/modification/relinking or reverse engineering to debug modifications.

These are Engineering changes, not independent QA acceptance or public-release
authorization. Prior accepted PR #12 remains frozen. The changed candidate needs
its own exact package checks; physical Windows/client tests remain separate.

---

'''
 for name in ['docs/THIRD_PARTY_NOTICES.md','docs/KNOWN_LIMITATIONS.md']:
  file=ROOT/name; file.write_text(current+'# Historical preceding candidate record\n\n'+file.read_text(encoding='utf-8'),encoding='utf-8')
 for name in ['docs/USER_GUIDE.md','docs/SETTINGS_ALERTS.md']:
  file=ROOT/name; file.write_text(file.read_text(encoding='utf-8')+'\n\n'+current.split('---')[0],encoding='utf-8')
 noticepath=ROOT/'packaging/licenses/QT-6.12.0-OPEN-SOURCE-NOTICE.md'
 noticepath.write_text(current+'## Earlier candidate notice (historical)\n\n'+noticepath.read_text(encoding='utf-8'),encoding='utf-8')
 reference=ROOT/'packaging/licenses/Microsoft.Windows.SDK.NET.Ref-10.0.19041.57-LICENSE-REFERENCE.txt'
 reference.write_text('''Microsoft Windows SDK projection 10.0.19041.57 — current evidence route

Official terms: https://aka.ms/WinSDKLicenseURL
Official REDIST list: https://learn.microsoft.com/en-us/legal/windows-sdk/redist

The original external-only reference has been superseded in this candidate by
bundled original terms, the official permitted-file list, and exact unmodified
NuGet/published DLL verification. See notifications/licenses/windows-sdk and
NATIVE_PACKAGE_NOTICES.json for the actual generated record. A missing or changed
bundle/asset fails the build. Independent QA remains required. This reference by
itself is not a grant and cannot substitute for those generated checks.
''',encoding='utf-8')
 instructions='''# Accessing and replacing the LGPL libraries

Global Pulse uses dynamically loaded Qt/PySide libraries. Their original licenses,
source inventories and notices are included; the application's own source license
is not selected by this dependency bundle.

The exact WebEngine/PDF source archive is publicly obtainable at:
'''+source['source_archive']['url']+'\n\nSHA-256: `'+source['source_archive']['sha256']+'`\n\n'+'''It includes the corresponding Qt WebEngine/PDF and bundled Chromium/PDFium sources.
Vendor SPDX files preserve source provenance and build configuration. The core Qt
and PySide binding source identities remain in QT-6.12.0-OPEN-SOURCE-COMPLIANCE.json.

Before public binary distribution, provide equivalent, no-charge access to these
source archives alongside the downloads and keep that access available. A private
GitHub link is not a public source offer; no source mirror is claimed published by
this preparation. The pinned public upstream URLs are included for exact retrieval.

To replace libraries: Exit Completely; back up the per-user installed directory;
build an ABI-compatible modified Qt/PySide version using the corresponding source
and the recorded platform/build configuration; replace the separate libraries and
matching plugins/resources in _internal/PySide6; then restart. Global Pulse imposes
no runtime signature/hash check preventing compatible modified Qt libraries. Build
pipeline hash checks protect release provenance, not an end user's modification.
Reverse engineering for debugging such modifications is not prohibited by Global
Pulse's component notice. Do not modify the separately licensed Microsoft files
under this LGPL permission. New library builds still require ABI compatibility.
'''
 (qt/'SOURCE-AND-REPLACEMENT.md').write_text(instructions,encoding='utf-8')
 plan=ROOT/'docs/engineering/GP-ENG-FREEWARE-COMPLIANCE-001/PLAN.md'
 plan.write_text(plan.read_text().replace('https://learn.microsoft.com/en-us/legal/windows-sdk/redist#microsofwindows-sd-kne-tref','https://learn.microsoft.com/en-us/legal/windows-sdk/redist'),encoding='utf-8')
 print('Prepared SDK terms, exact asset checks, source bundle, installer/first-use integration and canonical Windows validation route. No release approval.')


if __name__=='__main__':
 main()