"""R20 owner feedback: richer bounded briefs, never stronger invented claims.

Production Store/formatting tests run without Qt or network. The renderer
regression additionally requires Qt; all evidence is synthetic. Physical
Windows and live-source verification remain separate requirements.
"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from global_pulse.brief_selection import (
    BRIEF_DOMAINS, balanced_brief_sections, brief_domain,
    overview_evidence_candidates, overview_html,
)
from global_pulse.core import Store, build_brief


NOW = "2026-11-20T14:00:00Z"
AT = "2026-11-20T13:00:00Z"


def item(number, category="News", **changes):
    result = {
        "id": f"synthetic-brief-{number}", "title": f"SYNTHETIC {category} update {number}",
        "category": category, "severity": "unassessed", "verification": "unverified",
        "status": "active", "region": "Synthetic region", "updated_at": AT,
        "published_at": AT, "recap": "Synthetic attributed report, not a verified world event.",
        "synthetic": True, "report_count": 1, "independent_origins": [],
        "reports": [{"id": f"report-{number}", "source_id": "synthetic-brief-provider",
                     "publisher": "Synthetic provider", "title": "Original report",
                     "summary": "Synthetic provider-supplied detail about a reported local development.",
                     "url": f"https://example.org/report/{number}", "published_at": AT,
                     "first_retrieved_at": AT, "retrieved_at": AT, "publication_time_known": True,
                     "evidence_status": "active", "independence": "unknown"}],
    }
    result.update(changes)
    return result


def render(events, period="daily", now=NOW):
    with patch("global_pulse.core.utcnow", return_value=now):
        return build_brief(events, period)


class DailyBriefDepthTests(unittest.TestCase):
    def test_daily_renders_eight_news_records_not_previous_four(self):
        page = render([item(i) for i in range(12)])
        story_headings = [line for line in page.splitlines() if line.startswith("### ") and ". SYNTHETIC" in line]
        self.assertEqual(len(story_headings), 8)
        self.assertIn("8 of 12 supplied local records", page)
        self.assertIn("4 additional supplied records", page)
        self.assertIn("Source-provided detail", page)
        self.assertIn("provider-supplied detail", page)

    def test_small_budget_represents_each_topic_before_second_item(self):
        events = [item(i * 10 + n, category) for i, category in enumerate(
            ("Conflict", "Unrest", "Health", "Government", "Economy", "Humanitarian", "Infrastructure", "News", "Weather"))
            for n in range(8)]
        sections = balanced_brief_sections(events, per_domain=8, max_total=9, disaster_limit=3)
        self.assertEqual([name for name, _ in sections], list(BRIEF_DOMAINS))
        self.assertTrue(all(len(rows) == 1 for _, rows in sections))

    def test_weather_flood_cannot_hide_other_topics_or_exceed_weather_budget(self):
        events = [item(i, "Weather", severity="critical") for i in range(500)]
        events += [item(600 + i, category) for i, category in enumerate(
            ("Conflict", "Unrest", "Health", "Government", "Economy", "Humanitarian", "Infrastructure", "News"))]
        page = render(events)
        for domain in BRIEF_DOMAINS:
            self.assertIn(f"## {domain}", page)
        self.assertEqual(sum("SYNTHETIC Weather update" in line and line.startswith("### ")
                             for line in page.splitlines()), 3)
        self.assertIn("bounded sample, not a global event count", page)

    def test_unassessed_importance_and_official_attribution_remain_separate(self):
        statement = item(1, "Government", official_attribution=True,
                         reasons=["Unknown provenance is not counted as independence."])
        measurement = item(2, "Weather", verification="official", severity="moderate")
        before = deepcopy([statement, measurement])
        page = render([statement, measurement])
        self.assertIn("UNASSESSED means", page)
        self.assertIn("1 official measurement(s)", page)
        self.assertIn("1 unverified record(s)", page)
        self.assertIn("Official-source attribution", page)
        self.assertIn("does not independently verify its underlying claims", page)
        self.assertEqual([statement, measurement], before)
        self.assertEqual(statement["verification"], "unverified")
        self.assertEqual(statement["severity"], "unassessed")

    def test_window_and_source_offset_are_explicitly_utc(self):
        event = item(1, updated_at="2026-11-20T03:00:00Z")
        event["reports"][0]["published_at"] = "2026-11-19T21:45:00-05:00"
        page = render([event], now="2026-11-20T04:00:00Z")
        self.assertIn("2026-11-19T04:00:00Z through 2026-11-20T04:00:00Z", page)
        self.assertIn("rolling last 24 hours, not a calendar-day total", page)
        self.assertIn("source published 2026-11-20T02:45:00Z", page)
        self.assertIn("**2026-11-20:** 1 selected record(s)", page)
        self.assertIn("not asserted event-occurrence or publication dates", page)

    def test_unknown_publication_keeps_first_retrieval_label(self):
        event = item(1)
        event["reports"][0].update(publication_time_known=False,
                                   published_at="2026-11-20T13:50:00Z",
                                   first_retrieved_at="2026-11-20T12:00:00Z")
        page = render([event])
        self.assertIn("publication time unknown; first retrieved 2026-11-20T12:00:00Z", page)
        self.assertNotIn("source published 2026-11-20T13:50:00Z", page)

    def test_only_actual_in_window_changes_are_shown_once(self):
        change = {"kind": "correction", "publisher": "Synthetic source",
                  "report_id": "one", "title": "Provider revised its estimate", "at": AT}
        event = item(1, changes=[dict(change)], timeline=[
            {"at": AT, "changes": [dict(change)]},
            {"at": "2026-11-18T14:00:00Z", "changes": [dict(change, at="2026-11-18T14:00:00Z", title="Too old")]},
            {"at": "2026-11-21T14:00:00Z", "changes": [dict(change, at="2026-11-21T14:00:00Z", title="Future correction")]},
        ])
        page = render([event])
        self.assertEqual(page.count("Provider revised its estimate"), 1)
        self.assertNotIn("Too old", page)
        self.assertNotIn("Future correction", page)
        self.assertIn("Recorded changes during this window", page)

    def test_historical_and_future_context_not_presented_as_new_today(self):
        page = render([item(1, updated_at="2026-11-18T13:00:00Z"),
                       item(2, updated_at="2026-11-21T13:00:00Z", future_dated=True)])
        self.assertIn("Historical context", page)
        self.assertIn("not presented as new today", page)
        self.assertIn("Future-dated context", page)
        self.assertIn("not evidence of a current development", page)

    def test_source_metadata_is_escaped_links_validated_and_budgets_bounded(self):
        event = item(1, title="<script>bad</script> **source title**", recap="x" * 6000)
        base = event["reports"][0]
        event["reports"] = [dict(base, id=str(i), source_id=f"fixture-{i}",
                                 publisher="<img src=x onerror=alert(1)> **P**", summary="Detail " + "y" * 2000,
                                 url=f"https://example.org/report/{i}") for i in range(30)]
        event["reports"][0]["url"] = "javascript:alert(1)"
        page = render([event])
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img", page)
        self.assertNotIn("javascript:", page)
        self.assertIn(r"\*\*source title\*\*", page)
        self.assertEqual(sum("unknown provenance." in line for line in page.splitlines()), 8)
        self.assertIn("22 additional source record(s)", page)
        self.assertLess(len(page), 16000)

    def test_entity_encoded_source_markup_stays_text(self):
        event = item(1, title="&amp;lt;img src=x onerror=alert(1)&amp;gt;")
        event["reports"][0]["url"] = 'https://example.org/report/<tag>"value'
        page = render([event])
        self.assertNotIn("<img", page)
        self.assertNotIn("<tag>", page)
        self.assertIn("%3Ctag%3E%22value", page)

    def test_actual_store_distinguishes_statement_measurement_and_independence(self):
        with TemporaryDirectory() as directory:
            with Store(Path(directory).resolve() / "brief.sqlite3", mode="synthetic") as store:
                def raw(number, **kw):
                    return {"id": str(number), "source_id": f"synthetic-{number}", "publisher": "Fictional publisher",
                            "title": f"SYNTHETIC record {number}", "summary": f"Fictional provider metadata {number}.",
                            "url": f"https://example.org/brief/{number}", "published_at": AT, "retrieved_at": AT,
                            "category": "Government", "severity": "unassessed", "synthetic": True,
                            "event_key": f"synthetic-event-{number}", "official": True,
                            "official_scope": "statement", **kw}
                store.ingest([raw(1), raw(2, category="Weather", official_scope="measurement", severity="moderate")], now=AT)
                events = store.list_brief_events(since="2026-11-19T14:00:00Z", per_domain=8)
                page = render(events)
                self.assertEqual({e["verification"] for e in events}, {"unverified", "official"})
                self.assertIn("1 official measurement(s)", page)
                self.assertIn("1 unverified record(s)", page)
                self.assertIn("source published", page)
                self.assertIn("Fictional provider metadata", page)

    def test_empty_weekly_and_unknown_category_remain_honest(self):
        self.assertIn("No matching developments", render([]))
        page = render([item(1, "Unrecognized category")], "weekly")
        self.assertIn("rolling last 7 days", page)
        self.assertIn("## General news", page)
        self.assertIn("coverage gap, not evidence that no events occurred", page)


class WorldOverviewFeedbackTests(unittest.TestCase):
    """The Monitor overview has its own shortlist, not Daily Brief's renderer."""

    @staticmethod
    def regulatory(number, title="Orphan designation: SYNTHETIC medicine application"):
        event = item(number, "Health", title=title)
        event["reports"][0]["title"] = title
        event["recap"] = "Synthetic regulator reports application paperwork, not a health incident."
        return event

    def test_recent_routine_notices_do_not_evict_older_health_situations(self):
        paperwork = [self.regulatory(i) for i in range(6)]
        situations = [item(20 + i, "Health", updated_at="2026-11-20T12:00:00Z",
                           title=f"SYNTHETIC health advisory {i}") for i in range(2)]
        original = deepcopy(paperwork + situations)
        selected = overview_evidence_candidates(paperwork, paperwork + situations)
        self.assertEqual({e["id"] for e in selected}, {e["id"] for e in situations})
        self.assertEqual(paperwork + situations, original)
        self.assertIn("health advisory 0", overview_html(paperwork + situations))
        self.assertNotIn("SYNTHETIC medicine application", overview_html(paperwork + situations))

    def test_only_routine_health_is_separate_background_not_outbreak_coverage(self):
        events = [self.regulatory(1), self.regulatory(2,
            "Opinion/decision on a Paediatric investigation plan (PIP): SYNTHETIC")]
        original = deepcopy(events)
        page = overview_html(events)
        before_background, background = page.split("<b style='color:#bec6dc'>Routine medicines/regulatory notices", 1)
        self.assertNotIn("SYNTHETIC medicine application", before_background)
        self.assertIn("Only routine medicines/regulatory notices", before_background)
        self.assertIn("SYNTHETIC medicine application", background)
        self.assertIn("pulse-event://open/synthetic-brief-1", background)
        self.assertIn("not presented as outbreak or incident coverage", before_background)
        self.assertIn("Coverage gap", page)
        self.assertEqual(events, original)
        self.assertEqual(events[0]["category"], "Health")
        self.assertEqual(events[0]["verification"], "unverified")

    def test_background_notices_share_the_original_sixteen_card_total(self):
        categories = ("Conflict", "Unrest", "Health", "Government", "Economy",
                      "Humanitarian", "Infrastructure", "News", "Weather")
        events = []
        for index, category in enumerate(categories):
            events.extend(self.regulatory(index * 2 + offset) if category == "Health"
                          else item(index * 2 + offset, category) for offset in range(2))
        original = deepcopy(events)
        selected = overview_evidence_candidates(events, [])
        self.assertEqual(len(selected), 18)
        self.assertEqual({e["id"] for e in selected}, {e["id"] for e in events})
        page = overview_html(selected)
        self.assertEqual(page.count("href='pulse-event://open/"), 16)
        background = page.split("<b style='color:#bec6dc'>Routine medicines/regulatory notices", 1)[1]
        for number in (4, 5):
            self.assertIn(f"pulse-event://open/synthetic-brief-{number}", background)
        for category in categories:
            if category == "Health":
                continue
            identities = [e["id"] for e in events if e["category"] == category]
            self.assertTrue(any(f"pulse-event://open/{identity}" in page for identity in identities),
                            f"The background budget hid the represented {category} topic")
        self.assertEqual(events, original)

    def test_safety_alerts_and_mixed_reporting_are_not_hidden_as_paperwork(self):
        alert = self.regulatory(1, "SYNTHETIC urgent recall following an orphan designation")
        mixed = self.regulatory(2)
        mixed["reports"].append(dict(mixed["reports"][0],
                                    title="SYNTHETIC new safety warning", id="new-warning"))
        page = overview_html([alert, mixed])
        self.assertIn("SYNTHETIC urgent recall", page)
        self.assertIn("SYNTHETIC medicine application", page)
        self.assertNotIn("Routine medicines/regulatory notices</b>", page)
        self.assertEqual(len(overview_evidence_candidates([alert, mixed], [])), 2)

    def test_detail_attribution_dates_and_importance_do_not_upgrade_claims(self):
        event = item(1, "Government", official_attribution=True,
                     updated_at="2026-11-20T15:00:00Z",
                     recap="Fictional government reports an unconfirmed policy proposal.")
        event["reports"][0]["published_at"] = "2026-11-20T09:00:00+00:00"
        page = overview_html([event])
        self.assertIn("Fictional government reports an unconfirmed policy proposal", page)
        self.assertIn("Importance: unassessed", page)
        self.assertIn("Evidence: unverified; independent corroboration not established", page)
        self.assertIn("Official publication present", page)
        self.assertIn("source published 2026-11-20T09:00:00+00:00", page)
        self.assertNotIn("source published 2026-11-20T15:00", page)
        self.assertEqual(event["verification"], "unverified")

    def test_unknown_publication_time_remains_unknown_and_future_context_labeled(self):
        event = item(1, "Health", future_dated=True)
        event["reports"][0].update(publication_time_known=False,
                                   published_at="2026-12-10T00:00:00Z", future_dated=True)
        page = overview_html([event])
        self.assertIn("first retrieved " + AT, page)
        self.assertIn("publication unknown", page)
        self.assertIn("Future-dated source context", page)
        self.assertNotIn("source published 2026-12-10", page)

    def test_existing_categories_not_headline_keywords_determine_topic(self):
        event = item(1, "News", title="SYNTHETIC war and protest headline")
        page = overview_html([event])
        self.assertEqual(brief_domain(event), "General news")
        general = page.index("General news</b>")
        self.assertGreater(page.index("SYNTHETIC war and protest headline"), general)
        self.assertIn("local coverage gap is not a worldwide all-clear", page)

    @staticmethod
    def peace_topic(number=90):
        event = item(number, "News", title="SYNTHETIC peace talks source statement")
        event["reports"][0].update(source_id="un_peace_security", origin_id="un_news",
                                   publisher="United Nations News — Peace and Security",
                                   official=True, official_scope="statement",
                                   url="https://news.un.org/en/story/synthetic-test")
        return event

    def test_exact_publisher_topic_groups_only_overview_without_new_claims(self):
        event = self.peace_topic()
        original = deepcopy(event)
        page = overview_html([event])
        before_unrest = page.split("Unrest &amp; civil affairs</b>", 1)[0]
        self.assertIn("SYNTHETIC peace talks source statement", before_unrest)
        self.assertIn("Grouped by source topic", before_unrest)
        self.assertIn("does not establish an active conflict", before_unrest)
        self.assertIn("pulse-event://open/synthetic-brief-90", before_unrest)
        self.assertIn("Importance: unassessed", before_unrest)
        self.assertIn("Evidence: unverified", before_unrest)
        self.assertEqual(event, original)
        self.assertEqual(brief_domain(event), "General news")
        self.assertEqual(dict(balanced_brief_sections([event])), {"General news": [event]})

    def test_generic_or_spoofed_source_topic_is_not_a_conflict_category(self):
        changes = [
            {"source_id": "un_news"}, {"source_id": "crisisgroup_global"},
            {"source_id": "user-un_peace_security"}, {"origin_id": "different-origin"},
            {"official": False}, {"official_scope": "measurement"},
            {"url": "https://news.un.org.attacker.test/en/story/test"},
            {"url": "https://user@news.un.org/en/story/test"},
            {"url": "https://news.un.org:444/en/story/test"},
            {"url": "http://news.un.org/en/story/test"},
        ]
        for change in changes:
            with self.subTest(change=change):
                event = self.peace_topic()
                event["reports"][0].update(change)
                page = overview_html([event])
                self.assertNotIn("Grouped by source topic", page)
                self.assertGreater(page.index("SYNTHETIC peace talks source statement"),
                                   page.index("General news</b>"))

    def test_publisher_topic_applies_before_the_general_news_candidate_cap(self):
        event = self.peace_topic()
        event["updated_at"] = "2026-11-19T12:00:00Z"
        general = [item(i, "News") for i in range(6)]
        selected = overview_evidence_candidates(general, general + [event])
        self.assertEqual(len(selected), 3)
        self.assertIn(event["id"], {e["id"] for e in selected})
        self.assertTrue(all(e["category"] == "News" for e in selected))

    def test_existing_configured_topic_feed_to_store_to_overview_preserves_news(self):
        from global_pulse.sources import load_catalog, parse_feed
        source = next(s for s in load_catalog() if s["id"] == "un_peace_security")
        original_source = deepcopy(source)
        report = parse_feed(b'''<rss><channel><item>
            <guid>offline-synthetic-un-topic</guid>
            <title>SYNTHETIC peace talks announcement</title>
            <link>https://news.un.org/en/story/offline-synthetic-un-topic</link>
            <pubDate>Fri, 20 Nov 2026 13:00:00 GMT</pubDate>
            <description>Unused source body remains excluded by metadata-only policy.</description>
            </item></channel></rss>''', source, AT)[0]
        report["synthetic"] = True
        with TemporaryDirectory() as directory:
            with Store(Path(directory).resolve() / "topic.sqlite3", mode="synthetic") as store:
                store.ingest([report], now=AT)
                feed = store.list_events()
                original_events = deepcopy(feed)
                page = overview_html(overview_evidence_candidates(feed, []))
                self.assertIn("Grouped by source topic", page)
                self.assertIn("SYNTHETIC peace talks announcement", page)
                self.assertNotIn("Unused source body", page)
                self.assertEqual(feed, original_events)
                self.assertEqual(feed[0]["category"], "News")
                self.assertEqual(feed[0]["severity"], "unassessed")
                self.assertEqual(feed[0]["verification"], "unverified")
                self.assertEqual(store.list_events()[0]["category"], "News")
                self.assertEqual(source, original_source)

    def test_details_are_bounded_escaped_and_only_link_local_record_ids(self):
        event = item(1, "Health", recap="<img src=https://example.org/image> " + "x" * 9000,
                     title='<script>unsafe</script>', id='unsafe/<id>"')
        page = overview_html([event], label="<b>local</b>")
        self.assertNotIn("<img", page)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;img", page)
        self.assertIn("&lt;b&gt;local&lt;/b&gt;", page)
        self.assertIn("pulse-event://open/unsafe%2F%3Cid%3E%22", page)
        self.assertLess(len(page), 9000)

    def test_actual_store_health_projection_keeps_metadata_and_better_record(self):
        with TemporaryDirectory() as directory:
            with Store(Path(directory).resolve() / "overview.sqlite3", mode="synthetic") as store:
                reports = []
                for number in range(4):
                    title = (f"Orphan designation: SYNTHETIC application {number}"
                             if number < 3 else "SYNTHETIC public health advisory")
                    reports.append({"id": str(number), "source_id": f"overview-{number}",
                        "publisher": "Synthetic regulator", "title": title,
                        "summary": "Synthetic provider detail; no real-world health claim.",
                        "url": f"https://example.org/overview/{number}", "language": "en",
                        "published_at": AT, "retrieved_at": AT, "category": "Health",
                        "severity": "unassessed", "synthetic": True,
                        "event_key": f"overview-event-{number}", "official": True,
                        "official_scope": "statement"})
                store.ingest(reports, now=AT)
                feed = store.list_events()
                selected = overview_evidence_candidates(feed, [])
                page = overview_html(selected)
                self.assertIn("SYNTHETIC public health advisory", page)
                self.assertIn("Synthetic regulator reports", page)
                self.assertIn("Official publication present", page)
                self.assertEqual(len(selected), 2)
                self.assertTrue(all(e["category"] == "Health" for e in selected))
                self.assertTrue(all(e["verification"] == "unverified" for e in selected))
                self.assertEqual(len(store.list_events()), 4)


class DailyBriefRenderingTests(unittest.TestCase):
    def test_dark_preview_and_standalone_html_keep_readable_safe_source_links(self):
        from PySide6.QtGui import QColor, QTextDocument
        from PySide6.QtWidgets import QApplication
        from global_pulse.brief_rendering import brief_html
        from global_pulse.theme import PANEL, PURPLE, SEVERITY, TEXT
        app = QApplication.instance() or QApplication([])
        event = item(1, severity="high", title="SYNTHETIC &amp;lt;img src=x&amp;gt; source")
        event["reports"][0]["summary"] = "Synthetic excerpt <img src=https://example.org/not-an-image> **not markup**"
        event["reports"].append(dict(event["reports"][0], id="unsafe", url="javascript:alert(1)"))
        with patch("global_pulse.core.utcnow", return_value=NOW):
            html = brief_html([event])
        document = QTextDocument()
        document.setHtml(html)
        self.assertEqual(document.rootFrame().frameFormat().background().color(), QColor(PANEL))
        self.assertIn(f'bgcolor="{PANEL}"', html)
        self.assertNotIn("javascript:", html)
        anchors = []
        severity_colors = []
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    form = fragment.charFormat()
                    self.assertFalse(form.isImageFormat(), "Source markup became a remote resource")
                    if form.isAnchor():
                        anchors.append(form.anchorHref())
                        self.assertEqual(form.foreground().color(), QColor(PURPLE))
                        self.assertTrue(form.fontUnderline())
                    if fragment.text() == "HIGH":
                        severity_colors.append(form.foreground().color())
                iterator += 1
            block = block.next()
        self.assertTrue(anchors)
        self.assertEqual(set(anchors), {"https://example.org/report/1"})
        self.assertEqual(severity_colors, [QColor(SEVERITY["high"])])

        def luminance(color):
            rgb = QColor(color).getRgbF()[:3]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
            return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))

        for foreground in (PURPLE, TEXT):
            contrast = (luminance(foreground) + .05) / (luminance(PANEL) + .05)
            self.assertGreaterEqual(contrast, 4.5)
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
