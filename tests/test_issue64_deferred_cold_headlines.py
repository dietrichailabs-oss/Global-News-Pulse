"""Cold headline-language routing must yield to Qt without losing source evidence.

Engineering-only, offline synthetic records. This does not certify physical
Windows 11 playback, native shutdown stability or publisher language coverage.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import global_pulse.headline_translation as headline_module
from global_pulse.headline_translation import HeadlineTranslations
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


class InertWorker:
    def __init__(self):
        self.jobs = []

    def submit(self, *args):
        self.jobs.append(args)
        return True

    def cancel(self, *args):
        pass


def _event(title, language="und"):
    return {
        "title": title, "id": "synthetic-identity",
        "reports": [{"title": title, "language": language, "evidence_status": "active"}],
    }


def _archive(size):
    now = datetime.now(timezone.utc).isoformat()
    categories = ("Disaster", "Conflict", "Unrest", "Health", "Government",
                  "Economy", "Humanitarian", "Infrastructure", "News")
    return [
        {"id": f"deferred-synthetic-{i}", "event_key": f"deferred-synthetic:{i}",
         "title": f"SYNTHETIC UI profile {categories[i % len(categories)]} #{i}",
         "summary": "Fictional source evidence, no real-world event",
         "source_id": "offline-cold-profile", "publisher": "Synthetic Publisher",
         "url": f"https://example.invalid/deferred/{i}",
         "published_at": now, "retrieved_at": now,
         "country": "", "region": "Global", "category": categories[i % len(categories)],
         "synthetic": True, "severity": "unassessed"}
        for i in range(size)
    ]


def test_deferred_routing_preserves_unknown_and_checks_model_after_detection(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    worker = InertWorker()
    enabled = {"value": True}
    installed = {"value": False}
    translator = SimpleNamespace(
        catalog={"de": {"key": "test-pinned", "name": "German", "sha256": "a" * 64}},
        installed=lambda _: installed["value"],
    )
    engine = HeadlineTranslations(translator, worker, lambda: enabled["value"])
    title = "SYNTHETIC untrusted headline of sufficient length for inference"
    monkeypatch.setattr(headline_module, "language_of", lambda text, declared: calls.append((text, declared)) or "de")
    source = _event(title)
    try:
        initial = engine.view(source, defer_language=True)
        assert initial["state"] == "detecting"
        assert initial["title"] == initial["original"] == title
        assert "locally" in initial["label"]
        assert not calls and not worker.jobs
        for _ in range(120):
            app.processEvents()
            QTest.qWait(2)
            if not engine.deferred:
                break
        assert not engine.deferred and calls == [(title, "und")]
        missing = engine.view(source, defer_language=True)
        assert missing["state"] == "missing_model"
        assert "install German model" in missing["label"]
        assert missing["original"] == title
        installed["value"] = True
        pending = engine.view(source, defer_language=True)
        assert pending["state"] == "pending"
        assert worker.jobs and worker.jobs[0][-1] is False
        assert calls == [(title, "und")], "Live model status must not recompute cached language"
        assert source["reports"][0]["title"] == title
        new_title = title + " corrected"
        assert engine.view(_event(new_title), defer_language=True)["state"] == "detecting"
        enabled["value"] = False
        app.processEvents()
        QTest.qWait(5)
        assert not engine.deferred
        assert engine.view(_event(new_title), defer_language=True)["state"] == "original"
    finally:
        engine.close()
    assert not engine.language_cache and not engine.deferred and not engine.deferred_timer.isActive()


def test_large_cold_feed_is_interactive_before_bulk_language_detection(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    calls = []
    try:
        controller.store.ingest(_archive(820))
        def count_language(title, declared):
            calls.append(title)
            return "und"
        with patch.object(headline_module, "language_of", count_language):
            window = MainWindow(controller)
            window.show()
            app.processEvents()
            assert len(window._events) == 500
            assert len(calls) < 12, "Cold Qt construction cannot synchronously classify 500 titles"
            assert controller._headlines.deferred, "Bulk feed detection must be queued"
            assert "World intelligence overview" in window.overview_browser.toPlainText()
            assert "Health & disease" in window.overview_browser.toPlainText()
            assert any("identifying headline language" in
                       str(window.feed_list.item(i).data(0x0100).get("_translation_label", ""))
                       for i in range(min(20, window.feed_list.count())))
            record = window._events[0]
            selected = str(record["id"])
            window.navigate_event(selected)
            assert window._selected_id == selected
            assert record["title"] in window.intel_browser.toPlainText()
            assert window.intelligence_mode.currentIndex() == 1
            assert window.save_button.property("event_id") == selected
            window.save_button.click()
            assert controller.store.situation_state(selected)["saved"]
            window.open_page(1)
            window.open_page(0)
            assert window._selected_id == selected
            assert not window.media.auto_cameras and window.media.camera.camera is None
            for _ in range(12):
                app.processEvents()
                QTest.qWait(3)
            assert len(calls) >= 2, "Deferred timer must really progress on the Qt event loop"
            assert "Could not update view" not in window.status_label.text()
            assert len(controller._headlines.deferred) <= controller._headlines.MAX_DEFERRED
    finally:
        if window is not None:
            window._force_close = True
            window.media.shutdown()
            window.close()
        controller.close()
        if window is not None:
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
