"""Issue64: bounded session-only headline-language reuse after measured Qt stalls.

These are offline Engineering checks; they never claim language inference for
the publisher, install models, upload articles or assert full Windows stability.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import global_pulse.headline_translation as module
from global_pulse.headline_translation import HeadlineTranslations


class Worker:
    def __init__(self):
        self.submitted = []

    def submit(self, *args):
        self.submitted.append(args)
        return True

    def cancel(self, *args):
        return True


def event(title, language="und"):
    return {
        "id": "route-check",
        "title": title,
        "reports": [{"id": "route-check-source",
                     "title": title,
                     "language": language,
                     "evidence_status": "active"}],
    }


def service(catalog=None):
    worker = Worker()
    installed = {"value": False}
    translator = SimpleNamespace(
        catalog=catalog or {},
        installed=lambda _code: installed["value"],
    )
    engine = HeadlineTranslations(translator, worker, lambda: True)
    return engine, worker, installed


def test_unchanged_unknown_source_language_is_identified_once(monkeypatch):
    title = "Inert source-language report without a declaration, no claims"
    calls = []
    def fake_language(text, declared):
        calls.append((text, declared))
        return "und"

    monkeypatch.setattr(module, "language_of", fake_language)
    engine, worker, _ = service()
    try:
        original = event(title)
        for _ in range(25):
            shown = engine.view(original)
            assert shown["title"] == title
            assert shown["original"] == title
            assert shown["state"] in {"unavailable", "original"}
            assert shown["label"] != "Original English headline"
        assert calls == [(title, "und")]
        assert len(engine.language_cache) == 1
        assert worker.submitted == []
        assert original["reports"][0]["title"] == title
    finally:
        engine.close()
    assert not engine.language_cache


def test_changed_title_or_declared_language_invalidates_only_routing(monkeypatch):
    calls = []
    def fake_language(text, declared):
        calls.append((text, declared))
        return "und" if declared == "und" else "en"

    monkeypatch.setattr(module, "language_of", fake_language)
    engine, worker, _ = service()
    try:
        title = "SYNTHETIC record with text long enough for language routing"
        engine.view(event(title, "und"))
        engine.view(event(title, "und"))
        engine.view(event(title, "en"))
        engine.view(event(title + " updated", "und"))
        engine.view(event(title, "und"))
        assert calls == [(title, "und"), (title, "en"), (title + " updated", "und")]
        assert len(engine.language_cache) == 3
        assert not worker.submitted
    finally:
        engine.close()


def test_route_cache_is_lru_bounded_and_evicts(monkeypatch):
    calls = []
    def fake_language(text, declared):
        calls.append(text)
        return "und"

    monkeypatch.setattr(module, "language_of", fake_language)
    engine, _, _ = service()
    try:
        engine.MAX_LANGUAGE_CACHE = 3
        titles = ["SYNTHETIC language route fixture %d with long text" % i for i in range(6)]
        for title in titles:
            engine.view(event(title))
        assert len(engine.language_cache) == 3
        assert all((title, "und") in engine.language_cache for title in titles[3:])
        engine.view(event(titles[0]))
        assert len(calls) == 7 and calls[-1] == titles[0]
        assert len(engine.language_cache) == 3
    finally:
        engine.close()


def test_installation_checked_live_after_cached_non_english_routing(monkeypatch):
    calls = []
    def fake_language(text, declared):
        calls.append((text, declared))
        return "es"

    monkeypatch.setattr(module, "language_of", fake_language)
    engine, worker, installed = service({
        "es": {"key": "spanish-pinned", "sha256": "a" * 64, "name": "Spanish"}
    })
    try:
        title = "SYNTHETIC Spanish headline with declared language and no evidence change"
        source = event(title, "es")
        missing = engine.view(source)
        assert missing["state"] == "missing_model"
        assert missing["title"] == title
        assert "install Spanish model" in missing["label"]
        assert worker.submitted == []
        installed["value"] = True
        pending = engine.view(source)
        assert pending["state"] == "pending"
        assert pending["title"] == title
        assert worker.submitted and worker.submitted[0][3] is False
        assert len(calls) == 1
        assert source["reports"][0]["title"] == title
    finally:
        engine.close()


def test_disabled_route_never_detects_or_submits(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("Disabled local English headlines must not identify language")
    monkeypatch.setattr(module, "language_of", forbidden)
    worker = Worker()
    translator = SimpleNamespace(catalog={}, installed=lambda _: False)
    engine = HeadlineTranslations(translator, worker, lambda: False)
    try:
        shown = engine.view(event("SYNTHETIC headline entirely untouched when disabled"))
        assert shown["state"] == "original"
        assert shown["title"] == shown["original"]
        assert not engine.language_cache and not worker.submitted
    finally:
        engine.close()
