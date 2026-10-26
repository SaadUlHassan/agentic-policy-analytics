"""Deterministic evaluation gates (plan §8.3): G3 claim validity, G5 calculation accuracy."""

from __future__ import annotations

import ast

import pytest

from app.evaluation.__main__ import expectations_are_current
from app.evaluation.accuracy import check_computations, check_refusals
from app.evaluation.adversarial import CONTROL, NARRATIVE_CONTROL, build_cases, evaluate, summarise
from app.evaluation.golden import golden_dir, golden_series

# The rule each corruption must be caught by: detection for the wrong reason is not detection.
EXPECTED_CHECK = {
    "wrong_computation_ref": "resolution",
    "wrong_metric": "metric_equality",
    "shorter_interval": "interval_equality",
    "longer_interval": "interval_equality",
    "level_as_change": "predicate_fit",
    "wrong_unit_or_field": "predicate_fit",
    "wrong_direction": "sign_rule",
    "association_strength": "strength_rule",
    "association_from_descriptive": "kind_allowed",
    "fabricated_literal": "no_free_numbers",
    "causal_unhedged": "no_causal_language",
    "causal_hedged": "no_causal_language",
    "tampered_lineage": "identity_equality",
    "parent_child_swap": "identity_equality",
    "recommendation_with_figures": "recommendation_has_no_figures",
    "narrative_fabricated_number": "no_free_numbers",
    "narrative_causal": "no_causal_language",
}


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
