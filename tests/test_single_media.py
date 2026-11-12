"""Actual replacement widgets and lifecycle; live decoding has its own probe."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import socket
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QObject,Signal,QUrl
from PySide6.QtWidgets import QApplication,QMessageBox
from global_pulse.internet_radio import RadioPanel,AudioSession,station,valid_presets,STATIONS
from global_pulse.single_media import MediaPanel,Television

@pytest.fixture(scope='session')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*a,**k):raise AssertionError('Offline media tests cannot connect')
    monkeypatch.setattr(socket,'getaddrinfo',blocked)
    monkeypatch.setattr(socket.socket,'connect',blocked)
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)

class FakeSession(QObject):
    changed=Signal(str,str)
    instances=[]
    def __init__(self,identifier,parent=None):
        super().__init__(parent);self.identifier=identifier;self.stopped=False;self.started=False
        self.volume=None;self.muted=None;self.__class__.instances.append(self)
    def start(self,volume=60,muted=False):
        self.started=True;self.volume=volume;self.muted=muted
        self.changed.emit('CONNECTING','Opening');return True
    def stop(self):self.stopped=True;self.changed.emit('OFF','Stopped')
    def set_volume(self,value):self.volume=value
    def set_muted(self,value):self.muted=value

@pytest.fixture
def radio(app):
    FakeSession.instances=[]
    p=RadioPanel(session_factory=FakeSession,confirm=lambda:True)
    yield p
    p.shutdown();p.deleteLater();app.processEvents()

@pytest.mark.parametrize('bad',[None,{},[],True,'https://127.0.0.1/','unknown'])
def test_no_arbitrary_stream_url_admission(bad):
    with pytest.raises(ValueError):station(bad)

@pytest.mark.parametrize('bad',[None,{},True,17,'wnyc_fm'])
def test_malformed_presets_are_empty(bad):assert valid_presets(bad)==[None]*5

def test_presets_store_only_known_station_ids():
    assert valid_presets(['wnyc_fm',{'url':'https://evil.example'},['deutschlandfunk'],'bad','deutschlandfunk'])==['wnyc_fm',None,None,None,'deutschlandfunk']

def test_initial_panel_is_off_and_no_player_created(radio):
    assert radio.status.text()=='OFF'
    assert not radio.power.isChecked() and not FakeSession.instances
    assert radio.selector.count()==len(STATIONS)

def test_power_connects_and_does_not_claim_playing_early(radio):
    radio.power.click()
    assert len(FakeSession.instances)==1
    assert radio.status.text()=='CONNECTING'
    FakeSession.instances[-1].changed.emit('BUFFERING','Waiting')
    assert radio.status.text()=='BUFFERING'
    FakeSession.instances[-1].changed.emit('PLAYING','Decoded')
    assert radio.status.text()=='PLAYING'

def test_declined_consent_never_creates_backend(radio):
    radio._confirm=lambda:False
    radio.power.click()
    assert not FakeSession.instances and not radio.power.isChecked()
    assert radio.status.text()=='OFF'

def test_channel_change_stops_old_before_new_and_ignores_late_state(radio):
    radio.power.click();old=FakeSession.instances[-1]
    radio.next.click();new=FakeSession.instances[-1]
    assert old.stopped and new is not old and new.started
    old.changed.emit('PLAYING','late')
    assert radio.status.text()=='CONNECTING'
    new.changed.emit('PLAYING','current')
    assert radio.detail.text()=='current'

def test_channel_selection_while_off_never_connects(radio):
    radio.next.click();radio.previous.click()
    assert not FakeSession.instances and radio.status.text()=='OFF'

def test_off_stops_backend_and_ignores_queued_completion(radio):
    radio.power.click();session=FakeSession.instances[-1]
    radio.off();session.changed.emit('PLAYING','late')
    assert session.stopped and radio._session is None
    assert radio.status.text()=='OFF' and not radio.power.isChecked()

def test_error_stops_connection_and_does_not_retry(radio,app):
    radio.power.click();session=FakeSession.instances[-1]
    session.changed.emit('ERROR','Unavailable')
    for _ in range(3):app.processEvents()
    assert radio.status.text()=='ERROR' and radio.detail.text()=='Unavailable'
    assert session.stopped and len(FakeSession.instances)==1
    assert not radio.power.isChecked()

def test_volume_and_mute_reach_active_player(radio):
    radio.power.click();session=FakeSession.instances[-1]
    radio.volume.setValue(23);radio.mute.click()
    assert session.volume==23 and session.muted is True

def test_preset_roundtrip_and_legacy_settings_not_overwritten(radio,app):
    values={'radio_presets':[{'receiver':'https://old.example'}]}
    def put(k,v):values[k]=copy.deepcopy(v)
    radio.configure_preferences(lambda k,d=None:values.get(k,d),put)
    radio.selector.setCurrentIndex(1);assert radio.save_preset(2)
    assert values['radio_presets']==[{'receiver':'https://old.example'}]
    other=RadioPanel(session_factory=FakeSession,confirm=lambda:True)
    try:
        other.configure_preferences(lambda k,d=None:values.get(k,d),put)
        assert other.recall_preset(2)
        assert other.selector.currentData()=='deutschlandfunk'
        assert not other.power.isChecked() and not FakeSession.instances
    finally:other.shutdown();other.deleteLater()

def test_failed_preset_save_preserves_previous_state(radio):
    def failed(*a):raise OSError('local write failed')
    radio.configure_preferences(lambda k,d=None:d,failed)
    assert not radio.save_preset(0) and radio.presets==[None]*5

def test_shutdown_prevents_further_power(radio):
    radio.power.click();session=FakeSession.instances[-1]
    radio.shutdown();radio.power.click()
    assert session.stopped and len(FakeSession.instances)==1 and radio.status.text()=='OFF'

def test_timeout_clears_native_source_without_retry(app,monkeypatch):
    s=AudioSession('wnyc_fm')
    calls=[]
    class Player:
        def stop(self):calls.append('stop')
        def setSource(self,url):calls.append(url.toString())
    s.player=Player();s.active=True;s.started=1.0
    monkeypatch.setattr('global_pulse.internet_radio.time.monotonic',lambda:40.0)
    s._watch()
    assert s.state=='ERROR' and not s.active and s.closed
    assert calls==['stop',''] and not s.watchdog.isActive()
    s.deleteLater()

def test_new_media_has_one_tv_and_no_radio_video_tiles(app,monkeypatch):
    monkeypatch.setattr('global_pulse.internet_radio.AudioSession',FakeSession)
    panel=MediaPanel()
    try:
        assert len(panel.tiles)==1 and panel.tiles[0] is panel.tv
        assert isinstance(panel.radio,RadioPanel)
        assert not panel.radio.findChildren(Television)
        assert [panel.tabs.tabText(i) for i in range(3)]==['TV','Radio','Cameras']
    finally:panel.shutdown();panel.deleteLater()

def test_event_refresh_and_tab_switch_cannot_restart_radio(app,monkeypatch):
    monkeypatch.setattr('global_pulse.internet_radio.AudioSession',FakeSession)
    FakeSession.instances=[]
    panel=MediaPanel();panel.radio._confirm=lambda:True
    try:
        panel.tabs.setCurrentIndex(1);panel.radio.power.click()
        current=FakeSession.instances[-1]
        panel.set_event({'id':'event','reports':[],'media':[]})
        assert panel.radio._session is current and not current.stopped
        panel.tabs.setCurrentIndex(0)
        assert current.stopped and panel.radio.status.text()=='OFF'
        panel.set_event({'id':'another','reports':[]})
        panel.tabs.setCurrentIndex(1)
        assert len(FakeSession.instances)==1 and panel.radio.status.text()=='OFF'
    finally:panel.shutdown();panel.deleteLater()

def test_external_tv_and_receiver_directories_not_admitted(app):
    tv=Television()
    try:
        tv.set_catalog([{'url':'https://www.bbc.com/','type':'video'}, {'url':'https://websdr.org/','type':'radio'}, {'url':'https://www.youtube.com/watch?v=abcdefghijk','type':'video'}])
        assert not tv._builtins and not tv.catalog
        assert 'No packaged-verified TV' in tv.display.text()
        tv.video_url.setText('https://www.youtube.com/@somechannel/live')
        assert not tv.add_video()
        tv.video_url.setText('https://www.youtube.com/watch?v=abcdefghijk')
        assert tv.add_video() and len(tv.catalog)==1
        assert 'Your video' in tv.selector.currentText()
        assert tv.view is None
    finally:tv.stop();tv.deleteLater()

def test_tv_progress_not_page_load_or_constant_clock(app):
    tv=Television()
    try:
        tv._requested=True;generation=tv._generation
        tv._observed(generation,{'missing':True})
        assert tv.tv_status.text()!='PLAYING'
        tv._observed(generation,{'time':0.0,'paused':False,'ready':4})
        assert tv.tv_status.text()!='PLAYING'
        tv._observed(generation,{'time':1.0,'paused':False,'ready':4})
        assert tv.tv_status.text()=='PLAYING'
        tv.stop();tv._observed(generation,{'time':2.0,'paused':False,'ready':4})
        assert tv.tv_status.text()=='OFF'
    finally:tv.stop();tv.deleteLater()

def test_actual_mainwindow_uses_replacement_not_legacy(app,tmp_path):
    from global_pulse.controller import Controller
    from global_pulse.ui import MainWindow
    c=Controller(tmp_path,demo=True);w=MainWindow(c)
    try:
        assert isinstance(w.media,MediaPanel)
        assert w.media.radio.status.text()=='OFF'
        assert len(w.media.tiles)==1
        c.data_changed.emit();app.processEvents()
        assert w.media.radio._session is None
    finally:w._force_close=True;w.close();c.close();w.deleteLater();app.processEvents()
