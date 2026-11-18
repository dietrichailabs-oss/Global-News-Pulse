"""No-click Sources status reconciliation with 512 synthetic source identities.

Checks real Qt behavior. No network, source activation, or physical Win11 claim.
"""
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from global_pulse.controller import Controller
from global_pulse.provider_actions import _existing_source_rows
from global_pulse.source_availability import capability, health_text
from global_pulse.ui import MainWindow


def _close(app, window, controller):
    if window is not None:
        window._force_close = True
        for name in ("_workspace_warm_timer", "_evidence_refresh_timer",
                     "_collection_refresh_timer", "search_timer"):
            getattr(window, name).stop()
        window.media.shutdown()
        window.close()
        window.deleteLater()
    controller.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _warm(window):
    window._dirty_pages.add(3)
    window._last_navigation_at = time.monotonic() - 3
    window._workspace_warm_timer.stop()
    window._warm_next_workspace()
    window._workspace_warm_timer.stop()
    assert 3 not in window._dirty_pages


def test_unrelated_archive_revision_skips_512_source_rows_but_real_status_updates(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, demo=True)
    window = None
    try:
        exemplar = next(source for source in controller.catalog if capability(source)[0])
        # Fictional cloned metadata is only a stress test of the documented
        # 512-entry capacity. It does not represent 512 verified live publishers.
        controller.catalog = [
            dict(exemplar, id=f"fictional-source-{index:03d}",
                 name=f"Fictional Source {index:03d}",
                 attribution="SYNTHETIC TEST PROVIDER")
            for index in range(512)
        ]
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        assert window.prepare_initial_workspaces()
        assert window.source_table.rowCount() == 512
        assert window._source_status_last_states == {}
        original_key = window._source_status_render_key

        # A real Store write unrelated to provider health invalidates the
        # broad SQLite revision. No Qt source row may be reconciled.
        controller.store.set_setting("synthetic_other_workspace", {"revision": 1})
        assert window.controller.store.content_revision() != original_key[0]
        with patch("global_pulse.provider_actions._existing_source_rows",
                   side_effect=AssertionError("unrelated revision rebuilt Qt rows")), \
             patch("global_pulse.provider_actions.health_text",
                   side_effect=AssertionError("unrelated revision recomputed health")):
            _warm(window)
        assert window.source_table.rowCount() == 512
        assert window._source_status_render_key[0] == controller.store.content_revision()

        # One actual provider error may update ONLY its own health text.
        sid = "fictional-source-317"
        controller.store.set_source_state(sid, {
            "status": "error", "error": "SYNTHETIC offline timeout",
            "next_poll": "2026-11-18T08:30:00+00:00",
        })
        with patch("global_pulse.provider_actions.health_text",
                   wraps=health_text) as statuses:
            _warm(window)
            assert statuses.call_count == 1
        row = _existing_source_rows(window.source_table)[sid]
        assert window.source_table.item(row, 3).text() == "Last check failed"
        assert window.source_table.item(row, 6).text() != "—"
        another = _existing_source_rows(window.source_table)["fictional-source-100"]
        assert window.source_table.item(another, 3).text() == "Not checked"

        # A separate non-source mutation now skips every unchanged health row.
        controller.store.set_setting("synthetic_other_workspace", {"revision": 2})
        with patch("global_pulse.provider_actions._existing_source_rows",
                   side_effect=AssertionError("unchanged source rows reconciled")):
            _warm(window)
        assert window.source_table.item(row, 3).text() == "Last check failed"

        # A newer rate-limit status is never hidden by the unrelated-write
        # optimization. The real retry text must replace the prior error.
        controller.store.set_source_state(sid, {
            "status": "rate_limited",
            "next_poll": "2026-11-18T09:00:00+00:00",
        })
        with patch("global_pulse.provider_actions.health_text",
                   wraps=health_text) as statuses:
            _warm(window)
            assert statuses.call_count == 1
        assert window.source_table.item(row, 3).text() == "Rate limited; waiting for provider retry"
    finally:
        _close(app, window, controller)
