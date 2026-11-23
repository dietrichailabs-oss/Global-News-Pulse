# Worldwide live video research and launch readiness — 2026-11-23

Owner goal: 50–70 **actual live-video cameras**, not refreshing photographs. Preserve the cleaner R20 player and the 14 still-image entries. Preserve the owner-tested predecessor `e0a067fdd1b9886da4742abdde950fcf32e10b7f`. No public release or signing here.

## Research inventory: 64 named leads across six continents

The companion [research queue](WORLD_LIVE_CAMERA_RESEARCH_20261123.json) is **not** a runtime catalog. Every entry is NOT ADMITTED. Counts denote named operator listings for screening, not working streams, approvals, or active cameras. Motion was not observed in this review. Several providers may supply YouTube, still images, account-only content, intermittent or scheduled footage. Those are not acceptable as new live entries without an independently established supported alternative.

| Operator and source | Geography | Leads | Screening notes |
|---|---|---:|---|
| [Transport for NSW](https://www.nsw.gov.au/driving-boating-and-transport/boating-and-marine/using-waterways-boating-and-transport-information/conditions-weather-and-tides/webcams) | Oceania | 22 | Operator lists live vision; player rights and decoded motion pending. Third-party material excluded from general site licence. |
| [South Australia Department for Infrastructure and Transport](https://dit.sa.gov.au/marinesafety/web-cameras) | Oceania | 6 | Operator labels these as live sea-condition views; establish video versus still, specific player route, and footage terms. |
| [San Diego Zoo Wildlife Alliance](https://zoo.sandiegozoo.org/live-cameras) | North America | 13 | Operator lists live wildlife cameras; verify underlying provider, actual motion, hours, and desktop reuse. Exclude explicitly prerecorded Red Panda. |
| [National Park Service](https://www.nps.gov/media/webcam/view.htm?id=AF555E5C-BE40-FE91-52E98E0EDD833B68) | North America | 1 | NPS labels active live-stream; Canon/Yellowstone Forever attribution and actual player/rights require review. |
| [Korea Meteorological Administration / Korea National Park Service](https://www.weather.go.kr/gangwon/maple/cctv_knps.php) | Asia | 4 | Four HTML5 live-video labels; individual player routes and rights pending. |
| [BNU.tv](https://bnu.tv/) | South America | 6 | Operator advertises live video but also YouTube. Only promote after confirming a separate permitted non-YouTube player. |
| [NetMadeira](https://www.netmadeira.com/webcams-madeira) | Europe | 6 | Live-page listings; may be refresh images or YouTube. Thumbnail embed does not establish video permission. Format and rights pending. |
| [Africam](https://africam.com/) | Africa | 6 | Provider lists live wildlife viewing; sign-up and lodge routes noted. Held until approved public non-YouTube player with no login requirement is confirmed. |

### First review batch: provider-created CoastalCOMS player documents

These 10 exact document URLs were followed from the official NSW camera pages, using public provider player links, not extracted HLS URLs. A returned HTML document does not prove playback, rights, or current uptime. Lake Eucumbene showed a technical-issue notice; leave it held. Preserve the provider's notices/controls and original page link.

| Location | Published player document |
|---|---|
| Lake Eucumbene | [Video player](https://widget.coastalcoms.com/video/ee7e9e78-c228-4868-864c-8e8477a195c4) |
| Bermagui | [Video player](https://widget.coastalcoms.com/video/afdc038f-b8f6-466d-be38-a561260a45cb) |
| Ballina | [Video player](https://widget.coastalcoms.com/video/76818de6-1bc6-44d2-943a-3a905ee9c132) |
| Brunswick Heads | [Video player](https://widget.coastalcoms.com/video/db6bcca9-545e-4575-95ee-a5b1d4786f63) |
| Coffs Harbour | [Video player](https://widget.coastalcoms.com/video/c84385c2-10bb-499b-9c23-0542bff3210c) |
| Forster | [Video player](https://widget.coastalcoms.com/video/2bb39d41-38bd-4808-9c52-d4fee1525d0b) |
| Port Macquarie | [Video player](https://widget.coastalcoms.com/video/7c3cc779-daa6-48e6-9eed-c102efd59038) |
| Shoal Bay | [Video player](https://widget.coastalcoms.com/video/364ee26f-ad27-4713-93dd-fcf0f849541e) |
| Swansea | [Video player](https://widget.coastalcoms.com/video/5bb0d918-2423-4b5c-9840-c6599108523e) |
| Merimbula | [Video player](https://widget.coastalcoms.com/video/3d3a9ea9-8000-4d4e-9e87-5de98f2a15e0) |

[NSW copyright](https://www.nsw.gov.au/nsw-government/about-website/copyright) excludes third-party material unless expressly licensed. Its linking policy is not a third-party video redistribution licence. [South Australian operator page](https://dit.sa.gov.au/marinesafety/web-cameras) lists live condition views; the site licence does not alone establish third-party footage rights.

Explicit exclusions:
- YouTube routes, CAPTCHA, token/credential extraction, access-control bypass, private CCTV, and raw restreaming are out of scope.
- [SkylineWebcams](https://www.skylinewebcams.com/) free thumbnail/still embeds do not establish live-video reuse; no unapproved bulk embedding.
- [Africam viewing FAQ](https://africam.com/faq/how-do-i-watch-the-live-cameras/) describes signup or visiting individual lodge pages. Do not create accounts or bypass gates.
- [NetMadeira](https://www.netmadeira.com/webcams-madeira) thumbnail embeds do not count as live video; [San Diego Zoo](https://zoo.sandiegozoo.org/live-cameras) explicitly marks Red Panda as prerecorded.
- Agnes Water GPC result exposed only a weather widget during this review, not a confirmed video route, so it is not in the 64 count.

## Admission procedure

1. Confirm exact owner-published source and supported public player document; document terms for desktop display, branding, third-party resources and rights. Public viewing does not imply redistribution rights.
2. On the normal provider player, observe advancing live media and changing decoded frames; reject stills, loops, prerecorded footage, blocked/unsupported streams. Record UTC timestamp, provider identity, test duration, playback state, and availability separately. Never suppress provider errors.
3. Keep manual consent, isolated profile, finite exact host/frame allowlists, original link, and single active player. No raw-stream extraction, automatic connections, recording, aggregation or tracking.
4. Add individual candidates only after source review; check exact player and permitted resource routes; test in Windows Pulse, including resize, switch/stop/hide/exit and unavailable-provider states. Keep unverified candidates out of the active count.
5. Expand the three-entry finite registries coherently in Python, native host, and layout checks without broadening the trust model. Add catalog consistency and malformed-input tests; verify new routes cannot bypass consent or admit arbitrary URLs.
6. Target balanced six-continent coverage (60 total live entries, ideally approximately 10–12 per major region where feasible). Replace rejected leads rather than padding counts. A tested stream may go offline later.

## Prelaunch engineering work in this branch

- Preserve an identical, canonical manually selected live entry when the event-associated list is rebuilt. No restart or cancellation from unrelated news refreshes, but selection removal and explicit stop/hide/shutdown continue to invalidate consent.
- Add All cameras / Live video / Snapshots filter, composable with region and search. Filter does not autoconnect. Retain the current 3 live / 14 snapshot active catalog until actual admission.
- Add focused offline integration regressions and a two-platform workflow. CI is engineering evidence, not native playback or independent acceptance.

## Remaining launch gates — no bypass

| Gate | Required evidence |
|---|---|
| Current package | Exact-candidate full Windows regression, 8 installer lifecycle checks, package manifest/hashes, separate setup/portable ZIP, independent QA. |
| Stability | Ordinary standard-user Windows startup, camera load/error/retry, rapid tab/filter use, long idle/collector activity, no background playback after Stop/Exit, UI performance and shutdown timeouts. Preserve prior failures; do not waive or loosen existing limits. |
| Live camera/audio | Individually verified actual moving pictures and clean controls; provider outage handling; one active media session, consent, no surprise connections. Exercise radio/HAM separately. |
| Other product behavior | Physical notification/tray and cold activation, ordinary-user install, mixed DPI/monitor and display resizing; news freshness and source-health failure states. |
| Rights and release | Exact active source/footage rights and dependency notices, package provenance; review unresolved [PR 17](https://github.com/dietrichailabs-oss/Global-News-Pulse/pull/17) and [Issue 2](https://github.com/dietrichailabs-oss/Global-News-Pulse/issues/2). Independent release disposition and explicit owner release authorization; no automatic merge, public binary, signing or trust changes. |

Historical predecessor passed 2,327 tests and 10 subtests and eight installer checks. That evidence remains bound to the predecessor. Owner said the cleaner player was much better. No new native run or all-camera playback result is claimed by this research document.
