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
- a selectable worldwide bank of reviewed public landscape cameras;
- Windows installer and portable packaging.

YouTube playback has been removed at the owner's request. There is no YouTube/TV
tab, saved-video control, or bundled native TV helper. AM/FM/Internet radio,
HAM/SDR, reviewed cameras, and news source links remain. Existing saved-video
preferences and historical reports are left untouched but do not launch a player.

The current media expansion retires KiwiSDR and keeps WebSDR as the HAM receiver
type. Receiver links are checked with individual operators; the restricted
WebSDR.org directory dataset is not imported or mirrored. Camera entries are
periodically refreshed still images, not continuous video. Provider attribution,
connection consent, and availability/freshness limitations remain visible.

## CI

`Current Contract CI` runs the active cross-platform regression set on Linux and Windows.

`Windows Owner-Test Package` builds the unsigned Windows installer and portable package, performs offline package smoke testing, zips the verified installer for easier downloading, and uploads short-lived workflow artifacts. It does **not** publish a GitHub Release.

## Status

Engineering and independent QA are still active. Physical Windows playback, live-source behavior, notifications, remaining source-admission work, and final release approval remain separate gates.

See `docs/PUBLIC_MIGRATION.md` for the migration boundary.
