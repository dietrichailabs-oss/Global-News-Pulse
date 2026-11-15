"""Issue #82 / NA5B: an omitted HTTP/WS port is NOT the consented 8901.

Offline real-Qt QUrl parsing only. No external requests, SDR audio, or provider
availability are inferred from this scoped regression suite.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QUrl
from global_pulse.internet_radio import _receiver_origin_matches


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://na5b.com:8901/", True),
        ("http://na5b.com:8901/?tune=14250usb", True),
        ("http://na5b.com/", False),  # implicit HTTP/80 is not 8901
        ("http://na5b.com:80/", False),
        ("http://na5b.com:8902/", False),
        ("https://na5b.com:8901/", False),
        ("http://evil.example:8901/", False),
        ("ws://na5b.com:8901/socket", True),
        ("ws://na5b.com/socket", False),  # implicit WS/80 is not 8901
        ("ws://na5b.com:80/socket", False),
        ("wss://na5b.com:8901/socket", False),
        ("wss://evil.example:8901/socket", False),
    ],
)
def test_legacy_exact_protocol_host_effective_port(url, expected):
    assert _receiver_origin_matches(
        QUrl(url), "na5b.com", "http", "ws", 8901
    ) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://na5b.com:8901/", True),
        ("http://na5b.com/", False),
        ("ws://na5b.com:8901/socket", False),  # no WebSocket main navigation
        ("http://na5b.com:80/", False),
    ],
)
def test_legacy_main_frame_requires_exact_http_port(url, expected):
    assert _receiver_origin_matches(
        QUrl(url), "na5b.com", "http", "ws", 8901, main=True
    ) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://receiver.example/", True),  # implicit HTTPS/443 is correct
        ("https://receiver.example:443/", True),
        ("wss://receiver.example/socket", True),
        ("wss://receiver.example:443/socket", True),
        ("http://receiver.example/", False),
        ("ws://receiver.example/socket", False),
        ("https://receiver.example:8443/", False),
        ("https://unrelated.example/", False),
    ],
)
def test_standard_https_receiver_retains_port_443_default(url, expected):
    assert _receiver_origin_matches(
        QUrl(url), "receiver.example", "https", "wss", 443
    ) is expected


def test_standard_https_receiver_main_frame_disallows_wss_navigation():
    assert not _receiver_origin_matches(
        QUrl("wss://receiver.example/socket"), "receiver.example",
        "https", "wss", 443, main=True
    )
