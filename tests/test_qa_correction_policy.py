"""Bounded GP-CORE-001 method tests; NOT Qt, SQLite, or native integration.

Compile the actual Controller._watched method from this checkout, not a duplicate
implementation. The integration companion imports the full controller separately.
"""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def watched():
    path = Path(__file__).resolve().parents[1] / "global_pulse" / "controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Controller")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_watched")
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = {}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["_watched"]


def event(severity="informational", **changes):
    result = {"id": "fictional-port", "severity": severity, "country": "Norland",
              "region": "North Atlantic", "category": "Infrastructure",
              "reports": [{"source_id": "authority"}]}
    result.update(changes)
    return result


def call(watched, current=None, prior=None, reason="Correction: material correction", **settings):
    receiver = SimpleNamespace(get_setting=lambda key, default=None: settings.get(key, default))
    return watched(receiver, current or event(), previous=prior, reason=reason)


@pytest.mark.parametrize("kind", ["Correction", "Retraction"])
@pytest.mark.parametrize("threshold", ["moderate", "high"])
def test_downgraded_notice_uses_prior_significance(watched, kind, threshold):
    assert call(watched, prior=event("high"), reason=f"{kind}: material source notice",
                alert_threshold=threshold)


@pytest.mark.parametrize("reason", [None, "", "Official announcement: updated", "Developing event: update", "Not a correction", 1])
def test_ordinary_update_does_not_inherit_prior_significance(watched, reason):
    assert not call(watched, prior=event("critical"), reason=reason)


def test_unrelated_event_cannot_lend_significance(watched):
    assert not call(watched, prior=event("critical", id="unrelated"))


def test_missing_identity_cannot_lend_significance(watched):
    assert not call(watched, current=event(id=""), prior=event("critical", id=""))


def test_no_prior_remains_below_threshold(watched):
    assert not call(watched)


def test_previously_low_significance_stays_below_threshold(watched):
    assert not call(watched, prior=event())


def test_stricter_current_threshold_is_respected(watched):
    assert not call(watched, prior=event("high"), alert_threshold="critical")


@pytest.mark.parametrize("settings", [{"countries": ["Elsewhere"]},
    {"categories": ["Economy"]}, {"muted_sources": ["authority"]}])
def test_prior_significance_does_not_bypass_explicit_filters(watched, settings):
    assert not call(watched, prior=event("critical"), **settings)


@pytest.mark.parametrize("settings", [{"countries": ["norland"]},
    {"countries": ["NORTH ATLANTIC"]}, {"categories": ["Infrastructure"]}])
def test_matching_filters_keep_notice_eligible(watched, settings):
    assert call(watched, prior=event("high"), **settings)


def test_current_significance_remains_sufficient_without_prior(watched):
    assert call(watched, current=event("high"), reason="Official announcement: update")


def test_projection_with_no_prior_cannot_restore_muted_significance(watched):
    assert not call(watched, prior=None, muted_sources=["other-authority"])


def test_unknown_prior_rank_does_not_raise_significance(watched):
    assert not call(watched, prior=event("invalid"))


def test_inputs_are_not_mutated(watched):
    current, prior = event(), event("high")
    before = deepcopy((current, prior))
    assert call(watched, current=current, prior=prior)
    assert (current, prior) == before


def test_default_threshold_is_preserved(watched):
    assert not call(watched, current=event())
    assert call(watched, current=event("moderate"))


def test_real_ingestion_passes_projected_prior_and_validated_reason():
    path = Path(__file__).resolve().parents[1] / "global_pulse" / "controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Controller")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_reports")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "_watched"]
    assert len(calls) == 1
    assert ast.unparse(calls[0]) == "self._watched(event, previous=prior, reason=reason)"
    # This is a wiring assertion only; real ingestion is exercised by the
    # separately collected full-module integration companion.
