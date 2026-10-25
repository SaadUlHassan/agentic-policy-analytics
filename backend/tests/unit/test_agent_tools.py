"""Agent tools on real snapshot data, with an in-memory writer."""

from __future__ import annotations

import time

from app.agents.context import AgentContext
from app.agents.plan import ResearchPlan
from app.agents.tools import analytics_tools, extraction_tools
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.data.taxonomy import get_taxonomy

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

    async def save_artifact(self, dataset):
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

    digits = await tools["draft_claim"].ainvoke(
        {"kind": "comparison", "prose": "Since 2020,", "assertions": [assertion], "rationale": "r"}
    )
    too_many = await tools["draft_claim"].ainvoke(
        {"kind": "comparison", "assertions": [assertion] * 3, "rationale": "r"}
    )
    # No `kind`: models sometimes omit it, and it is inferred from the assertions.
    ok = await tools["draft_claim"].ainvoke({"assertions": [assertion], "rationale": "r"})
    duplicate = await tools["draft_claim"].ainvoke(
        {"kind": "comparison", "assertions": [assertion], "rationale": "r"}
    )

    assert digits.startswith("REWRITE") and too_many.startswith("TOO LONG")
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
