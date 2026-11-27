"""Offline invariants for independently sourced WebSDR operator links.

No test contacts a receiver, fetches a maintained directory, or claims audio.
"""
from urllib.parse import urlsplit

import pytest

from global_pulse.sdr_directory import (
    CURATED_WEBDR_HTTP_ORIGINS,
    CURATED_WEBDR_RECEIVERS,
    DIRECTORY_IMPORT_RESTRICTIONS,
    DIRECTORY_URLS,
    curated_receiver_for_url,
    curated_websdr_receivers,
    parse_directory,
    public_receiver_url,
)


NEW_IDS = {
    "kfs3", "kfs4", "hackgreen_hf", "hackgreen_vhf", "sk4ko", "k3fef",
    "so8oo", "dk0te", "dk1ml", "itapeva", "itajai_vhf", "orlandia",
    "paraibuna", "py7nm", "pu3alk", "volta_redonda", "pocos_caldas",
    "lz2kac", "sv8fxn",
}


def test_expansion_is_explicit_unique_operator_links_not_feed_import(monkeypatch):
    def unexpected_network(*args, **kwargs):
        raise AssertionError("Catalog construction must remain offline")

    monkeypatch.setattr("socket.getaddrinfo", unexpected_network)
    monkeypatch.setattr("socket.create_connection", unexpected_network)
    rows = curated_websdr_receivers()
    ids = [row["id"] for row in rows]
    assert len(rows) == 44
    assert len(set(ids)) == len(ids)
    assert NEW_IDS <= set(ids)
    assert len({row["url"] for row in rows}) == len(rows)
    assert DIRECTORY_URLS == {"websdr": "http://www.websdr.org/"}
    assert "permission" in DIRECTORY_IMPORT_RESTRICTIONS["websdr"].lower()
    for row in rows:
        assert row["provider"] == "websdr"
        assert not urlsplit(row["url"]).hostname.endswith("websdr.org")


def test_every_new_link_has_date_source_and_honest_availability():
    rows = [row for row in curated_websdr_receivers() if row["id"] in NEW_IDS]
    assert len(rows) == 19
    for row in rows:
        assert row["checked_date"] == "2026-11-21"
        assert public_receiver_url(row["documentation"])
        assert row["location"]
        assert row["bands"]
        assert "live audio unverified" in row["provenance"]
        assert "availability unverified" in row["reason"]
        # Named bands and center/sample-rate metadata were observed, but new
        # exact usable boundaries were not asserted. Do not invent band edges.
        assert row["ranges_khz"] == ()


def test_current_config_labels_win_over_templates_or_old_summaries():
    rows = {row["id"]: row for row in curated_websdr_receivers()}
    assert rows["kfs4"]["bands"] == ["12m", "10m-Mid", "10m-Hi"]
    assert rows["paraibuna"]["bands"] == ["80m", "40m"]
    assert rows["pocos_caldas"]["bands"] == ["40m", "10/11m"]
    assert rows["lz2kac"]["bands"] == ["2m"]
    assert "12m" in rows["itapeva"]["bands"]
    assert "stability testing" in rows["kfs3"]["provenance"]
    assert "future UberSDR migration" in rows["orlandia"]["provenance"]


def test_new_legacy_links_have_exact_reviewed_origins_not_wildcards():
    rows = [row for row in curated_websdr_receivers() if row["id"] in NEW_IDS]
    for row in rows:
        url = urlsplit(row["url"])
        if url.scheme == "http":
            assert (url.hostname, url.port or 80) in CURATED_WEBDR_HTTP_ORIGINS
            assert not row["embedded_candidate"]
            assert "consent" in row["reason"]
            assert (url.hostname, 65432) not in CURATED_WEBDR_HTTP_ORIGINS
            assert curated_receiver_for_url(f"http://{url.hostname}:65432/") is None
            # Different schemes/ports do not inherit an operator's catalog facts.
            wrong = f"https://{url.hostname}:{url.port or 80}/"
            assert curated_receiver_for_url(wrong) is None
        else:
            assert url.scheme == "https" and url.port in (None, 443)
            assert row["embedded_candidate"]
    assert ("allhau-0.websdr.at", 80) not in CURATED_WEBDR_HTTP_ORIGINS
    assert not any("*" in host for host, _ in CURATED_WEBDR_HTTP_ORIGINS)


def test_curated_records_are_fresh_and_untrusted_rows_do_not_grant_origins():
    rows = curated_websdr_receivers()
    target = next(row for row in rows if row["id"] == "hackgreen_hf")
    target["bands"].append("invented")
    target["provenance"] = "invented"
    source = next(row for row in CURATED_WEBDR_RECEIVERS if row["id"] == "hackgreen_hf")
    assert "invented" not in source["bands"]
    assert "invented" not in curated_receiver_for_url(source["url"])["provenance"]
    imported = parse_directory(
        "websdr",
        b'[{"url":"http://unreviewed.example:8901/","name":"Claimed WebSDR",'
        b'"bands":["HF"],"ranges_khz":[[0,999999999]],"id":"hackgreen_hf"}]',
    )
    assert len(imported) == 1
    assert not imported[0]["embedded_candidate"]
    assert "ranges_khz" not in imported[0]
    assert curated_receiver_for_url(imported[0]["url"]) is None
    assert ("unreviewed.example", 8901) not in CURATED_WEBDR_HTTP_ORIGINS


@pytest.mark.parametrize("url", [
    "https://kiwisdr.com/", "http://www.kiwisdr.com/public/",
    "https://receiver.proxy.kiwisdr.com/", "http://foo.bar.kiwisdr.com:8073/",
    "https://KIWISDR.COM./", "https://receiver.proxy.ＫＩＷＩＳＤＲ.com/",
])
def test_retired_kiwi_host_family_rejected_after_canonicalization(url):
    with pytest.raises(ValueError, match="removed"):
        public_receiver_url(url)
    assert curated_receiver_for_url(url) is None


def test_retired_provider_and_proxy_candidates_cannot_return():
    with pytest.raises(ValueError, match="Unknown receiver directory"):
        parse_directory("kiwisdr", b"[]")
    rows = parse_directory(
        "websdr",
        b'<a href="https://abc.proxy.kiwisdr.com/">Retired</a>'
        b'<a href="https://kiwisdr.com/">Retired root</a>'
        b'<a href="https://kiwi-radio.example/">Unrelated name</a>',
    )
    assert [row["host"] for row in rows] == ["kiwi-radio.example"]
    assert public_receiver_url("https://notkiwisdr.com/")["host"] == "notkiwisdr.com"
    assert public_receiver_url("https://kiwisdr.com.example/")["host"] == "kiwisdr.com.example"


@pytest.mark.parametrize("url", [
    "http://localhost:8901/", "http://127.0.0.1:8901/", "http://192.168.1.1/",
    "http://[::1]/", "http://radio.local/", "http://user:pass@k3fef.com:8901/",
    "file:///tmp/receiver.html", "http://k3fef.com:65536/",
])
def test_expansion_preserves_private_url_and_credential_rejection(url):
    with pytest.raises(ValueError):
        public_receiver_url(url)


LINK_ONLY_IDS = {"lu6flz", "lu3dj_40", "lu3dj_20", "lu8fcj", "f8kcf_romagny", "f8kcf_saleve"}


def test_nov23_individual_operator_links_keep_transport_and_live_claims_bounded():
    rows = {row["id"]: row for row in curated_websdr_receivers()}
    candidate = rows["bordeaux_ham"]
    assert candidate["embedded_candidate"] and candidate["url"] == "https://ham2.websdrbordeaux.fr/"
    assert "audio and availability unverified" in candidate["reason"]
    for identifier in LINK_ONLY_IDS:
        row = rows[identifier]
        parsed = urlsplit(row["url"])
        assert row["checked_date"] == "2026-11-23"
        assert row["link_only_review"] and not row["embedded_candidate"]
        assert parsed.scheme == "http"
        assert (parsed.hostname, parsed.port or 80) not in CURATED_WEBDR_HTTP_ORIGINS
        assert row["ranges_khz"] == ()
        assert "direct endpoint and live audio unverified" in row["reason"]
        assert public_receiver_url(row["documentation"])
