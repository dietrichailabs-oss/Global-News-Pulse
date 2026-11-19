"""Native WebView2 exact-URL HTTP observation: offline provenance contract."""
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QLabel
from global_pulse.single_media import Television

def test_native_exact_url_status_observation_is_bounded_and_guarded():
    src=(Path(__file__).resolve().parents[1]/"packaging/tv/NativeTvProgram.cs").read_text(encoding="utf-8")
    for s in ('web.WebResourceResponseReceived +=','exactVideoHttpResponseCount >= 8',
              'ExactVideoNavigation(e.Request.Uri, videoId, fullWatch)',
              'status = e.Response?.StatusCode ?? 0;',
              'type = "exact_video_http_response"',
              'provider_identity_acceptance_verified = false',
              'picture_audio_verified = false',
              'request.Headers.SetHeader("Referer", PublisherReferer);',
              'if (!permitted) e.Cancel = true;'):
        assert s in src
    assert src.index("web.WebResourceRequested +=")<src.index("web.WebResourceResponseReceived +=")
    assert src.index("web.NavigationStarting +=")<src.index("web.NavigateWithWebResourceRequest(request);")

def test_status_not_equated_to_app_identity_or_playback():
    app=QApplication.instance() or QApplication([])
    s=SimpleNamespace(_requested=True,_native_tv_active=True,
        _native_identity_note="OS app identity unverified",_native_http_note="",
        _last_native_status_at=0.0,tv_status=QLabel(),tv_diagnostics=QLabel())
    try:
        for v in (200,302,403,0,"garbage"):
            Television._native_tv_receipt(s,{"type":"exact_video_http_response","http_status":v})
            msg=s.tv_diagnostics.text()
            assert "WebView2 observed" in msg and "identity/playback NOT verified" in msg
            assert "picture/audio not confirmed" in msg
            if v==403: assert "HTTP ERROR" in s.tv_status.text()
        Television._native_tv_receipt(s,{"type":"exact_video_http_response","http_status":200})
        Television._native_tv_receipt(s,{"type":"waiting","h264":"probably","frames":0})
        assert "HTTP 200" in s.tv_diagnostics.text()
        assert "decoded frames 0" in s.tv_diagnostics.text()
    finally:
        s.tv_status.deleteLater()
        s.tv_diagnostics.deleteLater()
        app.processEvents()
