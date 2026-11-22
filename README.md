# Global News Pulse

Global News Pulse is Dietrich AI Labs' desktop world-news workstation.

This is the clean **public engineering repository** initialized from the corrected owner-retest source line. It is not yet a final public binary release.

## Current owner-retest line

The current source includes:

- corrected conflict / unrest / migration country stripes across split-source reporting;
- conservative publisher-country provenance handling;
- opt-in local GDELT batch ingestion and coded-country layer;
- NWS affected-area geometry and zone resolution;
- Situation Star / Brief persistence and filtered-selection fixes;
- a radio-first media panel with separate reviewed-camera access;
- documented direct Internet radio stations;
- an explicit in-app public SDR receiver path using an isolated memory-only browser session;
- a selectable worldwide bank of 14 reviewed public landscape snapshots and
  three separately consented live-camera choices;
- Windows installer and portable packaging.

YouTube playback has been removed at the owner's request. There is no YouTube/TV
tab, saved-video control, or bundled native TV helper. AM/FM/Internet radio,
HAM/SDR, reviewed cameras, and news source links remain. Existing saved-video
preferences and historical reports are left untouched but do not launch a player.

The current media expansion retires KiwiSDR and keeps WebSDR as the HAM receiver
type. Receiver links are checked with individual operators; the restricted
WebSDR.org directory dataset is not imported or mirrored. The 37 curated WebSDR
entries remain intact. The 14 existing camera snapshots retain their periodic
still-image behavior and 15-minute minimum refresh. **Auto cameras (still images)**
applies only to those snapshots.

The three manual live-video choices are Gladstone Ports Corporation's Tannum
Sands and 1770 cameras, and Brighton & Seacliff Yacht Club's Seacliff camera.
They use the original public provider pages through a separate, camera-only
Windows WebView2 helper. Connecting requires consent; selecting a camera,
matching a news event, or enabling automatic snapshots cannot start live video.
Press Play in the provider's player if it asks. Stop, changing camera or tab,
hiding the panel, and exiting disconnect the session; showing it again does not
resume live video. The installed Microsoft Edge WebView2 Runtime is required.
The helper uses a private browser session and attempts temporary-profile cleanup;
this does not promise that crashes or locked files leave no disk traces.
Provider attribution, Source links and availability limitations remain visible.

## CI

`Current Contract CI` runs the active cross-platform regression set on Linux and Windows.

`Windows Owner-Test Package` builds the unsigned Windows installer and portable package, performs offline package smoke testing, zips the verified installer for easier downloading, and uploads short-lived workflow artifacts. It does **not** publish a GitHub Release.

The dedicated three-camera Windows workflow exercises the camera helper and
packages this successor. Its diagnostics distinguish child-window embedding and
page loading from actual moving video. Provider playback still requires a
separate observation on the exact Windows package.

## Status

Engineering and independent QA are still active. Physical Windows playback, live-source behavior, notifications, remaining source-admission work, and final release approval remain separate gates.

The current three-camera source was reconstructed from retained task records on
base `74c8de9ef59df577b0d9ee7e902b2d98baa6903e` after the prior working checkout
was lost. The unavailable `a4e4c960bf8954a19db62a486c65822b7ef1019d` candidate and
its reported 2,320-test result do not validate these reconstructed files. Fresh
source/package receipts identify this successor. Public-page observations dated
November 22 are attributed to the earlier session; they were not repeated during
reconstruction and do not verify playback inside Windows Pulse.

See `docs/PUBLIC_MIGRATION.md` for the migration boundary.
