# Accessing and replacing the LGPL libraries

Global Pulse uses dynamically loaded Qt/PySide libraries. Their original licenses,
source inventories and notices are included; the application's own source license
is not selected by this dependency bundle.

The exact WebEngine/PDF source archive is publicly obtainable at:
https://download.qt.io/development_releases/qtwebengine/6.140.0-rc/qtwebengine-everywhere-src-6.140.0-rc.tar.xz

SHA-256: `61257967afd9803a1db6403e86ea25c4efff8fad479bda365a9d81bfd709f621`

It includes the corresponding Qt WebEngine/PDF and bundled Chromium/PDFium sources.
Vendor SPDX files preserve source provenance and build configuration. The core Qt
and PySide binding source identities remain in QT-6.12.0-OPEN-SOURCE-COMPLIANCE.json.

Before public binary distribution, provide equivalent, no-charge access to these
source archives alongside the downloads and keep that access available. A private
GitHub link is not a public source offer; no source mirror is claimed published by
this preparation. The pinned public upstream URLs are included for exact retrieval.

To replace libraries: Exit Completely; back up the per-user installed directory;
build an ABI-compatible modified Qt/PySide version using the corresponding source
and the recorded platform/build configuration; replace the separate libraries and
matching plugins/resources in _internal/PySide6; then restart. Global Pulse imposes
no runtime signature/hash check preventing compatible modified Qt libraries. Build
pipeline hash checks protect release provenance, not an end user's modification.
Reverse engineering for debugging such modifications is not prohibited by Global
Pulse's component notice. Do not modify the separately licensed Microsoft files
under this LGPL permission. New library builds still require ABI compatibility.
