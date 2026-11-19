"""Installed Windows package identity must be observed locally, never invented.

Offline tests deliberately do not contact YouTube or claim actual playback.
"""
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLabel

from global_pulse.single_media import Television


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "packaging" / "tv" / "NativeTvProgram.cs"


def test_native_package_identity_is_os_backed_not_a_publisher_website():
    src = NATIVE.read_text(encoding="utf-8")
    assert 'GetCurrentPackageFullName(ref length, null)' in src
    assert 'GetCurrentPackageFullName(ref length, buffer)' in src
    assert 'if (result == 15700) return "absent"' in src
    assert 'result != 122 || length == 0 || length > 512' in src
    assert 'return result == 0 && buffer.Length > 0 ? "present" : "unknown"' in src
    assert 'type = "installed_package_identity"' in src
    assert 'string installedPackageState = InstalledPackageIdentityState();' in src
    assert 'os_package_identity_state=installedPackageState' in src
    assert 'cases=exact.Length * 2 + 12' in src
    assert 'source = "GetCurrentPackageFullName"' in src
    assert 'referer_matches_registered_app_id = false' in src
    assert 'provider_acceptance_verified = false' in src
    assert 'request.Headers.SetHeader("Referer", PublisherReferer);' in src
    assert src.index('type = "installed_package_identity"') < src.index(
        'web.NavigateWithWebResourceRequest(request);')
    # Identity values, user folder and registry state must never be logged.
    assert 'Reply(new { type = "installed_package_identity",\n                state = InstalledPackageIdentityState(),' in src
    assert 'GetCurrentPackageFullName' in src
    assert 'PublisherReferer = "https://www.dietrichailabs.com/"' in src


def test_no_package_identity_is_reported_without_invented_google_acceptance():
    app = QApplication.instance() or QApplication([])
    receipt = SimpleNamespace(
        _requested=True, _native_tv_active=True,
        _native_identity_note="", _native_package_note="", _native_http_note="",
        _last_native_status_at=0.0,
        tv_status=QLabel(), tv_diagnostics=QLabel(),
    )
    try:
        for state, expected in (
            ("absent", "absent for this process"),
            ("present", "detected locally"),
            ("unknown", "unavailable/unknown"),
            ("anything else", "unavailable/unknown"),
        ):
            Television._native_tv_receipt(receipt, {
                "type": "installed_package_identity", "state": state,
                "referer_matches_registered_app_id": False,
                "provider_acceptance_verified": False,
            })
            assert expected in receipt.tv_diagnostics.text()
            assert "no video playback confirmed" in receipt.tv_diagnostics.text()
            assert "https://" not in receipt.tv_diagnostics.text()
        Television._native_tv_receipt(receipt, {
            "type": "installed_package_identity", "state": "absent",
        })
        Television._native_tv_receipt(receipt, {
            "type": "web_request_identity",
            "referer_present": True, "publisher_url_match": True,
        })
        assert "publisher URL observed" in receipt.tv_diagnostics.text()
        assert "absent for this process" in receipt.tv_diagnostics.text()
        Television._native_tv_receipt(receipt, {
            "type": "exact_video_http_response", "http_status": 200,
        })
        assert "HTTP 200" in receipt.tv_diagnostics.text()
        assert "identity/playback NOT verified" in receipt.tv_diagnostics.text()
        assert "absent for this process" in receipt.tv_diagnostics.text()
        Television._native_tv_receipt(receipt, {
            "type": "waiting", "h264": "probably", "frames": 0,
        })
        assert "decoded frames 0" in receipt.tv_diagnostics.text()
        assert "absent for this process" in receipt.tv_diagnostics.text()
        assert "picture/audio not confirmed" in receipt.tv_diagnostics.text()
    finally:
        receipt.tv_status.deleteLater()
        receipt.tv_diagnostics.deleteLater()
        app.processEvents()
