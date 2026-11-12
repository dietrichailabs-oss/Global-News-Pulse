"""Small, explicit trust boundaries for exported text and user-opened URLs."""
from __future__ import annotations

import csv
import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def event_id(value: str) -> str:
    value = str(value)
    if not EVENT_ID.fullmatch(value):
        raise ValueError("Invalid event identifier")
    return value


def safe_url(value: str, *, allow_http: bool = False) -> str:
    """Validate an external link; networking collectors perform DNS checks too."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid link")
    p = urlsplit(value.strip())
    if p.scheme.lower() not in ({"https", "http"} if allow_http else {"https"}):
        raise ValueError("Only public HTTPS links can be opened")
    if not p.hostname or p.username or p.password or "\\" in p.netloc:
        raise ValueError("Unsafe link authority")
    host = p.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".localhost", ".internal", ".lan")):
        raise ValueError("Local network links are not permitted")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private network addresses are not permitted")
    if address is None:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValueError("Invalid hostname") from error
        if "." not in ascii_host or not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}", ascii_host):
            raise ValueError("A public DNS hostname is required")
        if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", ascii_host):
            raise ValueError("Ambiguous numeric host is not permitted")
    try:
        if p.port not in (None, 443, 80 if allow_http else 443):
            raise ValueError("Nonstandard network ports are not permitted")
    except ValueError as exc:
        raise ValueError("Invalid or unsupported port") from exc
    return urlunsplit((p.scheme.lower(), p.netloc, p.path, p.query, p.fragment))


def atomic_text(path: str | Path, text: str) -> None:
    path = Path(path).expanduser().absolute()
    if path.exists() and path.is_symlink():
        raise ValueError("Export destination must not be a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".global-pulse-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def csv_cell(value) -> str:
    text = str(value if value is not None else "")
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def redact(message: str) -> str:
    message = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+", r"\1[redacted]", str(message))
    message = re.sub(r"(?i)(api[_-]?key|token|secret|authorization|password)([=:]\s*)[^\s&]+", r"\1\2[redacted]", message)
    return re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[redacted]@", message)[:1000]

