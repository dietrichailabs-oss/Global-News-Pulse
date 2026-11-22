# Global Pulse 0.1.1 / E2 — private engineering test build

**Dietrich AI Labs. This is a private test candidate, not an approved Version 1 release.**

## Start

Extract the complete portable ZIP to a new folder, then open `GlobalPulse.exe`.
Do not run the executable from inside the ZIP, and do not move it away from its
`_internal`, `notifications` and `camera` directories. Alternatively, run the per-user setup
program. It does not request a system service, automatic startup, or administrator
privileges. The build is not code-signed; confirm its exact SHA-256 against the
GitHub handoff before testing. Do not disable Windows security to make it run.

On the first normal launch, choose interests and whether to start public-source
monitoring. No API key or paid account is required for enabled default sources.
Opening a media player is a separate consented connection to its provider; the
Radio and Cameras tabs do not load remote media merely because they are visible.
Radio is the default tab. YouTube playback, the TV tab and native TV helper have
been removed from this R20 candidate.

For complete physical removal of an older installed TV helper, close Pulse,
uninstall the old version, then run this installer. An overlay install can leave
unused old program files. The normal uninstaller preserves the separate user
settings/archive directory. A fresh portable extraction also contains no TV helper.

Closing the dashboard normally hides it in the system tray. Double-click the
purple radar icon to reopen it. **Exit Completely** in the tray menu stops the
application. Pause Monitoring and Mute Notifications are separate controls.

## Test safely

Use a new test folder and a separate archive for this engineering build. From a
terminal, the following opens the normal application with monitoring paused:

```powershell
.\GlobalPulse.exe --data-dir "$env:LOCALAPPDATA\GlobalPulse-E2-PrivateTest" --no-start
```

The existing default archive, when used, is under the current user's local
application-data directory. E2 adds warning identity/redirect tables and records
**schema version 2**. Preserve a closed-app copy of any earlier archive before an
upgrade. Do not point E1 at a database upgraded by E2; the older program rejects
the newer schema. A rollback uses the prior application **and its separate backup
archive**, never an in-place schema downgrade.

For an empty offline UI check, append `--snapshot PATH_TO_NEW_PNG`; snapshot mode
never starts collection or native notification registration. Fictional fixtures
are not shipped in this runtime. Normal startup contains no synthetic headlines.

## First checks

Verify the upper map, persistent left-side category/time controls, lower news feed,
Radio/Cameras media panel, and narrow stacked intelligence sidebar. Panels
can be resized. Reset Layout restores the E2 defaults; an upgraded user profile
may retain its previously saved panel arrangement.

Then test live collection, pause/resume, source links, saved Situation Rooms and
search with the desired configured public sources. Check tray reopen and full
exit. Keep clear which notifications Windows actually displayed versus those
saved only in Global Pulse's alert history. Do Not Disturb and OS permissions may
suppress toasts; no submission receipt proves a visible notification.

## Three manual live cameras

This reconstruction adds **GPC Tannum Sands**, **GPC 1770** and **BSYC Seacliff**
to the Cameras selector, separately from the unchanged 14 snapshots. Use an
ordinary Windows user session with the Microsoft Edge WebView2 Runtime installed.
The camera helper includes its .NET runtime, but does not install WebView2. Keep
the whole package together so the `camera` helper can be found.

For each of the three live choices:

1. Open Cameras and select the source. Confirm that selection alone makes no
   connection, including when **Auto cameras (still images)** is enabled.
2. Choose **Connect**, read the provider/privacy notice, and consent. Confirm
   that the correct original provider page appears inside the camera panel;
   press Play in that page if required.
3. Observe visible moving video or an advancing player time for a stated interval.
   Record the exact source/package identity and result. A page-loaded status,
   screenshot, or native child-window handle alone is not a playback pass.
4. Press Connect again while the session is active. It should keep one player.
   If playback initialization fails, a fresh manual Connect should retry once
   rather than treating the failed session as still connected.
5. Exercise Stop, a different camera, the Radio tab, hide/reopen and full exit.
   Each boundary must disconnect the prior camera; returning does not resume it.
   Old status messages must not relabel a replacement session as playing.
6. Exercise a pending consent response with Stop/hide/shutdown/selection changes.
   A late Yes must not start the canceled camera. Repeat the cancellation checks
   with a snapshot so the shared connection path is covered.

Confirm that all 14 snapshots still use still images and their existing refresh
floor, that live choices never enter automatic event association, that YouTube
and KiwiSDR remain absent, and that the 37 WebSDR entries remain available. Source
links are explicit external actions. Record unavailable sources honestly; do not
substitute an unrelated stream, broaden the host list, or label page loading as
video playback. The private live browser may create temporary files and attempts
cleanup on close; a crash can leave files requiring later cleanup.

## Known acceptance limits

The repository handoff identifies the exact source commit, build run, tests,
artifact filenames, sizes and hashes. Consult those receipts rather than treating
this guide as proof that a test ran. CI can exercise frozen launch, offline Qt
rendering, source tests, and installer file lifecycle. It does not establish real
Notification Center presentation/click routing, standard-user behavior, Windows
Snap, mixed-monitor DPI, permitted media playback, independent QA or release
approval. Those checks remain explicit until observed against this exact package.

The three-camera source was reconstructed from base `74c8de9` and retained task
records after the earlier checkout disappeared. The old `a4e4c96` candidate's
2,320-test report does not validate these bytes. Earlier November 22 public-page
observations are attributed history, not repeated verification or a Windows
playback pass. Use the new run receipts and package hashes for this candidate.

Core corrections cover durable notice significance, deferred evidence/history,
and NWS/CAP update/cancellation/expiry. Independent Pulse QA must retest them;
Engineering does not close its own findings. Foreign-language support and external
provider limits are detailed in `KNOWN_LIMITATIONS.md` and
`SOURCE_ACCESS_MATRIX.md`. Source/compliance and packaged dependency reviews
remain pending. This package is not cleared for public distribution.

The complete user guide is `USER_GUIDE.md`, notification preferences are in
`SETTINGS_ALERTS.md`, and component notices are in `THIRD_PARTY_NOTICES.md` and
`licenses/`. Uninstall removes installed program files, not user archives, optional
models or separately exported files.
