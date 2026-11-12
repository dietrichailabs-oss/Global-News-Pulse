"""Issue #22 QA109 correction: corrupt persisted provider host holds fail closed.

Offline only. No provider contact.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from global_pulse.sources import Scheduler, iso


def source(source_id="provider", host="news.example.org"):
    return {
        "id": source_id,
        "name": source_id,
        "url": f"https://{host}/rss",
        "allowed_domains": [host],
        "adapter": "rss",
        "enabled": True,
        "access_status": "reviewed_public",
        "min_interval": 300,
    }


class FakeStore:
    def __init__(self, states):
        self.states = {k: dict(v) for k, v in states.items()}

    def get_source_state(self, source_id):
        return dict(self.states.get(source_id, {}))

    def set_source_state(self, source_id, state):
        self.states[source_id] = dict(state)


class NoNetworkCollector:
    def __init__(self, source):
        self.source = source

    def collect(self, state):
        return {
            "state": dict(state),
            "reports": [],
            "observations": [],
        }


@pytest.mark.parametrize(
    "status,http_status,retry_seconds,minimum_remaining",
    [
        ("denied", 403, 7200, 23 * 3600),
        ("unavailable", 503, 7200, 90 * 60),
        ("rate_limited", 429, 7200, 90 * 60),
    ],
)
def test_malformed_next_poll_reconstructs_host_hold_after_restart(
    status, http_status, retry_seconds, minimum_remaining
):
    failed_at = datetime.now(timezone.utc)
    provider = source("provider")
    sibling = source("sibling")
    store = FakeStore(
        {
            "provider": {
                "status": status,
                "http_status": http_status,
                "last_failure": iso(failed_at),
                "retry_after_seconds": retry_seconds,
                "next_poll": "definitely-not-a-date",
            }
        }
    )

    scheduler = Scheduler(store, lambda reports: None, collector_factory=NoNetworkCollector)
    scheduler.sources = [provider, sibling]
    scheduler._tick()

    assert not scheduler._workers
    host_due = scheduler._host_next["news.example.org"]
    assert host_due > time.monotonic() + minimum_remaining


def test_corrupt_provider_hold_does_not_block_unrelated_host():
    failed_at = datetime.now(timezone.utc)
    provider = source("provider", "news.example.org")
    sibling = source("sibling", "news.example.org")
    unrelated = source("other", "other.example.net")
    store = FakeStore(
        {
            "provider": {
                "status": "denied",
                "http_status": 403,
                "last_failure": iso(failed_at),
                "retry_after_seconds": 86400,
                "next_poll": "bad-date",
            }
        }
    )
    scheduler = Scheduler(store, lambda reports: None, collector_factory=NoNetworkCollector)
    scheduler.sources = [provider, sibling, unrelated]
    scheduler._tick()

    assert "provider" not in scheduler._workers
    assert "sibling" not in scheduler._workers
    assert "other" in scheduler._workers


def test_malformed_failure_time_uses_one_bounded_non_sliding_fallback():
    provider = source("provider")
    sibling = source("sibling")
    store = FakeStore(
        {
            "provider": {
                "status": "unavailable",
                "http_status": 503,
                "last_failure": "also-not-a-date",
                "retry_after_seconds": 1800,
                "next_poll": "not-a-date",
            }
        }
    )
    scheduler = Scheduler(store, lambda reports: None, collector_factory=NoNetworkCollector)
    scheduler.sources = [provider, sibling]

    scheduler._tick()
    first_due = scheduler._host_next["news.example.org"]
    assert first_due > time.monotonic() + 1200

    scheduler._tick()
    second_due = scheduler._host_next["news.example.org"]
    assert abs(second_due - first_due) < 2.0
    assert not scheduler._workers


def test_corrupt_reconstruction_clamps_untrusted_retry_without_truncating_valid_absolute_due():
    provider = source("provider")
    scheduler = Scheduler(FakeStore({}), lambda reports: None, collector_factory=NoNetworkCollector)
    now = time.time()

    malformed = {
        "status": "rate_limited",
        "last_failure": iso(datetime.now(timezone.utc)),
        "retry_after_seconds": 10**12,
        "next_poll": "bad",
    }
    due = scheduler._persisted_host_due(provider, malformed, now)
    assert due <= now + 30 * 86400 + 5

    valid_absolute = datetime.now(timezone.utc) + timedelta(days=45)
    valid = dict(malformed, next_poll=iso(valid_absolute))
    absolute_due = scheduler._persisted_host_due(provider, valid, now)
    assert absolute_due > now + 44 * 86400
