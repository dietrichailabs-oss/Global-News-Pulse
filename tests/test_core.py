import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from global_pulse.core import Store, alert_reason, build_brief, normalize_report, plain_text, safe_public_url

STAMP = "2026-11-08T10:00:00Z"


def report(id="a", **changes):
    r = dict(id=id, source_id="source_a", publisher="Regional A", title="Port Northhaven closes after major power outage",
             summary="The fictional Northhaven port authority reported an interruption to cargo operations.",
             url=f"https://a.example/news/{id}", published_at=STAMP, retrieved_at=STAMP,
             language="en", region="North Atlantic", country="Norland", category="Infrastructure", event_key="test-outage",
             severity="high", origin_id="", independence="unknown", synthetic=True)
    r.update(changes)
    return r


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite3")
    yield s
    s.close()


def test_single_social_report_is_unverified_and_feed_only(store):
    e = store.ingest([report(kind="social")], now=STAMP)[0]
    assert e["verification"] == "unverified"
    assert e["independent_origins"] == []
    assert alert_reason(e) is None
    assert "Independent corroboration has not been established" in e["recap"]


def test_unknown_independence_from_three_publishers_is_not_confirmation(store):
    records = [report(str(i), source_id=f"source{i}", publisher=f"Source {i}", url=f"https://{i}.example/story", origin_id=f"origin{i}") for i in range(3)]
    e = store.ingest(records, now=STAMP)[0]
    assert e["verification"] == "unverified"
    assert not e["independent_origins"]


def test_syndication_and_identical_originals_are_not_independent(store):
    e = store.ingest([report(independence="original", origin_id="wire-a"),
                      report("b", source_id="source_b", publisher="B", independence="syndicated", origin_id="wire-a"),
                      report("c", source_id="source_c", publisher="C", independence="original", origin_id="different-but-exact-copy")], now=STAMP)[0]
    assert len(e["independent_origins"]) == 1
    assert e["verification"] == "unverified"
    assert alert_reason(e) is None


def test_two_documented_originals_developing_and_three_corroborated(store):
    a = report(independence="original", origin_id="origin-a")
    b = report("b", source_id="source_b", summary="Regional B independently reports cargo disruptions at Northhaven.", independence="original", origin_id="origin-b")
    e = store.ingest([a, b], now=STAMP)[0]
    assert e["verification"] == "developing"
    assert alert_reason(e).startswith("Developing")
    c = report("c", source_id="source_c", summary="Regional C independently describes the outage in the port district.", independence="original", origin_id="origin-c")
    e2 = store.ingest([c], now="2026-11-08T10:05:00Z")[0]
    assert e2["verification"] == "corroborated"


def test_official_statement_only_confirms_attribution(store):
    e = store.ingest([report(official=True, official_scope="statement", origin_id="government", independence="original")], now=STAMP)[0]
    assert e["verification"] == "unverified"
    assert e["official_attribution"] is True
    assert "not every underlying claim" in e["recap"]
    assert alert_reason(e).startswith("Official")


def test_official_measurement_is_scope_labelled(store):
    e = store.ingest([report(official=True, official_scope="measurement", origin_id="official-sensor", independence="original")], now=STAMP)[0]
    assert e["verification"] == "official"
    assert e["verification_scope"] == "official measurement"


def test_conflicts_compare_equal_units_observation_time_and_scope(store):
    a = report(independence="original", origin_id="a", claims={"injuries": {"value": 8, "unit": "people", "as_of": STAMP}})
    b = report("b", source_id="source_b", independence="original", origin_id="b", summary="An independent report gives twelve injured people.", claims={"injuries": {"value": 12, "unit": "people", "as_of": STAMP}})
    e = store.ingest([a, b], now=STAMP)[0]
    assert len(e["contradictions"]) == 1
    assert e["contradictions"][0]["kind"] == "conflicting_claims"
    assert {c["value"] for c in e["contradictions"][0]["claims"]} == {8, 12}
    assert "no value has been selected as true" in e["contradictions"][0]["explanation"]
    assert e["verification"] == "developing"


def test_different_measurement_times_are_not_contradictions(store):
    a = report(claims={"injuries": {"value": 8, "unit": "people", "as_of": STAMP}}, origin_id="a")
    b = report("b", source_id="source_b", origin_id="b", claims={"injuries": {"value": 12, "unit": "people", "as_of": "2026-11-08T12:00:00Z"}})
    e = store.ingest([a, b], now=STAMP)[0]
    assert not e["contradictions"]


def test_missing_comparable_time_is_only_possible_discrepancy(store):
    e = store.ingest([report(claims={"cause": {"value": "equipment failure"}}),
                      report("b", source_id="source_b", claims={"cause": {"value": "under investigation"}})], now=STAMP)[0]
    assert e["contradictions"][0]["kind"] == "potential_discrepancy"


def test_retrieval_repeat_has_no_revision_or_alert(store):
    a = report(official=True)
    e = store.ingest([a], now=STAMP)[0]
    alert = store.add_alert(e, alert_reason(e))
    assert alert
    a["retrieved_at"] = "2026-11-08T10:10:00Z"
    assert store.ingest([a], now="2026-11-08T10:10:00Z") == []
    assert store.get_event(e["id"])["revision"] == 1
    assert store.get_event(e["id"])["reports"][0]["retrieved_at"] == a["retrieved_at"]
    assert store.add_alert(e, alert_reason(e)) is None


def test_syndicated_copy_adds_source_trail_without_duplicate_alert(store):
    original = report(independence="original", origin_id="a", official=True)
    first = store.ingest([original], now=STAMP)[0]
    copy = report("b", source_id="wirecopy", independence="syndicated", origin_id="a")
    later = store.ingest([copy], now="2026-11-08T10:05:00Z")[0]
    assert later["report_count"] == 2
    assert later["material_signature"] == first["material_signature"]
    assert alert_reason(later, first) is None


def test_same_record_revisions_preserved_and_playback_is_as_known(store):
    e = store.ingest([report(summary="Initial report: eight injuries.")], now=STAMP)[0]
    changed = report(summary="Corrected report: four injuries.", kind="correction")
    e2 = store.ingest([changed], now="2026-11-08T10:20:00Z")[0]
    assert e2["revision"] == 2
    old = store.get_event(e["id"], at="2026-11-08T10:10:00Z")
    assert old["reports"][0]["summary"] == "Initial report: eight injuries."
    assert "Corrected" not in old["recap"]
    assert len(old["timeline"]) == 1
    assert "Corrected" in store.get_event(e["id"])["recap"]
    assert store.list_events(before="2026-11-08T10:10:00Z")[0]["revision"] == 1


def test_correction_and_retraction_override_cooldown_and_keep_history(store):
    e = store.ingest([report(official=True)], now=STAMP)[0]
    assert store.add_alert(e, alert_reason(e))
    correction = report("corrected", official=True, kind="correction", correction_of="a", title="Northhaven authority corrects cargo outage impact", summary="The authority corrects an earlier impact figure.")
    corrected = store.ingest([correction], now="2026-11-08T10:10:00Z")[0]
    assert corrected["id"] == e["id"]
    assert next(r for r in corrected["reports"] if r["id"] == "a")["evidence_status"] == "corrected"
    assert alert_reason(corrected, e).startswith("Correction")
    assert store.add_alert(corrected, alert_reason(corrected, e))
    retraction = report("withdrawal", official=True, kind="retraction", retraction_of="corrected", title="Authority withdraws its cargo outage impact statement")
    retracted = store.ingest([retraction], now="2026-11-08T10:20:00Z")[0]
    assert retracted["status"] == "retracted"
    assert store.add_alert(retracted, alert_reason(retracted, corrected))
    assert len(store.list_alerts()) == 3
    assert len(retracted["timeline"]) == 3


def test_cross_publisher_retraction_cannot_erase_other_source(store):
    first = store.ingest([report(independence="original", origin_id="a")], now=STAMP)[0]
    malicious = report("evil", source_id="another", publisher="Another", retraction_of="a", kind="retraction", origin_id="another")
    e = store.ingest([malicious], now="2026-11-08T10:10:00Z")[0]
    original = next(r for r in e["reports"] if r["id"] == "a")
    assert original["evidence_status"] == "active"
    assert next(r for r in e["reports"] if r["id"] == "evil")["unresolved_reference"] == "a"


def test_material_alerts_have_persistent_dedup_and_delivery_status(store):
    e = store.ingest([report(official=True)], now=STAMP)[0]
    alert = store.add_alert(e, alert_reason(e))
    assert {"id", "event_id", "reason", "title", "created_at", "read"} <= set(alert)
    store.update_alert_delivery(alert["id"], "Suppressed by Windows settings; retained in history")
    assert "Suppressed" in store.list_alerts()[0]["delivery_status"]
    store.mark_alert_read(alert["id"])
    assert store.list_alerts()[0]["read"] is True
    assert store.add_alert(e, alert_reason(e)) is None


def test_quiet_delivery_does_not_change_local_alert_retention(store):
    e = store.ingest([report(official=True)], now=STAMP)[0]
    alert = store.add_alert(e, alert_reason(e))
    store.update_alert_delivery(alert["id"], "Quiet hours: native delivery skipped")
    assert len(store.list_alerts()) == 1


def test_situations_compute_changes_since_last_visit(store):
    e = store.ingest([report()], now=STAMP)[0]
    store.save_situation(e["id"])
    first = store.visit_situation(e["id"])
    assert len(first["changes"]) == 1
    assert store.visit_situation(e["id"])["changes"] == []
    store.ingest([report("b", source_id="b", summary="New account from a regional reporter.")], now="2026-11-08T10:10:00Z")
    assert store.list_situations()[0]["new_revisions"] == 1
    assert len(store.visit_situation(e["id"])["changes"]) == 1


def test_full_text_filters_and_malicious_query_are_safe(store):
    e = store.ingest([report()], now=STAMP)[0]
    assert store.list_events(query="Northhaven cargo")
    assert store.list_events(query="Northhaven", category="Infrastructure", region="Norland")
    assert store.list_events(query='" OR 1=1; DROP TABLE events;--') == []
    assert store.get_event(e["id"])
    assert not store.list_events(category="Economics")


def test_event_clustering_respects_country_time_and_synthetic_boundary(store):
    base = report(event_key="")
    first = store.ingest([base], now=STAMP)[0]
    same = report("copy", source_id="copy", event_key="", url="https://copy.example/story")
    assert store.ingest([same], now=STAMP)[0]["id"] == first["id"]
    elsewhere = report("elsewhere", source_id="elsewhere", event_key="", country="Otherland", url="https://other.example/story")
    assert store.ingest([elsewhere], now=STAMP)[0]["id"] != first["id"]
    later = report("later", event_key="", published_at="2026-11-11T10:00:00Z", url="https://a.example/later")
    assert store.ingest([later], now="2026-11-11T10:00:00Z")[0]["id"] != first["id"]
    real = report("live", source_id="live", event_key="", synthetic=False, url="https://live.example/story")
    assert store.ingest([real], now=STAMP) == []
    assert "separate archives" in store.last_ingest_errors[0]["error"]


def test_conflicting_geolocations_do_not_invent_a_pin(store):
    e = store.ingest([report(latitude=45, longitude=-20, geo_precision="regional"),
                      report("b", source_id="b", latitude=25, longitude=70, geo_precision="regional")], now=STAMP)[0]
    assert e["latitude"] is None and e["longitude"] is None


def test_foreign_report_uses_honest_english_fallback(store):
    e = store.ingest([report(language="de", title="Stromausfall im Hafen", summary="Die Ursache wird untersucht.")], now=STAMP)[0]
    assert "reliable English translation is not available" in e["recap"]
    assert e["reports"][0]["title"] == "Stromausfall im Hafen"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "http://127.0.0.1/x", "http://localhost/x", "https://user:pass@example.com/x", "http://169.254.169.254/latest", "http://0x7f000001/x", "http://127.1/x", "https://a.example:444/x"])
def test_untrusted_urls_rejected(url):
    with pytest.raises(ValueError):
        safe_public_url(url)


def test_bad_input_does_not_poison_valid_neighbors(store):
    result = store.ingest([report(url="javascript:alert(1)"), report("good")], now=STAMP)
    assert len(result) == 1 and len(store.last_ingest_errors) == 1
    assert "Unsafe" in str(store.last_ingest_errors) or "HTTP" in str(store.last_ingest_errors)


def test_html_script_and_naive_timestamps_sanitized(store):
    e = store.ingest([report(title="<b>Port closure</b><script>alert(1)</script>", published_at="2026-11-08T10:00:00")], now=STAMP)[0]
    assert e["title"] == "Port closure"
    assert e["published_at"].endswith("Z")


def test_economic_dates_and_revisions_are_separate(store):
    obs = dict(source_id="stats", indicator="Inflation", country="Norland", observation_date="2025", value=4.3, unit="percent", release_date="2026-04-01", retrieved_at=STAMP, url="https://stats.example/data")
    store.put_observations([obs])
    store.put_observations([dict(obs, value=4.1, release_date="2026-06-01")])
    saved = store.list_observations()[0]
    assert saved["date"] == "2025"
    assert saved["release_date"] == "2026-06-01"
    assert saved["retrieved_at"] == STAMP
    assert saved["previous_value"] == 4.3
    assert saved["value"] == 4.1
    assert saved["revision_count"] == 2
    store.put_observations([dict(obs, value=4.1, release_date="2026-06-01", retrieved_at="2026-11-08T12:00:00Z")])
    assert store.list_observations()[0]["revision_count"] == 2


def test_source_retention_removes_derived_text_and_search_records(store):
    e = store.ingest([report(retention_days=1)], now=STAMP)[0]
    store.save_situation(e["id"])
    count = store.prune(now="2026-11-10T10:00:01Z")
    assert count["reports"] == 1 and count["events"] == 1
    assert store.get_event(e["id"]) is None
    assert not store.list_events(query="Northhaven")
    assert not store.list_situations()


def test_partial_source_retention_rebuilds_without_expired_evidence(store):
    old = report(retention_days=1, summary="Unique expired purple meteor wording")
    live = report("b", source_id="b", retention_days=365, summary="Remaining current coverage")
    e = store.ingest([old, live], now=STAMP)[0]
    store.prune(now="2026-11-10T10:00:01Z")
    current = store.get_event(e["id"])
    assert current["report_count"] == 1
    assert "purple meteor" not in json.dumps(current)
    assert not store.list_events(query="purple meteor")


def test_settings_checkpoints_and_concurrent_writes(store):
    store.set_setting("watchlist", {"countries": ["NL"], "topics": ["Economy"]})
    store.set_source_state("a", {"etag": '"abc"', "next_poll": STAMP})
    assert store.get_setting("watchlist")["countries"] == ["NL"]
    assert store.get_source_state("a")["etag"] == '"abc"'
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: store.ingest([report(str(i), source_id=f"thread{i}", event_key=f"isolated{i}", title=f"Unique independent event {i}")], now=STAMP), range(20)))
    assert store.stats()["events"] == 20


def test_reopen_preserves_dedup_and_history(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    with Store(path) as s:
        e = s.ingest([report(official=True)], now=STAMP)[0]
        s.add_alert(e, alert_reason(e))
    with Store(path) as s:
        assert s.get_event(e["id"])["report_count"] == 1
        assert len(s.list_alerts()) == 1
        assert s.add_alert(e, alert_reason(e)) is None


def test_briefs_are_grounded_source_linked_and_synthetic_labelled(store):
    e = store.ingest([report()], now=STAMP)[0]
    brief = build_brief([e])
    assert "SYNTHETIC TRAINING DATA" in brief
    assert "https://a.example/news/a" in brief
    assert e["id"] in brief
    assert "No matching developments" in build_brief([])
    with pytest.raises(ValueError):
        build_brief([e], "yearly")


def test_complete_fictional_crisis_scenario(store):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "crisis.json").read_text())
    previous = None
    emitted = []
    for i, stage in enumerate(fixture["stages"]):
        events = store.ingest(stage["reports"], now=stage["at"])
        if stage.get("observations"):
            store.put_observations(stage["observations"])
        current = events[-1]
        reason = alert_reason(current, previous)
        if reason:
            # Dedup is tested separately; capture policy transitions here.
            emitted.append((i, reason))
        if i < 2:
            assert current["verification"] == "unverified"
            assert reason is None
        if i == 2:
            assert current["verification"] == "developing"
            assert reason.startswith("Developing")
        previous = current
    assert len(fixture["stages"]) == 10
    assert any(reason.startswith("Correction") for _, reason in emitted)
    assert any(reason.startswith("Retraction") for _, reason in emitted)
    assert len(previous["timeline"]) == 10
    assert previous["synthetic"] is True
    assert previous["contradictions"]
    assert previous["media"]
    assert any(r["language"] == "de" for r in previous["reports"])
    assert len(store.list_observations()) == 1


def test_radio_media_station_identity_survives_normalization_and_event_aggregation(store):
    tuned = report(
        media=[
            {
                "url": "https://receiver.example.org/tune",
                "title": "Receiver A 1000",
                "name": "Receiver A 1000",
                "provider": "Public receiver",
                "type": "radio",
                "receiver": "https://receiver.example.org/tune",
                "frequency": "1000 kHz",
                "mode": "AM",
            },
            {
                "url": "https://receiver.example.org/tune",
                "title": "Receiver A 2000",
                "name": "Receiver A 2000",
                "provider": "Public receiver",
                "type": "radio",
                "receiver": "https://receiver.example.org/tune",
                "frequency": "2000 kHz",
                "mode": "AM",
            },
            {
                "url": "https://receiver.example.org/directory",
                "title": "Directory only",
                "provider": "Directory",
                "type": "radio",
            },
        ]
    )
    normalized = normalize_report(tuned, now=STAMP)
    assert normalized["media"][0]["receiver"] == "https://receiver.example.org/tune"
    assert normalized["media"][0]["frequency"] == "1000 kHz"
    assert normalized["media"][0]["mode"] == "AM"
    assert normalized["media"][0]["name"] == "Receiver A 1000"
    assert "receiver" not in normalized["media"][2]
    assert "frequency" not in normalized["media"][2]
    assert "mode" not in normalized["media"][2]

    event = store.ingest([tuned], now=STAMP)[0]
    stations = [item for item in event["media"] if item["url"] == "https://receiver.example.org/tune"]
    assert len(stations) == 2
    assert {(item["frequency"], item["mode"]) for item in stations} == {
        ("1000 kHz", "AM"),
        ("2000 kHz", "AM"),
    }
    directory = next(item for item in event["media"] if item["url"] == "https://receiver.example.org/directory")
    assert "receiver" not in directory


def test_source_credit_and_unknown_publication_are_preserved(store):
    raw = report(official=True, published_at="", publication_time_unknown=True,
                 source_license="CC BY 3.0 https://creativecommons.org/licenses/by/3.0/",
                 byline="Fictional Reporter", attribution="Publisher and author credit required",
                 source_updated_at="2026-11-08T09:59:00Z", latitude=35, longitude=-30,
                 geo_precision="source_point", source_references=[{"id":"sensor","url":"https://sensor.example/record"}])
    e = store.ingest([raw], now=STAMP)[0]
    assert e["publication_time_known"] is False
    assert e["first_retrieved_at"] == STAMP
    saved = e["reports"][0]
    assert saved["byline"] == "Fictional Reporter"
    assert saved["source_references"][0]["id"] == "sensor"
    assert saved["geo_precision"] == "approximate"
    assert alert_reason(e) is None
    brief = build_brief([e])
    assert "CC BY 3.0" in brief and "Fictional Reporter" in brief
    assert "publication time unknown" in brief


def test_unverified_social_correction_does_not_generate_notice(store):
    e = store.ingest([report(kind="correction", correction_of="unknown")], now=STAMP)[0]
    assert alert_reason(e) is None


def test_archive_mode_is_persistent_and_cannot_be_switched(tmp_path):
    path = tmp_path / "archive.sqlite3"
    with Store(path, mode="live") as s:
        assert not s.ingest([report()], now=STAMP)
    with pytest.raises(ValueError, match="separate archives"):
        Store(path, mode="synthetic")


def test_distinct_provider_event_keys_do_not_fuzzy_merge_quakes(store):
    a = report("quake-a", event_key="usgs:quake-a", title="Magnitude four earthquake near Northhaven")
    b = report("quake-b", event_key="usgs:quake-b", title=a["title"], url="https://a.example/quake-b")
    events = store.ingest([a, b], now=STAMP)
    assert len(events) == 2
    assert events[0]["id"] != events[1]["id"]


def test_last_previous_events_contains_exact_preupdate_sources(store):
    first = store.ingest([report(summary="Original excerpt")], now=STAMP)[0]
    assert store.last_previous_events == {}
    store.ingest([report(summary="Revised excerpt")], now="2026-11-08T11:00:00Z")
    assert store.last_previous_events[first["id"]]["reports"][0]["summary"] == "Original excerpt"


def test_expiring_report_invalidates_derived_translation_cache(store):
    store.ingest([report(retention_days=1)], now=STAMP)
    store.set_setting("translation:somehash", "A translated version of the source report")
    store.set_setting("watchlist", ["Norland"])
    store.prune(now="2026-11-10T10:00:01Z")
    assert store.get_setting("translation:somehash") is None
    assert store.get_setting("watchlist") == ["Norland"]


def test_archive_iteration_has_no_interactive_result_limit(store):
    store.ingest([report(str(i), event_key=f"unique-{i}") for i in range(7)], now=STAMP)
    assert len(store.list_events(limit=3)) == 3
    all_events = list(store.iter_events(batch_size=3))
    assert len(all_events) == 7
    assert len({e["id"] for e in all_events}) == 7


def test_economic_provider_attribution_and_dates_preserved(store):
    record = dict(source_id="worldbank", indicator="Inflation", indicator_name="Consumer prices", country="Example", country_code="EX", date="2025", value=4.1, unit="percent", release_date=None, dataset_updated_at="2026-10-08", attribution="World Bank / IMF", source_note="Annual observed rate", url="https://data.example/series")
    store.put_observations([record])
    saved = store.list_observations()[0]
    assert saved["attribution"] == "World Bank / IMF"
    assert saved["country_code"] == "EX"
    assert saved["dataset_updated_at"] == "2026-10-08"
    assert saved["release_date"] == ""
    assert saved["observation_date"] == "2025"


def test_observations_cannot_mix_synthetic_and_live(store):
    store.set_setting("archive_mode", "live")
    store.put_observations([dict(indicator="Test",country="Example",date="2026",value=1,synthetic=True)])
    assert not store.list_observations()


def test_bulk_unrelated_live_news_without_event_keys_builds_complete_events(store):
    # Real RSS adapters supply batches of titles without upstream event IDs.
    # Every row after the first scans earlier, still-unmaterialized events.
    records = [report(str(i), event_key="", synthetic=False,
                      title=f"Regional infrastructure maintenance announcement number {i}",
                      summary=f"Local authority published maintenance notice {i}.",
                      url=f"https://news.example/notice/{i}") for i in range(80)]
    events = store.ingest(records, now=STAMP)
    assert len(events) == 80
    assert all(e["region"] == "North Atlantic" and e["report_count"] == 1 for e in events)
    assert store.stats()["reports"] == 80
    assert len(store.last_ingest_errors) == 0
    assert len(list(store.iter_events())) == 80


def test_multiple_correlated_and_unrelated_groups_in_one_fresh_batch(store):
    harbor = "Northhaven harbor cargo operations halted after regional power outage"
    hospital = "Southhaven public hospital announces equipment maintenance schedule"
    records = [
        report("a1", source_id="regional-a", event_key="", title=harbor,
               independence="original", origin_id="a-original", summary="Regional A witnessed harbor operations halted."),
        report("b1", source_id="medical-b", event_key="", title=hospital,
               independence="original", origin_id="b-original", summary="Medical B reports the hospital schedule."),
        report("a2", source_id="regional-c", event_key="", title="Update: " + harbor,
               independence="original", origin_id="c-original", summary="Regional C independently checked the harbor closure."),
        report("b2", source_id="medical-d", event_key="", title="Breaking: " + hospital,
               independence="original", origin_id="d-original", summary="Medical D independently reports hospital maintenance."),
    ]
    events = store.ingest(records, now=STAMP)
    assert len(events) == 2
    assert sorted(e["report_count"] for e in events) == [2, 2]
    assert all(e["verification"] == "developing" for e in events)
    assert {frozenset(r["id"] for r in e["reports"]) for e in events} == {frozenset({"a1","a2"}),frozenset({"b1","b2"})}
    assert all(len(e["timeline"]) == 1 for e in events)
