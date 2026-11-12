"""Regression for QA 6781746041: installation is not notification consent.

The installer contract uses Inno's informational page rather than its mandatory
agreement page. Runtime tests execute the exact committed begin() AST with inert
collaborators; they do not claim a physical Windows desktop observation.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from global_pulse import distribution_terms as terms

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INFO = r"{#PackageRoot}\notifications\licenses\windows-sdk\SDK_TERMS.txt"


def directives(text, section):
    current = None
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].casefold()
            continue
        if current == section.casefold() and "=" in line:
            key, value = line.split("=", 1)
            key = key.strip().casefold()
            assert key not in result, "Duplicate installer directive"
            result[key] = value.strip()
    return result


def test_installer_discloses_unchanged_component_terms_without_application_gate():
    source = (ROOT / "packaging/GlobalPulse.iss").read_text(encoding="utf-8")
    setup = directives(source, "Setup")
    assert setup["infobeforefile"] == EXPECTED_INFO
    assert "licensefile" not in setup
    assert setup["privilegesrequired"] == "lowest"
    assert "[Code]" not in source
    assert terms.SETTING not in source
    assert "--accept" not in source


def test_one_shot_generator_cannot_reintroduce_application_license_gate():
    tree = ast.parse((ROOT / "scripts/prepare_compliance_candidate.py").read_text(encoding="utf-8"))
    edits = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "replace" and len(node.args) >= 3
             and isinstance(node.args[0], ast.Constant)
             and node.args[0].value == "packaging/GlobalPulse.iss"]
    assert len(edits) == 1
    replacement = ast.literal_eval(edits[0].args[2])
    setup = directives(replacement, "Setup")
    assert setup == {"infobeforefile": EXPECTED_INFO}


def run_exact_startup(monkeypatch, *, accepted, no_start=False,
                      skip_setup=True, onboarding_answer=True):
    source = (ROOT / "global_pulse/__main__.py").read_text(encoding="utf-8")
    functions = [node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.FunctionDef) and node.name == "begin"]
    assert len(functions) == 1
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    events = []
    controller = SimpleNamespace(
        start=lambda: events.append("news-start"),
        get_setting=lambda key, default=None: default,
    )
    notifier = SimpleNamespace(
        start=lambda: events.append("notification-start"),
        status_changed=SimpleNamespace(emit=lambda text: events.append(("status", text))),
    )
    def decide(actual_controller, parent):
        assert actual_controller is controller
        events.append("component-consent")
        return accepted
    def onboard(actual_controller, parent):
        assert actual_controller is controller
        events.append("onboarding")
        return onboarding_answer
    monkeypatch.setattr(terms, "accept_windows_sdk_terms", decide)
    namespace = {"__package__": "global_pulse", "controller": controller,
                 "window": object(), "notifier": notifier,
                 "args": SimpleNamespace(no_start=no_start, skip_setup=skip_setup),
                 "onboarding": onboard}
    exec(compile(module, "<exact-committed-begin>", "exec"), namespace)
    namespace["begin"]()
    return events


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("no_start", [False, True])
def test_notification_decision_is_independent_of_news_and_pause(monkeypatch, accepted, no_start):
    events = run_exact_startup(monkeypatch, accepted=accepted, no_start=no_start)
    assert events[0] == "component-consent"
    assert ("notification-start" in events) is accepted
    assert ("news-start" in events) is (not no_start)
    if not accepted:
        assert any(isinstance(event, tuple) and "not accepted" in event[1] for event in events)


@pytest.mark.parametrize("onboarding_answer", [False, True])
def test_declining_component_terms_does_not_skip_or_override_news_onboarding(monkeypatch, onboarding_answer):
    events = run_exact_startup(monkeypatch, accepted=False, skip_setup=False,
                               onboarding_answer=onboarding_answer)
    assert "onboarding" in events
    assert "notification-start" not in events
    assert ("news-start" in events) is onboarding_answer
