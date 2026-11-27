"""Opt-in US ZIP discovery of Internet radio, never an RF receiver.

Radio Browser data is discovery metadata, not admission to the native decoder.
Only a byte-matching bundled station can be selected in Pulse; other stations
are opened explicitly in the user's browser. No ZIP or results are persisted.
API references: https://docs.radio-browser.info/ and https://api.zippopotam.us/.
"""
from __future__ import annotations

import json
import math
import random
import re
from urllib.parse import urlencode
from uuid import UUID

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from .security import safe_url

ZIP_BASE = "https://api.zippopotam.us/us/"
SERVER_DIRECTORY = "https://de1.api.radio-browser.info/json/servers"
PAGE_SIZE = 1000
MAX_PAGES = 8
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
MAX_RESULTS = 250
SERVER_NAME = re.compile(r"[a-z0-9-]+\.api\.radio-browser\.info\Z", re.ASCII)


def zip_code(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{5}", value.strip()):
        raise ValueError("Enter a five-digit US ZIP code.")
    return value.strip()


def _json(payload: bytes, maximum: int):
    if not isinstance(payload, bytes) or len(payload) > maximum:
        raise ValueError("The directory response exceeds the safe size limit.")
    try:
        return json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("The provider returned an unreadable directory response.") from exc


def _coordinate(value, limit: float) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing geographic coordinates.")
    number = float(value)
    if not math.isfinite(number) or abs(number) > limit:
        raise ValueError("Invalid geographic coordinates.")
    return number


def parse_zip(payload: bytes, requested: str) -> dict:
    requested = zip_code(requested)
    data = _json(payload, 64 * 1024)
    if (not isinstance(data, dict) or data.get("country abbreviation") != "US"
            or data.get("post code") != requested):
        raise ValueError("The provider did not return that US ZIP code.")
    places = data.get("places")
    if not isinstance(places, list) or not places or not isinstance(places[0], dict):
        raise ValueError("No place was found for this ZIP code.")
    place = places[0]
    try:
        return {
            "zip": requested,
            "latitude": _coordinate(place.get("latitude"), 90),
            "longitude": _coordinate(place.get("longitude"), 180),
            "name": str(place.get("place name") or requested)[:120],
            "state": str(place.get("state abbreviation") or "")[:8],
        }
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("The ZIP provider returned invalid coordinates.") from exc


def parse_servers(payload: bytes) -> list[str]:
    data = _json(payload, 128 * 1024)
    if not isinstance(data, list):
        raise ValueError("The radio service directory is unavailable.")
    names = []
    for item in data[:128]:
        name = item.get("name", "") if isinstance(item, dict) else ""
        if isinstance(name, str) and SERVER_NAME.fullmatch(name) and name not in names:
            names.append(name)
    if not names:
        raise ValueError("No validated Radio Browser service is available.")
    return names


def station_search_url(server: str, page: int) -> str:
    if (not isinstance(server, str) or not SERVER_NAME.fullmatch(server)
            or type(page) is not int or not 0 <= page < MAX_PAGES):
        raise ValueError("Invalid radio search destination or page.")
    # Distance parameters are not documented by this API. Fetch the bounded US
    # geocoded inventory and calculate distance locally, including state borders.
    query = urlencode({"countrycode": "US", "has_geo_info": "true",
                       "hidebroken": "true", "order": "name",
                       "limit": PAGE_SIZE, "offset": page * PAGE_SIZE})
    return "https://" + server + "/json/stations/search?" + query


def parse_stations(payload: bytes, catalog=()) -> tuple[list[dict], int]:
    data = _json(payload, MAX_PAGE_BYTES)
    if not isinstance(data, list) or len(data) > PAGE_SIZE:
        raise ValueError("The radio service returned an unexpected result page.")
    admitted = {item["url"]: item["id"] for item in catalog
                if isinstance(item, dict) and isinstance(item.get("url"), str)
                and isinstance(item.get("id"), str)}
    rows = []
    seen = set()
    for item in data:
        if not isinstance(item, dict) or item.get("countrycode") != "US":
            continue
        try:
            identifier = str(UUID(item.get("stationuuid", "")))
            lat = _coordinate(item.get("geo_lat"), 90)
            lon = _coordinate(item.get("geo_long"), 180)
        except (ValueError, TypeError, AttributeError, OverflowError):
            continue
        if identifier in seen:
            continue
        links = {}
        for key in ("homepage", "url_resolved", "url"):
            try:
                links[key] = safe_url(item.get(key), allow_http=True)
            except (ValueError, TypeError, UnicodeError):
                continue
        target = links.get("homepage") or links.get("url_resolved") or links.get("url")
        if not target:
            continue
        seen.add(identifier)
        native_id = next((admitted[url] for key, url in links.items()
                          if key != "homepage" and url in admitted), None)
        rows.append({
            "id": identifier, "name": str(item.get("name") or "Unnamed station")[:180],
            "tags": str(item.get("tags") or "")[:300],
            "state": str(item.get("state") or "")[:100],
            "latitude": lat, "longitude": lon, "url": target,
            "catalog_id": native_id,
        })
    return rows, len(data)


def distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    delta = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 3958.7613 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, delta))))


def nearby_stations(rows: list[dict], location: dict, radius: int, text: str = "") -> list[dict]:
    needle = text.strip().casefold()
    nearby = []
    for row in rows:
        distance = distance_miles(location["latitude"], location["longitude"],
                                  row["latitude"], row["longitude"])
        if distance > radius or (needle and needle not in
                                (row["name"] + " " + row["tags"] + " " + row["state"]).casefold()):
            continue
        nearby.append(dict(row, distance=distance))
    return sorted(nearby, key=lambda row: (row["distance"], row["name"].casefold(), row["id"]))


class LocalRadioPanel(QWidget):
    """Bounded, cancellable metadata requests; never starts audio on selection."""
    station_selected = Signal(str)

    def __init__(self, parent=None, *, catalog=()):
        super().__init__(parent)
        self.catalog = tuple(catalog)
        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._generation = 0
        self._closed = False
        self._error = ""
        self._payload = bytearray()
        self._total_bytes = 0
        self._rows = []
        self._location = None
        self._partial = False
        self._page = 0
        self._server = ""
        self._requested_zip = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QPushButton("Local stations by ZIP ▸")
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName("Show local Internet radio ZIP search")
        layout.addWidget(self.toggle)
        self.body = QWidget(self)
        layout.addWidget(self.body)
        inner = QVBoxLayout(self.body)
        inner.setContentsMargins(0, 0, 0, 0)
        self.disclosure = QLabel(
            "Internet streams, not over-air AM/FM. A PC needs tuner/SDR hardware for RF. "
            "Lookup sends your ZIP to Zippopotam.us; Radio Browser receives a US-station request "
            "and your IP, not your ZIP. No automatic location lookup; ZIP is not saved."
        )
        self.disclosure.setTextFormat(Qt.TextFormat.PlainText)
        self.disclosure.setWordWrap(True)
        inner.addWidget(self.disclosure)
        controls = QHBoxLayout()
        self.zip_input = QLineEdit()
        self.zip_input.setPlaceholderText("US ZIP code")
        self.zip_input.setMaxLength(5)
        self.zip_input.setMaximumWidth(130)
        self.zip_input.setAccessibleName("Five-digit US ZIP for local Internet stations")
        self.radius = QComboBox()
        for value in (25, 50, 100):
            self.radius.addItem(f"Within {value} miles", value)
        self.radius.setCurrentIndex(1)
        self.lookup = QPushButton("Find local stations")
        self.cancel = QPushButton("Cancel lookup")
        self.cancel.setEnabled(False)
        for control in (self.zip_input, self.radius, self.lookup, self.cancel):
            controls.addWidget(control)
        inner.addLayout(controls)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter station name, music, news, genre…")
        self.search.setAccessibleName("Filter discovered local stations")
        inner.addWidget(self.search)
        self.results = QComboBox()
        self.results.setAccessibleName("Nearby Internet station discovery results")
        self.results.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.results.setMinimumContentsLength(20)
        inner.addWidget(self.results)
        row = QHBoxLayout()
        self.open_station = QPushButton("Open station in browser")
        self.use_station = QPushButton("Select reviewed station in Pulse")
        row.addWidget(self.open_station)
        row.addWidget(self.use_station)
        inner.addLayout(row)
        self.status = QLabel("Enter a ZIP and choose Find. Community metadata is not verified reception or coverage.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        inner.addWidget(self.status)
        self.body.hide()
        self.toggle.toggled.connect(self._expanded)
        self.lookup.clicked.connect(self.start_lookup)
        self.zip_input.returnPressed.connect(self.start_lookup)
        self.cancel.clicked.connect(self.cancel_lookup)
        self.search.textChanged.connect(self._show_results)
        self.radius.currentIndexChanged.connect(self._show_results)
        self.results.currentIndexChanged.connect(self._selection_changed)
        self.open_station.clicked.connect(self.open_selected)
        self.use_station.clicked.connect(self.select_reviewed)
        self._selection_changed()

    def _expanded(self, expanded):
        self.body.setVisible(expanded)
        self.toggle.setText("Local stations by ZIP ▾" if expanded else "Local stations by ZIP ▸")

    def start_lookup(self):
        if self._closed or self._reply is not None:
            return False
        try:
            requested = zip_code(self.zip_input.text())
        except ValueError as exc:
            self.status.setText(str(exc))
            return False
        if QMessageBox.question(
            self, "Find local Internet radio?",
            "Send this ZIP to Zippopotam.us to find its approximate center, then retrieve "
            "community station metadata from Radio Browser? Both providers receive your IP. "
            "Your ZIP is not sent to Radio Browser or saved. This does not tune an RF receiver "
            "or start any audio.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return False
        self._requested_zip = requested
        self._rows = []
        self._location = None
        self._partial = False
        self._page = 0
        self._total_bytes = 0
        self.results.clear()
        self.lookup.setEnabled(False)
        self.cancel.setEnabled(True)
        self.status.setText("Looking up ZIP location…")
        self._request(ZIP_BASE + requested, "zip", 64 * 1024)
        return True

    def _request(self, url, stage, maximum):
        if self._closed:
            return
        self._payload = bytearray()
        self._error = ""
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", b"GlobalPulse/0.1.1 (local Internet radio discovery)")
        request.setRawHeader(b"Accept", b"application/json")
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,
                             QNetworkRequest.LoadControl.Manual)
        request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute,
                             QNetworkRequest.LoadControl.Manual)
        request.setTransferTimeout(15000)
        reply = self._manager.get(request)
        self._reply = reply
        generation = self._generation
        reply.readyRead.connect(lambda: self._read(reply, generation, maximum))
        reply.finished.connect(lambda: self._finished(reply, generation, stage, url, maximum))

    def _read(self, reply, generation, maximum):
        if (reply is not self._reply or generation != self._generation
                or self._closed or self._error):
            return
        chunk = bytes(reply.readAll())
        self._total_bytes += len(chunk)
        if len(self._payload) + len(chunk) > maximum or self._total_bytes > MAX_TOTAL_BYTES:
            self._error = "Directory size limit reached; lookup stopped without opening a station."
            reply.abort()
            return
        self._payload.extend(chunk)

    def _finished(self, reply, generation, stage, requested_url, maximum):
        if reply is not self._reply or generation != self._generation or self._closed:
            reply.deleteLater()
            return
        self._read(reply, generation, maximum)
        if reply is not self._reply:  # An abort may deliver a nested finished signal.
            return
        self._reply = None
        payload = bytes(self._payload)
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        ok = (not self._error and reply.error() == QNetworkReply.NetworkError.NoError
              and status == 200 and reply.url().toString() == requested_url)
        reply.deleteLater()
        if not ok:
            self._failed(self._error or
                         "Provider unavailable, denied, rate-limited or redirected. No station was opened. Try later.")
            return
        try:
            self._accept_payload(stage, payload)
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            self._failed(str(exc)[:300])

    def _accept_payload(self, stage, payload):
        if self._closed:
            return
        if stage == "zip":
            self._location = parse_zip(payload, self._requested_zip)
            self.status.setText("Finding an available Radio Browser directory service…")
            self._request(SERVER_DIRECTORY, "servers", 128 * 1024)
        elif stage == "servers":
            self._server = random.choice(parse_servers(payload))
            self.status.setText("Loading bounded US station metadata; no audio connection…")
            self._request(station_search_url(self._server, self._page), "stations", MAX_PAGE_BYTES)
        elif stage == "stations":
            rows, received = parse_stations(payload, self.catalog)
            prior = {row["id"] for row in self._rows}
            self._rows.extend(row for row in rows if row["id"] not in prior)
            if received == PAGE_SIZE and self._page + 1 < MAX_PAGES:
                self._page += 1
                self.status.setText(f"Loading station metadata page {self._page + 1}…")
                self._request(station_search_url(self._server, self._page), "stations", MAX_PAGE_BYTES)
                return
            self._partial = received == PAGE_SIZE
            self.lookup.setEnabled(True)
            self.cancel.setEnabled(False)
            self._show_results()
        else:
            raise ValueError("Unexpected radio lookup stage.")

    def _failed(self, message):
        # A later-page failure invalidates the lookup as a whole. Retaining its
        # location/rows would let a filter change hide the error and present an
        # incomplete directory as a successful result.
        self._rows = []
        self._location = None
        self._partial = False
        self.results.clear()
        self._selection_changed()
        self.lookup.setEnabled(not self._closed)
        self.cancel.setEnabled(False)
        self.status.setText(message)

    def cancel_lookup(self):
        self._generation += 1
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        self._payload = bytearray()
        self._rows = []
        self._location = None
        self.results.clear()
        self._failed("Lookup cancelled. No station was opened and no ZIP was saved.")

    def _show_results(self, *_):
        if self._location is None or self._reply is not None:
            return
        rows = nearby_stations(self._rows, self._location, self.radius.currentData(), self.search.text())
        self.results.clear()
        for row in rows[:MAX_RESULTS]:
            self.results.addItem(f"{row['name']} · about {row['distance']:.0f} mi", row)
        shown = min(len(rows), MAX_RESULTS)
        self.status.setText(
            f"{shown} of {len(rows)} matching stations near {self._location['name']}, "
            f"{self._location['state']}. "
            + ("Partial directory: safety page limit reached. " if self._partial else "")
            + "Only community entries with coordinates are included; ZIP-center distances are approximate, "
            "not AM/FM coverage. Unreviewed streams open in your browser, not Pulse's native player."
        )
        self._selection_changed()

    def _selection_changed(self, *_):
        row = self.results.currentData()
        self.open_station.setEnabled(isinstance(row, dict))
        self.use_station.setEnabled(isinstance(row, dict) and row.get("catalog_id") in
                                    {item.get("id") for item in self.catalog})

    def open_selected(self):
        row = self.results.currentData()
        if self._closed or not isinstance(row, dict):
            return False
        try:
            url = safe_url(row.get("url"), allow_http=True)
        except (ValueError, TypeError, UnicodeError):
            self.status.setText("This station does not have a safe public website link.")
            return False
        # QMessageBox.question uses AutoText; percent-encode untrusted URL
        # delimiters so directory metadata cannot inject rich-text markup into
        # the consent dialog. Navigation still uses the validated URL below.
        display_url = bytes(QUrl(url).toEncoded()).decode("ascii")
        note = "This link uses unencrypted HTTP. " if url.startswith("http:") else ""
        if QMessageBox.question(
            self, "Open discovered station?",
            note + "Open this community-provided link in your default browser? The website receives "
            "your IP; it may use cookies or redirect. Listing does not verify playback or publisher rights.\n\n" + display_url,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return False
        return bool(QDesktopServices.openUrl(QUrl(url)))

    def select_reviewed(self):
        row = self.results.currentData()
        if self._closed or not isinstance(row, dict):
            return False
        identifier = row.get("catalog_id")
        if identifier not in {item.get("id") for item in self.catalog}:
            return False
        self.station_selected.emit(identifier)
        return True

    def shutdown(self):
        self._closed = True
        self.cancel_lookup()
