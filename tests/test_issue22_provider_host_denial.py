"""Issue #22: denied / 503 provider replies impose a finite shared host circuit.

Offline-only: MockTransport, no real source contact or rights inference.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from global_pulse.sources import Collector, Scheduler, iso

NOW = datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc)


def source(source_id="a", host="news.example.org"):
    return {
        "id": source_id, "name": source_id, "url": f"https://{host}/rss",
        "allowed_domains": [host], "adapter": "rss",
        "enabled": True, "access_status": "reviewed_public",
        "min_interval": 300,
    }


def mock_client(status, headers=None):
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(status, headers=headers or {}, request=request)

    def client_factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return client_factory, seen


@pytest.mark.parametrize("status,expected", [
    (401, "denied"), (403, "denied"), (503, "unavailable"), (429, "rate_limited"),
])
def test_denial_status_has_finite_persisted_retry_and_no_content(status, expected):
    factory, seen = mock_client(status, {"Retry-After": "7200"})
    result = Collector(source(), client_factory=factory, now=lambda: NOW).collect({})
    state = result["state"]
    assert len(seen) == 1
    assert result["reports"] == [] and result["observations"] == []
    assert state["status"] == expected
    assert state["http_status"] == status
    assert state["retry_after_seconds"] >= (86400 if status in {401, 403} else 7200)
    assert state["next_poll"] == iso(NOW + timedelta(seconds=state["retry_after_seconds"]))
    assert state["last_failure"] == iso(NOW)
    assert state.get("last_success") is None
    assert "http" not in state["error"].lower() or f"http {status}" in state["error"].lower()
    assert "https://" not in state["error"]


class FakeStore:
    def __init__(self, states):
        self.states = states

    def get_source_state(self, source_id):
        return dict(self.states.get(source_id, {}))


@pytest.mark.parametrize("status", ["denied", "unavailable", "rate_limited"])
def test_same_host_hold_survives_new_scheduler_instance(status):
    from global_pulse.sources import timestamp
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    provider = source("provider")
    sibling = source("sibling")
    store = FakeStore({"provider": {
        "status": status, "http_status": {"denied": 403, "unavailable": 503,
                                           "rate_limited": 429}[status],
        "retry_after_seconds": 7200, "next_poll": iso(future),
    }})
    for _ in range(2):  # separate Scheduler instance models restart
        scheduler = Scheduler(store, lambda reports: None)
        scheduler.sources = [provider, sibling]
        scheduler._tick()
        assert not scheduler._workers, "same-host sibling must not bypass persisted Retry-After"
        host_due = scheduler._host_next["news.example.org"]
        assert host_due > __import__("time").monotonic() + 600
    assert timestamp(store.get_source_state("provider")["next_poll"]) > datetime.now(timezone.utc).timestamp()


def test_denial_without_header_is_bounded_not_a_hot_loop():
    factory, seen = mock_client(403)
    state = Collector(source(), client_factory=factory, now=lambda: NOW).collect({})["state"]
    assert len(seen) == 1
    assert state["status"] == "denied"
    assert state["retry_after_seconds"] == 86400
    assert state["next_poll"] == iso(NOW + timedelta(days=1))
