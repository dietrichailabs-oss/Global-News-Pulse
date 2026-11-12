# -*- mode: python ; coding: utf-8 -*-
"""Explicit Windows onedir application specification.

No project directory, fixture tree, user profile, or development output is copied
wholesale. PyInstaller's supported Qt hooks collect the necessary native runtime.
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

if sys.platform != "win32":
    raise SystemExit("The Global Pulse Windows candidate must be built on Windows x64.")

project = Path(SPECPATH).resolve().parent
resources = project / "global_pulse" / "resources"
allowed_resources = [
    "sources.json", "media_catalog.json", "translation_models.json", "context_cameras.json",
    "world_countries.geojson", "MAP_DATA_LICENSE.txt", "pulse.png", "pulse.ico",
]
datas = []
for filename in allowed_resources:
    path = resources / filename
    if not path.is_file():
        raise SystemExit(f"Required application resource is missing: {filename}")
    datas.append((str(path), "global_pulse/resources"))

datas += collect_data_files("langdetect", includes=["profiles/*"])
datas += collect_data_files("sacremoses", includes=["data/*", "data/**/*"])
for package in ("global-pulse", "PySide6", "PySide6_Essentials", "PySide6_Addons",
                "PySide6_WebEngine", "PySide6_Pdf", "shiboken6", "httpx", "httpcore", "anyio",
                "certifi", "idna", "h11", "defusedxml", "langdetect", "six",
                "ctranslate2", "sentencepiece", "sacremoses", "subword-nmt",
                "numpy", "PyYAML", "regex", "click", "joblib", "tqdm",
                "typing_extensions", "socksio"):
    datas += copy_metadata(package)

binaries = collect_dynamic_libs("ctranslate2")
analysis = Analysis(
    [str(project / "scripts" / "entrypoint.py")],
    pathex=[str(project)], binaries=binaries, datas=datas,
    hiddenimports=[
        "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtNetwork",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "ctranslate2", "sentencepiece", "sacremoses", "subword_nmt.apply_bpe",
        "langdetect", "defusedxml.ElementTree", "httpx", "httpcore._backends.sync",
    ],
    hookspath=[], runtime_hooks=[],
    excludes=["pytest", "_pytest", "tests", "test", "unittest", "doctest", "pdb",
              "IPython", "tkinter", "PySide6.QtTest", "PySide6.QtQuickTest",
              "PySide6.QtCanvasPainter", "PySide6.QtCoap", "PySide6.QtGraphs",
              "PySide6.QtGrpc", "PySide6.QtHttpServer", "PySide6.QtLottie",
              "PySide6.QtMqtt", "PySide6.QtNetworkAuth", "PySide6.QtQuick3D",
              "PySide6.QtQuick3DPhysics", "PySide6.QtQuickTimeline",
              "PySide6.QtVirtualKeyboard", "PySide6.QtWaylandCompositor",
              "PySide6.QtInsightTracker", "PySide6.QtVncServer"],
    noarchive=False, optimize=1,
)

# PyInstaller's QtQml hook collects the complete wheel QML tree. The PySide6
# Addons wheel therefore contributes Qt modules Global Pulse never imports or
# uses, including modules whose open-source route is GPL-only. Excluding their
# Python bindings alone is insufficient because QML plugin trees can still pull
# their shared libraries into Analysis.binaries/datas. Prune only the reviewed
# unused module families, then let package_manifest.py fail closed if any
# forbidden family still survives the frozen build.
_QT_FORBIDDEN_RUNTIME_PREFIXES = (
    "qt6canvaspainter", "qt6coap", "qt6graphs", "qt6grpc", "qt6httpserver",
    "qt6lottie", "qt6mqtt", "qt6networkauth", "qt6quick3d",
    "qt6quicktimeline", "qt6virtualkeyboard", "qt6waylandcompositor",
    "qt6insighttracker", "qt6vncserver",
)
_QT_FORBIDDEN_QML_FRAGMENTS = (
    "/pyside6/qml/qtgraphs/",
    "/pyside6/qml/qtgrpc/",
    "/pyside6/qml/qtlottie/",
    "/pyside6/qml/qtquick3d/",
    "/pyside6/qml/qtquick/timeline/",
    "/pyside6/qml/qtquick/virtualkeyboard/",
)

def _keep_reviewed_qt_entry(entry):
    destination = str(entry[0]).replace("\\", "/").lower()
    basename = destination.rsplit("/", 1)[-1]
    if any(basename.startswith(prefix) for prefix in _QT_FORBIDDEN_RUNTIME_PREFIXES):
        return False
    rooted = "/" + destination.lstrip("/")
    if any(fragment in rooted for fragment in _QT_FORBIDDEN_QML_FRAGMENTS):
        return False
    return True

analysis.binaries = [entry for entry in analysis.binaries if _keep_reviewed_qt_entry(entry)]
analysis.datas = [entry for entry in analysis.datas if _keep_reviewed_qt_entry(entry)]
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="GlobalPulse", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    target_arch="x86_64", uac_admin=False, uac_uiaccess=False,
    icon=str(resources / "pulse.ico"), contents_directory="_internal",
)
collection = COLLECT(
    exe, analysis.binaries, analysis.datas,
    strip=False, upx=False, name="GlobalPulse",
)
