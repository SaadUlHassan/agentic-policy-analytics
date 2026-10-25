"""Tools the Extraction and Analytics agents call. Deterministic guards back every LLM judgement.

Every tool takes a `rationale` argument: the agent's public, one-sentence reason for the step.
It is shown to the researcher; the tool itself ignores it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.agents.context import AgentContext
from app.agents.evidence import ConsistencyCheck, Rejection, Selection
from app.agents.plan import ResearchPlan
from app.analytics.results import Computation, Interval, Refusal, RefusalCode, SeriesInput
from app.connectors import registry
from app.connectors.http import SourceUnavailable
from app.data.identity import MeasureType, same_measure_incompatibility
from app.data.models import NormalizedDataset, SeriesData
from app.data.periods import Frequency
from app.grounding.checks import verify_claim
from app.grounding.contracts import Assertion, Claim, ClaimKind
from app.grounding.prose import LeadIn, compose_text
from app.grounding.render import render_claim

MAX_COMPUTATIONS_PER_ROUND = 8
MAX_STATEMENTS_PER_FINDING = 2


def plan_window(plan: ResearchPlan, frequency: Frequency) -> list[str]:
    assert plan.start_year is not None and plan.end_year is not None
    years = range(plan.start_year, plan.end_year + 1)
    if frequency is Frequency.ANNUAL:
        return [str(y) for y in years]
    return [f"{y}-Q{q}" for y in years for q in range(1, 5)]


def _missing_in_window(series: SeriesData, window: list[str]) -> list[str]:
    values = series.value_map()
    return [p for p in window if p not in values or values[p].value is None]


class _Step(BaseModel):
    rationale: str = Field(
        description="One plain sentence, shown to the researcher: why you are taking this step"
    )


def _tool(fn: Callable[..., Awaitable[Any]], schema: type[BaseModel], description: str) -> BaseTool:
    return StructuredTool.from_function(
        coroutine=fn, name=fn.__name__, args_schema=schema, description=description
    )


class _Finish(_Step):
    summary: str = Field(description="What was achieved and what is still missing")


async def finish(summary: str, rationale: str = "") -> str:
    return summary


# -- extraction ------------------------------------------------------------------------------------


class _Search(_Step):
    query: str = Field(description="Words describing the metric needed, e.g. 'employment level by sector'")


class _Fetch(_Step):
    dataset_id: str


class _Inspect(_Step):
    dataset_id: str
    sector: str = Field(description="Sector key, e.g. 'info_comms'")


class _Decide(_Step):
    series_key: str
    reason: str = Field(description="Why this series does or does not fit the plan, in one sentence")


class _Consistency(_Step):
    series_key: str
    other_series_key: str = Field(description="The same statistic from another platform")


def extraction_tools(ctx: AgentContext, plan: ResearchPlan) -> list[BaseTool]:
    async def _load(dataset_id: str) -> NormalizedDataset:
        """Fetch, parse and quality-check a dataset (once per analysis) and record it as evidence."""
        if (cached := ctx.evidence.dataset(dataset_id)) is not None:
            return cached
        try:
            dataset = await registry.fetch(dataset_id, ctx.catalog, ctx.taxonomy, ctx.fetcher)
        except SourceUnavailable as exc:
            raise RuntimeError(f"source unavailable: {exc.reason}") from exc
        ctx.evidence.datasets[dataset.artifact_id] = dataset
        await ctx.writer.save_artifact(dataset)
        await ctx.writer.emit(
            "extraction",
            "quality_report",
            f"Validated {dataset_id}",
            {
                "dataset_id": dataset_id,
                "title": dataset.provenance.title,
                "platform": dataset.provenance.platform,
                "series": len(dataset.series),
                "identified": len(dataset.identified_series()),
                "issues": [i.model_dump() for i in dataset.quality],
            },
        )
        return dataset

    async def _compare(series_key: str, other_series_key: str) -> dict[str, Any]:
        """Same statistic on two platforms: compare every plan-window period both report."""
        for done in ctx.evidence.consistency:
            if {done.series_a, done.series_b} == {series_key, other_series_key}:
                return {
                    "verdict": done.verdict,
                    "periods_compared": len(done.periods),
                    "note": "already checked",
                }
        found = [ctx.evidence.find_series(k) for k in (series_key, other_series_key)]
        if found[0] is None or found[1] is None:
            raise RuntimeError("fetch both datasets first")
        (ds_a, a), (ds_b, b) = found[0], found[1]
        if a.identity is None or b.identity is None:
            raise RuntimeError("both series must be identified")
        if reason := same_measure_incompatibility(a.identity, b.identity):
            return {"verdict": "not comparable", "reason": reason.value}
        values_a, values_b = a.value_map(), b.value_map()
        compared, mismatches = [], []
        for period in plan_window(plan, a.identity.frequency):
            va, vb = values_a.get(period), values_b.get(period)
            if va is None or vb is None or va.value is None or vb.value is None:
                continue
            compared.append(period)
            if va.value * a.identity.scale != vb.value * b.identity.scale:
                mismatches.append({"period": period, series_key: va.value, other_series_key: vb.value})
        check = ConsistencyCheck(
            series_a=series_key,
            artifact_a=ds_a.artifact_id,
            series_b=other_series_key,
            artifact_b=ds_b.artifact_id,
            periods=compared,
            mismatches=mismatches,
        )
        ctx.evidence.consistency.append(check)
        await ctx.writer.emit(
            "extraction",
            "consistency_check",
            check.verdict,
            {
                "series_a": series_key,
                "platform_a": ds_a.provenance.platform,
                "series_b": other_series_key,
                "platform_b": ds_b.provenance.platform,
                "periods_compared": len(compared),
                "mismatches": mismatches,
            },
        )
        return {"verdict": check.verdict, "periods_compared": len(compared), "mismatches": mismatches[:10]}

    async def _check_mirrors(dataset_id: str, series: SeriesData) -> list[str]:
        """Quality control, not a choice: a selected series is always compared with the same statistic
        republished on another catalogued platform."""
        entry = ctx.catalog.get(dataset_id)
        notes = []
        for mirror_id in [m for m in (entry.mirrors if entry else []) if ctx.catalog.get(m)]:
            try:
                mirror = await _load(mirror_id)
            except RuntimeError as exc:
                notes.append(f"mirror {mirror_id} unavailable: {exc}")
                continue
            assert series.identity is not None
            twin = next(
                (
                    m
                    for m in mirror.find(series.identity.sector)
                    if m.identity and same_measure_incompatibility(series.identity, m.identity) is None
                ),
                None,
            )
            if twin is None:
                notes.append(f"mirror {mirror_id} has no matching series")
                continue
            result = await _compare(series.key, twin.key)
            notes.append(
                f"cross-checked against {mirror_id} ({mirror.provenance.platform}): {result['verdict']}"
            )
        return notes

    async def search_catalog(query: str, rationale: str = "") -> list[dict[str, Any]]:
        return [h.model_dump(exclude={"score"}) for h in ctx.catalog.search(query)]

    async def fetch_dataset(dataset_id: str, rationale: str = "") -> dict[str, Any]:
        dataset = await _load(dataset_id)
        notable = [i for i in dataset.quality if i.severity != "info" or i.code == "SERVED_FROM_SNAPSHOT"]
        return {
            "dataset_id": dataset_id,
            "title": dataset.provenance.title,
            "platform": dataset.provenance.platform,
            "from_snapshot": dataset.provenance.from_snapshot,
            "sectors_available": sorted(
                {s.identity.sector for s in dataset.identified_series() if s.identity}
            ),
            "notable_quality_issues": [f"{i.code} x{i.count}: {i.message}" for i in notable][:8],
        }

    async def inspect_series(dataset_id: str, sector: str, rationale: str = "") -> list[dict[str, Any]]:
        dataset = ctx.evidence.dataset(dataset_id)
        if dataset is None:
            raise RuntimeError(f"fetch {dataset_id} first")
        out = []
        for s in dataset.find(sector):
            assert s.identity is not None
            out.append(
                {
                    "series_key": s.key,
                    "source_label": s.label,
                    **s.identity.model_dump(mode="json"),
                    "first_period": s.observations[0].period if s.observations else None,
                    "last_period": s.observations[-1].period if s.observations else None,
                    "missing_in_plan_window": _missing_in_window(s, plan_window(plan, s.identity.frequency)),
                    "blocking_quality_errors": [f"{i.code}: {i.message}" for i in dataset.blocking_issues(s)],
                }
            )
        return out or [{"note": f"no identified series for sector {sector!r} in {dataset_id}"}]

    async def select_series(series_key: str, reason: str, rationale: str = "") -> str:
        found = ctx.evidence.find_series(series_key)
        if found is None:
            raise RuntimeError(f"unknown series {series_key!r}")
        dataset, series = found
        identity = series.identity
        problems = []
        if identity is None:
            problems.append(f"series is unidentified ({series.unidentified_reason})")
        problems += [f"quality error {i.code}: {i.message}" for i in dataset.blocking_issues(series)]
        if identity is not None:
            if identity.sector not in plan.sectors:
                problems.append(f"sector {identity.sector} is not in the plan {plan.sectors}")
            if identity.metric not in plan.metrics:
                problems.append(f"metric {identity.metric} is not in the plan {plan.metrics}")
            if missing := _missing_in_window(series, plan_window(plan, identity.frequency)):
                problems.append(f"no values for {', '.join(missing)}")
        if problems or identity is None:
            await ctx.writer.emit("extraction", "selection_refused", series_key, {"problems": problems})
            return "REFUSED by policy: " + "; ".join(problems)
        source = SeriesInput(
            artifact_id=dataset.artifact_id,
            dataset_id=dataset.dataset_id,
            series_key=series.key,
            identity=identity,
        )
        ctx.evidence.selected[series_key] = Selection(source=source, series=series, reason=reason)
        await ctx.writer.emit(
            "extraction",
            "selection",
            f"Selected {identity.subject()}",
            {"series_key": series_key, "dataset_id": dataset.dataset_id, "reason": reason},
        )
        notes = await _check_mirrors(dataset.dataset_id, series)
        return f"SELECTED {series_key}" + (f". {'; '.join(notes)}" if notes else "")

    async def reject_series(series_key: str, reason: str, rationale: str = "") -> str:
        ctx.evidence.rejected.append(Rejection(series_key=series_key, reason=reason))
        await ctx.writer.emit("extraction", "rejection", f"Rejected {series_key}", {"reason": reason})
        return f"REJECTED {series_key}"

    async def check_consistency(
        series_key: str, other_series_key: str, rationale: str = ""
    ) -> dict[str, Any]:
        return await _compare(series_key, other_series_key)

    return [
        _tool(search_catalog, _Search, "Search the curated catalogue; hits list mirrors on other platforms."),
        _tool(fetch_dataset, _Fetch, "Fetch, parse and quality-check a catalogued dataset."),
        _tool(inspect_series, _Inspect, "List a fetched dataset's series for one sector with coverage."),
        _tool(
            select_series, _Decide, "Select a series as evidence (checked against the plan and its mirrors)."
        ),
        _tool(reject_series, _Decide, "Record that a candidate series does not fit the plan."),
        _tool(
            check_consistency,
            _Consistency,
            "Compare the same statistic published on two platforms over the plan window.",
        ),
        _tool(finish, _Finish, "Call when your task is complete or cannot progress further."),
    ]


# -- analytics -------------------------------------------------------------------------------------

ToolName = Literal[
    "value_at", "change_between", "yoy_change", "cagr", "trend", "compare_periods", "cumulative"
]


class _Compute(_Step):
    tool: ToolName
    series_key: str
    period: str | None = Field(default=None, description="For value_at and yoy_change")
    start: str | None = Field(default=None, description="For change_between, cagr, trend, cumulative")
    end: str | None = None
    a_start: str | None = Field(default=None, description="For compare_periods: earlier window")
    a_end: str | None = None
    b_start: str | None = Field(default=None, description="For compare_periods: later window")
    b_end: str | None = None


class _AssertionIn(BaseModel):
    predicate: str = Field(description="Predicate id, e.g. 'change.increase'")
    computation_id: str = Field(description="computation_id returned by compute")
    field: str = Field(
        description="A key of the computation's `fields`, e.g. 'pct_change', 'cagr_pct', 'total'"
    )
    metric: str = Field(description="That field's `metric`, e.g. 'employment_level'")
    series_key: str
    interval_start: str = Field(description="That field's interval start")
    interval_end: str = Field(description="That field's interval end")


class _Draft(_Step):
    kind: Literal["measured", "comparison"] | None = Field(
        default=None, description="Optional; inferred from the assertions when omitted"
    )
    lead_in: LeadIn = Field(
        default="", description="Optional neutral connective placed before the statements"
    )
    assertions: list[_AssertionIn] = Field(description="One or two statements; each renders as a clause")


_SINGLE_PERIOD_PREDICATES = {"level.at", "flow.at"}


def infer_kind(assertions: list[_AssertionIn]) -> str:
    """Models sometimes omit `kind`; it follows from what the assertions state."""
    return "measured" if all(a.predicate in _SINGLE_PERIOD_PREDICATES for a in assertions) else "comparison"


_ARGS = {
    "value_at": ("period",),
    "yoy_change": ("period",),
    "change_between": ("start", "end"),
    "cagr": ("start", "end"),
    "trend": ("start", "end"),
    "compare_periods": ("a_start", "a_end", "b_start", "b_end"),
    "cumulative": ("start", "end"),
}


def _describe(c: Computation) -> dict[str, Any]:
    return {
        "computation_id": c.id,
        "tool": c.tool,
        "series_key": c.inputs[0].series_key,
        "notes": c.notes,
        "fields": {
            name: {
                "value": round(f.value, 6),
                "value_kind": f.value_kind,
                "metric": f.metric,
                "unit": f.unit,
                "scale": f.scale,
                "interval": f.interval.model_dump(),
            }
            for name, f in c.result.items()
        },
    }


def suggested_computations(measure: MeasureType, window: list[str]) -> list[dict[str, str]]:
    """Statistics that are eligible for this kind of series over the plan window, with exact arguments."""
    start, end = window[0], window[-1]
    half = len(window) // 2
    halves = {"a_start": start, "a_end": window[half - 1], "b_start": window[half], "b_end": end}
    if measure is MeasureType.FLOW:
        return [{"tool": "cumulative", "start": start, "end": end}, {"tool": "compare_periods", **halves}]
    suggestions = [
        {"tool": "change_between", "start": start, "end": end},
        {"tool": "trend", "start": start, "end": end},
    ]
    if measure is MeasureType.STOCK:
        suggestions.insert(1, {"tool": "cagr", "start": start, "end": end})
    return suggestions


def analytics_tools(ctx: AgentContext, plan: ResearchPlan) -> list[BaseTool]:
    computed_this_round = 0

    async def list_evidence(rationale: str = "") -> list[dict[str, Any]]:
        out = []
        for key, sel in ctx.evidence.selected.items():
            window = plan_window(plan, sel.source.identity.frequency)
            out.append(
                {
                    "series_key": key,
                    "subject": sel.source.identity.subject(),
                    **sel.source.identity.model_dump(mode="json"),
                    "plan_window": [window[0], window[-1]],
                    "suggested_computations": suggested_computations(
                        sel.source.identity.measure_type, window
                    ),
                }
            )
        return out or [{"note": "no series selected"}]

    async def compute(tool: ToolName, series_key: str, rationale: str = "", **params: str | None) -> Any:
        nonlocal computed_this_round
        if computed_this_round >= MAX_COMPUTATIONS_PER_ROUND:
            return (
                f"BUDGET: {MAX_COMPUTATIONS_PER_ROUND} computations already done this round. "
                "Draft claims from the existing computations now."
            )
        selection = ctx.evidence.selected.get(series_key)
        if selection is None:
            raise RuntimeError(f"{series_key!r} is not a selected series")
        needed = _ARGS[tool]
        if missing := [a for a in needed if not params.get(a)]:
            raise RuntimeError(f"{tool} needs {', '.join(missing)}")
        computed_this_round += 1
        result: Computation | Refusal = getattr(ctx.toolkit, tool)(
            selection.source, selection.series, *(params[a] for a in needed)
        )
        if isinstance(result, Refusal) and result.code is RefusalCode.INVALID_WINDOW:
            computed_this_round -= 1  # an argument mistake, not an analysis: report it to the agent only
            raise RuntimeError(f"invalid arguments: {result.detail}")
        if isinstance(result, Refusal):
            ctx.evidence.refusals.append(result)
            await ctx.writer.emit(
                "analytics",
                "refusal",
                f"{tool} refused: {result.code}",
                {"series_key": series_key, "code": result.code, "detail": result.detail},
            )
            return f"REFUSED {result.code}: {result.detail}"
        ctx.evidence.computations[result.id] = result
        await ctx.writer.save_computation(result)
        await ctx.writer.emit(
            "analytics",
            "computation",
            f"{tool} on {selection.source.identity.subject()}",
            {"computation_id": result.id, "tool": tool, "params": result.params},
        )
        return _describe(result)

    async def draft_claim(
        assertions: list[Any], kind: str | None = None, lead_in: str = "", rationale: str = ""
    ) -> str:
        parsed = [_AssertionIn.model_validate(a) for a in assertions]
        kind = kind or infer_kind(parsed)
        # Readability rules: one idea per finding. Rejected before verification, so they are not counted.
        if not parsed:
            return "EMPTY: a finding needs at least one assertion"
        if len(parsed) > MAX_STATEMENTS_PER_FINDING:
            return f"TOO LONG: at most {MAX_STATEMENTS_PER_FINDING} statements per finding; split it up"
        # A draft that states nothing new (every statement already in a verified finding) is refused.
        stated = {
            (a.predicate, a.computation_id, a.field): claim.id
            for claim in ctx.evidence.verified_claims()
            for a in claim.assertions.values()
        }
        signature = {(a.predicate, a.computation_id, a.field) for a in parsed}
        if signature and signature <= stated.keys():
            already = sorted({stated[k] for k in signature})
            return f"DUPLICATE of {', '.join(already)}: draft a different finding or finish"
        slots = [f"a{i}" for i in range(1, len(parsed) + 1)]
        claim = Claim(
            id=f"k{len(ctx.evidence.claims) + 1}",
            kind=ClaimKind(kind),
            text=compose_text(lead_in, slots),
            assertions={
                slot: Assertion(
                    predicate=a.predicate,
                    computation_id=a.computation_id,
                    field=a.field,
                    metric=a.metric,
                    series_key=a.series_key,
                    interval=Interval(start=a.interval_start, end=a.interval_end),
                )
                for slot, a in zip(slots, parsed, strict=True)
            },
        )
        verdict = verify_claim(claim, ctx.evidence.computations)
        ctx.evidence.claims.append((claim, verdict))
        rendered = render_claim(claim, ctx.evidence.computations) if verdict.passed else None
        await ctx.writer.emit(
            "analytics",
            "claim_verdict",
            "Claim verified" if verdict.passed else "Claim rejected",
            {
                "claim_id": claim.id,
                "passed": verdict.passed,
                "rendered": rendered,
                "failures": [f.model_dump() for f in verdict.failures],
            },
        )
        if verdict.passed:
            return f"VERIFIED {claim.id}: {rendered}"
        return "REJECTED: " + "; ".join(f"{f.name}: {f.detail}" for f in verdict.failures)

    return [
        _tool(list_evidence, _Step, "List the selected series and the plan window."),
        _tool(compute, _Compute, "Run a deterministic statistic on a selected series."),
        _tool(draft_claim, _Draft, "Draft a finding; it is verified and the verdict returned."),
        _tool(finish, _Finish, "Call when your task is complete or cannot progress further."),
    ]
