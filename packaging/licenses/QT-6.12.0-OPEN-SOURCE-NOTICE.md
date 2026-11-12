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

---

## Earlier candidate notice (historical)

# Qt / PySide open-source compliance notice — Global Pulse

Global Pulse distributes Qt/PySide libraries as separate dynamically loaded files and is using the applicable open-source LGPL route for reviewed modules where that route is offered. This is not evidence of a commercial Qt entitlement and does not select the Global Pulse application's own license.

## Source-pinned core Qt / PySide line

- Qt 6.12.0 core source: `qt-everywhere-src-6.12.0.zip`, 604,643,023 bytes, SHA-256 `a72e89c33726d742e67edf494abf7b625eaffc756673221c9823322ecd1a32d1`.
- PySide6 6.12.0 binding source: `pyside-setup-everywhere-src-6.12.0.zip`, 23,393,479 bytes, SHA-256 `15b25c9e06f3acb8930c318192f3c20aee162f4b8d01bf4b4c60193c924cd847`.

The package includes GNU LGPLv3 and GPLv3 texts and an exact generated hash inventory of the Qt runtime files actually shipped.

## Qt WebEngine / Qt PDF 6.140

Qt 6.12 intentionally separated Qt WebEngine and Qt PDF into the **6.140** release line. The shipped PySide packages are `PySide6-WebEngine 6.12.0.140` and `PySide6-Pdf 6.12.0.140`, not ordinary Qt WebEngine/PDF 6.12.0 binaries.

The exact Windows x64 WebEngine wheel reviewed by the dependency lock has SHA-256 `f9b61b1d457a591ee590a6b80515f25a3e61e2576a2a0a70566380f9d9de4ab0` and was published by Qt Project on 2026-10-08. Qt documents the 6.140 line as Chromium 140 based; this bundle records Chromium baseline `140.0.7339.264`.

The package carries:
- the Chromium BSD license text;
- the PDFium BSD/Apache license text;
- the official versioned Qt WebEngine 6.140 third-party-license inventory reference;
- the official Qt PDF 6.140 third-party inventory;
- `QT-WEBENGINE-PDF-6.140-SOURCE-STATUS.json` describing the current corresponding-source limitation.

**Corresponding-source status remains HOLD.** As of the recorded 2026-11-10 review, Engineering did not independently locate a final public `v6.140.0` source tag/archive corresponding to the shipped 2026-10-08 wheel. The public `6.140` Git branch is mutable and its observed head is newer than the wheel, so it is not relabeled as the wheel's source. The Qt 6.12.0 core source archive above must not be represented as satisfying the separate WebEngine/PDF 6.140 source obligation.

## Library replacement

Global Pulse uses a writable one-directory Windows package. Qt/PySide DLLs remain under `_internal/PySide6`; Global Pulse does not enforce an application signature/hash that prevents the installing user from replacing an interface-compatible Qt library after **Exit Completely**. Matching plugins/resources may also be required by a modified Qt build.

This notice does not waive third-party terms, provider/content rights, the Microsoft Windows SDK external-license-reference HOLD, the unresolved WebEngine/PDF corresponding-source HOLD, or independent QA/release review.
