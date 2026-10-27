"""Scoring one live run from what it stored (plan §8.3).

Nothing here trusts the run's own verdicts. Every retained finding is verified again from its stored
claim against the stored computations, and its text is rendered again; narrative sentences, charts
and citations are checked against the stored evidence. Golden computations are recognised by
rerunning their spec on the series the run selected and matching the computation fingerprint, so
a mirror on another platform counts as the same evidence.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analytics.results import Computation, Refusal, SeriesInput
from app.analytics.tools import Toolkit
from app.data.identity import SeriesIdentity, same_measure_incompatibility
from app.data.models import NormalizedDataset, SeriesData
from app.data.taxonomy import get_taxonomy
from app.db.models import (
    Analysis,
    AnalysisArtifact,
    AnalysisEvent,
    AnalysisStatus,
    ComputationRow,
    DatasetArtifact,
    LLMCall,
    ReportRow,
)
from app.evaluation.accuracy import Series, compare_fields, run_spec
from app.evaluation.golden import expected, golden
from app.grounding.checks import check_free_text, verify_claim
from app.grounding.contracts import Claim
from app.grounding.predicates import PREDICATES
from app.grounding.render import render_claim

AGENTS = ("coordinator", "extraction", "analytics")
COMPLETED = {AnalysisStatus.COMPLETED, AnalysisStatus.COMPLETED_WITH_LIMITATIONS}


@dataclass
class Stored:
    """Everything one analysis left in the database."""

    analysis: Analysis
    report: dict[str, Any] | None
    events: list[AnalysisEvent]
    calls: list[LLMCall]
    computations: dict[str, Computation]
    datasets: dict[str, NormalizedDataset]  # by artifact id, as this analysis fetched them


async def load(sessions: async_sessionmaker[AsyncSession], analysis_id: str) -> Stored:
    async with sessions() as session:
        analysis = await session.get(Analysis, analysis_id)
        assert analysis is not None, analysis_id
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
        events = list(
            await session.scalars(
                select(AnalysisEvent)
                .where(AnalysisEvent.analysis_id == analysis_id)
                .order_by(AnalysisEvent.seq)
            )
        )
        calls = list(
            await session.scalars(
                select(LLMCall).where(LLMCall.analysis_id == analysis_id).order_by(LLMCall.id)
            )
        )
        computations = {
            row.computation_id: Computation.model_validate(row.content)
            for row in await session.scalars(
                select(ComputationRow).where(ComputationRow.analysis_id == analysis_id)
            )
        }
        rows = await session.execute(
            select(DatasetArtifact.content, AnalysisArtifact.fetch_record)
            .join(AnalysisArtifact, AnalysisArtifact.artifact_id == DatasetArtifact.artifact_id)
            .where(AnalysisArtifact.analysis_id == analysis_id)
        )
        fetched = [NormalizedDataset.model_validate(c).as_fetched(f) for c, f in rows]
    return Stored(analysis, report, events, calls, computations, {d.artifact_id: d for d in fetched})


def golden_name(identity: SeriesIdentity, series: Series) -> str | None:
    """The golden series this identity measures (a mirror on another platform measures the same)."""
    return next(
        (
            name
            for name, (source, _) in series.items()
            if same_measure_incompatibility(identity, source.identity) is None
        ),
        None,
    )


def _selected(stored: Stored, series: Series) -> dict[str, tuple[SeriesInput, Any]]:
    """The run's selected series by golden name (or by series key when it is not a golden series)."""
    out = {}
    for sel in (stored.report or {}).get("evidence", {}).get("selected", []):
        dataset = stored.datasets[sel["artifact_id"]]
        data = next(s for s in dataset.series if s.key == sel["series_key"])
        assert data.identity is not None
        source = SeriesInput(
            artifact_id=dataset.artifact_id,
            dataset_id=dataset.dataset_id,
            series_key=data.key,
            identity=data.identity,
        )
        out[golden_name(data.identity, series) or data.key] = (source, data)
    return out


def _golden_ids(selected: dict[str, tuple[SeriesInput, Any]]) -> dict[str, str]:
    """computation id -> golden computation id, for every golden computation the selection allows."""
    toolkit = Toolkit(get_taxonomy().version)
    out = {}
    for cid, spec in golden()["computations"].items():
        if all(name in selected for name in (spec["series"], spec.get("other", spec["series"]))):
            result = run_spec(toolkit, spec, selected)
            if isinstance(result, Computation):
                out[result.id] = cid
    return out


def _golden_artifacts(cid: str, series: Series) -> set[str]:
    spec = golden()["computations"][cid]
    return {series[name][0].artifact_id for name in (spec["series"], spec.get("other", spec["series"]))}


def _in_base_units(cid: str, computation: Computation) -> dict[str, list[float | None]]:
    """A golden computation made on a republication (e.g. MOM's workbook in thousands at 0.1 for
    SingStat's persons): expected and actual value of each field in base units. The expectation is
    pinned to the golden dataset, so rounding in the republication can differ; this is reported,
    and the republication itself is checked against the source by the run's consistency check."""
    wanted = expected()["computations"][cid]["fields"]
    return {
        name: [
            want["value"] * want["scale"],
            got.value * got.scale if (got := computation.result.get(name)) is not None else None,
        ]
        for name, want in wanted.items()
    }


def _fetched_input(stored: Stored, ref: SeriesInput) -> tuple[SeriesInput, SeriesData] | None:
    """A computation input as this analysis fetched it: the identity comes from the source, not
    from what the computation says about itself."""
    dataset = stored.datasets.get(ref.artifact_id)
    data = next((s for s in dataset.series if s.key == ref.series_key), None) if dataset else None
    if dataset is None or data is None or data.identity is None:
        return None
    source = SeriesInput(
        artifact_id=dataset.artifact_id,
        dataset_id=dataset.dataset_id,
        series_key=data.key,
        identity=data.identity,
    )
    return source, data


def recompute(stored: Stored, computation: Computation) -> Computation | Refusal | None:
    """The computation run again on its fetched inputs, or None if an input was never fetched."""
    inputs = [_fetched_input(stored, ref) for ref in computation.inputs]
    if any(i is None for i in inputs):
        return None
    args = [i for i in inputs if i is not None]
    toolkit, p = Toolkit(get_taxonomy().version), computation.params
    if computation.tool == "correlate":
        return toolkit.correlate(*args[0], *args[1], p["start"], p["end"], p["lag"])
    if computation.tool == "yoy_change":  # stored as the change between the prior period and `end`
        return toolkit.yoy_change(*args[0], p["end"])
    return getattr(toolkit, computation.tool)(*args[0], **p)


def check_recomputed(stored: Stored) -> list[str]:
    """Every stored computation, golden or not and on whichever platform, must be reproduced
    exactly from the series this analysis fetched: values, inputs with their identities, and
    fingerprint. Golden computations on the golden datasets are also checked against the
    independent expectation."""
    out = []
    for key, computation in stored.computations.items():
        again = recompute(stored, computation)
        if again is None:
            out.append(f"{key}: an input series was not fetched by this analysis")
        elif not isinstance(again, Computation):
            out.append(f"{key}: recomputing it is refused ({again.code})")
        else:
            out += [
                f"{key}: {part} differs when recomputed from the fetched series"
                for part in ("id", "fingerprint", "inputs", "result", "interpretation_allowed")
                if getattr(again, part) != getattr(computation, part)
            ]
            if key != computation.id:
                out.append(f"{key}: stored under another computation's id")
    return out


def _names(refusal: Refusal, by_key: dict[str, str]) -> frozenset[str]:
    keys = (refusal.series_key, refusal.other_series_key)
    return frozenset(by_key.get(k, k) for k in keys if k)


def check_retained(stored: Stored) -> list[str]:
    """Every way the stored result fails the §3.6 contract; empty when it holds."""
    report = stored.report
    if report is None:
        return []
    failures: list[str] = []
    verified_events = {
        e.detail.get("claim_id"): e.detail.get("rendered")
        for e in stored.events
        if e.type == "claim_verdict" and e.detail.get("passed")
    }
    citations = {c["id"]: c for c in report["citations"]}
    allowed_periods: set[str] = set()
    for finding in report["findings"]:
        fid = finding["id"]
        if "claim" not in finding:
            failures.append(f"{fid}: no stored claim to verify")
            continue
        claim = Claim.model_validate(finding["claim"])
        verdict = verify_claim(claim, stored.computations)
        failures += [f"{fid}: {c.name}: {c.detail}" for c in verdict.failures]
        if not verdict.passed:
            continue
        rendered = render_claim(claim, stored.computations)
        if rendered != finding["text"]:
            failures.append(f"{fid}: text differs from its rendered claim")
        if verified_events.get(fid) != rendered:
            failures.append(f"{fid}: no matching verification event")
        lineage = {
            i.artifact_id
            for a in claim.assertions.values()
            for i in stored.computations[a.computation_id].inputs
        }
        cited = {citations[c]["artifact_id"] for c in finding["citations"] if c in citations}
        if cited != lineage or len(cited) != len(finding["citations"]):
            failures.append(f"{fid}: citations do not match the computations' inputs")
        allowed_periods |= {p for a in claim.assertions.values() for p in (a.interval.start, a.interval.end)}
    # Generated prose: no unbound numbers and no causal wording. Deterministic limitations (refusal
    # details, caveats) legitimately carry numbers, so they are only checked for causal wording.
    generated = [
        report["summary"],
        *(lim["text"] for lim in report["limitations"] if lim["source"] == "coordinator"),
    ]
    if report["title"] != stored.analysis.query:
        generated.append(report["title"])
    for text in generated:
        failures += [
            f"narrative: {c.name}: {c.detail}" for c in check_free_text(text, allowed_periods) if not c.passed
        ]
    for lim in report["limitations"]:
        failures += [
            f"limitation: {c.detail}"
            for c in check_free_text(lim["text"], set())
            if c.name == "no_causal_language" and not c.passed
        ]
    for artifact_id in {c["artifact_id"] for c in citations.values()} - set(stored.datasets):
        failures.append(f"citation of {artifact_id}, which this analysis never fetched")
    for chart in report["charts"]:
        for line in chart["series"]:
            dataset = stored.datasets.get(citations.get(line["citation"], {}).get("artifact_id", ""))
            data = next((s for s in dataset.series if s.key == line["series_key"]), None) if dataset else None
            if data is None:
                failures.append(f"{chart['id']}: {line['series_key']} not in its cited dataset")
                continue
            identity = data.identity
            stated = (chart["metric"], chart["frequency"], chart["unit"], chart["scale"])
            if identity is None or stated != (
                identity.metric,
                identity.frequency,
                identity.unit,
                identity.scale,
            ):
                failures.append(
                    f"{chart['id']}: metric, frequency, unit or scale differ from {line['series_key']}"
                )
            observed = data.value_map()
            if any(
                p["period"] not in observed or observed[p["period"]].value != p["value"]
                for p in line["points"]
            ):
                failures.append(
                    f"{chart['id']}: {line['series_key']} points differ from the source observations"
                )
    return failures


def autonomy(stored: Stored) -> dict[str, Any]:
    """Who decided what (plan MA-1, MA-2): LLM decisions per agent, and decisions driven by the
    evidence rather than by a fixed route. A proposal the policy guard overruled is not the model's
    decision: it is listed separately."""
    decisions = Counter(c.agent for c in stored.calls if c.ok)
    rationales = Counter(
        e.agent for e in stored.events if e.type in ("rationale", "decision", "plan") and e.agent in AGENTS
    )
    driven: list[dict[str, str]] = []
    overrides: list[str] = []
    rounds = Counter[str]()
    for e in stored.events:
        if e.type == "rejection":
            driven.append(
                {
                    "agent": "extraction",
                    "decision": "rejected a candidate series",
                    "detail": f"{e.title}: {e.detail.get('reason', '')}",
                }
            )
        elif e.type == "handoff" and e.title == "Back to Coordinator":
            rounds[e.agent] += 1
        elif e.type == "decision":
            action, objective = e.detail.get("action"), e.detail.get("objective", "")
            if e.detail.get("policy_override"):
                overrides.append(e.detail["policy_override"])
            elif action == "extract" and rounds["extraction"]:
                driven.append(
                    {"agent": "coordinator", "decision": "requested more evidence", "detail": objective}
                )
            elif action == "analyse" and rounds["analytics"]:
                driven.append(
                    {"agent": "coordinator", "decision": "requested more analysis", "detail": objective}
                )
    return {
        "llm_decisions": {a: decisions.get(a, 0) for a in AGENTS},
        "public_rationales": {a: rationales.get(a, 0) for a in AGENTS},
        "evidence_driven": driven,
        "policy_overrides": overrides,
    }


def directions(stored: Stored, golden_ids: dict[str, str]) -> dict[str, str]:
    """Golden computation id -> the direction a retained finding stated about it."""
    out = {}
    for finding in (stored.report or {}).get("findings", []):
        for a in finding.get("claim", {}).get("assertions", {}).values():
            if (cid := golden_ids.get(a["computation_id"])) is not None:
                predicate = PREDICATES[a["predicate"]]
                out[f"{cid}.{a['field']}"] = predicate.sign or predicate.id
    return out


def _usage(stored: Stored) -> dict[str, Any]:
    return {
        "calls": len(stored.calls),
        "failed_calls": sum(not c.ok for c in stored.calls),
        "answered_by": dict(Counter(c.provider for c in stored.calls if c.ok)),
        "fallbacks": sum(1 for c in stored.calls if c.ok and c.fallback_from),
        "input_tokens": sum(c.input_tokens or 0 for c in stored.calls),
        "output_tokens": sum(c.output_tokens or 0 for c in stored.calls),
        "llm_latency_ms": sum(c.latency_ms for c in stored.calls),
        # Calls whose token usage is unknown (e.g. a timeout): any cost total is then unknown too.
        "calls_without_usage": sum(c.input_tokens is None or c.output_tokens is None for c in stored.calls),
        "active_ms": stored.analysis.active_ms_used,
        "by_model": {
            model: [
                sum(c.input_tokens or 0 for c in stored.calls if c.model == model),
                sum(c.output_tokens or 0 for c in stored.calls if c.model == model),
            ]
            for model in sorted({c.model for c in stored.calls})
        },
    }


def score(
    stored: Stored, expect: dict[str, Any], series: Series, clarification: dict[str, Any] | None
) -> dict[str, Any]:
    """One run against its golden query's expectations."""
    report = stored.report or {}
    plan = stored.analysis.plan or {}
    selected = _selected(stored, series)
    by_key = {source.series_key: name for name, (source, _) in selected.items()}
    golden_ids = _golden_ids(selected)
    findings = report.get("findings", [])
    refusals = [Refusal.model_validate(r) for r in report.get("evidence", {}).get("refusals", [])]

    # Refusal correctness: refuse what must be refused, and answer nothing that cannot be answered.
    refusal_problems = []
    if expect.get("clarification"):
        if clarification is None:
            refusal_problems.append("did not ask for clarification")
    elif expect.get("in_scope") is False and plan.get("in_scope") is not False:
        refusal_problems.append("out-of-domain question was planned as in scope")
    if expect.get("findings") == "none" and findings:
        refusal_problems.append(f"{len(findings)} finding(s) for a question the data cannot answer")
    if expect.get("computations") and not findings:
        refusal_problems.append("no verified finding for a question the data can answer")
    recorded = {r.identity() for r in refusals}
    toolkit = Toolkit(get_taxonomy().version)
    for rid in expect.get("refusals", []):
        spec = golden()["refusals"][rid]
        needed = (spec["series"], spec.get("other", spec["series"]))
        if missing := [n for n in needed if n not in selected]:
            refusal_problems.append(f"{rid}: {', '.join(missing)} not selected")
            continue
        # The refusal of exactly this request (tool, series, window, lag) on the run's own series.
        request = run_spec(toolkit, spec, selected)
        if (
            not isinstance(request, Refusal)
            or request.code != spec["code"]
            or request.identity() not in recorded
        ):
            refusal_problems.append(f"{rid}: expected {spec['code']} for {spec['tool']} {spec['params']}")
    for cid in expect.get("computations", []):
        spec = golden()["computations"][cid]
        pair = frozenset({spec["series"], spec.get("other", spec["series"])})
        wanted = {k: str(v) for k, v in spec["params"].items()}
        if any(
            r.tool == spec["tool"]
            and _names(r, by_key) == pair
            and {k: str(v) for k, v in r.params.items()} == wanted
            for r in refusals
        ):
            refusal_problems.append(f"{cid}: an eligible computation was refused")

    names = set(selected)
    sectors = {source.identity.sector for source, _ in selected.values()}
    alternatives = [set(a) for a in expect.get("series_any_of", [])]
    identities_ok = (not alternatives or any(a <= names for a in alternatives)) and sectors <= set(
        expect.get("sectors", sectors)
    )

    computed = {cid for comp_id, cid in golden_ids.items() if comp_id in stored.computations}
    mismatches, republished = [], {}
    for comp_id, cid in golden_ids.items():
        if (computation := stored.computations.get(comp_id)) is None:
            continue
        if {i.artifact_id for i in computation.inputs} == _golden_artifacts(cid, series):
            mismatches += [
                f"{f.computation}.{f.field}" for f in compare_fields(cid, computation.result) if not f.ok
            ]
        else:
            republished[cid] = _in_base_units(cid, computation)
    mismatches += check_recomputed(stored)
    # A run must finish: failed, or paused for a question nobody expected, is not an outcome.
    completed = stored.analysis.status in COMPLETED or (
        stored.analysis.status == AnalysisStatus.AWAITING_INPUT and bool(expect.get("clarification"))
    )
    supported_run = bool(findings) and plan.get("in_scope", False)
    agency = autonomy(stored)
    return {
        "status": stored.analysis.status,
        "completed": completed,
        "error": stored.analysis.error,
        "plan": {
            k: plan.get(k) for k in ("in_scope", "sectors", "metrics", "start_year", "end_year", "intent")
        }
        if plan
        else None,
        "clarification": clarification,
        "unexpected_clarification": clarification is not None and not expect.get("clarification"),
        "selected": sorted(names),
        "identities_correct": identities_ok,
        "refusals": sorted({f"{r.code.value}:{'+'.join(sorted(_names(r, by_key)))}" for r in refusals}),
        "refusal_correct": not refusal_problems,
        "refusal_problems": refusal_problems,
        "expected_computations": sorted(expect.get("computations", [])),
        "golden_computations_found": sorted(computed),
        "computation_mismatches": mismatches,
        "republished_computations": republished,
        "retained_failures": check_retained(stored),
        "findings": [f["text"] for f in findings],
        "summary": report.get("summary", ""),
        "narrative_removed": report.get("verification", {}).get("narrative_removed", []),
        "narrative_check": report.get("verification", {}).get("narrative_check"),
        "directions": directions(stored, golden_ids),
        "autonomy": agency,
        "all_agents_decided": not supported_run
        or all(agency["llm_decisions"][a] and agency["public_rationales"][a] for a in AGENTS),
        "usage": _usage(stored),
    }
