"""Bounded, untrusted public SDR directory parsing.

Only extracts public receiver *candidates* from operator directories. It never
contacts individual receivers, infers current availability, or grants rights.
"""
from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_DIRECTORY_BYTES = 1_000_000
MAX_RECEIVERS = 400
DIRECTORY_URLS = {
    "websdr": "https://websdr.org/",
    "kiwisdr": "https://kiwisdr.com/public/",
}
_IGNORED_HOSTS = {
    "websdr.org", "www.websdr.org", "kiwisdr.com", "www.kiwisdr.com",
    "github.com", "www.github.com", "youtube.com", "www.youtube.com",
    "facebook.com", "www.facebook.com", "twitter.com", "x.com",
}


def public_receiver_url(value):
    """Validate public host URLs, even when an operator uses HTTP/custom ports.

    The separate in-app browser policy remains HTTPS/443 only. Never fetch any
    of these receiver URLs for discovery; browsing requires explicit user action.
    """
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid receiver URL")
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Public HTTP(S) receiver URL required")
    if parts.username or parts.password or "\\" in parts.netloc:
        raise ValueError("Unsafe receiver URL")
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".local", ".localhost", ".lan", ".internal", ".test", ".invalid")
    ):
        raise ValueError("Private host not accepted")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and not addr.is_global:
        raise ValueError("Non-public IP address not accepted")
    if addr is None:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid host") from exc
        if not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}",
            ascii_host,
        ):
            raise ValueError("Public DNS name required")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid receiver port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid receiver port")
    clean = urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, ""))
    embedded = parts.scheme.lower() == "https" and port in (None, 443)
    return {"url": clean, "host": host, "embedded_candidate": embedded,
            "reason": ("HTTPS/443 candidate; embedded resources may still fail"
                       if embedded else "Browser only: receiver requires HTTP or custom port")}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.current = {"href": dict(attrs).get("href", ""), "title": []}

    def handle_data(self, data):
        if self.current is not None and sum(map(len, self.current["title"])) < 240:
            self.current["title"].append(data[:240])

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            self.links.append((self.current["href"], " ".join(self.current["title"])))
            self.current = None


def _json_rows(parsed):
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("receivers", "stations", "results", "entries", "items", "data"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    return []


def parse_directory(provider, content):
    """Return bounded, deduplicated candidates from one official directory.

    A directory's HTML can change or be access-gated, so an empty result is
    honest. Do not claim that this is every operating receiver or a live status.
    """
    if provider not in DIRECTORY_URLS:
        raise ValueError("Unknown receiver directory")
    if not isinstance(content, (bytes, bytearray)) or len(content) > MAX_DIRECTORY_BYTES:
        raise ValueError("Directory reply exceeded bounded size")
    raw = bytes(content).decode("utf-8", errors="replace")
    candidates = []
    if raw.lstrip().startswith(("[", "{")):
        try:
            rows = _json_rows(json.loads(raw))
        except (ValueError, TypeError):
            rows = []
        for row in rows[:MAX_RECEIVERS * 3]:
            if isinstance(row, dict):
                href = row.get("url") or row.get("link") or row.get("receiver_url")
                title = row.get("name") or row.get("title") or row.get("location")
                if isinstance(href, str):
                    candidates.append((href, title))
    else:
        parser = _Links()
        parser.feed(raw)
        candidates = parser.links[:MAX_RECEIVERS * 10]
    results, seen = [], set()
    for href, title in candidates:
        if not isinstance(href, str):
            continue
        url = urljoin(DIRECTORY_URLS[provider], href)
        try:
            info = public_receiver_url(url)
        except ValueError:
            continue
        if info["host"] in _IGNORED_HOSTS or info["host"].endswith(
            (".websdr.org", ".kiwisdr.com")
        ):
            continue
        if info["url"] in seen:
            continue
        seen.add(info["url"])
        label = re.sub(r"\s+", " ", str(title or "")).strip()[:110]
        info.update({"name": label or info["host"], "provider": provider})
        results.append(info)
        if len(results) >= MAX_RECEIVERS:
            break
    return results
