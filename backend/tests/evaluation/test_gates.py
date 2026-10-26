"""Deterministic evaluation gates (plan §8.3): G3 claim validity, G5 calculation accuracy."""

from __future__ import annotations

import ast

import pytest

from app.analytics.results import Computation
from app.evaluation.__main__ import expectations_are_current
from app.evaluation.accuracy import check_computations, check_refusals
from app.evaluation.adversarial import (
    CONTROL,
    EXPECTED_CHECK,
    NARRATIVE_CONTROL,
    build_cases,
    evaluate,
    summarise,
)
from app.evaluation.golden import golden_dir, golden_series


@pytest.fixture
async def series():
    return await golden_series()


def test_expected_values_are_computed_without_the_application():
    tree = ast.parse((golden_dir().parent / "compute_expected.py").read_text())
    imported = {
        (node.module or "") if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in getattr(node, "names", [])
    }
    assert not {m for m in imported if m == "app" or m.startswith("app.")}
    assert not {"scipy", "statsmodels", "pandas"} & {m.split(".")[0] for m in imported}


def test_expected_values_are_current_for_the_snapshots():
    assert expectations_are_current(), "rerun eval/compute_expected.py"


async def test_every_golden_computation_matches_the_independent_values(series):
    checks = check_computations(series)
    failing = [
        f"{f.computation}.{f.field}: expected {f.expected}, got {f.actual}" for f in checks if not f.ok
    ]
    assert not failing and len({f.computation for f in checks}) == 12


async def test_every_golden_refusal_gives_its_reason_code(series):
    assert [(r.refusal, r.actual) for r in check_refusals(series)] == [
        ("R01", "REFERENCE_MISMATCH"),
        ("R02", "INSUFFICIENT_PAIRS"),
        ("R03", "NOT_A_LEVEL"),
        ("R04", "NOT_A_LEVEL"),
    ]


async def test_adversarial_suite_meets_the_planned_size(series):
    cases, _ = build_cases(series)
    controls = [c for c in cases if c.category == CONTROL]
    assert len(controls) >= 20 and len([c for c in cases if not c.valid]) >= 40
    assert set(EXPECTED_CHECK) == {c.category for c in cases if not c.valid}
    assert any(c.category == NARRATIVE_CONTROL for c in cases)


async def test_every_corruption_is_caught_by_the_rule_it_breaks(series):
    cases, computations = build_cases(series)
    missed = [
        f"{o.case.category}: {o.case.description} (fired {o.failed_checks})"
        for o in evaluate(cases, computations)
        if not o.case.valid and EXPECTED_CHECK[o.case.category] not in o.failed_checks
    ]
    assert not missed


async def test_valid_controls_pass_and_the_gate_holds(series):
    cases, computations = build_cases(series)
    summary = summarise(evaluate(cases, computations))
    assert summary["false_positives"] == [] and summary["gate_passed"]


# -- the gates fail when the thing they guard breaks -------------------------------------------------


def _mutating(monkeypatch, tool: str, mutate) -> None:
    from app.analytics.tools import Toolkit

    original = getattr(Toolkit, tool)

    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if isinstance(result, Computation):
            result = result.model_copy(deep=True)
            mutate(result)
        return result

    monkeypatch.setattr(Toolkit, tool, wrapped)


async def test_a_relative_error_above_tolerance_below_one_fails(monkeypatch, series):
    # r ~ 0.47: an absolute 1e-6 would pass this; the declared relative 1e-6 must not.
    _mutating(
        monkeypatch,
        "correlate",
        lambda c: setattr(c.result["pearson_r"], "value", c.result["pearson_r"].value + 8e-7),
    )
    failing = {(f.computation, f.field) for f in check_computations(series) if not f.ok}
    assert failing == {("C10", "pearson_r"), ("C11", "pearson_r")}


async def test_a_wrong_confidence_interval_fails(monkeypatch, series):
    _mutating(
        monkeypatch,
        "trend",
        lambda c: c.result.get("slope_ci_high") and setattr(c.result["slope_ci_high"], "value", 1e99),
    )
    failing = {(f.computation, f.field) for f in check_computations(series) if not f.ok}
    assert failing == {("C09", "slope_ci_high")}


async def test_a_right_number_in_the_wrong_scale_fails(monkeypatch, series):
    def thousands_dropped(c):
        for f in c.result.values():
            if f.scale == 1000:
                f.scale = 1  # "22.7 thousand persons" would render as "23 persons"

    _mutating(monkeypatch, "change_between", thousands_dropped)
    failing = [f for f in check_computations(series) if not f.ok]
    assert {f.computation for f in failing} == {"C01", "C04"}  # yoy_change is a change_between
    assert all(f.expected_unit == "persons x1000" and f.actual_unit == "persons x1" for f in failing)


async def test_an_extra_unexpected_field_fails(monkeypatch, series):
    _mutating(monkeypatch, "cagr", lambda c: c.result.update(extra=c.result["cagr_pct"]))
    failing = {(f.computation, f.field, f.tolerance) for f in check_computations(series) if not f.ok}
    assert failing == {("C02", "extra", "unexpected field"), ("C12", "extra", "unexpected field")}


async def test_a_rejection_by_the_wrong_rule_is_not_detection(monkeypatch, series):
    from app.evaluation import adversarial

    original = adversarial.verify_claim

    def causal_check_broken(claim, computations):
        verdict = original(claim, computations)
        checks = [
            c.model_copy(update={"passed": True}) if c.name == "no_causal_language" else c
            for c in verdict.checks
        ]
        return verdict.model_copy(update={"checks": checks, "passed": all(c.passed for c in checks)})

    monkeypatch.setattr(adversarial, "verify_claim", causal_check_broken)
    cases, computations = build_cases(series)
    summary = summarise(evaluate(cases, computations))

    # Still rejected (by safe_prose), but not by the causal check: the gate must notice.
    for category in ("causal_hedged", "causal_unhedged"):
        assert summary["categories"][category]["detected"] == 0
        assert len(summary["categories"][category]["misattributed"]) == 2
    assert not summary["gate_passed"]


def test_freshness_ignores_cross_platform_float_noise_but_not_real_changes():
    import copy
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location(
        "compute_expected", golden_dir().parent / "compute_expected.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    stored, fresh = json.loads((golden_dir() / "expected.json").read_text()), script.expected()

    noisy = copy.deepcopy(stored)
    noisy["computations"]["C09"]["fields"]["slope_ci_low"]["value"] *= 1 + 1e-14  # another BLAS
    assert script.matches(noisy, fresh)
    for path, value in ((("C01", "end_value", "value"), 999.0), (("C01", "end_value", "unit"), "vacancies")):
        changed = copy.deepcopy(stored)
        changed["computations"][path[0]]["fields"][path[1]][path[2]] = value
        assert not script.matches(changed, fresh), path
