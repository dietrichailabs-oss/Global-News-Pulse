"""Scoped publisher-identity safety gate for multiple official RSS endpoints.

Source endpoints stay individually identifiable; separate feeds owned by one
publisher cannot falsely count as independent original corroboration.
"""
import copy
import json
from pathlib import Path

import pytest
from global_pulse.sources import load_catalog, parse_feed


DATE = "Wed, 11 Nov 2026 19:00:00 GMT"


def _publisher_source(sid, feed, *, group="usda_nass", independence="original"):
    source = {
        "id": sid,
        "name": "USDA NASS — " + sid,
        "url": "https://www.nass.usda.gov/rss/" + feed,
        "adapter": "rss",
        "enabled": True,
        "access_status": "reviewed_public",
        "allowed_domains": ["www.nass.usda.gov"],
        "article_domains": ["www.nass.usda.gov"],
        "independence": independence,
        "metadata_only": True,
        "language": "en",
    }
    if group is not None:
        source["publisher_origin_id"] = group
    return source


def _parse(source, ident):
    xml = ('<rss><channel><item><guid>' + ident + '</guid>'
           '<title>NASS published notice</title>'
           '<link>https://www.nass.usda.gov/Newsroom/2026/safe.html</link>'
           '<pubDate>' + DATE + '</pubDate>'
           '</item></channel></rss>').encode()
    return parse_feed(xml, source, "2026-11-11T20:00:00Z")[0]


def test_two_real_parser_paths_share_publisher_origin_not_report_identity():
    a = _parse(_publisher_source("nass_news", "news.xml"), "news-1")
    b = _parse(_publisher_source("nass_asb", "asb.xml"), "asb-1")
    assert a["id"] != b["id"] and a["source_id"] != b["source_id"]
    assert a["origin_id"] == b["origin_id"] == "usda_nass"
    assert a["publisher"] != b["publisher"]
    assert a["country_basis"] == b["country_basis"] == "publisher_coverage"
    assert a["latitude"] is None and b["latitude"] is None
    assert a["published_at"] and b["published_at"]


def test_backward_compatible_ungrouped_original_uses_source_id():
    item = _parse(_publisher_source("single_agency", "news.xml", group=None), "a")
    assert item["independence"] == "original" and item["origin_id"] == "single_agency"


def test_unknown_or_syndicated_never_become_original_via_group():
    for level in ("unknown", "syndicated"):
        item = _parse(_publisher_source("other", "news.xml", independence=level), "a")
        assert item["independence"] == level and item["origin_id"] == ""


@pytest.mark.parametrize("bad", ["", "USDA NASS", "foo/bar", "foo.b", {}, [], 17, None])
def test_runtime_catalog_refuses_malformed_publisher_origin_group(tmp_path, bad):
    base = json.loads((Path(__file__).resolve().parents[1] /
        "global_pulse/resources/sources.json").read_text(encoding="utf-8"))
    base = copy.deepcopy(base)
    base["sources"][0]["publisher_origin_id"] = bad
    f = tmp_path / "catalog.json"
    f.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid publisher origin identity"):
        load_catalog(f)


def test_released_catalog_without_origin_groups_still_loads():
    sources = load_catalog()
    assert sources and all("id" in item for item in sources)
