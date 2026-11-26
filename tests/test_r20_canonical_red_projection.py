"""Canonical red parity at the legacy and alias boundaries; offline fixtures."""
import json
from datetime import datetime,timedelta,timezone

from global_pulse.core import Store
from global_pulse.brief_selection import critical_alerts,overview_evidence_candidates
from test_r20_executive_brief_snapshot import _report


def test_canonical_red_brief_uses_legacy_projection_and_excludes_aliases(tmp_path):
    now=datetime.now(timezone.utc)-timedelta(minutes=3)
    stamp=now.isoformat()
    old=(now-timedelta(days=8)).isoformat()
    with Store(tmp_path/"canonical-red.sqlite3",mode="synthetic") as store:
        old_raw=dict(_report(1,"critical","Disaster"),published_at=old,retrieved_at=old)
        retained=store.ingest([old_raw],now=old)[0]
        rows=[dict(_report(i,"critical","Disaster"),published_at=stamp,retrieved_at=stamp)
              for i in (2,3,4,5)]
        admitted=store.ingest(rows,now=stamp)
        assert len(admitted)==4
        by_title={e["title"]:e for e in admitted}
        def identity(index):
            return by_title[f"FICTIONAL executive report {index}"]["id"]
        legacy,alias,target,withdrawn=(identity(i) for i in (2,3,4,5))
        # Isolated compatibility fixture: old event summary has stale severity.
        # The normal canonical read must recompute from retained source reports.
        with store._lock,store._conn:
            row=store._conn.execute("SELECT body FROM events WHERE id=?",(legacy,)).fetchone()
            body=json.loads(row[0])
            body.update(evidence_policy_version=1,severity="moderate")
            store._conn.execute("UPDATE events SET body=? WHERE id=?",(json.dumps(body),legacy))
            # Explicit late chain merge fixture, same canonical alias table
            # as the real lifecycle path; the old row is intentionally retained.
            from global_pulse.lifecycle import _merge
            _merge(store,alias,target,stamp)
            store._rebuild(target,stamp,[{"kind":"correction","publisher":"Synthetic fixture",
                                         "title":"Fictional linked source records","at":stamp}])
        revoked=dict(rows[-1],kind="retraction",status="retracted",
                     title="FICTIONAL withdrawn archive record")
        store.ingest([revoked],now=stamp)
        since=(now-timedelta(days=7)).isoformat()
        daily=(now-timedelta(days=1)).isoformat()
        page=store.list_events(map_evidence=True,limit=5000,since=since,keep_significant=True)
        expected={e["id"] for e in critical_alerts(page)}
        assert expected=={retained["id"],legacy,target}
        assert alias not in expected and withdrawn not in expected
        legacy_event=next(e for e in page if e["id"]==legacy)
        assert legacy_event["classification_recomputed"] is True
        assert legacy_event["severity"]=="critical"
        brief=store.list_brief_events(since=daily,map_since=since,per_domain=8)
        assert {e["id"] for e in critical_alerts(brief)}==expected
        feed=store.list_events(limit=500)
        assert {e["id"] for e in critical_alerts(overview_evidence_candidates(feed,page))}==expected
        assert not store.brief_manifest_matches(((alias,by_title["FICTIONAL executive report 3"]["revision"]),))
        assert store.brief_manifest_matches(tuple((e["id"],e["revision"]) for e in brief))
