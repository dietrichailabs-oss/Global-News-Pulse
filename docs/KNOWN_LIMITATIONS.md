# Current freeware compliance candidate — 2026-11-10

Global Pulse is provided free of charge. This does not change the application's
source-code licensing or remove third-party obligations.

WebEngine/PDF 6.140 source is identified as official RC commit
`d505fc23640d2bd6345e6483eb73daf4e19f5829`. The complete source archive, exact
SHA-256, vendor build/component inventories, source-file checks and bundled
notices are recorded in `licenses/qt-open-source/corresponding-source/SOURCE_MAP.json`.
The raw SDK and wheel binaries are distinct signed files; their compared executable
payloads are identical. No library was changed or downgraded. The earlier failure
to locate a final-named tag is historical, not a continuing reason to wait for one.

The Windows SDK permission is documented by Microsoft's official REDIST list and
the exact package-linked SDK license. Its selected DLLs remain unmodified. The
installer exposes the included Microsoft-only terms, and first native-notification
use requires affirmative local acceptance of their exact text. Declining does not
prevent news or local alert-history use. These terms do not restrict LGPL library
replacement/modification/relinking or reverse engineering to debug modifications.

These are Engineering changes, not independent QA acceptance or public-release
authorization. Prior accepted PR #12 remains frozen. The changed candidate needs
its own exact package checks; physical Windows/client tests remain separate.

---

# Historical preceding candidate record

# Engineering E2 known limitations

This list distinguishes required unfinished platform work from deliberately
restricted provider access. The approved Version 1 charter remains authoritative.

## Current release-integration status — November 10, 2026

The current Engineering release-integration line is **draft PR #12**, rooted
directly in independently accepted E4 source
`cc9b6234f7afe9499c0aac3559283b7851dad7d4`. The exact candidate identity is
recorded by Git and in each Windows `WINDOWS_BUILD_RECORD.json` /
`ENGINEERING_CANDIDATE.json`; this prose intentionally does not relabel an
older binary as current when the integration head advances.

Independent acceptance already preserved on the integration line includes:
- E4 radio/crisis/GDELT: 13/13 QA PASS on `cc9b6234`;
- Gate B saved-geometry correction: 5/5 independent PASS;
- Gate D local feed/model cleanup: 7/7 independent PASS;
- Gate D packaged privacy/egress: 529/529 Windows tests plus package/smoke PASS;
- Gate E narrow Python/.NET notice correction: 6/6 independent PASS.

Remaining release HOLDs are finite and explicit: ordinary-client Windows
notification/cold-activation observation; physical mixed-monitor/differing-DPI
observation; ordinary interactive packaged media/consent behavior where hosted
Server UI automation is blocked; exact Qt WebEngine/PDF 6.140 corresponding
source; the Microsoft Windows SDK external-license-reference redistribution
decision; and final integration-focused QA. A hosted-Server environment block
is not a product failure, and a GitHub artifact-storage quota failure is not a
product failure. **No public release is approved.**

## Historical independently reviewed E2 Windows private test candidate (November 9, 2026)

This historical **private Windows 0.1.1 / E2 test candidate**, never a public release,
had immutable runtime source [`0788d0f98d168b9082f63e1da0126cf4a81975d9`](https://github.com/dietrichailabs-oss/GlobalNewsPulse/commit/0788d0f98d168b9082f63e1da0126cf4a81975d9).
[Canonical Windows run 42727958033](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42727958033)
completed SUCCESS with **487 Engineering Windows tests / zero fail, error or skip**,
plus bounded frozen/installer smoke. The new separate installer/portable/diagnostics
artifacts are [13723603226](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42727958033/artifacts/13723603226),
[13724595234](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42727958033/artifacts/13724595234)
and [13723099373](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42727958033/artifacts/13723099373).
Engineering rehashed the original installer (SHA-256 `f8e9620f78bbedde383faadb18891dbc450b5b294314f0d7673fb16471097203`),
portable (SHA-256 `e265d964233fb68e0bf8afb9c757c37b1d2895b7378d12ee04839d817be08cee`)
and all 4,003 portable files. [Exact package verification](engineering/GP-ENG-CAMERA-CONFLICT-001/WINDOWS_EXACT_0788_VERIFICATION.md).

**Latest independent Pulse QA decision** is [GP-QA-E2-0788D0F9-001](qa/GP-QA-E2-0788D0F9-001/REPORT.md),
evidence `a16428387e5c87d67eb4f1e57b37b8afcf73176d`,
[return 6755821649](https://github.com/dietrichailabs-oss/GlobalNewsPulse/pull/2#issuecomment-6755821649):
**32 planned / 32 executed / 32 PASS / zero FAIL or BLOCKED** in its bounded
source/passive exact-package scope. QA independently closed the four owner-feedback
source findings GP-OF-CAM-001/002/003 and GP-OF-MAP-001; those closures are not
interactive native Windows, real camera/video/model, or release acceptance.
**GP-DOC-001 was independently closed** in the later 4bf6 package review:
the corrected Packaging paragraph is present in the reviewed shipped bytes.
Its earlier efa30535 P3 FAIL remains a historical result, not an open current defect.

**Overall / public release HOLD:** Interactive Notification Center display/click/cold
activation, ordinary-user install and tray/full exit, real physical Snap/mixed-DPI,
permitted live camera/video/model tests, packaged security/privacy/retention/egress,
complete QtWebEngine/PDF/Chromium, DWrite, Python/native-wheel/.NET/installer
license/notice/source or replacement evidence, and broader charter acceptance
are not established by these bounded reviews. Owner-approved UI appearance and
self-signing path do not constitute functional QA, public trust/reputation, or
redistribution-rights approval. Windows 10 remains an intended compatibility
target **not independently client-observed**; per owner amendment a separate Win10
cycle is **not** a standalone gate absent a concrete Win10-specific defect.
Hosted Windows Server 2022 is not an ordinary-user Windows 11 client observation.
New radio and live-video feature branches are **not** in these 0788 packages.
**Next Engineering action:** prepare independently reviewable new feature source
with focused regressions while finishing component-rights/media/privacy evidence;
Pulse QA independently retests changed bytes. No documentation change rebuilds 0788.

## Historical efa30535 Windows candidate and its original review (November 9, 2026)

That earlier **private test candidate**, never a public release, was source
[`efa30535facf0883870130ae9e1061d0c3b03321`](https://github.com/dietrichailabs-oss/GlobalNewsPulse/commit/efa30535facf0883870130ae9e1061d0c3b03321).
The [single canonical Windows run 42643934899](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42643934899)
completed **SUCCESS**, with **393 Windows Engineering tests passing**, zero failed,
errored or skipped; the frozen-application launch/restart, synthetic captures,
installer/reinstall/uninstall and private upload steps also completed successfully.
[Installer/portable/manifest/SBOM artifact 13687157564](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42643934899/artifacts/13687157564)
is **602,382,047 bytes**, GitHub-reported outer SHA-256
`88d5f6fe830e644840b2ab66e39a04b6b1eab8d00a91c868c10e2d508e3794ee`.
[Diagnostic artifact 13687442205](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42643934899/artifacts/13687442205)
is **1,219,974 bytes**, SHA-256
`56d70c018ba4eab27f10353406f90c1e5bbf1fc1482da97c6565557d320a2bab`.
These are **Engineering / GitHub upload receipts**, not independent new-package
hash acceptance. Both artifacts expire on November 23, 2026, subject to GitHub retention.

**New independent Pulse QA decision:** [GP-QA-E2-EFA305-001](https://github.com/dietrichailabs-oss/GlobalNewsPulse/blob/f7b4ebc340ff4326b2faff313c207f5e0a101023/docs/qa/GP-QA-E2-EFA305-001/REPORT.md)
records **71 planned, 67 executed, 67 PASS, 0 FAIL, 4 BLOCKED**.
QA **closed GP-CORE-007 for the specifically reproduced source behavior** after
54 independent temporal/history cases passed. At that *earlier* source retest, its
overall HOLD included the then-oversized combined payload; later transport and
package review resolved the byte-access blocker. The populated UI-01 composition
and UI-002 card-clipping reproductions were independently closed in the preceding
[cd1a21 retest](https://github.com/dietrichailabs-oss/GlobalNewsPulse/blob/d5c5f7dacec0906813acb54958edc49bced12081/docs/qa/GP-QA-E2-CD1A-001/REPORT.md),
but neither proves real mixed-DPI or native interaction. No source correction
is pending for the closed reproduced GP-CORE-007 case.

**Latest independent package review:** [GP-QA-E2-EFA305-PACKAGE-001](https://github.com/dietrichailabs-oss/GlobalNewsPulse/blob/47b7e89706dabedcb21b581acae42d6436b368c4/docs/qa/GP-QA-E2-EFA305-PACKAGE-001/REPORT.md)
records **15 planned / 15 executed / 14 PASS / 1 FAIL / 0 BLOCKED** in its
bounded *passive* review. QA downloaded and rehashed the original installer
(240,624,987 bytes, SHA-256 `dd6a1d404c9a2b6afc1dba3557d6df1ed953efe944c58070972caeb0bdf8d936`)
and portable (359,269,393 bytes, SHA-256
`ad43921d07c77b2c4f5e4199bd85082c3429073681bcdc6265336e8de6a04ba5`),
and independently verified all **4,003 portable files** against the manifest.
QA **closed GP-PKG-001 only for the original portable's collected tqdm LICENCE
and inventory correctness**; installer internals, redistributed Qt/Chromium,
CTranslate2/SentencePiece, .NET/Windows App SDK licenses and source/replacement
obligations remain unapproved. The single P3 FAIL **at this historical efa30535 review** was **GP-DOC-001**,
an outdated current-handoff sentence. Engineering corrected it and **independent
Pulse QA later closed it**, verifying the corrected paragraph in the 4bf6 shipped
package; that later closure does not rewrite the original efa30535 FAIL. Overall
**HOLD** remains for substantive unfinished acceptance. No native Windows/application execution occurred in this passive review.

Original, unchanged source `efa30535` Windows payloads are now accessible
individually from [installer artifact 13691563579](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42655019860/artifacts/13691563579)
and [portable artifact 13691144235](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42655019860/artifacts/13691144235),
with [original receipts artifact 13691159322](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42655019860/artifacts/13691159322).
These are read-only transport wrappers; they did **not** rebuild the original
runtime or installer. The combined old artifact remains immutable and historical.
**Smallest next action:** finish exact Qt/PySide/Chromium/native-wheel/.NET
component-to-license/source mapping, preserve the corrected documentation for
a separately identified future build, and arrange independent native Windows
acceptance without treating runner/offscreen tests as platform PASS.

**Still NOT RUN / HOLD:** actual Notification Center display, click and cold
activation, clean ordinary standard-user installation, tray/full exit, interactive
Snap and 100/125/150/200% mixed-monitor behavior, permitted live provider/media,
remaining charter, security/privacy/telemetry, complete Qt/Chromium/.NET/Python
source-access/licensing/redistribution and public release decision. Hosted Windows
snapshots were requested at 1440×940 and 960×640 but captured on a runner with a
1024×768 physical screen: not native monitor/DPI acceptance. The project has
**Engineering and independent Pulse QA only** under the owner amendment; no
separate Sable/Iris/PM/Release Management response is required, but no underlying
review is waived. No signing/public release/owner legal choice has been made.

**Historical separate source/package:** `cd1a21bb8a543afb993398df05c9a83dfd4973f6`
passed 375 Windows Engineering tests in [run 42589886841 attempt 2](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42589886841)
(the first attempt was cancelled), with private artifact 13666923687 and
diagnostics 13667242739. Original unchanged binaries were transported separately
as [installer 13679286136](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42627461554/artifacts/13679286136)
and [portable 13679296092](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42627461554/artifacts/13679296092);
this allowed independent byte checks. Its independent
[GP-QA-E2-CD1A-001](https://github.com/dietrichailabs-oss/GlobalNewsPulse/blob/d5c5f7dacec0906813acb54958edc49bced12081/docs/qa/GP-QA-E2-CD1A-001/REPORT.md)
verdict remains **FAIL** for those older bytes, not a verdict on the new package.
Older E1/b7ff26d/cb42f15 reports retain their original evidence identities.
This documentation-only update does **not** change or rebuild either package
or its embedded notice text.

## Analysis and coverage boundaries

- Corroboration requires documented reporting origins. Multiple publisher domains
  alone never establish independence; many ordinary RSS reports therefore remain
  unverified pending better provenance.
- Event grouping uses stable provider IDs/keys and conservative text/time/region
  matching. Uncertain relationships remain separate rather than becoming invented
  confirmations.
- Contradictions compare structured claims with compatible metric, scope, unit and
  observation time. This version does not claim unrestricted semantic contradiction
  detection across arbitrary natural-language articles.
- Emerging-signal reasons explain evidence, coverage and changes. Historical
  abnormality has no validated global baseline yet and is explicitly not scored
  as a predictive probability. Coverage volume is not proof of credibility.
- Only source-supplied event coordinates are shown as incident points. A feed's
  country/region can describe its jurisdiction or coverage; it is not automatically
  an incident location. Some events therefore have no map marker.
- Economic default series cover World Bank inflation, unemployment and GDP growth,
  supplemented by official economic announcements. They are not a complete live
  market-price, corporate-filings or sovereign-risk feed. Dataset update time is
  not asserted to be the release time of each observation.
- German, French and Spanish offline model paths have been exercised on simple
  controlled translations. Other languages currently receive an honest unsupported
  message. General translation accuracy needs broader independent review.

## External-access limits and supported fallbacks

- Tousi TV is preconfigured as its verified official channel/streams link. Automatic
  live-status discovery and one-alert-per-broadcast are unavailable without a
  reviewed supported discovery method. No stream is labeled live from guesswork.
- YouTube supports explicit permitted video links and its official embedded player.
  Broad automated video discovery is not active by default.
- X and Facebook use public original-source links. No scraping of logged-in/private
  accounts or unsupported automated discovery is present.
- BBC, UN News, Agência Brasil, ReliefWeb and other reviewed entries with unresolved
  permission or attribution requirements remain disabled/manual. The source matrix
  identifies each exact condition; there is no concealed paywall/API bypass.
- Webcam and radio integrations are reviewed public directories/link workflows.
  Individual camera/receiver permissions and live/delayed availability still apply.
  No automatic private-device discovery, recording, transcription or retransmission
  is performed.

## Packaging and operation

The engineering repository contains tests, fixtures and review evidence; strict
Windows staging excludes them. The **private** E2 Actions artifact contains a real
installer and portable package. For the **historical efa30535 package**, use
[the original-byte/notice handoff](https://github.com/dietrichailabs-oss/GlobalNewsPulse/blob/b5b460c0cfffa0cfe09cf7ab75bd24da28f2e9e1/docs/engineering/GP-ENG-EFA305-INTEGRITY/REPORT.md),
its two unchanged under-limit payload transports above and the independent
[package report](https://github.com/dietrichailabs-oss/GlobalNewsPulse/blob/47b7e89706dabedcb21b581acae42d6436b368c4/docs/qa/GP-QA-E2-EFA305-PACKAGE-001/REPORT.md);
verify each original SHA-256 and manifest before testing. Older `cd1a21`
and `cb42f15` handoffs remain historical. This file does not grant public redistribution or QA PASS.
Optional translation model binaries are not bundled and need a disclosed,
consented download. The app stops collecting after Exit Completely and cannot
generate new alerts while it is fully stopped.

## E2 archive compatibility

E2 uses schema version 2 for warning identities and merged-event redirects. Keep a
closed-app archive backup before upgrade. E1 must not open the upgraded database;
rollback requires its matching older archive. Saved user panel sizes are retained;
Reset Layout selects the new E2 reference-oriented composition.

The cold-activation and bounded translation-process changes need independent
Windows checks even when their source tests and engineering build pass. Read the
current handoff for actually executed tests; this list is not an acceptance receipt.
