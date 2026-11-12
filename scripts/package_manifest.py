"""Validate and describe an allowlisted Global Pulse runtime package.

This utility is standard-library only. It never imports or runs the packaged
application, sends data, accepts licenses, or marks Windows acceptance as passed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

VERSION = "0.1.1"
BUILD = "E2"
RUNTIME_COMPONENTS = {
    "global-pulse", "pyside6", "pyside6-essentials", "pyside6-addons", "pyside6-webengine", "pyside6-pdf",
    "shiboken6", "httpx", "httpcore", "anyio", "certifi", "idna", "h11", "defusedxml",
    "langdetect", "six", "ctranslate2", "sentencepiece", "sacremoses", "subword-nmt",
    "numpy", "pyyaml", "regex", "click", "joblib", "tqdm", "typing-extensions", "socksio",
    "colorama", "mock", "setuptools",
}
REVIEWED_LICENSE_ROOT = Path(__file__).resolve().parents[1] / "packaging" / "licenses"
REVIEWED_LICENSE_FALLBACKS = {
    ("ctranslate2", "4.8.5"): "CTranslate2-4.8.5-LICENSE.txt",
    ("sentencepiece", "0.2.3"): "SentencePiece-0.2.3-LICENSE.txt",
}
QT_COMPLIANCE_FILES = (
    "Qt-LGPL-3.0-only.txt",
    "Qt-GPL-3.0-only.txt",
    "QT-6.12.0-OPEN-SOURCE-COMPLIANCE.json",
    "QT-6.12.0-OPEN-SOURCE-NOTICE.md",
    "QT-WEBENGINE-PDF-6.140-SOURCE-STATUS.json",
    "Chromium-140-BSD-LICENSE.txt",
    "PDFium-BSD-Apache-LICENSE.txt",
)
QT_EXPECTED_DISTRIBUTIONS = {
    "pyside6": "6.12.0",
    "pyside6-essentials": "6.12.0",
    "pyside6-addons": "6.12.0",
    "pyside6-webengine": "6.12.0.140",
    "pyside6-pdf": "6.12.0.140",
    "shiboken6": "6.12.0",
}
QT_FORBIDDEN_RUNTIME_PREFIXES = {
    "qt6canvaspainter", "qt6coap", "qt6graphs", "qt6grpc",
    "qt6httpserver", "qt6lottie", "qt6mqtt", "qt6networkauth",
    "qt6quick3d", "qt6quicktimeline", "qt6virtualkeyboard",
    "qt6waylandcompositor", "qt6insighttracker", "qt6vncserver",
}
QT_FORBIDDEN_QML_FRAGMENTS = {
    "/pyside6/qml/qtgraphs/",
    "/pyside6/qml/qtgrpc/",
    "/pyside6/qml/qtlottie/",
    "/pyside6/qml/qtquick3d/",
    "/pyside6/qml/qtquick/timeline/",
    "/pyside6/qml/qtquick/virtualkeyboard/",
}
QT_REQUIRED_RUNTIME_BASENAMES = {
    "qt6core.dll", "qt6gui.dll", "qt6widgets.dll", "qt6network.dll",
    "qt6webenginecore.dll", "qtwebengineprocess.exe", "qt6pdf.dll",
}
TOP_FILES = {
    "GlobalPulse.exe", "README.md", "USER_GUIDE.md", "SETTINGS_ALERTS.md",
    "KNOWN_LIMITATIONS.md", "SOURCE_ACCESS_MATRIX.md", "THIRD_PARTY_NOTICES.md",
    "LICENSE.txt", "MANIFEST.json", "SBOM.cdx.json",
}
TOP_DIRECTORIES = {"_internal", "notifications", "licenses"}
FORBIDDEN_PARTS = {
    ".git", ".github", ".venv", "venv", "tests", "test", "fixtures", "checkpoints",
    "node_modules", "__pycache__", ".pytest_cache", "user data", "browser_cache",
}
FORBIDDEN_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".log", ".bak", ".old", ".pdb", ".key", ".pem", ".pfx", ".p12", ".env", ".ps1", ".cmd", ".bat"}
TEXT_SUFFIXES = {".txt", ".md", ".rst", ".json", ".geojson", ".xml", ".ini", ".yaml", ".yml", ".config", ".pem"}
SECRET_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
]
QT_VENDOR_SPDX_PATH = "licenses/qt-open-source/corresponding-source/qtwebengine-sbom_qtwebengine-6.140.0.spdx.json"
QT_VENDOR_SPDX_LOCALE_FIELDS = re.compile(
    rb'"(?:SPDXID|relatedSpdxElement)"\s*:\s*'
    rb'"SPDXRef-PackagedFile-qt-module-WebEngineCore-sk-pak-b42d-'
    rb'(?:RelWithDebInfo|Debug)-872898bf869d"'
)


def contains_embedded_credential(data, relative):
    """Ignore only reviewed Slovak locale IDs in their original vendor fields.

    Do not skip the file or alter vendor bytes. Keys elsewhere in that same
    document, changed identifiers, and all other secret patterns still fail.
    """
    reviewed_spans = ()
    if relative == QT_VENDOR_SPDX_PATH:
        reviewed_spans = tuple(m.span() for m in QT_VENDOR_SPDX_LOCALE_FIELDS.finditer(data))
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(data):
            if not any(start <= match.start() and match.end() <= end
                       for start, end in reviewed_spans):
                return True
    return False


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def digest(path):
    value=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(path)


def files(root):
    root=Path(root).resolve()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not permitted in the runtime package: "+path.relative_to(root).as_posix())
        if path.is_file():
            yield path,path.relative_to(root).as_posix()


def is_x64_pe(path):
    with Path(path).open("rb") as stream:
        header=stream.read(64)
        if len(header)<64 or header[:2]!=b"MZ":return False
        position=struct.unpack_from("<I",header,60)[0]
        if position>16*1024*1024:return False
        stream.seek(position);pe=stream.read(6)
        return len(pe)==6 and pe[:4]==b"PE\0\0" and struct.unpack_from("<H",pe,4)[0]==0x8664


def scan(root, *, require_complete=True):
    root=Path(root).resolve()
    if not root.is_dir():raise ValueError("Runtime package directory does not exist")
    errors=[];count=0;total=0
    for path,relative in files(root):
        parts=PurePosixPath(relative).parts
        folded={p.lower() for p in parts}
        if len(parts)==1 and parts[0] not in TOP_FILES:errors.append(relative+": root file is not allowlisted")
        if len(parts)>1 and parts[0] not in TOP_DIRECTORIES:errors.append(relative+": root directory is not allowlisted")
        if folded & FORBIDDEN_PARTS:errors.append(relative+": development or private-data directory")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES and relative!="_internal/certifi/cacert.pem":errors.append(relative+": forbidden runtime file type")
        if path.name.lower().startswith((".env","credentials","token_cache","secret")):errors.append(relative+": credential-like filename")
        if path.suffix.lower()==".py" and not relative.startswith("_internal/"):
            errors.append(relative+": project source outside frozen runtime")
        if (path.suffix.lower() in TEXT_SUFFIXES or path.name in {"METADATA","LICENSE","NOTICE","COPYING"}) and path.stat().st_size<=8*1024*1024:
            data=path.read_bytes()
            if contains_embedded_credential(data,relative):errors.append(relative+": potential embedded credential; match contents withheld")
            if path.name=="sources.json":
                catalog=json.loads(data)
                for source in catalog.get("sources",[]):
                    if any(source.get(k) for k in ("api_key","token","password","client_secret")):
                        errors.append(relative+": populated source credential field")
        count+=1;total+=path.stat().st_size
    required=["GlobalPulse.exe","notifications/GlobalPulse.Notifications.exe","notifications/GlobalPulse.Notifications.deps.json",
              "notifications/GlobalPulse.Notifications.runtimeconfig.json","notifications/pulse.png",
              "_internal/global_pulse/resources/world_countries.geojson","_internal/global_pulse/resources/sources.json",
              "_internal/global_pulse/resources/translation_models.json","_internal/global_pulse/resources/context_cameras.json","USER_GUIDE.md","KNOWN_LIMITATIONS.md","THIRD_PARTY_NOTICES.md"]
    if require_complete:
        for relative in required:
            if not (root/relative).is_file():errors.append(relative+": required runtime file is missing")
        # A framework-dependent helper must never be passed off as self-contained.
        if not (root/"notifications"/"coreclr.dll").is_file():errors.append("notifications/coreclr.dll: self-contained .NET runtime is missing")
        for relative in ("GlobalPulse.exe","notifications/GlobalPulse.Notifications.exe","notifications/coreclr.dll","_internal/python312.dll"):
            path=root/relative
            if not path.is_file() or not is_x64_pe(path):errors.append(relative+": required x64 Windows PE binary is missing or invalid")
        deps=root/"notifications"/"GlobalPulse.Notifications.deps.json"
        if deps.exists() and not any("microsoft.windowsappsdk" in name.lower() for name in json.loads(deps.read_text(encoding="utf-8-sig")).get("libraries",{})):
            errors.append("Native helper dependency identity does not include Microsoft.WindowsAppSDK")
    if errors:raise ValueError("Runtime package rejected:\n"+"\n".join(errors[:100]))
    return {"status":"PASS","files":count,"bytes":total,"scope":"Allowlist, required native payload, filenames, and selected embedded-secret patterns; not a complete security audit"}


def source_identity(root):
    root=Path(root).resolve()
    candidates=[]
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():continue
        rel=path.relative_to(root)
        if any(p in {".git",".venv","build","dist","release","__pycache__",".pytest_cache","obj","bin"} for p in rel.parts):continue
        if rel.parts[0] in {"global_pulse","scripts","packaging","tests","docs"} or len(rel.parts)==1 and path.name in {"pyproject.toml","README.md","LICENSE.txt","requirements-build.lock","requirements-bootstrap.lock"}:
            candidates.append((rel.as_posix(),digest(path)))
    result=hashlib.sha256()
    for name,sha in sorted(candidates):result.update(name.encode()+b"\0"+sha.encode()+b"\n")
    git_commit=None;git_dirty=None
    if (root/".git").exists():
        try:
            git_commit=subprocess.run(["git","rev-parse","HEAD"],cwd=root,capture_output=True,text=True,check=True,timeout=10).stdout.strip()
            git_dirty=bool(subprocess.run(["git","status","--porcelain"],cwd=root,capture_output=True,text=True,check=True,timeout=10).stdout.strip())
        except (OSError,subprocess.SubprocessError):pass
    return {"tree_sha256":result.hexdigest(),"file_count":len(candidates),"git_commit":git_commit,"git_worktree_dirty":git_dirty}


def manifest(root, source_root):
    root=Path(root).resolve()
    result=scan(root)
    entries=[{"path":name,"bytes":path.stat().st_size,"sha256":digest(path)} for path,name in files(root) if name!="MANIFEST.json"]
    value={"schema_version":1,"product":"Global Pulse","version":VERSION,"build":BUILD,
           "candidate_status":"Engineering candidate — Windows acceptance and release approvals required",
           "source":source_identity(source_root),"runtime_scan":result,"files":entries,
           "manifest_excludes_self":True,"native_windows_acceptance":"NOT RUN by packaging utility"}
    write_json(root/"MANIFEST.json",value)
    return {"files":len(entries),"manifest_sha256":digest(root/"MANIFEST.json"),"source_tree_sha256":value["source"]["tree_sha256"]}


def verify(root):
    root=Path(root).resolve();manifest_path=root/"MANIFEST.json"
    value=json.loads(manifest_path.read_text(encoding="utf-8"))
    expected={e["path"]:e for e in value["files"]}
    actual={name:path for path,name in files(root) if name!="MANIFEST.json"}
    errors=[]
    if set(actual)!=set(expected):errors.append("File set differs from manifest")
    for name,record in expected.items():
        if name not in actual:continue
        if actual[name].stat().st_size!=record["bytes"] or digest(actual[name])!=record["sha256"]:errors.append(name+": byte identity differs")
    if errors:raise ValueError("Manifest verification failed:\n"+"\n".join(errors[:100]))
    return {"status":"PASS","files":len(actual),"manifest_sha256":digest(manifest_path)}


def copy_licenses(root):
    root=Path(root).resolve();target=root/"licenses";target.mkdir(parents=True,exist_ok=True)
    records=[]
    for dist in metadata.distributions():
        name=dist.metadata.get("Name","")
        if canonical(name) not in RUNTIME_COMPONENTS:continue
        copied=[];destination=target/(canonical(name)+"-"+dist.version)
        for item in dist.files or []:
            path=Path(str(item));lower=path.name.lower()
            if not any(token in lower for token in ("license","licence","copying","notice","copyright")):continue
            actual=Path(dist.locate_file(item))
            if not actual.is_file() or actual.stat().st_size>5*1024*1024:continue
            # Use a stable unique destination; distribution-relative path names
            # contain no host paths and are validated before write.
            safe_name=re.sub(r"[^A-Za-z0-9_.-]","_",str(item))
            destination.mkdir(exist_ok=True)
            output=destination/safe_name
            shutil.copyfile(actual,output);copied.append(output.relative_to(root).as_posix())
        fallback_name=REVIEWED_LICENSE_FALLBACKS.get((canonical(name),str(dist.version)))
        if not copied and fallback_name:
            fallback=REVIEWED_LICENSE_ROOT/fallback_name
            if not fallback.is_file() or fallback.stat().st_size>5*1024*1024:
                raise ValueError(f"Reviewed fallback license text missing for {name} {dist.version}: {fallback_name}")
            destination.mkdir(exist_ok=True)
            output=destination/fallback_name
            shutil.copyfile(fallback,output);copied.append(output.relative_to(root).as_posix())
        license_value=dist.metadata.get("License-Expression") or dist.metadata.get("License") or "NOASSERTION"
        records.append({"name":name,"version":dist.version,"license_expression_or_metadata":license_value,"license_files":copied})
    qt_compliance_files=[]
    qt_runtime=[]
    qt_runtime_root=root/"_internal"/"PySide6"
    if qt_runtime_root.is_dir():
        distributions_by_name={canonical(r["name"]):r for r in records}
        for name,version in QT_EXPECTED_DISTRIBUTIONS.items():
            record=distributions_by_name.get(name)
            if not record or str(record["version"])!=version:
                raise ValueError(f"Qt/PySide compliance version mismatch: {name} expected {version}")
        qt_target=target/"qt-open-source";qt_target.mkdir(exist_ok=True)
        for filename in QT_COMPLIANCE_FILES:
            source=REVIEWED_LICENSE_ROOT/filename
            if not source.is_file() or source.stat().st_size<100 or source.stat().st_size>5*1024*1024:
                raise ValueError("Qt compliance file missing or invalid: "+filename)
            output=qt_target/filename
            shutil.copyfile(source,output);qt_compliance_files.append(output.relative_to(root).as_posix())
        forbidden_qml=sorted({
            relative
            for _,relative in files(root)
            if any(fragment in ("/"+relative.replace("\\","/").lower().lstrip("/")) for fragment in QT_FORBIDDEN_QML_FRAGMENTS)
        },key=str.casefold)
        if forbidden_qml:
            raise ValueError("Unapproved GPL-only Qt QML plugin trees shipped: "+", ".join(forbidden_qml[:50]))
        for path,relative in files(root):
            lower=path.name.lower()
            if relative.startswith("_internal/PySide6/") and ((lower.startswith("qt6") and lower.endswith(".dll")) or lower=="qtwebengineprocess.exe"):
                qt_runtime.append({"path":relative,"bytes":path.stat().st_size,"sha256":digest(path)})
        forbidden=sorted({
            Path(item["path"]).name
            for item in qt_runtime
            if any(Path(item["path"]).name.lower().startswith(prefix) for prefix in QT_FORBIDDEN_RUNTIME_PREFIXES)
        },key=str.casefold)
        if forbidden:
            raise ValueError("Unapproved GPL-only/commercial-only Qt runtime modules shipped: "+", ".join(forbidden))
        shipped={Path(item["path"]).name.lower() for item in qt_runtime}
        absent=sorted(QT_REQUIRED_RUNTIME_BASENAMES-shipped)
        if absent:
            raise ValueError("Expected reviewed Qt runtime component missing: "+", ".join(absent))
        write_json(qt_target/"QT_RUNTIME_COMPONENTS.json",{
            "qt_version":"6.12.0",
            "route":"Core Qt/PySide LGPL-3.0 source-pinned; WebEngine/PDF 6.140 license/notice mapped with corresponding-source HOLD",
            "source_archive_sha256":"a72e89c33726d742e67edf494abf7b625eaffc756673221c9823322ecd1a32d1",
            "pyside_source_sha256":"15b25c9e06f3acb8930c318192f3c20aee162f4b8d01bf4b4c60193c924cd847",
            "webengine_pdf_line":"6.140.0",
            "webengine_wheel_sha256":"f9b61b1d457a591ee590a6b80515f25a3e61e2576a2a0a70566380f9d9de4ab0",
            "webengine_pdf_corresponding_source_status":"HOLD",
            "files":sorted(qt_runtime,key=lambda r:r["path"].casefold()),
        })
        qt_compliance_files.append((qt_target/"QT_RUNTIME_COMPONENTS.json").relative_to(root).as_posix())
    python_licenses=[]
    for filename in ("LICENSE.txt","LICENSE"):
        original=Path(sys.base_prefix)/filename
        if original.is_file():
            destination=target/("Python-"+platform.python_version()+"-"+filename)
            shutil.copyfile(original,destination);python_licenses.append(destination.relative_to(root).as_posix())
    records.append({"name":"Python","version":platform.python_version(),"license_expression_or_metadata":"PSF-2.0 and bundled library notices; consult complete Python license","license_files":python_licenses})
    missing=[r["name"] for r in records if not r["license_files"]]
    write_json(target/"python-distributions.json",records)
    if missing:
        raise ValueError("Runtime license texts missing: "+", ".join(sorted(missing,key=str.casefold)))
    return {"distributions":len(records),"license_files":sum(len(r["license_files"]) for r in records),
            "unresolved_licenses":[r["name"] for r in records if r["license_expression_or_metadata"]=="NOASSERTION"],
            "missing_license_texts":[],"qt_compliance_files":qt_compliance_files,
            "qt_runtime_files":len(qt_runtime)}


def sbom(root):
    root=Path(root).resolve();components=[];dependencies=[];refs={}
    distributions={canonical(d.metadata.get("Name","")):d for d in metadata.distributions() if canonical(d.metadata.get("Name","")) in RUNTIME_COMPONENTS}
    for normalized,dist in sorted(distributions.items()):
        name=dist.metadata.get("Name",normalized);ref=f"pkg:pypi/{quote(normalized)}@{quote(dist.version)}";refs[normalized]=ref
        license_value=dist.metadata.get("License-Expression") or dist.metadata.get("License")
        component={"type":"library","name":name,"version":dist.version,"bom-ref":ref,"purl":ref,
                   "properties":[{"name":"globalpulse:evidence","value":"Installed build distribution metadata; runtime inclusion is recorded by package file manifest"}]}
        if license_value:component["licenses"]=[{"license":{"name":license_value[:1000]}}]
        else:component["properties"].append({"name":"globalpulse:license-review","value":"NOASSERTION — requires distribution review"})
        components.append(component)
    for normalized,dist in sorted(distributions.items()):
        names=[canonical(re.split(r"[\s(<>=!~\[]",requirement,maxsplit=1)[0]) for requirement in dist.requires or []]
        dependencies.append({"ref":refs[normalized],"dependsOn":sorted({refs[name] for name in names if name in refs})})
    for deps_path in sorted((root/"notifications").glob("*.deps.json")):
        document=json.loads(deps_path.read_text(encoding="utf-8-sig"))
        for name,info in document.get("libraries",{}).items():
            if "/" not in name:continue
            package,version=name.rsplit("/",1);ref=f"pkg:nuget/{quote(package)}@{quote(version)}"
            components.append({"type":"library","name":package,"version":version,"bom-ref":ref,"purl":ref,
                               "properties":[{"name":"globalpulse:evidence","value":"Published .NET deps.json"},
                                             {"name":"globalpulse:license-review","value":"NOASSERTION — consult NuGet package licenses and notices"}]})
    # A file inventory covers bundled native/Qt/WebEngine assets for which package
    # metadata alone is insufficient. It is not a claim of complete provenance.
    for path,name in files(root):
        if name in {"MANIFEST.json","SBOM.cdx.json"}:continue
        components.append({"type":"file","name":name,"bom-ref":"file:"+name,"hashes":[{"alg":"SHA-256","content":digest(path)}]})
    value={"bomFormat":"CycloneDX","specVersion":"1.6","serialNumber":"urn:uuid:"+str(uuid.uuid4()),"version":1,
           "metadata":{"timestamp":datetime.now(timezone.utc).isoformat(),"component":{"type":"application","name":"Global Pulse","version":VERSION+"-"+BUILD,"bom-ref":"global-pulse-candidate"},
                       "properties":[{"name":"globalpulse:status","value":"Engineering candidate; Windows acceptance NOT RUN by this utility"},
                                      {"name":"globalpulse:provenance-limit","value":"Core Qt/PySide source identities and runtime hashes included; WebEngine/PDF 6.140 corresponding-source identity remains HOLD; independent rights review required"}]},
           "components":components,"dependencies":dependencies,"compositions":[{"aggregate":"incomplete","assemblies":["global-pulse-candidate"]}]}
    write_json(root/"SBOM.cdx.json",value)
    return {"components":len(components),"sbom_sha256":digest(root/"SBOM.cdx.json"),"license_review":"Required; unproven licenses remain NOASSERTION"}


def archive(root, output):
    root=Path(root).resolve();output=Path(output).resolve()
    if root==output or root in output.parents:raise ValueError("Archive output must be outside the runtime directory")
    scan(root);verify(root);output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9,allowZip64=True) as zipped:
        for path,name in files(root):
            entry=zipfile.ZipInfo("GlobalPulse/"+name,date_time=(2026,11,8,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o644<<16
            zipped.writestr(entry,path.read_bytes())
    with zipfile.ZipFile(output) as zipped:
        bad=zipped.testzip()
        if bad:raise ValueError("Archive CRC verification failed")
    return {"filename":output.name,"bytes":output.stat().st_size,"sha256":digest(output)}


def artifact_hashes(paths,output):
    records=[]
    for path in paths:
        path=Path(path)
        if not path.is_file():raise ValueError("Expected artifact is missing: "+path.name)
        records.append({"filename":path.name,"bytes":path.stat().st_size,"sha256":digest(path)})
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text("".join(r["sha256"]+"  "+r["filename"]+"\n" for r in records),encoding="utf-8")
    return records


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="action",required=True)
    for name in ("scan","verify","licenses","sbom"):
        p=sub.add_parser(name);p.add_argument("root",type=Path)
    p=sub.add_parser("manifest");p.add_argument("root",type=Path);p.add_argument("--source-root",required=True,type=Path)
    p=sub.add_parser("archive");p.add_argument("root",type=Path);p.add_argument("output",type=Path)
    p=sub.add_parser("artifact-hashes");p.add_argument("paths",nargs="+",type=Path);p.add_argument("--output",required=True,type=Path)
    p=sub.add_parser("source-identity");p.add_argument("root",type=Path)
    args=parser.parse_args(argv)
    try:
        if args.action=="scan":result=scan(args.root)
        elif args.action=="verify":result=verify(args.root)
        elif args.action=="licenses":result=copy_licenses(args.root)
        elif args.action=="sbom":result=sbom(args.root)
        elif args.action=="manifest":result=manifest(args.root,args.source_root)
        elif args.action=="archive":result=archive(args.root,args.output)
        elif args.action=="artifact-hashes":result=artifact_hashes(args.paths,args.output)
        else:result=source_identity(args.root)
        print(json.dumps(result,indent=2));return 0
    except (ValueError,OSError,KeyError,json.JSONDecodeError) as error:
        print(str(error),file=sys.stderr);return 1


if __name__=="__main__":raise SystemExit(main())