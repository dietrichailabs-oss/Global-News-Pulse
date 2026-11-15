# Global Pulse source expansion — OBR admission and official feed exclusions (13 November 2026 UTC)

## Scope and release
Source-expansion Engineering work only, stacked draft [PR #7](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/7) behind owner-remediation PR #6. Do **not** merge, release, package, scrape, republish originals or equate additional feeds with independent event confirmation. Post-admission exact catalog: **165 configurations / 132 enabled**, one newly admitted independent origin `uk_obr`.

## OBR rights and provenance
* [Office for Budget Responsibility copyright](https://obr.uk/legal-pages/copyright/) explicitly allows reuse of OBR site information in any medium, excluding logos, subject to the UK Open Government Licence. Retain only original publisher RSS headline, source publication timestamp, direct publisher URL and OBR/OGL attribution; no summary, body, HTML, image, logo, audio, video, embedded media, sponsorship/endorsement or third-party content.
* First-party endpoint `https://obr.uk/feed/` is a publisher-owned, keyless HTTPS RSS feed, independently verified live twice using Global Pulse's actual `Collector`. No scraper, account, API key or relay required. The homepage is `https://obr.uk/`; **there is no separately verified official RSS-directory documentation**, so independently monitor continued endpoint ownership and OGL terms.
* `publisher_origin_id=uk_obr` is a single publisher family, separate from GOV.UK departmental feeds (`uk_government`), Met Office (`uk_metoffice`) and ONS (`ons`). Additional OBR siblings must reuse `uk_obr`, never add independent corroboration. `country=United Kingdom` means publisher coverage, not incident geography. OBR official statements do not independently verify their downstream predicted economic effects.

## Pre-enable direct Collector evidence
[Pre-admission GitHub Actions run 43408103840](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43408103840), before changing the catalog, verified `uk_obr_news` (HTTP **200**, **10 parsed entries**, **1 within 30 days**, latest **2026-10-28T16:42:05Z**, **0** machine-detected original-link, origin, summary, media, attribution, geography or date violations).
Sample first-party article URLs:
* https://obr.uk/the-chairs-presentation-on-our-october-2026-economic-and-fiscal-outlook/
* https://obr.uk/treasury-committee-report-concluding-its-inquiry-into-the-obr-15-years-on/

[Catalog admission commit 9f8f8e8](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/9f8f8e8e8895522f6eb6505c8b6a7d8366d4e430) set conservative hourly poll, 30-day freshness threshold, 180-day maximum retention, metadata-only, whitelist of `obr.uk` article hostnames, OGL rights and original link attribution. No linked article text or media collection.

## Post-commit exact-catalog verification
[GitHub Actions 43408461651](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43408461651) **PASS** on head `907c607a1ad641e7762302cde95cfc48f8b639af`:
* **21/21 offline tests PASS**: OBR rights, parser stripping summaries/media, malicious external article-host refusal, publisher origin/independence and neighboring existing Sweden/UK tests.
* Actual catalog row re-fetched direct from `obr.uk/feed/`: **HTTP 200, 10 reports, 1 recent, latest 2026-10-28T16:42:05Z, 0 detected violations**.
* Associated pinned workflow `.github/workflows/source-expansion-obr-post-admission.yml`; fixture `tests/test_source_expansion_obr.py`. Exact source headline, direct links and dates are retained. The 30-day gate will automatically treat OBR as stale without a later publication; it is not an always-on high-frequency alert feed.

## Directly probed but excluded, never enabled
[UK official legislation/OBR pre-admission run 43408103840](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43408103840) independently read the official `https://www.legislation.gov.uk/new` index, proving that it itself links `/new/data.feed`, `/new/uksi/data.feed`, and `/new/ukpga/data.feed` Atom endpoints. Government data is explicitly open under [the Open Government Licence](https://legislation.github.io/data-documentation/reuse-licence.html). All three endpoints returned **HTTP 200, zero usable Collector reports**, so **none enabled**. Investigate the RSS/Atom parser separately before considering any of these as supported news sources; a valid server response is not a passing admission.

[NASA first-party pre-admission run 43407542660](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43407542660) tested 4 publisher endpoints:
* `https://science.nasa.gov/feed/earth-observatory/natural-events`: HTTP 200, XML/Collector ParseError, zero reports — **rejected**.
* `https://science.nasa.gov/feed/earth-observatory/image-of-the-day`: HTTP 200, XML/Collector ParseError, zero reports — **rejected**.
* `https://www.nasa.gov/news-release/feed/`: HTTP 429 rate limited, zero reports — **rejected**. No anti-bot bypass.
* `https://cneos.jpl.nasa.gov/feed/news.xml`: HTTP 200, seven parseable records, one recent, zero machine-detected provenance violations, but one sample `original_url` was `https://cneos.jpl.nasa.gov/news/news.js` (JavaScript asset, not safely established article permalink) — **held and not enabled pending link-quality/parser review**. A machine admission candidate is not final rights/permalink admission.

Additional official publishers reviewed but not enabled: ADB RSS (commercial reuse restrictions on website content), HKMA press API (non-commercial use terms), Singapore NEA/SFA feeds (reuse/automation restrictions), and UN news feeds (rights/display ambiguity). Individual open-data licences do not automatically grant redistribution rights to the publisher's news text. No article-body scraping or permission bypass attempted.

## Broader status and follow-up
* Broader pre-OBR source audit [43408103803](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43408103803) **PASS** after a prior transient audit [43407542651](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43407542651) failed on several NZ Beehive feeds with 200/ParseError; the immediate independent retry parsed the NZ feeds (some topic-specific stale/empty by design) successfully. Do not misreport the first failure as a permanent exclusion or the 200 responses as always healthy.
* A parallel EMA source check [43408363144](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43408363144) saw HTTP 429 for one EMA sibling under the many catalog-change CI checks; **do not interpret the rate limit as an admission PASS or try to bypass it**. Throttle future repeat probes and reassess health on a paced run.
* Independent QA remains required for OBR publisher attribution/display, rights at deployment, end-to-end source freshness, feed stability and refusal of nonarticle asset URLs.
* This batch changes no existing gates, merged branches, installers, releases, owner remediation or user-facing binaries.
