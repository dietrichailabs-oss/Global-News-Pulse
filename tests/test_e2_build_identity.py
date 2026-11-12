"""Internal consistency, not a claim that the Windows compiler ran."""
from pathlib import Path
import importlib.util
import tomllib
import xml.etree.ElementTree as ET

from global_pulse import __version__, BUILD_ID
ROOT=Path(__file__).resolve().parents[1]


def test_e2_build_identity_is_consistent_across_declared_inputs():
    assert __version__=='0.1.1'
    assert BUILD_ID=='GP-ENG-001-E2'
    assert tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']==__version__
    assert ET.fromstring((ROOT/'packaging/notifications/GlobalPulse.Notifications.csproj').read_text()).find('.//Version').text==__version__
    script=(ROOT/'scripts/build_windows.ps1').read_text()
    assert "$version = '0.1.1'" in script and "$candidate = 'E2'" in script
    assert "'/DProductVersion=0.1.1','/DCandidateId=E2'" in script
    spec=importlib.util.spec_from_file_location('manifest_identity',ROOT/'scripts/package_manifest.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert (module.VERSION,module.BUILD)==(__version__,'E2')


def test_private_runtime_readme_is_used_without_packaging_internal_qa():
    script=(ROOT/'scripts/build_windows.ps1').read_text()
    assert "'docs\\PRIVATE_TEST_GUIDE.md' = 'README.md'" in script
    guide=(ROOT/'docs/PRIVATE_TEST_GUIDE.md').read_text()
    assert 'schema version 2' in guide
    assert 'not an approved Version 1 release' in guide
