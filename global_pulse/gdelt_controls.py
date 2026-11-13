"""Settings controls for the separate GDELT coded-event archive."""
from datetime import datetime, timezone
import sqlite3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QMessageBox, QPushButton, QSpinBox


_CONTROL_ERRORS = (sqlite3.Error, ValueError, RuntimeError, OSError)


def stamp(value):
    if type(value) is not int or value <= 0:
        return 'Never'
    try:
        return datetime.fromtimestamp(value, timezone.utc).strftime('%d %b %H:%M UTC')
    except (ValueError, OverflowError, OSError):
        return 'Unavailable'


class GdeltControls(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__('GDELT 15-minute batch archive', parent)
        self.controller = controller
        self._action_error = ''
        self._saved_enabled = controller.get_setting('gdelt_batches_enabled', False) is True
        self._saved_days = controller.get_setting('gdelt_retention_days', 7)
        form = QFormLayout(self)
        self.enable = QCheckBox('Collect GDELT batches while monitoring is active')
        self.enable.setChecked(self._saved_enabled)
        self.enable.setEnabled(not controller.demo)
        self.enable.toggled.connect(self._enable)
        form.addRow(self.enable)
        self.days = QSpinBox()
        self.days.setRange(1,365)
        self.days.setSuffix(' days')
        self.days.setValue(self._saved_days)
        self.days.valueChanged.connect(self._retention)
        form.addRow('Keep batch rows',self.days)
        self.info = QLabel('Checks at least 15 minutes apart, with saved retry delays. Changes here apply immediately. '
            'Expired GDELT rows are removed on the next collection; saved Situations and other reporting are not removed. '
            'Coded records are not verified crises. The separate GDELT map layer shows supported countries and source records. '
            'The Local news archive storage controls manage the byte budget. Journal working space can pause collection below that maximum.')
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.info)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.status_label)
        self.retry = QPushButton('Resume retries after reviewing source errors')
        self.retry.clicked.connect(self._retry)
        form.addRow(self.retry)
        controller.gdelt_status_changed.connect(self.refresh)
        controller.data_changed.connect(self.refresh)
        self.refresh()

    def _enable(self, value):
        if value:
            answer = QMessageBox.question(self,'Enable GDELT batch collection?',
                'This contacts the official GDELT data service while monitoring is active and stores coded event rows locally. '
                'It does not fetch linked articles or verify incidents. Pause or Exit Completely stops this collector. '
                'The legacy GDELT search collectors are suppressed while this batch option is enabled. Continue?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.refresh()
                return
        try:
            self.controller.set_setting('gdelt_batches_enabled', value)
        except _CONTROL_ERRORS:
            self._action_error = ('Could not apply the GDELT collection setting. '
                'Storage may be busy or unavailable; check the current collector state before retrying.')
        else:
            self._action_error = ''
        self.refresh()

    def _retention(self, value):
        try:
            self.controller.set_setting('gdelt_retention_days', value)
        except _CONTROL_ERRORS:
            self._action_error = ('Could not save GDELT retention. '
                'Storage may be busy or unavailable; the last readable setting is shown.')
        else:
            self._action_error = ''
        self.refresh()

    def _retry(self):
        try:
            self.controller.gdelt_review_retry()
        except _CONTROL_ERRORS:
            self._action_error = ('Could not update retry state. '
                'Storage may be busy or unavailable. No immediate request is authorized.')
        else:
            self._action_error = ''
        self.refresh()

    def _restore_preferences(self):
        # Readback must never trigger another write or a new consent dialog.
        blocked = self.enable.blockSignals(True)
        try:
            self.enable.setChecked(self._saved_enabled)
        finally:
            self.enable.blockSignals(blocked)
        blocked = self.days.blockSignals(True)
        try:
            self.days.setValue(self._saved_days)
        finally:
            self.days.blockSignals(blocked)

    def refresh(self):
        try:
            state = self.controller.gdelt_status()
            enabled = self.controller.get_setting('gdelt_batches_enabled',False) is True
            days = self.controller.get_setting('gdelt_retention_days',7)
        except _CONTROL_ERRORS:
            self._restore_preferences()
            self.retry.setEnabled(False)
            self.status_label.setText('GDELT storage is unavailable. Current state could not be read.\n' + self._action_error)
            return
        self._saved_enabled, self._saved_days = enabled, days
        self._restore_preferences()
        mode = ('Storage unavailable' if state.get('state') == 'storage_unavailable' else
            'Collecting' if state.get('running') else 'Off' if not enabled else
            'Paused' if not state.get('active') else state.get('state','idle').replace('_',' ').title())
        error = f" · HTTP {state['http_status']}" if state.get('http_status') else ''
        gap = '\nWarning: missing published intervals remain unresolved.' if state.get('gap') else ''
        pending = ('\nWarning: newest advertised GDELT export is unavailable; '
                   'only an older checksum-verified published export was used. '
                   'Latest-batch freshness is NOT confirmed.'
                   if state.get('state') == 'replication_pending' else '')
        self.status_label.setText(f"{mode}{error}\nLast attempt: {stamp(state.get('last_attempt'))} · Last successful check: {stamp(state.get('last_success'))}"
            f"\nNext allowed check: {stamp(state.get('next_at'))} · Cached rows: {state.get('cached_rows',0)}"
            f"\nLatest imported batch: {state.get('last_batch') or 'None'}{gap}{pending}\n{state.get('local_error','')}\n{self._action_error}")
        self.retry.setEnabled(bool(state.get('suspended')) and not self.controller.demo)
