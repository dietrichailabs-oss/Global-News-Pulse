"""Automatic local headline presentation, separate from stored source evidence.

No model downloads, provider requests, article scraping or archive writes.
At most two automatic jobs share the existing eight-job owned worker queue.
Results are session-only, content/model keyed, and bounded to 512 entries.
"""
from __future__ import annotations
from collections import OrderedDict
import hashlib
import json
from uuid import uuid4
from PySide6.QtCore import QObject, QTimer, Signal
from .translation import language_of


class HeadlineTranslations(QObject):
    changed = Signal()
    PREFIX = "auto-headline:"
    MAX_PENDING = 2
    MAX_CACHE = 512

    def __init__(self, translator, worker, enabled, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.worker = worker
        self.enabled = enabled
        self.cache = OrderedDict()
        self.pending = {}
        self.keys = set()
        self.closed = False
        self.notify = QTimer(self)
        self.notify.setSingleShot(True)
        self.notify.setInterval(0)
        self.notify.timeout.connect(self.changed.emit)

    def _notify(self):
        if not self.closed and not self.notify.isActive():
            self.notify.start()

    @staticmethod
    def _identity(item):
        return (item.get("key"), item.get("sha256"))

    def view(self, event):
        title = str(event.get("title") or "Untitled event")
        result = {"title": title, "original": title, "state": "original", "label": "Original headline"}
        if self.closed or self.enabled() is not True:
            return result
        # Never apply an unrelated report's language to the derived event title.
        report = next((r for r in event.get("reports", []) if isinstance(r, dict)
            and r.get("title") == title and not r.get("future_dated")
            and r.get("evidence_status", "active") == "active"
            and r.get("status", "active") not in {"retracted", "cancelled"}
            and r.get("kind") not in {"retraction", "cancellation"}), None)
        if report is None:
            result["label"] = "Original · headline language unconfirmed"
            return result
        code = language_of(title, report.get("language", ""))
        if code == "en":
            result["label"] = "Original English headline"
            return result
        item = self.translator.catalog.get(code)
        if not isinstance(item, dict):
            result.update(state="unavailable", label=f"Original · no local model for {code}")
            return result
        identity = self._identity(item)
        key = hashlib.sha256(json.dumps([code, title, identity], ensure_ascii=False).encode("utf-8")).hexdigest()
        try:
            installed = self.translator.installed(code)
        except (OSError, ValueError, TypeError):
            installed = False
        if not installed:
            result.update(state="missing_model", label=f"Original · install {item.get('name', code)} model")
            return result
        if key in self.cache:
            state, translated = self.cache[key]
            self.cache.move_to_end(key)
            if state == "ready":
                result.update(title=translated, state=state, label=f"Machine translated · {code} → English · local")
            else:
                result.update(state=state, label="Original · local translation failed")
            return result
        if key in self.keys:
            result.update(state="pending", label=f"Translating {code} → English locally…")
            return result
        if len(self.pending) >= self.MAX_PENDING:
            result.update(state="waiting", label="Original · waiting for local translator")
            return result
        rid = self.PREFIX + uuid4().hex
        self.pending[rid] = (key, code, identity)
        self.keys.add(key)
        # install=False is unconditional. Missing models are a visible status,
        # never permission to download or to open a consent dialog in a loop.
        try:
            accepted = self.worker.submit(rid, code, title[:4000], False)
        except (ValueError, RuntimeError, OSError):
            accepted = False
        if not accepted:
            self.pending.pop(rid, None)
            self.keys.discard(key)
            result.update(state="waiting", label="Original · translator busy or unavailable")
        else:
            result.update(state="pending", label=f"Translating {code} → English locally…")
        return result

    def complete(self, rid, code, text, error):
        if not isinstance(rid, str) or not rid.startswith(self.PREFIX):
            # Manual/model jobs also free space or make a model available.
            self._notify()
            return False
        job = self.pending.pop(rid, None)
        if job is None:
            return True  # Cancelled/late automatic jobs must never become popups.
        key, expected_code, identity = job
        self.keys.discard(key)
        if self.closed or self.enabled() is not True:
            return True
        current = self.translator.catalog.get(expected_code)
        if not isinstance(current, dict) or self._identity(current) != identity:
            self._notify()
            return True
        good = (code == expected_code and not error and isinstance(text, str)
                and 0 < len(text.strip()) <= 4000 and "\ufffd" not in text
                and not any(ord(c) < 32 and c not in "\n\r\t" for c in text))
        # Bounded negative cache prevents failure-refresh-retry loops.
        self.cache[key] = ("ready", text.strip()) if good else ("failed", "")
        self.cache.move_to_end(key)
        while len(self.cache) > self.MAX_CACHE:
            self.cache.popitem(last=False)
        self._notify()
        return True

    def cancel_pending(self):
        identities = list(self.pending)
        self.pending.clear()
        self.keys.clear()
        for rid in identities:
            self.worker.cancel(rid)

    def close(self):
        self.closed = True
        self.notify.stop()
        self.cancel_pending()
        self.cache.clear()
