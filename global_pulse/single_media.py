"""Owner replacement: one TV, one radio, and a separate reviewed-camera view.

No radio receiver directories or external-only sites enter the playback lineup.
Builtin TV admission is intentionally separate from user-added specific videos.
"""
from __future__ import annotations
import json
import math
import sys
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTabWidget,QLineEdit,QSlider,QMessageBox,QCheckBox
from .media_widget import _MediaTile, youtube_id, media_identity
from .internet_radio import RadioPanel


class Television(_MediaTile):
    def __init__(self,parent=None):
        self.native_tv=None
        self._native_tv_active=False
        self._poll_timer=None
        self._generation=0
        self._requested=False
        self._last_time=None
        self._progress_at=0.0
        self._player_loaded=False
        self._had_playback=False
        self._player_signal_connected=False
        self._last_decode_info=""
        self._last_native_status_at=0.0
        self._native_identity_note=""
        self._native_package_note=""
        self._native_mode="embed"
        self._native_state="off"
        self._native_identity_state="unknown"
        self._native_referer_state="unknown"
        self._native_http_status=0
        super().__init__(parent)
        self.setAccessibleName("Single large television player")
        self.display.setMinimumHeight(180)
        self.selector.setAccessibleName("Television channel or saved video")
        for control in self.findChildren(QPushButton):
            if control.text()=="Source ↗":
                control.setText("Open on YouTube")
                control.setToolTip("Open the selected official video in your browser if embedding fails")
        self._poll_timer=QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_pending=False
        self.tv_status=QLabel("OFF")
        self.tv_status.setTextFormat(Qt.TextFormat.PlainText)
        # Keep status above the large video surface, visible without scrolling.
        self.layout_.insertWidget(2,self.tv_status)
        # The one-line channel note cannot display 320-character decode receipts.
        self.tv_diagnostics=QLabel("Decoder diagnostics appear after Watch")
        self.tv_diagnostics.setObjectName("TVPlaybackDiagnostics")
        self.tv_diagnostics.setAccessibleName("TV codec and renderer diagnostics")
        self.tv_diagnostics.setWordWrap(True)
        self.tv_diagnostics.setTextFormat(Qt.TextFormat.PlainText)
        self.tv_diagnostics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tv_diagnostics.setMinimumHeight(48)
        self.tv_diagnostics.setMaximumHeight(104)
        self.layout_.insertWidget(3,self.tv_diagnostics)
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
        test_clip=QPushButton("Test TV player")
        test_clip.setAccessibleName("Try one official Blender Creative Commons test video inside Pulse")
        test_clip.clicked.connect(self.test_tv_player)
        owner_clip=QPushButton("Test your video")
        owner_clip.setAccessibleName("Test owner-provided YouTube video b0ZhJhN_Sn8 in Pulse")
        owner_clip.clicked.connect(self.test_owner_video)
        add.addWidget(self.video_url,1);add.addWidget(save)
        add.addWidget(test_clip);add.addWidget(owner_clip)
        self.layout_.addLayout(add)
        self.full_watch_button=QPushButton("Try YouTube watch page in Pulse")
        self.full_watch_button.setAccessibleName(
            "Try the selected video in YouTube's normal watch page, with consent"
        )
        self.full_watch_button.clicked.connect(self.watch_full_page)
        self.layout_.addWidget(self.full_watch_button)
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

    def test_tv_player(self):
        """Opt-in reproducible YouTube embed test, not a purported live channel.

        Blender Foundation's Creative Commons Big Buck Bunny video is an
        independently identifiable fixed video, not a rotating news livestream.
        Selecting it is a user gesture; Watch still requests explicit consent.
        """
        test_url="https://www.youtube.com/watch?v=YE7VzlLtp-4"
        self.video_url.setText(test_url)
        if not self.add_video():
            self.tv_status.setText("ERROR · cannot select test video")
            return False
        for index in range(self.selector.count()):
            item=self.selector.itemData(index) or {}
            if youtube_id(item.get("url",""))=="YE7VzlLtp-4":
                self.selector.setCurrentIndex(index)
                self.tv_status.setText("TEST READY · Blender video, not live news")
                self.note.setText("Fixed official Blender video selected · press Play after consent")
                self.watch()
                return True
        self.tv_status.setText("ERROR · test video not found")
        return False

    def test_owner_video(self):
        """Opt-in owner-supplied exact YouTube video ID; availability unverified.

        Not a reviewed 24/7 news channel or evidence of a playable embed.
        Official player and user-consent path remain unchanged.
        """
        test_url="https://www.youtube.com/watch?v=b0ZhJhN_Sn8"
        self.video_url.setText(test_url)
        if not self.add_video():
            self.tv_status.setText("ERROR · cannot select owner test video")
            return False
        for index in range(self.selector.count()):
            item=self.selector.itemData(index) or {}
            if youtube_id(item.get("url",""))=="b0ZhJhN_Sn8":
                self.selector.setCurrentIndex(index)
                self.tv_status.setText("OWNER TEST READY · video availability unverified")
                self.note.setText("Your supplied YouTube video · in-app playback requires consent and Play")
                self.watch()
                return True
        self.tv_status.setText("ERROR · owner test video missing")
        return False

    def _ensure_player(self):
        super()._ensure_player()
        # The actual browser replaces a hidden 180px-minimum placeholder.
        if self.view is not None:
            self.view.setMinimumHeight(180)

    def _tv_load_finished(self, ok):
        """Top-level browser navigation is not evidence of video playback."""
        if not self._requested:
            return
        self._player_loaded=bool(ok)
        if not ok:
            self.stop()
            self.tv_status.setText("ERROR · YouTube page could not load")
            self.note.setText("In-app YouTube page load failed · try Open on YouTube")
            self.tv_diagnostics.setText("YouTube page failed to load · no video verified")
        else:
            self.tv_status.setText("PAGE LOADED · video NOT verified")
            self.note.setText("YouTube web page loaded; that does not prove the video is available. Click Play inside the video.")

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
            if self._begin_native_player(video):
                return
            self.stop()
            self._ensure_player()
            from PySide6.QtWebEngineCore import QWebEngineHttpRequest
            request=QWebEngineHttpRequest(QUrl(f"https://www.youtube.com/embed/{video}?autoplay=0&mute=1&playsinline=1"))
            # A desktop WebView needs an explicit identifying Referer for
            # YouTube playback (error 153 otherwise). This is the real
            # product publisher domain, not a spoofed third-party origin.
            request.setHeader(b"Referer",b"https://www.dietrichailabs.com/")
            self.mute.setChecked(True)
            if not self._player_signal_connected:
                self.view.loadFinished.connect(self._tv_load_finished)
                self.view.renderProcessTerminated.connect(
                    self._renderer_terminated
                )
                self._player_signal_connected=True
            self._begin_observation()
            page=self.view.page()
            page.allowed_video_id=video
            page.full_watch_mode=False
            self.view.load(request);self.view.show();self.display.hide()
            if item.get("owner_test_candidate"):
                self.note.setText("OWNER TEST CANDIDATE · official embedded player · if playback reaches PLAYING, report the channel so it can be promoted to verified.")
            else:
                self.note.setText("Official embedded player · press Play · initially muted")
        except (ImportError,RuntimeError,ValueError):
            self.stop();self.tv_status.setText("ERROR")
            self.note.setText("The sandboxed embedded player could not start. No external website was opened.")
            self.tv_diagnostics.setText(
                "Embedded player startup refused or unavailable in this Qt session · "
                "no video or audio started"
            )

    def watch_full_page(self):
        """Load the selected official YouTube watch URL, not a stream mirror.

        Explicit consent, one exact video ID and strict mainframe/third-party
        origin policy remain. This offers YouTube's own normal player inside
        the app where iframe embedding is unavailable, without autoplay.
        """
        import os
        video=youtube_id(self._current().get("url",""))
        if not video:
            self.note.setText("Select an exact YouTube video first.")
            return False
        approved=QMessageBox.question(
            self,"Try official YouTube watch page inside Pulse?",
            "Open the selected video on YouTube's normal watch page inside "
            "Pulse? YouTube receives your IP address and player requests. "
            "Only this exact video may navigate; other videos, sign-in pages, "
            "downloads and popups remain blocked. Press Play yourself; "
            "availability depends on YouTube and the publisher. Continue?",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )==QMessageBox.StandardButton.Yes
        if not approved:
            return False
        try:
            if (os.environ.get("QTWEBENGINE_DISABLE_SANDBOX","").lower()
                not in {"","0","false"}
                or "--no-sandbox" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS","")):
                raise RuntimeError("Chromium sandbox is required")
            if hasattr(os,"geteuid") and os.geteuid()==0:
                raise RuntimeError("Standard user session required")
            if self._begin_native_player(video,full_watch=True):
                return True
            self.stop()
            self._ensure_player()
            if not self._player_signal_connected:
                self.view.loadFinished.connect(self._tv_load_finished)
                self.view.renderProcessTerminated.connect(
                    self._renderer_terminated
                )
                self._player_signal_connected=True
            self.view.page().allowed_video_id=video
            self.view.page().full_watch_mode=True
            self.mute.setChecked(True)
            self._begin_observation()
            self.view.load(QUrl("https://www.youtube.com/watch?v="+video))
            self.view.show()
            self.display.hide()
            self.tv_status.setText("OFFICIAL WATCH PAGE · video not verified")
            self.note.setText(
                "Normal YouTube player opened inside Pulse. "
                "Use Play there; only advancing video proves playback."
            )
            return True
        except (ImportError,RuntimeError,ValueError,OSError):
            self.stop()
            self.tv_status.setText("ERROR · official watch page unavailable")
            self.note.setText(
                "YouTube watch page could not start inside Pulse. "
                "Use Open on YouTube in your regular browser."
            )
            self.tv_diagnostics.setText(
                "Official YouTube watch page startup refused or unavailable · "
                "no in-app playback verified"
            )
            return False

    def _begin_native_player(self, video, *, full_watch=False):
        """Prefer the packaged, policy-guarded Edge codec process on Windows.

        The QtWebEngine player remains a non-Windows and source-run fallback.
        Consent and exact-video validation happen BEFORE this method.
        """
        if sys.platform != "win32":
            return False
        from .native_tv import NativeTvHost
        if NativeTvHost.executable() is None:
            return False
        self.stop()
        if self.native_tv is None:
            self.native_tv=NativeTvHost(self)
            self.layout_.insertWidget(3,self.native_tv,1)
            self.native_tv.status_received.connect(self._native_tv_receipt)
        self.mute.setChecked(True)
        self._requested=True
        self._native_tv_active=True
        self._had_playback=False
        self._progress_at=time.monotonic()
        self._last_native_status_at=0.0
        self._native_identity_note=""
        self._native_package_note=""
        self._native_http_note=""
        self._native_mode="watch" if full_watch else "embed"
        self._native_state="connecting"
        self._native_identity_state="unknown"
        self._native_referer_state="unknown"
        self._native_http_status=0
        self.tv_status.setText("CONNECTING · native Windows video decoder")
        self.tv_diagnostics.setText("Edge WebView2 selected · codec and frame verification pending")
        started=self.native_tv.play(video,full_watch=full_watch)
        if not started:
            self._native_tv_active=False
            self._requested=False
            self.tv_status.setText("NATIVE VIDEO UNAVAILABLE")
            self.tv_diagnostics.setText("Packaged WebView2 host could not start")
            return False
        self.display.hide()
        self.note.setText(
            ("Official YouTube watch page" if full_watch else "Official YouTube embedded player")+
            " in isolated Windows video process · press Play in the video · initially muted"
        )
        return True

    def _native_failure_evidence(self):
        """Compact enums/numbers survive Stop; never copy page text into Qt."""
        mode=("official watch page" if getattr(self,"_native_mode","")=="watch"
              else "embedded player")
        identity=getattr(self,"_native_identity_state","unknown")
        if not isinstance(identity,str) or identity not in {"present","absent","unknown"}:
            identity="unknown"
        referer_state=getattr(self,"_native_referer_state","unknown")
        if not isinstance(referer_state,str):referer_state="unknown"
        referer={
            "registered_app":"registered Windows app ID observed",
            "publisher":"publisher URL observed (not an app ID)",
            "present_unknown":"present, identity unknown",
            "missing_unknown":"missing/unknown",
            "browser_present":"browser-managed, present",
            "browser_missing":"browser-managed, missing/unknown",
        }.get(referer_state,"unknown")
        code=getattr(self,"_native_http_status",0)
        if type(code) is not int or not 100<=code<=599:code=0
        return (
            "Mode: "+mode+" · Windows package identity: "+identity+
            " · pre-send Referer: "+referer+
            " · exact video HTTP: "+(str(code) if code else "unknown")+
            " · provider acceptance and picture/audio NOT verified"
        )

    @staticmethod
    def _native_error_readout(event):
        """Only known error codes/enums enter the visible failure receipt.

        A number parsed from YouTube's visible DOM is not an IFrame API event;
        HTMLMediaElement errors are a separate namespace entirely.
        """
        reason=event.get("reason")
        if not isinstance(reason,str):reason=""
        provenance=event.get("observation")
        if reason=="youtube_unavailable":
            code=event.get("youtube_error_code")
            meanings={2:"invalid parameter",5:"HTML5 player failure",
                      100:"video unavailable",101:"embedding disallowed",
                      150:"embedding disallowed",153:"client identification missing"}
            if provenance=="visible_dom":
                if type(code) is int and code in meanings:
                    return (
                        "YOUTUBE ERROR "+str(code)+" · "+meanings[code],
                        "Visible YouTube error code "+str(code)+
                        " · DOM observation, not an IFrame API event."
                    )
                return ("UNAVAILABLE · visible YouTube player error",
                        "Visible YouTube error; numeric code unrecognized. "
                        "DOM observation, not an IFrame API event.")
            return ("UNAVAILABLE · YouTube player",
                    "Helper reported provider unavailability; error provenance unreported.")
        if reason=="html_media_error":
            code=event.get("media_error_code")
            meanings={1:"aborted",2:"network",3:"decoder",4:"unsupported media"}
            if provenance=="html_media_element" and type(code) is int and code in meanings:
                return ("VIDEO ERROR · "+meanings[code],
                        "HTMLMediaElement error "+str(code)+
                        " · not a YouTube/IFrame API error code.")
            return ("VIDEO ERROR · media element",
                    "Media error code/provenance unknown; no provider denial inferred.")
        messages={
            "video_document_timeout_45s":("VIDEO DOCUMENT TIMEOUT",
                "The selected video document did not load within 45 seconds."),
            "video_element_missing_45s":("VIDEO ELEMENT MISSING",
                "No video element was observed for 45 seconds."),
            "telemetry_timeout_45s":("PLAYER OBSERVATION TIMEOUT",
                "No valid player observation arrived for 45 seconds."),
            "no_media_progress_45s":("VIDEO STALLED · no media progress",
                "Unpaused player supplied no advancing frame evidence for 45 seconds."),
            "renderer_exited":("RENDERER EXITED · video unavailable",
                "The isolated Windows video renderer exited."),
            "oversized_tv_status":("VIDEO ERROR · invalid player receipt",
                "The isolated player exceeded the bounded receipt limit."),
            "native_window_attach_failed":("VIDEO ERROR · window attachment failed",
                "The exact owned player window could not be attached."),
            "private_window_not_ready":("VIDEO ERROR · private player not ready",
                "The isolated player did not provide a valid private window."),
            "native_process_start_failed":("VIDEO ERROR · player startup failed",
                "The isolated Windows video process did not start."),
        }
        if isinstance(reason,str) and reason.startswith("startup_"):
            return ("VIDEO ERROR · player startup failed",
                    "The isolated player failed during startup.")
        return messages.get(reason,("VIDEO ERROR · unclassified player failure",
                                    "Native player failure category unrecognized."))

    def _native_tv_receipt(self, event):
        if not self._native_tv_active or not self._requested:
            return
        kind=event.get("type")
        if kind=="ready":
            self._native_state="ready"
            self.tv_status.setText("WINDOWS PLAYER READY · press Play")
            self.tv_diagnostics.setText(
                "Native Edge WebView2 active · InPrivate profile · "
                "awaiting video time and decoded-frame evidence"
            )
            self.native_tv.command("MUTE 1")
            self.native_tv.command("VOLUME "+str(self.volume.value()))
        elif kind=="installed_package_identity":
            # OS-owned Win32 package query, not a publisher-site assumption.
            # The helper never emits the actual registered name or publisher.
            state=event.get("state")
            self._native_identity_state=(state if isinstance(state,str) and
                state in {"absent","present","unknown"} else "unknown")
            registered=event.get("referer_matches_registered_app_id") is True
            self._native_package_note=(
                "Windows package identity: "+self._native_identity_state+
                "; normal watch page uses browser-managed headers, not embed identity"
                if getattr(self,"_native_mode","embed")=="watch" else
                "Windows package identity: absent for this process; "
                "publisher URL is not a registered package ID"
                if state=="absent" else
                "Windows registered package ID selected for Referer; "
                "YouTube acceptance NOT verified"
                if state=="present" and registered else
                "Windows package identity detected locally; Referer match "
                "and YouTube acceptance NOT verified"
                if state=="present" else
                "Windows package identity unavailable/unknown"
            )
            self.tv_diagnostics.setText(self._native_package_note+
                                        " · no video playback confirmed")
        elif kind=="web_request_identity":
            # This is an observed PRE-NETWORK WebView2 header, not proof
            # YouTube received it or that Windows registered the app ID.
            present=event.get("referer_present") is True
            match=event.get("publisher_url_match") is True
            app_id_match=event.get("registered_app_id_match") is True
            watch=getattr(self,"_native_mode","embed")=="watch"
            self._native_referer_state=(
                ("browser_present" if present else "browser_missing") if watch else
                "registered_app" if present and app_id_match else
                "publisher" if present and match else
                "present_unknown" if present else "missing_unknown"
            )
            self._native_identity_note=(
                "Normal watch-page pre-send Referer: browser-managed, "+
                ("present" if present else "missing/unknown")+
                " · not an embedded app-ID assertion · playback NOT verified"
                if watch else
                "WebView2 pre-send Referer: "+
                ("registered Windows app ID observed" if present and app_id_match else
                 "publisher URL observed (not an app ID)" if present and match else
                 "present, identity unknown" if present else "missing/unknown")+
                " · YouTube receipt and playback NOT verified"
            )
            self.tv_diagnostics.setText(self._native_identity_note+
                                        (" · "+getattr(self,"_native_package_note","")
                                         if getattr(self,"_native_package_note","") else "")+
                                        " · no video playback confirmed")
        elif kind=="exact_video_http_response":
            # Even HTTP 200 does not show Google accepted our app identity.
            try: code=int(event.get("http_status",0))
            except (ValueError,TypeError,OverflowError): code=0
            if not 100<=code<=599: code=0
            self._native_http_status=code
            self._native_http_note=(
                "Exact video URL HTTP "+str(code) if code
                else "Exact video URL HTTP status unknown"
            )+" (WebView2 observed; identity/playback NOT verified)"
            self.tv_diagnostics.setText(
                self._native_http_note+
                (" · "+self._native_identity_note if self._native_identity_note else "")+
                " · picture/audio not confirmed"+
                (" · "+getattr(self,"_native_package_note","")
                 if getattr(self,"_native_package_note","") else ""))
            if code>=400:
                self.tv_status.setText("VIDEO DOCUMENT HTTP ERROR · "+str(code))
        elif kind=="navigation_redirect":
            if event.get("allowed") is not True:
                self.tv_status.setText("BLOCKED · unapproved video redirect")
                self.tv_diagnostics.setText(
                    "WebView2 blocked a navigation outside the exact consented video. "+
                    self._native_identity_note)
        elif kind=="page_loaded":
            success=event.get("success") is True
            self._native_state="page_loaded" if success else "page_error"
            self.tv_status.setText(
                "PAGE LOADED · video not yet verified" if success
                else "PAGE ERROR · video not loaded"
            )
        elif kind=="waiting":
            state=event.get("state")
            states={
                "awaiting_play":"AWAITING PLAY · press Play in the video",
                "paused":"PAUSED · press Play to resume",
                "missing_player":"WAITING · video element not yet observed",
                "buffering":"BUFFERING · no advancing frame evidence yet",
                "stalled":"STALLED · video progress not advancing",
            }
            if not isinstance(state,str) or state not in states:state="waiting"
            changed=getattr(self,"_native_state","")!=state
            self._native_state=state
            if changed:
                self.tv_status.setText(states.get(state,"WAITING · video not yet verified"))
            now=time.monotonic()
            if not changed and now-self._last_native_status_at<5.0:
                return
            self._last_native_status_at=now
            codec=event.get("h264")
            if codec not in ("probably","maybe"):codec="unknown"
            frames=event.get("frames",0)
            if type(frames) is not int or not 0<=frames<=2147483647:frames=0
            self.tv_diagnostics.setText(
                "Windows decoder H.264: "+codec+
                " · decoded frames "+str(frames)+
                " · picture/audio not confirmed"+
                (" · "+self._native_identity_note if self._native_identity_note else "")+
                (" · "+getattr(self,"_native_http_note","")
                 if getattr(self,"_native_http_note","") else "")+
                (" · "+getattr(self,"_native_package_note","")
                 if getattr(self,"_native_package_note","") else "")
            )
        elif kind=="advancing":
            frames=event.get("decoded_frames",0)
            current=event.get("current_time")
            if (type(frames) is not int or not 0<frames<=2147483647 or
                type(current) not in (int,float) or not 0<=current<=1e12 or
                not math.isfinite(current)):
                return  # Malformed counters are not advancing-frame evidence.
            self._had_playback=True
            now=time.monotonic()
            self._progress_at=now
            # The native helper reports at 1 Hz. Reflowing wrapped labels on
            # every receipt forced Qt's scroll-area/native-child geometry to
            # change while frames were being composited. Telemetry remains
            # live; only the visible diagnostic label is rate-limited.
            changed=getattr(self,"_native_state","")!="advancing"
            self._native_state="advancing"
            if changed:
                self.tv_status.setText("VIDEO TIME ADVANCING · decoded frames reported")
            if not changed and now-self._last_native_status_at<5.0:
                return
            self._last_native_status_at=now
            codec=event.get("h264")
            if codec not in ("probably","maybe"):codec="unknown"
            self.tv_diagnostics.setText(
                "Native Edge H.264 "+codec+
                " · time "+str(current)+
                "s · decoded frames "+str(frames)+
                " · picture and audio require owner verification"+
                (" · "+self._native_identity_note if self._native_identity_note else "")+
                (" · "+getattr(self,"_native_http_note","")
                 if getattr(self,"_native_http_note","") else "")+
                (" · "+getattr(self,"_native_package_note","")
                 if getattr(self,"_native_package_note","") else "")
            )
        elif kind=="error":
            evidence=Television._native_failure_evidence(self)
            title,detail=Television._native_error_readout(event)
            self.stop()
            self.tv_status.setText(title)
            self.tv_diagnostics.setText(
                detail+" · "+evidence+". No successful video playback is claimed."
            )
        elif kind=="ended":
            evidence=Television._native_failure_evidence(self)
            self.stop()
            self.tv_status.setText("ENDED · video element reported completion")
            self.tv_diagnostics.setText("HTMLMediaElement ended · "+evidence)
        elif kind=="stopped":
            self.stop()
            self.tv_status.setText("WINDOWS PLAYER EXITED")

    def _begin_observation(self):
        self._generation+=1;self._requested=True;self._poll_pending=False;self._last_time=None
        self._progress_at=time.monotonic()
        self._player_loaded=False
        self._had_playback=False
        self._last_decode_info=""
        self.tv_status.setText("CONNECTING · YouTube player")
        self.tv_diagnostics.setText("Connecting · no video picture or audio verified")
        self._poll_timer.start()
        self.view.page().setAudioMuted(self.mute.isChecked())

    def _renderer_terminated(self, status, exit_code):
        """Distinguish WebEngine renderer failure from an ordinary black video."""
        if not self._requested:
            return
        # Qt enum and numeric code are runtime diagnostics, not source URLs.
        self.stop()
        self.tv_status.setText("RENDERER EXITED · video unavailable")
        self.note.setText(
            "The embedded Chromium render process ended. This is a player "
            "failure, not a valid playing news stream. Try the normal "
            "YouTube browser link or inspect Windows graphics/Qt codecs."
        )
        self.tv_diagnostics.setText("Chromium renderer terminated · no video verified")

    @staticmethod
    def _media_diagnostics(value):
        """Safe codec/element summary from read-only YouTube page properties."""
        if not isinstance(value,dict):
            return ""
        codecs=value.get("codecs") or {}
        if not isinstance(codecs,dict):
            codecs={}
        def codec(name):
            raw=str(codecs.get(name) or "").lower()
            return raw if raw in {"probably","maybe"} else "not reported"
        parts=[
            "Decoder: H.264 "+codec("h264")+
            ", VP9 "+codec("vp9")+
            ", AV1 "+codec("av1")
        ]
        if value.get("missing"):
            parts.append("YouTube video element missing")
        elif "video_width" in value:
            width=value.get("video_width",0)
            height=value.get("video_height",0)
            parts.append(
                "video dimensions "+str(width)+"×"+str(height)
            )
            parts.append("network state "+str(value.get("network", "?")))
            parts.append("ready state "+str(value.get("ready", "?")))
            if value.get("frames") is not None:
                parts.append("decoded frames "+str(value["frames"]))
            if value.get("controls_visible") is False:
                parts.append("YouTube controls hidden")
        return " · ".join(parts)[:320]

    def _poll(self):
        if self._native_tv_active:
            return  # Native helper sends bounded, honest frame telemetry.
        if not self._requested or not self.view:return
        if time.monotonic()-self._progress_at>45:
            self.stop();self.tv_status.setText("ERROR")
            self.note.setText("No video progress in Pulse. Check embed permissions or use Open on YouTube. Connection stopped.")
            self.tv_diagnostics.setText("No media progress in 45 seconds · connection stopped")
            return
        # A lost JavaScript reply must not disable the independent deadline.
        if self._poll_pending:return
        self._poll_pending=True;generation=self._generation
        # YouTube can successfully load its embed shell while reporting
        # "Video unavailable" for a rotated/ended livestream. Read only the
        # provider's displayed error element, never arbitrary page content.
        script="""(()=>{const e=document.querySelector('.ytp-error-content-wrap,.ytp-error,.ytp-error-message');const probe=document.createElement('video');const codecs={h264:probe.canPlayType('video/mp4; codecs="avc1.42E01E,mp4a.40.2"'),vp9:probe.canPlayType('video/webm; codecs="vp9,opus"'),av1:probe.canPlayType('video/webm; codecs="av01.0.08M.08"')};const chrome=document.querySelector('.ytp-chrome-bottom');const controls_visible=chrome?getComputedStyle(chrome).visibility!=='hidden'&&getComputedStyle(chrome).display!=='none':false;if(e&&e.textContent&&e.textContent.trim())return{provider_error:e.textContent.trim().slice(0,250),codecs};const v=document.querySelector('video');return v?{time:v.currentTime,paused:v.paused,ready:v.readyState,ended:v.ended,error_code:v.error?v.error.code:0,video_width:v.videoWidth,video_height:v.videoHeight,frames:v.getVideoPlaybackQuality?v.getVideoPlaybackQuality().totalVideoFrames:null,network:v.networkState,controls_visible,codecs}:{missing:true,controls_visible,codecs};})()"""
        self.view.page().runJavaScript(script,lambda value,g=generation:self._observed(g,value))

    def _observed(self,generation,value):
        if generation!=self._generation or not self._requested:return
        self._poll_pending=False
        summary=self._media_diagnostics(value)
        if summary and summary!=self._last_decode_info:
            self._last_decode_info=summary
            self.tv_diagnostics.setText(summary+" · Picture/audio not yet proven")
            self.note.setText(summary+" · Picture/audio not yet proven")
        if isinstance(value,dict) and value.get("provider_error"):
            # A displayed provider error is stronger evidence than loadFinished.
            # Never treat a dead live-video recording as a playing channel.
            message=str(value["provider_error"])[:200]
            self.stop()
            self.tv_status.setText("UNAVAILABLE · YouTube video/embedding")
            self.note.setText(
                message + " · Try YouTube watch page in Pulse or "
                "Open on YouTube, or select another exact video."
            )
            # stop() clears stale media telemetry; restore the actual failure
            # receipt to the readable/selectable pane, not only the 14px note.
            self.tv_diagnostics.setText(
                "YouTube unavailable · " + message[:140] +
                " · " + (summary or "No decoder telemetry")[:120] +
                " · Playback not verified"
            )
            return
        if not isinstance(value,dict) or value.get("missing"):
            self.tv_status.setText(
                "PAGE LOADED · no video confirmed" if self._player_loaded
                else "PAGE LOADING"
            )
            return
        error_code=value.get("error_code") or (3 if value.get("error") else 0)
        if error_code:
            self.stop()
            reason={1:"aborted",2:"network",3:"decoder",4:"unsupported media"}
            self.tv_status.setText(
                "VIDEO ERROR · "+reason.get(error_code,"unknown")
            )
            self.note.setText(
                "The YouTube HTMLMediaElement reported error code " +
                str(error_code) +
                ". Provider restrictions, missing Qt codecs or graphics "
                "rendering may be involved. Try the official browser page."
            )
            self.tv_diagnostics.setText(
                "HTMLMediaElement error "+str(error_code)+" · "+
                (summary or "No codec information available")
            )
            return
        current=value.get("time")
        if isinstance(current,bool) or not isinstance(current,(int,float)) or not math.isfinite(current):return
        if value.get("ended"):
            self.stop();self.tv_status.setText("ENDED");return
        if value.get("paused"):
            self.tv_status.setText("PAUSED · press Play in video")
            # Do not reset the never-played deadline on every paused poll:
            # the old implementation could wait forever on a dead embed.
            if self._had_playback:
                self._progress_at=time.monotonic()
        elif value.get("ready",0)<2:
            self.tv_status.setText("BUFFERING · no decoded frame yet")
        elif (value.get("video_width")==0 or value.get("video_height")==0 or
              (value.get("frames") == 0 and current > 2.0)):
            self.tv_status.setText("NO DECODED FRAMES · black video suspected")
        elif self._last_time is not None and current>self._last_time:
            self._had_playback=True
            self.tv_status.setText("VIDEO TIME ADVANCING · picture unverified")
            self.note.setText(
                "Video clock is advancing. Audio and displayed picture are "
                "NOT confirmed by this measurement. "+(summary or "")
            )
            self._progress_at=time.monotonic()
        self._last_time=current

    def _volume(self,value):
        if self._native_tv_active and self.native_tv:
            self.native_tv.command("VOLUME "+str(max(0,min(100,value))))
            return
        if self.view and self._requested:
            self.view.page().runJavaScript("(()=>{const v=document.querySelector('video');if(v)v.volume="+str(max(0,min(100,value))/100.0)+";})()")

    def _mute(self,value):
        if self._native_tv_active and self.native_tv:
            self.native_tv.command("MUTE "+("1" if value else "0"))
            return
        if self.view:self.view.page().setAudioMuted(value)

    def stop(self):
        self._generation=getattr(self,"_generation",0)+1
        self._requested=False;self._poll_pending=False
        self._native_tv_active=False
        self._native_state="off"
        if self._poll_timer:self._poll_timer.stop()
        self._player_loaded=False
        self._had_playback=False
        if self.native_tv:self.native_tv.stop()
        super().stop()
        if hasattr(self,"tv_status"):self.tv_status.setText("OFF")
        if hasattr(self,"tv_diagnostics"):
            self.tv_diagnostics.setText("TV OFF · no active media diagnostics")


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

