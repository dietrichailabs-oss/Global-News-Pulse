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
- one large TV surface with clearly labeled owner-test video candidates;
- documented direct Internet radio stations;
- an explicit in-app public SDR receiver path using an isolated memory-only browser session;
- reviewed manual webcam access;
- Windows installer and portable packaging.

## CI

`Current Contract CI` runs the active cross-platform regression set on Linux and Windows.

`Windows Owner-Test Package` builds the unsigned Windows installer and portable package, performs offline package smoke testing, zips the verified installer for easier downloading, and uploads short-lived workflow artifacts. It does **not** publish a GitHub Release.

## Status

Engineering and independent QA are still active. Physical Windows playback, live-source behavior, notifications, remaining source-admission work, and final release approval remain separate gates.

See `docs/PUBLIC_MIGRATION.md` for the migration boundary.
