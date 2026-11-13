"""Offline HTTPX mocked checks for explicit GDELT manifest + export polling."""
import hashlib
import io
import zipfile

import httpx

from global_pulse.gdelt_batches import GdeltBatchCache
from global_pulse.gdelt_poll import poll_latest_export

STAMP = "20261111080000"


def archive_for(stamp):
    row = [""] * 61
    row[0] = stamp
    row[1] = "20261110"
    row[26] = "043"
    row[29] = "3"
    row[59] = stamp
    row[60] = "https://example.org/report"
    contents = ("\t".join(row) + "\n").encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(f"{stamp}.export.CSV", contents)
    return out.getvalue()


def manifest_for(stamp, contents, size=None):
    filename = f"{stamp}.export.CSV.zip"
    return (f"{len(contents) if size is None else size} {hashlib.md5(contents).hexdigest()} "
            f"http://data.gdeltproject.org/gdeltv2/{filename}\n").encode("ascii")


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_manifest_to_local_sqlite_without_any_article_download(tmp_path):
    raw = archive_for(STAMP)
    manifest = manifest_for(STAMP, raw)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if str(request.url).endswith("lastupdate.txt"):
            return httpx.Response(200, content=manifest)
        return httpx.Response(200, content=raw)

    with GdeltBatchCache(tmp_path / "pulse.sqlite3") as cache, make_client(handler) as client:
        result = poll_latest_export(cache, client=client)
        assert (result["status"], result["downloaded"], result["added"]) == ("complete", True, 1)
        assert cache.status()["cached_rows"] == 1
        assert len(calls) == 2
        assert calls[0] == "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
        assert calls[1].startswith("https://data.gdeltproject.org/gdeltv2/")
        assert not any("example.org" in url for url in calls)


def test_repeat_manifest_poll_does_not_redownload_or_reimport(tmp_path):
    raw = archive_for(STAMP)
    manifest = manifest_for(STAMP, raw)
    count = {"manifest": 0, "archive": 0}

    def handler(request):
        kind = "manifest" if str(request.url).endswith(".txt") else "archive"
        count[kind] += 1
        return httpx.Response(200, content=manifest if kind == "manifest" else raw)

    with GdeltBatchCache(tmp_path / "pulse.sqlite3") as cache, make_client(handler) as client:
        assert poll_latest_export(cache, client=client)["status"] == "complete"
        second = poll_latest_export(cache, client=client)
        assert second["status"] == "already_imported"
        assert not second["downloaded"]
        assert cache.status()["cached_rows"] == 1
        assert count == {"manifest": 2, "archive": 1}


def test_gap_after_missed_intervals_is_reported_not_falsely_backfilled(tmp_path):
    newer = "20261111084500"
    old_raw, new_raw = archive_for(STAMP), archive_for(newer)
    pointer = {"stamp": STAMP}

    def handler(request):
        stamp = pointer["stamp"]
        body = old_raw if stamp == STAMP else new_raw
        if str(request.url).endswith(".txt"):
            return httpx.Response(200, content=manifest_for(stamp, body))
        return httpx.Response(200, content=body)

    with GdeltBatchCache(tmp_path / "pulse.sqlite3") as cache, make_client(handler) as client:
        assert not poll_latest_export(cache, client=client)["gap_detected"]
        pointer["stamp"] = newer
        result = poll_latest_export(cache, client=client)
        assert result["gap_detected"]
        assert cache.status()["cached_rows"] == 2


def test_untrusted_manifest_cannot_trigger_archive_request(tmp_path):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text=(
            f"100 {'f'*32} https://attacker.example/gdeltv2/{STAMP}.export.CSV.zip"))

    with GdeltBatchCache(tmp_path / "db") as cache, make_client(handler) as client:
        result = poll_latest_export(cache, client=client)
        assert result["status"] == "error"
        assert requests == ["https://data.gdeltproject.org/gdeltv2/lastupdate.txt"]


def test_oversized_advertised_archive_is_never_requested(tmp_path):
    requests = []
    raw = archive_for(STAMP)

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=manifest_for(STAMP, raw, size=24 * 1024 * 1024 + 1))

    with GdeltBatchCache(tmp_path / "db") as cache, make_client(handler) as client:
        result = poll_latest_export(cache, client=client)
        assert result["status"] == "error"
        assert len(requests) == 1
        assert cache.status()["latest_batch"]["status"] == "error"


def test_archive_http_429_honors_retry_after_without_same_turn_repeat(tmp_path):
    calls = []
    raw = archive_for(STAMP)

    def handler(request):
        calls.append(str(request.url))
        if str(request.url).endswith(".txt"):
            return httpx.Response(200, content=manifest_for(STAMP, raw))
        return httpx.Response(429, headers={"Retry-After": "3600"})

    with GdeltBatchCache(tmp_path / "db") as cache, make_client(handler) as client:
        result = poll_latest_export(cache, client=client)
        assert result["status"] == "error"
        assert result["error"] == "GDELT endpoint returned HTTP 429"
        assert result["retry_after_seconds"] == 3600
        assert cache.status()["latest_batch"]["error"] == result["error"]
        assert len(calls) == 2


def test_transient_archive_404_retries_same_published_url_then_imports(tmp_path,monkeypatch):
    raw=archive_for(STAMP)
    calls=[]
    archive_attempt={"count":0}
    monkeypatch.setattr("global_pulse.gdelt_poll.time.sleep",lambda _seconds:None)

    def handler(request):
        calls.append(str(request.url))
        if str(request.url).endswith(".txt"):
            return httpx.Response(200,content=manifest_for(STAMP,raw))
        archive_attempt["count"]+=1
        if archive_attempt["count"]<3:
            return httpx.Response(404)
        return httpx.Response(200,content=raw)

    with GdeltBatchCache(tmp_path/"db") as cache, make_client(handler) as client:
        result=poll_latest_export(cache,client=client)
        assert result["status"]=="complete"
        assert result["added"]==1
        assert archive_attempt["count"]==3
        assert len(set(calls[1:]))==1


def test_latest_404_recovers_from_bounded_master_tail_with_independent_digest(tmp_path,monkeypatch):
    previous="20261111074500"
    latest=STAMP
    latest_raw=archive_for(latest)
    previous_raw=archive_for(previous)
    latest_manifest=manifest_for(latest,latest_raw)
    previous_line=manifest_for(previous,previous_raw).decode("ascii").strip()
    tail=("partial-old-line\n"+previous_line+"\n").encode("ascii")
    calls=[]
    monkeypatch.setattr("global_pulse.gdelt_poll.time.sleep",lambda _seconds:None)

    def handler(request):
        url=str(request.url)
        calls.append((url,request.headers.get("range")))
        if url.endswith("lastupdate.txt"):
            return httpx.Response(200,content=latest_manifest)
        if url.endswith(f"{latest}.export.CSV.zip"):
            return httpx.Response(404)
        if url.endswith("masterfilelist.txt"):
            start=100000
            end=start+len(tail)-1
            return httpx.Response(
                206,content=tail,
                headers={"Content-Range":f"bytes {start}-{end}/9999999",
                         "Content-Length":str(len(tail))}
            )
        if url.endswith(f"{previous}.export.CSV.zip"):
            return httpx.Response(200,content=previous_raw)
        raise AssertionError(url)

    with GdeltBatchCache(tmp_path/"db") as cache, make_client(handler) as client:
        result=poll_latest_export(cache,client=client)
        assert result["status"]=="complete"
        assert result["replication_pending"] is True
        assert result["recovered_from_master_list"] is True
        assert result["listed_batch_timestamp"]==latest
        assert result["batch_timestamp"]==previous
        assert result["added"]==1
        assert cache.status()["cached_rows"]==1
        master=[call for call in calls if call[0].endswith("masterfilelist.txt")]
        assert master==[("https://data.gdeltproject.org/gdeltv2/masterfilelist.txt","bytes=-65536")]


def test_redirect_to_nonapproved_domain_not_followed(tmp_path):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://attacker.example/collect"})

    with GdeltBatchCache(tmp_path / "db") as cache, make_client(handler) as client:
        result = poll_latest_export(cache, client=client)
        assert result["status"] == "error"
        assert "HTTP 302" in result["error"]
        assert len(calls) == 1


def test_bad_zip_does_not_set_success_checkpoint(tmp_path):
    fake = b"not a real ZIP file"
    manifest = manifest_for(STAMP, fake)
    def handler(request):
        return httpx.Response(200, content=manifest if str(request.url).endswith(".txt") else fake)
    with GdeltBatchCache(tmp_path / "db") as cache, make_client(handler) as client:
        result = poll_latest_export(cache, client=client)
        assert result["status"] == "error"
        assert cache.status()["latest_batch"]["status"] == "error"
        assert cache.status()["cached_rows"] == 0


def test_streaming_body_cap_denies_missing_content_length(tmp_path):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=b"x" * 8193)
    with GdeltBatchCache(tmp_path / "db") as cache, make_client(handler) as client:
        result = poll_latest_export(cache, client=client)
        assert result["status"] == "error"
        assert "size limit" in result["error"]
        assert len(requests) == 1


def test_concurrent_poll_leased_batch_does_not_issue_second_archive_get(tmp_path):
    raw = archive_for(STAMP)
    requests = []
    def handler(request):
        requests.append(str(request.url))
        if str(request.url).endswith(".txt"):
            return httpx.Response(200, content=manifest_for(STAMP, raw))
        raise AssertionError("An active SQLite download lease must suppress the archive request")
    from global_pulse.gdelt_batches import parse_manifest
    batch = parse_manifest(manifest_for(STAMP, raw))["export"]
    with GdeltBatchCache(tmp_path / "db") as cache, make_client(handler) as client:
        assert cache.reserve(batch)
        result = poll_latest_export(cache, client=client)
        assert result["status"] == "download_in_progress"
        assert not result["downloaded"]
        assert requests == ["https://data.gdeltproject.org/gdeltv2/lastupdate.txt"]


def test_unresolved_gaps_survive_replay_restart_and_newer_adjacent_batches(tmp_path):
    first = STAMP
    later = "20261111084500"
    adjacent = "20261111090000"
    db = tmp_path / "db"
    with GdeltBatchCache(db) as cache:
        for stamp in (first, later):
            raw = archive_for(stamp)
            with make_client(lambda req, raw=raw, stamp=stamp:
                httpx.Response(200, content=manifest_for(stamp, raw) if str(req.url).endswith(".txt") else raw)
            ) as client:
                result = poll_latest_export(cache, client=client)
                assert result["status"] == "complete"
        assert result["gap_detected"]
    with GdeltBatchCache(db) as cache:
        raw = archive_for(later)
        with make_client(lambda req: httpx.Response(
            200, content=manifest_for(later, raw) if str(req.url).endswith(".txt") else raw
        )) as client:
            replay = poll_latest_export(cache, client=client)
            assert replay["status"] == "already_imported"
            assert replay["gap_detected"]
        raw2 = archive_for(adjacent)
        with make_client(lambda req: httpx.Response(
            200, content=manifest_for(adjacent, raw2) if str(req.url).endswith(".txt") else raw2
        )) as client:
            next_result = poll_latest_export(cache, client=client)
            assert next_result["status"] == "complete"
            assert next_result["gap_detected"]


def test_latest_export_replication_lag_is_not_reported_current_after_restart(tmp_path, monkeypatch):
    """Real manifest -> 404 -> checksum-backed older EXPORT -> durable UI state.

    Retrying the same missing latest must retain 'replication pending', even
    when the fallback was already imported. Only importing the actual latest
    advertised export may restore CURRENT. No linked article is requested.
    """
    from global_pulse.gdelt_schedule import Schedule

    older = "20261111074500"
    latest = STAMP
    older_raw, latest_raw = archive_for(older), archive_for(latest)
    previous_line = manifest_for(older, older_raw).decode("ascii").strip()
    tail = ("partial-first-line\n" + previous_line + "\n").encode("ascii")
    visible = {"latest": False}
    calls = []
    monkeypatch.setattr("global_pulse.gdelt_poll.time.sleep", lambda _: None)

    def handler(request):
        url = str(request.url)
        calls.append(url)
        if url.endswith("lastupdate.txt"):
            return httpx.Response(200, content=manifest_for(latest, latest_raw))
        if url.endswith(f"{latest}.export.CSV.zip"):
            return httpx.Response(200, content=latest_raw) if visible["latest"] else httpx.Response(404)
        if url.endswith("masterfilelist.txt"):
            first = 90000
            return httpx.Response(206, content=tail,
                headers={"Content-Range": f"bytes {first}-{first + len(tail) - 1}/9999999"})
        if url.endswith(f"{older}.export.CSV.zip"):
            return httpx.Response(200, content=older_raw)
        raise AssertionError(f"Unexpected network destination: {url}")

    database = tmp_path / "global-pulse.sqlite3"
    with GdeltBatchCache(database) as cache, make_client(handler) as client:
        schedule = Schedule(database)
        for attempt_no in (0, 1):
            moment = 1794409200 + attempt_no * 900
            token = schedule.claim(now=moment, jitter=0)
            assert token
            result = poll_latest_export(cache, client=client)
            assert result["replication_pending"] is True
            assert result["listed_batch_timestamp"] == latest
            assert result["batch_timestamp"] == older
            assert result["status"] == ("complete" if attempt_no == 0 else "already_imported")
            result["cached_rows"] = cache.status()["cached_rows"]
            assert schedule.finish(token, result, now=moment)
            persisted = Schedule(database).status()  # fresh process / restart
            assert persisted["state"] == "replication_pending"
            assert persisted["last_batch"] == older
            assert persisted["last_success"] == moment
            assert persisted["cached_rows"] == 1
            assert persisted["gap"] == 0  # publication lag != proven missing interval

        visible["latest"] = True
        moment += 900
        token = Schedule(database).claim(now=moment, jitter=0)
        assert token
        result = poll_latest_export(cache, client=client)
        assert result["status"] == "complete" and not result.get("replication_pending")
        result["cached_rows"] = cache.status()["cached_rows"]
        assert Schedule(database).finish(token, result, now=moment)
        persisted = Schedule(database).status()
        assert persisted["state"] == "current"
        assert persisted["last_batch"] == latest
        assert persisted["cached_rows"] == 2
        assert not any("example.org" in url for url in calls)

