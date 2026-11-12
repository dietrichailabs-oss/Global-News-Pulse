"""Finite, hash-bound source correction for GP-UI-002 and Windows capture evidence.

Applies an inspectable unified diff only to five specified files. The published
files are normal source, not a runtime patch. Refuse changed bases rather than
replace another engineer's work. Full regression is required before publication.
"""
from pathlib import Path
import hashlib, subprocess, tempfile

EXPECTED = {
    'global_pulse/ui.py': '61f77d9e870ff74abfbb73e37d28e65872393763',
    'global_pulse/__main__.py': 'faa8f770cd0c171a290a1e0fad037e657a8365e0',
    'scripts/windows_package_smoke.py': '2129813e0a5066943738e3dc16a5c7f78c9fe259',
    'global_pulse/visual_diagnostics.py': None,
    'tests/test_e2_readable_sidebar.py': None,
}
OUTPUTS = {
    'global_pulse/ui.py': '73b0659f761d5c32506007f5ee036e41a95dd696d08d0dd49fc4edac60050033',
    'global_pulse/__main__.py': '065838af028e40d0f055a6f2ef02d8696c885a533c5ebd21c2a9defa7a15c8dc',
    'scripts/windows_package_smoke.py': '3bd4f4b90808b7a216bd763b206f6cf30f170622d018b63435fbec127756cd1c',
    'global_pulse/visual_diagnostics.py': '35e1fa58a04d81e1bec2fd9e8e3ec6c24beb0c777effc4e81d1c84279e1bfe05',
    'tests/test_e2_readable_sidebar.py': '8b0b3b5ac3a48553fa586f2748dec215573499ab490ed5d2b68594b9d68f8dc8',
}
PATCH_SHA256 = 'b974992ce514333d4f6f359a8bc7c7a2553a8701726c305b3de0915157d6d76c'


def apply():
    root = Path(__file__).resolve().parents[2]
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root).strip():
        raise SystemExit('Source worktree is not clean; preserve/reconcile it first')
    for name, expected in EXPECTED.items():
        path = root / name
        if path.is_symlink():
            raise SystemExit('Refusing symlink: ' + name)
        if expected is None:
            if path.exists():
                raise SystemExit('New path now exists; reconcile: ' + name)
        else:
            data = path.read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if actual != expected:
                raise SystemExit('Source advanced; refusing overwrite: ' + name)
    patch = (root / 'scripts/engineering/readability.patch').read_bytes()
    if len(patch) > 100000 or hashlib.sha256(patch).hexdigest() != PATCH_SHA256:
        raise SystemExit('Repair diff identity mismatch')
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / 'repair.patch'
        path.write_bytes(patch)
        subprocess.run(['git', 'apply', '--check', str(path)], cwd=root, check=True)
        subprocess.run(['git', 'apply', str(path)], cwd=root, check=True)
    for name, expected in OUTPUTS.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise SystemExit('Unexpected repaired bytes: ' + name)
    subprocess.run(['git', 'add', '--', *sorted(OUTPUTS)], cwd=root, check=True)
    changed = subprocess.check_output(['git', 'diff', '--cached', '--name-only'], cwd=root, text=True).splitlines()
    if set(changed) != set(OUTPUTS):
        raise SystemExit('Unexpected staged paths')
    print('Applied exactly five source/test paths. Independent QA and Windows remain pending.')


if __name__ == '__main__':
    apply()
