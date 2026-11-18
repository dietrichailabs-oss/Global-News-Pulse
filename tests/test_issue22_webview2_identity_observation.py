"""Bounded YouTube Error 153 instrumentation; not a playback or app-ID pass.

Network remains disabled in tests. Native WebView2 inspection is pre-send only,
and the Inno installer does not independently establish an MSIX package identity.
"""
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLabel

from global_pulse.single_media import Television


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "packaging" / "tv" / "NativeTvProgram.cs"


def test_webview2_observes_exact_consented_request_and_still_blocks_redirects():
    src = NATIVE.read_text(encoding="utf-8")
    assert 'request.Headers.SetHeader("Referer", PublisherReferer);' in src
    assert 'web.NavigateWithWebResourceRequest(request);' in src
    assert src.index('web.WebResourceRequested +=') < src.index(
        'web.NavigateWithWebResourceRequest(request);')
    assert 'e.ResourceContext == CoreWebView2WebResourceContext.Document' in src
    assert 'ExactVideoNavigation(e.Request.Uri, videoId, fullWatch)' in src
    assert 'e.Request.Headers.GetHeader("Referer")' in src
    assert 'type = "web_request_identity"' in src
    assert 'stage = "pre_network"' in src
    assert 'os_app_identity_verified = false' in src
    assert 'network_delivery_verified = false' in src
    assert 'if (e.IsRedirected)' in src
    assert 'if (!permitted) e.Cancel = true;' in src
    assert 'type = "navigation_redirect"' in src
    assert src.index('if (!permitted) e.Cancel = true;') < src.index(
        'web.NavigateWithWebResourceRequest(request);')
    # The publisher domain is not silently reclassified as an OS-registered ID.
    assert 'private const string PublisherReferer = "https://www.dietrichailabs.com/";' in src
    assert "publisher-owned" not in src.lower() or "app identity" in src.lower()


def test_visible_video_diagnostic_distinguishes_header_from_delivery_and_decoding():
    app = QApplication.instance() or QApplication([])
    receipt = SimpleNamespace(
        _requested=True, _native_tv_active=True,
        _native_identity_note="", _last_native_status_at=0.0,
        tv_status=QLabel(), tv_diagnostics=QLabel(),
    )
    Television._native_tv_receipt(receipt, {
        "type": "web_request_identity", "stage": "pre_network",
        "referer_present": True, "publisher_url_match": True,
        "os_app_identity_verified": False, "network_delivery_verified": False,
    })
    assert "publisher URL observed" in receipt.tv_diagnostics.text()
    assert "NOT verified" in receipt.tv_diagnostics.text()
    assert "no video playback confirmed" in receipt.tv_diagnostics.text()
    Television._native_tv_receipt(receipt, {
        "type": "waiting", "h264": "probably", "frames": 0,
    })
    assert "decoded frames 0" in receipt.tv_diagnostics.text()
    assert "OS app identity" in receipt.tv_diagnostics.text()
    assert "picture/audio not confirmed" in receipt.tv_diagnostics.text()
    Television._native_tv_receipt(receipt, {
        "type": "navigation_redirect", "allowed": False,
    })
    assert "BLOCKED" in receipt.tv_status.text()
    receipt.tv_status.deleteLater()
    receipt.tv_diagnostics.deleteLater()
    app.processEvents()


def test_missing_or_changed_referrer_never_becomes_verified_identity():
    QApplication.instance() or QApplication([])
    status = SimpleNamespace(
        _requested=True, _native_tv_active=True,
        _native_identity_note="", _last_native_status_at=0.0,
        tv_status=QLabel(), tv_diagnostics=QLabel(),
    )
    for present, matches, expected in (
        (False, False, "missing/unknown"),
        (True, False, "publisher mismatch"),
    ):
        Television._native_tv_receipt(status, {
            "type": "web_request_identity",
            "referer_present": present, "publisher_url_match": matches,
        })
        assert expected in status.tv_diagnostics.text()
        assert "OS app identity and server receipt NOT verified" in status.tv_diagnostics.text()
