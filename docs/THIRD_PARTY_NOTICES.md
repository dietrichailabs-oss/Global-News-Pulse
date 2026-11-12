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

# Historical preceding candidate record

# Global Pulse — third-party notices and distribution review record

Dependency/license inventory originally reviewed for **0.1.0 / E1 on 8 November 2026 UTC**. The active release-integration work is now **draft PR #12**, rooted directly in independently accepted E4 source `cc9b6234f7afe9499c0aac3559283b7851dad7d4`; exact moving integration identity is carried by Git and the Windows build receipts rather than by this prose. Gate B saved geometry, Gate D cleanup/privacy-egress, and the narrow Gate E Python/.NET notice corrections have independent QA acceptance in their stated scopes. Historical `0788d0f9`, `efa30535`, `4bf6ac2`, `cd1a21` and other package/notice evidence retains distinct identity and is not the current candidate. Overall **HOLD** remains for the explicitly unresolved component-rights and ordinary-client observations. No successful Engineering test or generated SBOM substitutes for rights review.

This document identifies known third-party components, the evidence for their licenses, and outstanding distribution work. The older efa30535 distribution-count/notice findings below are historical; the 0788 shipped package requires its own exact-rights mapping and has no comprehensive rights clearance. It is an engineering notice index, **not a complete license bundle, legal clearance, or release approval**. Actual private Windows E2 installer and portable packages now exist and their file hashes have been independently rechecked by Engineering, but the exact shipped Qt/Chromium/.NET/Python license texts, third-party notices, and corresponding-source/replacement obligations have **not** been fully reconciled. Hashes, a package manifest and generated SBOM establish byte identity, not distribution rights.

## Application ownership and license

The owner has not selected a license for the Global Pulse application source, branding, or application-owned assets. This document makes no license grant for them. In particular, no MIT license has been assigned to the application merely because some dependencies use MIT. The owner must select the application distribution terms and any required end-user terms before public distribution.

Third-party copyrights, licenses, disclaimers, trademarks, and attribution requirements remain with their respective owners. No dependency or data provider endorses Global Pulse by being listed here.

## Python dependency inventory

The exact version and artifact-hash input is [DEPENDENCY_INVENTORY.json](DEPENDENCY_INVENTORY.json). It contains **42 Python distributions across runtime, build, and test dependencies**. The runtime lock contains 30 distributions; 12 additional distributions appear in the build/bootstrap inputs. The source of truth for selection is [requirements.lock](../requirements.lock), [requirements-build.lock](../requirements-build.lock), and [requirements-bootstrap.lock](../requirements-bootstrap.lock). A Windows platform marker means the dependency was resolved for Windows; it does not mean it was installed or exercised on the Linux engineering host.

In the following table, **R** means present in the runtime lock, and **B** means present only in build/bootstrap inputs. These labels describe dependency selection, not proof that every distribution is included in the eventual frozen application. PyInstaller may include runtime hooks or bootstrap material from a build dependency. Conversely, a metapackage may contain no application runtime code. Compare the final package file manifest before deciding which notices to ship.

License expressions below are the recorded package metadata unless a specific local license-text finding is identified. The version links point to publisher-supplied package metadata. Upstream source references identify the projects; mutable default branches do not establish the exact corresponding source of a particular wheel. Preserve the license and notice files from the exact artifacts selected by the lock.

| Distribution / exact package metadata | Scope | Recorded license / specific finding | Authoritative project source |
| --- | --- | --- | --- |
| [anyio 4.16.0](https://pypi.org/project/anyio/4.16.0/) | R | MIT | [Upstream source](https://github.com/agronholm/anyio) |
| [certifi 2026.10.23](https://pypi.org/project/certifi/2026.10.23/) | R | MPL-2.0 | [Upstream source](https://github.com/certifi/python-certifi) |
| [click 8.5.1](https://pypi.org/project/click/8.5.1/) | R | BSD-3-Clause | [Upstream source](https://github.com/pallets/click) |
| [cloudpickle 3.1.2](https://pypi.org/project/cloudpickle/3.1.2/) | R | BSD-3-Clause | [Upstream source](https://github.com/cloudpipe/cloudpickle) |
| [colorama 0.4.6](https://pypi.org/project/colorama/0.4.6/) | R · Windows | NOASSERTION in metadata; upstream BSD-3-Clause; exact Windows text to verify | [Upstream source](https://github.com/tartley/colorama) |
| [ctranslate2 4.8.5](https://pypi.org/project/ctranslate2/4.8.5/) | R | MIT | [Upstream source](https://github.com/OpenNMT/CTranslate2) |
| [defusedxml 0.7.1](https://pypi.org/project/defusedxml/0.7.1/) | R | PSFL | [Upstream source](https://github.com/tiran/defusedxml) |
| [h11 0.16.0](https://pypi.org/project/h11/0.16.0/) | R | MIT | [Upstream source](https://github.com/python-hyper/h11) |
| [httpcore 1.0.9](https://pypi.org/project/httpcore/1.0.9/) | R | BSD-3-Clause | [Upstream source](https://github.com/encode/httpcore) |
| [httpx 0.28.1](https://pypi.org/project/httpx/0.28.1/) | R | BSD-3-Clause | [Upstream source](https://github.com/encode/httpx) |
| [idna 3.20](https://pypi.org/project/idna/3.20/) | R | BSD-3-Clause | [Upstream source](https://github.com/kjd/idna) |
| [joblib 1.6.0](https://pypi.org/project/joblib/1.6.0/) | R | BSD-3-Clause | [Upstream source](https://github.com/joblib/joblib) |
| [langdetect 1.0.9](https://pypi.org/project/langdetect/1.0.9/) | R | MIT | [Upstream source](https://github.com/Mimino666/langdetect) |
| [mock 5.2.0](https://pypi.org/project/mock/5.2.0/) | R | NOASSERTION in metadata; installed license text: BSD-2-Clause | [Upstream source](https://github.com/testing-cabal/mock) |
| [numpy 2.5.4](https://pypi.org/project/numpy/2.5.4/) | R | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | [Upstream source](https://github.com/numpy/numpy) |
| [pyside6 6.12.0](https://pypi.org/project/pyside6/6.12.0/) | R | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | [Upstream source](https://code.qt.io/cgit/pyside/pyside-setup.git/) |
| [pyside6-addons 6.12.0](https://pypi.org/project/pyside6-addons/6.12.0/) | R | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | [Upstream source](https://code.qt.io/cgit/pyside/pyside-setup.git/) |
| [pyside6-essentials 6.12.0](https://pypi.org/project/pyside6-essentials/6.12.0/) | R | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | [Upstream source](https://code.qt.io/cgit/pyside/pyside-setup.git/) |
| [pyside6-pdf 6.12.0.140](https://pypi.org/project/pyside6-pdf/6.12.0.140/) | R | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | [Upstream source](https://code.qt.io/cgit/pyside/pyside-setup.git/) |
| [pyside6-webengine 6.12.0.140](https://pypi.org/project/pyside6-webengine/6.12.0.140/) | R | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | [Upstream source](https://code.qt.io/cgit/pyside/pyside-setup.git/) |
| [pyyaml 6.0.3](https://pypi.org/project/pyyaml/6.0.3/) | R | MIT | [Upstream source](https://github.com/yaml/pyyaml) |
| [regex 2026.11.8](https://pypi.org/project/regex/2026.11.8/) | R | Apache-2.0 AND CNRI-Python | [Upstream source](https://github.com/mrabarnett/mrab-regex) |
| [sacremoses 0.2.0](https://pypi.org/project/sacremoses/0.2.0/) | R | NOASSERTION in metadata; installed license text: MIT | [Upstream source](https://github.com/hplt-project/sacremoses) |
| [sentencepiece 0.2.3](https://pypi.org/project/sentencepiece/0.2.3/) | R | Apache-2.0 | [Upstream source](https://github.com/google/sentencepiece) |
| [shiboken6 6.12.0](https://pypi.org/project/shiboken6/6.12.0/) | R | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | [Upstream source](https://code.qt.io/cgit/pyside/pyside-setup.git/) |
| [six 1.17.0](https://pypi.org/project/six/1.17.0/) | R | MIT | [Upstream source](https://github.com/benjaminp/six) |
| [socksio 1.0.0](https://pypi.org/project/socksio/1.0.0/) | R | NOASSERTION in metadata; installed license text: MIT | [Upstream source](https://github.com/sethmlarson/socksio) |
| [subword-nmt 0.3.8](https://pypi.org/project/subword-nmt/0.3.8/) | R | MIT | [Upstream source](https://github.com/rsennrich/subword-nmt) |
| [tqdm 4.70.1](https://pypi.org/project/tqdm/4.70.1/) | R | MPL-2.0 AND MIT | [Upstream source](https://github.com/tqdm/tqdm) |
| [typing-extensions 4.16.0](https://pypi.org/project/typing-extensions/4.16.0/) | R | PSF-2.0 | [Upstream source](https://github.com/python/typing_extensions) |
| [altgraph 0.17.5](https://pypi.org/project/altgraph/0.17.5/) | B | MIT | [Upstream source](https://github.com/ronaldoussoren/altgraph) |
| [iniconfig 2.3.1](https://pypi.org/project/iniconfig/2.3.1/) | B | MIT | [Upstream source](https://github.com/pytest-dev/iniconfig) |
| [packaging 26.3](https://pypi.org/project/packaging/26.3/) | B | Apache-2.0 OR BSD-2-Clause | [Upstream source](https://github.com/pypa/packaging) |
| [pefile 2024.8.26](https://pypi.org/project/pefile/2024.8.26/) | B · Windows | MIT | [Upstream source](https://github.com/erocarrera/pefile) |
| [pluggy 1.7.0](https://pypi.org/project/pluggy/1.7.0/) | B | MIT | [Upstream source](https://github.com/pytest-dev/pluggy) |
| [pygments 2.21.0](https://pypi.org/project/pygments/2.21.0/) | B | BSD-2-Clause | [Upstream source](https://github.com/pygments/pygments) |
| [pyinstaller 6.22.3](https://pypi.org/project/pyinstaller/6.22.3/) | B | GPL-2.0-or-later with bootloader exception; some files Apache-2.0 | [Upstream source](https://github.com/pyinstaller/pyinstaller) |
| [pyinstaller-hooks-contrib 2026.9](https://pypi.org/project/pyinstaller-hooks-contrib/2026.9/) | B | NOASSERTION in metadata; installed text: GPL-2.0-or-later standard hooks / Apache-2.0 runtime hooks | [Upstream source](https://github.com/pyinstaller/pyinstaller-hooks-contrib) |
| [pytest 9.2.0](https://pypi.org/project/pytest/9.2.0/) | B | MIT | [Upstream source](https://github.com/pytest-dev/pytest) |
| [pywin32-ctypes 0.2.3](https://pypi.org/project/pywin32-ctypes/0.2.3/) | B · Windows | BSD-3-Clause | [Upstream source](https://github.com/enthought/pywin32-ctypes) |
| [setuptools 84.2.1](https://pypi.org/project/setuptools/84.2.1/) | B | MIT | [Upstream source](https://github.com/pypa/setuptools) |
| [wheel 0.48.0](https://pypi.org/project/wheel/0.48.0/) | B | MIT | [Upstream source](https://github.com/pypa/wheel) |

### Metadata gaps and incorporated code

The local installed license texts resolve some missing metadata: `sacremoses 0.2.0` and `socksio 1.0.0` contain MIT licenses; `mock 5.2.0` contains a two-condition BSD license; `pyinstaller-hooks-contrib 2026.9` distinguishes GPL-2.0-or-later standard hooks from Apache-2.0 runtime hooks. These findings do not rewrite the original `NOASSERTION` fields in the machine inventory. The [Colorama upstream license](https://github.com/tartley/colorama/blob/master/LICENSE.txt) is BSD-3-Clause; retain and check the exact Windows artifact's notice during packaging.

The installed Linux distribution metadata did **not** expose license files for PySide6, its split Qt distributions, Shiboken6, CTranslate2, SentencePiece, or pytest. Their upstream terms are available, but the absence of wheel-listed text is an open packaging task. A successful dependency installation is not evidence that notices were bundled. CTranslate2 and SentencePiece also have native dependencies; NumPy's combined license expression and embedded license tree must be preserved. Libraries incorporated in wheels, such as numerical kernels, C/C++ runtimes, compression libraries, or vendored Python modules, need their own file-level review when present.

Primary license references for the translation runtime are the [CTranslate2 MIT license](https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE) and [SentencePiece Apache-2.0 license](https://github.com/google/sentencepiece/blob/master/LICENSE). `joblib` and `cloudpickle` are dependency entries; the application does not use them to deserialize source reports or downloaded model pickle files.

## Qt, PySide6, Qt WebEngine, and Chromium

The selected community packages are PySide6 / Shiboken6 **6.12.0** and split PySide6 WebEngine / PDF packages **6.12.0.140**. Qt for Python documents its community distribution as LGPLv3/GPLv3, with a separate commercial distribution. The wheel metadata records `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. No commercial Qt entitlement is asserted for this project. Some Qt modules and incorporated components have different terms; the actual packaged module set must determine the license inventory. Sources: [Qt for Python licensing options](https://doc.qt.io/qtforpython-6/commercial/index.html), [Qt 6.12 licensing](https://doc.qt.io/qt-6.12/licensing.html), and [Qt for Python third-party licenses](https://doc.qt.io/qtforpython-6/licenses.html).

The embedded video player uses Qt WebEngine, which includes Chromium code with additional licenses. The Qt license choice does not replace Chromium component obligations. The official [WebEngine licensing page](https://doc.qt.io/qt-6/qtwebengine-licensing.html) currently redirects to the WebEngine documentation snapshot; use it as licensing guidance, not as proof of the exact Windows binary version. The [Qt 6.12 third-party index](https://doc.qt.io/qt-6/licenses-used-in-qt.html) identifies module-level and incorporated component notices and points to Qt's SPDX SBOM information.

Before distributing this application under the community Qt terms, the release owner must establish the applicable license for every shipped module, preserve the required copyright and full license texts, and satisfy the relevant LGPL requirements for library source availability, user modification/replacement, relinking where applicable, and any required installation information. Application terms must preserve recipients' applicable rights. The current source tree has **not** demonstrated that the frozen Windows layout and installer fulfill those requirements. See the [Qt open-source licensing guidance](https://www.qt.io/faq/qt-open-source-licensing) and the actual license texts; an upstream homepage link is not a completed corresponding-source offer.

Authoritative starting points for corresponding-source work are the [PySide / Shiboken source repository](https://code.qt.io/cgit/pyside/pyside-setup.git/), the [Qt source repositories](https://code.qt.io/cgit/qt/), and the [Qt WebEngine source repository](https://code.qt.io/cgit/qt/qtwebengine.git/). The final record must identify the source revisions, patches, build configuration, and incorporated Chromium revision corresponding to the exact shipped Windows binaries. These mappings and the complete native notice bundle remain open. Do not use the application-generated SBOM to claim a full Chromium dependency audit.

## Native Windows components and build prerequisites

### Windows App SDK

The notification helper references **Microsoft.WindowsAppSDK 2.6.5**. The [Windows App SDK source repository](https://github.com/microsoft/WindowsAppSDK/blob/main/LICENSE) has an MIT license, but the selected NuGet binary package supplies **Microsoft Software License Terms — Microsoft Windows App SDK**. These are distinct licensing scopes. The [2.6.5 Runtime package license](https://www.nuget.org/packages/Microsoft.WindowsAppSDK.Runtime/2.6.5/License) matches the locally inspected main package terms. The locally observed main package `license.txt` SHA-256 is `5b11e6347756e40fe0274bc08c97f89201b94f0d50181a09a00f1f4740840501`.

Those terms permit specified NuGet-placed files to accompany an application, including self-contained deployment, subject to conditions. These include substantive application functionality, protective distribution/end-user terms, notice and trademark requirements, and other obligations. They also contain Microsoft data-collection and update provisions. The source repository's MIT notice does not replace these binary-distribution terms. Release review must address the actual package terms and privacy implications.

The observed `packaging/notifications/obj/project.assets.json` graph has **16 libraries**:

| Resolved package or package family | Version | Observed terms / provenance |
| --- | --- | --- |
| `Microsoft.WindowsAppSDK`; `.AI`; `.Base`; `.DWrite`; `.Foundation`; `.InteractiveExperiences`; `.ML`; `.Runtime`; `.Search`; `.Widgets`; `.WinUI` — 11 packages | 2.6.5 | Each local nuspec identifies `license.txt`; [Windows App SDK binary terms](https://www.nuget.org/packages/Microsoft.WindowsAppSDK.Runtime/2.6.5/License). |
| `Microsoft.Windows.AI.MachineLearning` | 2.4.89 | [Windows ML Runtime terms](https://www.nuget.org/packages/Microsoft.Windows.AI.MachineLearning/2.4.89/License); additional execution-provider terms may apply. |
| `Microsoft.Web.WebView2` | 1.0.3719.77 | Local SDK package `LICENSE.txt` contains Microsoft BSD-3-Clause-style terms. [Exact package](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3719.77). This does not license a separate WebView2 browser runtime. |
| `Microsoft.Windows.SDK.BuildTools` | 10.0.26100.4654 | Nuspec links the [Windows SDK terms](https://aka.ms/WinSDKLicenseURL). |
| `Microsoft.Windows.SDK.BuildTools.MSIX` | 1.7.251221100 | Local `sdk_license.txt`, Windows SDK terms. [Exact package](https://www.nuget.org/packages/Microsoft.Windows.SDK.BuildTools.MSIX/1.7.251221100). |
| `System.Numerics.Tensors` | 9.0.0 | Nuspec declares MIT; package includes `LICENSE.TXT` and `THIRD-PARTY-NOTICES.TXT`. [Exact package](https://www.nuget.org/packages/System.Numerics.Tensors/9.0.0). |

This is a **resolved build graph**, not a list of all binaries that will be shipped or executed. Global Pulse uses the AppNotifications API; it does not implement Windows ML inference or use WebView2 as its media player. Whether transitive AI/ML or WebView2 files enter the final self-contained publish must be established from that publish output. Unused functionality does not waive the terms for files that are redistributed.

### .NET and Python

The engineering SDK is **.NET SDK 10.0.403**. The Windows build script requires an existing stable .NET 10 SDK and records its actual version; it does not enforce this exact patch or install a system SDK. SDK version and runtime version are different identifiers. The [official .NET 10 download record](https://dotnet.microsoft.com/en-us/download/dotnet/10.0) associates SDK 10.0.403 with runtime 10.0.14. The observed native asset resolution includes 10.0.14 host/reference components. The existing compilation's `runtimeconfig.json` names `Microsoft.NETCore.App 10.0.0`; neither observation proves which runtime a later self-contained Windows publish will contain.

The [SDK source](https://github.com/dotnet/sdk/blob/main/LICENSE.TXT) and [runtime source](https://github.com/dotnet/runtime/blob/main/LICENSE.TXT) use MIT, with incorporated-code notices. Microsoft's [Windows binary licensing record](https://github.com/dotnet/core/blob/main/license-information-windows.md) assigns `coreclr.dll` to the [.NET Library License](https://dotnet.microsoft.com/en-us/dotnet_library_license.htm), which includes redistribution and data provisions. The build script requires `coreclr.dll` in the self-contained helper. Preserve the actual published runtime's license texts and [third-party notices](https://github.com/dotnet/runtime/blob/main/src/installer/pkg/THIRD-PARTY-NOTICES.TXT), and review any additional native files separately.

Python **3.12 x64** is a separately installed Windows build prerequisite; its patch version is not pinned by the current script. The frozen application includes a Python runtime. Record the actual patch version and retain its complete [PSF License Version 2, historical licenses, and incorporated-component notices](https://docs.python.org/3.12/license.html). Review the exact bundled SQLite, OpenSSL, compression, Unicode, and Microsoft runtime components if present; they are not fully described by the Python distribution's top-level license name.

### PyInstaller and Inno Setup

PyInstaller **6.22.3** is a build tool. Its GPL terms include a bootloader exception permitting combined application executables under the application's selected terms, subject to dependency licenses. Certain files use Apache-2.0. This exception does not resolve Qt or other dependencies' obligations. Sources: [PyInstaller license documentation](https://www.pyinstaller.org/en/stable/license.html), [COPYING.txt](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt), and [community-hook license distinctions](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/master/LICENSE).

Inno Setup **6.7.4** is the required separately installed installer compiler. Its setup engine becomes part of the generated installer. The [exact 6.7.4 license](https://raw.githubusercontent.com/jrsoftware/issrc/is-6_7_4/license.txt), [release](https://github.com/jrsoftware/issrc/releases/tag/is-6_7_4), and [official commercial-use explanation](https://jrsoftware.org/isorder.php) govern its use. Preserve required notices, website references, and any modification identification. The publisher requests commercial-license purchases; the current official explanation does not make purchase a mandatory prerequisite for permitted commercial use.

## Bundled map data

The world map derives from **Natural Earth 1:110m Admin 0 Countries**. Natural Earth places its raster and vector data in the public domain and permits modification and redistribution, including commercial use. Attribution is voluntary; this project retains the credit. Primary terms: [Natural Earth Terms of Use](https://www.naturalearthdata.com/about/terms-of-use/).

The source archive was [ne_110m_admin_0_countries.zip](https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip), retrieved 8 November 2026 UTC. SHA-256: `0f243aeac8ac6cf26f0417285b0bd33ac47f1b5bdb719fd3e0df37d03ea37110`. The transformation converted Shapefile geometry and selected identifiers, regional fields, and labels into bundled GeoJSON. Provenance is also in [MAP_DATA_LICENSE.txt](../global_pulse/resources/MAP_DATA_LICENSE.txt). Boundaries are cartographic representations, not a legal determination of sovereignty or jurisdiction.

## Optional offline translation models

Model packages are **not bundled with the application**. An explicit user action can download one of three pinned Argos model archives from its recorded HTTPS URL. Article text is not sent to the model host. The selected model identifiers, exact compressed sizes, and SHA-256 values are in [translation_models.json](../global_pulse/resources/translation_models.json):

| Model | Archive URL | Exact bytes | SHA-256 |
| --- | --- | ---: | --- |
| German → English, `de-en-1.3` | [translate-de_en-1_3.argosmodel](https://argos-net.com/v1/translate-de_en-1_3.argosmodel) | 150512831 | `becc2b0011f8249fcb89be9ecb75ba0d876b1fab93c28ee6ff0420936897d637` |
| French → English, `fr-en-1.9` | [translate-fr_en-1_9.argosmodel](https://argos-net.com/v1/translate-fr_en-1_9.argosmodel) | 66585033 | `3b3052fee6bb1e8e8e632a26a723eb2a2c7710dfe73ba61ffd9b83e85d4f14c1` |
| Spanish → English, `es-en-1.9` | [translate-es_en-1_9.argosmodel](https://argos-net.com/v1/translate-es_en-1_9.argosmodel) | 285208831 | `c54df2b62fceaf54a3ce5d97db6bf56efd7940063329f6778f4212d2acb370d4` |

The license basis is the maintainer's explicit response covering **model binaries**, not merely the Argos program: [Argos Translate issue 533](https://github.com/argosopentech/argos-translate/issues/533), dated 2 August 2026, states: “Yes the .argosmodel model binaries are released under the same MIT/CC0 license.” The [Argos project license explanation](https://github.com/argosopentech/argos-translate/blob/master/README.md?plain=1) identifies MIT or CC0. Preserve this provenance and the chosen applicable notice with any later redistribution; this project does not claim an independent audit of every training corpus or archive component.

Only approved CTranslate2 model assets, SentencePiece or BPE tokenizers, and bounded metadata/README material are extracted. Embedded Stanza, Python, pickle, PyTorch, and other unapproved assets are not extracted or loaded. The inference dependencies are CTranslate2, SentencePiece, sacremoses, and subword-nmt; an Argos Python runtime is not required. A future language or model revision needs its own size, integrity, provenance, and license review.

## Source data and external media

Software licenses do not grant redistribution rights for collected reporting, statistics, or external media. [SOURCE_ACCESS_MATRIX.md](SOURCE_ACCESS_MATRIX.md) and [sources.json](../global_pulse/resources/sources.json) record each provider's access, attribution, retention, redistribution limitations, and review status. Public availability does not by itself establish an unrestricted license. The eligible built-in sources use `access_status=reviewed_public`; uncertain or restricted providers remain manual/disabled. User-added feeds carry a separate user-supplied status, headline/link-only defaults, and no general redistribution clearance.

Attributions, original links, authors when supplied, and available source-license metadata accompany stored reports. Follow each source's terms when sharing exports. The catalog's public radio, webcam, social, and video entries are links, not copies or recording permissions. YouTube uses its official player only after consent; X and Facebook entries open original public pages. Global Pulse does not grant rights to download or rebroadcast those streams.

## Required work before binary publication

1. Select the application owner's license and distribution/end-user terms. Review their compatibility with every included component, especially the Microsoft binary and GNU library terms.
2. Build the exact Windows artifacts and retain package locks, actual Python/.NET/compiler identities, source identity, file hashes, and native dependency versions. Resolve every shipped file to its provenance and applicable terms.
3. Assemble the full license, copyright, NOTICE, and third-party text bundle. `scripts/package_manifest.py licenses` copies discoverable installed distribution texts and reports missing entries; it does not fetch or complete Qt, Chromium, NuGet, numerical-runtime, or other missing native notices.
4. Establish and exercise the applicable Qt/LGPL replacement, relinking, source availability, and installation-information path. Preserve exact corresponding sources and patches. Do not treat a link to a current upstream branch as sufficient evidence.
5. Review platform diagnostics and Microsoft terms against the public privacy statement, then perform the exact Windows network and clean-machine checks. Validate installer notices and uninstall behavior on the same artifact offered to users.
6. Engineering assembles all privacy/security, source-access, notices/licensing and exact-artifact evidence; **independent Pulse QA** independently reviews each check along with functional/visual/native Windows acceptance. The owner's November 9 two-role amendment supersedes Sable/Iris/PM/Release Management routing, but does **not** waive any underlying evidence gate. This engineering document grants no QA acceptance or public release approval.

This record must be updated when the dependency lock, model catalog, native publish, source registry, map data, or installer toolchain changes.

## Historical efa30535 package / exact-notice status — November 9, 2026

The [single canonical Windows run 42643934899](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42643934899)
passed its pinned build, 393 Engineering tests and frozen/installer smoke.
Exact source is [`efa30535facf0883870130ae9e1061d0c3b03321`](https://github.com/dietrichailabs-oss/GlobalNewsPulse/commit/efa30535facf0883870130ae9e1061d0c3b03321).
GitHub's private combined installer/portable/manifest/SBOM artifact
[13687157564](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42643934899/artifacts/13687157564)
has **602,382,047 outer bytes**, digest
`88d5f6fe830e644840b2ab66e39a04b6b1eab8d00a91c868c10e2d508e3794ee`;
[diagnostic artifact 13687442205](https://github.com/dietrichailabs-oss/GlobalNewsPulse/actions/runs/42643934899/artifacts/13687442205)
is separate. These are exact **builder/GitHub artifact metadata**, not independently
rehashed new installer/portable bytes.

The actual Windows collector **logged 31 distribution records, 65 discovered
license files**, and precisely **two names with missing copied license texts:
`ctranslate2` and `sentencepiece`**. After the source fix for British-spelled
filenames, `tqdm` is **no longer in the missing-text list**. This is a
source/runner observation, **not independent verification that the top-level
`tqdm/LICENCE` contents in the new packaged bytes match the original source**.
Four records have unresolved metadata expressions: `colorama`,
`global-pulse`, `mock`, and `sacremoses`. Some have available upstream or
internal text; retain their exact evidence rather than treating metadata
`NOASSERTION` as proof of either presence or absence. The SBOM labels NuGet
license assessment incomplete; shipped Qt/Chromium/.NET and corresponding-source
obligations remain unverified.

The independent [GP-QA-E2-EFA305-001 review](https://github.com/dietrichailabs-oss/GlobalNewsPulse/blob/f7b4ebc340ff4326b2faff313c207f5e0a101023/docs/qa/GP-QA-E2-EFA305-001/REPORT.md)
closed the specific GP-CORE-007 source reproductions, but **did not close
GP-PKG-001 or the rights/notices checks**. The only new combined binary archive
exceeds QA's **512 MiB** connector limit; the original new installer,
portable, complete manifest, inventory and shipped notice files were not
independently downloaded through that path. An existing separate Engineering
artifact-integrity operator on
`eng/efa30535-artifact-integrity-20261109` is addressing under-limit
**read-only** transports; do not duplicate it or silently repackage application
binaries. Upon availability, independently verify **exact original hashes**
and the copied `LICENCE` bytes, then reconcile every actual component and
corresponding-source obligation. Mark has **not chosen an application license**
or authorized public distribution. Engineering prepares evidence; Pulse QA
decides independent acceptance.

**Smallest next action:** obtain the existing operator's original-content
under-limit transport receipts, then have Pulse QA independently examine
`licenses/python-distributions.json`, the actual `tqdm` copied and internal
texts, CTranslate2/SentencePiece, PySide6/Qt/Chromium, NuGet/.NET/Windows App
SDK, notices and applicable replacement/source paths against that immutable
package. This documentation-only correction is **not a rebuilt package or
a license decision**, and is not grounds for a duplicate `check git` handoff.

## Historical cd1a21 immutable package review boundary — November 9, 2026

The [exact private E2 Windows handoff](engineering/GP-ENG-E2/WINDOWS_PRIVATE_CANDIDATE_CD1A_SELECTED.md) identifies source `cd1a21bb8a543afb993398df05c9a83dfd4973f6`, canonical Windows run **42589886841 / attempt 2**, installer **240,577,204 bytes** (SHA-256 `265c57bb0f3efff9cf06da8a1a8c604cf0b75b95d3a3bed55e5b964fe1839d54`) and portable ZIP **359,264,278 bytes** (SHA-256 `ae3241a77b2ec491288ad18f32c0a31365f5fa1aea62d9f7895400a038d5dc2d`). A [separate read-only transport/byte audit](https://github.com/dietrichailabs-oss/GlobalNewsPulse/blob/aa29ee997d0ca485580733d9ffdfdebcc4ad3c9c/docs/engineering/GP-ENG-E2-INTEGRITY-RESULTS/REPORT.md) re-downloaded the two original binary payloads and matched 4,001 runtime-manifest file hashes plus the manifest itself. That is **Engineering integrity evidence only**. The original binary/portable payloads and their bundled notices did not change.

The source packaging workflow [`scripts/build_windows.ps1`](../scripts/build_windows.ps1) copies this index as `THIRD_PARTY_NOTICES.md`, calls `scripts/package_manifest.py licenses`, then generates `SBOM.cdx.json` and `MANIFEST.json`. The license collection function copies **discoverable** installed Python distribution texts and writes `licenses/python-distributions.json`; it explicitly reports absent notices. The SBOM labels .NET NuGet licensing as `NOASSERTION` and reports incomplete compositions. There is no evidenced gate in this workflow that upgrades missing Qt/Chromium/.NET notices or corresponding-source mappings to legal clearance. **The source package scan PASS does not establish that those gaps are satisfied.**

For the exact private portable payload, an actionable **Engineering-to-Pulse-QA rights review** is: map `MANIFEST.json` entries for `_internal/`, `notifications/` and `licenses/` to every actually shipped PySide6/Qt WebEngine/Chromium/Python/.NET/Windows App SDK component; read `licenses/python-distributions.json`, record the exact missing texts and actual installed NuGet/Qt/Chromium notices; determine the applicable license route, corresponding-source/replacement provisions, attribution and user notices; check whether local archiving/export or native helper/runtime connections require explicit privacy disclosures. Pulse QA must independently review these concrete results. Anything not inspected is **NOT RUN/HOLD**, never silently PASS. Neither a source-only scan nor a byte-for-byte manifest audit resolves source-redistribution rights.

Public distribution still requires an owner-selected application license and any applicable terms; Engineering may prepare options/evidence but must not choose or accept legal terms for Mark. This coordination-only source-document update **does not rebuild** E2 or silently replace the notices embedded in the immutable `cd1a21` package. A later rebuilt package must carry corrected reviewed notices and its own new hashes and independent QA outcome.


## Current release-integration Qt open-source compliance route — November 10, 2026

The release-integration package no longer treats the installed wheel's `LicenseRef-Qt-Commercial.txt` as evidence of a commercial entitlement. Engineering selected the applicable **Qt/PySide open-source LGPLv3 route** for the reviewed Qt 6.12.0 runtime modules, while leaving the Global Pulse application's own license decision separate.

The package now carries the LGPLv3/GPLv3 texts, exact Qt/PySide source archive identities and hashes, replacement instructions for the separate `_internal/PySide6` runtime DLLs, a generated exact runtime file/hash inventory, and fail-closed checks for known Qt modules that are GPL-only or commercial-only and are not approved for this package. Qt WebEngine/Chromium and Qt PDF/PDFium third-party terms remain independently applicable and are tied to the versioned Qt 6.12 inventory/source record rather than inferred from the commercial-reference wheel file.

Exact source identities:
- Qt 6.12.0 complete source ZIP: 604,643,023 bytes, SHA-256 `a72e89c33726d742e67edf494abf7b625eaffc756673221c9823322ecd1a32d1`.
- PySide6 6.12.0 source ZIP: 23,393,479 bytes, SHA-256 `15b25c9e06f3acb8930c318192f3c20aee162f4b8d01bf4b4c60193c924cd847`.

This is an Engineering compliance implementation and evidence bundle, not independent legal clearance or public-release approval. The Windows SDK external-license-reference item remains explicitly HOLD pending owner acceptance of the applicable redistribution terms.


## Qt WebEngine / Qt PDF 6.140 source-status correction — November 10, 2026

Qt's 2026 release model separates **Qt WebEngine and Qt PDF 6.140** from the Qt 6.12 binary/source line. The locked Windows packages are `PySide6-WebEngine 6.12.0.140` and `PySide6-Pdf 6.12.0.140`. Therefore the previously pinned Qt 6.12.0 core source archive is **not** represented as corresponding source for these separately versioned binaries.

Current exact WebEngine wheel identity:
- `pyside6_webengine-6.12.0.140-cp310-abi3-win_amd64.whl`
- SHA-256 `f9b61b1d457a591ee590a6b80515f25a3e61e2576a2a0a70566380f9d9de4ab0`
- Qt Project / PyPI release date 2026-10-08
- Chromium baseline recorded as 140.0.7339.264.

The package includes the Chromium and PDFium license texts and the official versioned 6.140 licensing/inventory references. However, as of this review, only beta/RC 6.140 source downloads/tags were independently observed; a final immutable `v6.140.0` source tag/archive corresponding to the shipped wheel was not independently pinned. The mutable public `6.140` branch is not substituted for that missing identity.

**Gate E remains HOLD for WebEngine/PDF corresponding source** even if the Windows compliance build passes. The separate Windows SDK external-license-reference item also remains HOLD.
