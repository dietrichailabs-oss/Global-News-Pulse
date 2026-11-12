"""Engineering feature-successor for QA76's now-obsolete missing-cap wording.

The original QA file/blob is preserved, including its failing final string
assertion on PR79. Every consent/paused/retention assertion below is the same
behavior; only the feature-absence assertion becomes positive storage checks.
This is not an independent QA replacement or a claim that the old case passes.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import socket
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from global_pulse.controller import Controller
from global_pulse.gdelt_controls import GdeltControls
from global_pulse.archive_storage_controls import ArchiveStorageControls

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_consent_and_paused_state_with_implemented_storage_controls(tmp_path, app, monkeypatch):
    def denied(*args,**kwargs):
        raise AssertionError('Storage/consent acceptance cannot use the public network')
    monkeypatch.setattr(socket,'getaddrinfo',denied)
    monkeypatch.setattr(socket.socket,'connect',denied)
    c=Controller(tmp_path)
    controls=GdeltControls(c)
    budget=ArchiveStorageControls(c)
    try:
        monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
        controls.enable.setChecked(True)
        assert not c.get_setting('gdelt_batches_enabled') and not controls.enable.isChecked()
        assert c._gdelt.process is None
        monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
        controls.enable.setChecked(True)
        assert c.get_setting('gdelt_batches_enabled') and c._gdelt.process is None
        assert 'Paused' in controls.status_label.text()
        controls.days.setValue(31)
        assert c.get_setting('gdelt_retention_days')==31
        assert 'disk-size cap is not yet available' not in controls.info.text()
        assert 'Local news archive storage' in controls.info.text()
        assert budget.maximum.currentData()==30
        assert [budget.maximum.itemData(i) for i in range(budget.maximum.count())]==[5,10,15,20,30,50,100]
        budget.maximum.setCurrentIndex(budget.maximum.findData(10))
        assert c.get_setting('archive_max_gb')==10
        assert not c.monitoring and c._gdelt.process is None
    finally:
        budget.timer.stop();budget.close();controls.close();c.close()
