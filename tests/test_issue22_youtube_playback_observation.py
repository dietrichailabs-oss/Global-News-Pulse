"""Offline actual-JavaScript/native-receipt regressions, not YouTube playback.

The production C# PlaybackProbe is evaluated by Qt's JS engine against inert
DOM fixtures. No browser, network, external video, or identity registration is
used. The production C# timing state machine is separately executed by the
packaged Windows helper's --self-test-policy, not emulated in Python here.
"""
import json
import os
from pathlib import Path
import re
import socket

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication

from global_pulse.single_media import Television


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "packaging" / "tv" / "NativeTvProgram.cs"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline player-observation fixtures must not use network")
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def native_probe():
    source = NATIVE.read_text(encoding="utf-8")
    match = re.search(r'private const string PlaybackProbe = @"((?:[^"]|"")*)";', source)
    assert match, "Exercise the actual production probe, never a test reimplementation"
    return match.group(1).replace('""', '"')


def observe(app, *, errors=None, video=None, missing=False):
    engine = QJSEngine()
    fixture = json.dumps({"errors": errors or [], "video": video or {}, "missing": missing})
    setup = r"""
        const fixture=FIXTURE;
        function node(spec) {
            const rect=Object.assign({left:10,top:10,width:100,height:20},spec.rect||{});
            rect.right=rect.left+rect.width;rect.bottom=rect.top+rect.height;
            return {
                isConnected:spec.connected!==false,
                innerText:spec.text||'', textContent:spec.rawText||spec.text||'',
                parentElement:spec.parent?node(spec.parent):null,
                style:Object.assign({display:'block',visibility:'visible',opacity:'1',
                                     contentVisibility:'visible',overflowX:'visible',
                                     overflowY:'visible'},spec.style||{}),
                clientLeft:0,clientTop:0,
                clientWidth:spec.clientWidth===undefined?rect.width:spec.clientWidth,
                clientHeight:spec.clientHeight===undefined?rect.height:spec.clientHeight,
                getClientRects:()=>spec.rects===false?[]:[rect],
                getBoundingClientRect:()=>rect
            };
        }
        const errors=fixture.errors.map(node);
        const video=fixture.missing?null:Object.assign({
            currentTime:4,paused:true,ended:false,readyState:4,videoWidth:640,error:null,
            getVideoPlaybackQuality:()=>({totalVideoFrames:120})
        },fixture.video);
        function getComputedStyle(element) {return element.style;}
        const window={innerWidth:960,innerHeight:540};
        const document={
            querySelectorAll:()=>errors,
            querySelector:()=>video,
            createElement:()=>({canPlayType:()=> 'probably'})
        };
    """.replace("FIXTURE", fixture)
    # Evaluate the fixture and real probe in one lexical scope. QJSEngine's
    # separate evaluate() calls do not retain top-level const bindings.
    result = engine.evaluate(setup + native_probe())
    assert not result.isError(), result.toString()
    return json.loads(result.toString())


@pytest.mark.parametrize("code", [2, 5, 100, 101, 150, 153])
def test_actual_native_js_returns_visible_code_without_provider_text(app, code):
    result = observe(app, errors=[{"text":f"An error occurred. Error code: {code} secret-title"}])
    assert result["provider_error_visible"] is True
    assert result["provider_error_code"] == code
    assert "secret-title" not in json.dumps(result)
    assert not any(key in result for key in ("provider_error", "text", "html", "url"))


@pytest.mark.parametrize("hidden", [
    {"connected":False},
    {"rects":False},
    {"rect":{"width":0}},
    {"rect":{"height":0}},
    {"rect":{"left":1000}},
    {"rect":{"top":550}},
    {"style":{"display":"none"}},
    {"style":{"visibility":"hidden"}},
    {"style":{"visibility":"collapse"}},
    {"style":{"contentVisibility":"hidden"}},
    {"style":{"opacity":"0"}},
    {"style":{"opacity":"0.0"}},
    {"parent":{"style":{"display":"none"}}},
    {"parent":{"style":{"visibility":"hidden"}}},
    {"parent":{"style":{"opacity":"0"}}},
    {"parent":{"parent":{"style":{"opacity":"0"}}}},
    {"parent":{"style":{"overflowY":"hidden"},"clientHeight":0}},
    {"parent":{"style":{"overflowX":"clip"},"clientWidth":0}},
    {"parent":{"style":{"overflowY":"auto"},"rect":{"top":100}}},
])
def test_actual_native_js_ignores_hidden_errors_during_real_frame_observation(app, hidden):
    result = observe(app, errors=[dict(hidden,text="Error153 secret-title")],
                     video={"paused":False,"currentTime":10})
    assert result["provider_error_visible"] is False
    assert result["provider_error_code"] == 0
    assert result["time"] == 10 and result["frames"] == 120
    assert result["width"] == 640 and result["paused"] is False


def test_actual_native_js_accepts_partially_visible_error_inside_clipped_viewport(app):
    result = observe(app, errors=[{"text":"Error153","rect":{"left":950},
        "parent":{"style":{"overflowX":"hidden"},"rect":{"left":940,"width":40}}}])
    assert result["provider_error_visible"] is True
    assert result["provider_error_code"] == 153


def test_actual_native_js_checks_later_visible_match_and_uses_rendered_text(app):
    result = observe(app, errors=[
        {"style":{"display":"none"},"text":"Error153 stale"},
        {"text":"","rawText":"Error100 hidden descendant"},
        {"text":"Error150 actual rendered message"},
    ])
    assert result["provider_error_visible"] is True
    assert result["provider_error_code"] == 150
    assert "stale" not in json.dumps(result)


@pytest.mark.parametrize("message", [
    "Error code: 1533", "Error code: 999", "A visible failure without a code",
    "<script>secret-title</script>" + "X" * 10000,
])
def test_actual_native_js_unknown_messages_are_only_an_enum(app, message):
    result = observe(app, errors=[{"text":message}])
    assert result["provider_error_visible"] is True
    assert result["provider_error_code"] == 0
    assert len(json.dumps(result)) < 500


@pytest.mark.parametrize("code", [1, 2, 3, 4, 153, "3", None])
def test_actual_native_js_keeps_html_media_error_namespace_separate(app, code):
    result = observe(app, video={"error":{"code":code}})
    assert result["media_error_code"] == (code if type(code) is int and 1<=code<=4 else 0)
    assert result["provider_error_visible"] is False
    assert result["provider_error_code"] == 0


def test_actual_native_js_missing_player_and_ended_are_not_guessed_provider_errors(app):
    absent = observe(app, missing=True)
    assert absent["present"] is False and absent["time"] is None
    assert absent["provider_error_visible"] is False
    ended = observe(app, video={"ended":True})
    assert ended["ended"] is True and ended["provider_error_code"] == 0


@pytest.fixture
def tv(app):
    widget = Television()
    widget._requested = True
    widget._native_tv_active = True
    yield widget
    widget.stop()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def seed_evidence(tv, mode="embed"):
    tv._native_mode = mode
    tv._native_tv_receipt({"type":"installed_package_identity", "state":"absent"})
    tv._native_tv_receipt({"type":"web_request_identity", "referer_present":mode=="embed",
                          "publisher_url_match":mode=="embed", "registered_app_id_match":False})
    tv._native_tv_receipt({"type":"exact_video_http_response", "http_status":200})


@pytest.mark.parametrize("mode", ["embed", "watch"])
def test_native_failure_retains_bounded_evidence_after_stop_and_late_receipts(tv, mode):
    seed_evidence(tv, mode)
    tv._native_tv_receipt({"type":"error", "reason":"youtube_unavailable",
                          "observation":"visible_dom", "youtube_error_code":153,
                          "provider_error":"<b>secret-title</b>", "url":"https://secret.example/"})
    status, receipt = tv.tv_status.text(), tv.tv_diagnostics.text()
    assert "YOUTUBE ERROR 153" in status
    assert "DOM observation, not an IFrame API event" in receipt
    assert "Windows package identity: absent" in receipt and "HTTP: 200" in receipt
    assert ("official watch page" if mode=="watch" else "embedded player") in receipt
    assert ("browser-managed" if mode=="watch" else "publisher URL observed (not an app ID)") in receipt
    assert "provider acceptance and picture/audio NOT verified" in receipt
    assert "secret" not in receipt and len(receipt)<650
    assert tv.tv_diagnostics.textFormat() == Qt.TextFormat.PlainText
    assert not tv._requested and not tv._native_tv_active
    for event in ({"type":"stopped"}, {"type":"page_loaded","success":True},
                  {"type":"advancing","current_time":5,"decoded_frames":120}):
        tv._native_tv_receipt(event)
    assert tv.tv_status.text() == status and tv.tv_diagnostics.text() == receipt


@pytest.mark.parametrize("code", [True, "153", 1533, None, {}, []])
def test_native_error_readout_never_promotes_unknown_code_or_raw_text(tv, code):
    tv._native_tv_receipt({"type":"error", "reason":"youtube_unavailable",
                          "observation":"visible_dom", "youtube_error_code":code,
                          "provider_error":"Error153 SECRET"})
    assert "153" not in tv.tv_status.text()
    assert "numeric code unrecognized" in tv.tv_diagnostics.text()
    assert "SECRET" not in tv.tv_diagnostics.text()


def test_native_error_namespaces_and_provenance_are_not_interchangeable(tv):
    title, message = Television._native_error_readout({
        "reason":"html_media_error", "observation":"html_media_element", "media_error_code":3})
    assert "decoder" in title and "HTMLMediaElement error 3" in message
    title, message = Television._native_error_readout({
        "reason":"youtube_unavailable", "observation":"html_media_element", "youtube_error_code":153})
    assert "153" not in title and "provenance unreported" in message
    for reason in ([], {}, "https://secret.example/", "<b>secret</b>"):
        title, message = Television._native_error_readout({"reason":reason})
        assert "unclassified" in title and "secret" not in message


def test_native_pause_resume_and_stall_states_update_inside_numeric_throttle(tv, monkeypatch):
    monkeypatch.setattr("global_pulse.single_media.time.monotonic",lambda:100.0)
    tv._native_tv_receipt({"type":"waiting","state":"awaiting_play","frames":0})
    assert tv.tv_status.text().startswith("AWAITING PLAY")
    tv._native_tv_receipt({"type":"advancing","current_time":1,"decoded_frames":20})
    assert tv.tv_status.text().startswith("VIDEO TIME ADVANCING")
    for state, prefix in (("paused","PAUSED"),("buffering","BUFFERING"),("stalled","STALLED")):
        tv._native_tv_receipt({"type":"waiting","state":state,"frames":20})
        assert tv.tv_status.text().startswith(prefix)
    tv._native_tv_receipt({"type":"advancing","current_time":2,"decoded_frames":40})
    assert tv.tv_status.text().startswith("VIDEO TIME ADVANCING")
    assert "autoplay blocked" not in tv.tv_diagnostics.text().lower()


def test_native_ended_is_not_overwritten_by_process_stopped(tv):
    seed_evidence(tv,"watch")
    tv._native_tv_receipt({"type":"ended", "observation":"html_media_element"})
    receipt = tv.tv_diagnostics.text()
    assert tv.tv_status.text().startswith("ENDED")
    assert not tv._requested
    tv._native_tv_receipt({"type":"stopped","exit_code":0})
    assert tv.tv_status.text().startswith("ENDED") and tv.tv_diagnostics.text()==receipt


@pytest.mark.parametrize("current,frames", [
    (True,20), (float("nan"),20), (float("inf"),20), (10**500,20),
    (-1,20), (1,True), (1,0), (1,"200"), (1,{}),
])
def test_malformed_native_progress_is_not_a_playback_claim(tv, current, frames):
    tv._native_tv_receipt({"type":"advancing","current_time":current,"decoded_frames":frames})
    assert not tv._had_playback
    assert "ADVANCING" not in tv.tv_status.text()


def test_watch_page_uses_normal_navigation_without_modifying_embed_identity_contract():
    source = NATIVE.read_text(encoding="utf-8")
    navigation = source[source.index("playbackClock.Restart();"):source.index("telemetry.Start();")]
    watch, embed = navigation.split("else",1)
    assert "if (fullWatch)" in watch and "web.Navigate(url);" in watch
    assert "SetHeader" not in watch and "NavigateWithWebResourceRequest" not in watch
    assert 'request.Headers.SetHeader("Referer", registeredAppReferer ?? PublisherReferer);' in embed
    assert "web.NavigateWithWebResourceRequest(request);" in embed
    assert "offlineProbe || fullWatch ? null : RegisteredWindowsAppReferer()" in source
    assert 'FrameAllowed(e.Uri,videoId,fullWatch)' in source
    assert 'if (!permitted) e.Cancel = true;' in source


def test_native_deadline_predicate_is_invoked_before_pending_callback_gate_and_self_tested():
    source = NATIVE.read_text(encoding="utf-8")
    observer = source[source.index("private async Task InspectVideoAsync()"):
                      source.index("internal void CleanupPrivateProfileAfterExit()")]
    assert observer.index("playback.ExpiredReason(") < observer.index("if (pollPending) return;")
    assert 'readonly Stopwatch playbackClock' in source
    assert 'DateTime.UtcNow - started' not in source
    assert "failures += PlaybackPolicySelfTest(out int playbackCases);" in source
    assert "playback_cases=playbackCases" in source
    assert 'now - lastObservationAt > 45' in source
    assert 'State is "buffering" or "stalled"' in source
    assert 'return State = Played ? "paused" : "awaiting_play"' in source
    assert 'type="ended", observation="html_media_element"' in observer
    assert 'type="error", reason="youtube_unavailable", observation="visible_dom"' in observer
    assert 'type="error", reason="html_media_error", observation="html_media_element"' in observer
