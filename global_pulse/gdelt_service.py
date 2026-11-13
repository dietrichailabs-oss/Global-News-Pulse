"""Opt-in Qt scheduler and bounded owned child lifecycle for GDELT batches."""
from __future__ import annotations
from pathlib import Path
import sqlite3
import sys
import time
from PySide6.QtCore import QObject, QProcess, QTimer, Signal, Slot
from .gdelt_schedule import Schedule, retention_days
from .archive_storage import last_cleanup, save_cleanup_attempt


class GdeltService(QObject):
    changed = Signal()

    def __init__(self, database, days, parent=None):
        super().__init__(parent)
        self.database = Path(database).resolve()
        self.days = days
        self.schedule = Schedule(self.database)
        self.process = None
        self.token = None
        self.active = False
        self.closed = False
        self.reason = ''
        self.local_error = ''
        self.cleanup_error = ''
        self.cleanup_outcome = {}
        self.retry_clock = 0.0
        self._maintenance = False
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.tick)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)
        self.timeout_ms = 120000

    def command(self):
        if getattr(sys, 'frozen', False):
            return sys.executable, ['--gdelt-worker']
        return sys.executable, ['-m', 'global_pulse.gdelt_worker']

    def status(self):
        try:
            result = self.schedule.status()
        except (sqlite3.Error, OSError):
            result = {'state': 'storage_unavailable'}
        return dict(result, running=self.process is not None, active=self.active,
                    local_error=self.local_error, cleanup_running=self._maintenance and self.process is not None)

    def set_active(self, value):
        if type(value) is not bool:
            raise ValueError('Collector activation requires a boolean')
        if self.closed:
            return
        self.active = value
        if value:
            try:
                self.schedule.recover_legacy_transport_failure()
            except (sqlite3.Error, OSError, ValueError):
                # Normal schedule handling below will surface storage failures.
                pass
            self.timer.start()
            self.tick()
        else:
            self.timer.stop()
            self._stop('cancelled')
            self.changed.emit()

    @Slot()
    def tick(self):
        if self.closed or not self.active or self.process is not None:
            return
        if time.monotonic() < self.retry_clock:
            return
        try:
            token = self.schedule.claim()
        except (sqlite3.Error, OSError, ValueError):
            self.local_error = 'GDELT schedule storage unavailable; no request started.'
            self.retry_clock = time.monotonic() + 60
            self.changed.emit()
            return
        if token is None:
            self.changed.emit()
            return
        self._launch(token)

    def request_cleanup(self):
        if self.closed or self.process is not None:
            return False
        from uuid import uuid4
        self._launch(uuid4().hex, cleanup_only=True)
        return True

    def _launch(self, token, cleanup_only=False):
        self._maintenance = cleanup_only
        self.local_error = ''
        if cleanup_only:
            self.cleanup_error = ''
            self.cleanup_outcome = {'attempt': token, 'state': 'running'}
        self.token = token
        self.reason = ''
        process = QProcess(self)
        self.process = process
        process.setProperty('gdelt_attempt', token)
        process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        # Native receiver-bound slots avoid callbacks owning their own sender
        # and its parent across deferred QObject destruction.
        process.setStandardOutputFile(QProcess.nullDevice())
        process.setStandardErrorFile(QProcess.nullDevice())
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        program, arguments = self.command()
        arguments += ['--database', str(self.database), '--retention-days', str(retention_days(self.days()))]
        arguments += ['--cleanup-only', '--cleanup-attempt', token] if cleanup_only else ['--token', token, '--consent-network']
        self.deadline.start(self.timeout_ms)
        process.start(program, arguments)
        self.changed.emit()

    @Slot(int, QProcess.ExitStatus)
    def _finished(self, code, exit_status):
        process = self.sender()
        if process is self.process and process is not None:
            self._done(process, process.property('gdelt_attempt'), code, exit_status)

    @Slot(QProcess.ProcessError)
    def _process_error(self, error):
        process = self.sender()
        if process is self.process and process is not None and error == QProcess.ProcessError.FailedToStart:
            self.reason = 'failed_start'
            self._done(process, process.property('gdelt_attempt'), 2, QProcess.ExitStatus.CrashExit)

    def _done(self, process, token, code, exit_status):
        if process is not self.process or token != self.token:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            return
        self.deadline.stop()
        if self._maintenance:
            # A native exit alone is not proof that a cleanup happened. The
            # child must have saved a receipt with THIS exact attempt identity.
            if self.reason in ('failed_start', 'timeout', 'cancelled'):
                outcome = self.reason
            elif code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
                outcome = 'failed_exit'
            else:
                try:
                    with sqlite3.connect(str(self.database), timeout=.25) as connection:
                        receipt = last_cleanup(connection)
                    outcome = ('success' if receipt.get('attempt') == token
                               else 'missing_receipt')
                except (sqlite3.Error, OSError, ValueError):
                    outcome = 'receipt_unavailable'
            messages = {
                'failed_start': 'Archive cleanup could not start.',
                'failed_exit': 'Archive cleanup worker failed; completed removals, if any, are unknown.',
                'timeout': 'Archive cleanup timed out; completed removals, if any, are unknown.',
                'cancelled': 'Archive cleanup was interrupted; completed removals, if any, are unknown.',
                'missing_receipt': 'Archive cleanup ended without a matching completion receipt.',
                'receipt_unavailable': 'Archive cleanup result could not be verified because storage is unavailable.',
            }
            self.cleanup_outcome = {'attempt': token, 'state': outcome}
            self.cleanup_error = messages.get(outcome, '')
            self.local_error = self.cleanup_error
            try:
                with sqlite3.connect(str(self.database), timeout=.25) as connection:
                    save_cleanup_attempt(connection, token, outcome)
            except (sqlite3.Error, OSError, ValueError):
                # Retain the safe in-process outcome when SQLite is locked.
                if not self.cleanup_error:
                    self.cleanup_error = 'Archive cleanup completed, but attempt history could not be saved.'
                    self.local_error = self.cleanup_error
        else:
            try:
                # A normally completed worker already cleared its token. This is a
                # no-op then; a killed/missing-result worker gets an owned failure.
                self.schedule.finish(token, {'status': 'error'}, cancelled=self.reason == 'cancelled')
            except (sqlite3.Error, OSError, ValueError):
                self.local_error = 'GDELT result storage unavailable; saved retry time remains in effect.'
        process.finished.disconnect(self._finished)
        process.errorOccurred.disconnect(self._process_error)
        self.process = None
        self.token = None
        self._maintenance = False
        process.deleteLater()
        self.changed.emit()

    @Slot()
    def _timeout(self):
        if self.process is not None:
            self._stop('timeout')

    def _stop(self, reason):
        process = self.process
        if process is None:
            return
        self.reason = reason
        self.deadline.stop()
        # waitForFinished can emit finished/error synchronously. Defer our
        # cleanup until that native call has returned, rather than finalizing
        # the sender reentrantly while the stop operation still owns it.
        was_blocked = process.blockSignals(True)
        try:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                if not process.waitForFinished(2500):
                    self.active = False
                    self.timer.stop()
                    self.local_error = 'GDELT worker termination was not confirmed; no replacement will start.'
                    self.changed.emit()
                    raise RuntimeError(self.local_error)
        finally:
            process.blockSignals(was_blocked)
        if process is self.process:
            self._done(process, self.token, process.exitCode(), process.exitStatus())

    def review_retry(self):
        self.schedule.review_retry()
        self.tick()
        self.changed.emit()

    def close(self):
        self.active = False
        self.closed = True
        self.timer.stop()
        self._stop('cancelled')
