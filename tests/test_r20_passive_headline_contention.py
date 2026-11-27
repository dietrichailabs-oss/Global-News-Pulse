"""Regression for passive translation timer contention and one-pass Qt row reads."""
from types import SimpleNamespace
from unittest.mock import patch
import threading
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def test_deferred_language_timer_preserves_queue_when_archive_lock_busy(tmp_path):
    app = QApplication.instance() or QApplication([])
    ctl = Controller(tmp_path, demo=True)
    engine = ctl._headlines
    held, release = threading.Event(), threading.Event()
    worker = None
    try:
        title = "SYNTHETIC deferred routing fixture with unknown language"
        event = {"id": "test", "title": title, "reports": [
            {"title": title, "language": "und", "evidence_status": "active"}]}
        assert engine.view(event, defer_language=True)["state"] == "detecting"
        queued = list(engine.deferred)
        assert len(queued) == 1

        def hold():
            with ctl.store._lock:
                held.set()
                release.wait(5)

        worker = threading.Thread(target=hold)
        worker.start()
        assert held.wait(2)
        with patch("global_pulse.headline_translation.language_of", return_value="en") as detect:
            started = time.monotonic()
            engine._drain_deferred()
            assert time.monotonic() - started < 0.5
            assert list(engine.deferred) == queued
            assert engine.deferred_timer.interval() == 25
            assert engine.deferred_timer.isActive()
            assert not detect.called
            release.set()
            worker.join(5)
            assert not worker.is_alive()
            engine._drain_deferred()
            assert detect.call_count == 1
            assert not engine.deferred
            assert engine.deferred_timer.interval() == 1
            assert engine.view(event, defer_language=True)["label"] == "Original English headline"

        # Recheck the actual persisted setting instead of using stale consent.
        event = dict(event, title=title + " revised", reports=[
            {"title": title + " revised", "language": "und"}])
        assert engine.view(event, defer_language=True)["state"] == "detecting"
        ctl.store.set_setting("english_headlines", False)
        with patch("global_pulse.headline_translation.language_of") as detect:
            engine._drain_deferred()
            assert not detect.called
            assert not engine.deferred
            assert not engine.deferred_timer.isActive()
    finally:
        release.set()
        if worker is not None:
            worker.join(5)
        ctl.close()
        app.processEvents()


def test_passive_refresh_reads_each_row_once_and_uses_updated_selected_identity():
    class Item:
        def __init__(self, index):
            self.row = {"id": str(index), "title": f"Original {index}",
                        "_display_title": f"Original {index}",
                        "_translation_label": "Original headline",
                        "_situation_starred": index == 499}
            self.reads = 0
            self.display = self.row["title"]

        def data(self, role):
            assert role == Qt.ItemDataRole.UserRole
            self.reads += 1
            return dict(self.row)

        def text(self):
            return self.display

        def setText(self, value):
            self.display = value

        def setData(self, role, value):
            assert role == Qt.ItemDataRole.UserRole
            self.row = dict(value)

        def setToolTip(self, value):
            self.tip = value

    rows = [Item(i) for i in range(500)]
    rendered = []
    restored = []
    bar = SimpleNamespace(value=lambda: 42, setValue=restored.append)
    window = SimpleNamespace(
        feed_list=SimpleNamespace(count=lambda: len(rows), item=rows.__getitem__),
        english_headlines=SimpleNamespace(isChecked=lambda: True),
        _selected_id="499", _history_at=None,
        controller=SimpleNamespace(headline_view=lambda event, **kw: {
            "title": "Translated " + event["id"], "original": event["title"],
            "label": "Machine translated"}),
        intel_browser=SimpleNamespace(verticalScrollBar=lambda: bar),
        _render_event=lambda event, **kw: rendered.append((event, kw)),
        _selected_event=lambda: (_ for _ in ()).throw(AssertionError("unexpected Store read")),
    )
    MainWindow._refresh_translated_headlines(window)
    assert all(item.reads == 1 for item in rows)
    assert all(item.display == "Translated " + item.row["id"] for item in rows)
    assert rendered == [(rows[-1].row, {"update_media": False,
                                       "english_enabled": True, "starred_override": True})]
    assert restored == [42]


def test_real_deferred_timer_busy_then_disable_never_routes_unknown_consent(tmp_path):
    from PySide6.QtCore import QEventLoop,QTimer
    app=QApplication.instance() or QApplication([])
    ctl=Controller(tmp_path,demo=True)
    engine=ctl._headlines
    held,release,finished=threading.Event(),threading.Event(),threading.Event()
    worker=None
    timer=QTimer()
    loop=QEventLoop()
    errors=[]
    observations=[]
    try:
        title="SYNTHETIC deferred consent timer fixture"
        event={"id":"timer-test","title":title,"reports":[
            {"title":title,"language":"und","evidence_status":"active"}]}
        assert engine.view(event,defer_language=True)["state"]=="detecting"
        queued=list(engine.deferred)

        def hold():
            try:
                with ctl.store._lock:
                    held.set()
                    assert release.wait(4),"GUI observation deadline missed"
                    ctl.store.set_setting("english_headlines",False)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                finished.set()

        worker=threading.Thread(target=hold)
        worker.start()
        assert held.wait(2)
        started=time.monotonic()
        with patch("global_pulse.headline_translation.language_of",return_value="en") as detect:
            def observe():
                observations.append(time.monotonic()-started)
                if not release.is_set():
                    if (list(engine.deferred)!=queued or detect.called
                            or engine.deferred_timer.interval()!=25):
                        errors.append("busy timer consumed queue or bypassed preference")
                    release.set()
                elif finished.is_set() and not engine.deferred_timer.isActive():
                    loop.quit()
                elif time.monotonic()-started>3:
                    errors.append("timer recovery deadline missed")
                    loop.quit()
            timer.setInterval(100)
            timer.timeout.connect(observe)
            timer.start()
            QTimer.singleShot(4500,loop.quit)
            loop.exec()
            timer.stop()
            assert observations and observations[0]<0.5
            assert finished.is_set() and not errors,errors
            assert not detect.called
            assert not engine.deferred
            assert not engine.deferred_timer.isActive()
    finally:
        timer.stop()
        release.set()
        if worker is not None:
            worker.join(5)
        ctl.close()
        app.processEvents()
