# Global Pulse source expansion — Brazil BCB first-party Atom admission (13 November 2026 UTC)

## Scope and safety
Engineering-only on source-expansion draft PR #7, stacked behind PR #6. Four new Banco Central do Brasil feeds, **one publisher family**. Updated catalog: **164 configurations, 131 enabled**. No account or API key, third-party proxy, paywall workaround, article-body scraping, linked-page fetch, media collection, merge or published release.

## Publisher rights and feed documentation
- [BCB official RSS subscription directory](https://www.bcb.gov.br/en/about/rssen) explicitly promotes official economic, press and market publications RSS subscriptions.
- [BCB terms: Reproduction of Content](https://www.bcb.gov.br/en/about/privacystatement), last displayed update February 24, 2022, permits complete/partial website reproduction **preserving integrity and citing BCB**, and authorizes direct links to the BCB website; BCB logos are separately restricted. We retain only original feed headline, date signal, source link and attribution; **no RSS summary/content, article body, images, video, logo or other media**.
- Language `pt`; region `South America`; country `Brazil` means publisher coverage **not** incident/event coordinates. `independence=original` does not mean different BCB sibling feeds independently corroborate each other; **`publisher_origin_id=br_bcb`** shared by all four.

## Date provenance: reviewed Atom `updated`, not first-publication evidence
BCB's first-party `application/atom+xml` entries omit `published` but include current, offset-aware `updated` values. On the unconfigured first Collector probe all four returned HTTP 200 and 10 parsed entries, but publication dates were **unknown**; correctly not admitted. [Raw first-party Atom date-tag diagnostics 43398561643](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43398561643) observed these exact first three timestamps:
- Press: 2026-11-12T08:30:13-03:00, 2026-11-12T08:25:25-03:00, 2026-11-11T14:30:47-03:00.
- News: 2026-11-10T10:54:49-03:00, 2026-11-05T11:51:03-03:00, 2026-11-03T15:59:43-03:00.
- Regulatory notices: 2026-11-12T18:30:17-03:00, 2026-11-12T18:30:06-03:00, 2026-11-12T11:47:08-03:00.
- Focus: 2026-11-06T00:00:00-03:00, 2026-10-30T00:00:00-03:00, 2026-10-23T00:00:00-03:00.

After explicit source-scoped `updated_is_publication_time=true` review, `published_at` represents the **publisher's feed release/last-updated time only**; it is **not proof of an article's first publication or an independent event**. `source_updated_at` is preserved and checked equal during current Collector audits. No retrieval-time substitution, and no generic promotion of Atom `updated` on other feeds. BCB Focus published document URLs embed DDMMYYYY; direct post-admission validation confirmed **zero date mismatches** between the link's report date and publisher's Atom local update date across 10 reports. Future QA must review display date labeling to prevent describing edits as first publication.

## First-party direct pre-enable Collector evidence
[BCB explicit Atom-time pre-admission Actions run 43398779454](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43398779454), before enabling any BCB config:

| Source ID and category | Direct feed URL | HTTP/status | Parsed | Dated within 30d | Latest timestamp UTC | Metadata/provenance violations |
| --- | --- | --- | ---: | ---: | --- | ---: |
| `br_bcb_press` Economy | https://www.bcb.gov.br/api/feed/sitebcb/sitefeeds/notasImprensa?ano=2021 | 200 available | 10 | 10 | 2026-11-12T11:30:13Z | 0 |
| `br_bcb_news` Economy | https://www.bcb.gov.br/api/feed/sitebcb/sitefeeds/noticias?ano=2024 | 200 available | 10 | 4 | 2026-11-10T13:54:49Z | 0 |
| `br_bcb_acts` Government | https://www.bcb.gov.br/api/feed/app/demaisnormativos/atosecomunicados?ano=2025 | 200 available | 10 | 10 | 2026-11-12T21:30:17Z | 0 |
| `br_bcb_focus` Economy | https://www.bcb.gov.br/api/feed/sitebcb/sitefeeds/focus | 200 available | 10 | 4 | 2026-11-06T03:00:00Z | 0 |

The `ano` query component on several old first-party feed URLs is historically labeled despite returning current 2026 entries; its stability needs periodic re-check. The explicit 30-day recency gate and daily source status must take precedence over any query-string inference. No fake second publisher family is introduced.

## Post-commit repeat from actual checked-out catalog
Catalog commit [2a167367c0292ce847ea1839c5b6373c4299ed79](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/2a167367c0292ce847ea1839c5b6373c4299ed79); read-only pinned workflow [`source-expansion-bcb-post-admission.yml`](https://github.com/dietrichailabs-oss/Global-News-Pulse/blob/eng/source-expansion-open-feeds-20261113/.github/workflows/source-expansion-bcb-post-admission.yml) and [offline test fixture](https://github.com/dietrichailabs-oss/Global-News-Pulse/blob/eng/source-expansion-open-feeds-20261113/tests/test_source_expansion_bcb.py).

[Exact-catalog post-admission Actions 43399330275](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43399330275):
- **19/19 offline tests PASS** across BCB Atom, ECB MID and existing publisher-origin non-corroboration regression.
- Four direct first-party live Collector rechecks all PASS, HTTP 200, 10 reports each, current respectively **10, 4, 10, 4**, zero metadata, original-link, attribution, geography, origin, timestamp or media violations.
- `br_bcb_focus`: 0/10 canonical URL-vs-update report-date mismatches.
- No downloaded original article bodies or linked media, even where Atom entries contain publisher summaries.

## Excluded and independent QA gate
AfDB still **403** and commercial reuse restricted; SARS South Africa technically current but site [terms](https://www.sars.gov.za/terms-and-conditions/) prohibit nonprivate/commercial redistribution and restrict direct deep links; neither enabled. INEGI needs a verifiable individual official RSS address. Reserve Bank of India deep linking requires advance consent. Existing broad source live audits have occasionally failed on transient Statistics Canada timeouts; focused BCB/ECB admissions are unaffected, but **do not claim a full catalog audit pass until an actual successful run**.

PR #7 remains **draft, open and unmerged**. Independent QA must check date presentation, rights/display attribution, BCB endpoint query longevity, user-perceived nonindependent corroboration, and outage behavior; no release authorization is inferred from this Engineering admission.
