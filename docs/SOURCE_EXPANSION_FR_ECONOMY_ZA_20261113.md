# France Economy / South Africa public RSS admission — 2026-11-13

**Scope:** engineering source admission on draft [PR #7](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/7), stacked behind owner-remediation PR. **No merge, release, article-body collection or media download. Independent QA remains required.**

## Publisher-documented discovery and reuse

| Source | Publisher documentation | Source rights | Origin and permitted fields |
|---|---|---|---|
| `fr_economie_portal` — [official RSS](https://www.economie.gouv.fr/rss/toutesactualites) | [Economic ministry RSS guide](https://www.economie.gouv.fr/rss) | [Ministry's legal notices](https://www.economie.gouv.fr/mentions-legales) provide Etalab Open Licence 2.0 for content excluding third-party rights, require source and update date; RSS syndication is specifically offered free to readers and webmasters with visible credit | `fr_economie`, Economy; headline, original link, publication date, attribution |
| `fr_economie_daj` — [official legal affairs RSS](https://www.economie.gouv.fr/daj/rss) | [Official ministry feed list](https://www.economie.gouv.fr/tous-les-fils-d-infos) | Same French Ministry of Economy syndication and license notice as above | `fr_economie`, Government; same metadata-only policy, **not a new independent corroborator** |
| `za_statssa_news` — [Stats SA publisher RSS](https://www.statssa.gov.za/?feed=rss2) | [South African Government's official list links Statistics South Africa RSS](https://www.gov.za/subscribe-mailing-lists) | [Stats SA's own official statistical publication, general information, p. 17](https://www.statssa.gov.za/publications/P62421/P62421September2025.pdf) permits use of the agency's statistical information with Stats SA base-data acknowledgment and distinguishing derived analysis. This evidence **does not** license copying website news bodies or photographs; those remain off | `statssa`, Economy, Africa; headline, original link, publication date, attribution only |

No account, API key, paywall workaround or third-party RSS relay. `metadata_only=true`; original per-item publisher URL/UTC publication and attribution retained, 1,800-second polling floor, 30-day freshness threshold, 180-day retention ceiling. Publisher-country classification is explicitly **publisher coverage**, not an event location. Government/agency declarations are not automatic confirmation of the asserted underlying event or economic causality.

## Live pre-enablement candidate probe

[Publisher-direct probe run 43362522885](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43362522885) completed **SUCCESS** against uncommitted candidate dictionaries, using the actual bounded `Collector` with the declared Global Pulse user agent, HTTPS allowlists and metadata-only parsing. Probe output:

| Candidate | HTTP | Parsed | Dated within 30 days | Latest publisher date (UTC) | Ingested body/media/provenance/link violations | Decision |
|---|---:|---:|---:|---|---:|---|
| France economy ministry portal | 200 | 10 | 10 | 2026-11-12T09:59:16Z | 0 | Admit |
| France DAJ legal affairs | 200 | 10 | 6 | 2026-11-03T15:19:17Z | 0 | Admit |
| South Africa Stats SA | 200 | 10 | 10 | 2026-11-05T11:10:10Z | 0 | Admit |
| France DGCCRF | 301 | 0 | 0 | None | N/A | **Reject:** redirect target outside tested allowlist; do not silently expand it or scrape |
| France TRACFIN | 200 | 10 | 0 | 2026-08-27T17:04:08Z | 0 | **Reject:** stale archive for 30-day news policy |

A successful exploratory HTTP response is not admission. All candidates remained unadmitted until the 3 supported sources passed direct Collector freshness and domain/provenance validation. Rejected sources were **not added to the enabled catalog**.

## Post-enablement proof

- Catalog commit [`df1369d9`](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/df1369d9f0b1bd77d5ed74d4101c7f67a55b860e): adds only the three prevalidated candidates, now 142 catalog entries, catalog version `2026.11.12.source-expansion12`.
- Offline tests commit [`4ef5527a`](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/4ef5527a1a3302d72868c50fc20d1a63876dfc59): five synthetic parser/provenance/no-body tests, including common `fr_economie` origin, original HTTPS link, update date, jurisdiction distinction, cross-domain rejection and explicit denied/stale candidate exclusion.
- Admission workflow commit [`c654cd23`](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/c654cd23c12ff37f0e4b6f4e53113b0d3b3e0088); [post-catalog live run 43362793466](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43362793466): **SUCCESS**, **5/5 pytest pass**; all three re-fetched using the checked-out source catalog:
  - `fr_economie_portal`: HTTP 200, 10 parsed/10 recent, 0 violations, `fr_economie`.
  - `fr_economie_daj`: HTTP 200, 10 parsed/6 recent, 0 violations, `fr_economie`.
  - `za_statssa_news`: HTTP 200, 10 parsed/10 recent, 0 violations, `statssa`.
- All three passed publication-date, attribution, media, copied-description, original-HTTPS-link, publisher-origin and metadata-only checks against the *real* Collector.
- Parser never retrieves linked news articles. Any later change to rights, access, publication recency or independence requires disabling or a fresh explicit review.

## Hold and next review

This is **Engineering** evidence, not independent legal signoff or an end-to-end app release. Independent QA should reassess Stats SA's site-wide copyright-versus-statistical-data language (metadata-only use specifically) and publisher-domain provenance. The ministry's two sibling feeds count as **one** publisher when assessing independent confirmation. Continue investigating independent licensed public health, humanitarian, conflict and infrastructure publishers; exclude any candidate without both live parser success and adequate metadata rights. PR #7 stays draft and unmerged.
