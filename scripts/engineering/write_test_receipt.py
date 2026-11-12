"""Record actual JUnit accounting and exact tested source identities, never a QA verdict."""
from pathlib import Path
import argparse, hashlib, json, os, platform, subprocess, sys, xml.etree.ElementTree as ET
from datetime import datetime, timezone

p=argparse.ArgumentParser();p.add_argument('xml',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
root=Path(__file__).resolve().parents[2]
cases=ET.parse(a.xml).getroot().findall('.//testcase')
failures=sum(x.find('failure') is not None for x in cases)
errors=sum(x.find('error') is not None for x in cases)
skipped=sum(x.find('skipped') is not None for x in cases)
files={}
paths=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
for name in paths:
 if not name or not (name.startswith(('global_pulse/','tests/','packaging/','scripts/')) or name.endswith('.lock') or name=='pyproject.toml'):continue
 data=(root/name).read_bytes()
 files[name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}
result={'kind':'Engineering execution receipt','created_at_utc':datetime.now(timezone.utc).isoformat(),
 'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
 'python':sys.version,'platform':platform.platform(),'scope':'Full source/Qt/controller/SQLite regression; not independent QA or native desktop acceptance',
 'tests':len(cases),'failures':failures,'errors':errors,'skipped':skipped,'passed':len(cases)-failures-errors-skipped,
 'test_cases':[{'name':x.attrib.get('classname','')+'::'+x.attrib.get('name',''),
                'status':'FAIL' if x.find('failure') is not None else 'ERROR' if x.find('error') is not None else 'SKIP' if x.find('skipped') is not None else 'PASS'} for x in cases],
 'source_files':files,'workflow_run':f"https://github.com/{os.getenv('GITHUB_REPOSITORY','dietrichailabs-oss/GlobalNewsPulse')}/actions/runs/{os.getenv('GITHUB_RUN_ID','local')}",
 'independent_qa':'NOT RUN','release_approval':'NOT GRANTED'}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in {'source_files','test_cases'}},indent=2))
raise SystemExit(bool(failures or errors))
