"""Issue64: Daily/Weekly are category-balanced across the stored period, not
just the first 500 chronological events. All fixtures are synthetic and local.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtWidgets import QApplication

from global_pulse.brief_selection import balanced_brief_sections
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def record(i, category, at):
    return {
        "id": f"brief-archive-{i}",
        "event_key": f"brief-archive:{i}",
        "source_id": "qa-brief-archive-synthetic",
        "publisher": "Synthetic QA Publication",
        "title": f"SYNTHETIC {category} source report {i}",
        "summary": "Synthetic local source evidence only",
        "url": f"https://example.org/brief-archive/{i}",
        "category": category,
        "severity": "unassessed",
        "region": "Global",
        "country": "",
        "published_at": at,
        "retrieved_at": at,
        "synthetic": True,
    }


def test_period_sampler_and_daily_weekly_export_survive_501_newer_weather(tmp_path):
    ctrl = Controller(tmp_path, demo=True)
    try:
        now = datetime.now(timezone.utc)
        before = (now - timedelta(hours=3)).isoformat()
        recent = (now - timedelta(minutes=5)).isoformat()
        ctrl.store.ingest([record(900, "Health", before)], now=before)
        ctrl.store.ingest([record(i, "Disaster", recent) for i in range(501)], now=recent)
        since = (now - timedelta(days=1)).isoformat()
        assert all(e["category"] == "Disaster"
                   for e in ctrl.events(since=since, limit=500))
        for period, expected in (("daily", 8), ("weekly", 9)):
            events = ctrl.brief_events(since=since, period=period)
            assert len(events) <= 2 * expected
            assert any(e["category"] == "Health" for e in events)
            assert sum(e["category"] == "Disaster" for e in events) <= expected
            out = tmp_path / f"{period}.md"
            ctrl.export_brief(out, period)
            page = out.read_text(encoding="utf-8")
            assert "## Health & disease" in page
            assert "SYNTHETIC Health source report 900" in page
            # A titled source is repeated in its evidence trail; cap rendered
            # briefing story headings rather than raw full-text occurrences.
            assert sum("SYNTHETIC Disaster source report" in line
                       for line in page.splitlines() if line.startswith("### ")) <= 6
    finally:
        ctrl.close()


def test_off_period_records_are_not_mislabeled_current(tmp_path):
    ctrl = Controller(tmp_path, demo=True)
    try:
        now = datetime.now(timezone.utc)
        past = (now - timedelta(days=9)).isoformat()
        ctrl.store.ingest([record(901, "Health", past)], now=past)
        results = ctrl.brief_events(since=(now - timedelta(days=7)).isoformat(), period="weekly")
        assert not any(e["category"] == "Health" for e in results)
    finally:
        ctrl.close()


def test_daily_owner_depth_uses_eight_real_stored_nonweather_records(tmp_path):
    app = QApplication.instance() or QApplication([])
    ctrl = Controller(tmp_path, demo=True)
    try:
        now = datetime.now(timezone.utc)
        at = (now - timedelta(minutes=2)).isoformat()
        ctrl.store.ingest([record(1200 + i, "Government", at) for i in range(12)], now=at)
        events = ctrl.brief_events(since=(now - timedelta(days=1)).isoformat(), period="daily")
        assert len(events) == 8
        assert all(e["category"] == "Government" for e in events)
        out = tmp_path / "daily-depth.md"
        ctrl.export_brief(out, "daily")
        page = out.read_text(encoding="utf-8")
        assert sum(line.startswith("### ") and "SYNTHETIC Government source report" in line
                   for line in page.splitlines()) == 8
        assert "rolling last 24 hours" in page
        assert "UNASSESSED means" in page
        assert "0 official measurement(s)" in page
        assert "8 unverified record(s)" in page
    finally:
        ctrl.close()
        app.processEvents()


def test_qt_briefs_tab_uses_period_category_sample(tmp_path):
    app = QApplication.instance() or QApplication([])
    ctrl = Controller(tmp_path, demo=True)
    window = None
    try:
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=2)).isoformat()
        new = (now - timedelta(minutes=4)).isoformat()
        ctrl.store.ingest([record(999, "Conflict", old)], now=old)
        ctrl.store.ingest([record(i, "Disaster", new) for i in range(501)], now=new)
        window = MainWindow(ctrl)
        window.show()
        app.processEvents()
        window.brief_period.setCurrentIndex(0)
        window._generate_brief()
        rendered = window.brief_browser.toPlainText()
        assert "SYNTHETIC Conflict source report 999" in rendered
        assert "SYNTHETIC Disaster source report" in rendered
    finally:
        if window is not None:
            from PySide6.QtCore import QCoreApplication, QEvent
            window._force_close = True
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        ctrl.close()
