"""Agent tools on real snapshot data, with an in-memory writer."""

from __future__ import annotations

import time

import pytest
import respx
from pydantic import ValidationError

from app.agents.context import AgentContext
from app.agents.plan import ResearchPlan
from app.agents.tools import analytics_tools, extraction_tools
from app.connectors import singstat
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, SnapshotStore, get_snapshot_store
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
    assert "consistent" not in reply and ctx.evidence.consistency == []
    events = [d for t, _, d in ctx.writer.events if t == "consistency_check"]
    assert events and events[-1]["blocking_issues"]
