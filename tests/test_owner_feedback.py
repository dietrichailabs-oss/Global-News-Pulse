"""Owner first-use feedback: real SQLite/Qt and bounded synthetic side effects.
No live camera/model downloads or native Windows observations in these tests.
"""
import json
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from PySide6.QtCore import QPointF,Qt,QProcess,QCoreApplication,QEvent
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication,QListWidget,QMessageBox,QPushButton
from global_pulse.controller import Controller
from global_pulse.core import Store,build_brief
from global_pulse.map_widget import WorldMap
from global_pulse.brief_rendering import brief_html
from global_pulse.theme import SEVERITY
from global_pulse.camera_context import camera_catalog,associated_cameras,approved_camera
from global_pulse.media_widget import MediaPanel
from global_pulse.camera_snapshot import CameraSnapshot
from global_pulse.model_manager import ModelManager

OLD='2026-10-01T12:00:00Z'
NOW='2026-11-09T12:00:00Z'
SINCE='2026-11-08T12:00:00Z'


def record(identity='a',severity='moderate',stamp=OLD,**kw):
    value=dict(id=identity,source_id='fixture-authority',publisher='Fictional authority',
        title='Fictional Northhaven '+identity,summary='Isolated synthetic test report '+identity,
        url='https://authority.example/'+identity,published_at=stamp,retrieved_at=stamp,
        event_key=identity,severity=severity,official=True,official_scope='measurement',
        independence='original',origin_id='fixture-authority',synthetic=True,
        region='Northhaven',country='Norland',category='Disaster',latitude=30.0,longitude=40.0)
    value.update(kw);return value


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(tmp_path,app):
    c=Controller(tmp_path,demo=True)
    yield c
    # Dispose test-created unparented dialogs while QApplication is still alive.
    # Production dialogs are owned by the main window.
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget,ModelManager) and widget.controller is c:
            widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    c.close();app.processEvents()


@pytest.mark.parametrize('severity',['critical','high','moderate'])
def test_significant_map_persists_past_feed_window_and_restart(tmp_path,severity):
    path=tmp_path/'archive.sqlite3'
    with Store(path,mode='synthetic') as s:
        event=s.ingest([record(severity=severity)],now=OLD)[0]
        assert not s.list_events(since=SINCE)
    with Store(path,mode='synthetic') as s:
        found=s.list_events(since=SINCE,map_view=True,keep_significant=True)
        assert [e['id'] for e in found]==[event['id']]
        assert found[0]['retained_on_map']
        assert 'no newer status' in found[0]['map_retention_note'].lower()
        assert not s.list_events(since=SINCE,map_view=True,keep_significant=False)


@pytest.mark.parametrize('severity',['informational','unassessed'])
def test_low_importance_still_obeys_time_range(tmp_path,severity):
    with Store(tmp_path/'a.db',mode='synthetic') as s:
        s.ingest([record(severity=severity)],now=OLD)
        assert not s.list_events(since=SINCE,map_view=True,keep_significant=True)


def test_map_not_crowded_out_by_500_unlocated_feed_records(tmp_path):
    with Store(tmp_path/'a.db',mode='synthetic') as s:
        old=s.ingest([record()],now=OLD)[0]
        s.ingest([record(str(i),stamp=NOW,latitude=None,longitude=None) for i in range(510)],now=NOW)
        feed=s.list_events(since=SINCE,limit=500)
        assert len(feed)==500 and all(e['id']!=old['id'] for e in feed)
        mapped=s.list_events(since=SINCE,map_view=True,keep_significant=True,limit=5000)
        assert [e['id'] for e in mapped]==[old['id']]


@pytest.mark.parametrize('filters',[{'query':'absentneedle'},{'category':'Economy'},{'region':'Elsewhere'}])
def test_significant_retention_respects_explicit_filters(tmp_path,filters):
    with Store(tmp_path/'a.db',mode='synthetic') as s:
        s.ingest([record()],now=OLD)
        assert not s.list_events(since=SINCE,map_view=True,keep_significant=True,**filters)


def test_retraction_stops_live_marker_but_does_not_change_old_snapshot(tmp_path):
    with Store(tmp_path/'a.db',mode='synthetic') as s:
        s.ingest([record()],now=OLD)
        s.ingest([record('a',stamp=NOW,kind='retraction',status='retracted',summary='Fictional withdrawal')],now=NOW)
        assert not s.list_events(map_view=True,keep_significant=True)
        historic=s.list_events(before=OLD,map_view=True,keep_significant=True)
        assert len(historic)==1 and historic[0]['status']=='active'


def test_downgrade_ends_age_override_without_erasing_history(tmp_path):
    with Store(tmp_path/'a.db',mode='synthetic') as s:
        original=s.ingest([record()],now=OLD)[0]
        s.ingest([record('a',severity='informational',stamp='2026-10-02T12:00:00Z')],now='2026-10-02T12:00:00Z')
        assert not s.list_events(since=SINCE,map_view=True,keep_significant=True)
        assert s.get_event(original['id'],at=OLD)['severity']=='moderate'


def test_history_does_not_import_retained_future_view(tmp_path):
    with Store(tmp_path/'a.db',mode='synthetic') as s:
        s.ingest([record()],now=OLD)
        assert not s.list_events(since=SINCE,before=NOW,map_view=True,keep_significant=True)


def test_future_only_record_cannot_get_a_retained_pin(tmp_path):
    with Store(tmp_path/'a.db',mode='synthetic') as s:
        s.ingest([record(stamp='2026-12-01T12:00:00Z')],now=NOW)
        assert not s.list_events(since=SINCE,map_view=True,keep_significant=True)


def test_live_ui_map_is_separate_from_feed(controller,app):
    from global_pulse.ui import MainWindow
    controller.store.ingest([record()],now=OLD)
    w=MainWindow(controller)
    try:
        w.refresh_data()
        assert w.feed_list.count()==0
        assert len(w.world_map.events)==1
        assert '1 significant retained' in w.count_label.text()
    finally:w._force_close=True;w.close()


def cluster():
    return [(dict(id='a',title='First <fake>',severity='moderate',verification='official',region='A'),QPointF(100,100)),
            (dict(id='b',title='Second',severity='critical',verification='unverified',region='B'),QPointF(100,100))]


def test_cluster_hover_lists_both_events_and_escapes(app):
    text=WorldMap.cluster_tooltip(cluster())
    assert 'First &lt;fake&gt;' in text and 'Second' in text
    assert text.index('Second')<text.index('First')
    assert 'CRITICAL' in text and 'MODERATE' in text


def test_cluster_click_chooser_selects_either_exact_event(app):
    m=WorldMap();received=[];m.event_selected.connect(received.append)
    m.show_cluster(cluster(),QPointF(100,100));app.processEvents()
    dialog=m.cluster_dialog;listing=dialog.findChild(QListWidget)
    assert listing.count()==2
    listing.setCurrentRow(1)
    next(b for b in dialog.findChildren(QPushButton) if b.text()=='Open selected event').click()
    assert received==['a'] and m.selected_event=='a'
    m.close();app.processEvents()


@pytest.mark.parametrize('severity',list(SEVERITY))
def test_brief_severity_label_and_actual_color(controller,severity):
    e=controller.store.ingest([record(severity=severity)],now=OLD)[0]
    text=build_brief([e]);assert 'Severity: **'+severity.upper()+'**' in text
    html=brief_html([e]);assert SEVERITY[severity].lower() in html.lower()
    doc=QTextDocument();doc.setHtml(html)
    assert severity.upper() in doc.toPlainText()
    assert 'Fictional authority' in doc.toPlainText()


def test_html_export_has_colors_and_synthetic_warning(controller,tmp_path):
    current=datetime.now(timezone.utc).isoformat()
    controller.store.ingest([record(stamp=current)],now=current)
    path=tmp_path/'brief.html';controller.export_brief(path)
    text=path.read_text()
    assert SEVERITY['moderate'] in text and 'SYNTHETIC' in text


def test_model_manager_has_download_not_just_catalog_label(controller):
    dialog=ModelManager(controller)
    try:
        for code,(status,progress,button,cancel) in dialog.rows.items():
            assert 'not installed' in status.text()
            assert button.text()=='Download' and button.isEnabled()
            assert not cancel.isEnabled()
    finally:dialog.close()


def test_model_download_denial_does_not_queue(controller,monkeypatch):
    submitted=[];monkeypatch.setattr(controller._workers,'submit',lambda *a:submitted.append(a))
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
    assert not controller.download_translation_model('fr')
    assert not submitted and not controller._model_jobs


def test_model_download_queues_install_only_and_reports_failure(controller,monkeypatch):
    submitted=[];statuses=[];controller.model_download_changed.connect(lambda *a:statuses.append(a))
    monkeypatch.setattr(controller._workers,'submit',lambda *a:submitted.append(a) or True)
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    assert controller.download_translation_model('fr')
    rid,lang,text,install=submitted[0]
    assert lang=='fr' and text=='' and install is True
    assert not controller.download_translation_model('fr')
    controller._translation_complete(rid,lang,'','NetworkError')
    assert not controller._model_jobs and 'failed' in statuses[-1][1]


def test_installed_model_has_no_duplicate_download(controller,monkeypatch):
    monkeypatch.setattr(controller.translator,'installed',lambda _:True)
    dialog=ModelManager(controller)
    assert all(not row[2].isEnabled() and row[2].text()=='Installed' for row in dialog.rows.values())
    assert not controller.download_translation_model('fr');dialog.close()


def test_model_progress_uses_actual_bytes(controller):
    dialog=ModelManager(controller)
    dialog.update_progress('fr',5_000_000,10_000_000)
    assert dialog.rows['fr'][1].value()==50
    assert '5.0 / 10.0 MB' in dialog.rows['fr'][0].text();dialog.close()


def test_worker_install_only_does_not_run_inference(tmp_path,monkeypatch):
    from global_pulse.translation import Translator
    from global_pulse.translation_worker import main
    work=tmp_path/'translation-jobs'/'job-test';work.mkdir(parents=True)
    request=dict(data_dir=str(tmp_path),work_dir=str(work),language='fr',text='',install=True)
    (work/'request.json').write_text(json.dumps(request))
    calls=[]
    monkeypatch.setattr(Translator,'download',lambda self,c,progress=None:calls.append(c))
    monkeypatch.setattr(Translator,'translate',lambda *a:pytest.fail('install-only must not infer'))
    assert main(['--job',str(work)])==0 and calls==['fr']
    assert json.loads((work/'response.json').read_text())=={'text':'','error':''}


def test_real_owned_download_cancel_terminates_child(controller,app,monkeypatch):
    import sys
    monkeypatch.setattr(controller._workers,'command',lambda:(sys.executable,['-c','import time;time.sleep(30)']))
    results=[];controller._workers.completed.connect(lambda *a:results.append(a))
    controller._workers.submit('cancel-test','fr','',True)
    end=time.monotonic()+4
    while controller._workers.process.state()!=QProcess.ProcessState.Running and time.monotonic()<end:
        app.processEvents();time.sleep(.01)
    assert controller._workers.cancel('cancel-test')
    while not results and time.monotonic()<end:app.processEvents();time.sleep(.01)
    assert results and 'cancelled' in results[-1][3]
    assert controller._workers.process is None
    assert not list((controller.data_dir/'translation-jobs').iterdir())


@pytest.mark.parametrize('title',['Grand Canyon wildfire','Kīlauea eruption','Halemaʻumaʻu activity'])
def test_public_camera_matches_named_area_only(title):
    assert associated_cameras(dict(title=title,status='active'))


@pytest.mark.parametrize('event',[{'title':'Earthquake south of Fiji'},{'region':'North America'},
 {'title':'Kilauea event','status':'retracted'},{'title':'Grand Canyon event','future_dated':True}])
def test_no_unrelated_or_resolved_camera_substitution(event):
    assert not associated_cameras(event)


def test_untrusted_feed_cannot_supply_snapshot_endpoint(app):
    entry=dict(camera_catalog()[0],snapshot_url='http://127.0.0.1/private')
    assert approved_camera(entry) is None
    with pytest.raises(ValueError):CameraSnapshot(entry)


def test_camera_auto_requires_consent_and_stop_all_disables(app,monkeypatch):
    panel=MediaPanel();calls=[]
    for tile in panel.tiles:monkeypatch.setattr(tile,'connect_camera',lambda **k:calls.append(k))
    event=dict(id='event',title='Grand Canyon wildfire',status='active',severity='high')
    panel.set_event(event);assert not calls
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
    panel.auto_camera_check.setChecked(True);assert not calls and not panel.auto_cameras
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    panel.auto_camera_check.setChecked(True);assert calls==[{'auto_consented':True}]
    panel.stop();calls.clear();panel.set_event(event)
    assert not calls and not panel.auto_cameras;panel.close()


@pytest.mark.parametrize('extra',[{'synthetic':True},{'historical_view':True},{'severity':'informational'}])
def test_auto_camera_not_opened_for_synthetic_history_or_low_event(app,monkeypatch,extra):
    panel=MediaPanel();calls=[]
    for tile in panel.tiles:monkeypatch.setattr(tile,'connect_camera',lambda **k:calls.append(k))
    panel.restore_auto_cameras(True)
    event=dict(id='event',title='Grand Canyon wildfire',status='active',severity='high')
    event.update(extra);panel.set_event(event)
    assert not calls;panel.stop();panel.close()


def test_individual_camera_stop_prevents_refresh_reconnect(app,monkeypatch):
    panel=MediaPanel();panel.set_event(dict(id='event',title='Grand Canyon wildfire',status='active',severity='high'))
    tile=panel.tiles[0];tile.user_stop()
    assert tile.auto_camera_suspended and not tile.connect_camera(auto_consented=True)
    panel.close()


def test_snapshot_request_is_exact_no_cookie_no_redirect_and_stop_cancels(app,monkeypatch):
    from PySide6.QtCore import QObject,Signal,QByteArray
    from PySide6.QtNetwork import QNetworkRequest
    class Reply(QObject):
        readyRead=Signal();finished=Signal()
        aborted=False
        def setReadBufferSize(self,size):assert size==65536
        def readAll(self):return QByteArray()
        def abort(self):self.aborted=True
    CameraSnapshot._attempts.clear();CameraSnapshot._images.clear()
    image=CameraSnapshot(camera_catalog()[0]);reply=Reply();requests=[]
    monkeypatch.setattr(image.manager,'get',lambda req:requests.append(req) or reply)
    image.start()
    request=requests[0]
    assert request.url().toString()==camera_catalog()[0]['snapshot_url']
    assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute)==QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
    assert request.attribute(QNetworkRequest.Attribute.CookieLoadControlAttribute)==QNetworkRequest.LoadControl.Manual
    assert request.attribute(QNetworkRequest.Attribute.CookieSaveControlAttribute)==QNetworkRequest.LoadControl.Manual
    assert image.timer.interval()>=900000
    image.refresh();assert len(requests)==1  # No parallel/faster poll.
    image.stop();assert reply.aborted and image.reply is None and not image.timer.isActive()
    image.deleteLater()


def test_controller_reuses_model_dialog_and_explicit_exit_stops_downloads(controller,app):
    controller.manage_translation_models();first=controller._model_dialog
    first.close();controller.manage_translation_models()
    assert controller._model_dialog is first
    first.close()


def test_camera_switching_cannot_bypass_provider_cadence(app,monkeypatch):
    from time import monotonic
    item=camera_catalog()[0]
    CameraSnapshot._attempts[item['id']]=monotonic()
    CameraSnapshot._images.clear()
    camera=CameraSnapshot(item)
    monkeypatch.setattr(camera.manager,'get',lambda *a:pytest.fail('rapid reopen must not poll'))
    camera.start()
    assert 'deferred' in camera.text().lower()
    camera.stop();camera.deleteLater();CameraSnapshot._attempts.clear()


def test_camera_registry_is_required_in_frozen_package():
    root=Path(__file__).resolve().parents[1]
    assert '"context_cameras.json"' in (root/'packaging/GlobalPulse.spec').read_text()
    assert '"_internal/global_pulse/resources/context_cameras.json"' in (root/'scripts/package_manifest.py').read_text()
