"""Issue76 owner Windows failures: opt-in HAM receiver and tab responsiveness.

All media tests are intentionally offline: they verify correct policy/selection,
source identities and truthful UI state, not actual audio/video playback.
"""
from __future__ import annotations
import inspect
import os
from datetime import datetime,timedelta,timezone
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtWidgets import QApplication,QMessageBox

from global_pulse.controller import Controller
from global_pulse.internet_radio import (
    RadioPanel, OWNER_TEST_WEBDR_ORIGIN, _owner_legacy_websdr,
)
from global_pulse.sdr_directory import public_receiver_url
from global_pulse.ui import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_exact_public_na5b_origin_has_consent_only_embedded_test(app):
    receiver=RadioPanel(confirm=lambda:False)
    try:
        receiver._select_na5b_test()
        assert receiver.receiver_url.text()==OWNER_TEST_WEBDR_ORIGIN
        assert receiver.receiver_type.currentData()=="websdr"
        assert receiver.receiver_connect.isEnabled()
        assert "unencrypted" in receiver.receiver_list_note.text().lower()
        url,host=receiver._tuned_receiver_url()
        assert url=="http://na5b.com:8901/?tune=7100usb"
        assert host=="na5b.com"
        assert receiver.sdr_state=="OFF"
        receiver.receiver_type.setCurrentIndex(-1)  # No supported protocol.
        assert not receiver.receiver_connect.isEnabled()
        with pytest.raises(ValueError):
            receiver._receiver_target()
    finally:
        receiver.shutdown()
        receiver.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("url",(
    "http://example.com:8901/",
    "http://na5b.com:8902/",
    "http://na5b.com:8073/",
    "http://127.0.0.1:8901/",
    "http://localhost:8901/",
    "https://na5b.com:8901/",
    "http://na5b.com:8901@localhost/",
))
def test_no_blanket_custom_port_or_private_host_policy(app,url):
    receiver=RadioPanel(confirm=lambda:False)
    try:
        receiver.receiver_type.setCurrentIndex(
            receiver.receiver_type.findData("websdr")
        )
        receiver.receiver_url.setText(url)
        assert not receiver.receiver_connect.isEnabled()
        with pytest.raises(ValueError):
            receiver._receiver_target()
    finally:
        receiver.shutdown()
        receiver.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_na5b_consent_is_required_before_any_webengine_request(app,monkeypatch):
    receiver=RadioPanel(confirm=lambda:False)
    try:
        receiver._select_na5b_test()
        url,host=receiver._tuned_receiver_url()
        calls=[]
        monkeypatch.setattr(receiver,"_ensure_receiver_view",
                            lambda *_:calls.append("created"))
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *args,**kwargs: QMessageBox.StandardButton.No
        )
        assert not receiver._load_receiver_url(url,host,require_consent=True)
        assert not calls
        assert receiver.sdr_state=="OFF"
    finally:
        receiver.shutdown()
        receiver.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.fixture
def desktop(app,tmp_path):
    controller=Controller(tmp_path,demo=True)
    now=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    controller.store.ingest([
        dict(id=f"qa-tab-{i}",source_id="test-tab",publisher="QA",
             title=f"SYNTHETIC {kind} headline {i}",
             event_key=f"qa-tab:{i}", summary="Offline only",
             url=f"https://example.org/issue76/{i}",published_at=now,
             retrieved_at=now,category=kind,region="Global",
             country="",synthetic=True,severity="unassessed")
        for i,kind in enumerate(("Disaster","Health","Government"))
    ])
    window=MainWindow(controller)
    window.show()
    app.processEvents()
    yield window,controller
    window._force_close=True
    window.close()
    controller.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_one_unchanged_workspace_tab_load_per_category(desktop,monkeypatch):
    window,_=desktop
    calls=[]
    for page,name in ((1,"_populate_situations"),(2,"_populate_economy"),
                      (3,"_populate_sources"),(4,"_populate_alerts"),
                      (5,"_generate_brief")):
        original=getattr(window,name)
        def tracking(*args,_name=name,_func=original,**kwargs):
            calls.append(_name)
            return _func(*args,**kwargs)
        monkeypatch.setattr(window,name,tracking)
    for _ in range(15):
        for index in (1,2,3,4,5,0):
            window.open_page(index)
    assert calls==[
        "_populate_situations","_populate_economy","_populate_sources",
        "_populate_alerts","_generate_brief"
    ]
    # New evidence legitimately invalidates previously cached pages.
    window.refresh_data()
    calls.clear()
    window.open_page(2)
    window.open_page(3)
    window.open_page(2)
    assert calls==["_populate_economy","_populate_sources"]


def test_native_delivery_signal_does_not_reload_world_map(desktop,monkeypatch,app):
    window,controller=desktop
    reloaded=[]
    monkeypatch.setattr(window.world_map,"set_events",
                        lambda *a,**k:reloaded.append(True))
    changes=[]
    controller.data_changed.connect(lambda:changes.append(True))
    controller.notification_status="Native notification delivered"
    controller.notification_changed.emit()
    app.processEvents()
    assert not reloaded
    assert not changes
    window.open_page(4)
    assert "Native notification delivered" in window.notification_label.text()


def test_native_tray_has_single_click_context_fallback():
    from global_pulse import __main__ as bootstrap
    source=inspect.getsource(bootstrap.main)
    assert "ActivationReason.DoubleClick" in source
    assert "ActivationReason.Trigger" in source
    assert "menu.popup(QCursor.pos())" in source
    assert "tray.setContextMenu(menu)" in source
    assert "controller.notification_changed.emit()" in source
