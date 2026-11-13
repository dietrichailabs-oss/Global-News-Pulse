# Global Pulse source expansion — Brazil legislative journalism and South Korea gates (2026-11-13 UTC)

## Scope, status and freeze

Engineering-only source-expansion work on [draft PR #7](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/7), stacked behind PR #6. **No merge, release, Windows package, redistribution or article scraping is authorized.** Source catalog is now **168 configurations, 128 enabled** (three Câmara admissions, seven prior NZ Beehive feeds quarantined after live denial), with three newly admitted Agência Câmara RSS feeds under **one** independent publisher family `br_camara`. Independent QA (display rights, source clock, reuse terms, correction/retraction and reliability) remains required. The catalog retains `remote_updates=disabled`.

## Brazil — admitted three first-party feeds only after direct live checks

The [Câmara's own RSS directory](https://www.camara.leg.br/noticias/rss) explicitly lists 21 topic feeds and offers a standard XML syndication mechanism. The Câmara's [editorial communication manual](https://infograficos.camara.leg.br/manual-de-comunicacao/agencia-camara/) expressly allows free reuse of agency reporting **with due credit**. The official [RSS announcement](https://www.camara.leg.br/noticias/140474-agencia-camara-de-noticias-inaugura-servico-de-rss-tematico) explicitly permits automatic replication of agency headlines and site links for online publishers with the attribution Agência Câmara.

**Pre-admission repeatable live probe**: [Actions 43413911891](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43413911891), on previous unchanged catalog, passed 26/26 existing offline provenance and grouping tests and used the actual bounded `Collector` against all candidates.

| New source ID and direct publisher RSS | HTTP | Parseable reports | Reports within 30 days | Latest date UTC | Provenance violations |
|---|---:|---:|---:|---|---:|
| `br_camara_all` — `https://www.camara.leg.br/noticias/rss/ultimas-noticias` | 200 | 20 | 20 | 2026-11-12T22:54:00Z | 0 |
| `br_camara_health` — `https://www.camara.leg.br/noticias/rss/dinamico/SAUDE` | 200 | 10 | 10 | 2026-11-12T19:24:00Z | 0 |
| `br_camara_economy` — `https://www.camara.leg.br/noticias/rss/dinamico/ECONOMIA` | 200 | 10 | 10 | 2026-11-12T22:04:00Z | 0 |

Examples of actual original publisher permalinks from bounded pre-admission evidence:
- https://www.camara.leg.br/noticias/1319196-camara-entrega-medalha-rei-pele-a-pessoas-e-instituicoes-ligadas-ao-esporte
- https://www.camara.leg.br/noticias/1318861-comissao-aprova-adaptacao-de-moradias-do-minha-casa-minha-vida-para-familias-com-doentes
- https://www.camara.leg.br/noticias/1319043-comissao-de-financas-debate-com-receita-federal-regulamentacao-da-reforma-tributaria

**Admission commit** [5b15f59](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/5b15f59f66f0485ef44acb98681ecdbe4989cfe5) enables only these three records with direct HTTPS `www.camara.leg.br` feed and article host allowlists; no key, account, RSS proxy, source-body scrape or image download. Conservative hourly minimum polling, freshness threshold 30 days, retention 90 days. Retain exact publisher RSS headlines, dates, direct links and fixed Câmara credit, not descriptions, full bodies, news images, protected third-party media, logos or embedded audio/video.

All three `publisher_origin_id=br_camara`; overlap between general, health and economy feeds must never count as independent corroboration. This is journalism from a legislature about discussion, hearings, votes and legislative proposals, **not confirmation that legislation has entered into force**. Brazil denotes publisher jurisdiction, not incident location. Corrections may change article dates; display must not imply an independent incident time.

**Post-admission exact-catalog**: `.github/workflows/source-expansion-br-camara-post-admission.yml` with `tests/test_source_expansion_br_camara.py` adds repeatable headline/link/date/no-media and same-origin regression tests plus three independent direct read-only Collector requests after admission. See the workflow's actual completed job logs before claiming this gate passed.

## Rejected or held: Brazil Senate

The Senate's [official RSS announcement](https://www12.senado.leg.br/noticias/materias/2008/05/12/ja-esta-disponivel-o-servico-de-rss-da-agencia-senado) and [publication use policy](https://www12.senado.leg.br/assessoria-de-imprensa/noticias/politica-de-uso) support credited use. However the tested candidate `https://www12.senado.leg.br/noticias/rss.xml` produced **HTTP 200, 15 fresh parseable titles, but zero direct original article URLs** under the existing bounded Collector. All 15 records violated the required original-link provenance gate. **Not enabled.** Do not substitute guessed links, widget JavaScript, article-page scraping, or third-party RSS relays. The publisher use policy also requires credit to authors when reusing complete reports, a separate caution.

## South Korea — no additional enabled sources

[Pre-admission workflow 43413435103](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43413435103) passed its 26/26 offline parser/publisher grouping tests. Actual publisher-direct Collector checks:

- Bank of Korea all news `kr_bok_all`: **HTTP 200, 100 reports, 33 recent, 0 machine violations**.
- Bank of Korea statistics `kr_bok_economic`: **HTTP 200, 100 reports, 12 recent, 0 machine violations**.
- Korea Copyright Commission press: **HTTP 202 and response exceeds bounded size limit**; zero reports.
- Korea Copyright Commission notices: **HTTP 202**, 600 records but **600 original-link violations** (empty original URLs), zero accepted items.

Both Bank of Korea feeds **remain unadmitted** because a clear official permission for systematic headline metadata commercial reuse under the site's published copyright policy is not yet established. `KOGL` licensing generally has multiple types, including non-commercial types, and cannot be inferred for BOK press headlines from generic public-sector status. [KOGL types](https://www.kogl.or.kr/info/licenseTypeEn.do). The commission feeds fail live status, bounded size or link provenance checks and remain excluded. No denial bypass, spoofing or scraper workaround.

## QA follow-up (gated)

1. Independent rights/display review for all new Câmara headlines (publisher attribution and any third-party exceptions).
2. Verify corrected/updated feed dates are not misrepresented as independently established event timestamps.
3. Recheck sustained hourly host stability, origin grouping across all three siblings, and refusal of non-publisher original article links.
4. Review admission and broader source audit job logs before QA sign-off; a workflow having run is not itself a source admission pass.
5. Leave PR #7 draft/unmerged and all release/package gates unchanged.


## NZ Beehive host-wide access-denial quarantine

The [broader full source audit 43414479879](https://github.com/dietrichailabs-oss/Global-News-Pulse/actions/runs/43414479879) passed its offline stage but **failed live** on November 13, 2026 when **all seven** previously active `www.beehive.govt.nz` topic RSS feeds returned **HTTP 403**. These were `nz_economic_growth`, `nz_energy`, `nz_foreign_affairs`, `nz_health`, `nz_infrastructure`, `nz_national_security` and `nz_trade`. Earlier audit 43413912312 had passed (intermittent publisher host access); therefore this is an access reliability/denial, not proof these feeds are permanently gone. Per conservative admission policy, **all seven are now disabled** in catalog [quarantine commit a55e76a](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/a55e76ac149faf479c532e2551acdaf376c4da22). They remain visible for audit and retain their original `publisher_origin_id=nz_government`; disabled feeds cannot contribute data.

The broad audit now logs `SOURCE_QUARANTINE` without contacting denied siblings, requires all seven remain disabled, and fails closed if they are accidentally re-enabled. This respects Collector's minimum 24-hour host denial hold: do not bypass access denials with a different client, provider alias or immediate retrials. [Audit-circuit fix 2add702](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/2add702a944190ba7e14c9312791914c22697d07); [quarantine assertion 8146c93](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/8146c935f2fae7c64442c84ed225d2d15c6ef9bd).

Broad publisher audits previously launched on *every* documentation/probe commit. [CI pacing fix 2ed39e4](https://github.com/dietrichailabs-oss/Global-News-Pulse/commit/2ed39e422948f627b0bb9fed51595ab698d6a2b8) restricts automatic full audits to catalog/Collector/audit-script changes, retaining explicit manual dispatch. This prevents innocuous documentation or probe-only pushes from repeatedly hammering unrelated publishers. Existing independent source-specific workflows may also fire after catalog changes and still warrant pacing review.

**This quarantine does not reverse the three independent Câmara feed post-admission passes.** Full audit after quarantine must be examined as its own workflow result, and no previous failing audit may be re-labeled as a pass. Before restoring NZ feeds, obtain publisher-direct successful HTTP 200, parseable original links/recent content, and valid reuse/display rights after the access-denial hold. No source was silently re-enabled.
