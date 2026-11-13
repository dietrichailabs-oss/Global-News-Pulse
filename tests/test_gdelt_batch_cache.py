"""Deterministic GDELT batch/cache boundary tests; no public network or article requests."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import io
import sqlite3
import zipfile

import pytest

from global_pulse.gdelt_batches import (
    GdeltBatchCache, GdeltBatchError, parse_manifest, MAX_ARCHIVE_BYTES,
)

STAMP = "20261111080000"


def event_row(identifier="1001", *, day="20261110", date_added=STAMP,
              url="https://example.org/story", event_code="043", country="US"):
    row = [""] * 61
    row[0] = identifier
    row[1] = day
    row[26] = event_code
    row[29] = "3"
    row[52] = "Anchorage, Alaska"
    row[53] = country
    row[56] = "61.2181"
    row[57] = "-149.9003"
    row[59] = date_added
    row[60] = url
    return "\t".join(row)


def payload(rows, *, stamp=STAMP, name=None):
    filename = name or f"{stamp}.export.CSV"
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr(filename, ("\n".join(rows) + "\n").encode("utf-8"))
    return memory.getvalue()


def batch_from_archive(archive, *, stamp=STAMP, kind="export.CSV"):
    filename = f"{stamp}.{kind}.zip"
    entry = f"{len(archive)} {hashlib.md5(archive).hexdigest()} http://data.gdeltproject.org/gdeltv2/{filename}"
    return parse_manifest(entry)[kind.split(".")[0]]


def test_manifest_parses_three_datasets_and_only_upgrades_exact_host():
    data = payload([event_row()])
    name = f"{len(data)} {hashlib.md5(data).hexdigest()}"
    result = parse_manifest("\n".join(
        f"{name} http://data.gdeltproject.org/gdeltv2/{STAMP}.{kind}.zip"
        for kind in ("export.CSV", "mentions.CSV", "gkg.csv")
    ))
    assert set(result) == {"export", "mentions", "gkg"}
    assert all(v.url.startswith("http://data.gdeltproject.org/gdeltv2/") for v in result.values())
    assert result["export"].timestamp == STAMP


@pytest.mark.parametrize("suffix", [
    "data.gdeltproject.org.attacker.net/gdeltv2/" + STAMP + ".export.CSV.zip",
    "data.gdeltproject.org:1234/gdeltv2/" + STAMP + ".export.CSV.zip",
    "evil:data.gdeltproject.org/gdeltv2/" + STAMP + ".export.CSV.zip",
    "data.gdeltproject.org/gdeltv2/../" + STAMP + ".export.CSV.zip",
    "data.gdeltproject.org/gdeltv2/" + STAMP + ".export.CSV.zip?q=secret",
    "user:pass@data.gdeltproject.org/gdeltv2/" + STAMP + ".export.CSV.zip",
])
def test_manifest_denies_untrusted_url_shapes(suffix):
    with pytest.raises(GdeltBatchError):
        parse_manifest(f"100 {'f' * 32} http://{suffix}")


def test_manifest_denies_duplicate_kind_and_non_quarter_hour():
    line = f"100 {'f' * 32} http://data.gdeltproject.org/gdeltv2/{STAMP}.export.CSV.zip"
    with pytest.raises(GdeltBatchError, match="Duplicate"):
        parse_manifest(line + "\n" + line)
    with pytest.raises(GdeltBatchError, match="15-minute"):
        parse_manifest(line.replace(STAMP, "20261111080100"))


def test_import_records_provenance_without_automatic_map_or_article_fetch(tmp_path):
    archive = payload([event_row()])
    batch = batch_from_archive(archive)
    with GdeltBatchCache(tmp_path / "existing.sqlite3") as cache:
        result = cache.import_export(batch, archive, now="2026-11-11T08:05:00+00:00")
        assert result == {"status": "complete", "filename": batch.filename, "seen": 1,
                          "added": 1, "rejected": 0, "duplicates": 0}
        row = cache.connection.execute(
            "SELECT global_event_id,event_code,action_country_code,action_latitude,"
            "action_longitude,source_article_url FROM gdelt_event_rows").fetchone()
        assert row == ("1001", "043", "US", 61.2181, -149.9003, "https://example.org/story")
        assert cache.status()["latest_batch"]["status"] == "complete"
        assert cache.status()["latest_batch"]["timestamp"] == STAMP


def test_complete_batch_is_never_reimported_even_after_restart(tmp_path):
    db = tmp_path / "archive.sqlite3"
    raw = payload([event_row()])
    batch = batch_from_archive(raw)
    with GdeltBatchCache(db) as cache:
        assert cache.import_export(batch, raw)["added"] == 1
    with GdeltBatchCache(db) as cache:
        assert cache.is_complete(batch)
        assert cache.import_export(batch, b"do not download again")["status"] == "already_imported"
        assert cache.status()["cached_rows"] == 1


def test_dedupe_repeated_upstream_global_event_id_across_batches(tmp_path):
    raw1 = payload([event_row("999")])
    raw2 = payload([event_row("999"), event_row("1000")], stamp="20261111081500")
    with GdeltBatchCache(tmp_path / "db") as cache:
        assert cache.import_export(batch_from_archive(raw1), raw1)["added"] == 1
        result = cache.import_export(batch_from_archive(raw2, stamp="20261111081500"), raw2)
        assert (result["seen"], result["added"], result["duplicates"]) == (2, 1, 1)
        assert cache.status()["cached_rows"] == 2


@pytest.mark.parametrize("bad", [
    event_row(event_code=""),
    event_row(day="20261399"),
    event_row(url="javascript:alert(1)"),
    event_row(url="https://user:secret@example.org/story"),
    event_row().split("\t")[0],
])
def test_invalid_rows_are_rejected_not_fabricated(tmp_path, bad):
    raw = payload([bad, event_row("1002")])
    with GdeltBatchCache(tmp_path / "db") as cache:
        result = cache.import_export(batch_from_archive(raw), raw)
        assert (result["seen"], result["added"], result["rejected"]) == (2, 1, 1)


def test_bad_checksum_fails_atomically_and_retry_can_succeed(tmp_path):
    raw = payload([event_row()])
    batch = batch_from_archive(raw)
    with GdeltBatchCache(tmp_path / "db") as cache:
        with pytest.raises(GdeltBatchError, match="digest mismatch"):
            cache.import_export(batch, raw[:-1] + bytes([raw[-1] ^ 0x01]))
        assert cache.status()["latest_batch"]["status"] == "error"
        assert cache.status()["cached_rows"] == 0
        assert cache.import_export(batch, raw)["status"] == "complete"
        assert cache.status()["cached_rows"] == 1


def test_archive_size_limit_is_enforced_without_any_import(tmp_path):
    raw = payload([event_row()])
    batch = batch_from_archive(raw)
    with GdeltBatchCache(tmp_path / "db") as cache:
        with pytest.raises(GdeltBatchError, match="size limit"):
            cache.import_export(batch, b"x" * (MAX_ARCHIVE_BYTES + 1))
        assert cache.status()["cached_rows"] == 0


def test_zip_path_traversal_rejected_without_extracting_files(tmp_path):
    raw = payload([event_row()], name="../evil.txt")
    batch = batch_from_archive(raw)
    with GdeltBatchCache(tmp_path / "db") as cache:
        with pytest.raises(GdeltBatchError, match="unexpected member"):
            cache.import_export(batch, raw)
    assert not (tmp_path / "evil.txt").exists()


def test_row_quota_failure_rolls_back_entire_batch_and_retry_recovers(tmp_path):
    raw = payload([event_row("1"), event_row("2")])
    batch = batch_from_archive(raw)
    db = tmp_path / "database.sqlite3"
    with GdeltBatchCache(db, max_rows=1) as cache:
        with pytest.raises(GdeltBatchError, match="row cap"):
            cache.import_export(batch, raw)
        assert cache.status()["cached_rows"] == 0
        assert cache.status()["latest_batch"]["status"] == "error"
    with GdeltBatchCache(db, max_rows=3) as cache:
        assert cache.import_export(batch, raw)["added"] == 2


def test_prune_does_not_delete_checkpoint_or_unrelated_application_data(tmp_path):
    db = tmp_path / "shared.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE events_kept_by_app(id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO events_kept_by_app VALUES('starred-not-owned-by-gdelt')")
    raw = payload([event_row()])
    batch = batch_from_archive(raw)
    with GdeltBatchCache(db) as cache:
        cache.import_export(batch, raw)
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        assert cache.prune(retention_days=7, now=now) == 1
        assert cache.status()["cached_rows"] == 0
        assert cache.is_complete(batch)
        assert cache.import_export(batch, raw)["status"] == "already_imported"
        assert cache.connection.execute("SELECT id FROM events_kept_by_app").fetchone()[0] == "starred-not-owned-by-gdelt"


def test_unsupported_mentions_gkg_not_misrepresented_as_ingested(tmp_path):
    raw = payload([event_row()])
    kind = batch_from_archive(raw, kind="mentions.CSV")
    with GdeltBatchCache(tmp_path / "db") as cache:
        with pytest.raises(GdeltBatchError, match="Only GDELT EXPORT"):
            cache.import_export(kind, raw)
        assert cache.status()["cached_rows"] == 0


def test_parallel_cache_connections_do_not_reserve_same_archive(tmp_path):
    db = tmp_path / "db.sqlite3"
    raw = payload([event_row()])
    batch = batch_from_archive(raw)
    t0 = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
    with GdeltBatchCache(db) as one, GdeltBatchCache(db) as two:
        assert one.reserve(batch, now=t0)
        assert not two.reserve(batch, now=t0 + timedelta(seconds=10))
        assert one.status()["latest_batch"]["status"] == "downloading"
        # Abandoned lease expires deterministically without erasing evidence.
        assert two.reserve(batch, now=t0 + timedelta(minutes=4))
        assert two.import_export(batch, raw)["status"] == "complete"
        assert not one.reserve(batch, now=t0 + timedelta(hours=3))
        assert one.is_complete(batch)


def test_failed_download_releases_lease_and_preserves_error_for_restart(tmp_path):
    db = tmp_path / "db.sqlite3"
    raw = payload([event_row()])
    batch = batch_from_archive(raw)
    with GdeltBatchCache(db) as cache:
        assert cache.reserve(batch)
        cache.record_fetch_error(batch, "GDELT endpoint returned HTTP 429")
        assert cache.status()["latest_batch"]["error"] == "GDELT endpoint returned HTTP 429"
        assert cache.reserve(batch)
        assert cache.import_export(batch, raw)["status"] == "complete"
        cache.record_fetch_error(batch, "GDELT endpoint returned HTTP 429")
        assert cache.status()["latest_batch"]["status"] == "complete"
    with GdeltBatchCache(db) as reopened:
        assert reopened.is_complete(batch)


def test_parallel_lease_database_migration_works_on_old_table(tmp_path):
    db = tmp_path / "old.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE gdelt_batches(filename TEXT PRIMARY KEY, kind TEXT, batch_timestamp TEXT, source_url TEXT, advertised_bytes INTEGER, advertised_md5 TEXT, status TEXT, imported_at TEXT, records_seen INTEGER DEFAULT 0, records_added INTEGER DEFAULT 0, records_rejected INTEGER DEFAULT 0, records_duplicate INTEGER DEFAULT 0, error TEXT DEFAULT '', parser_version INTEGER DEFAULT 1)")
    with GdeltBatchCache(db) as cache:
        assert "lease_until" in {row[1] for row in cache.connection.execute("PRAGMA table_info(gdelt_batches)")}


@pytest.mark.parametrize("path", [
    "data.gdeltproject.org:invalid/gdeltv2/" + STAMP + ".export.CSV.zip",
    "data.gdeltproject.org:99999/gdeltv2/" + STAMP + ".export.CSV.zip",
    "[bad-ipv6/gdeltv2/" + STAMP + ".export.CSV.zip",
])
def test_malformed_manifest_port_and_ipv6_cannot_escape_boundary(path):
    with pytest.raises(GdeltBatchError):
        parse_manifest(f"100 {'f' * 32} http://{path}")


def test_huge_manifest_decimal_is_rejected_before_integer_conversion():
    with pytest.raises(GdeltBatchError):
        parse_manifest(f"{'9'*5000} {'f'*32} http://data.gdeltproject.org/gdeltv2/{STAMP}.export.CSV.zip")


def test_csv_field_limit_is_atomic_structured_error(tmp_path):
    import csv
    oversized = event_row("2").split("\t")
    oversized[52] = "x" * (csv.field_size_limit() + 1)
    raw = payload([event_row("1"), "\t".join(oversized)])
    with GdeltBatchCache(tmp_path / "db") as cache:
        with pytest.raises(GdeltBatchError):
            cache.import_export(batch_from_archive(raw), raw)
        assert cache.status()["cached_rows"] == 0
        assert cache.status()["latest_batch"]["status"] == "error"


def test_retry_new_archive_identity_never_leaves_obsolete_digest(tmp_path):
    first = payload([event_row("1")])
    second = payload([event_row("222")])
    initial = batch_from_archive(first)
    corrected = batch_from_archive(second)
    assert initial.filename == corrected.filename
    assert initial.advertised_md5 != corrected.advertised_md5
    with GdeltBatchCache(tmp_path / "db") as cache:
        with pytest.raises(GdeltBatchError):
            cache.import_export(initial, b"damaged")
        assert cache.import_export(corrected, second)["status"] == "complete"
        recorded = cache.connection.execute(
            "SELECT advertised_bytes,advertised_md5 FROM gdelt_batches WHERE filename=?",
            (corrected.filename,),
        ).fetchone()
        assert recorded == (len(second), corrected.advertised_md5)
