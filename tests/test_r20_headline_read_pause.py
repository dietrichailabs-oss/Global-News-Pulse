"""Owned archive-read pause: retain queued headline routing without busy polling."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import threading

from PySide6.QtWidgets import QApplication
from global_pulse.headline_translation import HeadlineTranslations
from test_warmed_category_filter import desktop, pump


def event(title):
    return {"title": title, "reports": [
        {"title": title, "language": "und", "evidence_status": "active"}]}


def test_overlapping_read_pauses_preserve_queue_and_recheck_live_consent():
    app=QApplication.instance() or QApplication([])
    enabled=Mock(return_value=True)
    engine=HeadlineTranslations(SimpleNamespace(catalog={}), Mock(), enabled)
    try:
        first=event("SYNTHETIC unknown headline one")
        second=event("SYNTHETIC unknown headline two")
        assert engine.view(first,defer_language=True)["state"]=="detecting"
        engine.set_deferred_pause("evidence",True)
        engine.set_deferred_pause("brief",True)
        assert engine.view(second,defer_language=True)["state"]=="detecting"
        queued=list(engine.deferred)
        assert len(queued)==2 and not engine.deferred_timer.isActive()
        enabled.reset_mock()
        with patch("global_pulse.headline_translation.language_of",return_value="en") as detect:
            engine._drain_deferred()
            engine.set_deferred_pause("evidence",False)
            engine._drain_deferred()
            enabled.assert_not_called()
            detect.assert_not_called()
            assert list(engine.deferred)==queued
            assert not engine.deferred_timer.isActive()
            engine.set_deferred_pause("brief",False)
            assert engine.deferred_timer.isActive()
            engine._drain_deferred()
            assert detect.call_count==1 and len(engine.deferred)==1
            # A preference change during a pause must not be bypassed.
            engine.set_deferred_pause("evidence",True)
            enabled.return_value=False
            engine.set_deferred_pause("evidence",False)
            engine._drain_deferred()
            assert detect.call_count==1 and not engine.deferred
            assert not engine.deferred_timer.isActive()
        enabled.return_value=True
        engine.set_deferred_pause("brief",True)
        engine.view(second,defer_language=True)
        engine.cancel_pending()
        engine.set_deferred_pause("brief",False)
        assert not engine.deferred and not engine.deferred_timer.isActive()
        engine.close()
        engine.set_deferred_pause("evidence",False)
        assert not engine.deferred_timer.isActive()
    finally:
        engine.close()
        app.processEvents()


def test_real_filter_worker_pauses_routing_and_resumes_on_error_and_retry(desktop,monkeypatch):
    app,w,ctl=desktop
    engine=ctl._headlines
    original=ctl.events
    entered,release=threading.Event(),threading.Event()
    fail=[True]

    def controlled(**filters):
        if fail[0]:
            fail[0]=False
            entered.set()
            if not release.wait(5):
                raise RuntimeError("offline gate expired")
            raise RuntimeError("offline intentional read error")
        return original(**filters)

    monkeypatch.setattr(ctl,"events",controlled)
    try:
        marker=event("SYNTHETIC queued headline during archive read")
        assert engine.view(marker,defer_language=True)["state"]=="detecting"
        w.category.setCurrentIndex(w.category.findData("Health"))
        w._start_filter_refresh()
        assert entered.wait(2)
        assert w._idle_snapshot_inflight
        assert "evidence" in engine._deferred_pause_reasons
        assert not engine.deferred_timer.isActive()
        queued=list(engine.deferred)
        with patch.object(engine,"enabled",side_effect=AssertionError("paused timer queried preference")):
            engine._drain_deferred()
            assert list(engine.deferred)==queued
        release.set()
        assert pump(app,lambda:not w._idle_snapshot_inflight)
        assert "evidence" not in engine._deferred_pause_reasons
        assert w._filter_refresh_pending and not w.world_map.isEnabled()
        assert "Filter read failed" in w.status_label.text()
        w.category.setCurrentIndex(w.category.findData("Disaster"))
        assert pump(app,lambda:not w._filter_refresh_pending)
        assert not engine._deferred_pause_reasons
        assert w.world_map.isEnabled()
        assert w._events and all(e["category"]=="Disaster" for e in w._events)
    finally:
        release.set()
