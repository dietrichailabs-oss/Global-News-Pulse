"""Retain queue cancellation/original evidence with measured batch-64 UI repaints.

Offline independent-of-provider Engineering regression; PR71's separate
hosted Qt/SQLite probe demonstrated 16 vs 64 paint cost, not physical QA.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

import global_pulse.headline_translation as headline_module
from global_pulse.headline_translation import HeadlineTranslations


class InertWorker:
    def __init__(self):
        self.jobs = []

    def submit(self, *args):
        self.jobs.append(args)
        return True

    def cancel(self, *args):
        pass


def _event(i):
    title = f"SYNTHETIC German-English-mixed headline #{i} unique offline evidence"
    return {"title": title,
            "reports": [{"title": title, "language": "und",
                         "evidence_status": "active", "status": "active"}]}


def test_batch64_defers_only_unknown_and_notifies_without_per_item_paint(monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert HeadlineTranslations.DEFERRED_NOTIFY_BATCH == 64
    calls = []
    monkeypatch.setattr(headline_module, "language_of",
                        lambda title, language: calls.append((title, language)) or "en")
    worker = InertWorker()
    enabled = {"value": True}
    translator = SimpleNamespace(catalog={}, installed=lambda _: False)
    engine = HeadlineTranslations(translator, worker, lambda: enabled["value"])
    notifications = []
    engine.changed.connect(lambda: notifications.append(len(calls)))
    records = [_event(i) for i in range(130)]
    try:
        for record in records:
            preview = engine.view(record, defer_language=True)
            assert preview["title"] == record["title"]
            assert preview["state"] == "detecting"
        assert len(engine.deferred) == 130
        assert not calls and not notifications and not worker.jobs
        # Stop only the REAL timer for this deterministic manual-drain unit test;
        # PR71 separately measures the unmodified native timer through Qt.
        # Otherwise processEvents() may drain an extra item on a slow host.
        engine.deferred_timer.stop()
        # Direct bounded drain makes signal-batch semantics deterministic;
        # separate PR71 tests exercise the ACTUAL 1ms Qt timer and desktop.
        for _ in range(63):
            engine._drain_deferred()
        app.processEvents()
        assert len(calls) == 63 and not notifications
        engine._drain_deferred()
        app.processEvents()
        assert notifications == [64]
        for _ in range(64):
            engine._drain_deferred()
        app.processEvents()
        assert notifications == [64, 128]
        engine._drain_deferred()
        app.processEvents()
        assert notifications == [64, 128], "Do not repaint the entire feed for every title"
        engine._drain_deferred()
        app.processEvents()
        assert notifications == [64, 128, 130]
        assert len(engine.deferred) == 0
        assert not engine.deferred_timer.isActive()
        assert len(calls) == len(records)
        assert engine.view(records[0], defer_language=True)["state"] == "original"
        assert records[0]["reports"][0]["title"] == records[0]["title"]
        assert not worker.jobs

        # Disable/close while the next batch is pending; late events cannot
        # repopulate closed UI state or turn the power back on.
        fresh = _event(140)
        assert engine.view(fresh, defer_language=True)["state"] == "detecting"
        engine.cancel_pending()
        enabled["value"] = False
        app.processEvents()
        assert not engine.deferred
        assert engine.view(fresh, defer_language=True)["state"] == "original"
        assert notifications == [64, 128, 130]
    finally:
        engine.close()
    assert not engine.deferred and not engine.pending and not engine.language_cache
