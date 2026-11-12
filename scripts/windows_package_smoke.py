"""Bounded, offline frozen/installer smoke in an explicitly supplied disposable directory.

Run only on the authorized Windows engineering runner. This is not interactive
notification, standard-user, mixed-monitor, third-party media, or independent QA.
The installer is per-user; no machine security settings or production data change.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):h.update(b)
    return h.hexdigest()


def run(args, timeout=90):
    env=os.environ.copy()
    # Exercise the actual Windows platform plugin, not Qt's headless font path.
    env['QT_QPA_PLATFORM']='windows'
    p=subprocess.run([str(x) for x in args],env=env,timeout=timeout,capture_output=True)
    if p.returncode:
        # Do not copy unknown private contents; this runner uses only controlled data.
        raise RuntimeError(f'{Path(args[0]).name} exited {p.returncode}; stderr={p.stderr[-2000:].decode("utf-8", "replace")}')
    return p


def inspect_png(path):
    data=path.read_bytes()
    if len(data)<1000 or data[:8]!=b'\x89PNG\r\n\x1a\n':raise AssertionError('Actual Qt PNG not produced')
    width,height=struct.unpack('>II',data[16:24])
    if width<960 or height<640:raise AssertionError('Unexpectedly small dashboard')
    return {'path':path.name,'bytes':len(data),'sha256':sha(path),'width':width,'height':height}


def snapshot(exe, root, label):
    data=root/(label+'-data'); image=root/(label+'.png')
    run([exe,'--no-start','--skip-setup','--data-dir',data,'--snapshot',image])
    database=data/'global-pulse.sqlite3'
    with sqlite3.connect(database) as db:
        for table in ('reports','events','alerts','observations'):
            if db.execute('SELECT count(*) FROM '+table).fetchone()[0]!=0:raise AssertionError('Fresh archive is not empty')
    diagnostics_path = image.with_suffix('.json')
    diagnostics = json.loads(diagnostics_path.read_text(encoding='utf-8'))
    if diagnostics.get('platform_backend') != 'windows':
        raise AssertionError('Frozen snapshot did not use the native Windows platform backend')
    if not diagnostics.get('image_saved') or not diagnostics.get('ascii_font_coverage'):
        raise AssertionError('Snapshot font/glyph diagnostic failed; inspect preserved evidence')
    for card in diagnostics.get('status_cards', {}).values():
        if card['viewport_height'] < 3 * card['line_spacing']:
            raise AssertionError('Visible intelligence card lacks three usable text lines')
    return {**inspect_png(image), 'diagnostics': diagnostics,
            'diagnostics_sha256': sha(diagnostics_path),
            'visual_acceptance': 'PENDING image inspection; glyph coverage alone is not visual acceptance'}


def synthetic_selected_snapshot(exe, root, label, fixture, size):
    """Actual frozen Windows snapshot of a deliberately populated, isolated demo.

    The controlled source fixture remains outside the installed package. This does
    not exercise live collection, media, notifications or independent GUI review.
    """
    if not fixture.is_file():
        raise AssertionError('Required checked-in synthetic fixture unavailable')
    data=root/(label+'-data'); image=root/(label+'.png')
    run([exe, '--demo', '--fixture', fixture, '--snapshot-first-fixture-event',
         '--snapshot-size', f'{size[0]}x{size[1]}', '--no-start', '--skip-setup',
         '--data-dir', data, '--snapshot', image])
    diagnostics_path=image.with_suffix('.json')
    diagnostics=json.loads(diagnostics_path.read_text(encoding='utf-8'))
    if diagnostics.get('platform_backend') != 'windows':
        raise AssertionError('Selected synthetic capture did not use native Windows backend')
    if (not diagnostics.get('image_saved') or not diagnostics.get('ascii_font_coverage')
            or not diagnostics.get('synthetic_fixture') or not diagnostics.get('synthetic_selected_event')
            or not diagnostics.get('synthetic_banner_visible')):
        raise AssertionError('Synthetic selection, banner or font coverage not proven')
    if diagnostics.get('requested_snapshot_size') != list(size):
        raise AssertionError('Synthetic snapshot request identity mismatch')
    if size == (960, 640) and diagnostics.get('window_size') != [960, 640]:
        raise AssertionError('Native minimum-size viewport was not actually displayed')
    # Demo mode writes a separate synthetic.sqlite3 archive, never the live one.
    # Verify the expected file before connecting, so SQLite cannot silently
    # create an empty live-named archive and obscure the actual test result.
    synthetic_db = data/'synthetic.sqlite3'
    if not synthetic_db.is_file() or (data/'global-pulse.sqlite3').exists():
        raise AssertionError('Isolated synthetic archive missing or live archive created')
    with sqlite3.connect(synthetic_db) as db:
        counts = {table: db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                  for table in ('reports', 'events')}
    if not all(counts.values()):
        raise AssertionError('Synthetic scenario was not actually populated')
    for card in diagnostics.get('status_cards', {}).values():
        if card['viewport_height'] < 3 * card['line_spacing']:
            raise AssertionError('Synthetic selected event clipped a status-card text viewport')
    return {**inspect_png(image), 'diagnostics': diagnostics, 'diagnostics_sha256': sha(diagnostics_path),
            'synthetic_record_counts': counts,
            'visual_acceptance': 'PENDING independent comparison of this synthetic selected-event image'}


def check_installed_payload(runtime, installed):
    manifest=json.loads((runtime/'MANIFEST.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        p=installed/item['path']
        if not p.is_file() or p.stat().st_size!=item['bytes'] or sha(p)!=item['sha256']:
            raise AssertionError('Installed payload differs: '+item['path'])
    if sha(installed/'MANIFEST.json')!=sha(runtime/'MANIFEST.json'):raise AssertionError('Installed manifest differs')
    return len(manifest['files'])


def worker_route(exe, root):
    data=root/'worker-data'; job=data/'translation-jobs'/'job-smoke'
    job.mkdir(parents=True)
    request={'data_dir':str(data),'work_dir':str(job),'language':'unsupported-test-model',
             'text':'Isolated smoke; no translation model download.','install':False}
    (job/'request.json').write_text(json.dumps(request),encoding='utf-8')
    p=subprocess.run([str(exe),'--translation-worker','--job',str(job)],timeout=30,capture_output=True)
    response=json.loads((job/'response.json').read_text(encoding='utf-8'))
    if p.returncode!=1 or response!={'text':'','error':'ValueError'}:
        raise AssertionError('Frozen owned-worker route did not reject unsupported model')
    # This narrowly tests dispatch/exit/no-model path, not model inference quality.
    return {'status':'PASS','exit_code':p.returncode,'scope':'Frozen worker dispatch, bounded error result, no network/model inference'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True,type=Path)
    parser.add_argument('--installer',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if sys.platform!='win32':parser.error('Windows-only engineering smoke')
    runtime=args.runtime.resolve(strict=True); installer=args.installer.resolve(strict=True)
    out=args.output.absolute()
    if out.exists():parser.error('Output must be new; never overwrite test evidence')
    out.mkdir(parents=True)
    if runtime==out or runtime in out.parents:parser.error('Evidence must be outside runtime')
    started=datetime.now(timezone.utc).isoformat()
    result={'status':'RUNNING','started_at_utc':started,'source':json.loads((runtime/'MANIFEST.json').read_text())['source'],
            'installer':{'filename':installer.name,'bytes':installer.stat().st_size,'sha256':sha(installer)},
            'scope':'Engineering Windows runner offline frozen launch/exit, repeated launch, per-user installation/reinstallation/uninstall payload check',
            'standard_user_execution':'NOT ESTABLISHED; runner token is not a standard-user acceptance environment',
            'native_notification_center':'NOT RUN','mixed_monitor_dpi':'NOT RUN','live_media':'NOT RUN','independent_qa':'NOT RUN','release_approval':'NOT GRANTED',
            'checks':[]}
    installed=out/'installed'; export=out/'user-export.txt'; export.write_text('Preserve this controlled exported user data.\n')
    uninstaller=None
    try:
        for label in ('frozen-first-launch','frozen-restart'):
            result['checks'].append({'name':label,'status':'PASS','image':snapshot(runtime/'GlobalPulse.exe',out,label)})
        fixture=Path(__file__).resolve().parents[1]/'tests'/'fixtures'/'crisis.json'
        for size in ((1440,940),(960,640)):
            label=f'frozen-synthetic-selected-{size[0]}x{size[1]}'
            result['checks'].append({'name':label,'status':'PASS',
                'image':synthetic_selected_snapshot(runtime/'GlobalPulse.exe',out,label,fixture,size)})
        result['checks'].append({'name':'frozen-translation-worker','result':worker_route(runtime/'GlobalPulse.exe',out)})
        for attempt in ('install','reinstall'):
            run([installer,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={installed}',f'/LOG={out/(attempt+".txt")}'],timeout=300)
            uninstaller=installed/'unins000.exe'
            count=check_installed_payload(runtime,installed)
            result['checks'].append({'name':attempt,'status':'PASS','files_matched':count,
                'image':snapshot(installed/'GlobalPulse.exe',out,attempt+'-launch')})
        if not uninstaller or not uninstaller.is_file():raise AssertionError('Uninstaller missing')
        run([uninstaller,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/LOG={out/"uninstall.txt"}'],timeout=90)
        end=time.monotonic()+20
        while (installed/'GlobalPulse.exe').exists() and time.monotonic()<end:time.sleep(.1)
        if (installed/'GlobalPulse.exe').exists():raise AssertionError('Uninstall left application executable')
        if not export.exists() or export.read_text()!='Preserve this controlled exported user data.\n':raise AssertionError('Export not preserved')
        if not (out/'install-launch-data'/'global-pulse.sqlite3').exists():raise AssertionError('Separate application archive was removed')
        result['checks'].append({'name':'uninstall-preserves-external-export-and-archive','status':'PASS'})
        result['status']='PASS'
        return 0
    except Exception as error:
        result['status']='FAIL';result['error']=str(error)
        return 1
    finally:
        result['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        (out/'WINDOWS_SMOKE.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        # Keep failure evidence. The disposable runner owns the installation;
        # do not hide failure behind forced filesystem cleanup.
        print(json.dumps(result,indent=2))


if __name__=='__main__':raise SystemExit(main())
