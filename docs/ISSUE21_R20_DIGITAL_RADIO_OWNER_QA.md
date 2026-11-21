# R20 digital radio and owner-feedback corrections — bounded QA handoff

Status: **DRAFT / bounded YouTube correction under review / no new playback PASS**. Based on exact
R19 integration parent `76b8164308dd2c8ca6da465e0df729c102715124`.
Do not merge, publish or reuse streams commercially from this draft.

## November 21 priority: YouTube playback and truthful player state

The owner's latest feedback is **"much better now try and get youtube working"**.
This records improvement of the recent tray/shutdown candidate, not blanket
physical acceptance. Preserve the working tray path and the owner's earlier
scoped HAM audio/tuning result. The exact accepted baseline for this bounded
successor is `18127060ba64aef506f5614e27507837ea1ad34a`, tree
`7723c57319bee4f4692c795d46224193a166a772`. Its native/package evidence remains
historical evidence for those bytes, not approval of this change.

### Demonstrated defects and separate identity dependency

An offline execution of the actual native observation JavaScript demonstrates
that a hidden YouTube error element can be returned as a fatal error while the
video reports advancing time and decoded frames. The native helper also starts
a 45-second no-progress deadline at navigation despite `autoplay=0` and the
instruction to press Play manually. Finally, its error receipt collapses all
provider failures into one generic reason and the UI discards earlier identity
and HTTP observations on Stop. These are reproducible source/fixture defects;
none establishes the cause of the owner's particular live Error 153.

[Google's required minimum functionality](https://developers.google.com/youtube/terms/required-minimum-functionality)
requires embedded-player identification and specifies the installed package
identity's Name component for non-store Windows distribution. The current
classic installer does not register such an identity; the real publisher URL
fallback is not a substitute. Do not invent an identity, import a certificate,
change trust stores, add signing/registration, or call an HTTP 200 response proof
that YouTube accepted the application. Those installation changes require a
separate owner decision if the embedded route needs them.

### Bounded correction contract

- Keep the existing, separately consented **Try YouTube watch page in Pulse**
  path. Use normal WebView2 navigation for that exact official watch URL, without
  injecting the embed Referer. Do not add automatic embed-to-watch fallback or
  claim normal-watch success is an embedded Error 153 fix.
- Treat only visibly displayed provider errors as fatal. Preserve recognized
  numeric error codes and bounded error classes, not raw page text, URLs,
  cookies, headers, or arbitrary HTML. Label DOM observations as observations,
  not fabricated IFrame API events.
- Distinguish awaiting manual Play, paused, buffering, advancing, stalled and
  ended states. A deliberate pause must not become a false playback failure.
  Retain separate finite deadlines for missing document/video, a lost callback,
  and actual unpaused no-progress; a pending JavaScript reply must not defeat
  the liveness deadline. Use monotonic elapsed time.
- Preserve the safe backend/mode, package-identity, pre-send Referer and HTTP
  observations in the final error readout. Show state changes promptly while
  retaining the existing rate limit for repeated numeric telemetry.
- Keep explicit exact-video consent, muted initial state, manual Play, private
  profile, native child ownership, Stop/Exit, sandbox, host/frame/redirect,
  permission and download restrictions. Do not broaden hosts speculatively or
  accept provider sign-in, cookie, age, geo, or bot prompts automatically.

The cumulative workflow source allowlist expands from 31 to 37 paths solely
for `global_pulse/single_media.py`, `packaging/tv/NativeTvProgram.cs`,
`tests/test_issue22_windows_package_identity.py`, and the new
`tests/test_issue22_youtube_playback_observation.py`, plus the opt-in diagnostic
`scripts/issue22_youtube_watch_probe.ps1` and its offline contract tests in
`tests/test_issue22_youtube_watch_probe.py`. The existing 14 deselections,
two ignored historical modules, tray latency thresholds, all eight offline
package checks, and distinct downloaded-byte QA remain unchanged.
The exact packaged native policy/playback cases and private codec probe now
also run offline before the installer smoke checks; neither contacts YouTube.

An additional live watch-page diagnostic is opt-in only: a push carrying
`[r20-youtube-live-qa]` in its commit message or the explicit workflow-dispatch
boolean. It runs after artifact creation against the actual frozen app with
a new disposable data directory. Its only authorized fixture is the existing
public Blender video `YE7VzlLtp-4`. Automation must interact with the real app
network-consent dialog and a currently observed native Play control, without
monkeypatching the dialog, starting the helper directly, guessing click
coordinates, or autoaccepting any provider prompt. Bounded app screenshots and
a separate `DIAGNOSTIC_ONLY` receipt must distinguish picture-progress
observations, provider denial, infrastructure failure, and unverified audio.
The hosted runner's actual token/desktop state is recorded; an administrator
runner is not standard-user or owner-PC acceptance. No new runtime dependency,
account, OS permission, package registration, or trust change is added.

### Required evidence before any success claim

Execute the actual observation script against inert adversarial fixtures,
including hidden ancestors, an earlier hidden error followed by a visible one,
visible recognized/unknown errors, valid progressing video, deliberate idle,
pause/resume, frozen playback and a lost callback. Verify bounded plain-text
diagnostics, terminal-state preservation and stale-session rejection. Run the
full local/native suites and fresh exact-source package verification before
describing a replacement installer as owner-test ready.

Live Windows acceptance remains separate: the selected official video must be
visibly playing with advancing decoded frames, audible after explicit unmute,
and responsive to pause/resume and Stop/Exit. A disposable CI playback attempt,
if separately recorded, is not owner-PC acceptance; lack of an interactive
desktop or audio device is not a PASS. Provider restrictions remain an honest
blocked result. Offline tests and successful document loading do not establish
live picture/audio. Public release remains on hold.

## Latest November 20 follow-up: visible receiver list and tray exit

The owner reported that the area below **WebSDR public receivers** still looked
like an empty manual-URL box. The same follow-up reports that tray **Exit
Completely / Close app** takes too long. These are new acceptance findings
against the prior `b420d956890ae28245d93012895520e48e8487b6` candidate; its
successful run and conditional owner-test approval remain historical evidence
for its exact bytes, not approval of this successor.

### Visible receiver selection contract

Show a selectable, scrollable receiver list directly below the provider row,
with receiver names and published frequency windows or operator band labels.
Keep the selected receiver, manual URL, requested frequency/range and Connect
action synchronized. Cold start and returning from the other directory must
show the built-in entries without a network refresh. A search with no matches
must say so rather than leave a misleading stale selection. Selection and
filtering do not connect or start audio; the explicit Connect action retains
origin-specific HTTP consent and all existing browser-only routing.

The core list and tuner must remain usable at 600x480, including the existing
one-pixel font stress and minimum-height headroom. The receiver details can
scroll independently; adding a list must not bury Lower/Step/Higher or Tune.

### Additional individually verified receiver entries

A second pass recognized more names in the supplied screenshots. Exact links
and coverage were then checked against each operator, not guessed from tiny
URL characters and not imported from the restricted central directory feed.
The built-in list now has **18 entries**, including these 11 additions:

| Receiver | Operator-documented endpoint | Stored coverage |
| --- | --- | --- |
| Maasbree HF low | `http://sdr.websdrmaasbree.nl:8901/` | 160m-15m band-family label; separate windows, exact HF edges unknown. |
| Maasbree HF high | `http://sdr.websdrmaasbree.nl:8902/` | 40m-10m band-family label; separate windows, exact HF edges unknown. |
| Maasbree 2m | `http://sdr.websdrmaasbree.nl:8905/` | Separate 144-145 and 145-146 MHz antenna windows. |
| KFS #1 | `http://websdr1.kfsdr.com:8901/` | 80/75, 60, 40, 30, 20, 17, 15 and 10m labels; exact edges unknown. |
| KFS #2 | `http://websdr2.kfsdr.com:8902/` | 160m, 12m and 10m-FM labels; exact edges unknown. |
| G0XBU Jodrell #1 | `http://g0xbuwebsdr.ddns.net:8901/` | 20m, 80m, 60m, 4m, CB, Airband and Marine labels; independent of Jodrell Bank. |
| G0XBU Jodrell #2 | `http://g0xbuwebsdr.ddns.net:8902/` | 2m, 70cm, PMR446, 6m and Airband labels. |
| DF0HTE, Esslingen | `https://websdr.afunk.hs-esslingen.de/` | Eight numeric windows from the indexed operator mobile page. |
| AMSAT-UK/BATC, Goonhilly | `https://vhf-goonhilly.batc.org.uk/` | 144-146, 435-437, 1296-1298 and 2320-2321 MHz, four separate windows. |
| Pardinho | `https://pardinho.websdr.com.br/` | 160m, 80m, 40m, 20m, 15m and 10/11m labels. |
| OA6DXV / RepublicaOA6 | `https://websdr2.republicaoa6.com/` | 40m; the published 7100 kHz center is not a coverage boundary. |

Primary evidence: [Maasbree operator manual link](https://websdr-maasbree.jouwweb.nl/operation/user-manual),
[Maasbree manual, July 29 2026](https://www.pa0sim.nl/Manual_WebSDR_Maasbree.pdf),
[KFS](https://www.kfsdr.org/), [G0XBU](https://www.g0xbu.co.uk/websdr),
[DF0HTE mobile range list](https://websdr.afunk.hs-esslingen.de/m.html),
[Goonhilly](https://vhf-goonhilly.batc.org.uk/),
[Pardinho](https://pardinho.websdr.com.br/), and
[RepublicaOA6](https://websdr2.republicaoa6.com/).
Indexed operator metadata is identified as such in the records; it is not a
personal observation of live tuning or audio. The complete screenshot directory
has not been transcribed, and other uncertain receiver identities remain absent.

The HTTP allowlist adds exactly seven reviewed host/port pairs (three Maasbree,
two KFS and two G0XBU). Four new receivers use HTTPS/443, with accurate transport
wording rather than an HTTP/None warning. Explicit HTTPS port 443 is the same
origin as implicit 443; other ports and schemes do not inherit curated facts.
Higher Goonhilly tuning is permitted only within the exact reviewed receiver's
documented windows. The generic unknown-receiver 0.1-500000 kHz limit and scan
step bounds must not be expanded by untrusted cached metadata.

### Responsive, safe full-exit contract

The previous tray path performed layout persistence, serial notification-helper
waits and controller/collector shutdown before removing the visible UI. The
correction must respond to the click promptly, stop admitting new work, cancel
owned worker processes and network work, preserve critical settings/Store writes,
and finish actual shutdown without blocking the GUI event loop. Repeated exit
requests are idempotent. Merely hiding an indefinitely running process, killing
unrelated processes, or using `os._exit` to discard pending writes is not accepted.

The workflow's exact cumulative source list expands from 24 to 30 paths only
for this owner-reported exit defect: `global_pulse/__main__.py`,
`global_pulse/native_notifications.py`, `global_pulse/gdelt_service.py`,
`global_pulse/translation_process.py`, `global_pulse/sources.py`, and
`tests/test_owner_feedback_qa_repairs.py`. The last file's production-shutdown
binder follows asynchronous completion while retaining its camera-abort,
consent and singleton-order assertions. This is an explicit source-scope
expansion, not a new test exclusion or weaker threshold. The original 14
deselections, two ignored historical modules and strict 420ms/exactly-two redraw
assertion remain.

### Fresh acceptance required

The `f113dfa8c3d0de10470893524b9320f66daa9c28` full local run passed
2,027 tests, but a subsequent independent 151-test focused run recorded one
failure in the unchanged 420ms/exactly-two reentrant-refresh gate. The first
composition reached its redraw at 248.9ms and a second 160ms debounce was then
armed; the 421.1ms observation still saw only one redraw. One separately
recorded isolated invocation passed. That intermittent result does not erase
the counterexample or grant acceptance.

The bounded production correction keeps ordinary first-due batching at an
explicit 160ms. Evidence arriving during composition is already coalesced and
is queued for a follow-up after the current composition has unwound, without a
second full debounce delay. The same callback still enforces the real one-second
worker gate and the independent 1.8-second navigation/apply cooldown. Closing
guards remain in force. The existing timing assertion, fixtures and exclusions
must stay unchanged; added deterministic tests cover pending follow-up batching,
non-recursion, ordinary interval restoration and the retained idle gates.

This concrete independent finding adds only `global_pulse/ui.py` to the exact
cumulative workflow source set, taking 30 paths to 31. It does not broaden the
package workflow or waive any full-suite, native smoke or byte-verification gate.

Independent review must cover real visible list geometry and selection,
finite-origin HTTP/HTTPS behavior, new numeric endpoints and unknown bounds,
prompt tray click handling, actual worker/process retirement, thread affinity,
safe persistence and repeated exit. A fresh full local/native suite, all eight
offline Windows package checks, and distinct downloaded-byte QA are required
before a replacement installer is described as owner-test ready. Live receiver
audio, YouTube Error 153, physical owner-PC performance and public-release rights
remain separate OPEN/HOLD items.

## Earlier November 20 follow-up: seven receivers and World overview

This bounded successor responds to the owner's supplied receiver links and
directory screenshots, and the separate **World intelligence overview**
screenshot. The prior `b4ecd0442f65651a68aec882ebed12435abba028` package remains
conditionally accepted only for its own frozen bytes; its QA decision does not
approve this successor. Exact new source/native/package evidence and a distinct
review are required before a replacement owner-test handoff.

### Individual receiver directory

That earlier local selector contained seven attributed receiver choices: the existing
NA5B link, the two explicitly pasted links, and four Northern Utah receivers
individually checked against their operator's documentation. Loading this list
does not request a central feed or connect any receiver. Selecting a name sets
the URL, lists its documented frequency windows and enables a range selector;
Connect, Lower/Higher and manual Tune still require an explicit user action.

| Receiver | Exact supplied/documented URL | Frequency provenance |
| --- | --- | --- |
| NA5B | `http://na5b.com:8901/` | Existing owner-observed band labels; no invented numeric limits. |
| University of Twente, Enschede, Netherlands | `http://websdr.ewi.utwente.nl:8901/` | Owner supplied 0.000–29.160 MHz; live coverage is not verified. |
| Odlisi–Kakheti HF WebSDR, Georgia | `http://sdrgeorgia.sytes.net:8902/` | NARG lists 26.976–29.024 MHz. |
| Northern Utah #1, Yellow | `http://websdr1.sdrutah.org:8901/index1a.html` | Operator's separate LF/MF/HF windows, not one continuous range. |
| Northern Utah #2, Green | `http://websdr2.sdrutah.org:8902/index1a.html` | Operator's separate 30 m through 6 m windows. |
| Northern Utah #4, Magenta | `http://websdr4.sdrutah.org:8904/` | Operator's separate HF windows, east-facing antenna. |
| Northern Utah #5, Teal | `http://websdr5.sdrutah.org:8905/` | Operator's separate HF windows, northwest-facing antenna. |

Primary references checked November 20:
[WebSDR linking/tuning FAQ](https://websdr.org/faq.html),
[NARG receiver information](https://narg.ge/websdr-tbilisi/),
[Northern Utah exact URLs and tune parameters](https://www.sdrutah.org/info/urlparam.html),
and [Northern Utah receiver windows](https://www.sdrutah.org/info/techinfo.html).
The Utah table prints a 20 m upper bound of **14.354 MHz** while its quoted
center/bandwidth are inconsistent with that number. The app preserves the
published value with a provenance warning; it does not silently infer 14.534.
Ranges are advertised/owner-supplied metadata, not proof of receiver lock,
waterfall, audible reception or current server availability.

The initial pass recovered only these seven entries. A later sectional image
review identified additional receiver names, which were checked against their
own operator pages as recorded above. Exact tiny URL/frequency characters are
not guessed, and the entire directory is not claimed as transcribed. No
restricted central dataset was downloaded to fill the gaps. The official FAQ
permits independently maintained receiver links; that is distinct from automated
reuse of its complete maintained dataset.

Each newly admitted legacy receiver has an explicit reviewed HTTP host/port
pair. Consent names the exact unencrypted origin, and the ephemeral embedded
session remains confined to that origin. No general HTTP/custom-port wildcard,
automatic connection, native decoder admission, recording or retransmission is
added. Known frequency windows constrain requested tuning; unknown bounds do
not become fabricated coverage. The existing geometry/font-stress, late-load,
Stop/cleanup and no-autoplay contracts remain mandatory.

### Separate World overview correction

The World overview was still a two-headline-per-topic renderer, separate from
the richer Daily Brief. Routine EMA PIP/orphan-designation paperwork could fill
its health shortlist before any meaningful health situation reached rendering.
The successor prioritizes non-administrative health records before truncation,
separates narrowly recognized paperwork into a labeled background section, and
shows bounded existing recaps, source dates, importance and evidence separately.
Canonical source categories, report verification and original event IDs remain
unchanged. No outbreak/conflict summary is generated to fill missing evidence.

The registered catalog also gives the explicit UN **Peace and Security** feed a
generic News category. Only that exact documented topic feed may supply an
overview-only security-topic grouping, visibly attributed as such; it does not
assert an active conflict or change the stored category. Generic UN/Crisis Group
items and headline-keyword guesses are not reclassified. Missing categories
remain honest local coverage gaps, not a worldwide all-clear. The owner's actual
Store is unavailable here, and the existing bounded feed/map reads can omit
older records; this correction does not claim exhaustive world coverage.

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

### Automatic central WebSDR dataset import remains permission-blocked

The official WebSDR landing page is a frameset; its actual receiver metadata
loads separately and explicitly prohibits reuse in another website or
automated system without prior permission. No such permission is recorded.
No restricted list was saved, copied into tests, scraped into the application
or fetched through an alternate path. No provider-contact request was sent.
Automatic WebSDR list import therefore remains blocked. This does not prohibit
the individually supplied/operator-documented receiver links described above.
The interface distinguishes those local choices from central import and retains
the explicit official-directory browser action and validated manual receiver
URLs. This is not a complete built-in WebSDR directory. Kiwi's separate existing
import must retain honest unavailable/empty
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

## November 20 owner follow-up: tray menu and shutdown callbacks

After the `84a98bdb` owner-test handoff, Mark reports that HAM radio audio and
tuning work on his machine. Record this as **owner-observed PASS for the tested
receiver/session**, not all-receiver or waterfall acceptance. This feedback does
not independently identify his installed source hash or selected receiver.

Two owner failures remain distinct:

1. The tray icon's menu/list, including Exit, is slow to appear **before** an
   Exit action can be selected.
2. Closing displayed source-callback error wording, re-showed the dashboard,
   then eventually closed. The exact owner log or stack trace was not supplied.

The prior local/native/package passes remain historical automated evidence;
they do not override this physical owner feedback. Reports are recorded on
[PR182](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/182#issuecomment-7055319464)
and the [Issue2 owner ledger](https://github.com/dietrichailabs-oss/Global-News-Pulse/issues/2#issuecomment-7055319710).

Independent reproduction of the accepted `4fad0cd8` source found:

- A 350 ms worker-held Store lock blocked the Qt tray-health read for 351.01 ms
  and delayed an already-queued menu popup to 371.9 ms. Coalescing health reads
  to 700 ms did not make each read nonblocking.
- A normal admitted callback still holding the shutdown barrier after one
  second produced the text `A source archive callback is still finishing;
  exit can be retried safely`. The Store correctly remained open, but ordinary
  drain was presented as failure rather than completing automatically.
- The existing recovery handler explicitly called `window.show()`, changing
  the main dashboard from hidden to visible.

These are real SQLite/Qt **offline source-path reproductions**, not recovered
owner logs, a claim of process restart, or physical Windows latency timings.

The successor must keep tray-menu presentation independent of busy database
work; distinguish temporary callback/ingest drain from genuine write failure;
and keep any necessary recovery UI separate from the closed main dashboard.
No forced process exit, discarded writes, premature singleton release, or
indefinitely hidden failed cleanup is acceptable. Late callbacks and repeated
Exit must remain harmless. Final layout and notification history must still
be committed, and only owned child processes may be cancelled.

Required new regression evidence includes lock-contended Qt menu popup, actual
admitted callback retirement with persisted readback, no false early shutdown
warning, genuine storage-error recovery, no dashboard resurrection, and safe
close-to-tray layout persistence. Fresh exact-source local/native full tests,
offline installer lifecycle and distinct downloaded-byte QA are required
before another test-ready handoff. No existing test threshold, exclusion or
public/rights/YouTube gate is relaxed. Working HAM behavior stays unchanged.

### Bounded successor implementation and acceptance scope

- Tray health takes a nonblocking Store lease. On BUSY it keeps the last
  measured icon state and retries on the normal timer; it never paints a false
  healthy status or makes menu presentation wait for a collector transaction.
- Close-to-tray reads cached **persisted** policy, captures Qt layout values on
  Qt, and uses one coalesced disk worker. The six layout values commit atomically
  without six dashboard-refresh signals. The ingestion/shutdown barrier and a
  second closed-state check prevent old deferred saves from overwriting the
  final Exit snapshot or touching a closed connection.
- Only the scheduler callback barrier and ingestion-lock contention are typed
  as `ShutdownPending`. They retry serially without overlapping finalizers.
  The existing three-second deadline bounds the invisible phase: admitted
  work still draining after that point shows standalone informational progress
  and completes automatically when safe. It does not reopen the dashboard.
- Genuine SQLite/write/child errors retain warning and Retry behavior. A real
  error after temporary waiting takes precedence over the old progress state.
  No exception-log suppression or blanket retry of arbitrary failures is used.
- The previous **untracked Store-lock timeout** recovery test stays unchanged:
  that distinct condition still reports a recoverable archive-close problem
  and requires Retry. This patch does not classify every Store reader or lock
  timeout as admitted callback drain or promise zero-time durable shutdown.

Pre-freeze engineering found a new pending-to-real-SQL-error race: its latency
module run returned 35 passed / 1 failed because the timer remained active when
a finalizer failed during the same launch/deadline turn. Production deadline
handling now stops that timer and preserves the true failure. The failing
assertion was not relaxed. This diagnostic was retained as tool-output evidence,
not a fabricated raw-log file or a frozen-source/full-suite result.

Regression additions also exercise the actual Qt menu and bootstrap close
handler under a worker-held Store lock, one-second-plus admitted callbacks,
progress-to-failure recovery, atomic rollback and readback, old-save/Exit races,
coalesced snapshots, later saves after SQLite failures, and retirement of the
Qt writer while a disk error is returning. Existing latency thresholds, test
functions, workflow exclusions, native-backend and package smoke gates remain
unchanged. Independent/full/native/package acceptance must be recorded against
the new immutable source, not borrowed from `84a98bdb`.

### Native 931c97d8 HOLD and explicit UTF-8 fixture correction

The first exact native run for the tray/shutdown correction,
`44852569456` attempt 1 / job `136687120303`, failed on source
`931c97d84c22674a3640cb35861e08da01418b1c`, tree
`803989dd5ac6cb865aca62dbd5c18e45f039aa7a`: **2,058 passed, 1 failed,
14 historical deselections, 10 subtests in 439.30 seconds**. Qt teardown was
1,557 to zero and the test command exited 1. Installer smoke, ZIP checks and
uploads were skipped; there were zero artifacts. The separate local 2,059
passes and independent 248 passes do not override this native HOLD.

The only failed assertion compared the new tray test's tooltip text. Its
preceding less-than-150-ms menu response, visible first-click menu, enabled
Exit action, deferred refresh and retained last-real icon checks all passed.
The bootstrap source is UTF-8, but its AST test helpers used locale-default
`Path.read_text()`. Independent codepoint reproduction established that the
middle-dot literal U+00B7 becomes U+00C2 followed by U+00B7 when those UTF-8
bytes are decoded as Windows CP1252. Normal Python source import decodes it
correctly. The connector-decoded Windows console log is itself lossy for
these characters, so this diagnosis is based on source bytes and codepoints,
not the rendered replacement glyphs.

The bounded child fixes all four bootstrap AST readers in the existing
latency test module to use `encoding="utf-8"`, and appends one deterministic
regression for the codepoints and every reader's explicit encoding. Product
code, tooltip text, thresholds, assertions, exclusions, workflow and build
scripts are unchanged from `931c97d8`. Two reads are inside test-function
bodies, including one test predating this correction: their decoding call
changes are explicit exceptions to prior whole-function AST identity claims.
All of their assertions and acceptance thresholds remain unchanged.

The failed run is preserved at
[native HOLD evidence](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/182#issuecomment-7055585629).
Its connector-decoded/LF-normalized log SHA-256 is
`47aa48bbcb5cec43f0216c64e0423920b2ecec8539db8a4cb6dcb840bd613919`;
independent failed-run metadata SHA-256 is
`684218dfe22852697094aa6cf39b71497fb7c93dad5d41c5782694a85f0abeb1`.
Do not rerun the failed source until green or publish an old package. The
explicit-encoding child requires its own exact-source full local/native
gates, eight offline package phases and distinct downloaded-byte QA.
