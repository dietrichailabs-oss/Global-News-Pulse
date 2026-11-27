"""Explicit receiver links plus bounded, untrusted public SDR directory parsing.

The curated list records individual owner-supplied/operator-documented
links. It is not an import or copy of WebSDR.org's maintained directory feed.
Neither curated records nor parsed candidates imply live reception or rights.
"""
from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_DIRECTORY_BYTES = 1_000_000
MAX_RECEIVERS = 400
DIRECTORY_URLS = {
    # WebSDR's official FAQ explicitly points to HTTP www.websdr.org for its
    # live operator list. It is opened only in the external browser; in-app
    # dataset import is permission-blocked below. Never autoconnect its links.
    "websdr": "http://www.websdr.org/",
}
# Verified November 20, 2026: WebSDR's public home is a frameset; its
# official frame loads a JSON receiver dataset whose response expressly
# requires prior permission for use in another website or automated system.
# Do not replace the broken HTML scrape with that restricted data endpoint.
# The public browser directory and owner-supplied individual links still work.
DIRECTORY_IMPORT_RESTRICTIONS = {
    "websdr": "Automatic import of WebSDR.org's maintained directory needs its operator's permission. "
              "The individually supplied links below are available without that import. "
              "Use Open directory for the provider's full live list."
}
# Individual receiver facts supplied by the owner or checked on that receiver's
# own operator page, November 20–21, 2026. Do not infer bounds from ham band names,
# rounded public-directory thumbnails or a different receiver at the same site.
# Numeric ranges are kHz. A listed range is not proof of current coverage/audio.
CURATED_WEBDR_RECEIVERS = (
    {
        "id": "na5b", "name": "NA5B · owner-tested link",
        "location": "Operator location not recorded",
        "url": "http://na5b.com:8901/", "ranges_khz": (),
        "bands": ("MW–160", "80m", "40m", "30m", "25m", "20m", "15m", "10m"),
        "provenance": "Individual link and band labels observed in the owner's receiver screenshot; numeric bounds and live reception not verified",
        "documentation": "http://na5b.com:8901/",
    },
    {
        "id": "twente", "name": "University of Twente",
        "location": "Enschede, Netherlands",
        "url": "http://websdr.ewi.utwente.nl:8901/",
        "ranges_khz": ((0.0, 29160.0),), "bands": (),
        "provenance": "Individual link, name and 0.000–29.160 MHz range supplied by owner; not live verified",
        "documentation": "http://websdr.ewi.utwente.nl:8901/",
    },
    {
        "id": "georgia", "name": "Odlisi–Kakheti HF WebSDR",
        "location": "Odlisi, Kakheti, Georgia",
        "url": "http://sdrgeorgia.sytes.net:8902/",
        "ranges_khz": ((26976.0, 29024.0),), "bands": (),
        "provenance": "Owner-supplied link; range and location listed by NARG, checked 2026-11-20; not live verified",
        "documentation": "https://narg.ge/websdr-tbilisi/",
    },
    {
        "id": "utah1", "name": "Northern Utah #1 · Yellow",
        "location": "Corinne, Utah, USA",
        "url": "http://websdr1.sdrutah.org:8901/index1a.html",
        "ranges_khz": ((125.0,221.0),(389.0,485.0),(516.0,2564.0),
                       (1708.0,2090.0),(3366.0,4134.0),(4816.0,5584.0),
                       (6741.0,7509.0)),
        "bands": (),
        "provenance": "Individually checked Northern Utah operator table, 2026-11-20; listed windows, not live verified",
        "documentation": "https://www.sdrutah.org/info/techinfo.html",
    },
    {
        "id": "utah2", "name": "Northern Utah #2 · Green",
        "location": "Corinne, Utah, USA",
        "url": "http://websdr2.sdrutah.org:8902/index1a.html",
        "ranges_khz": ((9994.0,10186.0),(13766.0,14354.0),(18022.0,18214.0),
                       (20816.0,21584.0),(24844.0,25036.0),(27816.0,28584.0),
                       (28232.0,29768.0),(49975.0,50625.0)),
        "bands": (),
        "provenance": "Northern Utah operator table, checked 2026-11-20; 20m upper bound is printed as 14.354 MHz despite an inconsistent center/bandwidth; not live verified",
        "documentation": "https://www.sdrutah.org/info/techinfo.html",
    },
    {
        "id": "utah4", "name": "Northern Utah #4 · Magenta",
        "location": "Corinne, Utah, USA",
        "url": "http://websdr4.sdrutah.org:8904/",
        "ranges_khz": ((6741.0,7509.0),(9994.0,10186.0),(13766.0,14354.0),
                       (18022.0,18214.0),(20816.0,21584.0),(24844.0,25036.0),
                       (27816.0,28584.0),(28232.0,29768.0)),
        "bands": (),
        "provenance": "Northern Utah operator table, checked 2026-11-20; 20m upper bound is printed as 14.354 MHz despite an inconsistent center/bandwidth; not live verified",
        "documentation": "https://www.sdrutah.org/info/techinfo.html",
    },
    {
        "id": "utah5", "name": "Northern Utah #5 · Teal",
        "location": "Corinne, Utah, USA",
        "url": "http://websdr5.sdrutah.org:8905/",
        "ranges_khz": ((9994.0,10186.0),(13766.0,14354.0),(18022.0,18214.0),
                       (20816.0,21584.0),(24844.0,25036.0),(27816.0,28584.0),
                       (28232.0,29768.0)),
        "bands": (),
        "provenance": "Northern Utah operator table, checked 2026-11-20; 20m upper bound is printed as 14.354 MHz despite an inconsistent center/bandwidth; not live verified",
        "documentation": "https://www.sdrutah.org/info/techinfo.html",
    },
    {
        "id": "maasbree_low", "name": "Maasbree · HF low",
        "location": "Maasbree, Netherlands",
        "url": "http://sdr.websdrmaasbree.nl:8901/", "ranges_khz": (),
        "bands": ("160m–15m (separate bands)",),
        "provenance": "Direct endpoint and HF band-family label from the operator manual, checked 2026-11-20; separate windows, not continuous coverage; exact HF edges and live reception unverified",
        "documentation": "https://www.pa0sim.nl/Manual_WebSDR_Maasbree.pdf",
    },
    {
        "id": "maasbree_high", "name": "Maasbree · HF high",
        "location": "Maasbree, Netherlands",
        "url": "http://sdr.websdrmaasbree.nl:8902/", "ranges_khz": (),
        "bands": ("40m–10m (separate bands)",),
        "provenance": "Direct endpoint and HF band-family label from the operator manual, checked 2026-11-20; separate windows, not continuous coverage; exact HF edges and live reception unverified",
        "documentation": "https://www.pa0sim.nl/Manual_WebSDR_Maasbree.pdf",
    },
    {
        "id": "maasbree_2m", "name": "Maasbree · 2m",
        "location": "Maasbree, Netherlands",
        "url": "http://sdr.websdrmaasbree.nl:8905/",
        "ranges_khz": ((144000.0, 145000.0), (145000.0, 146000.0)),
        "bands": ("2m",),
        "provenance": "Direct endpoint and two 2m windows from the operator manual, checked 2026-11-20; 144–145 and 145–146 MHz use different antennas; live reception unverified",
        "documentation": "https://www.pa0sim.nl/Manual_WebSDR_Maasbree.pdf",
    },
    {
        "id": "kfs1", "name": "KFS #1 · Omnidirectional",
        "location": "Half Moon Bay, California, USA",
        "url": "http://websdr1.kfsdr.com:8901/", "ranges_khz": (),
        "bands": ("80/75m", "60m", "40m", "30m", "20m", "17m", "15m", "10m"),
        "provenance": "Individual receiver link and band labels from the KFS operator page, checked 2026-11-20; exact edges and live reception unverified",
        "documentation": "https://www.kfsdr.org/",
    },
    {
        "id": "kfs2", "name": "KFS #2 · Omnidirectional",
        "location": "Half Moon Bay, California, USA",
        "url": "http://websdr2.kfsdr.com:8902/", "ranges_khz": (),
        "bands": ("160m", "12m", "10m-FM"),
        "provenance": "Individual receiver link and band labels from the KFS operator page, checked 2026-11-20; exact edges and live reception unverified",
        "documentation": "https://www.kfsdr.org/",
    },
    {
        "id": "g0xbu1", "name": "G0XBU · Jodrell #1",
        "location": "Near Jodrell Bank, United Kingdom; independently operated",
        "url": "http://g0xbuwebsdr.ddns.net:8901/", "ranges_khz": (),
        "bands": ("20m", "80m", "60m", "4m", "CB", "Airband", "Marine"),
        "provenance": "Individual G0XBU operator link and band labels, checked 2026-11-20; not affiliated with Jodrell Bank; example configuration snippets are not current coverage proof",
        "documentation": "https://www.g0xbu.co.uk/websdr",
    },
    {
        "id": "g0xbu2", "name": "G0XBU · Jodrell #2",
        "location": "Near Jodrell Bank, United Kingdom; independently operated",
        "url": "http://g0xbuwebsdr.ddns.net:8902/", "ranges_khz": (),
        "bands": ("2m", "70cm", "PMR446", "6m", "Airband"),
        "provenance": "Individual G0XBU operator link and band labels, checked 2026-11-20; not affiliated with Jodrell Bank; exact edges and live reception unverified",
        "documentation": "https://www.g0xbu.co.uk/websdr",
    },
    {
        "id": "df0hte", "name": "DF0HTE · Esslingen University",
        "location": "Esslingen, Germany",
        "url": "https://websdr.afunk.hs-esslingen.de/",
        "ranges_khz": ((1416.0, 2184.0), (3468.0, 3852.0),
                       (6908.0, 7292.0), (10004.0, 10196.0),
                       (13791.0, 14559.0), (18004.0, 18196.0),
                       (26431.0, 27199.0), (28936.0, 29704.0)),
        "bands": ("160m", "80m", "40m", "30m", "20m", "17m", "11m", "10m"),
        "provenance": "Numeric windows from the indexed operator mobile page, checked 2026-11-20; not a live receiver-state or audio observation",
        "documentation": "https://websdr.afunk.hs-esslingen.de/m.html",
    },
    {
        "id": "goonhilly", "name": "AMSAT-UK / BATC · Goonhilly",
        "location": "Goonhilly Earth Station, Cornwall, United Kingdom",
        "url": "https://vhf-goonhilly.batc.org.uk/",
        "ranges_khz": ((144000.0, 146000.0), (435000.0, 437000.0),
                       (1296000.0, 1298000.0), (2320000.0, 2321000.0)),
        "bands": ("2m", "70cm", "23cm", "13cm"),
        "provenance": "Four separate windows explicitly listed by the Goonhilly operator, checked 2026-11-20; no continuous coverage between windows or live reception claimed",
        "documentation": "https://vhf-goonhilly.batc.org.uk/",
    },
    {
        "id": "pardinho", "name": "Pardinho WebSDR",
        "location": "Pardinho, São Paulo, Brazil · GG56TV",
        "url": "https://pardinho.websdr.com.br/", "ranges_khz": (),
        "bands": ("160m", "80m", "40m", "20m", "15m", "10/11m"),
        "provenance": "Band labels from the indexed operator receiver page, checked 2026-11-20; presets are not coverage boundaries; exact edges and live reception unverified",
        "documentation": "https://pardinho.websdr.com.br/",
    },
    {
        "id": "oa6dxv", "name": "OA6DXV · RepublicaOA6",
        "location": "Arequipa, Peru",
        "url": "https://websdr2.republicaoa6.com/", "ranges_khz": (),
        "bands": ("40m",),
        "provenance": "Operator lists 40m with center 7100 kHz, checked 2026-11-20; a center frequency does not establish lower/upper limits or live reception",
        "documentation": "https://websdr2.republicaoa6.com/",
    },
    # Independently checked operator links; no central directory import.
    # See docs/WEBDR_OPERATOR_LINKS_20261121.md for sources and exclusions.
    # Static page/configuration availability is not proof of active audio.
    {
        "id": "kfs3", "name": "KFS #3 · Southeast Array",
        "location": "Half Moon Bay, California, USA",
        "url": "http://websdr3.kfsdr.com:8903/", "ranges_khz": (),
        "bands": ("80/75m", "60m", "40m", "30m", "20m", "17m", "15m", "10m-Lo"),
        "checked_date": "2026-11-21",
        "provenance": "KFS operator news and receiver HTML/config checked 2026-11-21; operator reports ongoing stability testing; exact edges and live audio unverified",
        "documentation": "https://www.kfsdr.com/news",
    },
    {
        "id": "kfs4", "name": "KFS #4 · Southeast Array",
        "location": "Half Moon Bay, California, USA",
        "url": "http://websdr4.kfsdr.com:8904/", "ranges_khz": (),
        "bands": ("12m", "10m-Mid", "10m-Hi"),
        "checked_date": "2026-11-21",
        "provenance": "KFS operator news and receiver HTML/config checked 2026-11-21; operator reports ongoing stability testing; exact edges and live audio unverified",
        "documentation": "https://www.kfsdr.com/news",
    },
    {
        "id": "hackgreen_hf", "name": "Hack Green · HF",
        "location": "Nantwich, Cheshire, United Kingdom",
        "url": "http://hackgreensdr.org:8901/", "ranges_khz": (),
        "bands": ("160m", "80m", "60m", "40m", "20m", "17m"),
        "checked_date": "2026-11-21",
        "provenance": "RAF Hack Green operator page and its band configuration retrieved 2026-11-21; exact edges and live audio unverified",
        "documentation": "http://hackgreensdr.org:8901/",
    },
    {
        "id": "hackgreen_vhf", "name": "Hack Green · VHF / UHF",
        "location": "Nantwich, Cheshire, United Kingdom",
        "url": "http://hackgreensdr.org:8902/", "ranges_khz": (),
        "bands": ("70cm", "2m", "4m", "10m", "6m"),
        "checked_date": "2026-11-21",
        "provenance": "RAF Hack Green operator page and its band configuration retrieved 2026-11-21; exact edges and live audio unverified",
        "documentation": "http://hackgreensdr.org:8902/",
    },
    {
        "id": "sk4ko", "name": "SK4KO · Mora",
        "location": "Mora, Sweden",
        "url": "http://websdr.sk4ko.com:8901/", "ranges_khz": (),
        "bands": ("160m", "80m", "40m", "20m", "15m", "10m"),
        "checked_date": "2026-11-21",
        "provenance": "SK4KO club announcement and HF receiver HTML/config checked 2026-11-21; separate offline VHF service not included; exact edges and live audio unverified",
        "documentation": "https://www.sk4ko.com/new/index.php/home/nyheter/196-new-hf-websdr-online",
    },
    {
        "id": "k3fef", "name": "K3FEF / W3TKP · Radio Ranch",
        "location": "Milford, Pennsylvania, USA",
        "url": "http://k3fef.com:8901/", "ranges_khz": (),
        "bands": ("HF",),
        "checked_date": "2026-11-21",
        "provenance": "K3FEF operator page and its HF configuration retrieved 2026-11-21; separate UberSDR is not this endpoint; exact edges and live audio unverified",
        "documentation": "http://k3fef.com:8901/",
    },
    {
        "id": "so8oo", "name": "SO8OO · Southeastern Poland",
        "location": "Southeastern Poland · KN09vw",
        "url": "https://sdr.so8oo.net/", "ranges_khz": (),
        "bands": ("VLF", "160m", "80m", "60m", "40m", "20m", "10m", "QO-100"),
        "checked_date": "2026-11-21",
        "provenance": "Location and band labels on the SO8OO operator page checked 2026-11-21; exact edges and live audio unverified",
        "documentation": "https://sdr.so8oo.net/",
    },
    {
        "id": "dk0te", "name": "DK0TE · Lake Constance",
        "location": "Friedrichshafen, Germany · JN47RP",
        "url": "http://dk0te.dhbw-ravensburg.de:8901/", "ranges_khz": (),
        "bands": ("160m", "80m-CW", "80m", "40m", "30m", "20m", "15m", "10m"),
        "checked_date": "2026-11-21",
        "provenance": "DK0TE operator page and its current band configuration retrieved 2026-11-21; separate narrow windows, not full ham-band coverage; exact edges and live audio unverified",
        "documentation": "http://dk0te.dhbw-ravensburg.de:8901/",
    },
    {
        "id": "dk1ml", "name": "DK1ML · Frankfurt / Main",
        "location": "Near Frankfurt / Main, Germany",
        "url": "http://websdr.homeip.net:8901/", "ranges_khz": (),
        "bands": ("160m", "80m", "60m", "40m", "20m", "6m", "2m", "70cm", "23cm", "QO-100"),
        "checked_date": "2026-11-21",
        "provenance": "DK1ML operator announcement on F05 club site and receiver HTML checked 2026-11-21; operator-published labels only; exact edges and live audio unverified",
        "documentation": "https://f05.de/2025/11/05/das-neue-websdr-von-dk1ml/",
    },
    {
        "id": "itapeva", "name": "Itapeva · Fazenda São Francisco",
        "location": "Itapeva, São Paulo, Brazil",
        "url": "http://itapeva.websdr.com.br:8901/", "ranges_khz": (),
        "bands": ("160m", "80m", "40m", "30m", "20m", "15m", "12m", "10m"),
        "checked_date": "2026-11-21",
        "provenance": "Independent Brazilian operator network identifies this station; receiver HTML/config retrieved 2026-11-21; current config labels supersede older network summary; exact edges and live audio unverified",
        "documentation": "http://itapeva.websdr.com.br:8901/",
    },
    {
        "id": "itajai_vhf", "name": "Itajaí · VHF",
        "location": "Itajaí, Santa Catarina, Brazil",
        "url": "http://itajai.sdr.net.br:8083/", "ranges_khz": (),
        "bands": ("VHF LO", "VHF HI"),
        "checked_date": "2026-11-21",
        "provenance": "Itajaí operator page and its two-window VHF configuration retrieved 2026-11-21; separate unresponsive HF endpoint not included; exact edges and live audio unverified",
        "documentation": "http://itajai.sdr.net.br:8083/",
    },
    {
        "id": "orlandia", "name": "Orlândia · HF",
        "location": "Orlândia, São Paulo, Brazil",
        "url": "http://orlandia.sdr.net.br:9001/", "ranges_khz": (),
        "bands": ("40m", "80m"),
        "checked_date": "2026-11-21",
        "provenance": "Orlândia WebSDR HTML/config retrieved 2026-11-21; operator announces a future UberSDR migration, not yet treated as supported here; exact edges and live audio unverified",
        "documentation": "http://orlandia.sdr.net.br:9001/",
    },
    {
        "id": "paraibuna", "name": "Paraibuna · HF",
        "location": "Paraibuna, São Paulo, Brazil",
        "url": "http://paraibuna.websdr.com.br:8901/", "ranges_khz": (),
        "bands": ("80m", "40m"),
        "checked_date": "2026-11-21",
        "provenance": "Independent Brazilian operator network identifies this station; receiver HTML/config retrieved 2026-11-21; two configured bands only, not older template buttons; exact edges and live audio unverified",
        "documentation": "http://paraibuna.websdr.com.br:8901/",
    },
    {
        "id": "py7nm", "name": "PY7NM · Caruaru",
        "location": "Caruaru, Pernambuco, Brazil",
        "url": "http://py7nmcaruarupe.ddns.net:81/", "ranges_khz": (),
        "bands": ("40m", "30m", "VHF", "11m"),
        "checked_date": "2026-11-21",
        "provenance": "PY7NM receiver HTML/config retrieved 2026-11-21; location corroborated by its independent operator network; config labels only, not generic buttons; exact edges and live audio unverified",
        "documentation": "http://py7nmcaruarupe.ddns.net:81/",
    },
    {
        "id": "pu3alk", "name": "PU3ALK · Porto Lucena",
        "location": "Porto Lucena, Rio Grande do Sul, Brazil",
        "url": "http://pu3alk.com.br:9001/", "ranges_khz": (),
        "bands": ("80m", "40m", "10m"),
        "checked_date": "2026-11-21",
        "provenance": "PU3ALK operator page and its band configuration retrieved 2026-11-21; exact edges and live audio unverified",
        "documentation": "http://pu3alk.com.br:9001/",
    },
    {
        "id": "volta_redonda", "name": "Volta Redonda · HF / VHF",
        "location": "Volta Redonda, Rio de Janeiro, Brazil · GG77XM",
        "url": "http://websdr.dynv6.net:8901/", "ranges_khz": (),
        "bands": ("40m", "15m", "2m-L", "2m-H"),
        "checked_date": "2026-11-21",
        "provenance": "Volta Redonda WebSDR operator HTML/config retrieved 2026-11-21; separate OpenWebRX link is not included; exact edges and live audio unverified",
        "documentation": "http://websdr.dynv6.net:8901/",
    },
    {
        "id": "pocos_caldas", "name": "CRAPOCA · Poços de Caldas",
        "location": "Poços de Caldas, Minas Gerais, Brazil",
        "url": "http://crapoca.websdr.com.br:8901/", "ranges_khz": (),
        "bands": ("40m", "10/11m"),
        "checked_date": "2026-11-21",
        "provenance": "Independent Brazilian operator network identifies this station; receiver HTML/config retrieved 2026-11-21; current two-band configuration only; exact edges and live audio unverified",
        "documentation": "http://crapoca.websdr.com.br:8901/",
    },
    {
        "id": "lz2kac", "name": "LZ2KAC · Gabrovo",
        "location": "Gabrovo, Bulgaria",
        "url": "http://websdr.lz2kac.org:8901/", "ranges_khz": (),
        "bands": ("2m",),
        "checked_date": "2026-11-21",
        "provenance": "LZ2KAC operator page and its single-band configuration retrieved 2026-11-21; no extra bands inferred from the station name; exact edges and live audio unverified",
        "documentation": "http://websdr.lz2kac.org:8901/",
    },
    {
        "id": "sv8fxn", "name": "SV8FXN · Naxos Island",
        "location": "Naxos Island, Greece",
        "url": "http://sv8fxn-naxos.ddns.net:8901/", "ranges_khz": (),
        "bands": ("40m", "80m", "160m", "MW"),
        "checked_date": "2026-11-21",
        "provenance": "Naxos operator page and its four-band configuration retrieved 2026-11-21; exact edges and live audio unverified",
        "documentation": "http://sv8fxn-naxos.ddns.net:8901/",
    },
    {
        "id": "bordeaux_ham", "name": "Bordeaux · HAM",
        "location": "Bordeaux, France",
        "url": "https://ham2.websdrbordeaux.fr/", "ranges_khz": (),
        "bands": ("HF",),
        "checked_date": "2026-11-23",
        "provenance": "Operator WebSDR page exposes tuning, mode and waterfall controls in retrieved HTML; HF coverage described by radio amateur F5NIH, exact edges and live audio unverified",
        "documentation": "https://www.websdrbordeaux.fr/",
    },
    {
        "id": "lu6flz", "name": "LU6FLZ · Venado Tuerto · browser only",
        "location": "Santa Fe, Argentina",
        "url": "http://lu6flz.no-ip.org:7999/", "ranges_khz": (),
        "bands": ("40m",),
        "checked_date": "2026-11-23",
        "provenance": "Operator-linked Radio Club Venado Tuerto and LU7DKO Observatory identify this receiver; direct endpoint could not be verified in this environment; live audio unverified",
        "documentation": "https://www.lu3fv.com.ar/recursos",
        "link_only_review": True,
    },
    {
        "id": "lu3dj_40", "name": "LU3DJ · Tres Arroyos 40m · browser only",
        "location": "Buenos Aires, Argentina",
        "url": "http://lu3dj.ddns.net:8080/", "ranges_khz": (),
        "bands": ("40m",),
        "checked_date": "2026-11-23",
        "provenance": "Radio Club Villa María publishes this individual endpoint and band; direct page not verified; live audio unverified",
        "documentation": "https://radioclubvillamaria.info/websdr/",
        "link_only_review": True,
    },
    {
        "id": "lu3dj_20", "name": "LU3DJ · Tres Arroyos 20m · browser only",
        "location": "Buenos Aires, Argentina",
        "url": "http://lu3dj.ddns.net:8081/", "ranges_khz": (),
        "bands": ("20m",),
        "checked_date": "2026-11-23",
        "provenance": "Radio Club Villa María publishes this distinct receiver port and band; direct page not verified; live audio unverified",
        "documentation": "https://radioclubvillamaria.info/websdr/",
        "link_only_review": True,
    },
    {
        "id": "lu8fcj", "name": "LU8FCJ · Villa Cañás · browser only",
        "location": "Santa Fe, Argentina",
        "url": "http://el22.dyndns-blog.com:8080/", "ranges_khz": (),
        "bands": ("80m",),
        "checked_date": "2026-11-23",
        "provenance": "Radio Club Villa María lists this exact 80m link and Radio Club Venado Tuerto confirms the operator; direct page not verified; live audio unverified",
        "documentation": "https://radioclubvillamaria.info/websdr/",
        "link_only_review": True,
    },
    {
        "id": "f8kcf_romagny", "name": "F8KCF · Romagny · browser only",
        "location": "Annemasse, France",
        "url": "http://sdr.f8kcf.net:8901/", "ranges_khz": (),
        "bands": ("2m", "70cm"),
        "checked_date": "2026-11-23",
        "provenance": "Hosting club documents this exact VHF/UHF endpoint; direct page not verified; live audio unverified",
        "documentation": "https://f8kcf.net/accueil/",
        "link_only_review": True,
    },
    {
        "id": "f8kcf_saleve", "name": "F8KCF · Mont Salève · browser only",
        "location": "Haute-Savoie, France",
        "url": "http://sdr2.f8kcf.net:7489/", "ranges_khz": (),
        "bands": ("2m", "70cm", "3cm"),
        "checked_date": "2026-11-23",
        "provenance": "Hosting club documents this receiver and bands; direct page not verified; live audio unverified. High frequency controls remain in the original browser.",
        "documentation": "https://f8kcf.net/accueil/",
        "link_only_review": True,
    },
)
# Curating an arbitrary discovery result never grants HTTP/WebEngine admission.
# This immutable allowlist contains only the exact individually reviewed origins.
CURATED_WEBDR_HTTP_ORIGINS = frozenset({
    ("na5b.com", 8901),
    ("websdr.ewi.utwente.nl", 8901),
    ("sdrgeorgia.sytes.net", 8902),
    ("websdr1.sdrutah.org", 8901),
    ("websdr2.sdrutah.org", 8902),
    ("websdr4.sdrutah.org", 8904),
    ("websdr5.sdrutah.org", 8905),
    ("sdr.websdrmaasbree.nl", 8901),
    ("sdr.websdrmaasbree.nl", 8902),
    ("sdr.websdrmaasbree.nl", 8905),
    ("websdr1.kfsdr.com", 8901),
    ("websdr2.kfsdr.com", 8902),
    ("g0xbuwebsdr.ddns.net", 8901),
    ("g0xbuwebsdr.ddns.net", 8902),
    ("websdr3.kfsdr.com", 8903),
    ("websdr4.kfsdr.com", 8904),
    ("hackgreensdr.org", 8901),
    ("hackgreensdr.org", 8902),
    ("websdr.sk4ko.com", 8901),
    ("k3fef.com", 8901),
    ("dk0te.dhbw-ravensburg.de", 8901),
    ("websdr.homeip.net", 8901),
    ("itapeva.websdr.com.br", 8901),
    ("itajai.sdr.net.br", 8083),
    ("orlandia.sdr.net.br", 9001),
    ("paraibuna.websdr.com.br", 8901),
    ("py7nmcaruarupe.ddns.net", 81),
    ("pu3alk.com.br", 9001),
    ("websdr.dynv6.net", 8901),
    ("crapoca.websdr.com.br", 8901),
    ("websdr.lz2kac.org", 8901),
    ("sv8fxn-naxos.ddns.net", 8901),
})
_IGNORED_HOSTS = {
    "websdr.org", "www.websdr.org", "kiwisdr.com", "www.kiwisdr.com",
    "github.com", "www.github.com", "youtube.com", "www.youtube.com",
    "facebook.com", "www.facebook.com", "twitter.com", "x.com",
}


def public_receiver_url(value):
    """Validate public host URLs, even when an operator uses HTTP/custom ports.

    The separate in-app policy is HTTPS/443 plus a finite exact-origin list for
    consented legacy receivers. Validation alone never grants that exception.
    Never fetch these URLs for discovery; browsing requires explicit action.
    """
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid receiver URL")
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Public HTTP(S) receiver URL required")
    if parts.username or parts.password or "\\" in parts.netloc:
        raise ValueError("Unsafe receiver URL")
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".local", ".localhost", ".lan", ".internal", ".test", ".invalid")
    ):
        raise ValueError("Private host not accepted")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and not addr.is_global:
        raise ValueError("Non-public IP address not accepted")
    if addr is None:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid host") from exc
        if not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}",
            ascii_host,
        ):
            raise ValueError("Public DNS name required")
        host = ascii_host
    if host == "kiwisdr.com" or host.endswith(".kiwisdr.com"):
        raise ValueError("KiwiSDR receivers have been removed")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid receiver port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid receiver port")
    netloc = f"[{host}]" if addr is not None and addr.version == 6 else host
    if port is not None:
        netloc += f":{port}"
    clean = urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))
    embedded = parts.scheme.lower() == "https" and port in (None, 443)
    return {"url": clean, "host": host, "embedded_candidate": embedded,
            "reason": ("HTTPS/443 candidate; embedded resources may still fail"
                       if embedded else "Browser only: receiver requires HTTP or custom port")}


def curated_websdr_receivers():
    """Fresh records; no network, persisted input, or directory-feed dependency."""
    result = []
    for source in CURATED_WEBDR_RECEIVERS:
        row = dict(public_receiver_url(source["url"]))
        row.update(source)
        row["bands"] = list(source["bands"])
        row["ranges_khz"] = tuple(tuple(pair) for pair in source["ranges_khz"])
        row["provider"] = "websdr"
        parsed = urlsplit(row["url"])
        if row.get("link_only_review"):
            # Club-published HTTP links are selectable external bookmarks;
            # no new unencrypted embedded origin or numeric bounds granted.
            row["embedded_candidate"] = False
            row["reason"] = "Browser only: club-published link; direct endpoint and live audio unverified; availability unverified"
        elif row["embedded_candidate"]:
            row["reason"] = (
                "Operator HTTPS/443 candidate; embedded resources may still fail; "
                "audio and availability unverified"
            )
        elif (parsed.scheme == "http"
              and (parsed.hostname, parsed.port or 80) in CURATED_WEBDR_HTTP_ORIGINS):
            row["reason"] = (
                f"Operator HTTP/{parsed.port or 80}; in-app only after specific "
                "unencrypted transport consent; audio and availability unverified"
            )
        else:
            row["reason"] = (
                "Browser only: operator HTTP/custom port is not admitted in-app; "
                "audio and availability unverified"
            )
        result.append(row)
    return result


def curated_receiver_for_url(value):
    """Return only built-in individual facts matching this exact public origin."""
    try:
        parsed = urlsplit(public_receiver_url(value)["url"])
    except (ValueError, TypeError):
        return None
    origin = (parsed.scheme, parsed.hostname,
              parsed.port or (443 if parsed.scheme == "https" else 80))
    for row in curated_websdr_receivers():
        target = urlsplit(row["url"])
        target_origin = (target.scheme, target.hostname,
                         target.port or (443 if target.scheme == "https" else 80))
        if origin == target_origin:
            return row
    return None


def receiver_range_label(ranges):
    """Format already curated numeric bounds without claiming a station is on air."""
    return " · ".join(f"{start/1000:.3f}–{end/1000:.3f} MHz" for start, end in ranges)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.current = {"href": dict(attrs).get("href", ""), "title": []}

    def handle_data(self, data):
        if self.current is not None and sum(map(len, self.current["title"])) < 240:
            self.current["title"].append(data[:240])

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            self.links.append((self.current["href"], " ".join(self.current["title"])))
            self.current = None


def _json_rows(parsed):
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("receivers", "stations", "results", "entries", "items", "data"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    return []


def _operator_bands(value):
    """Only operator-supplied band labels; never fabricate numeric bounds."""
    if not isinstance(value,list):
        return []
    labels=[]
    for raw in value[:40]:
        if (not isinstance(raw,str) or not raw.strip()
                or any(ord(char)<32 for char in raw)):
            continue
        label=re.sub(r"\s+"," ",raw).strip()[:30]
        if label and label not in labels:
            labels.append(label)
        if len(labels)>=24:
            break
    return labels


def parse_directory(provider, content):
    """Return bounded, deduplicated candidates from one official directory.

    A directory's HTML can change or be access-gated, so an empty result is
    honest. Do not claim that this is every operating receiver or a live status.
    """
    if provider not in DIRECTORY_URLS:
        raise ValueError("Unknown receiver directory")
    if not isinstance(content, (bytes, bytearray)) or len(content) > MAX_DIRECTORY_BYTES:
        raise ValueError("Directory reply exceeded bounded size")
    raw = bytes(content).decode("utf-8", errors="replace")
    candidates = []
    if raw.lstrip().startswith(("[", "{")):
        try:
            rows = _json_rows(json.loads(raw))
        except (ValueError, TypeError, RecursionError):
            # A small deeply nested JSON reply can exceed Python's recursion
            # budget; it must not escape the Qt network completion callback.
            rows = []
        for row in rows[:MAX_RECEIVERS * 3]:
            if isinstance(row, dict):
                href = row.get("url") or row.get("link") or row.get("receiver_url")
                title = row.get("name") or row.get("title") or row.get("location")
                if isinstance(href, str):
                    candidates.append((href, title, _operator_bands(row.get("bands"))))
    else:
        parser = _Links()
        parser.feed(raw)
        candidates = [(href,title,[]) for href,title in parser.links[:MAX_RECEIVERS * 10]]
    results, seen = [], set()
    for href, title, bands in candidates:
        if not isinstance(href, str):
            continue
        try:
            url = urljoin(DIRECTORY_URLS[provider], href)
            info = public_receiver_url(url)
        except (ValueError, TypeError):
            # One malformed URL (including an invalid IPv6 bracket) must not
            # discard independent valid operators in the same response.
            continue
        host=info["host"]
        if (host in _IGNORED_HOSTS or host.endswith(".websdr.org")
                or host.endswith(".kiwisdr.com")):
            continue
        if info["url"] in seen:
            continue
        seen.add(info["url"])
        label = re.sub(r"\s+", " ", str(title or "")).strip()[:110]
        info.update({"name": label or info["host"], "provider": provider,
                     "bands": bands})
        results.append(info)
        if len(results) >= MAX_RECEIVERS:
            break
    return results
