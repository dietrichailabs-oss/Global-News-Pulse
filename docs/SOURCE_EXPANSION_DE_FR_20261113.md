# Germany / France first-party RSS expansion — engineering admission evidence

**Recorded:** 2026-11-13 03:03 UTC  
**Scope:** Branch `eng/source-expansion-open-feeds-20261113`, stacked PR #7. Engineering admission only; **independent QA pending, no merge or release**.

## Publisher / rights checks

| Source ID | Origin / category | Direct RSS endpoint | Publisher feed and reuse documentation |
|---|---|---|---|
| `destatis_press` | `destatis` / Economy; Germany | [Destatis press RSS](https://www.destatis.de/SiteGlobals/Functions/RSSFeed/DE/RSSNewsfeed/Aktuell.xml?nn=241288) | [Official Destatis RSS instructions](https://www.destatis.de/DE/Service/RSS/RSS_Einfuehrung/_inhalt.html), [Destatis open-data terms](https://www.destatis.de/EN/Service/OpenData/opendata-einleitung.html); reproduce agency information with source acknowledgment, excluding identified third-party material |
| `fr_service_public_business` | `fr_dila` / Government; France | [Service Public business RSS](https://www.service-public.gouv.fr/abonnements/rss/actu-actu-pro.rss) | [DILA's official RSS instructions](https://entreprendre.service-public.gouv.fr/P10008) expressly permit website/blog republication and require visible source attribution or original service-public.gouv.fr link; [Service Public reuse terms](https://www.service-public.gouv.fr/P10150) explain the Open Licence and attribution/update-date requirements for covered public material |

Both routes require **no account, API key or credentials**. Source and publication timestamps are preserved. Publisher domicile is **not** an event-location assertion. Headlines, date metadata, original links and attribution are displayed; feed description/body, embeds, images, audio and videos are not copied or published. No access bypass, HTML scraper or proxy is used.

## Pre-enablement live admission

The [GitHub Actions publisher-direct admission job, run 43356232374](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43356232374) completed **SUCCESS** on the unmodified proposed endpoints. Real `Collector` with bounded HTTP parser, no redirects outside approved hosts:

| ID | HTTP | Parsed reports | Reports dated within 21 days | Latest supplied publication | Empty/missing-link/body/media/independence violations |
|---|---:|---:|---:|---|---:|
| `destatis_press` | 200 | 10 | 10 | 2026-11-12T07:00:00Z | 0 |
| `fr_service_public_business` | 200 | 234 | 8 | 2026-11-04T23:00:00Z | 0 |

Counts are point-in-time parser observations, **not** a guarantee of completeness or constant availability. The probe does not fetch linked articles. Source origin IDs are distinct because the publishers are distinct; any future feeds from either publisher must reuse its origin ID to avoid false independent corroboration.

## Catalog and regression evidence

- Catalog addition: `destatis_press` and `fr_service_public_business` are enabled **only after** the live preadmission PASS, with `metadata_only=true`, `access_status=reviewed_public`, polling floor 1800 seconds, 21-day stale threshold and explicit publisher-origin IDs.
- [Offline test suite](../tests/test_source_expansion_de_fr.py) checks no-body/no-media RSS parsing, original link/timestamp/attribution, source licensing metadata, origin segregation, and sibling origins remaining identical for the same publisher.
- [Post-admission GitHub workflow](../.github/workflows/source-expansion-de-fr-probe.yml) validates the checked-out catalog identities and executes that suite and real `Collector` against the publisher endpoints. [Run 43356763385](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43356763385) completed **SUCCESS**: 4 offline pytest tests passed; both catalog entries returned HTTP 200 with 10/234 parsed reports, 10/8 reports recent within 21 days, and zero no-body/media/provenance-link violations.
- Current-source freshness must follow the publisher publication dates and report stale/empty/denied sources as unavailable, not pad the source count.

## Exclusions / limitations

- Brazil IBGE RSS location was investigated but a direct HTTP request from the research environment received **HTTP 403**. Not admitted; do not bypass with scraping, different user identities, credential tricks or third-party relays. This is an exploratory access observation, not an application Collector result.
- French INSEE other feed candidates were not independently validated against the application's parser/rights model, so not admitted.
- External publisher rights and any new distribution use remain subject to independent QA. Public documentation and this engineering evidence do **not** supersede that gate.
