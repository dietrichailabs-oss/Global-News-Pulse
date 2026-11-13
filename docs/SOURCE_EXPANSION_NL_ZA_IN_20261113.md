# Publisher-direct Netherlands CBS and South Africa SAnews source admission — 2026-11-13

**Engineering-only scope:** draft [PR #7](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/7) stacked behind owner-remediation PR #6. No merge, release, account/key, scraping, third-party relay or permission-bypass. Independent QA and display-rights review remain pending.

## Official directories and rights

- [Statistics Netherlands (CBS) publisher RSS directory](https://www.cbs.nl/en-gb/rss-feeds) **expressly authorizes embedding latest RSS headlines on a third-party site** with visible source credit; [CBS copyright](https://www.cbs.nl/en-gb/about-us/website/copyright) provides CC BY 4.0 for ordinary CBS-owned website content and excludes marked third-party assets, photos, branding and logo use. No such assets retained.
- [South African Government SAnews RSS links](https://www.sanews.gov.za/content/sa-news) identify two first-party feeds. The same publisher page explicitly permits news media to reuse material for free **with SAnews credited**; conservative integration retains only article headline, original URL, date and publisher credit, never the full copy or media. Source agency is the Government Communication and Information System (GCIS).
- [India PIB RSS directory](https://www.pib.gov.in/ViewRss.aspx?lang=1&reg=1) and [PIB copyright policy](https://www.pib.gov.in/content/3604_2_CopyrightPolicy.aspx?lang=1&reg=3) document free attributed reuse. **However both direct press-feed endpoints returned HTTP 403 under the standard Collector identity, so both are excluded; no account, custom identity, scraper or alternative relay.**
- [Australian Bureau of Meteorology RSS](https://www.bom.gov.au/rss/) explicitly states **personal, non-commercial use only**, so not admitted into this potential commercial service. Rights restrictions are a hard stop regardless of topical value.

## Direct pre-enable collector evidence

[Pre-admission workflow run 43375511404](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43375511404) — completed SUCCESS, using locked dependencies and the actual bounded metadata-only Collector with its normal client identity. Its success indicates the probe ran, **not** that every candidate was admitted.

| Candidate | HTTP | Parsed | Dated within 30d | Latest UTC | Decision |
|---|---:|---:|---:|---|---|
| CBS all news | 200 | 50 | 36 | 2026-11-13 06:30 (future-dated at probe; do not treat as published current news) | Admit; recent nonfuture reports also verified |
| CBS economy | 200 | 50 | 21 | 2026-11-12 06:30 | Admit |
| CBS health/welfare | 200 | 50 | 2 | 2026-11-13 06:30 (future-dated at probe) | Admit; nonfuture recent reports verified |
| CBS manufacturing/energy | 200 | 50 | 2 | 2026-11-10 06:30 | Admit |
| SAnews South Africa news | 200 | 10 | 10 | 2026-11-12 16:38 | Admit |
| SAnews features | 200 | 10 | 6 | 2026-11-03 09:36 | Admit |
| PIB English RSS Regid=1 | **403** | 0 | 0 | none | **Exclude; access denial** |
| PIB English RSS Regid=3 | **403** | 0 | 0 | none | **Exclude; access denial** |

Probe reports **zero** metadata leakage, media copying, missing publisher dates/credit, original-URL inequality, disallowed HTTPS article hosts or origin violations among the six admitted candidates.

## Runtime / provenance and QA boundaries

- All four CBS feeds share `publisher_origin_id=nl_cbs`; both SAnews feeds share `publisher_origin_id=za_sanews`. **Six endpoints represent two independent publisher families**, not six corroborators.
- `metadata_only=true`; `min_interval=3600` seconds; `stale_after_days=30`; `retention_days=180`; source country is publisher coverage, not claim/event geolocation.
- CBS's provider-published future datestamps require explicit caution: recency uses only timestamps no later than the current UTC probe clock, and news UI must not present future-dated items as past/current event evidence.
- Synthetic tests assert original HTTPS links, original dates, per-family origin IDs, no copied descriptions, article bodies, enclosures or cross-host links. Two denied PIB candidates are absent from the enabled catalog.
- Post-admission workflow `.github/workflows/source-expansion-nl-za-admission.yml` must independently pass **both** focused parser/origin tests and all six real checked-out catalog fetches. Engineering verification is not independent legal/QA approval.

No application runtime feature, remediation fix, release artifact or install package changed.
