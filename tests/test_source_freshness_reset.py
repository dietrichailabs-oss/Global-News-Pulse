"""Regression: a fresh HTTP 200 cannot borrow prior response's publication date.

All HTTP is a local httpx.MockTransport, and no provider is contacted.
Publication and provider-update timestamps must stay distinct.
"""
from datetime import datetime, timedelta, timezone
import json

import httpx

from global_pulse.sources import Collector
from global_pulse.source_availability import health_text

NOW = datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc)
PUBLISHED = b'''<rss><channel><item><guid>dated</guid><title>Dated notice</title>
<link>https://example.org/dated</link>
<pubDate>Wed, 11 Nov 2026 13:00:00 GMT</pubDate>
</item></channel></rss>'''
STALE = PUBLISHED.replace(b'11 Nov 2026', b'11 Nov 2024')
UPDATE_ONLY = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>update-only</id><title>Undated original</title>
<link href="https://example.org/updated" rel="alternate"/>
<updated>2026-11-11T15:00:00Z</updated>
</entry></feed>'''
EMPTY = b'<rss><channel></channel></rss>'


def poll(body, state=None, *, adapter="rss", status=200, now=NOW):
    source = dict(
        id="source_status_regression", name="Offline synthetic publisher",
        url="https://example.org/rss", adapter=adapter, enabled=True,
        min_interval=600, allowed_domains=["example.org"],
        category="News", region="Global", access_status="reviewed_public",
        license="Synthetic offline fixture", attribution="Synthetic publisher",
        language="en", stale_after_days=14,
    )

    def factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(status, content=body, request=request)
        ), **kwargs)

    return Collector(source, client_factory=factory, now=lambda: now).collect(state)


def test_http_200_undated_atom_cannot_inherit_stale_publication():
    prior = poll(STALE)
    assert prior["state"]["status"] == "stale"
    assert prior["state"]["latest_publication"] == "2024-11-11T13:00:00Z"
    changed = poll(UPDATE_ONLY, prior["state"], adapter="atom")
    assert len(changed["reports"]) == 1
    report = changed["reports"][0]
    assert report["published_at"] == ""
    assert report["source_updated_at"] == "2026-11-11T15:00:00Z"
    assert report["publication_time_unknown"] is True
    state = changed["state"]
    assert state["status"] == "available"
    assert state["freshness"] == "publication dates unavailable"
    assert "latest_publication" not in state
    assert state["error"] == ""
    assert health_text(state) == "Last check succeeded; publication freshness unknown"


def test_http_200_empty_feed_cannot_inherit_recent_publication():
    prior = poll(PUBLISHED)
    assert prior["state"]["freshness"] == "recent"
    assert prior["state"]["latest_publication"] == "2026-11-11T13:00:00Z"
    empty = poll(EMPTY, prior["state"])
    assert empty["reports"] == []
    state = empty["state"]
    assert state["status"] == "available"
    assert state["count"] == 0
    assert state["freshness"] == "no reports"
    assert "latest_publication" not in state
    assert health_text(state) == "Feed reachable; no reports in the latest response"


def test_http_304_reuses_last_observed_publication_status_without_new_reports():
    prior = poll(STALE)
    unchanged = poll(b"", prior["state"], status=304)
    assert unchanged["reports"] == []
    assert unchanged["state"]["status"] == "stale"
    assert unchanged["state"]["freshness"] == "stale"
    assert unchanged["state"]["latest_publication"] == "2024-11-11T13:00:00Z"


def test_latest_dated_response_reestablishes_date_after_unknown_response():
    prior = poll(UPDATE_ONLY, adapter="atom")
    assert prior["state"]["freshness"] == "publication dates unavailable"
    refreshed = poll(PUBLISHED, prior["state"])
    assert refreshed["state"]["status"] == "available"
    assert refreshed["state"]["freshness"] == "recent"
    assert refreshed["state"]["latest_publication"] == "2026-11-11T13:00:00Z"


def test_304_rechecks_cached_date_as_time_passes_without_rewriting_evidence():
    prior = poll(PUBLISHED)
    assert prior["state"]["freshness"] == "recent"
    original = prior["state"]["latest_publication"]
    # The feed sends no new data after the 14-day freshness threshold.
    later = poll(b"", prior["state"], status=304, now=NOW + timedelta(days=15))
    assert later["reports"] == []
    state = later["state"]
    assert state["latest_publication"] == original
    assert state["status"] == "stale"
    assert state["freshness"] == "stale"
    assert "newest publication is " + original in state["error"]
    assert health_text(state) == "Feed reachable; reporting is stale"


def test_304_within_freshness_window_preserves_current_cached_status():
    prior = poll(PUBLISHED)
    unchanged = poll(b"", prior["state"], status=304, now=NOW + timedelta(days=13))
    assert unchanged["reports"] == []
    assert unchanged["state"]["latest_publication"] == prior["state"]["latest_publication"]
    assert unchanged["state"]["status"] == "not_modified"
    assert unchanged["state"]["freshness"] == "recent"


def test_304_malformed_cached_publication_is_invalidated_without_inventing_date():
    state = {
        "status": "available",
        "freshness": "recent",
        "count": 1,
        "latest_publication": "definitely-not-a-date",
        "etag": "qa-etag",
        "last_modified": "",
        "failures": 0,
    }
    unchanged = poll(b"", state, status=304)
    refreshed = unchanged["state"]
    assert "latest_publication" not in refreshed
    assert refreshed["status"] == "not_modified"
    assert refreshed["freshness"] == "publication dates unavailable"
    assert refreshed["etag"] == "qa-etag"
    assert refreshed["count"] == 1
    assert refreshed["error"] == ""
    assert health_text(refreshed) == "Last check succeeded; publication freshness unknown"


def test_indicator_observations_are_not_reported_as_empty_news_feed():
    payload = [{"lastupdated": "2026-11-10"}, [{
        "indicator": {"id": "FP.CPI.TOTL.ZG", "value": "Inflation"},
        "country": {"id": "ZA", "value": "South Africa"},
        "countryiso3code": "ZAF", "date": "2025",
        "value": 4.5, "unit": "annual %"
    }]]
    result = poll(json.dumps(payload).encode(), adapter="worldbank")
    assert result["reports"] == []
    assert len(result["observations"]) == 1
    assert result["state"]["count"] == 1
    assert result["state"]["status"] == "available"
    assert result["state"]["freshness"] == "observations received"
    assert "latest_publication" not in result["state"]
    assert health_text(result["state"]) == (
        "Feed reachable; indicator observations received; release freshness unverified"
    )
