# Source expansion — Sweden Statistics (SCB), UK Met Office, exclusions (13 November 2026)

Engineering evidence record for [draft PR #7](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/7), branch `eng/source-expansion-open-feeds-20261113` stacked behind remediation PR #6. **No merge, release, application deployment, publisher scraping, or final QA/legal signoff.**

## Live pre-admission, via actual bounded Collector (before catalog edit)

- Sweden Statistics (SCB): `https://www.scb.se/Feed/statistiknyheter/` — `HTTP 200`, `available`, **10/10 recent 30-day** dated parseable records, latest **2026-11-13T07:00:00Z**, **zero** retained summaries/media/attribution/original-link/origin/article-domain violations. [Direct pre-admission run 43383069634](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43383069634), job 131745122232.
- UK Met Office news: `https://www.metoffice.gov.uk/feed/syndication/news-rss.xml` — `HTTP 200`, `available`, **4/4 recent 30-day** dated records, latest **2026-11-11T00:22:55Z**, **zero** violations of the same invariants. [Direct pre-admission run 43383427393](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43383427393), job 131746233399.

The pre-admission workflow exit status denotes probe execution. Each candidate's printed `passed` result separately establishes parser suitability. Both above passed. No user-agent/proxy modification, retries after denials, HTML article-body scraping, source caching of image/media/audio/video or bypass.

## First-party documentation and metadata reuse rights

**SCB (Sweden):** [Official RSS subscription directory](https://www.scb.se/om-scb/nyheter-och-press/bevaka-nyheter/) explicitly provides RSS updates for new statistics. [SCB website reuse policy](https://www.scb.se/om-scb/om-scb.se-och-anvandningsvillkor/) says **website text, tables, figures and infographics are CC BY 4.0**, whereas only the separate open statistical database/geodata is CC0. Attribution recommended/retained for both. SCB name/logo not used to imply affiliation. Only a first-party original Swedish-language headline, publication date, original HTTPS article link and clear credit are used; no narratives, media or summaries are redistributed. Third-party material excluded.

**Met Office (UK):** [Official RSS feed listing and RSS syndication conditions](https://weather.metoffice.gov.uk/guides/rss) links to its News Releases RSS and confirms RSS display with **direct functional article links, source credit, no inserted interstitial/splash page**. [Met Office Website Terms](https://www.metoffice.gov.uk/policies/tandc) distinguish RSS—**free for any purpose**—from non-RSS gadgets/data feeds, where personal/noncommercial limits apply. RSS may not be modified, and the owner can withdraw it. Integration stores original title, original clickable URL and publication time with clear credit, with no RSS description/article-body/media copying or logo. Final UI QA must ensure original Met Office link opens as a real navigable page without intermediates, no text modification/no implied endorsement, and prompt removal if the publisher withdraws permission.

## Admitted catalog

| Source | `publisher_origin_id` | Language | Category | Poll | Retention | Recency |
|---|---|---|---|---|---|---|
| `se_scb_statistics` | `se_scb` | sv | Economy | >=3600 s | <=180 d | <=30 d |
| `uk_metoffice_news` | `uk_metoffice` | en | News | >=3600 s | <=180 d | <=30 d |

Both are `rss`, `metadata_only=true`, `official=true`, `access_status=reviewed_public`, `independence=original`, origin-grouped with any future sibling feeds from the same publisher; they **are two publisher families, not two new independent confirmations of any story**. Publisher-country metadata is `publisher_coverage`, never an asserted occurrence/event location. Original source URLs, publication timestamps and attribution are preserved, and non-HTTPS or off-allowlist article links rejected.

Previous catalog: **155 configurations, 122 enabled**. After commit: **157 configurations, 124 enabled**, `catalog_version=2026.11.13.source-expansion16`.

## Rejected/unadmitted researched candidates

- **Eurostat statistics-update RSS**: official API guide describes `https://ec.europa.eu/eurostat/api/dissemination/catalogue/rss/en/statistics-update.rss`, but direct bounded Collector on [run 43383069634](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43383069634) returned **HTTP 406**, `error`, **0** parsed reports and no date. It was **NOT enabled**. The existing separate `eurostat_news` remains its original catalog entry; any future Eurostat sibling must use origin `eurostat`. No HTTP header spoofing or alternate scraper attempted.
- **Met Office UK severe weather warning RSS**: official `https://weather.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK` returned **HTTP 200**, `available` but **0** parsed reports and no publication date in [run 43383427393](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43383427393). This can represent a quiet period or a parser incompatibility. It was **NOT enabled**. No real-time warnings or successful admission inferred from HTTP 200.
- **ReliefWeb API v2** is not treated as a no-account public feed for new onboarding: API usage now requires registering/requesting approval for an application name. Do not guess an app name or bypass this obligation.

## Post-admission review gate

A separate strict checked-out-catalog workflow at `.github/workflows/source-expansion-se-uk-admission.yml` must pass both `tests/test_source_expansion_se_uk.py` and `tests/test_issue22_publisher_origin_group.py` plus **actual live Collector** fetches for both enabled entries, with metadata-only and publisher-URL/origin/date validation. **This document is written before recording final CI results; consult workflow run logs and PR batch comment for the result.** If a source fails post-admission, disable it until resolved. Independent QA, source-reuse/display review, and PR #6 owner remediation are still pending. No application release/merge authorized.
