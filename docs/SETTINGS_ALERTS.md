# Settings and alert behavior

## Monitoring and sources

The default interval is 600 seconds. Supported preferences are 300, 600, 1800 and
3600 seconds. Each provider's minimum interval, cache metadata and Retry-After
instructions take precedence. **Refresh** cannot override them. Sources schedule
independently with at most four bounded collection workers. Checkpoints survive
restart; sleep and network loss do not create invented missed observations.

Pause invalidates in-flight collection generations before delivery into the
archive/alert pipeline. Resume checks eligible sources without replaying imaginary
intermediate polls. Exit stops monitoring and the helper; there is no installed
always-on service.

The source catalog distinguishes reviewed public adapters, user-configured feeds,
manual-only entries and sources requiring access/licensing review. A disabled
review-required provider cannot be activated by its checkbox. User RSS/Atom feeds
need a public HTTPS URL and the user's acknowledgement of access rights.

## Alert policy

| Evidence or change | Implemented behavior |
|---|---|
| Significant current official announcement/measurement | Eligible for an alert with exact official attribution |
| Developing event supported by documented independent reporting origins | Eligible for an alert |
| One unverified social item | Feed only |
| Syndicated copies/reposts | Do not increase independent-origin count or create repeat alerts |
| Significant correction/retraction | Eligible for a separately identified alert; preserves history |
| Undated, old or future-dated initial imports | No fresh-event alert based only on retrieval time |

Freshness uses known publication/provider update times, with a 24-hour window for
ordinary newly collected records. A fresh correction to an older event can still
qualify. Material evidence, origin, claim and status changes control duplicate
suppression; polling again is not a material change. Countries, topics, minimum
importance and source mutes further scope alert eligibility.

Muted sources are removed from the evidence view used to decide a notification.
An unmuted repost cannot borrow confirmation or severity from a muted official
source. No confidence percentage is fabricated.

## Quiet hours and native delivery

Quiet hours use the computer's local time. An overnight range such as 22:00–07:00
crosses midnight. Equal start/end times mean quiet all day when quiet hours are
enabled. Quiet hours and Mute suppress native submissions while preserving
qualifying internal alert history and an explicit suppression status.

Windows controls visual notification delivery and Notification Center retention.
Global Pulse records a native submission separately from visible delivery. A
helper receipt does not prove that a toast appeared. Windows permissions, policy
and Do Not Disturb remain authoritative.

Native registration can briefly queue up to 32 requests for at most 15 seconds.
Overflow, registration timeout, failed writes, missing acknowledgements and exit
are recorded honestly. An uncertain submission is never blindly retried. Each
receipt is correlated with its exact internal alert identifier, including when
several alerts refer to the same event.

## Retention

The default history target is 365 days, configurable between 1 and 3650 days.
Stricter source-specific limits take precedence. Retention is checked at startup,
when the preference changes and once daily during operation. Expired source text
is also removed from derived recaps, historical snapshots, search, alerts and
translation caches. Exported files are controlled by the user and are not silently
removed with the internal archive.

## Diagnostics and privacy

Diagnostics are local and bounded. They redact credential-like values; collection
does not require secrets by default. No telemetry, advertising, hidden account
collection or external intelligence upload is implemented. Opening a publisher
link, consenting to a media player or downloading a language model makes the
described direct provider connection.



## Local cleanup controls

The source registry distinguishes built-in reviewed sources from user-configured feeds. Only a
`user_supplied` custom feed can be removed through **Remove selected custom feed**. Removal
invalidates the scheduler generation, deletes that feed's persisted configuration/checkpoint, and
stops future delivery from any already in-flight stale collection. Existing historical reports are
not silently rewritten; normal source/history retention applies.

Installed reviewed translation models can be deleted with **Remove local model**. The application
refuses removal while that language has active download work and constrains deletion to the exact
reviewed child directory under the local `models` root. Event history and exports are unaffected.

On Windows, the application data root is
`%LOCALAPPDATA%\DietrichAILabs\GlobalPulse`. `diagnostics.log` rotates at 256,000 bytes with
two backups. The installer deliberately leaves this application data root, optional models and
user-created exports in place during uninstall. Use **Exit Completely** before manually deleting the
application data root if complete local-data removal is desired.


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

