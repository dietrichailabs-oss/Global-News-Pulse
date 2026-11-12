"""Finite E2 source repair executed in the locked CI engineering environment.

This is a source-maintenance script, never a runtime monkey patch. It refuses
unexpected source identities and publishes nothing itself. The paired workflow
runs the entire real Qt/SQLite test suite before a separate job can commit the
three tested source/test files. No QA finding is closed by this script.
"""
from __future__ import annotations
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    'global_pulse/core.py': '78c96e26961b9a94199bd1b4e9a7dfe560664088',
    'global_pulse/controller.py': 'f83cca49ffd2767dd856a6159ac2ce46fe981d90',
}
TEST_PATH = 'tests/test_qa_history_integration.py'
REPORT_PATH = 'docs/engineering/GP-ENG-E2-HISTORY/results.json'


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise RuntimeError('Expected exactly one source anchor: ' + repr(before[:110]))
    return source.replace(before, after, 1)


TESTS = r'''"""Engineering regressions for GP-CORE-001/005/006, using real Qt and SQLite.
No live collection or native notification helper runs. Captured Qt signals are
not evidence of a displayed Windows notification or independent QA acceptance.
"""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timedelta, timezone
import pytest
from PySide6.QtWidgets import QApplication
from global_pulse.controller import Controller
from global_pulse.core import Store, alert_reason, notification_view

T0 = datetime(2026, 11, 9, tzinfo=timezone.utc)


def stamp(days=0, hours=0, minutes=0):
    return (T0 + timedelta(days=days, hours=hours, minutes=minutes)).isoformat().replace("+00:00", "Z")


def report(identifier="a", at=None, **values):
    moment = at or stamp()
    result = dict(id=identifier, source_id="authority", publisher="Fictional test authority",
                  title="Fictional harbor closure notice", summary="A fictional harbor is closed for inspection.",
                  url="https://authority.example/report/" + identifier,
                  published_at=moment, retrieved_at=moment, language="en", region="North Atlantic",
                  country="Norland", category="Infrastructure", event_key="history-regression",
                  severity="high", official=True, official_scope="measurement",
                  origin_id="authority", independence="original", kind="report", synthetic=False)
    result.update(values)
    return result


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(tmp_path, app):
    value = Controller(tmp_path)
    value.monitoring = True  # Direct isolated records; scheduler/network never starts.
    yield value
    value.close()


def send(controller, at, *records):
    controller._on_reports(list(records), now=at)
    assert not controller.store.last_ingest_errors


@pytest.mark.parametrize("same_record", [True, False])
@pytest.mark.parametrize("reopen", [True, False])
def test_twelve_daily_corrections_and_retraction_keep_all_alerts(tmp_path, app, same_record, reopen):
    c = Controller(tmp_path)
    c.monitoring = True
    try:
        send(c, stamp(), report())
        previous_id = "a"
        for day in range(1, 13):
            if reopen:
                c.close()
                c = Controller(tmp_path)
                c.monitoring = True
            identifier = "a" if same_record else "correction-" + str(day)
            correction = report(identifier, stamp(days=day), kind="correction", severity="informational",
                                correction_of="" if same_record else previous_id,
                                summary="Material correction number " + str(day) + ": the closure estimate was wrong.")
            send(c, stamp(days=day), correction)
            previous_id = identifier
            assert len(c.store.list_alerts()) == day + 1
            assert c.events()[0]["severity"] == "informational"
        withdrawal = report("withdrawal", stamp(days=13), kind="retraction", retraction_of=previous_id,
                            severity="informational", summary="The final fictional closure claim is withdrawn.")
        send(c, stamp(days=13), withdrawal)
        assert len(c.store.list_alerts()) == 14
        assert len(c.events()[0]["timeline"]) == 14
        assert c.store.list_alerts()[0]["kind"] == "retraction"
        send(c, stamp(days=13, minutes=1), withdrawal)
        assert len(c.store.list_alerts()) == 14  # Identical notices remain deduplicated.
    finally:
        c.close()


def test_intervening_ordinary_downgrade_does_not_erase_correction_history(controller):
    send(controller, stamp(), report())
    send(controller, stamp(hours=1), report(at=stamp(hours=1), severity="informational", summary="Routine lower-severity update."))
    assert len(controller.store.list_alerts()) == 1
    send(controller, stamp(hours=2), report(at=stamp(hours=2), severity="informational", kind="correction", summary="Material correction after the routine downgrade."))
    assert [a["kind"] for a in controller.store.list_alerts()] == ["correction", "official"]


@pytest.mark.parametrize("key,value", [
    ("muted_sources", ["authority"]), ("categories", ["Economy"]),
    ("countries", ["Elsewhere"]), ("alert_threshold", "critical"),
])
def test_historical_significance_does_not_bypass_current_preferences(controller, key, value):
    send(controller, stamp(), report())
    controller.set_setting(key, value)
    send(controller, stamp(hours=1), report(at=stamp(hours=1), severity="informational", kind="correction", summary="First material correction."))
    send(controller, stamp(hours=2), report(at=stamp(hours=2), severity="informational", kind="correction", summary="Second material correction."))
    assert len(controller.store.list_alerts()) == 1


def test_muted_historical_source_cannot_lend_significance_to_other_source(controller):
    send(controller, stamp(), report())
    send(controller, stamp(hours=1), report("low", stamp(hours=1), source_id="other", origin_id="other", severity="informational", summary="Independent low-severity notice."))
    controller.set_setting("muted_sources", ["authority"])
    before = len(controller.store.list_alerts())
    send(controller, stamp(hours=2), report("low", stamp(hours=2), source_id="other", origin_id="other", severity="informational", kind="correction", summary="The other low-severity notice is corrected."))
    assert len(controller.store.list_alerts()) == before
    projected = notification_view(controller.events()[0], ["authority"])
    assert "authority" not in projected["significance_history"]


@pytest.mark.parametrize("quiet", [False, True])
def test_repeat_corrections_keep_history_without_violating_delivery_controls(controller, quiet):
    emitted = []
    controller.native_alert.connect(lambda *args: emitted.append(args))
    if quiet:
        controller.set_setting("quiet_enabled", True)
        controller.set_setting("quiet_start", "00:00")
        controller.set_setting("quiet_end", "00:00")
    else:
        controller.set_setting("notifications_enabled", False)
    send(controller, stamp(), report())
    for hour in (1, 2):
        send(controller, stamp(hours=hour), report(at=stamp(hours=hour), severity="informational", kind="correction", summary="Material correction " + str(hour)))
    assert len(controller.store.list_alerts()) == 3
    assert not emitted
    assert all(("Quiet hours" if quiet else "muted") in a["delivery_status"] for a in controller.store.list_alerts())


def test_legacy_event_without_history_recovers_retained_significance(controller):
    send(controller, stamp(), report())
    send(controller, stamp(hours=1), report(at=stamp(hours=1), severity="informational", summary="Routine downgrade."))
    event = controller.events()[0]
    with controller.store._conn:
        body = json.loads(controller.store._conn.execute("SELECT body FROM events WHERE id=?", (event["id"],)).fetchone()[0])
        body.pop("significance_history", None)  # Emulate the existing pre-repair archive representation.
        controller.store._conn.execute("UPDATE events SET body=? WHERE id=?", (json.dumps(body), event["id"]))
    send(controller, stamp(hours=2), report(at=stamp(hours=2), severity="informational", kind="correction", summary="Correction after archive upgrade."))
    assert len(controller.store.list_alerts()) == 2
    assert controller.events()[0]["significance_history"]["authority"] == "high"


def test_retention_removes_significance_derived_only_from_expired_report(tmp_path):
    with Store(tmp_path / "retention.sqlite3", mode="live") as store:
        store.ingest([report(retention_days=1)], now=stamp())
        store.ingest([report("low", stamp(days=2), severity="informational", kind="correction", correction_of="a", summary="Low-severity replacement.")], now=stamp(days=2))
        assert store.list_events()[0]["significance_history"]["authority"] == "high"
        result = store.prune(365, now=stamp(days=3))
        assert result["reports"] == 1
        assert store.list_events()[0]["significance_history"]["authority"] == "informational"


@pytest.mark.parametrize("kind", ["correction", "retraction"])
@pytest.mark.parametrize("reopen", [False, True])
def test_deferred_notice_on_unrelated_rebuild_is_versioned_and_alerted(tmp_path, app, kind, reopen):
    c = Controller(tmp_path)
    c.monitoring = True
    try:
        notice = report("deferred", stamp(hours=25), severity="informational", kind=kind,
                        summary="Deferred material " + kind, **{kind + "_of": "a"})
        # Retrieval occurs now, not at the notice's future publication time.
        notice["retrieved_at"] = stamp()
        send(c, stamp(), report(), notice)
        event_id = c.events()[0]["id"]
        assert len(c.store.list_alerts()) == 1
        if reopen:
            c.close()
            c = Controller(tmp_path)
            c.monitoring = True
        context = report("context", stamp(hours=25), source_id="context", origin_id="context", official=False,
                         independence="unknown", kind="commentary", severity="informational", summary="Unrelated current context.")
        send(c, stamp(hours=25), context)
        current = c.event(event_id)
        deferred = next(r for r in current["reports"] if r["id"] == "deferred")
        assert not deferred["future_dated"]
        assert deferred["retrieved_at"] == stamp()  # Do not invent another retrieval.
        assert any(change["report_id"] == "deferred" and change["kind"] == kind for change in current["changes"])
        assert len(c.store.list_alerts()) == 2
        assert c.store.list_alerts()[0]["kind"] == kind
        past = c.event(event_id, at=stamp(hours=1))
        assert next(r for r in past["reports"] if r["id"] == "deferred")["future_dated"]
        send(c, stamp(hours=26), dict(context, id="context2", url="https://context.example/second", published_at=stamp(hours=26)))
        assert len(c.store.list_alerts()) == 2
    finally:
        c.close()


def test_historical_replay_uses_chosen_revision_time_without_writing(tmp_path):
    with Store(tmp_path / "history.sqlite3", mode="live") as store:
        withdrawal = report("future-withdrawal", stamp(hours=25), kind="retraction", retraction_of="a", severity="informational")
        store.ingest([report(), withdrawal], now=stamp())
        initial = store.list_events()[0]
        counts = store.stats()
        versions = store._conn.execute("SELECT count(*) FROM report_revisions").fetchone()[0]
        historical = store.get_event(initial["id"], at=stamp(days=2))
        assert historical["revision"] == initial["revision"] == 1
        assert historical["updated_at"] == stamp()
        assert historical["verification"] == "official"
        assert historical["status"] == "active"
        assert next(r for r in historical["reports"] if r["id"] == "a")["evidence_status"] == "active"
        assert next(r for r in historical["reports"] if r["id"] == "future-withdrawal")["future_dated"]
        assert store.stats() == counts
        assert store._conn.execute("SELECT count(*) FROM report_revisions").fetchone()[0] == versions


def test_fresh_commentary_cannot_make_old_deferred_retraction_a_new_alert(controller):
    withdrawal = report("old-future-withdrawal", stamp(hours=25), kind="retraction", retraction_of="a", severity="informational")
    send(controller, stamp(), report(), withdrawal)
    context = report("context", stamp(days=5), kind="commentary", official=False, source_id="context", origin_id="context", severity="informational")
    send(controller, stamp(days=5), context)
    event = controller.events()[0]
    assert event["status"] == "retracted"
    assert any(c["kind"] == "retraction" for c in event["changes"])
    assert len(controller.store.list_alerts()) == 1


def test_future_high_evidence_never_seeds_current_significance_history(controller):
    send(controller, stamp(), report("future", stamp(days=5), severity="critical"),
         report("low", stamp(), source_id="low", origin_id="low", severity="informational"))
    send(controller, stamp(hours=1), report("low", stamp(hours=1), source_id="low", origin_id="low", severity="informational", kind="correction", summary="An informational correction."))
    assert controller.events()[0]["significance_history"].get("authority") is None
    assert not controller.store.list_alerts()
'''


def apply() -> None:
    sources = {}
    for name, expected in EXPECTED.items():
        data = (ROOT / name).read_bytes()
        if git_blob(data) != expected:
            raise RuntimeError('Source identity changed; review before applying: ' + name)
        sources[name] = data.decode('utf-8')
    if (ROOT / TEST_PATH).exists():
        raise RuntimeError('Regression file already exists; refusing overwrite')
    core = sources['global_pulse/core.py']
    core = replace_once(core,
        '    eligible = [r for r in active if not r.get("future_dated")]\n',
        '''    eligible = [r for r in active if not r.get("future_dated")]
    # Significance belongs to a retained source history, not just the immediately
    # preceding headline. Keep it separate from current displayed severity.
    retained_sources = {r["source_id"] for r in labelled}
    significance_history = {source: level for source, level in
                            (previous or {}).get("significance_history", {}).items()
                            if source in retained_sources and level in SEVERITY}
    for report in eligible:
        source = report["source_id"]
        if SEVERITY[report["severity"]] > SEVERITY.get(significance_history.get(source), -1):
            significance_history[source] = report["severity"]
''')
    core = replace_once(core,
        '             "material_signature": _hash(material), "changes": changes,\n',
        '             "material_signature": _hash(material), "changes": changes,\n             "significance_history": significance_history,\n')
    core = replace_once(core,
        '    changed_records = {c.get("record_key"): c.get("kind") for c in changes}\n',
        '''    notice_significant = significant or any(
        SEVERITY.get(level, 0) >= 2 for level in event.get("significance_history", {}).values())
    changed_records = {c.get("record_key"): c.get("kind") for c in changes}
''')
    core = replace_once(core,
        '    if significant and any(changed_records.get(r.get("record_key")) == "retraction" for r in notices):',
        '    if notice_significant and any(changed_records.get(r.get("record_key")) == "retraction" for r in notices):')
    core = replace_once(core,
        '    if significant and any(changed_records.get(r.get("record_key")) == "correction" for r in notices):',
        '    if notice_significant and any(changed_records.get(r.get("record_key")) == "correction" for r in notices):')
    core = replace_once(core,
        '    projected["revision"] = event["revision"]\n    return projected\n',
        '''    projected["revision"] = event["revision"]
    # A muted source must not contribute its OLD significance either.
    projected["significance_history"] = {
        source: level for source, level in event.get("significance_history", {}).items()
        if source not in muted and source in {r["source_id"] for r in reports}}
    return projected
''')
    core = replace_once(core,
        '        _, event["reports"] = _evidence_reports(reports, at=at or event["updated_at"])\n',
        '''        # The request selects a saved revision; its header AND report states
        # are evaluated at that revision's time. Reading is never a new revision.
        _, event["reports"] = _evidence_reports(reports, at=event["updated_at"])
''')
    core = replace_once(core,
        '        event = _build_event(event_id, reports, previous=previous, stamp=stamp, changes=changes)\n',
        '''        retention_rebuild = any(c.get("kind") == "retention" for c in changes)
        if previous and ("significance_history" not in previous or retention_rebuild):
            # Migrate existing archives and discard history derived only from
            # expired records. FK cascades have already removed their versions.
            history = {}
            for version in self._conn.execute(
                    "SELECT body,seen_at FROM report_revisions WHERE event_id=? ORDER BY id", (event_id,)):
                evidence = json.loads(version["body"])
                if (evidence.get("status", "active") != "active"
                        or evidence.get("kind") in {"retraction", "commentary", "repost"}
                        or not evidence.get("publication_time_known", True)
                        or _dt(evidence["published_at"]) > _dt(version["seen_at"]) + timedelta(minutes=10)):
                    continue
                source, level = evidence["source_id"], evidence["severity"]
                if SEVERITY.get(level, 0) > SEVERITY.get(history.get(source), -1):
                    history[source] = level
            previous = dict(previous, significance_history=history)

        # Deferred notices can become effective when ANY report rebuilds their
        # event, not only when that notice happens to be polled again.
        prior_snapshot = self._get_event_unlocked(event_id, at=previous["updated_at"]) if previous and not retention_rebuild else None
        if prior_snapshot:
            prior_reports = prior_snapshot["reports"]
        elif previous and retention_rebuild:
            _, prior_reports = _evidence_reports(reports, at=previous["updated_at"])
        else:
            prior_reports = []
        prior_by_key = {r["record_key"]: r for r in prior_reports}
        _, current_labels = _evidence_reports(reports, at=stamp)
        current_by_key = {r["record_key"]: r for r in current_labels}
        recorded = {c.get("record_key") for c in changes}
        changes = list(changes)
        for report in reports:
            key = report["record_key"]
            old, current = prior_by_key.get(key), current_by_key[key]
            if old is None:
                continue
            now_eligible = not current.get("future_dated")
            became_eligible = old.get("future_dated", False) and now_eligible
            resolved_notice = (bool(old.get("unresolved_reference"))
                               and not current.get("unresolved_reference") and now_eligible)
            if became_eligible or resolved_notice:
                kind = ("retraction" if report.get("retraction_of") or report["kind"] == "retraction" or report["status"] == "retracted"
                        else "correction" if report.get("correction_of") or report["kind"] == "correction" or report["status"] == "corrected"
                        else "eligibility")
                if key not in recorded:
                    changes.append({"kind": kind, "report_id": report["id"], "record_key": key,
                                    "publisher": report["publisher"], "title": report["title"], "at": stamp,
                                    "transition": "evidence_eligibility" if became_eligible else "reference_resolved"})
                    recorded.add(key)
            if bool(report.get("future_dated")) != bool(current.get("future_dated")):
                # Version the derived eligibility without inventing a retrieval
                # or changing the original publication timestamp/source bytes.
                report["future_dated"] = bool(current.get("future_dated"))
                fingerprint = _report_fingerprint(report)
                self._conn.execute("UPDATE reports SET body=? WHERE record_key=?", (_json(report), key))
                self._conn.execute("INSERT INTO report_revisions(record_key,event_id,seen_at,fingerprint,body) VALUES(?,?,?,?,?)",
                                   (key, event_id, stamp, fingerprint, _json(report)))
        event = _build_event(event_id, reports, previous=previous, stamp=stamp, changes=changes)
''')
    controller = sources['global_pulse/controller.py']
    controller = replace_once(controller,
        '            significance = max(significance, ranks.get(previous.get("severity", "unassessed"), 0))\n',
        '''            significance = max(significance, ranks.get(previous.get("severity", "unassessed"), 0),
                               max((ranks.get(level, 0) for source, level in
                                    event.get("significance_history", {}).items()
                                    if source not in muted), default=0))
''')
    controller = replace_once(controller,
        '                if not event or not self._has_fresh_change(event, now=now):\n',
        '                if not event:\n')
    controller = replace_once(controller,
        '                if not reason or not self._watched(event, previous=prior, reason=reason):\n',
        '''                if (not reason or not self._has_fresh_change(event, now=now, reason=reason)
                        or not self._watched(event, previous=prior, reason=reason)):
''')
    controller = replace_once(controller,
        '    def _has_fresh_change(event, now=None):\n',
        '    def _has_fresh_change(event, now=None, *, reason=None):\n')
    controller = replace_once(controller,
        '        changed = {c.get("record_key") for c in event.get("changes", [])}\n',
        '''        notice_kind = ("retraction" if isinstance(reason, str) and reason.startswith("Retraction:")
                       else "correction" if isinstance(reason, str) and reason.startswith("Correction:") else None)
        changed = {c.get("record_key") for c in event.get("changes", [])
                   if notice_kind is None or c.get("kind") == notice_kind}
''')
    output = {'global_pulse/core.py': core, 'global_pulse/controller.py': controller, TEST_PATH: TESTS}
    for name, text in output.items():
        ast.parse(text, filename=name)
    for name, text in output.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
        print(name, git_blob(path.read_bytes()))


def evidence() -> None:
    tree = ET.parse('/tmp/gp-history-results.xml')
    suites = list(tree.getroot().iter('testsuite'))
    totals = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
    if totals['tests'] < 240 or any(totals[key] for key in ('failures', 'errors', 'skipped')):
        raise RuntimeError('Full passing regression required; no skipped-case acceptance')
    tested_files = {}
    for name in (*EXPECTED, TEST_PATH):
        data = (ROOT / name).read_bytes()
        tested_files[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'git_blob': git_blob(data)}
    result = {
        'review': 'GP-ENG-E2-HISTORY', 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
        'checkout_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'workflow_run_url': 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID'],
        'python': platform.python_version(), 'platform': platform.platform(),
        'scope': 'Engineering full Linux offscreen Qt/controller/SQLite regression on the exact modified files below; not independent QA or Windows acceptance.',
        'changes': ['Durable source-scoped correction significance with preference projection and retention reset.',
                    'Deferred evidence eligibility and notice changes versioned during event rebuilds.',
                    'Historical report state evaluated at the saved event revision timestamp.',
                    'Material-notice freshness bound to that notice rather than unrelated fresh commentary.'],
        'independent_qa_retest': 'NOT RUN', 'windows_acceptance': 'NOT RUN', 'release_approval': 'NOT GRANTED',
        'remaining': ['GP-CORE-002 NWS/CAP lifecycle', 'GP-UI-01 mandatory layout', 'Windows/platform observations and packaging', 'Independent full charter review'],
        **totals, 'tested_files': tested_files,
        'test_cases': [case.get('classname', '') + '::' + case.get('name', '') for case in tree.getroot().iter('testcase')],
    }
    destination = ROOT / REPORT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    staging = ROOT / '.history-publish'
    staging.mkdir(exist_ok=False)
    for name in (*EXPECTED, TEST_PATH, REPORT_PATH):
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    print(json.dumps({k: result[k] for k in ('checkout_commit', 'workflow_run_url', 'tests', 'failures', 'errors', 'skipped')}, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in {'apply', 'evidence'}:
        raise SystemExit('Usage: apply_e2_history_repair.py apply|evidence')
    (apply if sys.argv[1] == 'apply' else evidence)()

# E2 history publish retry: hidden staging is explicitly included in Actions artifact upload.
