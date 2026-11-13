# Global Pulse source expansion — European Central Bank and Brazil probe (13 November 2026)

## Authorization and scope
Draft PR #7, source expansion only; stacked behind PR #6, no release, merge, installer, media ingestion or article scraping authorized. Bounded direct first-party RSS fetches with a 1-hour minimum interval per newly enabled feed, 30-day source recency threshold, and 180-day retention ceiling.

## Publisher rights and official feed documentation
- [ECB publisher RSS directory](https://www.ecb.europa.eu/home/html/rss.en.html) documents first-party press and statistical press RSS.
- [ECB disclaimer/copyright](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html): information can be used freely with accuracy and source citation; reproduction of documents bearing authors' names may need prior permission. Admission uses **only original headlines, dates, original publisher article links and attribution**; no document, article body, RSS description, image, media, logo or working paper text copied.
- [Brazil official RSS directory](https://www.gov.br/pt-br/rss) provides direct topical feeds and publishes a CC BY-ND 3.0 notice at its footer. RSS existence is **not** evidence of current activity.

## Pre-enablement GitHub Actions evidence
[Direct-publisher pre-admission run 43391181214](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43391181214) from commit `9374f35386906ced848db8f338cafb616648b64a`.
All 7 returned HTTP 200 and had zero metadata/provenance violations, but only 2 met the freshness/availability gate.

| Candidate | Parsed reports | Reports dated within 30 days | Latest publication (UTC) | Decision |
| --- | ---: | ---: | --- | --- |
| ECB press `ecb_press` | 14 | 14 | 2026-11-13 07:20 | **Admit** |
| ECB statistics `ecb_statpress` | 15 | 4 | 2026-11-02 09:00 | **Admit** |
| Brazil economy `br_gov_economy` | 5 | 0 | 2023-01-02 | **Reject stale** |
| Brazil health `br_gov_health` | 8 | 0 | 2023-02-23 | **Reject stale** |
| Brazil infrastructure `br_gov_infrastructure` | 5 | 0 | 2023-01-02 | **Reject stale** |
| Brazil energy `br_gov_energy` | 5 | 0 | 2023-01-02 | **Reject stale** |
| Brazil justice `br_gov_justice` | 5 | 0 | 2023-01-02 | **Reject stale** |

All five Brazil feeds remain **absent from the enabled catalog**; the official portal is a historical archive in this test, not live 2026 signals. No relay or scraping substitution was used.

## Provenance, geography and retention
The two ECB sibling feeds share `publisher_origin_id=eu_ecb`. They contribute **one original publisher family, not two independent corroborating publishers**. Their European/euro-area publisher context is not an incident coordinate or destination country. Explicit allowed/article HTTPS host allowlists, no untrusted article domain redirects, and unchanged original links and source dates are enforced by the Collector. Metadata-only mode ensures summaries and media arrays remain empty.

## Post-admission
A pinned, read-only GitHub Actions workflow `.github/workflows/source-expansion-ecb-post-admission.yml` runs offline parser and origin regressions followed by a **fresh direct live check from the checked-out catalog**. Results must be inspected before classifying the commit as verified.

## Hold
This is Engineering source admission evidence only. Independent QA must still confirm rights/display conditions, provenance grouping, data freshness and outage behavior. PR #7 must remain draft/unmerged and nothing should be released.
