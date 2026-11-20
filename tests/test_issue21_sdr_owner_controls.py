"""Issue #21: offline receiver discovery, power-state and volume regression tests."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from urllib.parse import urlsplit

import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.sdr_directory import (
    CURATED_WEBDR_HTTP_ORIGINS, curated_receiver_for_url,
    curated_websdr_receivers, parse_directory, public_receiver_url,
)
from global_pulse.internet_radio import RadioPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _cleanup(panel, app):
    panel.shutdown()
    panel.deleteLater()
    app.processEvents()


def test_public_receiver_links_and_port_policy():
    https = public_receiver_url("https://radio.example.org/rx")
    assert https["embedded_candidate"] is True
    http = public_receiver_url("http://radio.example.org:8073/")
    assert http["embedded_candidate"] is False
    assert "Browser only" in http["reason"]
    with pytest.raises(ValueError):
        public_receiver_url("https://localhost:443/")
    with pytest.raises(ValueError):
        public_receiver_url("http://192.168.0.1:8073/")
    with pytest.raises(ValueError):
        public_receiver_url("https://radio.example.org\\@localhost/")
    with pytest.raises(ValueError):
        public_receiver_url("https://user:secret@radio.example.org/")


def test_websdr_directory_html_is_bounded_and_deduplicated():
    html = b"""<html><body>
      <a href="http://sdr1.example.org:8901/">Ontario amateur receiver</a>
      <a href="http://sdr1.example.org:8901/">Duplicate</a>
      <a href="https://radio.example.org/">Europe HF WebSDR</a>
      <a href="http://localhost:8901/">Private reject</a>
      <a href="javascript:alert(1)">Script reject</a>
      <a href="https://websdr.org/faq.html">FAQ reject</a>
      </body></html>"""
    rows = parse_directory("websdr", html)
    assert [r["host"] for r in rows] == ["sdr1.example.org", "radio.example.org"]
    assert rows[0]["embedded_candidate"] is False
    assert rows[1]["embedded_candidate"] is True
    assert rows[0]["name"] == "Ontario amateur receiver"


def test_kiwi_directory_json_and_empty_handling():
    import json
    raw = json.dumps({"receivers": [
        {"url": "https://kiwi.example.org/", "name": "Example Kiwi"},
        {"url": "http://remote.example.org:8073/", "name": "Remote Kiwi"},
        {"url": "https://127.0.0.1/", "name": "Forbidden"}]}).encode()
    rows = parse_directory("kiwisdr", raw)
    assert len(rows) == 2
    assert rows[0]["name"] == "Example Kiwi"
    assert rows[1]["embedded_candidate"] is False
    assert parse_directory("kiwisdr", b"<html><h1>Access gate</h1></html>") == []
    with pytest.raises(ValueError):
        parse_directory("kiwisdr", b"x" * 1_000_001)


def test_receiver_picker_populates_url_and_flags_browser_only(app):
    panel = RadioPanel(confirm=lambda: False)
    try:
        assert panel.receiver_connect.isEnabled() is False
        panel.sdr_directory_cache["websdr"] = [
            dict(public_receiver_url("http://outside.example.org:8901/"),
                 name="Outside receiver", provider="websdr"),
            dict(public_receiver_url("https://online.example.org/"),
                 name="In-app candidate", provider="websdr"),
        ]
        panel._change_receiver_directory()
        # Individually supplied receiver links remain selectable offline;
        # the original two dynamic rows are still retained after that list.
        assert panel.receiver_picker.count() == len(curated_websdr_receivers()) + 3
        panel.receiver_picker.setCurrentIndex(1)
        assert panel.receiver_url.text() == "http://na5b.com:8901/"
        assert panel.receiver_connect.isEnabled()
        outside=next(i for i in range(panel.receiver_picker.count())
                     if (panel.receiver_picker.itemData(i) or {}).get("name")=="Outside receiver")
        panel.receiver_picker.setCurrentIndex(outside)
        assert panel.receiver_url.text().startswith("http://")
        assert panel.receiver_external.isEnabled()
        assert not panel.receiver_connect.isEnabled()
        online=next(i for i in range(panel.receiver_picker.count())
                    if (panel.receiver_picker.itemData(i) or {}).get("name")=="In-app candidate")
        panel.receiver_picker.setCurrentIndex(online)
        assert panel.receiver_url.text().startswith("https://")
        assert panel.receiver_connect.isEnabled()
        assert panel.receiver_type.currentData() == "websdr"
    finally:
        _cleanup(panel, app)


def test_recovered_receivers_preserve_individual_operator_evidence():
    rows = {row["id"]: row for row in curated_websdr_receivers()}
    expected_urls = {
        "maasbree_low": "http://sdr.websdrmaasbree.nl:8901/",
        "maasbree_high": "http://sdr.websdrmaasbree.nl:8902/",
        "maasbree_2m": "http://sdr.websdrmaasbree.nl:8905/",
        "kfs1": "http://websdr1.kfsdr.com:8901/",
        "kfs2": "http://websdr2.kfsdr.com:8902/",
        "g0xbu1": "http://g0xbuwebsdr.ddns.net:8901/",
        "g0xbu2": "http://g0xbuwebsdr.ddns.net:8902/",
        "df0hte": "https://websdr.afunk.hs-esslingen.de/",
        "goonhilly": "https://vhf-goonhilly.batc.org.uk/",
        "pardinho": "https://pardinho.websdr.com.br/",
        "oa6dxv": "https://websdr2.republicaoa6.com/",
    }
    for identifier, url in expected_urls.items():
        row = rows[identifier]
        assert row["url"] == url
        assert row["name"] and row["location"] and row["bands"]
        assert row["documentation"].startswith("https://")
        assert "2026-11-20" in row["provenance"]
        assert "availability unverified" in row["reason"]
    assert rows["df0hte"]["ranges_khz"] == (
        (1416.0, 2184.0), (3468.0, 3852.0), (6908.0, 7292.0),
        (10004.0, 10196.0), (13791.0, 14559.0), (18004.0, 18196.0),
        (26431.0, 27199.0), (28936.0, 29704.0),
    )
    assert "indexed operator mobile page" in rows["df0hte"]["provenance"]
    assert rows["goonhilly"]["ranges_khz"] == (
        (144000.0, 146000.0), (435000.0, 437000.0),
        (1296000.0, 1298000.0), (2320000.0, 2321000.0),
    )
    assert rows["maasbree_2m"]["ranges_khz"] == (
        (144000.0, 145000.0), (145000.0, 146000.0),
    )
    assert "different antennas" in rows["maasbree_2m"]["provenance"]


def test_operator_band_labels_do_not_fabricate_numeric_receiver_bounds():
    rows = {row["id"]: row for row in curated_websdr_receivers()}
    for identifier in ("maasbree_low", "maasbree_high", "kfs1", "kfs2",
                       "g0xbu1", "g0xbu2", "pardinho", "oa6dxv"):
        assert rows[identifier]["bands"]
        assert rows[identifier]["ranges_khz"] == ()
    assert rows["kfs2"]["bands"] == ["160m", "12m", "10m-FM"]
    assert rows["pardinho"]["bands"] == ["160m", "80m", "40m", "20m", "15m", "10/11m"]
    assert rows["oa6dxv"]["bands"] == ["40m"]
    assert "center 7100 kHz" in rows["oa6dxv"]["provenance"]
    assert "not affiliated" in rows["g0xbu1"]["provenance"]


def test_na5b_displays_only_owner_observed_band_labels_without_inferred_bounds():
    row = curated_receiver_for_url("http://na5b.com:8901/")
    assert row["bands"] == ["MW–160", "80m", "40m", "30m", "25m", "20m", "15m", "10m"]
    assert row["ranges_khz"] == ()
    assert "owner's receiver screenshot" in row["provenance"]
    assert "numeric bounds and live reception not verified" in row["provenance"]
    assert "availability unverified" in row["reason"]


def test_curated_origins_are_unique_and_transport_explanations_are_specific():
    rows = curated_websdr_receivers()
    assert len({row["id"] for row in rows}) == len(rows)
    origins = []
    http_origins = set()
    for row in rows:
        parsed = urlsplit(row["url"])
        origin = (parsed.scheme, parsed.hostname,
                  parsed.port or (443 if parsed.scheme == "https" else 80))
        origins.append(origin)
        if parsed.scheme == "https":
            assert row["embedded_candidate"] is True
            assert "Operator HTTPS/443 candidate" in row["reason"]
            assert "unencrypted" not in row["reason"]
            assert "HTTP/None" not in row["reason"]
        else:
            assert row["embedded_candidate"] is False
            assert "specific unencrypted transport consent" in row["reason"]
            http_origins.add((parsed.hostname, parsed.port))
    assert len(set(origins)) == len(origins)
    assert http_origins == CURATED_WEBDR_HTTP_ORIGINS


def test_curated_receiver_records_are_fresh_and_do_not_share_mutable_bands():
    first = curated_websdr_receivers()
    original = {row["id"]: row for row in curated_websdr_receivers()}
    for row in first:
        row["name"] = "Tampered caller label"
        row["bands"].append("invented band")
        row["ranges_khz"] = ((0.0, 999999999.0),)
    assert {row["id"]: row for row in curated_websdr_receivers()} == original
    assert curated_receiver_for_url(original["df0hte"]["url"]) == original["df0hte"]


def test_curated_https_default_port_preserves_exact_origin_metadata_only():
    for row in curated_websdr_receivers():
        parsed = urlsplit(row["url"])
        if parsed.scheme == "https":
            explicit = f"https://{parsed.hostname}:443{parsed.path}"
            assert curated_receiver_for_url(explicit)["id"] == row["id"]
            assert curated_receiver_for_url(f"https://{parsed.hostname}:444/") is None
            assert curated_receiver_for_url(f"http://{parsed.hostname}:443/") is None
        else:
            assert curated_receiver_for_url(f"http://{parsed.hostname}/") is None
            assert curated_receiver_for_url(f"https://{parsed.hostname}:{parsed.port}/") is None
    assert curated_receiver_for_url("https://user:secret@vhf-goonhilly.batc.org.uk/") is None


def test_curating_a_link_does_not_grant_an_unreviewed_http_origin(monkeypatch):
    import global_pulse.sdr_directory as directory
    example = dict(curated_websdr_receivers()[0])
    example.update(id="unknown", url="http://unreviewed.example.org:8901/", bands=())
    for computed_key in ("embedded_candidate", "host", "provider", "reason"):
        example.pop(computed_key)
    monkeypatch.setattr(directory, "CURATED_WEBDR_RECEIVERS", (example,))
    row = directory.curated_websdr_receivers()[0]
    assert row["embedded_candidate"] is False
    assert row["reason"].startswith("Browser only:")
    assert "not admitted in-app" in row["reason"]
    assert "unencrypted transport consent" not in row["reason"]


def test_receiver_state_is_not_green_until_load_success(app):
    panel = RadioPanel(confirm=lambda: False)
    class FakePage:
        def __init__(self):
            self.muted = None
        def setAudioMuted(self, flag):
            self.muted = flag
    class FakeView:
        def __init__(self):
            self._page = FakePage()
        def page(self):
            return self._page
        def stop(self):
            pass
        def setUrl(self, value):
            pass
        def hide(self):
            pass
        def deleteLater(self):
            pass
    try:
        panel.receiver_view = FakeView()
        panel.receiver_connected = True
        panel._sdr_state_change("CONNECTING")
        assert "CONNECTING" in panel.sdr_status.text()
        assert panel.sdr_state == "CONNECTING"
        assert not panel.sdr_mute.isEnabled()
        panel._sdr_load_finished(True)
        assert "ON" in panel.sdr_status.text()
        assert panel.sdr_mute.isEnabled()
        assert panel.sdr_volume.isEnabled()
        panel.sdr_mute.setChecked(True)
        assert panel.receiver_view.page().muted is True
        panel.disconnect_receiver()
        assert "OFF" in panel.sdr_status.text()
        assert not panel.sdr_mute.isEnabled()
    finally:
        _cleanup(panel, app)


def test_kiwi_volume_is_explicit_and_websdr_cannot_fake_volume(app):
    panel = RadioPanel(confirm=lambda: False)
    try:
        panel.receiver_url.setText("https://radio.example.org/")
        assert panel._tuned_receiver_url()[0].endswith("?f=7100usb&vol=40")
        panel.sdr_volume.setValue(25)
        assert panel._tuned_receiver_url()[0].endswith("?f=7100usb&vol=25")
        assert panel.sdr_volume_value.text() == "25%"
        panel.receiver_type.setCurrentIndex(panel.receiver_type.findData("websdr"))
        panel._sdr_state_change("ON")
        assert not panel.sdr_volume.isEnabled()
        assert panel._tuned_receiver_url()[0].endswith("?tune=7100usb")
    finally:
        _cleanup(panel, app)
