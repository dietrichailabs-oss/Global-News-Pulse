"""Content-bound local consent for the bundled Microsoft notification component.

This is not an application-wide license and does not restrict separately licensed
Qt/LGPL components. Declining leaves ordinary news/history use available but does
not start the Microsoft notification helper. No network or telemetry is involved.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
from typing import Callable

SETTING = 'microsoft_sdk_terms_accepted_sha256'
MAX_TERMS_BYTES = 512 * 1024


def read_terms(package_root: Path) -> tuple[str, str]:
    root = package_root.resolve(strict=True)
    directory = root / 'notifications/licenses/windows-sdk'
    record_path, terms_path = directory / 'BUNDLE.json', directory / 'SDK_TERMS.txt'
    for path, bound in ((record_path, 65536), (terms_path, MAX_TERMS_BYTES)):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('Microsoft component terms are missing or outside this package')
        if path.stat().st_size > bound:
            raise ValueError('Microsoft component terms exceed the supported size')
    record = json.loads(record_path.read_text(encoding='utf-8'))
    if not isinstance(record, dict) or not isinstance(record.get('documents'), dict):
        raise ValueError('Malformed Microsoft component terms record')
    if record.get('sdk_version') != '10.0.19041.57':
        raise ValueError('Unreviewed Microsoft component terms version')
    data = terms_path.read_bytes()
    identity = hashlib.sha256(data).hexdigest()
    expected = record.get('documents', {}).get('SDK_TERMS.txt', {})
    if not isinstance(expected, dict) or len(data) != expected.get('bytes') or identity != expected.get('sha256'):
        raise ValueError('Microsoft component terms do not match the package record')
    return data.decode('utf-8-sig'), identity


def consent(package_root: Path, get_setting: Callable, set_setting: Callable,
            prompt: Callable[[str], bool]) -> bool:
    text, identity = read_terms(package_root)
    if get_setting(SETTING, '') == identity:
        return True
    # Only the explicit affirmative result stores acceptance. No CLI flag,
    # onboarding skip, installer state, or default checked box implies consent.
    if prompt(text) is not True:
        return False
    set_setting(SETTING, identity)
    return True


def _show_terms(text: str, parent) -> bool:
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout
    dialog = QDialog(parent)
    dialog.setWindowTitle('Windows notification component terms')
    dialog.resize(680, 520)
    layout = QVBoxLayout(dialog)
    explanation = QLabel('Global Pulse is free of charge. Windows notifications use a Microsoft component. '
                         'Read its terms below. Declining leaves news and local alert history available, '
                         'but Windows notifications will not start.')
    explanation.setWordWrap(True)
    layout.addWidget(explanation)
    view = QTextBrowser(dialog)
    view.setOpenExternalLinks(False)
    view.setOpenLinks(False)
    view.setPlainText(text)
    view.setAccessibleName('Microsoft notification component terms')
    layout.addWidget(view)
    buttons = QDialogButtonBox(dialog)
    agree = buttons.addButton('Agree and enable Windows notifications', QDialogButtonBox.ButtonRole.AcceptRole)
    decline = buttons.addButton('Decline', QDialogButtonBox.ButtonRole.RejectRole)
    agree.setAutoDefault(False)
    agree.setDefault(False)
    decline.setDefault(True)
    decline.setFocus()
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return accepted


def accept_windows_sdk_terms(controller, parent) -> bool:
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        # Developer usage follows the SDK developer terms separately. Offline
        # snapshot/demo paths never reach this function or execute the helper.
        return True
    try:
        return consent(Path(sys.executable).parent, controller.get_setting,
                       controller.set_setting, lambda text: _show_terms(text, parent))
    except (OSError, ValueError, TypeError, KeyError) as error:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(parent, 'Windows notifications unavailable',
                            str(error) + '. Use the complete package; alert history remains available.')
        return False
