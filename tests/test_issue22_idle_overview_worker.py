"""Exact-source no-click world-overview worker and Qt-presentation regression.

These hosted offline tests do not establish physical Windows 11 smoothness,
independent QA, live media playback, or source reuse rights.
"""
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from global_pulse.brief_selection import overview_evidence_candidates, overview_html
from test_issue22_idle_selected_context import _fixture, _close


def _snapshot(app, window):
    snapshots = []
    window._idle_snapshot_ready.connect(snapshots.append)
    window._start_idle_snapshot()
    deadline = time.monotonic() + 20
    while not snapshots and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert snapshots, "Source worker never completed: no fake Qt heartbeat pass"
    result = snapshots[-1]
    assert "error" not in result, result.get("error")
    assert result["revision_before"] == result["revision_after"]
    return result


def test_post_splash_worker_prepares_exact_source_overview_and_attribution(tmp_path):
    app, controller, window, event = _fixture(tmp_path)
    try:
        snapshot = _snapshot(app, window)
        expected = overview_evidence_candidates(
            snapshot["feed"], snapshot["country_evidence"])
        assert snapshot["overview_events"] == expected
        scope = (window.time_range.currentText().lower() +
                 (", filtered" if (window.category.currentData() or
                  window.region.currentData() or window.search.text().strip())
                  else ", all categories"))
        assert snapshot["overview_html"] == overview_html(
            expected, label=scope+" local feed and retained map evidence")
        assert event["id"] in [str(e["id"]) for e in snapshot["overview_events"]]
        assert "source" in snapshot["overview_html"].lower()
    finally:
        _close(app, controller, window)


def test_no_click_qt_paint_uses_worker_html_without_reranking_5000_rows(tmp_path):
    app, controller, window, event = _fixture(tmp_path)
    try:
        snapshot = _snapshot(app, window)
        # The worker has already supplied source-consistent HTML and local
        # navigation candidates. A second passive Qt apply must NOT rerun
        # the 5k-record classification or HTML renderer on the GUI thread.
        with (patch("global_pulse.brief_selection.overview_evidence_candidates",
                    side_effect=AssertionError("overview classification on Qt")) as shortlist,
              patch("global_pulse.brief_selection.overview_html",
                    side_effect=AssertionError("overview HTML on Qt")) as renderer,
              patch("global_pulse.brief_selection.overview_documents",
                    side_effect=AssertionError("overview page construction on Qt")) as pages):
            window.refresh_data(_idle_snapshot=snapshot)
            assert shortlist.call_count == 0
            assert renderer.call_count == 0
            assert pages.call_count == 0
        assert window._overview_events == snapshot["overview_events"]
        assert window._overview_html_cached == snapshot["overview_html"]
    finally:
        _close(app, controller, window)


def test_explicit_overview_still_formats_changed_source_and_keeps_links(tmp_path):
    app, controller, window, event = _fixture(tmp_path)
    try:
        altered = dict(event, title="FICTIONAL corrected evidence")
        window._overview_events = [altered]
        window._update_world_overview()
        assert "FICTIONAL corrected evidence" in window._overview_html_cached
        assert "pulse-event://open/" in window._overview_html_cached
        assert altered["id"] in window._overview_html_cached
        # A later user/manual refresh cannot be suppressed by an old worker
        # cache: new source evidence is shown and original ID remains linked.
        altered2 = dict(altered, title="FICTIONAL revised again")
        window._overview_events = [altered2]
        window._update_world_overview()
        assert "FICTIONAL revised again" in window._overview_html_cached
        assert "FICTIONAL corrected evidence" not in window._overview_html_cached
    finally:
        _close(app, controller, window)
