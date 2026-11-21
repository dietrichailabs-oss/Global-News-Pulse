"""Installed Windows package identity must be observed locally, never invented.

Offline tests deliberately do not contact YouTube or claim actual playback.
"""
import html
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QTextDocument
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
    assert 'cases=exact.Length * 2 + 16' in src
    assert 'RegisteredWindowsAppReferer()' in src
    assert 'PackageNameFromFullName' in src
    assert 'GetCurrentPackageFullName(ref length, buffer)' in src
    assert 'registered_app_id_match = registeredMatch' in src
    assert 'os_app_identity_verified = registeredMatch' in src
    assert 'source = "GetCurrentPackageFullName"' in src
    assert 'referer_matches_registered_app_id = registeredAppReferer != null' in src
    assert 'provider_acceptance_verified = false' in src
    assert 'request.Headers.SetHeader("Referer", registeredAppReferer ?? PublisherReferer);' in src
    assert 'string? registeredAppReferer = offlineProbe || fullWatch ? null : RegisteredWindowsAppReferer();' in src
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
            "type": "installed_package_identity", "state": "present",
            "referer_matches_registered_app_id": True,
        })
        assert "registered package ID selected" in receipt.tv_diagnostics.text()
        assert "YouTube acceptance NOT verified" in receipt.tv_diagnostics.text()
        Television._native_tv_receipt(receipt, {
            "type": "web_request_identity",
            "referer_present": True, "registered_app_id_match": True,
            "publisher_url_match": False,
        })
        assert "registered Windows app ID observed" in receipt.tv_diagnostics.text()
        assert "YouTube receipt and playback NOT verified" in receipt.tv_diagnostics.text()
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


def _assert_accessible_diagnostics(label):
    """Exercise Qt's real accessibility adapter, not just widget properties."""
    accessible = QAccessible.queryAccessibleInterface(label)
    assert accessible is not None
    assert accessible.text(QAccessible.Text.Name) == "TV codec and renderer diagnostics"
    displayed = label.text()
    assert label.textFormat() == Qt.TextFormat.PlainText
    assert accessible.text(QAccessible.Text.Description) == displayed
    help_text = accessible.text(QAccessible.Text.Help)
    assert help_text == "<pre>" + html.escape(displayed) + "</pre>"
    # Qt's Windows UIA HelpText property receives the controlled envelope.
    # A client can decode the exact body; a help popup renders literal text.
    assert html.unescape(help_text[5:-6]) == displayed
    document = QTextDocument()
    document.setHtml(help_text)
    assert document.toPlainText() == displayed


@pytest.mark.parametrize("terminal", ["error", "ended", "stopped"])
def test_actual_accessible_diagnostics_follow_visible_receipts_and_terminal_state(terminal):
    app = QApplication.instance() or QApplication([])
    tv = Television()
    try:
        _assert_accessible_diagnostics(tv.tv_diagnostics)
        assert tv.tv_diagnostics.text() == "Decoder diagnostics appear after Watch"
        tv._requested = True
        tv._native_tv_active = True
        tv._native_mode = "watch"
        for receipt in (
            {"type": "installed_package_identity", "state": "absent"},
            {"type": "web_request_identity", "referer_present": False},
            {"type": "exact_video_http_response", "http_status": 200},
            {"type": "waiting", "state": "awaiting_play", "frames": 0},
            {"type": "advancing", "current_time": 12.25, "decoded_frames": 245,
             "h264": "probably"},
        ):
            tv._native_tv_receipt(receipt)
            _assert_accessible_diagnostics(tv.tv_diagnostics)
        assert "time 12.25s" in tv.tv_diagnostics.text()
        assert "decoded frames 245" in tv.tv_diagnostics.text()

        tv._native_tv_receipt({
            "type": terminal, "reason": "youtube_unavailable",
            "youtube_error_code": 153, "observation": "visible_dom",
        })
        _assert_accessible_diagnostics(tv.tv_diagnostics)
        final_text = tv.tv_diagnostics.text()
        final_status = tv.tv_status.text()
        assert not tv._requested and not tv._native_tv_active
        if terminal == "error":
            assert "Visible YouTube error code 153" in final_text
            assert "Mode: official watch page" in final_text
        elif terminal == "ended":
            assert "HTMLMediaElement ended" in final_text
        else:
            assert final_text == "TV OFF · no active media diagnostics"
        for late in ({"type": "stopped"}, {"type": "page_loaded", "success": True},
                     {"type": "advancing", "current_time": 99, "decoded_frames": 999}):
            tv._native_tv_receipt(late)
            _assert_accessible_diagnostics(tv.tv_diagnostics)
            assert tv.tv_diagnostics.text() == final_text
            assert tv.tv_status.text() == final_status
    finally:
        tv.stop()
        tv.deleteLater()
        app.processEvents()


def test_diagnostic_help_renders_markup_as_literal_noninteractive_text():
    app = QApplication.instance() or QApplication([])
    tv = Television()
    try:
        # Adversarial setter fixture, not a new provider-text admission path.
        displayed = '<a href="https://invalid.example/">not a link</a> & <b>not bold</b>\nsecond line'
        tv.tv_diagnostics.setText(displayed)
        _assert_accessible_diagnostics(tv.tv_diagnostics)
        document = QTextDocument()
        document.setHtml(tv.tv_diagnostics.whatsThis())
        block = document.begin()
        while block.isValid():
            fragment = block.begin()
            while not fragment.atEnd():
                assert not fragment.fragment().charFormat().isAnchor()
                fragment += 1
            block = block.next()
    finally:
        tv.stop()
        tv.deleteLater()
        app.processEvents()
