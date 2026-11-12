# Global Pulse user guide

This guide describes the implemented workstation. Engineering E1 remains subject
to the Windows build and acceptance checks documented in the engineering report.

## Start monitoring

Open Global Pulse and select the interests offered at first launch. Public sources
are preconfigured. Core news and crisis monitoring do not require an API key,
developer account or paid service. Choose **Resume** if the top bar shows Paused.

**Refresh** asks the scheduler to check eligible sources; it still respects
provider intervals and backoff. A source may legitimately publish no new items.
Source failures do not disable other collectors. The **Sources** page shows
availability, last success/failure, next eligibility and provider access limits.

## Monitor workspace

The upper map is available offline. Drag to pan, scroll or use the plus/minus
controls to zoom, and use the country search or a country selection to explore a
region. **World** resets the view. **Layers** controls category visibility;
**Density** adds a visual concentration overlay. Clusters show their count and
expand as you zoom.

The marker's color describes importance: critical red, high orange, moderate
yellow, informational blue, or unassessed gray. Its separate outline/symbol
describes evidence classification. An official measurement is different from an
official statement about an unverified underlying incident. Details explain that
distinction. Approximate or regional locations are labeled; missing coordinates
remain missing and do not become invented pinpoints.

The lower feed contains locally retained event records. Select a card to read the
recap, reporting origins, sources, contradictory claims and timeline in the right
panel. Use **Original source** to inspect the publisher's evidence. Attribution,
author credits and source terms remain attached to the report. Undated source
items explicitly lack a known publication time.

Use the global search and region/category/time controls to filter the local
archive. The history slider reconstructs prior event/report revisions. **Latest**
returns to the current view. A notification activation also returns to the current
event instead of leaving the application on an unrelated historical snapshot.

Panels are resizable. Your layout and map view are saved locally. At smaller
window sizes, panels scroll. `Ctrl+F` focuses search and `Ctrl+,` opens Settings.

## Situation Rooms

Select an event and choose **Save**. In **Situations**, reopen it to see its current
evidence, retained timeline and **What Changed Since My Last Visit?** content.
Opening a room advances its last-visit checkpoint. Saving a room does not exempt
its source text from source-specific retention limits.

## Economic observations

The **Economy** workspace presents stored World Bank indicator series and country
comparisons. An observation year, provider dataset update, release date and
retrieval timestamp describe different things. Missing release dates are not
filled with retrieval times. Revisions retain previous reported values. A change
in a single economic indicator is not labeled proof of an economic crisis.

## Translation

Select a source record and choose **Translate**. English content remains unchanged.
For German, French or Spanish, Global Pulse offers its reviewed local model if it
is not installed. It shows the download size and asks first:

| Language → English | Optional model download |
|---|---:|
| German | 150.5 MB |
| French | 66.6 MB |
| Spanish | 285.2 MB |

After installation, translation runs on your computer with CTranslate2; article
text is not sent to a translation service. The original text remains available,
and output is labeled machine translation. Unsupported languages, missing models
and failures produce a clear message. The application does not invent full
article text, captions or audio transcripts.

## Media, webcams and radio

The contextual media panel shows related links and a small reviewed public-source
directory. A supported YouTube video can use the official player after you accept
the connection disclosure. Playback starts only with a user gesture and begins
muted. **Float** creates a movable/resizable player window; **Stop** ends media
playback without pausing source monitoring.

The embedded player uses a temporary, isolated browser profile and denies camera,
microphone, geolocation, downloads and new windows. It will not run with Chromium
sandboxing disabled. Provider/region availability and rights are shown.

Tousi TV is a verified channel link with a manual live-page fallback. This build
does not claim to automatically detect its broadcasts. Webcam/radio entries are
public directories or original-source links; individual endpoints still depend
on provider permission and availability. The application does not record or
retransmit audio or access private cameras/accounts.

## Alerts and background behavior

The **Alerts** page retains qualifying event updates. Native Windows notifications
are handled by the Windows App SDK component in the complete Windows build.
Clicking a native notification is intended to restore the existing window, select
the matching event and focus its map marker where coordinates exist; this behavior
must be verified during Windows acceptance for the frozen artifact.

Closing X normally hides the dashboard in the system tray and preserves
monitoring. The first close explains this. Double-click the radar icon to reopen.
The tray provides Open, Pause, Resume, Mute, Alerts, Settings and **Exit Completely**.
When a system tray is unavailable, closing exits instead of hiding an inaccessible
application. **Exit Completely** ends collection and the native helper.

## Export and backup

The **Briefs** workspace produces daily or weekly Markdown briefs with source links
and qualified evidence descriptions. Export the full archive as JSON or CSV.
Exports include source URLs and attribution; CSV cells that could be interpreted
as spreadsheet formulas are neutralized.

Exports are saved where you choose. Uninstall does not intentionally remove those
files. To back up the local archive, use Exit Completely first and copy the Global
Pulse data directory. On Windows it is under
`%LOCALAPPDATA%\DietrichAILabs\GlobalPulse`. Do not replace a live database while
the application is running.



## Removing local configuration and models

User-added RSS/Atom feeds can be removed from **Sources** with **Remove selected custom feed**.
Removing a feed stops future collection and removes its saved feed/checkpoint configuration; it does
not rewrite or silently erase already collected history, which remains subject to the configured
retention period, and it never deletes separately exported files.

Downloaded offline translation models can be removed from **Settings → Manage translation models**
with **Remove local model**. The action is limited to the selected reviewed model directory and is
unavailable while that model has active download work. Removing a model does not remove event
history or exports.

Global Pulse's Windows data directory is
`%LOCALAPPDATA%\DietrichAILabs\GlobalPulse`. Uninstall removes installed program files but
intentionally preserves the local archive, diagnostics, optional models and user-chosen exports.
After **Exit Completely**, a user who wants to discard the entire remaining local application data
can delete that directory manually. Diagnostics rotate locally at 256,000 bytes with two backups.


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

