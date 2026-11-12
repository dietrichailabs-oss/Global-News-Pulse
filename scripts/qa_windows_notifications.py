"""Explicit, source-only Windows native-notification QA harness.

Synthetic reports are isolated and live collection is never started. This is not
shipped in the application. Native submission receipts do not prove visibility.
Cold activation and exact installer identity require separate artifact tests.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-native-tests",action="store_true",help="Explicitly consent to synthetic native Windows test notifications")
    parser.add_argument("--data-dir",type=Path,help="New empty test directory, or a directory previously marked by this harness")
    parser.add_argument("--activate",default="",help="Send a validated test event ID to the existing harness instance")
    args=parser.parse_args(argv)
    if not args.confirm_native_tests:parser.error("Use --confirm-native-tests to authorize visibly labeled synthetic native notifications.")
    if sys.platform!="win32":parser.error("This native acceptance harness requires Windows. Linux execution is not equivalent evidence.")
    helper=PROJECT/"build"/"notifications"/"GlobalPulse.Notifications.exe"
    if not helper.is_file():parser.error("Build the self-contained native helper into build/notifications first.")
    directory=(args.data_dir or Path(tempfile.mkdtemp(prefix="global-pulse-native-qa-"))).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    marker=directory/"QA_RUN.json"
    if any(directory.iterdir()) and not marker.exists():parser.error("Refusing an existing unmarked directory; choose an empty isolated QA directory.")
    if marker.exists():
        saved=json.loads(marker.read_text(encoding="utf-8"))
        if saved.get("kind")!="GlobalPulse synthetic native QA":parser.error("The directory marker does not identify this QA harness.")
        run_id=saved["run_id"]
    else:
        run_id=str(uuid.uuid4())
        marker.write_text(json.dumps({"kind":"GlobalPulse synthetic native QA","run_id":run_id,"started_at":datetime.now(timezone.utc).isoformat(),"live_collection":False,"exact_packaged_artifact":False,"cold_activation_test":"NOT COVERED"},indent=2),encoding="utf-8")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QDockWidget,QComboBox,QCheckBox,QInputDialog,QSystemTrayIcon,QMenu,QSpinBox
    from PySide6.QtCore import Qt
    from global_pulse.controller import Controller,in_quiet_hours
    from global_pulse.core import alert_reason
    from global_pulse.native_notifications import NativeNotifications
    from global_pulse.single_instance import SingleInstance
    from global_pulse.security import event_id
    from global_pulse.ui import MainWindow
    from global_pulse.__main__ import pulse_icon

    if args.activate:event_id(args.activate)
    app=QApplication([sys.argv[0]])
    app.setApplicationName("Global Pulse Native QA — Synthetic")
    app.setQuitOnLastWindowClosed(False)
    instance=SingleInstance(directory)
    if not instance.acquire(args.activate):return 0
    receipt_path=directory/"native-observations.jsonl"
    def record(kind,**values):
        payload={"at":datetime.now(timezone.utc).isoformat(),"run_id":run_id,"kind":kind,**values}
        with receipt_path.open("a",encoding="utf-8") as output:
            output.write(json.dumps(payload,ensure_ascii=False)+"\n");output.flush()
        print(json.dumps(payload,ensure_ascii=False),flush=True)

    class QAController(Controller):
        def __init__(self):
            super().__init__(directory,demo=True)
            self.monitoring=True
            self.last_batch=[]
            self.ids={}
            self.stamp=datetime.now(timezone.utc).isoformat()
            self.scenario=uuid.uuid4().hex[:8]

        def new_scenario(self):
            self.scenario=uuid.uuid4().hex[:8];self.ids={};self.last_batch=[];self.stamp=datetime.now(timezone.utc).isoformat()
            record("new_synthetic_scenario",scenario=self.scenario)
            self.status_changed.emit("New fictional scenario. Previous evidence remains in this isolated test archive.")

        def start(self):self.resume()
        def pause(self):
            self.monitoring=False;self.status_changed.emit("QA simulation paused · no collection runs in this harness");self.data_changed.emit()
        def resume(self):
            self.monitoring=True;self.status_changed.emit("QA synthetic actions enabled · no collection runs in this harness");self.data_changed.emit()
        def refresh(self):self.status_changed.emit("This QA harness never starts a source scheduler or live collection.")

        def report(self,identifier,title,*,situation="A",official=False,publisher="Fictional QA authority",kind="report",origin="qa-origin-A"):
            identifier=self.scenario+"-"+identifier
            return {"id":identifier,"source_id":"qa-"+origin,"publisher":publisher,"title":"[QA TEST] "+title,
                    "summary":"Fictional controlled Windows notification test. No real incident is reported.",
                    "url":"https://example.com/qa/"+identifier,"published_at":self.stamp,"retrieved_at":self.stamp,
                    "language":"en","region":"QA test region "+situation,"country":"Fictional QA territory",
                    "category":"Infrastructure","kind":kind,"origin_id":origin,"independence":"original",
                    "event_key":"synthetic-native-qa-"+run_id+"-"+self.scenario+"-"+situation,"severity":"high",
                    "latitude":15.0 if situation=="A" else -20.0,"longitude":-35.0 if situation=="A" else 100.0,
                    "geo_precision":"regional","claims":{},"official":official,"official_scope":"statement","synthetic":True}

        def send_case(self,case):
            if not self.monitoring:
                record("paused_action_rejected",case=case);self.status_changed.emit("Paused: test report was not ingested or alerted.");return
            if case=="official":batch=[self.report("official-A","Fictional authority announces a harbor closure",official=True)]
            elif case=="developing":batch=[
                self.report("regional-B1","Regional team reports a fictional service interruption",situation="B",publisher="Fictional regional newsroom one",origin="regional-one"),
                self.report("regional-B2","Independent local reporting describes the fictional disruption",situation="B",publisher="Fictional regional newsroom two",origin="regional-two")]
            elif case=="correction":
                batch=[self.report("correction-A","Correction to the fictional harbor announcement",official=True,kind="correction")];batch[0]["correction_of"]=self.scenario+"-official-A"
            elif case=="retraction":
                batch=[self.report("retraction-A","Retraction of the fictional harbor announcement",official=True,kind="retraction")];batch[0]["retraction_of"]=self.scenario+"-official-A"
            elif case=="duplicate":batch=copy.deepcopy(self.last_batch)
            else:return
            if case!="duplicate":self.last_batch=copy.deepcopy(batch)
            previous={e["id"]:e for e in self.store.list_events()}
            changed=self.store.ingest(batch)
            submissions=0
            for event in changed:
                self.ids["B" if event.get("region","").endswith(" B") else "A"]=event["id"]
                reason=alert_reason(event,previous.get(event["id"]))
                if not reason:continue
                alert=self.store.add_alert(event,reason)
                if not alert:continue
                event["_alert_id"]=alert["id"]
                self.alert_received.emit(alert)
                notifier.notify(event,"[QA TEST] "+reason)
                submissions+=1
            record("synthetic_action",case=case,changed_events=len(changed),eligible_alerts=submissions,event_ids=[e["id"] for e in changed])
            self.data_changed.emit()

    controller=QAController()
    notifier=NativeNotifications(enabled=True,predicate=lambda: controller.monitoring and controller.get_setting("notifications_enabled",True) and not in_quiet_hours({k:controller.get_setting(k,d) for k,d in [("quiet_enabled",False),("quiet_start","00:00"),("quiet_end","00:00")]}))
    window=MainWindow(controller);window.setWindowTitle("[QA TEST] Global Pulse — source integration only")
    window.setWindowIcon(pulse_icon())
    notifier.status_changed.connect(lambda status: (setattr(controller,"notification_status",status),record("helper_status",status=status),controller.data_changed.emit()))
    def receipt(identifier,status):
        controller.store.update_alert_delivery(identifier,status)
        record("helper_receipt",alert_id=identifier,status=status,visible_toast_proven=False)
        controller.data_changed.emit()
    notifier.delivery_changed.connect(receipt)
    def activate(identifier=""):
        window.showNormal() if window.isMinimized() else window.show()
        if identifier:window.navigate_event(identifier)
        window.raise_();window.activateWindow();record("activation_routed",event_id=identifier,selected_event_id=window._selected_id)
    notifier.activated.connect(activate);instance.activated.connect(activate)
    dock=QDockWidget("Synthetic native QA controls — no live collection",window);dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
    controls=QWidget();layout=QVBoxLayout(controls)
    note=QLabel("Source harness only. OS submission is not evidence of a visible toast. Cold activation and installer identity require separate exact-artifact tests.");note.setWordWrap(True);layout.addWidget(note)
    actions=QHBoxLayout()
    delay=QSpinBox();delay.setRange(0,30);delay.setValue(3);delay.setSuffix(" sec delay")
    def schedule(case):
        seconds=delay.value();record("scheduled_synthetic_action",case=case,delay_seconds=seconds)
        QTimer.singleShot(seconds*1000,lambda:controller.send_case(case))
    for title,case in (("Official A","official"),("Developing B","developing"),("Repeat last batch","duplicate"),("Correction A","correction"),("Retraction A","retraction")):
        b=QPushButton(title);b.clicked.connect(lambda checked=False,c=case:schedule(c));actions.addWidget(b)
    actions.addWidget(delay)
    reset=QPushButton("New scenario");reset.clicked.connect(controller.new_scenario);actions.addWidget(reset)
    layout.addLayout(actions)
    actions=QHBoxLayout()
    for title,action in (("Select A",lambda:activate(controller.ids.get("A",""))),("Select B",lambda:activate(controller.ids.get("B",""))),("Minimize",window.showMinimized),("Hide to tray",window.hide),("Pause",controller.pause),("Resume",controller.resume)):
        b=QPushButton(title);b.clicked.connect(action);actions.addWidget(b)
    mute=QCheckBox("Mute native alerts");mute.toggled.connect(lambda value:controller.set_setting("notifications_enabled",not value));actions.addWidget(mute)
    quiet=QCheckBox("Quiet hours now");quiet.toggled.connect(lambda value:(controller.set_setting("quiet_start","00:00"),controller.set_setting("quiet_end","00:00"),controller.set_setting("quiet_enabled",value)));actions.addWidget(quiet)
    layout.addLayout(actions)
    observations=QHBoxLayout();case_select=QComboBox();case_select.addItems([f"GP-N{i:02d}" for i in range(1,21)]);observations.addWidget(case_select)
    def observe():
        text,ok=QInputDialog.getMultiLineText(window,"Record manual observation","Describe what you actually observed; include PASS, FAIL, BLOCKED, or INCONCLUSIVE and evidence filename:")
        if ok and text.strip():record("operator_observation",case_id=case_select.currentText(),text=text.strip()[:4000],independent_attestation=False)
    b=QPushButton("Record observed result…");b.clicked.connect(observe);observations.addWidget(b)
    observations.addWidget(QLabel("Evidence: "+str(receipt_path)),1)
    exit_button=QPushButton("Exit Completely");observations.addWidget(exit_button);layout.addLayout(observations)
    dock.setWidget(controls);window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,dock)
    tray=QSystemTrayIcon(pulse_icon(),app);menu=QMenu();menu.addAction("Open QA window",lambda:activate());menu.addAction("Pause synthetic actions",controller.pause);tray.setContextMenu(menu)
    tray.activated.connect(lambda reason:activate() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
    if QSystemTrayIcon.isSystemTrayAvailable():tray.show()
    closed=False
    def shutdown():
        nonlocal closed
        if closed:return
        closed=True;window.save_layout();window._force_close=True;tray.hide();notifier.stop();controller.close();instance.close()
        record("harness_exit",cold_activation_test="NOT COVERED",exact_packaged_artifact=False);app.quit()
    menu.addAction("Exit Completely",shutdown);exit_button.clicked.connect(shutdown);controller.quit_requested.connect(shutdown)
    window.set_close_handler(lambda:window.hide() if tray.isVisible() else shutdown())
    window.show();notifier.start()
    record("harness_start",process_id=os.getpid(),helper_relative_path="build/notifications/GlobalPulse.Notifications.exe",helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),source_harness=True,live_collection=False)
    if args.activate:QTimer.singleShot(100,lambda:activate(args.activate))
    try:return app.exec()
    finally:
        if not closed:shutdown()


if __name__=="__main__":raise SystemExit(main())
