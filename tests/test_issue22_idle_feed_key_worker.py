"""Issue22: no-click source feed canonical-key JSON belongs off the Qt thread.

Offline real-Qt synthetic evidence only. Not independent QA, physical Win11
smoothness, media playback, or permission/release acceptance.
"""
import json
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from test_issue22_idle_overview_worker import _snapshot
from test_issue22_idle_selected_context import _fixture, _close


def _sorted_source(rows, index):
    copied=list(rows)
    if index==1:
        rank={"critical":4,"high":3,"moderate":2,"informational":1,"unassessed":0}
        copied.sort(key=lambda row:(
            rank.get(row.get("severity"),0),str(row.get("updated_at",""))),
            reverse=True)
    elif index==2:
        copied.sort(key=lambda row:int(row.get("report_count",0)),reverse=True)
    return copied


def _original_bytes(rows):
    return json.dumps(rows,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),default=str)


def test_worker_serializes_exact_original_evidence_with_every_sort_mode(tmp_path):
    app,controller,window,event=_fixture(tmp_path)
    try:
        for sort_index in (0,1,2):
            window.sort_combo.setCurrentIndex(sort_index)
            snapshot=_snapshot(app,window)
            assert snapshot["feed_sort_index"]==sort_index
            assert snapshot["feed_serialized"]==_original_bytes(
                _sorted_source(snapshot["feed"],sort_index))
            # The source key includes the original nested reports, not just
            # ids/timestamps. Corrections may change report bytes in place.
            if snapshot["feed"]:
                altered=[dict(row) for row in snapshot["feed"]]
                altered[0]=dict(altered[0],title="FICTIONAL corrected source")
                assert _original_bytes(_sorted_source(altered,sort_index))!=snapshot["feed_serialized"]
    finally:
        _close(app,controller,window)


def test_passive_qt_refresh_consumes_worker_key_without_deep_json(tmp_path):
    app,controller,window,event=_fixture(tmp_path)
    try:
        snapshot=_snapshot(app,window)
        with patch.object(window,"_populate_feed",wraps=window._populate_feed) as feed:
            window.refresh_data(_idle_snapshot=snapshot)
            assert feed.call_count==1
            assert feed.call_args.kwargs["serialized_feed"]==snapshot["feed_serialized"]
        # The worker key is accepted directly by the actual real-QListWidget
        # presenter. No 500-record JSON scan may run on the GUI thread.
        window._events=list(snapshot["feed"])
        with patch("global_pulse.ui.json.dumps",
                   side_effect=AssertionError("deep JSON on passive Qt")) as dump:
            window._populate_feed(
                saved_ids=snapshot["saved_situation_ids"],
                english_enabled=snapshot["english_headlines_enabled"],
                serialized_feed=snapshot["feed_serialized"])
            assert dump.call_count==0
        assert window.feed_list.count()==len(snapshot["feed"])
        if snapshot["feed"]:
            row=window.feed_list.item(0).data(Qt.ItemDataRole.UserRole)
            assert isinstance(row,dict) and row.get("reports")==snapshot["feed"][0].get("reports")
    finally:
        _close(app,controller,window)


def test_explicit_changed_source_does_not_reuse_stale_worker_key(tmp_path):
    app,controller,window,event=_fixture(tmp_path)
    try:
        snapshot=_snapshot(app,window)
        window._events=list(snapshot["feed"])
        window._populate_feed(
            saved_ids=snapshot["saved_situation_ids"],
            english_enabled=snapshot["english_headlines_enabled"],
            serialized_feed=snapshot["feed_serialized"])
        if not snapshot["feed"]:
            return
        changed=dict(snapshot["feed"][0])
        changed["recap"]="FICTIONAL nested evidence correction"
        window._events=[changed]+list(snapshot["feed"][1:])
        # No precomputed key on explicit/changed source or archive-pin path.
        window._populate_feed(
            saved_ids=snapshot["saved_situation_ids"],
            english_enabled=snapshot["english_headlines_enabled"])
        assert window._feed_snapshot_key[0]!=snapshot["feed_serialized"]
        assert "FICTIONAL nested evidence correction" in (
            window.feed_list.item(0).data(Qt.ItemDataRole.UserRole)["recap"])
    finally:
        _close(app,controller,window)
