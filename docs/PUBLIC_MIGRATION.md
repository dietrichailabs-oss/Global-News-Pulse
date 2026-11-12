# Public migration note

This public repository was seeded from the corrected Global Pulse owner-retest source line on 2026-11-12.

The migration intentionally excludes:
- private PR/issue discussion history and QA handoff records;
- historical one-off GitHub Actions workflows from the private engineering repository;
- the generated 8 MB `packaging/licenses/qt-webengine-pdf/SOURCE-NOTICES.txt` evidence file, which is not referenced by the source or build scripts.

The underlying Qt WebEngine/PDF SBOMs, source maps, replacement notes, third-party license material, application source, packaging definitions, scripts, and regression tests are retained.

No public binary release is created by the workflows in this repository. Windows package jobs produce short-lived workflow artifacts for owner testing only.
