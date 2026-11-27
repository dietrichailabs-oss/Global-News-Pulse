# Worldwide public camera expansion — 21 November 2026

Owner scope: add more active public webcams worldwide without restoring YouTube or KiwiSDR. This change adds **12 camera views** to the two-entry reviewed bank: **14 entries across four continents and four countries**. Of these, **13 returned decoded JPEG images with recent server modification times during this review**. The existing USGS Kilauea V1 endpoint returned HTTP 403 and remains explicitly marked unavailable; it is not included in the responding count.

These are **periodically refreshed still images, not continuous live video**. Server `Last-Modified` is a freshness signal, not independently authenticated capture time. Provider image captions/timestamps remain authoritative, and a source responding during review is not a guarantee it is responding now. No incident is inferred from a camera image.

## Bounded endpoint observations

Checks were direct, no-redirect GETs using the app's `GlobalPulse/0.1 (consented public landscape camera)` user agent and JPEG/PNG accept header. Each successful payload was decoded and verified as JPEG in memory. All were below the application's 4,000,000-byte and 16-megapixel limits. No source image was added to the repository or an archive.

All times in this table are **UTC on 22 November 2026**, corresponding to the evening of **21 November in America/New_York**. Byte lengths are observations of those particular frames, not expected permanent sizes.

| Registry ID | Place | Check UTC | HTTP / response MIME | Decoded pixels | Bytes | Server Last-Modified UTC |
| --- | --- | --- | --- | --- | ---: | --- |
| `nps-grand-canyon-yavapai` | Grand Canyon, United States | 02:01:56 | 200 / image/jpeg | 3840 × 2160 | 3,261,265 | 01:55:09 |
| `usgs-kilauea-v1` | Kilauea, United States | 02:01:56 | **403 — unavailable** | — | — | — |
| `geonet-ruapehu-north` | Ruapehu north, New Zealand | 02:01:56 | 200 / application/octet-stream | 640 × 480 | 48,020 | 02:01:02 |
| `geonet-ruapehu-south` | Ruapehu south, New Zealand | 02:01:56 | 200 / application/octet-stream | 640 × 480 | 41,333 | 01:51:04 |
| `geonet-taranaki` | Taranaki Maunga, New Zealand | 02:02:01 | 200 / application/octet-stream | 640 × 480 | 66,170 | 01:51:05 |
| `geonet-tongariro` | Tongariro, New Zealand | 02:02:01 | 200 / application/octet-stream | 640 × 480 | 35,954 | 02:01:03 |
| `geonet-whakaari-tekaha` | Whakaari from Te Kaha, New Zealand | 02:02:02 | 200 / application/octet-stream | 640 × 480 | 27,290 | 01:51:05 |
| `geonet-raoul-island` | Raoul Island, New Zealand | 02:02:02 | 200 / application/octet-stream | 640 × 480 | 45,299 | 01:51:04 |
| `dwd-hohenpeissenberg` | Hohenpeißenberg, Germany | 02:04:14 | 200 / image/jpeg | 1200 × 675 | 112,894 | 02:01:37 |
| `dwd-warnemuende` | Warnemünde, Germany | 02:04:14 | 200 / image/jpeg | 1200 × 675 | 114,947 | 02:02:23 |
| `dwd-wasserkuppe` | Wasserkuppe, Germany | 02:04:14 | 200 / image/jpeg | 1200 × 675 | 94,526 | 02:02:42 |
| `dwd-lindenberg` | Lindenberg observatory, Germany | 02:04:18 | 200 / image/jpeg | 1200 × 675 | 91,767 | 02:03:19 |
| `dwd-schmuecke` | Schmücke, Germany | 02:04:19 | 200 / image/jpeg | 1200 × 675 | 116,346 | 02:01:15 |
| `eso-paranal-panorama` | Paranal Observatory, Chile | 02:02:05 | 200 / image/jpeg | 960 × 355 | 102,713 | 01:48:16 |

### Bounded repeat sample, 02:12:15–02:12:33 UTC

One repeat request per endpoint again produced **13 decoded JPEG responses and one USGS HTTP 403**. All six GeoNet images had advanced server modification times to approximately 02:11 UTC and different payload lengths. Three DWD views (Hohenpeißenberg, Lindenberg, Schmücke) likewise advanced to approximately 02:11 UTC with different payload lengths. The NPS modification time advanced to 02:05:09 UTC, but its byte length was unchanged; that alone does not prove a changed picture. Warnemünde and Wasserkuppe retained their approximately 02:02 UTC timestamps, and ESO retained 01:48:16 UTC (about 24 minutes old at the repeat check). Those observations are retained honestly rather than asserting that every image changes on each request. The registry records the first frozen review above; this repeat sample does not establish continuous availability or authenticated camera capture time.

## Primary operator provenance and terms

### U.S. National Park Service and USGS — existing entries rechecked

- [NPS Grand Canyon camera page](https://www.nps.gov/media/webcam/view.htm?id=6AB2E06A-B28C-A55F-6E7C6519E2AA8F51), [exact image](https://www.nps.gov/featurecontent/ard/webcams/images/grcalarge.jpg), [NPS disclaimer and copyright information](https://www.nps.gov/aboutus/disclaimer.htm). NPS credit remains visible; no claim is made over government-origin works.
- [USGS V1 camera page and public-domain designation](https://www.usgs.gov/media/webcams/v1cam-kilauea-volcano-hawaii-west-halemaumau-crater), [exact unavailable image](https://volcanoes.usgs.gov/observatories/hvo/cams/V1cam/images/M.jpg). Its original ID and named-area association are retained for compatibility, but its visible review status is unavailable. No authentication, referrer or access-block bypass was attempted.

### GeoNet / Earth Sciences New Zealand — six additions

The [official camera index](https://www.geonet.org.nz/volcano/cameras) supplies individual camera links and exact current image URLs. The [camera data documentation](https://www.geonet.org.nz/data/types/camera) documents the stable latest-image endpoint and ten-minute source cadence. The [GeoNet policy](https://www.geonet.org.nz/policy) licenses content under [CC BY 3.0 New Zealand](https://creativecommons.org/licenses/by/3.0/nz/).

The visible credit acknowledges GeoNet / Earth Sciences New Zealand and its NHC, LINZ, NEMA and MBIE sponsors. Full uncropped source images are displayed. Camera choices are the [north Ruapehu view](https://www.geonet.org.nz/volcano/cameras/ruapehunorth), [south Ruapehu view](https://www.geonet.org.nz/volcano/cameras/ruapehusouth), [Taranaki Maunga](https://www.geonet.org.nz/volcano/cameras/taranaki), [Tongariro](https://www.geonet.org.nz/volcano/cameras/tongariro), [Te Kaha view toward Whakaari](https://www.geonet.org.nz/volcano/cameras/tekaha), and [Raoul Island](https://www.geonet.org.nz/volcano/cameras/raoulisland).

Each registry entry records the exact reviewed `https://images.geonet.org.nz/volcano/cameras/latest/<camera-id>.jpg` endpoint. These six endpoints served JPEG bytes with `application/octet-stream`. A **per-entry canonical-registry exception** admits that MIME only alongside a valid JPEG/PNG signature, successful bounded raster decoding, HTTP 200 and all pre-existing network controls. Caller/event fields cannot grant the exception. This is not general binary-content admission.

### Deutscher Wetterdienst — five additions

The [DWD public webcam directory](https://opendata.dwd.de/weather/webcam/) and its individual subdirectories expose the exact `_latest_1200.jpg` products used here. Their actual directory listings, not a constructed URL guess, established these endpoints:

- [Hohenpeißenberg south](https://opendata.dwd.de/weather/webcam/Hohenpeissenberg-S/)
- [Warnemünde northwest](https://opendata.dwd.de/weather/webcam/Warnemuende-NW/)
- [Wasserkuppe southwest](https://opendata.dwd.de/weather/webcam/Wasserkuppe-SW/)
- [Lindenberg north-northeast](https://opendata.dwd.de/weather/webcam/Lindenberg-NNE/)
- [Schmücke southwest](https://opendata.dwd.de/weather/webcam/Schmuecke-SW/)

The [official OpenData README](https://opendata.dwd.de/README.txt) explains public, registration-free access. DWD's [current Naturgefahrenportal copyright notice](https://www.naturgefahrenportal.de/de/copyright) applies [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) to its publicly available meteorological information with geographic reference. The separate [DWD observations copyright notice](https://kunden.dwd.de/ankonda/info/copyright.jsf) also permits credited reproduction of freely accessible DWD material and requires marked images to remain unaltered. The implementation treats these broad weather-camera views as geographic meteorological information; it does not reuse portal stock photography or extract protected logos. Credit is **© Deutscher Wetterdienst**; complete images and embedded timestamps/credits remain intact, with aspect-ratio-preserving display only.

### European Southern Observatory — one addition

The [official ESO webcam page](https://www.eso.org/public/outreach/webcams/) expressly offers image embedding through the displayed product URL. The [Paranal panorama image](https://www.eso.org/public/archives/static/pano/latest/pano_PV_960x.jpg) was current at review. [ESO's copyright terms](https://www.eso.org/public/copyright/) provide [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) unless otherwise identified, with full visible credit. This landscape panorama is credited **ESO**, linked to the original page, uncropped, and carries no endorsement claim. It is not an extracted YouTube stream.

## Deliberately excluded from the active expansion

- ESO's ALMA panorama returned a valid JPEG but `Last-Modified` was **21 March 2020**, so HTTP 200 alone did not qualify it as active.
- ESO's ELT south panorama returned a valid JPEG but `Last-Modified` was **20 November 2026 01:59:32 UTC**, nearly two days earlier. It was not added. ESO labels its ELT west camera non-operational.
- Japanese Meteorological Agency camera pages expose recent frames, but their image addresses are time-stamped rather than stable latest-image URLs. Pinning one frame would silently become stale; a separately reviewed resolver would be needed. No invented `latest.jpg` URL or unreviewed adapter was added.
- Australian Antarctic Division permissions do not provide the same straightforward reuse basis for this in-app display; its cameras were not added as native snapshots.
- This bank does **not** claim coverage on every continent. No stale or unlicensed source was added merely to increase a country/continent count.

## Product behavior and QA boundary

- Radio remains the initial tab. Camera search and continent filtering are local, offline operations and never initiate playback or grant consent. Both Ruapehu views retain separate camera identities even when an operator page is shared.
- All reviewed entries are manually browsable without selecting a news event. The UI visibly distinguishes the dated responding count from USGS's unavailable result, displays operator credit/license/source links, and calls the images refreshing stills rather than live video. The unavailable legacy view is explicitly marked in the selector and sorted last in the normal manual bank.
- Network access requires explicit Connect consent, or existing explicit auto-camera consent while the Cameras tab is selected and a conservatively matched active event qualifies. Generic countries/continents do not imply a camera witnessed an event; contradictory named areas fail closed.
- Minimum refresh remains **900 seconds per camera**, with process-wide cadence protection. Requests retain a **15-second deadline**, **4 MB / 16 MP limits**, exact registry binding, no redirects and no cookie loading/saving. Images stay in memory; no recordings, frame history, rehosting or private-person tracking.
- Offline fixture tests cover catalog contracts, named-area conflicts, canonical MIME authority, independent camera identities, local filters, visible credit, retained unavailable status and no implicit connections. Endpoint observations are separate evidence; neither category is Windows packaged-build or continuous-video QA.
