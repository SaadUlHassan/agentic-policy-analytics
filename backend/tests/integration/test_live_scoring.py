"""The live-evaluation scorer on a stored run: it re-verifies what the run kept and catches tampering."""

from __future__ import annotations

import copy
import json

import pytest

from app.evaluation import live
from app.evaluation.golden import golden, golden_series
from app.evaluation.scoring import check_retained, load, score
from app.jobs.runner import execute
from app.llm.scripted import ScriptedChatModel
from tests.integration.test_analysis_graph import ALL_SUPPORTED, _happy_path_script, _settings, _start

pytestmark = pytest.mark.integration


@pytest.fixture
async def stored(sessions, database_url, checkpoints):
    analysis_id, intent = await _start(sessions)
    models = {
        "bedrock": ScriptedChatModel(replies=_happy_path_script()),
        "openai": ScriptedChatModel(replies=[ALL_SUPPORTED]),
    }
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models=models,
    )
    assert status == "completed"
    return await load(sessions, analysis_id)


def _expect(query_id: str) -> dict:
    return next(q for q in golden()["queries"] if q["id"] == query_id)["expect"]


async def test_a_verified_run_passes_every_retained_check(stored):
    assert stored.report["findings"] and all("claim" in f for f in stored.report["findings"])
    assert check_retained(stored) == []


@pytest.mark.parametrize(
    ("tamper", "failure"),
    [
        (lambda r: r["findings"][0].update(text="Employment fell sharply."), "text differs"),
        (
            lambda r: r["findings"][1]["claim"]["assertions"]["a1"]["interval"].update(start="2021-Q1"),
            "interval_equality",
        ),
        (lambda r: r["findings"][0].pop("claim"), "no stored claim"),
        (lambda r: r["findings"][0].update(citations=["S2"]), "citations do not match"),
        (lambda r: r.update(summary="Employment grew by 40,000 jobs."), "no_free_numbers"),
        (lambda r: r.update(summary="Vacancies rose due to strong demand."), "no_causal_language"),
        (lambda r: r["charts"][0]["series"][0]["points"][0].update(value=1.0), "points differ"),
    ],
)
async def test_tampered_reports_are_caught(stored, tamper, failure):
    tampered = copy.copy(stored)
    tampered.report = copy.deepcopy(stored.report)
    tamper(tampered.report)
    assert any(failure in f for f in check_retained(tampered))


async def test_a_mirror_selection_counts_as_the_golden_series(stored):
    series = await golden_series()
    scored = score(stored, _expect("G01"), series, None)
    # The run selected Data.gov.sg's quarterly vacancies, the mirror of SingStat's M184071.
    assert scored["selected"] == ["ict_employment_level", "ict_vacancies"]
    assert scored["identities_correct"] and scored["refusal_correct"]
    assert scored["golden_computations_found"] == ["C02", "C07"]
    assert scored["computation_mismatches"] == [] and scored["retained_failures"] == []
    # C07 was computed on the republication: compared in base units, not gated field by field.
    assert set(scored["republished_computations"]) == {"C07"}
    assert all(want == got for want, got in scored["republished_computations"]["C07"].values())
    assert scored["directions"] == {"C02.cagr_pct": "positive", "C07.pct_change": "positive"}
    assert scored["all_agents_decided"]


async def test_a_missing_expected_refusal_fails_refusal_correctness(stored):
    scored = score(stored, _expect("G06"), await golden_series(), None)
    assert not scored["refusal_correct"]
    assert scored["refusal_problems"] == [
        "R01: expected REFERENCE_MISMATCH on ['ict_employment_level', 'ict_vacancies_annual_average']"
    ]


async def test_an_answer_to_an_unanswerable_question_is_a_refusal_failure(stored):
    scored = score(stored, _expect("G10"), await golden_series(), None)
    assert not scored["refusal_correct"]
    assert any("out-of-domain" in p for p in scored["refusal_problems"])


async def test_summary_gates_need_every_query_on_both_orders(stored, tmp_path):
    scored = score(stored, _expect("G01"), await golden_series(), None)
    records = [
        {
            "query_id": "G01",
            "order": "bedrock",
            "run": i,
            "analysis_id": "a",
            "clarification": None,
            "score": scored,
        }
        for i in range(2)
    ]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    summary = live.summarise(tmp_path)

    assert summary["gates"]["retained_claim_correctness"] and summary["gates"]["live_computation_accuracy"]
    assert not summary["gates"]["refusal_correctness"]  # 1 of 12 queries, one provider order
    assert not summary["hard_gates_passed"]
    assert summary["consistency"]["per_query"]["G01"] == {
        "runs": 2,
        "jaccard": 1.0,
        "direction_conflicts": {},
    }
