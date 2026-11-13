# Global Pulse source expansion: Federal Reserve topical RSS; Australia, European Parliament and GOV.UK exclusions (2026-11-13 UTC)

## Scope / release gate

Engineering-only source-expansion batch for [draft PR #7](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/7), stacked behind remediation PR #6. **No merge, installer, release, feed mirroring, scraping, third-party media, keys, or overrides of publisher access controls.** The reviewed catalog is now **170 configurations / 130 enabled**, from 168 / 128, on catalog version `2026.11.13.source-expansion23`. This batch adds **2 feeds but 0 new independently corroborating publisher families**. QA, continuing publisher reliability and rights/display review remain required.

The only two newly admitted feeds belong to the Board of Governors of the Federal Reserve System and therefore **share `publisher_origin_id=federal_reserve_press` with the already-enabled `federal_reserve_press` all-press feed**. That existing record now also explicitly declares `publisher_origin_id`, retaining the same effective origin string as the prior parser fallback. A story repeated in multiple Board feeds must never count as independent confirmation.

## Rights and publisher documentation

- [Board's official RSS directory](https://www.federalreserve.gov/feeds/feeds.htm): directly lists the banking/consumer policy, enforcement, monetary, orders and other topic feeds, intended for RSS aggregators.
- [Board disclaimer / copyright and linking policy](https://www.federalreserve.gov/disclaimer.htm): unless otherwise noted, the Board's own information is public domain, may be copied/distributed with a citation to the Board. Third-party photos and graphics require their respective rights, and Board seals/logos are protected. Attribution does not imply endorsement.
- Intake is strictly publisher headline, publisher publication timestamp, direct original Board article hyperlink, constant source credit; descriptions/article summaries/bodies, embedded images/audio/video, external media, site framing, and logos are **not** retained.
- Feed original article URLs remain restricted to `www.federalreserve.gov`, and fetched publisher endpoints are restricted to HTTPS `www.federalreserve.gov`. Country denotes **publisher jurisdiction**, not event coordinates or incident geography. The Board's statement is not proof that a third party has independently verified the underlying claim.

## Exact pre-admission direct Collector evidence

[US Federal Reserve pre-admission run 43423791348](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43423791348) used the real bounded Collector (not manual guesses) against the Board's documented RSS URLs before either feed was enabled. Existing offline provenance/parser regression tests: **26 passed**.

| Feed | Direct URL | HTTP | Reports | Last 30 days | Last publication (UTC) | Decision |
| --- | --- | ---: | ---: | ---: | --- | --- |
| Enforcement actions `fed_enforcement` | https://www.federalreserve.gov/feeds/press_enforcement.xml | 200 | 15 | 3 | 2026-11-12 16:00 | **Admitted**; zero detected violations |
| Monetary policy `fed_monetary` | https://www.federalreserve.gov/feeds/press_monetary.xml | 200 | 15 | 2 | 2026-11-12 17:45 | **Admitted**; zero detected violations |
| Banking/consumer policy `fed_bcreg` | https://www.federalreserve.gov/feeds/press_bcreg.xml | 200 | 15 | 0 | 2026-10-02 20:00 | **Rejected**; stale |
| Banking orders `fed_orders` | https://www.federalreserve.gov/feeds/press_orders.xml | 406 | 0 | 0 | — | **Rejected**; HTTP error |
| Other Board announcements `fed_other` | https://www.federalreserve.gov/feeds/press_other.xml | 406 | 0 | 0 | — | **Rejected**; HTTP error |

All five share the same underlying Board publisher, not independent corroboration. No stale/HTTP-406 feed was enabled, and no alternate client, spoofing or scrape bypass was used. Sample authentic publisher original-link evidence: https://www.federalreserve.gov/newsevents/pressreleases/enforcement20261112a.htm and https://www.federalreserve.gov/newsevents/pressreleases/monetary20261112a.htm.

## Post-admission gate and code provenance

- [Admission catalog commit e20230f](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/e20230fea0f4a3ee0619769bbc959739cb511e9b): two enabled `metadata_only` records, hourly min fetch interval, 30-day stale threshold, 90-day retention, direct publisher domains, fixed attribution, documented rights and shared origin.
- [Explicit existing-origin commit 88f8132](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/88f81329434578c6cab6bf7f344b42334c3cb0ac): pins the existing Board all-press feed to `publisher_origin_id=federal_reserve_press` without changing its effective parsed origin; prevents independent-count inflation.
- `tests/test_source_expansion_fed_topics.py`: exact catalog metadata/license/origin, source publication date, headline, source-only original link, no body/summary/media, refusal of nonpublisher URLs, and all-press sibling independence assertions.
- `.github/workflows/source-expansion-fed-topics-post-admission.yml`: reruns parser/provenance regressions and actual direct live Collector against both enabled catalog records.
- [First post-admission run 43424123069](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43424123069): **30/30 offline tests passed; 2/2 direct live reads passed**, each HTTP 200 and 15 reports with 3 / 2 reports in the past 30 days, zero detected provenance, original-link or media violations. Results have identical `publisher_origin_id=federal_reserve_press`. Later exact-head rerun must be checked separately before QA sign-off.
- [Broader catalog source audit run 43423979811](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43423979811): **completed successfully** for first admission-catalog commit; a further audit against the explicit origin-head is a separate gate. Seven previously quarantined New Zealand Beehive feeds remain disabled and were not re-fetched through the denied host.
- Any successful Action result for a *probe* is evidence that the probe script ran to completion, **not** evidence that every candidate passed source admission.

## International source experiments: live exclusions, no catalog additions

### Australia: DSS / DTA

[Probe 43422662057](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43422662057) ran **26/26 offline baseline tests**, then directly attempted four RSS URLs through the same bounded Collector: `https://www.dss.gov.au/rss/updates.xml`, `https://www.dss.gov.au/rss/resources.xml`, `https://www.dta.gov.au/news-and-blogs/latest/feed/news_item`, `https://www.dta.gov.au/news-and-blogs/latest/feed/all`. All **4/4 timed out** with no HTTP response or accepted records on November 13 at 12:09 UTC. No candidate enabled. Permission to attribute, even if established, does not make an unreliable endpoint eligible.

### European Parliament

[Probe 43423123088](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43423123088) ran **26/26 offline baseline tests**, then four official European Parliament RSS candidates: `press-releases`, `press-releases-plenary`, `press-releases-committees` and `top-stories`, each under `https://www.europarl.europa.eu/rss/doc/.../en.xml`. All **4/4 returned HTTP 403** at 12:12 UTC. **No feed admitted.** Respect the access denial; do not use proxy, alternate identity, scraper or repeated sibling re-probes to defeat it.

### UK government departments

[Probe 43423364585](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43423364585) ran **26/26 offline tests** and directly collected department Atom feeds from `department-for-work-pensions.atom`, `environment-agency.atom`, `hm-revenue-customs.atom` on `www.gov.uk`. All three returned **HTTP 200 with 20 titles and publisher-domain original links each**, **but 0 verifiable publication timestamps and 0 confirmed recent records**, so each failed the date/provenance admission gate (20 failures each). Existing global parser correctly refuses to silently infer `published_at` from Atom `updated` without a publisher-specific opt-in proving the date semantics. **None enabled**; do not mislabel source modification times as publication times.

## QA and follow-up / no release

1. Review Board-attribution presentation, protected seals/media exclusions, Board use notice, and correction/republishing date semantics.
2. Recheck active Board endpoint stability over multiple normal polling intervals; verify if topical titles materially add unique discovery versus the pre-existing all-press feed. All Board feeds still contribute **one** corroborating publisher family.
3. Check latest exact-head post-admission + broader audit job conclusions (not only workflow-trigger status). Distinguish suppressed/blocked sources from active.
4. Resolve GOV.UK Atom dated-event semantics only with legitimate publisher docs; never globally substitute `updated` for `published`.
5. Do not retry Australia timeouts or European Parliament HTTP 403 with evasion, and do not restore seven NZ access-denied feeds without genuine host recovery and normal hold.
6. PR #7 stays draft, stacked behind PR #6. Independent QA remains necessary; no merge or release approved.
