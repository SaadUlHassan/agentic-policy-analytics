"""The live-evaluation scorer on a stored run: it re-verifies what the run kept and catches tampering."""

from __future__ import annotations

import copy
import json

import pytest

from app.analytics.tools import Toolkit
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.connectors.registry import fetch
from app.core.config import get_settings
from app.data.taxonomy import get_taxonomy
from app.db.models import AnalysisStatus
from app.evaluation import live
from app.evaluation.accuracy import run_spec
from app.evaluation.golden import golden, golden_series
from app.evaluation.harness import RunResult
from app.evaluation.resilience import _outage_late
from app.evaluation.scoring import check_retained, load, score
from app.grounding.contracts import Claim
from app.grounding.render import render_claim
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
    assert scored["refusal_problems"] == ["R01: ict_vacancies_annual_average not selected"]


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


def _copy(stored):
    out = copy.copy(stored)
    out.analysis = copy.copy(stored.analysis)
    out.report = copy.deepcopy(stored.report)
    out.computations = {k: c.model_copy(deep=True) for k, c in stored.computations.items()}
    out.events = [copy.copy(e) for e in stored.events]
    for e in out.events:
        e.detail = copy.deepcopy(e.detail)
    return out


def _rerender(stored) -> None:
    """Make tampered values read consistently everywhere text is checked, as a careful forger would."""
    for finding in stored.report["findings"]:
        text = render_claim(Claim.model_validate(finding["claim"]), stored.computations)
        finding["text"] = text
        for e in stored.events:
            if e.type == "claim_verdict" and e.detail.get("claim_id") == finding["id"]:
                e.detail["rendered"] = text


async def test_wrong_arithmetic_on_a_republication_is_a_mismatch(stored):
    tampered = _copy(stored)
    on_mirror = next(c for c in tampered.computations.values() if c.tool == "change_between")
    assert on_mirror.inputs[0].dataset_id.startswith("d_")  # Data.gov.sg's copy of M184071
    on_mirror.result["pct_change"].value = 10000.0
    _rerender(tampered)

    scored = score(tampered, _expect("G01"), await golden_series(), None)

    assert scored["retained_failures"] == []  # the forgery is self-consistent...
    assert any("result differs when recomputed" in m for m in scored["computation_mismatches"])


async def test_a_computation_must_carry_its_fetched_series_identity(stored):
    tampered = _copy(stored)
    cagr = next(c for c in tampered.computations.values() if c.tool == "cagr")
    cagr.inputs[0].identity = cagr.inputs[0].identity.model_copy(update={"sector_label": "Manufacturing"})
    _rerender(tampered)

    scored = score(tampered, _expect("G01"), await golden_series(), None)

    assert any("inputs differs when recomputed" in m for m in scored["computation_mismatches"])


async def test_every_stored_computation_of_a_real_run_recomputes_exactly(stored):
    assert stored.computations
    assert score(stored, _expect("G01"), await golden_series(), None)["computation_mismatches"] == []


async def test_a_chart_must_state_its_series_unit_and_scale(stored):
    tampered = _copy(stored)
    chart = next(c for c in tampered.report["charts"] if c["scale"] == 1000)
    chart["scale"] = 1  # the same points would now read as persons, not thousands
    assert any("unit or scale differ" in f for f in check_retained(tampered))


async def test_a_failed_run_fails_its_gates(stored, tmp_path):
    failed = _copy(stored)
    failed.analysis.status, failed.analysis.error, failed.analysis.plan = (
        AnalysisStatus.FAILED,
        {"code": "LLM_UNAVAILABLE"},
        None,
    )
    failed.report, failed.events, failed.calls, failed.computations, failed.datasets = None, [], [], {}, {}

    scored = score(failed, _expect("G03"), await golden_series(), None)

    assert not scored["completed"]
    assert scored["refusal_problems"] == ["no verified finding for a question the data can answer"]
    record = {"query_id": "G03", "order": "bedrock", "run": 0, "analysis_id": "a", "clarification": None}
    (tmp_path / "runs.jsonl").write_text(json.dumps({**record, "score": scored}) + "\n")
    assert not live.summarise(tmp_path)["gates"]["runs_completed"]


async def _with_golden_selection(stored, names: list[str]):
    """The stored run as if it had selected these golden series (fetched from the snapshots)."""
    out, series = _copy(stored), await golden_series()
    fetcher = Fetcher(mode="snapshot", snapshots=get_snapshot_store())
    out.datasets = dict(stored.datasets)
    selected = []
    for name in names:
        source, _ = series[name]
        dataset = await fetch(source.dataset_id, get_catalog(), get_taxonomy(), fetcher)
        out.datasets[dataset.artifact_id] = dataset
        selected.append({"artifact_id": dataset.artifact_id, "series_key": source.series_key})
    await fetcher.aclose()
    out.report["evidence"]["selected"] = selected
    return out, series


async def test_a_required_refusal_must_be_for_the_requested_window_and_lag(stored):
    run, series = await _with_golden_selection(stored, ["ict_vacancies", "ict_employment_change"])
    spec = golden()["refusals"]["R02"]  # lag 1 over 2022-Q1..2024-Q4: 11 pairs
    genuine = run_spec(Toolkit(get_taxonomy().version), spec, series)
    other_request = genuine.model_copy(update={"params": {"start": "2020-Q1", "end": "2021-Q4", "lag": "0"}})

    run.report["evidence"]["refusals"] = [other_request.model_dump(mode="json")]
    assert not score(run, {"in_scope": True, "refusals": ["R02"]}, series, None)["refusal_correct"]

    run.report["evidence"]["refusals"] = [genuine.model_dump(mode="json")]
    assert score(run, {"in_scope": True, "refusals": ["R02"]}, series, None)["refusal_correct"]


async def test_a_late_outage_report_must_have_no_narrative(stored):
    report = _copy(stored)
    report.analysis.status = AnalysisStatus.COMPLETED_WITH_LIMITATIONS
    report.report["verification"]["narrative_note"] = "narrative unavailable; findings are shown as verified"
    report.report["limitations"].append(
        {
            "source": "system",
            "text": "Analysis stopped early (LLM_UNAVAILABLE); only verified findings are shown.",
        }
    )
    late = RunResult(report.analysis.id, late_faults_after_seq=1)
    assert any("generated title or summary" in p for p in _outage_late(report, late))

    report.report |= {"summary": "", "title": report.analysis.query}
    report.report["limitations"] = [
        lim for lim in report.report["limitations"] if lim["source"] != "coordinator"
    ]
    report.report["verification"].pop("narrative_check", None)
    assert _outage_late(report, late) == []


async def test_unknown_token_usage_makes_live_cost_unknown(stored, monkeypatch):
    scored = score(stored, _expect("G01"), await golden_series(), None)
    assert scored["usage"]["calls_without_usage"]  # scripted replies report no usage
    models = scored["usage"]["by_model"]
    monkeypatch.setattr(get_settings(), "llm_prices", {m: (1.0, 2.0) for m in models})

    cost = live._cost([{"score": scored}])

    assert cost["priced"] is False and cost["usd"] is None


async def test_a_run_that_could_not_be_scored_fails_runs_completed(stored, tmp_path):
    scored = score(stored, _expect("G01"), await golden_series(), None)
    record = {"query_id": "G01", "order": "bedrock", "analysis_id": "a", "clarification": None}
    unscored = {**record, "run": 1, "analysis_id": "b", "scoring_error": "KeyError: missing artifact"}
    (tmp_path / "runs.jsonl").write_text(
        json.dumps({**record, "run": 0, "score": scored}) + "\n" + json.dumps(unscored) + "\n"
    )

    summary = live.summarise(tmp_path)

    assert summary["unscored"] == ["b"]
    assert not summary["gates"]["runs_completed"] and not summary["hard_gates_passed"]

    # Nothing scorable at all, next to a passing resilience phase, still fails.
    (tmp_path / "runs.jsonl").write_text(json.dumps(unscored) + "\n")
    (tmp_path / "resilience.json").write_text(json.dumps([{"name": "s", "passed": True}]))
    summary = live.summarise(tmp_path)
    assert summary["gates"] == {"runs_completed": False, "provider_resilience": True}
    assert not summary["hard_gates_passed"]


async def test_a_redo_replaces_only_runs_the_ledger_shows_an_account_outage_spoiled(
    sessions, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from app.db.models import LLMCall
    from tests.integration.test_lifecycle import _new

    golden_run, _ = await _new(sessions)
    spoiled, _ = await _new(sessions)
    failed_otherwise, _ = await _new(sessions)
    async with sessions() as session:
        for analysis_id, error in [
            # As the ledger keeps it: cut at 200 characters, before OpenAI's error code.
            (
                spoiled,
                "OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'You have no credits "
                "remaining. Add credits to continue using the API at https://platform.openai.com/settings/organizati",
            ),
            (failed_otherwise, "TimeoutError: no reply"),  # a product-side failure stays as it was
        ]:
            session.add(
                LLMCall(
                    analysis_id=analysis_id,
                    agent="analytics",
                    purpose="react_step",
                    provider="openai",
                    model="gpt-5.5",
                    ok=False,
                    latency_ms=1,
                    error=error,
                )
            )
        await session.commit()
    records = [
        {"query_id": "G01", "order": "bedrock", "run": 0, "analysis_id": golden_run, "clarification": None},
        {"query_id": "G01", "order": "openai", "run": 1, "analysis_id": spoiled, "clarification": None},
        {
            "query_id": "G02",
            "order": "openai",
            "run": 2,
            "analysis_id": failed_otherwise,
            "clarification": None,
        },
    ]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    async def fresh(env, series, query, order, index):
        return {
            "query_id": query["id"],
            "order": order,
            "run": index,
            "analysis_id": "fresh",
            "clarification": None,
        }

    monkeypatch.setattr(live, "_golden_run", fresh)
    replaced_golden = await live.redo_phase(SimpleNamespace(sessions=sessions), {}, tmp_path, concurrency=1)

    after = [json.loads(line) for line in (tmp_path / "runs.jsonl").read_text().splitlines()]
    assert not replaced_golden
    assert [r["analysis_id"] for r in after] == [golden_run, "fresh", failed_otherwise]
    assert after[1]["replaces"] == {"analysis_id": spoiled, "reason": live.REDO_REASON}
    assert "replaces" not in after[0] and "replaces" not in after[2]


async def test_an_account_outage_is_reported_as_not_evaluated_never_as_a_pass(stored, tmp_path):
    good = score(stored, _expect("G01"), await golden_series(), None)
    spoiled = {**good, "account_outage": True, "completed": False, "retained_failures": ["k1: text differs"]}
    record = {"query_id": "G01", "order": "bedrock", "analysis_id": "a", "clarification": None}
    (tmp_path / "runs.jsonl").write_text(
        json.dumps({**record, "run": 0, "score": good})
        + "\n"
        + json.dumps({**record, "run": 1, "analysis_id": "b", "score": spoiled})
        + "\n"
    )

    summary = live.summarise(tmp_path)

    assert summary["not_evaluated"]["runs"] == [{"query": "G01", "order": "bedrock", "run": 1}]
    assert not summary["complete"]
    assert summary["gates"]["runs_completed"]  # the spoiled run does not count either way...
    assert not summary["gates"]["retained_claim_correctness"]  # ...but what it stored is still checked
    assert "Incomplete: not evaluated" in live.markdown(summary)


def _with(good: dict, **changes) -> dict:
    return {**good, **changes, "usage": {**good["usage"], **changes.get("usage", {})}}


async def test_excluded_runs_still_count_for_cost_and_stored_correctness(stored, tmp_path, monkeypatch):
    good = score(stored, _expect("G01"), await golden_series(), None)
    metered = {"by_model": {"m": [1_000_000, 0]}, "calls_without_usage": 0}
    spoiled = _with(good, account_outage=True, retained_failures=["k1: text differs"], usage=metered)
    record = {"query_id": "G01", "order": "bedrock", "run": 0, "analysis_id": "a", "clarification": None}
    (tmp_path / "runs.jsonl").write_text(json.dumps({**record, "score": spoiled}) + "\n")
    scenario = {
        "name": "s",
        "expected": "e",
        "passed": True,
        "status": "completed",
        "answered_by": ["bedrock"],
    }
    (tmp_path / "resilience.json").write_text(json.dumps([scenario]))
    monkeypatch.setattr(get_settings(), "llm_prices", {"m": (1.0, 1.0)})

    summary = live.summarise(tmp_path)

    # Every run is excluded, yet what it stored is checked and what it generated is paid for.
    assert summary["gates"]["retained_claim_correctness"] is False and not summary["hard_gates_passed"]
    assert summary["cost"]["usd"] == 1.0
    assert "k1: text differs" in live.markdown(summary)


async def test_a_partly_unjudged_suite_leaves_the_evaluation_incomplete(tmp_path):
    results = [
        {"judge": "bedrock", "unjudged": 0, "recall": 1.0},
        {"judge": "openai", "unjudged": 1, "recall": 1.0},
    ]
    (tmp_path / "judge.json").write_text(json.dumps({"findings_shown": [], "results": results}))

    summary = live.summarise(tmp_path)

    assert not summary["complete"]
    assert summary["not_evaluated"]["judges"] == ["openai (1 of 34 sentences without a verdict)"]
