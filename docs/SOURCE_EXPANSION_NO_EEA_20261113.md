# Statistics Norway / European Environment Agency open RSS admission — 2026-11-13

**Engineering-only draft PR #7; stacked behind PR #6. No merge, release, media or article-body scraping. Independent QA is still required.**

## Publisher documentation and rights (first-party)

| Source | Official feed documentation and rights | Scope and origin |
|---|---|---|
| `norway_ssb_latest` — [RSS](https://www.ssb.no/en/rss/) | [SSB's official RSS guide](https://www.ssb.no/en/diverse/rss); [SSB CC BY 4.0 licence](https://www.ssb.no/en/diverse/lisens), expressly permits commercial reuse with attribution, licence link and change notice; excludes third-party photographs and confidential material | Norway, Economy, `norway_ssb`; publisher says latest feed shows last 3 days |
| `norway_ssb_labour` — [RSS](https://www.ssb.no/en/rss/arbeid-og-lonn) | Same official SSB guide: topic-specific feed covers up to 90 days; same CC BY 4.0 licence | Norway, Economy, **same** `norway_ssb` |
| `norway_ssb_energy` — [RSS](https://www.ssb.no/en/rss/energi-og-industri) | Same official SSB guide and licence; no separately-owned source merely because topic differs | Norway, energy/industry statistics; **same** `norway_ssb`; not an outage signal |
| `eea_press_releases` — [RSS](https://www.eea.europa.eu/en/newsroom/rss-feeds/eeas-press-releases-rss/rss.xml) | [EEA official RSS directory](https://www.eea.europa.eu/en/newsroom/rss-feeds); [EEA legal notice](https://www.eea.europa.eu/en/legal-notice): EEA-owned material CC BY, commercial reuse with EEA source and intact meaning; third-party exceptions | European environment/health/climate news, `eu_eea` |
| `eea_publications` — [RSS](https://www.eea.europa.eu/en/newsroom/rss-feeds/publications-rss/rss.xml) | Same EEA first-party directory, legal notice and CC BY terms | Europe-wide reports, **same** `eu_eea`; never an independent confirmation of another EEA feed |

All admitted endpoints are first-party HTTPS RSS, do not need an account/API key, use bounded official Global Pulse Collector and host allowlists, store only feed headline + publication date + original publisher link + attribution, and have a 1,800-second minimum poll interval, 30-day current-news freshness threshold and <=180-day retention.

## **Before enablement**: publisher-direct live Collector

Pre-admission action [run 43369910480](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43369910480), started 2026-11-13 05:07 UTC, finished SUCCESS. Candidate dictionaries only; **the catalog was not edited when testing**.

| Candidate | HTTP / Collector | Parsed | <=30d | Latest publication (UTC) | Violations | Admission |
|---|---|---:|---:|---|---:|---|
| SSB latest | 200 / available | 14 | 14 | 2026-11-12 07:00 | 0 | Pass |
| SSB labour | 200 / available | 8 | 5 | 2026-11-12 07:00 | 0 | Pass |
| SSB energy and industry | 200 / available | 10 | 9 | 2026-11-12 07:00 | 0 | Pass |
| EEA press | 200 / available | 25 | 7 | 2026-11-12 09:00 | 0 | Pass |
| EEA publications | 200 / available | 25 | 7 | 2026-11-12 09:00 | 0 | Pass |

No feed fails the current-news rule. Parsed reports had title, publication date, original HTTPS publisher link, attribution, correct publisher-origin group and no retained summary/media. Each publisher's **sibling feeds share a single `publisher_origin_id`**, even if overlapping items have different source-local IDs.

## Post-admission and release gates

The separate post-commit GitHub Action `source-expansion-no-eea-admission.yml` must pass the full checked-out catalog Collector, strict origin/link/date/body/media constraints, offline synthetic parser tests, and existing publisher-origin grouping regression. Only a successful post-commit action is proof of live admission after enablement. Engineering evidence does **not** constitute independent QA, legal endorsement, map event geolocation, owner product-fix approval, merge authorization, or public-release authorization.

No harvesting of linked article bodies, image downloads, generic scraping, relay scraping, per-publisher spoofed UA, credential access, or redistribution of publisher media.
