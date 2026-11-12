"""Real Television widget/deadline/Stop path with an inert WebEngine-view spy.

No network, real WebEngine, or live video. A withheld callback models the
boundary that must not disable the independently checked inactivity deadline.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import socket
import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.single_media import Television


class SilentView:
    def __init__(self):
        self.stops = 0
        self.urls = []
        self.hidden = False
        self.queries = []
    def page(self): return self
    def runJavaScript(self, script, callback):
        self.queries.append((script, callback))  # Deliberately no callback.
    def stop(self): self.stops += 1
    def setUrl(self, url): self.urls.append(url.toString())
    def hide(self): self.hidden = True


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tv(app, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('TV deadline regression must not access the network')
    monkeypatch.setattr(socket, 'getaddrinfo', denied)
    monkeypatch.setattr(socket.socket, 'connect', denied)
    widget = Television()
    widget.view = SilentView()
    widget._requested = True
    widget._progress_at = 100.0
    widget._poll_timer.start()
    yield widget
    widget.stop()
    widget.view = None
    widget.deleteLater()
    app.processEvents()


def assert_stopped(widget):
    assert widget._requested is False
    assert widget._poll_pending is False
    assert not widget._poll_timer.isActive()
    assert widget.view.stops == 1
    assert widget.view.urls == ['about:blank']
    assert widget.view.hidden is True
    assert widget.tv_status.text() == 'ERROR'
    assert 'Connection stopped' in widget.note.text()


def test_pending_callback_cannot_disable_timeout(tv, monkeypatch):
    tv._poll_pending = True
    generation = tv._generation
    monkeypatch.setattr('global_pulse.single_media.time.monotonic', lambda: 146.0)
    tv._poll()
    assert_stopped(tv)
    assert not tv.view.queries
    tv._observed(generation, {'time': 99.0, 'paused': False, 'ready': 4})
    assert tv.tv_status.text() == 'ERROR' and tv._requested is False


def test_nonpending_timeout_preserves_existing_stop_behavior(tv, monkeypatch):
    tv._poll_pending = False
    monkeypatch.setattr('global_pulse.single_media.time.monotonic', lambda: 146.0)
    tv._poll()
    assert_stopped(tv)
    assert not tv.view.queries


def test_pending_callback_before_deadline_does_not_queue_another_query(tv, monkeypatch):
    tv._poll_pending = True
    monkeypatch.setattr('global_pulse.single_media.time.monotonic', lambda: 120.0)
    tv._poll()
    assert tv._requested is True and tv._poll_pending is True
    assert tv._poll_timer.isActive()
    assert tv.view.stops == 0 and not tv.view.urls and not tv.view.queries
