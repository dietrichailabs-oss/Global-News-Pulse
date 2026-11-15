# European Medicines Agency official RSS admission — November 13, 2026

**Scope:** engineering-only source expansion in [draft PR #7](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/7), stacked behind owner-remediation PR #6. **No merge, public release, HTML/media retrieval, unauthorized retries, or credentials. Independent QA is still required.**

## Official documentation and legal restrictions

The [European Medicines Agency (EMA) RSS directory](https://www.ema.europa.eu/en/news-events/rss-feeds) lists direct, account-free publisher RSS feeds for "News and press releases" and "What's new". The [EMA legal notice](https://www.ema.europa.eu/en/about-us/about-website/legal-notice) allows commercial and noncommercial reuse of EMA-owned materials with explicit original-source acknowledgment. It excludes third-party materials and logos. **EMA's separate linking conditions also prohibit showing linked information alongside advertising** and prohibit implying endorsement or changing linked information. Independent QA must confirm that display/placement respects these conditions before release, especially if advertising is ever added.

The integration retains only the title, publication timestamp, original publisher HTTPS URL and attribution/licence reference. Article summaries, bodies, attachments, photos, video and other media are *not* retained. No article linked from RSS is fetched. The EMA origin group is a **single** `publisher_origin_id=eu_ema` despite more than one sibling RSS feed. EMA regulatory statements are **not** clinical advice or independent evidence. Country remains unspecified (European/global publisher coverage, not incident geography). 1h minimum poll, 30-day current-news freshness, 180-day maximum retention.

## Pre-enable test (candidate dictionaries, not enabled catalog)

[GitHub Action run 43370461210](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43370461210) completed SUCCESS 2026-11-13 05:12 UTC with the actual bounded `Collector` and normal Global Pulse client identity. Every passing row had zero article-body/media/host/date/origin violations:

| Candidate | Publisher endpoint | HTTP / status | Parsed | Recent <=30 days | Latest publisher UTC | Decision |
|---|---|---|---:|---:|---|---|
| EMA news/press | [News RSS](https://www.ema.europa.eu/en/news.xml) | 200 / available | 6 | 6 | 2026-11-06 13:20 | **Admit** as `ema_news_releases` |
| EMA What's New | [What's New RSS](https://www.ema.europa.eu/en/whats-new.xml) | 200 / available | 208 | 208 | 2026-11-12 16:20 | **Admit** as `ema_whats_new`; broad site/document notices are *not* automatically urgent clinical events |
| EMA new-human medicines | [New medicines RSS](https://www.ema.europa.eu/en/new-human-medicine-new.xml) | 200 / available | 6 | 6 | 2026-10-16 10:00 | **Hold**, near 30-day expiration and overlaps existing EMA newsroom |
| EMA withdrawn applications | [Withdrawn applications RSS](https://www.ema.europa.eu/en/withdrawn-applications.xml) | **429** / rate_limited | 0 | 0 | none | **Reject** for current use; no publisher-denial bypass, per-client UA spoofing, HTML scraping or relay |

One exploratory fourth request to the same EMA host hit a rate limit, so the two catalog-admitted siblings have a 3600s polling floor; dedicated post-admission tests pace same-host requests by 5s. A passing pre-enable request does not guarantee continuing access.

## Strict catalog post-admission gates

Workflow `.github/workflows/source-expansion-ema-admission.yml` tests the checked-out catalog with synthetic parser/provenance/origin tests plus real live `Collector` requests for each of the **two** enabled EMA rows. It fails closed if HTTP is not 200, the publisher response is empty or outdated, origin IDs differ, originals leave allowed HTTPS domains, dates are missing, or article descriptions/media are retained.

The strict post-admission result must be linked and reported separately when it finishes; engineering-only success is **not** final legal/compliance signoff or product release authority. Draft PR #7 and owner/remediation PR remain **unmerged**.
