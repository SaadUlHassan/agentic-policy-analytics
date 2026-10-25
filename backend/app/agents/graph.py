"""The multi-agent graph: Coordinator plans and routes; Extraction and Analytics run ReAct loops."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agents import prompts
from app.agents.context import AgentContext
from app.agents.plan import NextAction, ResearchPlan, validate_plan, vocabulary
from app.agents.react import run_react
from app.agents.report import ReportNarrative, build_report
from app.agents.tools import analytics_tools, extraction_tools
from app.db.models import AnalysisStatus
from app.grounding.qualitative import unsupported_sentences
from app.grounding.render import render_claim
from app.llm.router import LLMUnavailable

MAX_ROUNDS = {"extraction": 2, "analytics": 2}
TOOL_BUDGET = {"extraction": 14, "analytics": 16}
RECURSION_LIMIT = 30


class GraphState(TypedDict, total=False):
    query: str
    plan: dict[str, Any]
    objective: str
    rounds: dict[str, int]
    report: dict[str, Any]
    status: str


def _plan(state: GraphState) -> ResearchPlan:
    return ResearchPlan.model_validate(state["plan"])


async def interpret(
    state: GraphState, runtime: Runtime[AgentContext]
) -> Command[Literal["supervise", "report"]]:
    ctx = runtime.context
    sectors, metrics = vocabulary(ctx.catalog, ctx.taxonomy)
    messages = [SystemMessage(prompts.coordinator_plan(sectors, metrics)), HumanMessage(state["query"])]
    plan = await ctx.router.structured(
        ResearchPlan, messages, agent="coordinator", purpose="plan", deadline=ctx.deadline
    )
    if problems := validate_plan(plan, sectors, metrics):
        messages.append(HumanMessage("Revise the plan. Problems: " + "; ".join(problems)))
        plan = await ctx.router.structured(
            ResearchPlan, messages, agent="coordinator", purpose="plan_repair", deadline=ctx.deadline
        )
        if problems := validate_plan(plan, sectors, metrics):
            plan = plan.model_copy(
                update={
                    "in_scope": False,
                    "scope_note": "The question could not be mapped to supported data: "
                    + "; ".join(problems),
                }
            )
    if plan.in_scope and (plan.start_year is None or plan.end_year is None):
        end = date.today().year - 1
        plan = plan.model_copy(
            update={
                "start_year": end - 4,
                "end_year": end,
                "assumptions": [
                    *plan.assumptions,
                    "No period was given, so the most recent five complete years are used.",
                ],
            }
        )
    ctx.plan = plan
    await ctx.writer.save_plan(plan.model_dump())
    await ctx.writer.emit("coordinator", "plan", "Research plan", plan.model_dump())
    goto: Literal["supervise", "report"] = "supervise" if plan.in_scope else "report"
    return Command(update={"plan": plan.model_dump(), "rounds": {"extraction": 0, "analytics": 0}}, goto=goto)


def _evidence_summary(ctx: AgentContext, rounds: dict[str, int]) -> dict[str, Any]:
    ev = ctx.evidence
    return {
        "datasets_fetched": sorted({d.dataset_id for d in ev.datasets.values()}),
        "selected_series": [
            {"series_key": k, "subject": s.source.identity.subject(), "dataset": s.source.dataset_id}
            for k, s in ev.selected.items()
        ],
        "rejected_series": [r.series_key for r in ev.rejected],
        "computations": len(ev.computations),
        "refusals": [f"{r.tool}:{r.code}" for r in ev.refusals],
        "claims_verified": len(ev.verified_claims()),
        "claims_rejected": len(ev.claims) - len(ev.verified_claims()),
        "rounds_used": rounds,
        "rounds_allowed": MAX_ROUNDS,
    }


def _guard(action: str, ctx: AgentContext, rounds: dict[str, int]) -> str | None:
    """Reason the proposed action is not allowed, or None."""
    if action == "extract" and rounds["extraction"] >= MAX_ROUNDS["extraction"]:
        return "extraction rounds exhausted"
    if action == "analyse":
        if not ctx.evidence.selected:
            return "no series selected yet"
        if rounds["analytics"] >= MAX_ROUNDS["analytics"]:
            return "analytics rounds exhausted"
    if action == "report" and rounds["extraction"] == 0:
        return "no extraction attempted yet"
    return None


Action = Literal["extract", "analyse", "report"]
Node = Literal["extraction", "analytics", "report"]


def _fallback(ctx: AgentContext, rounds: dict[str, int]) -> Action:
    if not ctx.evidence.selected and rounds["extraction"] < MAX_ROUNDS["extraction"]:
        return "extract"
    if (
        ctx.evidence.selected
        and not ctx.evidence.verified_claims()
        and rounds["analytics"] < MAX_ROUNDS["analytics"]
    ):
        return "analyse"
    return "report"


_NODE: dict[Action, Node] = {"extract": "extraction", "analyse": "analytics", "report": "report"}


async def supervise(
    state: GraphState, runtime: Runtime[AgentContext]
) -> Command[Literal["extraction", "analytics", "report"]]:
    ctx = runtime.context
    rounds = state["rounds"]
    if all(rounds[a] >= n for a, n in MAX_ROUNDS.items()):
        return Command(goto="report")
    summary = _evidence_summary(ctx, rounds)
    messages = [
        SystemMessage(prompts.coordinator_supervise()),
        HumanMessage(f"Plan: {json.dumps(state['plan'])}\nEvidence so far: {json.dumps(summary)}"),
    ]
    proposal = await ctx.router.structured(
        NextAction, messages, agent="coordinator", purpose="supervise", deadline=ctx.deadline
    )
    action: Action = proposal.action
    objective, override = proposal.objective, None
    if reason := _guard(action, ctx, rounds):
        override = f"proposed '{action}' refused by policy: {reason}"
        action = _fallback(ctx, rounds)
        objective = f"{objective} (policy route: {action})"
    await ctx.writer.emit(
        "coordinator",
        "decision",
        f"Next: {action}",
        {
            "action": action,
            "objective": objective,
            "rationale": proposal.rationale,
            "policy_override": override,
        },
    )
    return Command(update={"objective": objective}, goto=_NODE[action])


async def extraction(state: GraphState, runtime: Runtime[AgentContext]) -> Command[Literal["supervise"]]:
    ctx = runtime.context
    plan = _plan(state)
    task = f"Research plan: {json.dumps(state['plan'])}\nObjective from the Coordinator: {state['objective']}"
    outcome = await run_react(
        ctx,
        agent="extraction",
        system=prompts.extraction(vocabulary(ctx.catalog, ctx.taxonomy)[0]),
        task=task,
        tools=extraction_tools(ctx, plan),
        max_tool_calls=TOOL_BUDGET["extraction"],
    )
    rounds = {**state["rounds"], "extraction": state["rounds"]["extraction"] + 1}
    await ctx.writer.emit(
        "extraction",
        "handoff",
        "Back to Coordinator",
        {"stop_reason": outcome.stop_reason, "selected": list(ctx.evidence.selected)},
    )
    return Command(update={"rounds": rounds}, goto="supervise")


async def analytics(state: GraphState, runtime: Runtime[AgentContext]) -> Command[Literal["supervise"]]:
    ctx = runtime.context
    plan = _plan(state)
    done = [
        f"{c.id}: {c.text} -> {[a.computation_id for a in c.assertions.values()]}"
        for c in ctx.evidence.verified_claims()
    ]
    task = (
        f"Research plan: {json.dumps(state['plan'])}\nObjective from the Coordinator: {state['objective']}\n"
        f"Findings already verified (do not repeat them): {done or 'none'}\n"
        "Start by listing the evidence."
    )
    outcome = await run_react(
        ctx,
        agent="analytics",
        system=prompts.analytics(),
        task=task,
        tools=analytics_tools(ctx, plan),
        max_tool_calls=TOOL_BUDGET["analytics"],
    )
    rounds = {**state["rounds"], "analytics": state["rounds"]["analytics"] + 1}
    await ctx.writer.emit(
        "analytics",
        "handoff",
        "Back to Coordinator",
        {"stop_reason": outcome.stop_reason, "claims_verified": len(ctx.evidence.verified_claims())},
    )
    return Command(update={"rounds": rounds}, goto="supervise")


async def report(state: GraphState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    plan = _plan(state)
    narrative: ReportNarrative | None = None
    removed: list[dict[str, str]] = []
    if plan.in_scope:
        findings = [render_claim(c, ctx.evidence.computations) for c in ctx.evidence.verified_claims()]
        narrative, removed = await _checked_narrative(ctx, state["query"], findings)
    built = build_report(plan, ctx.evidence, narrative, question=state["query"])
    built["verification"]["narrative_removed"] = removed
    if not plan.in_scope:
        built["limitations"].insert(0, {"source": "coordinator", "text": plan.scope_note or "Out of scope."})
    # Completed only when every planned sector x metric has a verified finding and nothing was refused.
    complete = bool(built["findings"]) and not ctx.evidence.refusals and not built["coverage"]["uncovered"]
    status = AnalysisStatus.COMPLETED if complete else AnalysisStatus.COMPLETED_WITH_LIMITATIONS
    await ctx.writer.emit(
        "coordinator",
        "report",
        built["title"],
        {
            "findings": len(built["findings"]),
            "limitations": len(built["limitations"]),
            "citations": [c["id"] for c in built["citations"]],
            "narrative_removed": removed,
        },
    )
    return {"report": built, "status": status.value}


async def _judge(ctx: AgentContext, findings: list[str], sentences: list[str]) -> dict[int, str]:
    try:
        return await unsupported_sentences(ctx.router, findings, sentences, deadline=ctx.deadline)
    except LLMUnavailable:
        return {i: "could not be checked" for i in range(len(sentences))}


async def _rewrite_summary(
    ctx: AgentContext, query: str, findings: list[str], summary: str, reason: str
) -> str | None:
    try:
        rewritten = await ctx.router.structured(
            ReportNarrative,
            [
                SystemMessage(prompts.report_narrative()),
                HumanMessage(
                    f"Question: {query}\nVerified findings:\n"
                    + "\n".join(f"- {f}" for f in findings)
                    + f"\nA reviewer rejected this summary: {summary!r} because: {reason}. "
                    "Write a new summary that only restates what the findings say."
                ),
            ],
            agent="coordinator",
            purpose="report_rewrite",
            deadline=ctx.deadline,
        )
    except LLMUnavailable:
        return None
    return rewritten.summary or None


async def _checked_narrative(
    ctx: AgentContext, query: str, findings: list[str]
) -> tuple[ReportNarrative | None, list[dict[str, str]]]:
    """Write the narrative, then keep only sentences an (independent) judge finds supported."""
    try:
        narrative = await ctx.router.structured(
            ReportNarrative,
            [
                SystemMessage(prompts.report_narrative()),
                HumanMessage(
                    f"Question: {query}\nVerified findings:\n" + "\n".join(f"- {f}" for f in findings)
                ),
            ],
            agent="coordinator",
            purpose="report",
            deadline=ctx.deadline,
        )
    except LLMUnavailable:
        return None, []
    # Every generated sentence is judged: title (0), summary (1), then limitations (2..).
    sentences = [narrative.title, narrative.summary, *narrative.limitations]
    rejected = await _judge(ctx, findings, sentences)
    removed = [{"text": sentences[i], "reason": reason} for i, reason in rejected.items()]
    if 1 in rejected and narrative.summary:
        # One rewrite with the judge's reason; if that is also unsupported the report has no summary.
        retry = await _rewrite_summary(ctx, query, findings, narrative.summary, rejected[1])
        if retry and not await _judge(ctx, findings, [retry]):
            narrative = narrative.model_copy(update={"summary": retry})
            del rejected[1]
    await ctx.writer.emit(
        "coordinator",
        "narrative_check",
        f"{len(sentences) - len(rejected)} of {len(sentences)} narrative sentences supported",
        {"removed": removed},
    )
    return narrative.model_copy(
        update={
            "title": "" if 0 in rejected else narrative.title,
            "summary": "" if 1 in rejected else narrative.summary,
            "limitations": [t for i, t in enumerate(narrative.limitations, start=2) if i not in rejected],
        }
    ), removed


def build_graph() -> Any:
    builder = StateGraph(GraphState, context_schema=AgentContext)
    builder.add_node("interpret", interpret)
    builder.add_node("supervise", supervise)
    builder.add_node("extraction", extraction)
    builder.add_node("analytics", analytics)
    builder.add_node("report", report)
    builder.add_edge(START, "interpret")
    builder.add_edge("report", END)
    return builder.compile()
