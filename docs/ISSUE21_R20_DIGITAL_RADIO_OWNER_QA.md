# R20 digital radio and owner-feedback corrections — bounded QA handoff

Status: **DRAFT / owner physical feedback FAIL / corrective QA pending**. Based on exact
R19 integration parent `76b8164308dd2c8ca6da465e0df729c102715124`.
Do not merge, publish or reuse streams commercially from this draft.

## November 20 owner feedback and corrected scope

Mark's physical test of the supplied R20 candidate reported missing active
Sources, a thin Daily Brief, undiscoverable/failing preset saves, HAM controls
below the visible area, and incomplete receiver discovery. The prior
`e33c0618fa13b1e490dab7670a9abac83ff7e315` source/package conditional decision
is historical, not physical acceptance of this new source. The screenshot
alone does not independently establish the installed binary hash.

- **Sources:** the existing registry has 170 entries; ordinary missing rows
  were not reproduced as a catalog truncation. The separate GDELT batch
  collector was absent from the inventory and is now shown with recorded
  status. Search, collection-state filters, enabled/total/matching counts and
  Show all retain off, unavailable and never-checked sources. Selected detail
  state follows enable/disable, monitoring and health changes without an extra
  Store query. GDELT-linked websites are not counted as registered publishers.
- **Daily Brief:** actual daily retrieval and rendering increase from four to
  eight records per non-weather topic (60 total maximum, three weather).
  Category selection shares the budget before filling busy categories. The
  brief includes dated source excerpts, recorded changes, topic coverage and
  evidence counts with an explicit rolling 24-hour/7-day window. Missing topics
  remain coverage gaps. Severity UNASSESSED and evidence verification are
  separate; no verification or Store logic was relaxed, and unchecked stories
  are not relabeled verified. Archive update dates are not event dates.
- **Radio presets:** visible Save/Recall/Clear controls with named slots;
  writes require a real storage backend and exact read-back confirmation.
  SQLite close/reopen/recall/clear is tested. Failed writes do not claim success
  or discard the prior slot. Recalling a hidden station restores the filter
  atomically and does not turn power on or briefly play an intermediate station.
- **HAM:** Lower/Higher, step, frequency, mode, Tune, receiver selector and
  Connect/Stop sit directly beneath the digital readout. Verbose receiver,
  volume and scan details are a bounded collapsible area. Production-style
  600x480 and 960x640 offline layout checks are not physical Windows proof.
- **Local radio by ZIP:** explicit, opt-in US five-digit ZIP lookup sends the
  entered ZIP to Zippopotam.us. Radio Browser receives a US geocoded-station
  query and the client's IP, not the ZIP; distances are calculated locally.
  No automatic location request, saved ZIP, audio start, cookies or redirects.
  Station/genre search and 25/50/100-mile radii use approximate ZIP-center
  distances, not broadcast coverage. Community entries without coordinates
  are absent; bounded/partial results are labeled. Provider failure invalidates
  partial results so a filter change cannot hide the failure.
  Unreviewed stations open only after consent in the default browser. Only an
  exact existing reviewed stream can select its bundled Pulse station ID.
  **Ordinary PCs need tuner/SDR hardware for over-air AM/FM**; this feature
  discovers Internet stations and does not add an RF receiver.

### WebSDR permission blocker — full built-in directory NOT delivered

The official WebSDR landing page is a frameset; its actual receiver metadata
loads separately and explicitly prohibits reuse in another website or
automated system without prior permission. No such permission is recorded.
No restricted list was saved, copied into tests, scraped into the application
or fetched through an alternate path. No provider-contact request was sent.
Automatic WebSDR list import therefore remains blocked. The interface explains
this and retains the explicit official-directory browser action, known NA5B,
and validated manual receiver URLs. This is not a complete built-in WebSDR
directory. Kiwi's separate existing import must retain honest unavailable/empty
status; a directory entry never verifies reception, audio or reuse rights.

Fresh exact-source full Windows packaging and a distinct independent QA
disposition are required. Original strict 420ms/exactly-two redraw gate and all
inherited exclusions remain unchanged. No R21, certificate/trust-store change,
release/tag/merge or claim that YouTube Error 153 is fixed.

### Offline fixture corrections found by the full regression gate

The first local integrated run reported 1,951 passes and two failures with the
same 14 historical deselections and two ignored modules. Distinct QA reproduced
both failures on untouched `e33c0618` in a separate checkout:

- The map single-classifier equivalence test compared a fixed November 17
  baseline with a live-clock widget call. Its +3-day future record becomes
  current on November 20. The test now supplies the same fixed clock to both
  sides; all event equality, single-classifier and neutral-evidence assertions
  remain intact. No product classifier/time behavior changed.
- The unknown-language Collector test mocked HTTP but left its preceding
  custom-feed DNS admission live. The test now injects a public-address DNS
  fixture for the exact test host, asserts that admission was exercised, and
  retains the real Collector/SQLite persistence checks. No live feed is
  contacted, and production DNS/SSRF checks remain unchanged.

These are test-input isolation corrections, not new exclusions or threshold
relaxations. The exact workflow guard additionally names both changed tests.
They do not claim a repair of physical Windows performance or audio.

### Native 9ae gate failure and corrective follow-up

The first full Windows package run for exact `9ae3eddef089da755452e0e6d32e699ecaedf32b`
failed with 1,950 passes, three failures and the unchanged 14 deselections.
Qt teardown returned 1,487 objects to zero. Installer smoke and all artifact
uploads were skipped; **there is no 9ae installer or package approval**.

- The 600x480 HAM layout test exposed a genuine Windows font/layout difference:
  expanding details and scan grew the panel to 495 pixels. The follow-up reduces
  unnecessary margins/gaps while keeping the exact 600x480 assertion and all
  primary controls; it must pass the native backend again.
- The HTML-export test incorrectly read the UTF-8 output with Windows cp1252.
  The test now reads UTF-8 and checks the declared charset. Product export
  encoding remains UTF-8; no content is removed to hide the issue.
- The new Store brief fixture used a Windows short-name temporary path. It now
  resolves that fixture path before Store construction. The production
  canonical-path/storage safety guard is unchanged.
- Read-only visual QA also found hard-to-read default-blue source links on
  the dark Brief. The corrective renderer uses the existing theme's readable
  underlined link foreground and matching body colors for both preview and
  standalone HTML export; source URLs, severity and evidence are preserved.

These follow-up changes require a fresh immutable source identity, full native
gate, installer smoke and distinct downloaded-byte review. No prior green
Linux run or older package substitutes for them. The exact cumulative workflow
allowlist includes the renderer and UTF-8 test; test exclusions are unchanged.

### Native 4c0 font-metric boundary failure

The corrective Windows run for `4c0e7bf74a543e16993797dbd53adb343c840979`
passed 1,954 tests but failed the new taller-font HAM layout regression: the
600x480 panel expanded to 600x481 when details and scan were expanded. The
normal-font bounds checks, UTF-8 export fixture, canonical Store fixture and
all remaining cases passed; the same 14 deselections were retained and Qt
teardown returned 1,487 objects to zero. Packaging and smoke were skipped and
the run produced no artifacts. This is another native HOLD, not a ready build.

The next bounded layout correction must recover actual space with a useful
font-metric margin, while preserving the exact 600x480 assertion, every core
tuning control and the usable details viewport. A fresh full native run,
installer smoke and distinct downloaded-byte review remain required. No test
threshold, font-stress case, backend or exclusion may be relaxed to accept it.

The follow-up removes only the duplicated HAM/SDR eyebrow already supplied by
the tab and reduces readout padding from 10 to 8 pixels, keeping its 34-pixel
font and every primary control. This recovers 20 actual vertical pixels beyond
4c0 in the diagnostic layout. The same stress case additionally requires a
minimum-height hint of at most 470 pixels and a details viewport of at least
24 pixels. Local focused radio checks pass, but native acceptance is still
pending for the new exact source.

## Intent and limits

- Broadcast and HAM/SDR are separate tabs. The broadcast dial shows the
  broadcaster's published AM/FM frequency **only where documented**; internet-
  only services show `INTERNET STREAM`. Previous/Next changes the documented
  station selection; it never scans unreviewed RF frequencies. Genre filters
  cover News & Talk, Music, Classical and Culture, with All stations as default.
- There are initially **18 pinned publisher-documented HTTPS MP3 streams**.
  A consented external Radio Browser link and the ZIP-based metadata lookup
  support wider station discovery; community streams are **not** imported into
  the native player without review.
  No automatic network call occurs merely by opening the radio tab.
- The HAM dial shows the **requested** frequency in a large MHz readout and an
  exact kHz/mode caption. Lower/Higher buttons step by selectable 1, 5, 10, 25
  or 100 kHz. Actual operator tune/receive/audio **cannot** be established by
  URL creation or a successful webpage load. The operator's embedded controls
  remain authoritative. Advanced scan is opt-in and initially collapsed.
- HAM receiver selector retains the known NA5B owner-tested HTTP/8901 link,
  manual validated URLs and the separate on-demand bounded Kiwi flow.
  Automatic WebSDR import is blocked pending permission as described above.
  The separate external
  **Open directory** action also names plaintext HTTP and IP disclosure before
  opening the WebSDR URL; refusal opens no browser and makes no request.
  No automatic receiver
  connection, no recording, no transmission, no unreviewed origin expansion.
- If an operator provides explicit `bands` as JSON metadata, the GUI displays
  those labels, without claiming exact bounds. NA5B's screenshot-observed band
  labels are disclosed as such, not as a universal frequency plan.

## Required independent QA

| ID | Check | Required evidence |
| --- | --- | --- |
| R20-01 | Launch and idle on physical Windows before any clicks | No baseline UI choppiness, stalled startup, or foreground network fetch; capture CPU, click responsiveness and video idle |
| R20-02 | Open Broadcast tab; navigate 10+ stations rapidly | No freezes; large digital label and selected name stay synchronized; no playback until Power/consent |
| R20-03 | Filter News, Music, Classical, Culture; Save/Recall/Clear all five presets; restart | Named slots survive an actual Store close/reopen; save failure is visible; hidden preset restores All stations atomically; selection does not start playback |
| R20-04 | WNYC FM/AM and WQXR vs internet-only streams | RF frequency shown only where publisher supplies it; otherwise `INTERNET STREAM` |
| R20-05 | Power/Stop All then switch tabs, pages, sources | Old audio sessions close; no background auto-connection or stale liveness |
| R20-06 | At 600x480 and 960x640 select NA5B, change mode; step Lower/Higher; expand details | Primary tuner and Connect/Stop stay visible; exact requested kHz/MHz/mode and consented target; no audio claim from page load |
| R20-07 | WebSDR permission message/external directory; Kiwi refresh/failure | WebSDR import makes no request without recorded reuse permission; explicit external HTTP consent; valid manual/NA5B entries remain usable; no auto-connect or availability claim |
| R20-08 | Play NA5B live with receiver's own controls and verify waterfall/audio | Record separate results for page load, actual signal/waterfall, and audible audio. No provider controls bypassed |
| R20-09 | Confirm YouTube player separately | Error 153 still OPEN unless real Windows playback proof is attached; R20 changes do not claim this fixed |
| R20-10 | Offline suite, exact native Windows build, installer/rollback smoke | Preserve process exit, exclusions, one-EXE quick-test ZIP, portable ZIP separately, and SHA-256 receipts |
| R20-11 | Sources all/enabled/off/unchecked/search/Show all; selected state changes | All registry entries remain discoverable, exact counts, GDELT separate, no extra passive Store read/network fetch, no stale selected collection status |
| R20-12 | Actual Store daily brief with more than four reports per topic | Up to eight/topic; bounded weather; original verification preserved; dated attributed detail and changes; no fabricated missing topics, publication dates or corroboration |
| R20-13 | ZIP discovery accept/refuse/cancel/failure and radius/genre filter | No request before consent; only five-digit ZIP to disclosed provider; bounded async metadata; no redirects/cookies; late responses ignored; failures cannot become success via filtering |
| R20-14 | Discovered station selection and external URL consent | Only exact reviewed catalog matches select native station; no autoplay; arbitrary community URL remains browser-only with encoded consent text, rights/HTTP disclosure and default refusal |

## Source and rights provenance

- WNYC/WQXR streaming directory:
  https://prod.wnyc.org/audio-other-formats/
- Deutschlandradio streaming directory:
  https://www.deutschlandradio.de/streamingdienste-100.html
- Radio France documented brand/webradio stream examples:
  https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-brands
  and https://developers.radiofrance.fr/doc/en/tutorial-by-example/list-locals-and-webradios
- WebSDR operator directory: http://www.websdr.org/
- KiwiSDR operator directory: https://kiwisdr.com/public/
- Community station discovery, external and unvetted:
  https://www.radio-browser.info/
- Radio Browser official API and service discovery:
  https://docs.radio-browser.info/ and https://api.radio-browser.info/
- ZIP-to-approximate-center metadata (not exact user location):
  https://api.zippopotam.us/

Public release is **HOLD** until independent QA, live Windows audio/performance
verification, YouTube handling decisions, and publisher/licensing authorization.
