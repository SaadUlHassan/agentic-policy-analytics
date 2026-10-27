"""Agent tools on real snapshot data, with an in-memory writer."""

from __future__ import annotations

import time

import pytest
import respx
from pydantic import ValidationError

from app.agents.context import AgentContext
from app.agents.plan import (
    ResearchPlan,
    align_period,
    cap_options,
    clarification_problems,
    shorten_question,
    validate_plan,
    vocabulary,
)
from app.agents.tools import analytics_tools, extraction_tools
from app.connectors import singstat
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, SnapshotStore, get_snapshot_store
from app.data.taxonomy import get_taxonomy
from app.grounding.checks import verify_claim

PLAN = ResearchPlan(
    intent="ICT",
    in_scope=True,
    sectors=["info_comms"],
    metrics=["job_vacancies"],
    start_year=2020,
    end_year=2024,
    rationale="test",
)
VACANCIES = "M184071:1.2.4@SSIC2020"


class MemoryWriter:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    async def emit(self, agent, type, title, detail=None):
        self.events.append((type, title, detail or {}))
        return len(self.events)

    async def save_artifact(self, dataset, payloads=()):
        pass

    async def save_computation(self, computation):
        pass


def _ctx() -> AgentContext:
    return AgentContext(
        router=None,
        writer=MemoryWriter(),
        catalog=get_catalog(),
        taxonomy=get_taxonomy(),  # type: ignore[arg-type]
        fetcher=Fetcher(mode="snapshot", snapshots=get_snapshot_store()),
        deadline=time.monotonic() + 60,
    )


def _tools(tools):
    return {t.name: t for t in tools}


async def test_selecting_a_mirrored_series_cross_checks_the_other_platform():
    ctx = _ctx()
    tools = _tools(extraction_tools(ctx, PLAN))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M184071", "rationale": "r"})

    reply = await tools["select_series"].ainvoke(
        {"series_key": VACANCIES, "reason": "fits", "rationale": "r"}
    )

    assert "cross-checked against d_3f17bbf67d31d4d402caa8755eb74afc (datagov): consistent" in reply
    (check,) = ctx.evidence.consistency
    assert len(check.periods) == 20 and check.mismatches == []
    assert {d.provenance.platform for d in ctx.evidence.datasets.values()} == {"singstat", "datagov"}


async def test_selection_outside_the_plan_is_refused():
    ctx = _ctx()
    tools = _tools(extraction_tools(ctx, PLAN))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M184071", "rationale": "r"})
    reply = await tools["select_series"].ainvoke(
        {"series_key": "M184071:1.2.4.2@SSIC2020", "reason": "subsector", "rationale": "r"}
    )
    assert reply.startswith("REFUSED by policy") and "it_info_services" in reply
    assert not ctx.evidence.selected


async def test_a_series_at_another_frequency_than_the_plan_asks_for_is_refused():
    # "Annual ICT job vacancies": the quarterly series measures the right thing at the wrong frequency.
    ctx = _ctx()
    tools = _tools(extraction_tools(ctx, PLAN.model_copy(update={"frequency": "annual"})))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M184071", "rationale": "r"})
    reply = await tools["select_series"].ainvoke(
        {"series_key": VACANCIES, "reason": "fits", "rationale": "r"}
    )
    assert reply.startswith("REFUSED by policy") and "the plan asks for annual figures" in reply
    assert not ctx.evidence.selected


def test_how_a_question_is_put_is_asked_to_be_fixed_but_never_refuses_it():
    asking = PLAN.model_copy(
        update={
            "sectors": [],
            "needs_clarification": True,
            "clarification_question": "Which sector? " + ", ".join(f"option {i}" for i in range(40)),
            "clarification_options": [f"option {i}" for i in range(15)],
        }
    )
    sectors, metrics = vocabulary(get_catalog(), get_taxonomy())
    # The sector is what it asks about, so its absence is not a vocabulary problem.
    assert validate_plan(asking, sectors, metrics) == []
    assert clarification_problems(asking) == [
        "offer at most 4 clarification options, not 15",
        "ask one short question; put the choices in clarification_options, not in the question",
    ]
    assert cap_options(asking).clarification_options == ["option 0", "option 1", "option 2", "option 3"]
    assert shorten_question(asking).clarification_question == "Which sector?"
    # Without a question, a missing sector is still a problem.
    assert validate_plan(PLAN.model_copy(update={"sectors": []}), sectors, metrics) == ["no sector chosen"]


@pytest.mark.parametrize(
    ("question", "planned", "aligned"),
    [
        ("Did growth weaken after mid-2022, compared with 2020 to mid-2022?", (2021, 2025), (2020, 2025)),
        ("Did growth weaken after mid-2022, compared with 2020 to mid-2022?", (2020, 2022), (2020, 2025)),
        ("How did employment change in 2023 compared with 2022?", (2022, 2023), (2022, 2023)),
        ("Employment from 2020 to 2024", (2019, 2023), (2020, 2024)),
        ("ICT employment under SSIC 2020 in 2023", (2023, 2023), (2023, 2023)),
        ("How is the sector doing?", (2021, 2025), (2021, 2025)),
        ("Employment from 2020 to 2024", (None, None), (2020, 2024)),
        ("Employment from 2020 to 2024", (2021, 2025), (2020, 2024)),  # a named end is kept, not widened
        ("ICT employment in the five years before 2020", (2015, 2019), (2015, 2019)),
        ("ICT employment before 2020", (None, None), (2015, 2019)),
        ("ICT employment under ssic 2020 in 2023", (2023, 2023), (2023, 2023)),
        # A before/after comparison keeps both sides; "after 2022" does not open a period ending in 2024.
        (
            "Compare ICT employment before 2022 with employment after 2022, using 2020 to 2024.",
            (2020, 2024),
            (2020, 2024),
        ),
        (
            "Compare ICT employment in 2020 to 2021 (before 2022) with 2022 to 2024.",
            (2020, 2024),
            (2020, 2024),
        ),
        ("ICT employment since 2020", (2020, 2023), (2020, 2025)),
        ("ICT employment from 2018 until 2020", (2018, 2020), (2018, 2020)),
    ],
)
def test_the_plan_period_covers_the_years_the_question_names(question, planned, aligned):
    plan = PLAN.model_copy(update={"start_year": planned[0], "end_year": planned[1]})
    result = align_period(plan, question, latest_year=2025)
    assert (result.start_year, result.end_year) == aligned
    assert (len(result.assumptions) > len(plan.assumptions)) == (aligned != planned)


async def test_draft_rules_refuse_digit_lead_ins_and_long_findings_before_verification():
    ctx = _ctx()
    await _tools(extraction_tools(ctx, PLAN))["fetch_dataset"].ainvoke(
        {"dataset_id": "M184071", "rationale": "r"}
    )
    await _tools(extraction_tools(ctx, PLAN))["select_series"].ainvoke(
        {"series_key": VACANCIES, "reason": "fits", "rationale": "r"}
    )
    tools = _tools(analytics_tools(ctx, PLAN))
    computed = await tools["compute"].ainvoke(
        {
            "tool": "change_between",
            "series_key": VACANCIES,
            "start": "2020-Q1",
            "end": "2024-Q4",
            "rationale": "r",
        }
    )
    assertion = {
        "predicate": "change.increase",
        "computation_id": computed["computation_id"],
        "field": "pct_change",
        "metric": "job_vacancies",
        "series_key": VACANCIES,
        "interval_start": "2020-Q1",
        "interval_end": "2024-Q4",
    }

    with pytest.raises(ValidationError):  # only allow-listed lead-ins exist in the schema
        await tools["draft_claim"].ainvoke(
            {"lead_in": "It is false that", "assertions": [assertion], "rationale": "r"}
        )
    too_many = await tools["draft_claim"].ainvoke(
        {"kind": "comparison", "assertions": [assertion] * 3, "rationale": "r"}
    )
    # No `kind`: models sometimes omit it, and it is inferred from the assertions.
    ok = await tools["draft_claim"].ainvoke({"assertions": [assertion], "rationale": "r"})
    duplicate = await tools["draft_claim"].ainvoke(
        {"kind": "comparison", "assertions": [assertion], "rationale": "r"}
    )

    assert too_many.startswith("TOO LONG")
    assert ok == (
        "VERIFIED k1: Job vacancies in Information & Communications rose by 21.7% "
        "between 2020-Q1 and 2024-Q4."
    )
    assert duplicate.startswith("DUPLICATE of k1")
    cagr = await tools["compute"].ainvoke(
        {"tool": "cagr", "series_key": VACANCIES, "start": "2020-Q1", "end": "2024-Q4", "rationale": "r"}
    )
    both = {
        **assertion,
        "predicate": "cagr.growth",
        "computation_id": cagr["computation_id"],
        "field": "cagr_pct",
    }
    combined = await tools["draft_claim"].ainvoke(
        {"kind": "comparison", "assertions": [assertion, both], "rationale": "r"}
    )
    restated = await tools["draft_claim"].ainvoke(
        {"kind": "comparison", "assertions": [both], "rationale": "r"}
    )
    assert combined.startswith("VERIFIED k2") and restated.startswith("DUPLICATE of k2")
    assert len(ctx.evidence.claims) == 2  # refused drafts never reach the verifier


async def test_wrong_field_name_lists_the_fields_that_exist():
    ctx = _ctx()
    await _tools(extraction_tools(ctx, PLAN))["fetch_dataset"].ainvoke(
        {"dataset_id": "M184071", "rationale": "r"}
    )
    await _tools(extraction_tools(ctx, PLAN))["select_series"].ainvoke(
        {"series_key": VACANCIES, "reason": "fits", "rationale": "r"}
    )
    tools = _tools(analytics_tools(ctx, PLAN))
    computed = await tools["compute"].ainvoke(
        {"tool": "cagr", "series_key": VACANCIES, "start": "2020-Q1", "end": "2024-Q4", "rationale": "r"}
    )
    reply = await tools["draft_claim"].ainvoke(
        {
            "kind": "comparison",
            "rationale": "r",
            "assertions": [
                {
                    "predicate": "cagr.growth",
                    "computation_id": computed["computation_id"],
                    "field": "job_vacancies",
                    "metric": "job_vacancies",
                    "series_key": VACANCIES,
                    "interval_start": "2020-Q1",
                    "interval_end": "2024-Q4",
                }
            ],
        }
    )
    assert "its fields are ['cagr_pct']" in reply


async def test_employment_level_is_cross_checked_against_its_wide_format_mirror():
    plan = PLAN.model_copy(update={"metrics": ["employment_level"]})
    ctx = _ctx()
    tools = _tools(extraction_tools(ctx, plan))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M182841", "rationale": "r"})
    reply = await tools["select_series"].ainvoke(
        {"series_key": "M182841:3.4@SSIC2020", "reason": "fits", "rationale": "r"}
    )
    assert "d_d2518fed6cc2014f0cd061b4570a9592 (datagov): consistent" in reply
    assert ctx.evidence.consistency[0].periods == ["2020", "2021", "2022", "2023", "2024"]


@respx.mock
async def test_series_with_a_blocking_quality_error_cannot_be_selected(tmp_path):
    # SingStat says "Number" where the catalogue expects thousands: a UNIT_MISMATCH error on the series.
    page = {
        "Data": {
            "title": "Employment",
            "row": [
                {
                    "seriesNo": "3.4",
                    "rowText": "Information And Communications",
                    "uoM": "Number",
                    "columns": [{"key": str(y), "value": "180300"} for y in range(2020, 2025)],
                }
            ],
        }
    }
    respx.get(singstat.tabledata_url("M182841", 0)).respond(json=page)
    ctx = _ctx()
    ctx.fetcher = Fetcher(mode="live", snapshots=SnapshotStore(tmp_path), backoff_s=0)
    tools = _tools(extraction_tools(ctx, PLAN.model_copy(update={"metrics": ["employment_level"]})))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M182841", "rationale": "r"})

    (inspected,) = await tools["inspect_series"].ainvoke(
        {"dataset_id": "M182841", "sector": "info_comms", "rationale": "r"}
    )
    reply = await tools["select_series"].ainvoke(
        {"series_key": "M182841:3.4@SSIC2020", "reason": "fits", "rationale": "r"}
    )

    assert inspected["blocking_quality_errors"][0].startswith("UNIT_MISMATCH")
    assert reply.startswith("REFUSED by policy") and "UNIT_MISMATCH" in reply
    assert not ctx.evidence.selected


async def test_a_republished_copy_of_a_selected_statistic_is_refused():
    ctx = _ctx()
    plan = PLAN.model_copy(update={"metrics": ["employment_change"]})
    tools = _tools(extraction_tools(ctx, plan))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M183891", "rationale": "r"})
    first = await tools["select_series"].ainvoke(
        {"series_key": "M183891:1.2.4@SSIC2020", "reason": "fits", "rationale": "r"}
    )
    assert (
        "cross-checked against mrsd_3_qtly_emp_chg_by_ind (mom): consistent within published rounding"
        in first
    )

    mom_ict = ctx.evidence.dataset("mrsd_3_qtly_emp_chg_by_ind").find("info_comms")[0].key
    second = await tools["select_series"].ainvoke(
        {"series_key": mom_ict, "reason": "also fits", "rationale": "r"}
    )

    assert second.startswith("REFUSED by policy") and "used only as a cross-check" in second
    assert list(ctx.evidence.selected) == ["M183891:1.2.4@SSIC2020"]


def _employment_change_tools(ctx):
    return _tools(extraction_tools(ctx, PLAN.model_copy(update={"metrics": ["employment_change"]})))


async def test_selecting_the_mom_release_first_still_cross_checks_singstat():
    ctx = _ctx()
    tools = _employment_change_tools(ctx)
    await tools["fetch_dataset"].ainvoke({"dataset_id": "mrsd_3_qtly_emp_chg_by_ind", "rationale": "r"})
    mom_ict = ctx.evidence.dataset("mrsd_3_qtly_emp_chg_by_ind").find("info_comms")[0].key

    reply = await tools["select_series"].ainvoke({"series_key": mom_ict, "reason": "fits", "rationale": "r"})

    assert "cross-checked against M183891 (singstat): consistent within published rounding" in reply
    (check,) = ctx.evidence.consistency
    assert check.mismatches == [] and len(check.periods) == 20


async def test_a_mirror_with_blocking_errors_is_not_reported_consistent():
    from tests.unit.data.test_quality_mutations import MOM_Q_XLSX, MutatedSnapshots, _cells, _edit_workbook

    def hundreds(sheet) -> None:
        for cell in _cells(sheet, lambda v: v == "In Thousands"):
            cell.value = "In Hundreds"

    ctx = _ctx()
    ctx.fetcher = Fetcher(mode="snapshot", snapshots=MutatedSnapshots({MOM_Q_XLSX: _edit_workbook(hundreds)}))
    tools = _employment_change_tools(ctx)
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M183891", "rationale": "r"})

    reply = await tools["select_series"].ainvoke(
        {"series_key": "M183891:1.2.4@SSIC2020", "reason": "fits", "rationale": "r"}
    )

    assert "not comparable (blocking quality errors: mrsd_3_qtly_emp_chg_by_ind: UNIT_MISMATCH)" in reply
    assert "consistent" not in reply
    (check,) = ctx.evidence.consistency  # recorded as refused, never as agreement
    assert check.not_comparable and check.verdict.startswith("not comparable") and not check.periods
    events = [d for t, _, d in ctx.writer.events if t == "consistency_check"]
    assert events and "UNIT_MISMATCH" in events[-1]["not_comparable"]


async def test_analytics_agent_can_correlate_the_named_pair_and_state_it_as_an_association():
    ctx = _ctx()
    plan = PLAN.model_copy(update={"metrics": ["job_vacancies", "employment_change"]})
    extraction = _tools(extraction_tools(ctx, plan))
    for dataset_id, key in (("M184071", VACANCIES), ("M183891", "M183891:1.2.4@SSIC2020")):
        await extraction["fetch_dataset"].ainvoke({"dataset_id": dataset_id, "rationale": "r"})
        await extraction["select_series"].ainvoke({"series_key": key, "reason": "fits", "rationale": "r"})
    tools = _tools(analytics_tools(ctx, plan))

    evidence = await tools["list_evidence"].ainvoke({"rationale": "r"})
    vacancies = next(e for e in evidence if e.get("series_key") == VACANCIES)
    suggestions = [s for s in vacancies["suggested_computations"] if s["tool"] == "correlate"]
    # Listed first under the leading series (vacancies lead employment change).
    assert vacancies["suggested_computations"][:2] == suggestions
    assert [(s["other_series_key"], s["lag"]) for s in suggestions] == [
        ("M183891:1.2.4@SSIC2020", "0"),
        ("M183891:1.2.4@SSIC2020", "1"),
    ]

    described = await tools["compute"].ainvoke(
        {k: v for k, v in suggestions[0].items() if k != "pairs"} | {"rationale": "r"}
    )
    field = described["fields"]["pearson_r"]
    # The model calls it a comparison; an association is defined by its predicate, not its label.
    reply = await tools["draft_claim"].ainvoke(
        {
            "kind": "comparison",
            "assertions": [
                {
                    "predicate": "assoc.positive",
                    "computation_id": described["computation_id"],
                    "field": "pearson_r",
                    "metric": field["metric"],
                    "series_key": VACANCIES,
                    "interval_start": "2020-Q1",
                    "interval_end": "2024-Q4",
                }
            ],
            "rationale": "r",
        }
    )
    assert reply.startswith("VERIFIED") and "exploratory, not evidence of cause" in reply
    (claim,) = ctx.evidence.verified_claims()
    assert claim.kind == "association"


async def test_a_refused_correlation_is_recorded_as_a_limitation():
    ctx = _ctx()
    plan = PLAN.model_copy(update={"metrics": ["job_vacancies", "employment_level"]})
    extraction = _tools(extraction_tools(ctx, plan))
    annual_vacancies = "d_01966fdb498fa7fa2863635e25539693"
    await extraction["fetch_dataset"].ainvoke({"dataset_id": "M182841", "rationale": "r"})
    await extraction["fetch_dataset"].ainvoke({"dataset_id": annual_vacancies, "rationale": "r"})
    vac_key = ctx.evidence.dataset(annual_vacancies).find("info_comms")[0].key
    for key in ("M182841:3.4@SSIC2020", vac_key):
        await extraction["select_series"].ainvoke({"series_key": key, "reason": "fits", "rationale": "r"})
    tools = _tools(analytics_tools(ctx, plan))

    evidence = await tools["list_evidence"].ainvoke({"rationale": "r"})
    suggested = [c for e in evidence for c in e.get("suggested_computations", []) if c["tool"] == "correlate"]
    assert suggested == [], "no rule pairs these two"
    (refused,) = [e["correlations_not_allowed"] for e in evidence if "correlations_not_allowed" in e]
    assert refused[0].startswith("REFERENCE_MISMATCH")
    assert [t for t, *_ in ctx.writer.events].count("refusal") == 1
    # Asking anyway gets the same answer, recorded once.
    reply = await tools["compute"].ainvoke(
        {
            "tool": "correlate",
            "series_key": "M182841:3.4@SSIC2020",
            "other_series_key": vac_key,
            "start": "2020",
            "end": "2024",
            "rationale": "r",
        }
    )

    assert reply.startswith("REFUSED REFERENCE_MISMATCH")
    (refusal,) = ctx.evidence.refusals
    assert refusal.code == "REFERENCE_MISMATCH"


async def test_repeating_a_computation_reuses_it_without_spending_the_budget():
    ctx = _ctx()
    tools_e = _tools(extraction_tools(ctx, PLAN))
    await tools_e["fetch_dataset"].ainvoke({"dataset_id": "M184071", "rationale": "r"})
    await tools_e["select_series"].ainvoke({"series_key": VACANCIES, "reason": "fits", "rationale": "r"})
    tools = _tools(analytics_tools(ctx, PLAN))
    args = {"tool": "trend", "series_key": VACANCIES, "start": "2020-Q1", "end": "2024-Q4", "rationale": "r"}

    first = await tools["compute"].ainvoke(args)
    repeats = [await tools["compute"].ainvoke(args) for _ in range(10)]  # more than the round's budget

    assert all(
        r["computation_id"] == first["computation_id"] and "already computed" in r["note"] for r in repeats
    )
    fresh = await tools["compute"].ainvoke({**args, "tool": "change_between"})
    assert "computation_id" in fresh, "the budget was not used up by repeats"


def test_a_refused_correlation_reads_as_a_sentence_about_both_series():
    from app.agents.evidence import EvidenceStore
    from app.agents.report import _refusal_text
    from app.analytics.results import Refusal

    refusal = Refusal(
        tool="correlate",
        code="REFERENCE_MISMATCH",
        detail="both are stocks but observed differently",
        params={},
        series_key="a",
        other_series_key="b",
    )
    assert _refusal_text(refusal, EvidenceStore()) == (
        "a and b were not correlated: REFERENCE_MISMATCH (both are stocks but observed differently)"
    )


async def _selected(dataset_ids: list[str], metrics: list[str], start_year: int = 2020, end_year: int = 2024):
    ctx = _ctx()
    plan = PLAN.model_copy(update={"metrics": metrics, "start_year": start_year, "end_year": end_year})
    extraction = _tools(extraction_tools(ctx, plan))
    for dataset_id in dataset_ids:
        await extraction["fetch_dataset"].ainvoke({"dataset_id": dataset_id, "rationale": "r"})
        key = ctx.evidence.dataset(dataset_id).find("info_comms")[0].key
        selected = await extraction["select_series"].ainvoke(
            {"series_key": key, "reason": "fits", "rationale": "r"}
        )
        assert selected.startswith("SELECTED"), selected
    return ctx, plan, _tools(analytics_tools(ctx, plan))


async def test_the_same_pair_refused_in_reverse_order_is_recorded_once():
    annual_vacancies = "d_01966fdb498fa7fa2863635e25539693"
    ctx, _, tools = await _selected(["M182841", annual_vacancies], ["employment_level", "job_vacancies"])
    await tools["list_evidence"].ainvoke({"rationale": "r"})
    vacancies = ctx.evidence.dataset(annual_vacancies).find("info_comms")[0].key

    reply = await tools["compute"].ainvoke(
        {
            "tool": "correlate",
            "series_key": vacancies,
            "other_series_key": "M182841:3.4@SSIC2020",
            "start": "2020",
            "end": "2024",
            "rationale": "r",
        }
    )

    assert "already recorded" in reply and len(ctx.evidence.refusals) == 1


async def test_each_suggested_lag_is_checked_and_an_ineligible_lag_is_reported():
    # 2022-2024: lag 0 has 12 pairs (eligible), lag 1 has 11 (too few).
    ctx, _, tools = await _selected(
        ["M184071", "M183891"], ["job_vacancies", "employment_change"], 2022, 2024
    )

    evidence = await tools["list_evidence"].ainvoke({"rationale": "r"})

    suggested = [c for e in evidence for c in e.get("suggested_computations", []) if c["tool"] == "correlate"]
    assert [c["lag"] for c in suggested] == ["0"] and suggested[0]["pairs"].startswith("12 aligned pairs")
    (refusal,) = ctx.evidence.refusals
    assert refusal.code == "INSUFFICIENT_PAIRS" and refusal.params["lag"] == "1"


async def test_an_earlier_result_is_still_returned_after_the_round_budget_is_spent():
    ctx, _, tools = await _selected(["M184071"], ["job_vacancies"])
    periods = [f"{y}-Q{q}" for y in (2020, 2021) for q in range(1, 5)]
    first = [
        await tools["compute"].ainvoke(
            {"tool": "value_at", "series_key": VACANCIES, "period": p, "rationale": "r"}
        )
        for p in periods
    ][0]
    assert len(ctx.evidence.computations) == 8  # the round's budget

    again = await tools["compute"].ainvoke(
        {"tool": "value_at", "series_key": VACANCIES, "period": "2020-Q1", "rationale": "r"}
    )
    new = await tools["compute"].ainvoke(
        {"tool": "value_at", "series_key": VACANCIES, "period": "2022-Q1", "rationale": "r"}
    )

    assert again["computation_id"] == first["computation_id"]
    assert isinstance(new, str) and new.startswith("BUDGET")


async def test_caveats_of_a_retained_association_are_in_the_report():
    from app.agents.report import build_report
    from tests.unit.test_correlation import WINDOW, _association

    ctx, plan, tools = await _selected(["M184071", "M183891"], ["job_vacancies", "employment_change"])
    described = await tools["compute"].ainvoke(
        {
            "tool": "correlate",
            "series_key": VACANCIES,
            "other_series_key": "M183891:1.2.4@SSIC2020",
            "start": WINDOW[0],
            "end": WINDOW[1],
            "lag": "0",
            "rationale": "r",
        }
    )
    computation = ctx.evidence.computations[described["computation_id"]]
    claim = _association(computation)
    ctx.evidence.claims.append((claim, verify_claim(claim, ctx.evidence.computations)))

    report = build_report(plan, ctx.evidence, narrative=None, question="Are these related?")

    texts = [item["text"] for item in report["limitations"]]
    assert (
        "Job vacancies in Information & Communications and employment change in Information & "
        "Communications: the two series count different populations (establishments vs total employment)"
    ) in texts
    assert any("serially dependent" in t for t in texts)


# -- data-quality panel ----------------------------------------------------------------------------


def _panel(plan, ctx) -> dict[str, dict]:
    from app.agents.report import build_report

    return {d["dataset_id"]: d for d in build_report(plan, ctx.evidence, None, question="q")["data_quality"]}


def _in_hundreds(sheet) -> None:
    from tests.unit.data.test_quality_mutations import _cells

    for cell in _cells(sheet, lambda v: v == "In Thousands"):
        cell.value = "In Hundreds"


async def test_a_refused_cross_check_and_its_errors_stay_in_the_panel():
    from tests.unit.data.test_quality_mutations import MOM_Q, MOM_Q_XLSX, MutatedSnapshots, _edit_workbook

    ctx = _ctx()
    ctx.fetcher = Fetcher(
        mode="snapshot", snapshots=MutatedSnapshots({MOM_Q_XLSX: _edit_workbook(_in_hundreds)})
    )
    plan = PLAN.model_copy(update={"metrics": ["employment_change"]})
    tools = _tools(extraction_tools(ctx, plan))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M183891", "rationale": "r"})
    await tools["select_series"].ainvoke(
        {"series_key": "M183891:1.2.4@SSIC2020", "reason": "fits", "rationale": "r"}
    )

    panel = _panel(plan, ctx)

    assert panel[MOM_Q]["role"] == "cross-check"
    assert any(c["code"] == "UNIT_MISMATCH" and c["severity"] == "error" for c in panel[MOM_Q]["checks"])


async def test_the_panel_states_the_meaning_the_fetched_workbook_gives_a_marker():
    from tests.unit.data.test_quality_mutations import (
        MOM_Q,
        MOM_Q_XLSX,
        MutatedSnapshots,
        _cells,
        _edit_workbook,
    )

    def redefine(sheet) -> None:
        for cell in _cells(sheet, lambda v: v.startswith("'-'")):
            cell.value = "'-' :  Not available"

    ctx = _ctx()
    ctx.fetcher = Fetcher(mode="snapshot", snapshots=MutatedSnapshots({MOM_Q_XLSX: _edit_workbook(redefine)}))
    plan = PLAN.model_copy(update={"sectors": ["manufacturing"], "metrics": ["employment_change"]})
    tools = _tools(extraction_tools(ctx, plan))
    await tools["fetch_dataset"].ainvoke({"dataset_id": MOM_Q, "rationale": "r"})
    key = ctx.evidence.dataset(MOM_Q).find("manufacturing")[0].key
    await tools["select_series"].ainvoke({"series_key": key, "reason": "fits", "rationale": "r"})

    dataset = _panel(plan, ctx)[MOM_Q]

    assert dataset["markers"][0]["meaning"] == "Not available"  # what this workbook says, not the manifest
    assert any(c["code"] == "LEGEND_CHANGED" for c in dataset["checks"])


async def test_a_dataset_used_both_ways_lists_its_cross_checked_series_too():
    from app.connectors import singstat
    from tests.unit.data.test_quality_mutations import MutatedSnapshots, _edit_singstat

    def unknown_marker(row: dict) -> None:
        if row["seriesNo"] == "1.1.1":  # manufacturing
            next(c for c in row["columns"] if c["key"].startswith("2019"))["value"] = "x"

    ctx = _ctx()
    ctx.fetcher = Fetcher(
        mode="snapshot",
        snapshots=MutatedSnapshots({singstat.tabledata_url("M184071", 0): _edit_singstat(unknown_marker)}),
    )
    plan = PLAN.model_copy(update={"sectors": ["info_comms", "manufacturing"]})
    tools = _tools(extraction_tools(ctx, plan))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M184071", "rationale": "r"})
    await tools["select_series"].ainvoke({"series_key": VACANCIES, "reason": "fits", "rationale": "r"})
    # Manufacturing is taken from the Data.gov.sg copy, so M184071's manufacturing row is only a cross-check.
    mirror = ctx.evidence.dataset("d_3f17bbf67d31d4d402caa8755eb74afc").find("manufacturing")[0].key
    await tools["select_series"].ainvoke({"series_key": mirror, "reason": "fits", "rationale": "r"})

    dataset = _panel(plan, ctx)["M184071"]

    assert dataset["role"] == "evidence"
    assert {VACANCIES, "M184071:1.1.1@SSIC2020"} <= set(dataset["series"])
    assert any(c["code"] == "UNLISTED_MARKER" for c in dataset["checks"])


async def test_a_coverage_gap_says_why_from_the_fetched_data():
    from app.agents.report import _why_uncovered

    ctx = _ctx()
    tools = _tools(extraction_tools(ctx, PLAN))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M182841", "rationale": "r"})
    early = PLAN.model_copy(update={"metrics": ["employment_level"], "start_year": 1985, "end_year": 1990})

    reason = _why_uncovered("info_comms", "employment_level", early, ctx.evidence)
    assert reason.startswith("M182841 has it only for ") and reason.endswith("not for all of 1985 to 1990")

    covered = early.model_copy(update={"start_year": 2020, "end_year": 2024})
    assert _why_uncovered("info_comms", "employment_level", covered, ctx.evidence) == (
        "M182841 has it, but it was not selected"
    )
    assert _why_uncovered("info_comms", "recruitment_rate", covered, ctx.evidence) == (
        "no dataset fetched for this analysis has such a series"
    )


class _Choosing:
    """A router whose only answer is the given option choice (or an outage)."""

    def __init__(self, options=None):
        self.options = options

    async def structured(self, schema, messages, **kwargs):
        from app.llm.router import LLMUnavailable

        if self.options is None:
            raise LLMUnavailable("down")
        return schema(options=self.options)


@pytest.mark.parametrize(
    ("answer", "offered"),
    [
        (
            ["Information & Communications", "Manufacturing"],
            ["Information & Communications", "Manufacturing"],
        ),
        (["Information & Communications", "Something invented", "Construction"], None),  # stays a subset
        (["Information & Communications"], "first four"),  # fewer than two: fall back
        (None, "first four"),  # provider down: fall back
    ],
)
async def test_too_many_options_are_chosen_from_not_cut(answer, offered):
    from app.agents.graph import _choose_options

    sectors = [
        "Services",
        "Manufacturing",
        "Construction",
        "Retail",
        "Information & Communications",
        "Finance",
    ]
    plan = PLAN.model_copy(update={"needs_clarification": True, "clarification_options": sectors})
    ctx = _ctx()
    ctx.router = _Choosing(answer)

    chosen = (await _choose_options(ctx, "How is the sector doing?", plan)).clarification_options

    if offered == "first four":
        assert chosen == sectors[:4]
    elif offered is None:
        assert chosen == ["Information & Communications", "Construction"]
    else:
        assert chosen == offered


def test_a_quarter_on_annual_data_starts_its_year_or_the_next():
    from app.agents.tools import suggested_computations
    from app.data.identity import MeasureType

    years = [str(y) for y in range(2020, 2026)]
    assert suggested_computations(MeasureType.FLOW, years, "2022-Q3")[1]["b_start"] == "2023"
    assert suggested_computations(MeasureType.FLOW, years, "2022-Q1")[1]["b_start"] == "2022"


@pytest.mark.parametrize(
    ("comparison_start", "split"),
    [
        ("2022-Q3", ("2022-Q2", "2022-Q3")),
        (None, ("2022-Q2", "2022-Q3")),
        ("2023-Q1", ("2022-Q4", "2023-Q1")),
        ("2023", ("2022-Q4", "2023-Q1")),  # a year starts at its first quarter
        ("2019-Q1", ("2022-Q2", "2022-Q3")),  # outside the window: halves
    ],
)
def test_a_period_comparison_splits_where_the_question_does(comparison_start, split):
    from app.agents.tools import suggested_computations
    from app.data.identity import MeasureType

    window = [f"{y}-Q{q}" for y in range(2020, 2025) for q in range(1, 5)]
    compare = suggested_computations(MeasureType.FLOW, window, comparison_start)[1]
    assert (compare["a_end"], compare["b_start"]) == split
    assert (compare["a_start"], compare["b_end"]) == ("2020-Q1", "2024-Q4")


async def test_the_coordinator_sees_planned_pairs_without_a_series():
    from app.agents.graph import _evidence_summary

    ctx = _ctx()
    ctx.plan = PLAN.model_copy(update={"metrics": ["employment_level", "job_vacancies"]})
    tools = _tools(extraction_tools(ctx, ctx.plan))
    await tools["fetch_dataset"].ainvoke({"dataset_id": "M184071", "rationale": "r"})
    await tools["select_series"].ainvoke({"series_key": VACANCIES, "reason": "fits", "rationale": "r"})

    summary = _evidence_summary(ctx, {"extraction": 1, "analytics": 0})

    assert summary["planned_without_series"] == ["employment_level in info_comms"]
    assert summary["planned_without_findings"] == [
        "employment_level in info_comms",
        "job_vacancies in info_comms",
    ]
