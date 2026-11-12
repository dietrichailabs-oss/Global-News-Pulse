"""Owner-selected archive budget; safe persisted controls and offline cleanup."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QMessageBox, QPushButton
import sqlite3
from .archive_storage import CHOICES_GB, DEFAULT_GB, GB, MESSAGES


class ArchiveStorageControls(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__('Local news archive storage', parent)
        self.controller = controller
        self._saved = DEFAULT_GB
        self._error = ''
        form = QFormLayout(self)
        self.maximum = QComboBox()
        self.maximum.setAccessibleName('Maximum local news archive size')
        for value in CHOICES_GB:
            self.maximum.addItem(f'{value} GB', value)
        self.maximum.setCurrentIndex(self.maximum.findData(DEFAULT_GB))
        self.maximum.currentIndexChanged.connect(self._change)
        form.addRow('Maximum size', self.maximum)
        self.usage = QLabel()
        self.usage.setTextFormat(Qt.TextFormat.PlainText)
        self.usage.setWordWrap(True)
        form.addRow(self.usage)
        note = QLabel('Default 30 GB; 1 GB = 1,000,000,000 bytes. This does not reserve disk space. '
            'Includes the news database and SQLite WAL, SHM and rollback files; models and user exports are excluded. '
            'Collection reserves journal/checkpoint working space and 256 MiB free drive space, so it may pause below the maximum. '
            'Only disposable GDELT cache is removed for size pressure; saved Situations and other source evidence are not deleted by this cleanup. '
            'Existing source-retention rules still apply separately.')
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        form.addRow(note)
        self.clean = QPushButton('Clean disposable cache now')
        self.clean.setToolTip('Runs local cleanup only. No provider request or monitoring activation.')
        self.clean.clicked.connect(self._clean)
        form.addRow(self.clean)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        controller.data_changed.connect(self.refresh)
        controller.gdelt_status_changed.connect(self.refresh)
        self.refresh()

    def _change(self, _index):
        value = self.maximum.currentData()
        if value < self._saved:
            result = QMessageBox.question(self, 'Lower archive storage limit?',
                'The lower limit may require removing the oldest disposable GDELT cache. '
                'Saved situations and other source reporting are preserved. If safe cleanup cannot make room, collection pauses. Continue?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if result != QMessageBox.StandardButton.Yes:
                self.refresh()
                return
        try:
            self.controller.set_setting('archive_max_gb', value)
            self._error = ''
        except (sqlite3.Error, OSError, RuntimeError, ValueError):
            self._error = 'Storage choice could not be saved. The last readable saved choice is shown.'
        self.refresh()

    def _clean(self):
        try:
            started = self.controller.clean_archive_cache()
            self._error = '' if started else 'Cleanup cannot start while another archive worker is running.'
        except (sqlite3.Error, OSError, RuntimeError, ValueError):
            self._error = 'Cleanup could not start; stored reporting has not been removed by this action.'
        self.refresh()

    def refresh(self):
        if getattr(self.controller, '_closed', False):
            self.timer.stop()
            return
        try:
            state = self.controller.archive_storage_status()
            self._saved = state['selected_gb']
        except (sqlite3.Error, OSError, RuntimeError, ValueError):
            blocked = self.maximum.blockSignals(True)
            try:
                self.maximum.setCurrentIndex(self.maximum.findData(self._saved))
            finally:
                self.maximum.blockSignals(blocked)
            self.clean.setEnabled(False)
            self.usage.setText('Archive storage is unavailable.\n' + self._error)
            return
        blocked = self.maximum.blockSignals(True)
        try:
            self.maximum.setCurrentIndex(self.maximum.findData(self._saved))
        finally:
            self.maximum.blockSignals(blocked)
        running = state.get('cleanup_running', False)
        self.clean.setEnabled(not running and not self.controller.demo)
        last = state.get('last_cleanup', {})
        detail = ('Cleanup running locally; no provider request.' if running else
                  state.get('message') or 'Archive collection has working space.')
        if last.get('at'):
            detail += '\nLast cleanup receipt: ' + last['at']
            if type(last.get('removed_rows')) is int:
                detail += f" · {last['removed_rows']} disposable rows removed"
            if last.get('state') in MESSAGES:
                detail += '\n' + MESSAGES[last['state']]
        attempt = state.get('cleanup_attempt') or {}
        outcomes = {
            'success': 'Latest cleanup attempt completed with a matching receipt.',
            'failed_start': 'Latest cleanup attempt could not start.',
            'failed_exit': 'Latest cleanup attempt failed; any partial removals are unknown.',
            'timeout': 'Latest cleanup attempt timed out; any partial removals are unknown.',
            'cancelled': 'Latest cleanup attempt was interrupted; any partial removals are unknown.',
            'missing_receipt': 'Latest cleanup attempt ended without a matching completion receipt.',
            'receipt_unavailable': 'Latest cleanup attempt result is unavailable; storage could not be read.',
        }
        if not running and attempt.get('state') in outcomes:
            detail += '\n' + outcomes[attempt['state']]
        if state.get('cleanup_error'):
            detail += '\n' + state['cleanup_error']
        self.usage.setText(f"{state['used_bytes']/GB:.2f} GB used / {self._saved} GB maximum"
            f"\n{state['free_disk_bytes']/GB:.2f} GB free on drive · {state['reusable_bytes']/GB:.2f} GB reusable database pages"
            f"\n{detail}\n{self._error}")
