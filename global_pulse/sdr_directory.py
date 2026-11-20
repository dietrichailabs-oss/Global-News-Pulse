"""Explicit receiver links plus bounded, untrusted public SDR directory parsing.

The small curated list records individual owner-supplied/operator-documented
links. It is not an import or copy of WebSDR.org's maintained directory feed.
Neither curated records nor parsed candidates imply live reception or rights.
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
    # WebSDR's official FAQ explicitly points to HTTP www.websdr.org for its
    # live operator list. It is opened only in the external browser; in-app
    # dataset import is permission-blocked below. Never autoconnect its links.
    "websdr": "http://www.websdr.org/",
    "kiwisdr": "https://kiwisdr.com/public/",
}
# Verified November 20, 2026: WebSDR's public home is a frameset; its
# official frame loads a JSON receiver dataset whose response expressly
# requires prior permission for use in another website or automated system.
# Do not replace the broken HTML scrape with that restricted data endpoint.
# The public browser directory and owner-supplied individual links still work.
DIRECTORY_IMPORT_RESTRICTIONS = {
    "websdr": "Automatic import of WebSDR.org's maintained directory needs its operator's permission. "
              "The individually supplied links below are available without that import. "
              "Use Open directory for the provider's full live list."
}
# Individual receiver facts supplied by the owner or checked on that receiver's
# own operator page, November 20, 2026. Do not infer bounds from ham band names,
# rounded public-directory thumbnails or a different receiver at the same site.
# Numeric ranges are kHz. A listed range is not proof of current coverage/audio.
CURATED_WEBDR_RECEIVERS = (
    {
        "id": "na5b", "name": "NA5B · owner-tested link",
        "location": "Operator location not recorded",
        "url": "http://na5b.com:8901/", "ranges_khz": (),
        "bands": (),
        "provenance": "Individual link and band labels supplied by owner; numeric bounds not recorded",
        "documentation": "http://na5b.com:8901/",
    },
    {
        "id": "twente", "name": "University of Twente",
        "location": "Enschede, Netherlands",
        "url": "http://websdr.ewi.utwente.nl:8901/",
        "ranges_khz": ((0.0, 29160.0),), "bands": (),
        "provenance": "Individual link, name and 0.000–29.160 MHz range supplied by owner; not live verified",
        "documentation": "http://websdr.ewi.utwente.nl:8901/",
    },
    {
        "id": "georgia", "name": "Odlisi–Kakheti HF WebSDR",
        "location": "Odlisi, Kakheti, Georgia",
        "url": "http://sdrgeorgia.sytes.net:8902/",
        "ranges_khz": ((26976.0, 29024.0),), "bands": (),
        "provenance": "Owner-supplied link; range and location listed by NARG, checked 2026-11-20; not live verified",
        "documentation": "https://narg.ge/websdr-tbilisi/",
    },
    {
        "id": "utah1", "name": "Northern Utah #1 · Yellow",
        "location": "Corinne, Utah, USA",
        "url": "http://websdr1.sdrutah.org:8901/index1a.html",
        "ranges_khz": ((125.0,221.0),(389.0,485.0),(516.0,2564.0),
                       (1708.0,2090.0),(3366.0,4134.0),(4816.0,5584.0),
                       (6741.0,7509.0)),
        "bands": (),
        "provenance": "Individually checked Northern Utah operator table, 2026-11-20; listed windows, not live verified",
        "documentation": "https://www.sdrutah.org/info/techinfo.html",
    },
    {
        "id": "utah2", "name": "Northern Utah #2 · Green",
        "location": "Corinne, Utah, USA",
        "url": "http://websdr2.sdrutah.org:8902/index1a.html",
        "ranges_khz": ((9994.0,10186.0),(13766.0,14354.0),(18022.0,18214.0),
                       (20816.0,21584.0),(24844.0,25036.0),(27816.0,28584.0),
                       (28232.0,29768.0),(49975.0,50625.0)),
        "bands": (),
        "provenance": "Northern Utah operator table, checked 2026-11-20; 20m upper bound is printed as 14.354 MHz despite an inconsistent center/bandwidth; not live verified",
        "documentation": "https://www.sdrutah.org/info/techinfo.html",
    },
    {
        "id": "utah4", "name": "Northern Utah #4 · Magenta",
        "location": "Corinne, Utah, USA",
        "url": "http://websdr4.sdrutah.org:8904/",
        "ranges_khz": ((6741.0,7509.0),(9994.0,10186.0),(13766.0,14354.0),
                       (18022.0,18214.0),(20816.0,21584.0),(24844.0,25036.0),
                       (27816.0,28584.0),(28232.0,29768.0)),
        "bands": (),
        "provenance": "Northern Utah operator table, checked 2026-11-20; 20m upper bound is printed as 14.354 MHz despite an inconsistent center/bandwidth; not live verified",
        "documentation": "https://www.sdrutah.org/info/techinfo.html",
    },
    {
        "id": "utah5", "name": "Northern Utah #5 · Teal",
        "location": "Corinne, Utah, USA",
        "url": "http://websdr5.sdrutah.org:8905/",
        "ranges_khz": ((9994.0,10186.0),(13766.0,14354.0),(18022.0,18214.0),
                       (20816.0,21584.0),(24844.0,25036.0),(27816.0,28584.0),
                       (28232.0,29768.0)),
        "bands": (),
        "provenance": "Northern Utah operator table, checked 2026-11-20; 20m upper bound is printed as 14.354 MHz despite an inconsistent center/bandwidth; not live verified",
        "documentation": "https://www.sdrutah.org/info/techinfo.html",
    },
)
# Curating an arbitrary discovery result never grants HTTP/WebEngine admission.
# This immutable allowlist contains only the exact individually reviewed origins.
CURATED_WEBDR_HTTP_ORIGINS = frozenset({
    ("na5b.com", 8901),
    ("websdr.ewi.utwente.nl", 8901),
    ("sdrgeorgia.sytes.net", 8902),
    ("websdr1.sdrutah.org", 8901),
    ("websdr2.sdrutah.org", 8902),
    ("websdr4.sdrutah.org", 8904),
    ("websdr5.sdrutah.org", 8905),
})
_IGNORED_HOSTS = {
    "websdr.org", "www.websdr.org", "kiwisdr.com", "www.kiwisdr.com",
    "github.com", "www.github.com", "youtube.com", "www.youtube.com",
    "facebook.com", "www.facebook.com", "twitter.com", "x.com",
}


def public_receiver_url(value):
    """Validate public host URLs, even when an operator uses HTTP/custom ports.

    The separate in-app policy is HTTPS/443 plus a finite exact-origin list for
    consented legacy receivers. Validation alone never grants that exception.
    Never fetch these URLs for discovery; browsing requires explicit action.
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
        host = ascii_host
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid receiver port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid receiver port")
    netloc = f"[{host}]" if addr is not None and addr.version == 6 else host
    if port is not None:
        netloc += f":{port}"
    clean = urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))
    embedded = parts.scheme.lower() == "https" and port in (None, 443)
    return {"url": clean, "host": host, "embedded_candidate": embedded,
            "reason": ("HTTPS/443 candidate; embedded resources may still fail"
                       if embedded else "Browser only: receiver requires HTTP or custom port")}


def curated_websdr_receivers():
    """Fresh records; no network, persisted input, or directory-feed dependency."""
    result = []
    for source in CURATED_WEBDR_RECEIVERS:
        row = dict(public_receiver_url(source["url"]))
        row.update(source)
        row["bands"] = list(source["bands"])
        row["ranges_khz"] = tuple(tuple(pair) for pair in source["ranges_khz"])
        row["provider"] = "websdr"
        row["reason"] = (
            f"Operator HTTP/{urlsplit(row['url']).port}; in-app only after specific "
            "unencrypted transport consent; audio and availability unverified"
        )
        result.append(row)
    return result


def curated_receiver_for_url(value):
    """Return only built-in individual facts matching this exact public origin."""
    try:
        parsed = urlsplit(public_receiver_url(value)["url"])
    except (ValueError, TypeError):
        return None
    origin = (parsed.scheme, parsed.hostname, parsed.port)
    for row in curated_websdr_receivers():
        target = urlsplit(row["url"])
        if origin == (target.scheme, target.hostname, target.port):
            return row
    return None


def receiver_range_label(ranges):
    """Format already curated numeric bounds without claiming a station is on air."""
    return " · ".join(f"{start/1000:.3f}–{end/1000:.3f} MHz" for start, end in ranges)


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


def _operator_bands(value):
    """Only operator-supplied band labels; never fabricate numeric bounds."""
    if not isinstance(value,list):
        return []
    labels=[]
    for raw in value[:40]:
        if (not isinstance(raw,str) or not raw.strip()
                or any(ord(char)<32 for char in raw)):
            continue
        label=re.sub(r"\s+"," ",raw).strip()[:30]
        if label and label not in labels:
            labels.append(label)
        if len(labels)>=24:
            break
    return labels


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
        except (ValueError, TypeError, RecursionError):
            # A small deeply nested JSON reply can exceed Python's recursion
            # budget; it must not escape the Qt network completion callback.
            rows = []
        for row in rows[:MAX_RECEIVERS * 3]:
            if isinstance(row, dict):
                href = row.get("url") or row.get("link") or row.get("receiver_url")
                title = row.get("name") or row.get("title") or row.get("location")
                if isinstance(href, str):
                    candidates.append((href, title, _operator_bands(row.get("bands"))))
    else:
        parser = _Links()
        parser.feed(raw)
        candidates = [(href,title,[]) for href,title in parser.links[:MAX_RECEIVERS * 10]]
    results, seen = [], set()
    for href, title, bands in candidates:
        if not isinstance(href, str):
            continue
        try:
            url = urljoin(DIRECTORY_URLS[provider], href)
            info = public_receiver_url(url)
        except (ValueError, TypeError):
            # One malformed URL (including an invalid IPv6 bracket) must not
            # discard independent valid operators in the same response.
            continue
        host=info["host"]
        if (host in _IGNORED_HOSTS or host.endswith(".websdr.org")
                or (host.endswith(".kiwisdr.com")
                    and not host.endswith(".proxy.kiwisdr.com"))):
            # Kiwi publishes receiver proxy hostnames at
            # <id>.proxy.kiwisdr.com; they are real candidate receivers, not
            # directory navigation links. Transport admission is unchanged.
            continue
        if info["url"] in seen:
            continue
        seen.add(info["url"])
        label = re.sub(r"\s+", " ", str(title or "")).strip()[:110]
        info.update({"name": label or info["host"], "provider": provider,
                     "bands": bands})
        results.append(info)
        if len(results) >= MAX_RECEIVERS:
            break
    return results
