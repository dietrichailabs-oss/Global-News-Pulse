# R20 digital radio — bounded owner-test handoff

Status: **DRAFT / private owner test / independent QA pending**. Based on exact
R19 integration parent `76b8164308dd2c8ca6da465e0df729c102715124`.
Do not merge, publish or reuse streams commercially from this draft.

## Intent and limits

- Broadcast and HAM/SDR are separate tabs. The broadcast dial shows the
  broadcaster's published AM/FM frequency **only where documented**; internet-
  only services show `INTERNET STREAM`. Previous/Next changes the documented
  station selection; it never scans unreviewed RF frequencies. Genre filters
  cover News & Talk, Music, Classical and Culture, with All stations as default.
- There are initially **18 pinned publisher-documented HTTPS MP3 streams**.
  A consented external Radio Browser link supports wider station discovery;
  community streams are **not** imported into the native player without review.
  No automatic network call occurs merely by opening the radio tab.
- The HAM dial shows the **requested** frequency in a large MHz readout and an
  exact kHz/mode caption. Lower/Higher buttons step by selectable 1, 5, 10, 25
  or 100 kHz. Actual operator tune/receive/audio **cannot** be established by
  URL creation or a successful webpage load. The operator's embedded controls
  remain authoritative. Advanced scan is opt-in and initially collapsed.
- HAM receiver selector is populated only from on-demand, bounded public
  directory metadata. An exact NA5B owner-tested HTTP/8901 link is pinned even
  when WebSDR's HTTP directory is unavailable. Network directory refresh
  requires explicit user approval for unencrypted HTTP. The separate external
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
| R20-03 | Filter News, Music, Classical, Culture; save/recall five presets | Only matching stations appear; hidden preset restores All stations; selection does not start playback |
| R20-04 | WNYC FM/AM and WQXR vs internet-only streams | RF frequency shown only where publisher supplies it; otherwise `INTERNET STREAM` |
| R20-05 | Power/Stop All then switch tabs, pages, sources | Old audio sessions close; no background auto-connection or stale liveness |
| R20-06 | Select NA5B, change HAM mode; step Lower/Higher | Exact requested kHz/MHz/mode changes and proper receiver page target is loaded after consent; never claim audio from page load |
| R20-07 | Refresh WebSDR and KiwiSDR directory, including HTTP refusal/failure | Existing available entries remain selectable; malformed/private URL rejected; pinned NA5B available offline; no automatic receiver connect |
| R20-08 | Play NA5B live with receiver's own controls and verify waterfall/audio | Record separate results for page load, actual signal/waterfall, and audible audio. No provider controls bypassed |
| R20-09 | Confirm YouTube player separately | Error 153 still OPEN unless real Windows playback proof is attached; R20 changes do not claim this fixed |
| R20-10 | Offline suite, exact native Windows build, installer/rollback smoke | Preserve process exit, exclusions, one-EXE quick-test ZIP, portable ZIP separately, and SHA-256 receipts |

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

Public release is **HOLD** until independent QA, live Windows audio/performance
verification, YouTube handling decisions, and publisher/licensing authorization.
