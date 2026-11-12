"""Engineering actual-control storage tests; temporary DB, no public requests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from contextlib import contextmanager
import socket
import sqlite3
import sys
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from global_pulse.controller import Controller
from global_pulse.gdelt_controls import GdeltControls


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controls(tmp_path, app, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Storage-control tests cannot contact providers')
    monkeypatch.setattr(socket, 'getaddrinfo', denied)
    monkeypatch.setattr(socket.socket, 'connect', denied)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *args: errors.append(args))
    controller = Controller(tmp_path)
    widget = GdeltControls(controller)
    yield widget, controller, errors
    widget.close()
    controller.close()
    assert not errors, 'An exception escaped a Qt signal handler'


@contextmanager
def locked(controller):
    connection = sqlite3.connect(controller._gdelt.schedule.database, timeout=.1)
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield
    finally:
        connection.rollback()
        connection.close()


def test_actual_retry_click_preserves_suspension_and_error_until_success(controls):
    widget, controller, errors = controls
    schedule = controller._gdelt.schedule
    token = schedule.claim(jitter=0)
    schedule.finish(token, {'status':'error','http_status':403})
    before = schedule.status()
    widget.refresh()
    assert widget.retry.isEnabled()
    with locked(controller):
        widget.retry.click()
        assert not errors and controller._gdelt.process is None
        assert 'Could not update retry state' in widget.status_label.text()
        widget.refresh()
        assert 'Could not update retry state' in widget.status_label.text()
    assert schedule.status() == before
    widget.refresh()
    assert widget.retry.isEnabled()
    assert 'Could not update retry state' in widget.status_label.text()
    widget.retry.click()
    assert schedule.status()['state'] == 'waiting'
    assert schedule.status()['next_at'] == before['next_at']
    assert 'Could not update retry state' not in widget.status_label.text()
    assert controller._gdelt.process is None


@pytest.mark.parametrize('initial', [False, True])
def test_failed_enable_or_disable_restores_saved_checkbox(controls, monkeypatch, initial):
    widget, controller, errors = controls
    controller.set_setting('gdelt_batches_enabled', initial)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    with locked(controller):
        widget.enable.setChecked(not initial)
        assert not errors
        assert widget.enable.isChecked() is initial
        assert 'Could not apply the GDELT collection setting' in widget.status_label.text()
    assert controller.get_setting('gdelt_batches_enabled') is initial
    assert controller._gdelt.process is None
    widget.refresh()
    assert 'Could not apply the GDELT collection setting' in widget.status_label.text()


def test_failed_retention_edit_restores_value_and_success_clears_error(controls):
    widget, controller, errors = controls
    before = controller.get_setting('gdelt_retention_days')
    with locked(controller):
        widget.days.setValue(31)
        assert not errors and widget.days.value() == before
        assert 'Could not save GDELT retention' in widget.status_label.text()
    assert controller.get_setting('gdelt_retention_days') == before
    widget.refresh()
    assert 'Could not save GDELT retention' in widget.status_label.text()
    widget.days.setValue(31)
    assert controller.get_setting('gdelt_retention_days') == 31
    assert 'Could not save GDELT retention' not in widget.status_label.text()
    assert controller._gdelt.process is None


@pytest.mark.parametrize('method', ['gdelt_status', 'get_setting'])
def test_refresh_read_failure_is_safe_and_preserves_last_controls(controls, monkeypatch, method):
    widget, controller, errors = controls
    before = (widget.enable.isChecked(), widget.days.value())
    def unavailable(*args, **kwargs):
        raise sqlite3.DatabaseError('private database path and diagnostic must not be shown')
    monkeypatch.setattr(controller, method, unavailable)
    widget.refresh()
    assert not errors and not widget.retry.isEnabled()
    assert before == (widget.enable.isChecked(), widget.days.value())
    assert 'storage is unavailable' in widget.status_label.text()
    assert 'private database' not in widget.status_label.text()
    assert controller._gdelt.process is None
