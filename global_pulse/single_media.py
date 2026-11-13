"""Owner replacement: one TV, one radio, and a separate reviewed-camera view.

No radio receiver directories or external-only sites enter the playback lineup.
Builtin TV admission is intentionally separate from user-added specific videos.
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTabWidget,QLineEdit,QSlider,QMessageBox,QCheckBox
from .media_widget import _MediaTile, youtube_id, media_identity
from .internet_radio import RadioPanel


class Television(_MediaTile):
    def __init__(self,parent=None):
        self._poll_timer=None
        self._generation=0
        self._requested=False
        self._last_time=None
        self._ever_played=False
        self._progress_at=0.0
        super().__init__(parent)
        self.setAccessibleName("Single large television player")
        self.display.setMinimumHeight(180)
        self.selector.setAccessibleName("Television channel or saved video")
        for control in self.findChildren(QPushButton):
            if control.text()=="Source ↗":control.hide()
        self._poll_timer=QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_pending=False
        self.tv_status=QLabel("OFF")
        self.tv_status.setTextFormat(Qt.TextFormat.PlainText)
        self.layout_.addWidget(self.tv_status)
        row=QHBoxLayout()
        self.volume=QSlider(Qt.Orientation.Horizontal);self.volume.setRange(0,100);self.volume.setValue(60)
        self.volume.setAccessibleName("Television volume")
        self.mute=QPushButton("Mute");self.mute.setCheckable(True);self.mute.setChecked(True)
        self.mute.setAccessibleName("Mute television audio")
        self.volume.valueChanged.connect(self._volume)
        self.mute.toggled.connect(self._mute)
        row.addWidget(self.mute);row.addWidget(self.volume,1);self.layout_.addLayout(row)
        add=QHBoxLayout()
        self.video_url=QLineEdit();self.video_url.setPlaceholderText("Your YouTube video URL (not a channel page)")
        self.video_url.setAccessibleName("Add a specific YouTube video")
        save=QPushButton("Add video");save.clicked.connect(self.add_video)
        add.addWidget(self.video_url,1);add.addWidget(save);self.layout_.addLayout(add)
        self._saved=[]
        self._builtins=[]
        self._test_candidates=[]
        self._setter=None
        self._populate_channels()

    def configure_preferences(self,getter,setter):
        self._setter=setter
        raw=getter("single_tv_videos_v1",[])
        self._saved=[]
        if isinstance(raw,list):
            for item in raw[:50]:
                video=youtube_id(item) if isinstance(item,str) else None
                if video and video not in self._saved:self._saved.append(video)
        self._populate_channels()

    def set_catalog(self,catalog):
        # A provider URL/metadata response is never sufficient for *verified*
        # built-in admission. Keep those exact bytes in the verified resource.
        path=Path(__file__).with_name("resources")/"tv_playback_verified.json"
        try:items=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError):items=[]
        self._builtins=[]
        if isinstance(items,list):
            for item in items[:50]:
                if not isinstance(item,dict):continue
                proof=item.get("playback_evidence")
                if not isinstance(proof,dict) or proof.get("packaged_windows_playback") is not True:continue
                if not all(isinstance(proof.get(key),str) and proof[key] for key in ("source_commit","package_sha256","report")):continue
                if youtube_id(item.get("url")):self._builtins.append(dict(item))

        # Owner-test candidates are intentionally separate from verified
        # built-ins. Only exact official YouTube video/live-video identities
        # are exposed; channel pages and arbitrary provider websites are not.
        entries=catalog if isinstance(catalog,list) else []
        verified_ids={youtube_id(item.get("url","")) for item in self._builtins}
        # Only entries byte-for-byte represented by the bundled reviewed media
        # catalog may become owner-test candidates. Arbitrary caller-provided
        # YouTube URLs remain user-added only and never enter this lane.
        try:
            reviewed=json.loads((Path(__file__).with_name("resources")/"media_catalog.json").read_text(encoding="utf-8")).get("entries",[])
        except (OSError,ValueError,TypeError):
            reviewed=[]
        reviewed_exact={
            (str(item.get("id","")),str(item.get("url","")))
            for item in reviewed if isinstance(item,dict)
            and str(item.get("type","")).casefold()=="video"
            and youtube_id(item.get("url",""))
        }
        self._test_candidates=[]
        for item in entries[:100]:
            if not isinstance(item,dict) or str(item.get("type","")).casefold()!="video":
                continue
            if (str(item.get("id","")),str(item.get("url",""))) not in reviewed_exact:
                continue
            video=youtube_id(item.get("url",""))
            if not video or video in verified_ids:
                continue
            candidate=dict(item)
            candidate["title"]="TEST · "+str(item.get("title","Official video"))
            candidate["owner_test_candidate"]=True
            candidate["availability"]=(
                "Owner-test candidate · not yet packaged-verified. "
                + str(item.get("availability","Official provider controls availability and embedding."))
            )
            self._test_candidates.append(candidate)
            if len(self._test_candidates)>=12:
                break
        self._populate_channels()

    def set_event(self,event):
        # Selecting news must not interrupt or silently replace a TV station.
        pass

    def add_video(self):
        video=youtube_id(self.video_url.text().strip())
        if not video:
            self.note.setText("Enter a specific YouTube video/live-video URL. Channel pages and other websites are not TV streams.")
            return False
        if video in self._saved:return True
        if len(self._saved)>=50:
            self.note.setText("Your saved-video list is full (50).")
            return False
        updated=self._saved+[video]
        try:
            if callable(self._setter):self._setter("single_tv_videos_v1",["https://www.youtube.com/watch?v="+v for v in updated])
        except (OSError,ValueError,RuntimeError):
            self.note.setText("Video was not saved; previous selections are unchanged.");return False
        self._saved=updated;self._populate_channels();self.video_url.clear();return True

    def _populate_channels(self):
        self.media=[]
        self.catalog=list(getattr(self,"_builtins",[]))+list(getattr(self,"_test_candidates",[]))+[
            {"url":"https://www.youtube.com/watch?v="+v,"title":"Your video · "+v,"type":"video","availability":"User-added specific video; availability and embedding permission are controlled by YouTube/publisher"}
            for v in getattr(self,"_saved",[])]
        self._populate()
        if not self.catalog:
            self.display.setText("TELEVISION\n\nNo packaged-verified TV channels yet\nYour specific video links can be added below")
            self.note.setText("Unverified built-ins and external-only websites are not offered as working TV channels.")
        elif self._test_candidates and not self._builtins:
            self.display.setText("TELEVISION\n\nOwner-test TV candidates available\nSelect TEST · channel, then Watch")
            self.note.setText("TEST entries are official exact-video candidates, not packaged-verified built-ins yet.")

    def watch(self):
        import os
        item=self._current()
        video=youtube_id(item.get("url",""))
        if not video:
            self.note.setText("Select a verified channel or add a specific supported video.");return
        consent=QMessageBox.question(self,"Connect to YouTube?",
            "Open the official embedded player? YouTube and its media servers receive your IP address and player requests. Playback initially stays muted; press Play in the player.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if consent!=QMessageBox.StandardButton.Yes:return
        try:
            if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX", "").lower() not in {"", "0", "false"} or "--no-sandbox" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
                raise RuntimeError("The embedded player requires Chromium sandboxing")
            if hasattr(os,"geteuid") and os.geteuid()==0:
                raise RuntimeError("The embedded player requires a standard user session")
            self.stop()
            self._ensure_player()
            from PySide6.QtWebEngineCore import QWebEngineHttpRequest
            request=QWebEngineHttpRequest(QUrl(f"https://www.youtube-nocookie.com/embed/{video}?autoplay=0&mute=1&playsinline=1"))
            request.setHeader(b"Referer",b"https://www.dietrichailabs.com/")
            self.mute.setChecked(True)
            self.view.load(request);self.view.show();self.display.hide()
            if item.get("owner_test_candidate"):
                self.note.setText("OWNER TEST CANDIDATE · official embedded player · if playback reaches PLAYING, report the channel so it can be promoted to verified.")
            else:
                self.note.setText("Official embedded player · press Play · initially muted")
            self._begin_observation()
        except (ImportError,RuntimeError,ValueError):
            self.stop();self.tv_status.setText("ERROR")
            self.note.setText("The sandboxed embedded player could not start. No external website was opened.")

    def _begin_observation(self):
        self._generation+=1;self._requested=True;self._poll_pending=False;self._last_time=None;self._ever_played=False
        self._progress_at=time.monotonic();self.tv_status.setText("CONNECTING")
        self._poll_timer.start()
        self.view.page().setAudioMuted(self.mute.isChecked())

    def _poll(self):
        if not self._requested or not self.view:return
        if time.monotonic()-self._progress_at>45:
            self.stop();self.tv_status.setText("ERROR")
            self.note.setText("No in-app playback progress. This video may be unavailable, blocked for embedding, or waiting for Play. Connection stopped.")
            return
        # A lost JavaScript reply must not disable the independent deadline.
        if self._poll_pending:return
        self._poll_pending=True;generation=self._generation
        script="""(()=>{const v=document.querySelector('video');return v?{time:v.currentTime,paused:v.paused,ready:v.readyState,ended:v.ended,error:!!v.error}:{missing:true};})()"""
        self.view.page().runJavaScript(script,lambda value,g=generation:self._observed(g,value))

    def _observed(self,generation,value):
        if generation!=self._generation or not self._requested:return
        self._poll_pending=False
        if not isinstance(value,dict) or value.get("missing"):
            self.tv_status.setText("PLAYER LOADING");return
        if value.get("error"):
            self.stop();self.tv_status.setText("ERROR");self.note.setText("The embedded video reported a playback error; connection stopped.");return
        current=value.get("time")
        if isinstance(current,bool) or not isinstance(current,(int,float)) or not math.isfinite(current):return
        if value.get("ended"):
            self.stop();self.tv_status.setText("ENDED");return
        if value.get("paused"):
            self.tv_status.setText("PAUSED · use Play in the official player")
            # A page that has never played must not keep its connection alive
            # forever by reporting paused=True once per second. A deliberate
            # pause AFTER real playback is allowed until Stop/tab change.
            if self._ever_played:self._progress_at=time.monotonic()
        elif value.get("ready",0)<2:
            self.tv_status.setText("BUFFERING")
        elif self._last_time is not None and current>self._last_time:
            self.tv_status.setText("PLAYING");self._progress_at=time.monotonic();self._ever_played=True
        self._last_time=current

    def _volume(self,value):
        if self.view and self._requested:
            self.view.page().runJavaScript("(()=>{const v=document.querySelector('video');if(v)v.volume="+str(max(0,min(100,value))/100.0)+";})()")

    def _mute(self,value):
        if self.view:self.view.page().setAudioMuted(value)

    def stop(self):
        self._generation=getattr(self,"_generation",0)+1
        self._requested=False;self._poll_pending=False
        if self._poll_timer:self._poll_timer.stop()
        super().stop()
        if hasattr(self,"tv_status"):self.tv_status.setText("OFF")


class MediaPanel(QWidget):
    auto_cameras_changed=Signal(bool)
    def __init__(self,parent=None):
        super().__init__(parent)
        self._shutting_down=False
        self.auto_cameras=False
        self._event=None
        self._camera_matches=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.tabs=QTabWidget()
        self.tv=Television(self)
        self.radio=RadioPanel(self)
        from .camera_context import camera_catalog
        self._camera_catalog=[dict(item) for item in camera_catalog()]
        camera_page=QWidget();camera_layout=QVBoxLayout(camera_page)
        self.auto_camera_check=QCheckBox("Auto cameras")
        self.auto_camera_check.toggled.connect(self._toggle_cameras)
        self.camera_status=QLabel("Select an event for reviewed area cameras")
        self.camera_status.setWordWrap(True);self.camera_status.setTextFormat(Qt.TextFormat.PlainText)
        self.camera=_MediaTile(self)
        self.camera.set_catalog(self._camera_catalog)
        camera_layout.addWidget(self.auto_camera_check);camera_layout.addWidget(self.camera_status);camera_layout.addWidget(self.camera,1)
        self.tabs.addTab(self.tv,"TV");self.tabs.addTab(self.radio,"Radio");self.tabs.addTab(camera_page,"Cameras")
        self._last_tab=0
        self.tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self.tabs,1)
        self.stop_button=QPushButton("Stop all media");self.stop_button.clicked.connect(self.stop)
        layout.addWidget(self.stop_button)
        # There is one television tile, never four TV/radio windows.
        self.tiles=[self.tv]

    def set_catalog(self,catalog):
        self.tv.set_catalog(catalog)

    def configure_radio_preferences(self,getter,setter):
        self.radio.configure_preferences(getter,setter)
        self.tv.configure_preferences(getter,setter)

    def _tab_changed(self,index):
        if self._last_tab==0:self.tv.stop()
        elif self._last_tab==1:self.radio.off()
        elif self._last_tab==2:self.camera.stop()
        self._last_tab=index
        if index==2:self._apply_camera()

    def set_event(self,event):
        from .camera_context import associated_cameras
        if (event or {}).get("id")!=(self._event or {}).get("id"):
            self.camera.auto_camera_suspended=False
        self._event=event
        self._camera_matches=associated_cameras(event)
        total=len(self._camera_catalog)
        if self._camera_matches:
            self.camera_status.setText(
                f"{total} reviewed camera(s) available · {len(self._camera_matches)} match selected event · area context only"
            )
        else:
            self.camera_status.setText(
                f"{total} reviewed camera(s) available manually · none match selected event"
            )
        # Event-associated cameras sort first, but the reviewed manual camera
        # bank remains visible even when no event matches.
        self.camera.media=self._camera_matches
        self.camera.catalog=self._camera_catalog
        self.camera._populate()
        self._apply_camera()
        # Neither TV nor radio selection/playback is changed by a news refresh.

    def _apply_camera(self):
        event=self._event or {}
        if (self._shutting_down or not self.auto_cameras or self.tabs.currentIndex()!=2
                or event.get("synthetic") or event.get("historical_view")
                or event.get("severity") not in {"critical","high","moderate"}):return
        if self.camera._current().get("id") in {item["id"] for item in self._camera_matches}:
            self.camera.connect_camera(auto_consented=True)

    def restore_auto_cameras(self,enabled):
        self.auto_cameras=enabled is True
        self.auto_camera_check.blockSignals(True);self.auto_camera_check.setChecked(self.auto_cameras);self.auto_camera_check.blockSignals(False)

    def _toggle_cameras(self,enabled):
        if enabled:
            enabled=QMessageBox.question(self,"Automatically connect reviewed area cameras?",
                "While the Cameras tab is selected, connect matching reviewed public cameras for active events? Providers receive your IP address. Images remain in memory, not recordings. Coverage is limited.",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
        self.restore_auto_cameras(enabled);self.auto_cameras_changed.emit(enabled)
        if enabled:self.camera.auto_camera_suspended=False;self._apply_camera()
        else:self.camera.stop()

    def radio_off(self):self.radio.off();return True

    def stop(self):
        if self.auto_cameras:self.restore_auto_cameras(False);self.auto_cameras_changed.emit(False)
        self.tv.stop();self.radio.off();self.camera.user_stop()
        from .camera_snapshot import CameraSnapshot
        CameraSnapshot._images.clear()

    def shutdown(self):
        self._shutting_down=True
        self.tv.stop();self.radio.shutdown();self.camera.stop()
        from .camera_snapshot import CameraSnapshot
        CameraSnapshot._images.clear()
