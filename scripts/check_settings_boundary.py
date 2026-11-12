"""Engineering replay: retain original QA bytes; never claim independent QA."""
from pathlib import Path
import hashlib
import subprocess
import sys

suites = [
 ('4bb9184c7fec22c6d04733e742d660ccc9a678eb', 'tests/test_qa_issue22_quiet_settings.py', '69295283d8c1f088913a7a250d9e8f75e935075b'),
 ('b1d39caddd9b2d3e3e7a8855d4979f9fa97dfd5a', 'tests/test_qa_issue22_startup_settings.py', '2592127067892898e2423246ca045899bc7cd505'),
]
for commit, path, expected in suites:
    raw = subprocess.check_output(['git', 'show', commit + ':' + path])
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert actual == expected, ('QA suite identity mismatch', path)
    Path(path).write_bytes(raw)
    print('UNCHANGED_QA_BYTES_ENGINEERING_REPLAY', path, actual, flush=True)
print('ACTUAL_ENGINEERING_TESTED_SOURCE', subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), flush=True)
paths = [p for _, p, _ in suites] + ['tests/test_issue22_settings_boundary.py', 'tests/test_controller.py', 'tests/test_issue22_provider_controls.py', 'tests/test_issue22_alert_filter_sanitize.py', 'tests/test_core.py']
completed = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--tb=short', *paths], timeout=240)
sys.exit(completed.returncode)
