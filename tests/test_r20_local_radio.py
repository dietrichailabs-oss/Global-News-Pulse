"""Independent adversarial ZIP-discovery QA: offline, synthetic, no RF/live claim."""
from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QMessageBox

from global_pulse import local_radio as radio


CATALOG = ({"id": "reviewed", "url": "https://reviewed.example.org/live.mp3"},)


def encoded(value):
    return json.dumps(value).encode("utf-8")


def zip_payload(**changes):
    data = {"country abbreviation": "US", "post code": "08010", "places": [{
        "latitude": "40.0", "longitude": "-75.0", "place name": "Synthetic town",
        "state abbreviation": "NJ"}]}
    data.update(changes)
    return encoded(data)


def station(index=1, **changes):
    data = {"stationuuid": str(UUID(int=index)), "countrycode": "US",
            "geo_lat": 40.0, "geo_long": -75.0, "name": "Synthetic news",
            "tags": "news,talk", "state": "New Jersey",
            "homepage": "https://station.example.org/", "url": "https://stream.example.org/live"}
    data.update(changes)
    return data


class Hook:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in list(self.callbacks):
            callback()


class Reply:
    def __init__(self, url, payload=b"", *, status=200, error=None):
        self.readyRead, self.finished = Hook(), Hook()
        self.payload = payload
        self.destination = url
        self.status = status
        self.network_error = QNetworkReply.NetworkError.NoError if error is None else error
        self.aborted = 0
        self.deleted = 0
        self.emit_abort = False

    def readAll(self):
        payload, self.payload = self.payload, b""
        return payload

    def abort(self):
        self.aborted += 1
        if self.emit_abort:
            self.finished.emit()

    def deleteLater(self):
        self.deleted += 1

    def attribute(self, attribute):
        assert attribute == QNetworkRequest.Attribute.HttpStatusCodeAttribute
        return self.status

    def error(self):
        return self.network_error

    def url(self):
        return QUrl(self.destination)


class Manager:
    def __init__(self):
        self.requests = []
        self.replies = []

    def get(self, request):
        self.requests.append(request)
        reply = Reply(request.url().toString())
        self.replies.append(reply)
        return reply


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app, monkeypatch):
    manager = Manager()
    monkeypatch.setattr(radio, "QNetworkAccessManager", lambda parent: manager)
    widget = radio.LocalRadioPanel(catalog=CATALOG)
    yield widget, manager
    widget.shutdown()
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("value", [None, 8010, "8010", "08010-1234", "٠٨٠١٠", "0801x", "08010\nX"])
def test_zip_validation_rejects_non_ascii_or_non_exact_zip(value):
    with pytest.raises(ValueError):
        radio.zip_code(value)


def test_zip_response_identity_bounds_and_country_are_required():
    assert radio.parse_zip(zip_payload(), " 08010 ")["latitude"] == 40.0
    for changes in ({"post code": "08011"}, {"country abbreviation": "CA"},
                    {"places": []}, {"places": [None]},
                    {"places": [{"latitude": True, "longitude": -75}]},
                    {"places": [{"latitude": "NaN", "longitude": -75}]},
                    {"places": [{"latitude": 91, "longitude": -75}]},
                    {"places": [{"latitude": 40, "longitude": -181}]}):
        with pytest.raises(ValueError):
            radio.parse_zip(zip_payload(**changes), "08010")


@pytest.mark.parametrize("payload", [b"\xff", b"{broken", b"[" * 2000 + b"]" * 2000,
                                      b"x" * (64 * 1024 + 1), b"null", b"[]"])
def test_zip_malformed_or_oversize_response_fails_closed(payload):
    with pytest.raises(ValueError):
        radio.parse_zip(payload, "08010")


def test_server_allowlist_and_search_query_do_not_send_zip():
    names = radio.parse_servers(encoded([
        {"name": "de2.api.radio-browser.info"}, {"name": "de2.api.radio-browser.info"},
        {"name": "radio-browser.info.attacker.example"}, {"name": "127.0.0.1"},
        {"name": "localhost"}, {"name": "de2.api.radio-browser.info@attacker.example"},
        {"name": "de2.api.radio-browser.info:443"}, None]))
    assert names == ["de2.api.radio-browser.info"]
    url = radio.station_search_url(names[0], 2)
    parsed = urlsplit(url)
    assert parsed.scheme == "https" and parsed.hostname == names[0]
    assert parse_qs(parsed.query) == {"countrycode": ["US"], "has_geo_info": ["true"],
        "hidebroken": ["true"], "order": ["name"], "limit": ["1000"], "offset": ["2000"]}
    assert "08010" not in url and "latitude" not in url and "longitude" not in url
    for server, page in (("attacker.example", 0), (names[0], -1),
                         (names[0], 8), (names[0], True), (names[0], "1")):
        with pytest.raises(ValueError):
            radio.station_search_url(server, page)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)",
    "https://127.0.0.1/live", "http://10.0.0.1/live", "https://[::1]/", "http://receiver.lan/",
    "https://user:pass@station.example.org/", "http://station.example.org:8901/", "https://localhost/",
    "https://station.example.org/\nheader"])
def test_station_link_schema_private_network_and_ports_cannot_enter_results(url):
    rows, count = radio.parse_stations(encoded([station(homepage=url, url=url, url_resolved=url)]), CATALOG)
    assert count == 1 and rows == []


def test_station_validation_identity_country_and_coordinates():
    bad = [station(2, stationuuid="not-a-uuid"), station(3, countrycode="GB"),
           station(4, geo_lat=True), station(5, geo_lat=91),
           station(6, geo_long="NaN"), station(7, geo_long=-181), None]
    rows, count = radio.parse_stations(encoded([station(), station(), *bad]), CATALOG)
    assert count == 9 and len(rows) == 1 and rows[0]["id"] == str(UUID(int=1))
    with pytest.raises(ValueError):
        radio.parse_stations(encoded([station()] * 1001), CATALOG)
    with pytest.raises(ValueError):
        radio.parse_stations(encoded({"stations": []}), CATALOG)


def test_only_exact_reviewed_stream_url_can_select_native_station():
    rows, _ = radio.parse_stations(encoded([
        station(1, homepage=CATALOG[0]["url"]),
        station(2, url=CATALOG[0]["url"] + "?unreviewed=1"),
        station(3, url_resolved=CATALOG[0]["url"]),
        station(4, url=CATALOG[0]["url"]),
    ]), CATALOG)
    assert [row["catalog_id"] for row in rows] == [None, None, "reviewed", "reviewed"]


def test_nearby_station_distance_filter_includes_state_borders_and_stable_sort():
    rows, _ = radio.parse_stations(encoded([
        station(1, name="Beta", state="Pennsylvania"),
        station(2, name="Alpha", state="New Jersey"),
        station(3, name="Far away", geo_lat=45),
    ]))
    location = radio.parse_zip(zip_payload(), "08010")
    results = radio.nearby_stations(rows, location, 25)
    assert [row["name"] for row in results] == ["Alpha", "Beta"]
    assert all(row["distance"] == 0 for row in results)
    assert [row["name"] for row in radio.nearby_stations(rows, location, 25, "PENNSYLVANIA")] == ["Beta"]
    assert 68 < radio.distance_miles(40, -75, 41, -75) < 70


def test_construction_expansion_and_refused_consent_send_no_requests(panel, monkeypatch):
    widget, manager = panel
    assert manager.requests == [] and widget.body.isHidden()
    widget.toggle.setChecked(True)
    assert manager.requests == []
    widget.zip_input.setText("08010")
    calls = []
    def refuse(*args):
        calls.append(args)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(radio.QMessageBox, "question", refuse)
    assert widget.start_lookup() is False
    assert len(calls) == 1 and calls[0][-1] == QMessageBox.StandardButton.No
    assert "not sent to Radio Browser" in calls[0][2]
    assert manager.requests == [] and widget._location is None
    widget.zip_input.setText("oops")
    assert widget.start_lookup() is False
    assert len(calls) == 1 and manager.requests == []


def test_consented_requests_use_no_redirect_or_cookies_and_have_timeout(panel, monkeypatch):
    widget, manager = panel
    monkeypatch.setattr(radio.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.zip_input.setText("08010")
    assert widget.start_lookup()
    request = manager.requests[0]
    assert request.url().toString() == radio.ZIP_BASE + "08010"
    assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute) == QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
    assert request.attribute(QNetworkRequest.Attribute.CookieLoadControlAttribute) == QNetworkRequest.LoadControl.Manual
    assert request.attribute(QNetworkRequest.Attribute.CookieSaveControlAttribute) == QNetworkRequest.LoadControl.Manual
    assert request.transferTimeout() == 15000
    assert widget.lookup.isEnabled() is False and widget.cancel.isEnabled()
    assert widget.start_lookup() is False and len(manager.requests) == 1


def deliver(manager, payload, **changes):
    reply = manager.replies[-1]
    reply.payload = payload
    for key, value in changes.items():
        setattr(reply, key, value)
    reply.finished.emit()
    return reply


def begin(panel, monkeypatch):
    widget, manager = panel
    monkeypatch.setattr(radio.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.zip_input.setText("08010")
    assert widget.start_lookup()
    deliver(manager, zip_payload())
    assert manager.requests[-1].url().toString() == radio.SERVER_DIRECTORY
    deliver(manager, encoded([{"name": "de2.api.radio-browser.info"}]))
    return widget, manager


def test_full_lookup_never_opens_browser_or_audio_and_is_memory_only(panel, monkeypatch):
    opened, selected = [], []
    monkeypatch.setattr(radio.QDesktopServices, "openUrl", lambda url: opened.append(url))
    widget, manager = begin(panel, monkeypatch)
    widget.station_selected.connect(selected.append)
    deliver(manager, encoded([station(1), station(2, url=CATALOG[0]["url"])]))
    assert len(manager.requests) == 3 and widget.results.count() == 2
    assert opened == [] and selected == [] and widget.lookup.isEnabled()
    assert "not AM/FM coverage" in widget.status.text()
    widget.results.setCurrentIndex(0)
    assert widget.use_station.isEnabled() is False and widget.select_reviewed() is False
    widget.results.setCurrentIndex(1)
    assert widget.use_station.isEnabled() and widget.select_reviewed()
    assert selected == ["reviewed"] and opened == []
    widget.shutdown()
    assert widget.results.count() == 0 and widget._rows == [] and widget._location is None
    assert widget.select_reviewed() is False and widget.start_lookup() is False


def test_bounded_pagination_deduplicates_and_reports_cap(panel, monkeypatch):
    widget, manager = begin(panel, monkeypatch)
    page = encoded([station()] * radio.PAGE_SIZE)
    for _ in range(radio.MAX_PAGES):
        deliver(manager, page)
    assert len(manager.requests) == 2 + radio.MAX_PAGES
    assert widget.results.count() == 1 and len(widget._rows) == 1
    assert "Partial directory" in widget.status.text() and "safety page limit" in widget.status.text()
    assert widget._reply is None and widget.lookup.isEnabled()


def test_cancel_disconnects_stale_callbacks_and_shutdown_blocks_new_work(panel, monkeypatch):
    widget, manager = begin(panel, monkeypatch)
    stale = manager.replies[-1]
    stale.emit_abort = True
    count = len(manager.requests)
    widget.cancel_lookup()
    stale.payload = encoded([station()])
    stale.readyRead.emit()
    stale.finished.emit()
    assert stale.aborted == 1 and len(manager.requests) == count
    assert widget._rows == [] and widget._location is None and widget.results.count() == 0
    assert widget._reply is None and "cancelled" in widget.status.text()
    widget.shutdown()
    widget._accept_payload("zip", zip_payload())
    assert len(manager.requests) == count and widget._closed


@pytest.mark.parametrize("change", [
    {"status": 302}, {"status": 429}, {"status": 200, "destination": "https://attacker.example/"},
    {"network_error": QNetworkReply.NetworkError.TimeoutError},
])
def test_provider_errors_and_redirects_stop_before_advancing(panel, monkeypatch, change):
    widget, manager = panel
    monkeypatch.setattr(radio.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.zip_input.setText("08010")
    assert widget.start_lookup()
    deliver(manager, zip_payload(), **change)
    assert len(manager.requests) == 1 and widget._reply is None
    assert widget._location is None and widget.results.count() == 0
    assert widget.lookup.isEnabled() and not widget.cancel.isEnabled()
    assert "Provider unavailable" in widget.status.text()


def test_malformed_response_after_zip_stops_and_retains_failure_on_filter(panel, monkeypatch):
    widget, manager = begin(panel, monkeypatch)
    deliver(manager, b"{not json")
    error = widget.status.text()
    widget.search.setText("news")
    assert widget.results.count() == 0
    assert widget.status.text() == error, "Changing filter must not disguise a failed lookup as zero complete matches"


def test_failed_later_page_cannot_be_presented_as_complete_results(panel, monkeypatch):
    widget, manager = begin(panel, monkeypatch)
    deliver(manager, encoded([station()] * radio.PAGE_SIZE))
    assert len(widget._rows) == 1
    deliver(manager, b"", status=429)
    assert "Provider unavailable" in widget.status.text()
    widget.radius.setCurrentIndex(2)
    assert widget.results.count() == 0 or "partial" in widget.status.text().casefold(), \
        "Later-page failure must clear results or retain an explicit partial/failure warning"


def test_byte_limit_abort_is_finite_even_if_finished_emits_synchronously(panel, monkeypatch):
    widget, manager = panel
    monkeypatch.setattr(radio.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.zip_input.setText("08010")
    assert widget.start_lookup()
    reply = manager.replies[-1]
    reply.emit_abort = True
    reply.payload = b"x" * (64 * 1024 + 1)
    reply.readyRead.emit()
    assert reply.aborted == 1 and widget._reply is None and len(manager.requests) == 1
    assert "size limit" in widget.status.text() and widget.lookup.isEnabled()


def test_external_link_requires_separate_default_no_consent_and_revalidation(panel, monkeypatch):
    widget, manager = begin(panel, monkeypatch)
    deliver(manager, encoded([station(homepage="http://station.example.org/")]))
    opened, prompts = [], []
    monkeypatch.setattr(radio.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    def refuse(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(radio.QMessageBox, "question", refuse)
    assert widget.open_selected() is False and opened == []
    assert prompts[-1][-1] == QMessageBox.StandardButton.No
    assert "unencrypted HTTP" in prompts[-1][2] and "cookies or redirect" in prompts[-1][2]
    monkeypatch.setattr(radio.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    assert widget.open_selected() and opened == ["http://station.example.org/"]
    row = widget.results.currentData()
    row["url"] = "http://127.0.0.1/"
    widget.results.setItemData(widget.results.currentIndex(), row)
    assert widget.open_selected() is False and len(opened) == 1


def test_community_url_cannot_inject_rich_text_into_browser_consent(panel, monkeypatch):
    widget, manager = begin(panel, monkeypatch)
    url = ('https://station.example.org/?x=<b>Trusted station</b>'
           '&foo=<a href="https://other.example/">Alternate</a>')
    deliver(manager, encoded([station(homepage=url)]))
    prompts, opened = [], []
    def refuse(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(radio.QMessageBox, "question", refuse)
    monkeypatch.setattr(radio.QDesktopServices, "openUrl", lambda value: opened.append(value))
    assert widget.open_selected() is False and opened == []
    assert len(prompts) == 1
    text = prompts[0][2]
    assert "<b>" not in text and "<a href=" not in text and "</a>" not in text
    assert bytes(QUrl(url).toEncoded()).decode("ascii") in text
    assert "%3Cb%3E" in text and "%3Ca%20href=%22" in text
