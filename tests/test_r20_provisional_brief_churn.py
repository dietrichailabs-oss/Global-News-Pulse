"""Exercise automatic first-evidence Brief recovery while real Store writes continue."""
import json
import threading
import time
from datetime import datetime,timezone
from test_r20_owner_brief_recovery import desktop,wait_until
from test_r20_executive_brief_snapshot import _report


def test_first_eligible_collection_replaces_empty_daily_while_archive_changes(desktop):
    app,ctl,w=desktop
    opening=w._daily_brief_snapshot
    assert opening is not None and not opening["manifest"]
    stop,seeded=threading.Event(),threading.Event()
    counts={"status_writes":0,"source_writes":0}
    errors=[]
    state={}
    # Use the actual normal evidence_changed signal, not a direct Generate,
    # injected cache, forced readiness flag, or manual idle snapshot.
    def collect():
        try:
            ctl.store.ingest([_report(1,"critical","Disaster"),
                              _report(2,"high","Health")])
            assert not ctl.store.last_ingest_errors
            state["initial_ids"]={str(e["id"]) for e in ctl.store.list_events()
                                  if e["title"]=="FICTIONAL executive report 1"}
            assert len(state["initial_ids"])==1
            seeded.set()
            ctl.evidence_changed.emit()
            sequence=0
            while not stop.wait(.075):
                sequence+=1
                ctl.store.set_setting("offline-provisional-brief-churn",sequence)
                counts["status_writes"]+=1
                if sequence%8==0:
                    ctl.store.ingest([_report(100+sequence,"high","Government")])
                    assert not ctl.store.last_ingest_errors
                    counts["source_writes"]+=1
                    ctl.evidence_changed.emit()
        except Exception as exc:
            errors.append(type(exc).__name__+": "+str(exc))
            seeded.set()

    worker=threading.Thread(target=collect,name="offline-provisional-collector")
    w.open_page(5)
    started=time.monotonic()
    worker.start()
    def ready():
        if errors:
            return True
        snapshot=w._daily_brief_snapshot
        return bool(seeded.is_set() and snapshot is not None
                    and snapshot is not opening and snapshot["manifest"]
                    and state.get("initial_ids",set())<=set(dict(snapshot["manifest"]))
                    and w._displayed_brief_snapshot is snapshot
                    and w.brief_export_button.isEnabled())
    try:
        observed=wait_until(ready,timeout=20)
        elapsed=time.monotonic()-started
        snapshot=w._daily_brief_snapshot
        print("R20_PROVISIONAL_CHURN="+json.dumps({
            "ready":observed and not errors,"elapsed_ms":round(elapsed*1000,3),
            "counts":counts.copy(),"errors":errors,
            "snapshot_nonempty":bool(snapshot and snapshot["manifest"]),
            "snapshot_inflight":w._idle_snapshot_inflight,
            "brief_inflight":w._idle_brief_inflight,
            "brief_reader_active":w._idle_brief_worker_active,
            "requested_reader":w._requested_brief_job is not None,
            "status":w.brief_state_label.text()[:300]},sort_keys=True),flush=True)
        assert not errors,errors
        assert observed,"Empty opening did not recover during continuing collection"
        assert counts["status_writes"]>0 and counts["source_writes"]>0
        assert "FICTIONAL executive report 1" in snapshot["markdown"]
        assert "FICTIONAL executive report 1" in w.brief_browser.toPlainText()
    finally:
        stop.set()
        worker.join(timeout=6)
        assert not worker.is_alive()
        # Stop new warm scheduling and let already admitted reads finish before
        # fixture disposal. Retain the failure evidence printed above.
        w._workspace_warm_timer.stop()
        w._evidence_refresh_timer.stop()
        assert wait_until(lambda:not w._idle_snapshot_inflight
                          and not w._idle_brief_worker_active,timeout=12)
        assert ctl._settle_brief_readers(timeout=5)
