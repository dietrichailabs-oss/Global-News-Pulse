"""Demo-specific payload, shortcut, seed, launch and reinstall checks."""
from __future__ import annotations
import argparse, json, os, sqlite3, time
from pathlib import Path
from scripts.windows_package_smoke import run, check_installed_payload, inspect_png
from scripts.qa_r20_prepare_provider_demo import SOURCE, EXE_SHA, SETUP, DEMO_NAME, digest

def settings(path):
    with sqlite3.connect(path) as db:
        return dict((key,json.loads(value)) for key,value in db.execute("SELECT key,value FROM settings"))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--work",type=Path,required=True)
    args=p.parse_args()
    root=args.work.resolve()
    runtime=root/"GlobalPulse"
    installer=root/"demo"/DEMO_NAME
    clean=root/"clean"/(SETUP+".exe")
    out=root/"smoke"
    out.mkdir()
    installed=out/"installed"
    profile=Path(os.environ["LOCALAPPDATA"])/"DietrichAILabs"/"GlobalPulse-ProviderDemo"
    normal=Path(os.environ["LOCALAPPDATA"])/"DietrichAILabs"/"GlobalPulse"
    assert not profile.exists(), "Use disposable runner with fresh demonstration profile"
    assert not normal.exists(), "Do not touch an existing normal profile"
    db=profile/"global-pulse.sqlite3"
    receipt={"source_commit":SOURCE,"original_run":46064298575,"scope":"Demo wrapper only; unchanged runtime. Offline hosted Windows checks, not standard-user physical or live provider acceptance.","checks":[]}
    assert digest(clean)==EXE_SHA
    assert digest(installer)!=EXE_SHA
    for attempt in ("install","reinstall"):
        run([installer,"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-",f"/DIR={installed}",f"/LOG={out/(attempt+'.log')}"],timeout=300)
        count=check_installed_payload(runtime,installed)
        assert count==3360
        s=settings(db)
        assert s["archive_mode"]=="live" and s["enabled_sources"]==[]
        assert s["source_enable_all_upgrade_v1"] is True and s["notifications_enabled"] is False
        assert s["gdelt_batches_enabled"] is False
        assert not normal.exists()
        if attempt=="reinstall":
            assert s["provider_demo_test_marker"]=="preserve-me"
        else:
            ps=r"""
$ErrorActionPreference='Stop'
$shortcut=Join-Path ([Environment]::GetFolderPath('Programs')) 'Global Pulse Provider Demo\Global Pulse Provider Demo.lnk'
if (!(Test-Path -LiteralPath $shortcut -PathType Leaf)) {throw 'Demo shortcut missing'}
$s=(New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
@{target=$s.TargetPath;arguments=$s.Arguments;working=$s.WorkingDirectory}|ConvertTo-Json -Compress
"""
            result=run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps])
            link=json.loads(result.stdout.decode("utf-8-sig"))
            assert Path(link["target"]).resolve()==(installed/"GlobalPulse.exe").resolve()
            assert link["arguments"]==f'--no-start --data-dir "{profile}"',link
            image=out/"demo-start.png"
            run([installed/"GlobalPulse.exe","--no-start","--data-dir",profile,"--snapshot",image],timeout=90)
            diag=json.loads(image.with_suffix(".json").read_text(encoding="utf-8"))
            assert diag["platform_backend"]=="windows" and diag["image_saved"]
            receipt["checks"].append({"name":"actual-demo-shortcut-and-frozen-offline-start","status":"PASS","image":inspect_png(image)})
            s=settings(db)
            assert s["enabled_sources"]==[] and not s["notifications_enabled"]
            with sqlite3.connect(db) as c:
                assert all(c.execute("SELECT count(*) FROM "+table).fetchone()[0]==0 for table in ("reports","events","observations","alerts"))
                c.execute("INSERT INTO settings VALUES(?,?)",("provider_demo_test_marker",json.dumps("preserve-me")))
            assert not normal.exists()
        receipt["checks"].append({"name":attempt,"status":"PASS","runtime_files_matched":count})
    run([installed/"unins000.exe","/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART",f"/LOG={out/'uninstall.log'}"],timeout=90)
    end=time.monotonic()+20
    while (installed/"GlobalPulse.exe").exists() and time.monotonic()<end:
        time.sleep(.1)
    assert not (installed/"GlobalPulse.exe").exists()
    assert settings(db)["provider_demo_test_marker"]=="preserve-me"
    assert not normal.exists()
    assert digest(clean)==EXE_SHA
    receipt["checks"].append({"name":"uninstall-preserves-demo-profile-and-clean-identity","status":"PASS"})
    receipt["status"]="PASS"
    receipt["clean"]={"filename":clean.name,"bytes":clean.stat().st_size,"sha256":digest(clean)}
    receipt["demo"]={"filename":installer.name,"bytes":installer.stat().st_size,"sha256":digest(installer)}
    (root/"DEMO_PACKAGE_RECEIPT.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print("DEMO_PACKAGE_PASS="+json.dumps(receipt,sort_keys=True),flush=True)

if __name__=="__main__":
    main()
