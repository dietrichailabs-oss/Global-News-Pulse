"""Packaging-boundary tests use inert files, never runnable Windows candidates."""
import importlib.util
import json
import struct
import zipfile
from pathlib import Path

import pytest

SPEC=importlib.util.spec_from_file_location("gp_package_manifest",Path(__file__).parents[1]/"scripts"/"package_manifest.py")
pack=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


def inert_pe_header(machine=0x8664):
    data=bytearray(256);data[:2]=b"MZ";struct.pack_into("<I",data,60,128)
    data[128:132]=b"PE\0\0";struct.pack_into("<H",data,132,machine)
    return bytes(data)


@pytest.fixture
def package(tmp_path):
    root=tmp_path/"runtime";root.mkdir()
    for name in ("GlobalPulse.exe","notifications/GlobalPulse.Notifications.exe","notifications/coreclr.dll","_internal/python312.dll"):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(inert_pe_header())
    for name in ("notifications/pulse.png","USER_GUIDE.md","KNOWN_LIMITATIONS.md","THIRD_PARTY_NOTICES.md"):
        (root/name).write_bytes(b"INERT PACKAGING TEST FIXTURE")
    for name,data in (
        ("notifications/GlobalPulse.Notifications.deps.json",{"libraries":{"Microsoft.WindowsAppSDK/2.6.5":{"type":"package"}}}),
        ("notifications/GlobalPulse.Notifications.runtimeconfig.json",{"runtimeOptions":{"tfm":"net10.0"}}),
        ("_internal/global_pulse/resources/world_countries.geojson",{"type":"FeatureCollection","features":[]}),
        ("_internal/global_pulse/resources/sources.json",{"sources":[]}),
        ("_internal/global_pulse/resources/translation_models.json",{}),
        ("_internal/global_pulse/resources/context_cameras.json",{"schema_version":1,"entries":[]})):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data))
    return root


def test_package_requires_native_self_contained_x64_payload(package):
    assert pack.scan(package)["status"]=="PASS"
    (package/"notifications"/"coreclr.dll").unlink()
    with pytest.raises(ValueError,match="self-contained .NET runtime is missing"):pack.scan(package)


def test_package_rejects_wrong_architecture(package):
    (package/"GlobalPulse.exe").write_bytes(inert_pe_header(0x14c))
    with pytest.raises(ValueError,match="required x64 Windows PE"):pack.scan(package)


@pytest.mark.parametrize("name",["personal.sqlite3","_internal/tests/crisis.json","old-setup.exe","notifications/debug.pdb"])
def test_runtime_rejects_private_development_and_unallowlisted_files(package,name):
    path=package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("inert content")
    with pytest.raises(ValueError,match="Runtime package rejected"):pack.scan(package)


def test_secret_scanner_does_not_print_secret_value(package):
    secret="ghp_"+"A"*40
    path=package/"_internal"/"configuration.json";path.write_text(json.dumps({"bad_token":secret}))
    with pytest.raises(ValueError) as error:pack.scan(package)
    assert "potential embedded credential" in str(error.value)
    assert secret not in str(error.value)


def test_public_certificate_bundle_is_allowed_but_private_key_is_not(package):
    path=package/"_internal"/"certifi"/"cacert.pem";path.parent.mkdir();path.write_text("-----BEGIN CERTIFICATE-----\npublic trust data\n-----END CERTIFICATE-----")
    assert pack.scan(package)["status"]=="PASS"
    path.write_text("-----BEGIN "+"PRIVATE KEY-----\ntest-only")
    with pytest.raises(ValueError,match="potential embedded credential"):pack.scan(package)


def test_manifest_detects_modified_and_added_bytes(package,tmp_path):
    source=tmp_path/"source";source.mkdir();(source/"README.md").write_text("Source identity fixture")
    pack.manifest(package,source)
    assert pack.verify(package)["status"]=="PASS"
    (package/"USER_GUIDE.md").write_text("tampered after freeze")
    with pytest.raises(ValueError,match="byte identity differs"):pack.verify(package)


def test_archive_is_complete_and_output_cannot_be_inside_runtime(package,tmp_path):
    pack.manifest(package,tmp_path)
    destination=tmp_path/"candidate.zip"
    result=pack.archive(package,destination)
    assert result["sha256"]==pack.digest(destination)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert "GlobalPulse/GlobalPulse.exe" in archive.namelist()
        assert all(name.startswith("GlobalPulse/") for name in archive.namelist())
    with pytest.raises(ValueError,match="outside the runtime"):pack.archive(package,package/"bad.zip")


def test_sbom_does_not_invent_complete_provenance_or_native_acceptance(package):
    result=pack.sbom(package)
    document=json.loads((package/"SBOM.cdx.json").read_text())
    assert document["compositions"][0]["aggregate"]=="incomplete"
    assert "Required" in result["license_review"]
    text=json.dumps(document)
    assert "Windows acceptance NOT RUN" in text
    assert "NOASSERTION" in text


def test_source_identity_excludes_generated_and_private_files(tmp_path):
    (tmp_path/"global_pulse").mkdir();(tmp_path/"global_pulse"/"app.py").write_text("source")
    before=pack.source_identity(tmp_path)["tree_sha256"]
    (tmp_path/"build").mkdir();(tmp_path/"build"/"generated.exe").write_text("generated")
    (tmp_path/".env").write_text("unrelated private setting")
    assert pack.source_identity(tmp_path)["tree_sha256"]==before
    (tmp_path/"global_pulse"/"app.py").write_text("changed source")
    assert pack.source_identity(tmp_path)["tree_sha256"]!=before


def test_license_collector_copies_british_licence_text(tmp_path, monkeypatch):
    """An inert installed distribution with LICENCE must appear in the shipped inventory."""
    class SyntheticDistribution:
        version = "4.70.1"
        metadata = {"Name": "tqdm", "License-Expression": "MIT AND MPL-2.0"}
        files = [
            Path("tqdm-4.70.1.dist-info/licenses/LICENCE"),
            Path("tqdm-4.70.1.dist-info/licenses/LICENCE.md"),
            Path("tqdm-4.70.1.dist-info/README.md"),
        ]

        def locate_file(self, item):
            return tmp_path / "installed" / item

    distribution = SyntheticDistribution()
    for filename in distribution.files:
        path = distribution.locate_file(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("INERT LICENCE TEST TEXT" if "LICENCE" in path.name else "README NOT A LICENCE")
    monkeypatch.setattr(pack.metadata, "distributions", lambda: [distribution])
    _with_python_license(tmp_path, monkeypatch)

    runtime = tmp_path / "runtime"
    result = pack.copy_licenses(runtime)
    records = json.loads((runtime / "licenses" / "python-distributions.json").read_text())
    record = next(item for item in records if item["name"] == "tqdm")
    assert len(record["license_files"]) == 2
    assert all("LICENCE" in item for item in record["license_files"])
    assert all((runtime / name).read_text() == "INERT LICENCE TEST TEXT" for name in record["license_files"])
    assert "tqdm" not in result["missing_license_texts"]
    assert not any("README" in item for item in record["license_files"])


def _with_python_license(tmp_path, monkeypatch):
    root = tmp_path / "python-runtime"
    root.mkdir()
    (root / "LICENSE.txt").write_text("INERT PYTHON LICENSE TEST TEXT")
    monkeypatch.setattr(pack.sys, "base_prefix", str(root))


def test_license_collector_still_fails_closed_without_python_license(tmp_path, monkeypatch):
    """The fixture fix must not weaken the production missing-license gate."""
    empty_python = tmp_path / "python-without-license"
    empty_python.mkdir()
    monkeypatch.setattr(pack.sys, "base_prefix", str(empty_python))
    monkeypatch.setattr(pack.metadata, "distributions", lambda: [])
    with pytest.raises(ValueError, match="Runtime license texts missing: Python"):
        pack.copy_licenses(tmp_path / "runtime")


def test_license_collector_uses_exact_reviewed_fallback_when_wheel_omits_text(tmp_path, monkeypatch):
    class SyntheticDistribution:
        version = "4.8.5"
        metadata = {"Name": "ctranslate2", "License-Expression": "MIT"}
        files = []

        def locate_file(self, item):
            return tmp_path / "installed" / item

    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / "CTranslate2-4.8.5-LICENSE.txt").write_text("INERT REVIEWED FALLBACK LICENSE")
    monkeypatch.setattr(pack, "REVIEWED_LICENSE_ROOT", approved)
    monkeypatch.setattr(pack.metadata, "distributions", lambda: [SyntheticDistribution()])
    _with_python_license(tmp_path, monkeypatch)

    runtime = tmp_path / "runtime"
    result = pack.copy_licenses(runtime)
    records = json.loads((runtime / "licenses" / "python-distributions.json").read_text())
    record = next(item for item in records if item["name"] == "ctranslate2")
    assert record["license_files"] == ["licenses/ctranslate2-4.8.5/CTranslate2-4.8.5-LICENSE.txt"]
    assert (runtime / record["license_files"][0]).read_text() == "INERT REVIEWED FALLBACK LICENSE"
    assert result["missing_license_texts"] == []


@pytest.mark.parametrize(("name", "version"), [("ctranslate2", "4.8.6"), ("sentencepiece", "0.2.4"), ("tqdm", "4.70.1")])
def test_license_collector_fails_closed_without_exact_reviewed_text(tmp_path, monkeypatch, name, version):
    class SyntheticDistribution:
        metadata = {"Name": name, "License-Expression": "MIT"}
        files = []

        def locate_file(self, item):
            return tmp_path / "installed" / item

    distribution = SyntheticDistribution()
    distribution.version = version
    monkeypatch.setattr(pack.metadata, "distributions", lambda: [distribution])
    monkeypatch.setattr(pack, "REVIEWED_LICENSE_ROOT", tmp_path / "approved-empty")
    _with_python_license(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Runtime license texts missing"):
        pack.copy_licenses(tmp_path / "runtime")


def test_reviewed_fallback_license_sources_exist():
    for filename in pack.REVIEWED_LICENSE_FALLBACKS.values():
        path = pack.REVIEWED_LICENSE_ROOT / filename
        assert path.is_file()
        assert path.stat().st_size > 100


def test_qt_pdf_distribution_is_in_rights_inventory_and_frozen_metadata_selection():
    assert "pyside6-pdf" in pack.RUNTIME_COMPONENTS
    spec_text = (Path(__file__).parents[1] / "packaging" / "GlobalPulse.spec").read_text()
    assert '"PySide6_Pdf"' in spec_text


def test_notification_helper_uses_only_foundation_windows_app_sdk_component():
    root = Path(__file__).parents[1]
    project = (root / "packaging" / "notifications" / "GlobalPulse.Notifications.csproj").read_text()
    lock = json.loads((root / "packaging" / "notifications" / "packages.lock.json").read_text())
    assert 'PackageReference Include="Microsoft.WindowsAppSDK.Foundation" Version="2.6.5"' in project
    assert 'PackageReference Include="Microsoft.WindowsAppSDK" ' not in project
    packages = set(lock["dependencies"]["net10.0-windows10.0.19041"])
    assert {
        "Microsoft.Windows.SDK.BuildTools",
        "Microsoft.Windows.SDK.BuildTools.MSIX",
        "Microsoft.WindowsAppSDK.Base",
        "Microsoft.WindowsAppSDK.Foundation",
        "Microsoft.WindowsAppSDK.InteractiveExperiences",
    } == packages
    assert not any(name.startswith("Microsoft.Web.WebView2") for name in packages)
    assert not any(name.startswith("Microsoft.WindowsAppSDK.AI") for name in packages)
    assert not any(name.startswith("Microsoft.WindowsAppSDK.ML") for name in packages)
    assert not any(name.startswith("Microsoft.WindowsAppSDK.WinUI") for name in packages)


def test_qt_open_source_compliance_sources_are_exact_and_present():
    assert pack.QT_EXPECTED_DISTRIBUTIONS["pyside6"] == "6.12.0"
    assert pack.QT_EXPECTED_DISTRIBUTIONS["pyside6-webengine"] == "6.12.0.140"
    assert pack.QT_EXPECTED_DISTRIBUTIONS["pyside6-pdf"] == "6.12.0.140"
    for filename in pack.QT_COMPLIANCE_FILES:
        path = pack.REVIEWED_LICENSE_ROOT / filename
        assert path.is_file()
        assert path.stat().st_size > 100
    compliance = json.loads((pack.REVIEWED_LICENSE_ROOT / "QT-6.12.0-OPEN-SOURCE-COMPLIANCE.json").read_text(encoding="utf-8"))
    sources = {row["name"]: row for row in compliance["exact_source_archives"]}
    assert sources["Qt 6.12.0 complete source"]["sha256"] == "a72e89c33726d742e67edf494abf7b625eaffc756673221c9823322ecd1a32d1"
    assert sources["PySide6 6.12.0 source"]["sha256"] == "15b25c9e06f3acb8930c318192f3c20aee162f4b8d01bf4b4c60193c924cd847"
    webengine = sources["Qt WebEngine / Qt PDF 6.140.0-rc complete source"]
    assert webengine["git_commit"] == "d505fc23640d2bd6345e6483eb73daf4e19f5829"
    assert webengine["sha256"] == "61257967afd9803a1db6403e86ea25c4efff8fad479bda365a9d81bfd709f621"
    assert webengine["bytes"] == 580351144
    assert compliance["webengine_inventory"]["complete_inventory_required"] is True


def test_qt_compliance_forbidden_module_set_covers_known_non_lgpl_release_risks():
    forbidden = pack.QT_FORBIDDEN_RUNTIME_PREFIXES
    assert "qt6graphs" in forbidden
    assert "qt6grpc" in forbidden
    assert "qt6httpserver" in forbidden
    assert "qt6networkauth" in forbidden
    assert "qt6quick3d" in forbidden
    assert "qt6virtualkeyboard" in forbidden
    assert "qt6insighttracker" in forbidden
    assert "qt6vncserver" in forbidden


def test_pyinstaller_spec_prunes_unused_non_lgpl_qt_families_and_qml_trees():
    spec_text = (Path(__file__).parents[1] / "packaging" / "GlobalPulse.spec").read_text(encoding="utf-8")
    assert '"PySide6.QtGraphs"' in spec_text
    assert '"PySide6.QtQuick3D"' in spec_text
    assert '"PySide6.QtNetworkAuth"' in spec_text
    assert '"qt6graphs"' in spec_text
    assert '"/pyside6/qml/qtgraphs/"' in spec_text
    assert 'analysis.binaries = [entry for entry in analysis.binaries if _keep_reviewed_qt_entry(entry)]' in spec_text
    assert 'analysis.datas = [entry for entry in analysis.datas if _keep_reviewed_qt_entry(entry)]' in spec_text


def test_qt_compliance_requires_webengine_pdf_and_core_runtime_anchors():
    required = pack.QT_REQUIRED_RUNTIME_BASENAMES
    assert {"qt6core.dll","qt6gui.dll","qt6widgets.dll","qt6network.dll",
            "qt6webenginecore.dll","qtwebengineprocess.exe","qt6pdf.dll"} <= required


def test_webengine_pdf_6140_source_mapping_requires_own_exact_source_and_qa():
    status = json.loads((pack.REVIEWED_LICENSE_ROOT / "QT-WEBENGINE-PDF-6.140-SOURCE-STATUS.json").read_text(encoding="utf-8"))
    source_map = json.loads((pack.REVIEWED_LICENSE_ROOT / "qt-webengine-pdf" / "SOURCE_MAP.json").read_text(encoding="utf-8"))
    assert status["schema_version"] == 2
    assert status["decision"] == "CORRESPONDING_SOURCE_IDENTIFIED_ENGINEERING_CHECK_PENDING_INDEPENDENT_QA"
    assert status["public_release"] == "NOT_APPROVED"
    assert source_map["public_release"] == "NOT_APPROVED"
    assert source_map["status"] == "ENGINEERING_CORRESPONDING_SOURCE_IDENTIFIED_PENDING_INDEPENDENT_QA"
    assert source_map["certificate_trust"] == "NOT_EVALUATED_BY_SOURCE_MAPPING"
    assert source_map["source_download_verified"] is True
    assert source_map["source_tag_verified"] is True
    assert source_map["source_sbom_mismatches"] == []
    assert status["source_archive"] == source_map["source_archive"]
    source = status["source_archive"]
    assert source["name"] == "Qt WebEngine / Qt PDF 6.140.0-rc complete source"
    assert source["git_commit"] == status["source_commit"] == "d505fc23640d2bd6345e6483eb73daf4e19f5829"
    assert source["git_tag"] == "v6.140.0-rc"
    assert source["sha256"] == "61257967afd9803a1db6403e86ea25c4efff8fad479bda365a9d81bfd709f621"
    assert source["bytes"] == 580351144
    assert status["binary_relationship"] == source_map["binary_relationship"]
    assert status["evidence_bundle"] == "qt-open-source/corresponding-source/SOURCE_MAP.json"

    # Preserve the failed historical lookup; do not turn it into a final-tag claim.
    historical = status["historical_unresolved_lookup"]
    assert historical["decision"] == "HOLD"
    assert historical["observed_binary_distribution"]["pyside_webengine_version"] == "6.12.0.140"
    assert historical["observed_binary_distribution"]["pyside_pdf_version"] == "6.12.0.140"
    assert historical["observed_binary_distribution"]["windows_x64_webengine_wheel_sha256"] == "f9b61b1d457a591ee590a6b80515f25a3e61e2576a2a0a70566380f9d9de4ab0"
    assert historical["public_source_observation"]["final_v6_140_0_tag_observed"] is False
    assert "not asserted as the wheel's corresponding source" in historical["public_source_observation"]["branch_head_observation"]


def test_qt_notice_does_not_claim_core_612_source_covers_separate_webengine_6140():
    text = (pack.REVIEWED_LICENSE_ROOT / "QT-6.12.0-OPEN-SOURCE-NOTICE.md").read_text(encoding="utf-8")
    current, historical = text.split("## Earlier candidate notice (historical)", 1)
    assert "d505fc23640d2bd6345e6483eb73daf4e19f5829" in current
    assert "not independent QA acceptance or public-release" in current
    assert "Corresponding-source status remains HOLD" in historical
    assert "must not be represented as satisfying the separate WebEngine/PDF 6.140 source obligation" in historical


def test_qt_compliance_blocks_forbidden_qml_plugin_families():
    fragments = pack.QT_FORBIDDEN_QML_FRAGMENTS
    assert "/pyside6/qml/qtgraphs/" in fragments
    assert "/pyside6/qml/qtquick3d/" in fragments
    assert "/pyside6/qml/qtquick/virtualkeyboard/" in fragments
