"""Packaging-only provider demo preparation; never rebuild application."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import zipfile

SOURCE = "d4ff8fb70b1dc8ae41b14f23ad519ca04450679a"
SETUP = "GlobalPulse-0.1.1-E2-windows-x64-setup"
PORTABLE = "GlobalPulse-0.1.1-E2-windows-x64-portable.zip"
CUSTODY_SHA = "a277bdf1e9a66f80406c09fe9b730e74662e5b37ce02682a0d4e938aef0890f6"
EXE_SHA = "d3d07db8479b8ffcb458e3ed600499331c76259d1519578f9a9107157b3e773f"
DEMO_NAME = "GlobalPulse-0.1.1-E2-ProviderDemo-windows-x64-setup.exe"

def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def extract(z, name, path, size, sha):
    assert z.namelist().count(name) == 1, name
    assert z.getinfo(name).file_size == size, name
    path.parent.mkdir(parents=True, exist_ok=True)
    with z.open(name) as f, path.open("xb") as target:
        shutil.copyfileobj(f, target, length=1024*1024)
    assert path.stat().st_size == size and digest(path) == sha, name

def prepare(custody, root):
    assert custody.stat().st_size == 619888198 and digest(custody) == CUSTODY_SHA
    root.mkdir()
    inputs=root/"inputs"
    inputs.mkdir()
    clean=root/"clean"
    clean.mkdir()
    seed=root/"seed"
    seed.mkdir()
    (root/"demo").mkdir()
    with zipfile.ZipFile(custody) as z:
        extract(z,"15230719212-setup.zip",inputs/"setup-outer.zip",249477497,
                "5a5e77af18e9dce55d96648e35337212e1209a9710ca0474248f3f7667684df7")
        extract(z,"15230564346-portable.zip",inputs/"portable-outer.zip",369997415,
                "8c7f3fa7c4011c1cb3fd4d0348d7ca8e342daf7eeb530560ff5705121ba6be28")
        extract(z,"15230589401-receipts.zip",root/"original-receipts.zip",356726,
                "4a7b5cd21554da8b2e9de7b3f43204c89324edda6dccf0dc14cdc3b965c64b1f")
    with zipfile.ZipFile(inputs/"setup-outer.zip") as z:
        extract(z,SETUP+".zip",inputs/"setup.zip",249401379,
                "1aa86a2fae2a5b90e3344ac7a122adbb030da09b9db9423e218f473c1c6876bc")
    with zipfile.ZipFile(inputs/"setup.zip") as z:
        assert z.namelist() == [SETUP+".exe"]
        extract(z,SETUP+".exe",clean/(SETUP+".exe"),250093699,EXE_SHA)
    with zipfile.ZipFile(inputs/"portable-outer.zip") as z:
        extract(z,PORTABLE,inputs/PORTABLE,372560538,
                "b279a7f93f1d7e5340167a731a339b3afbeeb9821c01bcec504a65e1b7b7b47f")
    runtime=root/"GlobalPulse"
    runtime.mkdir()
    with zipfile.ZipFile(inputs/PORTABLE) as z:
        manifest_bytes=z.read("GlobalPulse/MANIFEST.json")
        manifest=json.loads(manifest_bytes)
        expected={entry["path"]:entry for entry in manifest["files"]}
        assert len(expected)==len(manifest["files"])==3360
        assert len({name.casefold() for name in expected})==len(expected)
        assert set(z.namelist())=={"GlobalPulse/"+name for name in expected}|{"GlobalPulse/MANIFEST.json"}
        assert len(z.namelist())==3361
        with zipfile.ZipFile(root/"original-receipts.zip") as receipts:
            assert receipts.read("MANIFEST.json")==manifest_bytes
        for name,item in expected.items():
            p=PurePosixPath(name)
            assert not p.is_absolute() and not any(x in {".","..",""} for x in name.split("/"))
            assert ":" not in name and chr(92) not in name
            extract(z,"GlobalPulse/"+name,runtime.joinpath(*p.parts),item["bytes"],item["sha256"])
        (runtime/"MANIFEST.json").write_bytes(manifest_bytes)
    with sqlite3.connect(seed/"global-pulse.sqlite3") as db:
        db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        settings={"archive_mode":"live","enabled_sources":[],
                  "source_enable_all_upgrade_v1":True,"setup_complete":True,
                  "notifications_enabled":False,"gdelt_batches_enabled":False,
                  "user_feeds":[],"english_headlines":False}
        db.executemany("INSERT INTO settings VALUES(?,?)",
                       [(key,json.dumps(value)) for key,value in settings.items()])
    guide="""GLOBAL PULSE - PROVIDER DEMONSTRATION ONLY
Not a public release. This separate installer uses the exact verified
R20 application runtime without changing it.

Always use the Global Pulse Provider Demo shortcut, not the bare
GlobalPulse.exe. The shortcut uses a separate local demo profile and
starts monitoring paused. A fresh demo profile has no enabled feeds;
select only the provider(s) and operations agreed for the demo.
Existing demo settings are preserved on reinstall. Recheck enabled
sources before collection. Keep native Windows notifications off to
avoid shared notification identity with a normal installation.
Close the clean application before running the demonstration.

The runtime remains fully functional; the seed is a safe starting
configuration, not an enforced network sandbox. Do not enable
unapproved providers or use exports or embedded media outside the
agreed scope. Preserve credit and source links. Use Exit Completely
in the tray to stop collection and media. The demonstration does not
establish permission for public distribution. Unsigned software:
verify installer SHA-256; do not bypass Windows security.
The separate profile is retained on uninstall.
"""
    (seed/"PROVIDER_DEMO_GUIDE.txt").write_text(guide,encoding="utf-8")
    (root/"PREPARATION.json").write_text(json.dumps({
        "source_commit":SOURCE,"original_run":46064298575,
        "clean_installer_sha256":EXE_SHA,"runtime_files_verified":len(expected),
        "manifest_sha256":digest(runtime/"MANIFEST.json"),
        "scope":"Original runtime and clean EXE verified; demo wrapper not yet compiled or tested.",
        "demo_seed":settings},indent=2)+"\n",encoding="utf-8")
    print("CLEAN_EXE_VERIFIED",EXE_SHA,"RUNTIME_FILES",len(expected),flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--custody",type=Path,required=True)
    p.add_argument("--work",type=Path,required=True)
    args=p.parse_args()
    prepare(args.custody,args.work)

if __name__=="__main__":
    main()
