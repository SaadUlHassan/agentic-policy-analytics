"""The multi-agent graph: Coordinator plans and routes; Extraction and Analytics run ReAct loops."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents import prompts
from app.agents.context import AgentContext
from app.agents.evidence import to_refs
from app.agents.plan import (
    MAX_CLARIFICATION_OPTIONS,
    NextAction,
    ResearchPlan,
    align_period,
    cap_options,
    clarification_problems,
    shorten_question,
    validate_plan,
    vocabulary,
)
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
    # References to the evidence gathered so far, so a resumed execution can rebuild its store.
    evidence: dict[str, Any]
    clarification: str
    clarified: bool
    report: dict[str, Any]
    status: str


def _plan(state: GraphState) -> ResearchPlan:
    return ResearchPlan.model_validate(state["plan"])


async def interpret(
    state: GraphState, runtime: Runtime[AgentContext]
) -> Command[Literal["supervise", "report", "clarify"]]:
    ctx = runtime.context
    await ctx.check_cancel()
    sectors, metrics = vocabulary(ctx.catalog, ctx.taxonomy)
    messages = [SystemMessage(prompts.coordinator_plan(sectors, metrics)), HumanMessage(state["query"])]
    if answer := state.get("clarification"):
        messages.append(
            HumanMessage(f"The researcher clarified: {answer}. Plan with this; do not ask again.")
        )

    def settled(plan: ResearchPlan) -> ResearchPlan:
        # Once the researcher has answered (or chosen to proceed), the plan does not ask again.
        return plan.model_copy(update={"needs_clarification": False}) if state.get("clarified") else plan

    plan = settled(
        await ctx.router.structured(
            ResearchPlan, messages, agent="coordinator", purpose="plan", deadline=ctx.deadline
        )
    )
    if problems := validate_plan(plan, sectors, metrics) + clarification_problems(plan):
        messages.append(HumanMessage("Revise the plan. Problems: " + "; ".join(problems)))
        plan = settled(
            await ctx.router.structured(
                ResearchPlan, messages, agent="coordinator", purpose="plan_repair", deadline=ctx.deadline
            )
        )
    plan = align_period(
        plan, state["query"], latest_year=date.today().year - 1, answer=state.get("clarification")
    )
    if plan.needs_clarification:
        plan = shorten_question(plan)
        if len(plan.clarification_options) > MAX_CLARIFICATION_OPTIONS:
            plan = await _choose_options(ctx, state["query"], plan)
    # Only vocabulary decides scope: how a question is put is never a reason to refuse it.
    if problems := validate_plan(plan, sectors, metrics):
        plan = plan.model_copy(
            update={
                "in_scope": False,
                "scope_note": "The question could not be mapped to supported data: " + "; ".join(problems),
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
    rounds = {"extraction": 0, "analytics": 0}
    if plan.needs_clarification and not state.get("clarified"):
        return Command(update={"plan": plan.model_dump(), "rounds": rounds}, goto="clarify")
    return await _adopt_plan(ctx, plan, rounds)


class OptionChoice(BaseModel):
    options: list[str] = Field(description="The chosen options, copied exactly from the list")


async def _choose_options(ctx: AgentContext, query: str, plan: ResearchPlan) -> ResearchPlan:
    """Too many options to offer: the model picks the ones the researcher most likely means, from its
    own list. Anything else (an invented option, too many, no answer) falls back to the first ones."""
    offered = plan.clarification_options
    try:
        choice = await ctx.router.structured(
            OptionChoice,
            [
                SystemMessage(
                    f"Choose two to {MAX_CLARIFICATION_OPTIONS} options to offer a researcher who asked "
                    "an ambiguous question: the ones they most likely mean. Copy them exactly."
                ),
                HumanMessage(f"Question: {query}\nOptions: {json.dumps(offered)}"),
            ],
            agent="coordinator",
            purpose="clarification_options",
            deadline=ctx.deadline,
        )
    except LLMUnavailable:
        return cap_options(plan)
    chosen = list(dict.fromkeys(o for o in choice.options if o in offered))
    if not 2 <= len(chosen) <= MAX_CLARIFICATION_OPTIONS:
        return cap_options(plan)
    return plan.model_copy(update={"clarification_options": chosen})


async def _adopt_plan(ctx: AgentContext, plan: ResearchPlan, rounds: dict[str, int]) -> Command[Any]:
    plan = plan.model_copy(update={"needs_clarification": False})
    ctx.plan = plan
    await ctx.writer.save_plan(plan.model_dump())
    await ctx.writer.emit("coordinator", "plan", "Research plan", plan.model_dump())
    goto: Literal["supervise", "report"] = "supervise" if plan.in_scope else "report"
    return Command(update={"plan": plan.model_dump(), "rounds": rounds}, goto=goto)


async def clarify(
    state: GraphState, runtime: Runtime[AgentContext]
) -> Command[Literal["interpret", "supervise", "report"]]:
    """Pause for the researcher. On resume this node restarts and interrupt() returns the answer, so
    nothing with side effects may come before it."""
    plan = _plan(state)
    response = interrupt(
        {
            "question": plan.clarification_question,
            "options": plan.clarification_options,
            "assumptions": plan.assumptions,
        }
    )
    if response.get("proceed") and not (plan.sectors and plan.metrics):
        # Nothing to proceed with yet (the question was about the sector or the measure): plan again,
        # taking the most sensible default instead of asking.
        default = "No preference: use the most sensible default sector and measure, as assumptions."
        return Command(update={"clarification": default, "clarified": True}, goto="interpret")
    if response.get("proceed"):
        proceeded = plan.model_copy(
            update={"assumptions": [*plan.assumptions, "The researcher chose to proceed without clarifying."]}
        )
        return await _adopt_plan(runtime.context, proceeded, state["rounds"])
    return Command(update={"clarification": str(response["answer"]), "clarified": True}, goto="interpret")


def _planned_without(ctx: AgentContext, covered: set[tuple[str, str]]) -> list[str]:
    plan = ctx.plan
    if plan is None:
        return []
    return [f"{m} in {s}" for s in plan.sectors for m in plan.metrics if (s, m) not in covered]


def _without_series(ctx: AgentContext) -> list[str]:
    """Planned sector x metric pairs no selected series measures yet."""
    selected = {(x.source.identity.sector, x.source.identity.metric) for x in ctx.evidence.selected.values()}
    return _planned_without(ctx, selected)


def _evidence_summary(ctx: AgentContext, rounds: dict[str, int]) -> dict[str, Any]:
    ev = ctx.evidence
    with_findings = {
        (ref.identity.sector, ref.identity.metric)
        for claim in ev.verified_claims()
        for a in claim.assertions.values()
        for ref in ev.computations[a.computation_id].inputs
    }
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
        "planned_without_series": _without_series(ctx),
        "planned_without_findings": _planned_without(ctx, with_findings),
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


def _policy_objective(action: Action, ctx: AgentContext) -> str:
    if action == "extract":
        missing = _without_series(ctx)
        return "Find and validate series for the plan" + (f": {', '.join(missing)}" if missing else "")
    if action == "analyse":
        return "Compute statistics on the selected series and draft findings (policy route)"
    return "Write the report from the verified findings (policy route)"


_NODE: dict[Action, Node] = {"extract": "extraction", "analyse": "analytics", "report": "report"}


async def supervise(
    state: GraphState, runtime: Runtime[AgentContext]
) -> Command[Literal["extraction", "analytics", "report"]]:
    ctx = runtime.context
    await ctx.check_cancel()
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
        # The refused proposal's objective was written for another action: the route sets its own.
        objective = _policy_objective(action, ctx)
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
    await ctx.check_cancel()
    plan = _plan(state)
    task = (
        f"Research plan: {json.dumps(state['plan'])}\nObjective from the Coordinator: {state['objective']}\n"
        f"Planned but no series selected yet: {_without_series(ctx) or 'none'}"
    )
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
    return Command(update={"rounds": rounds, "evidence": to_refs(ctx.evidence)}, goto="supervise")


async def analytics(state: GraphState, runtime: Runtime[AgentContext]) -> Command[Literal["supervise"]]:
    ctx = runtime.context
    await ctx.check_cancel()
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
    return Command(update={"rounds": rounds, "evidence": to_refs(ctx.evidence)}, goto="supervise")


async def report(state: GraphState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = runtime.context
    await ctx.check_cancel()
    plan = _plan(state)
    narrative: ReportNarrative | None = None
    removed: list[dict[str, str]] = []
    if plan.in_scope:
        findings = [render_claim(c, ctx.evidence.computations) for c in ctx.evidence.verified_claims()]
        narrative, removed = await _checked_narrative(ctx, state["query"], findings)
    built = build_report(plan, ctx.evidence, narrative, question=state["query"])
    built["verification"]["narrative_removed"] = removed
    if check := _narrative_check_independence(ctx):
        built["verification"]["narrative_check"] = check
        if not check["independent"]:
            built["limitations"].append(
                {
                    "source": "verification",
                    "text": f"The narrative was checked by the same model provider that wrote it "
                    f"({', '.join(check['writers'])}); the other provider was unavailable, so the "
                    "check was not independent.",
                }
            )
    if not plan.in_scope:
        built["limitations"].insert(0, {"source": "coordinator", "text": plan.scope_note or "Out of scope."})
    # Completed only when every planned sector x metric has a verified finding, nothing was refused, and
    # the comparison asked for could be made.
    complete = (
        bool(built["findings"])
        and not ctx.evidence.refusals
        and not built["coverage"]["uncovered"]
        and not plan.unavailable_comparison
    )
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


def _narrative_check_independence(ctx: AgentContext) -> dict[str, Any] | None:
    """Whether every narrative check was made by a different provider from every writer of the
    text it checked (plan §3.1). None when no narrative was written and checked."""
    answered = ctx.router.answered_by
    writers = sorted({*answered.get("report", []), *answered.get("report_rewrite", [])})
    judges = sorted(set(answered.get("narrative_check", [])))
    if not writers or not judges:
        return None
    return {"writers": writers, "judges": judges, "independent": not set(writers) & set(judges)}


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


def build_graph(checkpointer: Any = None) -> Any:
    """`checkpointer` persists progress (resume after a crash, pause for clarification)."""
    builder = StateGraph(GraphState, context_schema=AgentContext)
    builder.add_node("interpret", interpret)
    builder.add_node("clarify", clarify)
    builder.add_node("supervise", supervise)
    builder.add_node("extraction", extraction)
    builder.add_node("analytics", analytics)
    builder.add_node("report", report)
    builder.add_edge(START, "interpret")
    builder.add_edge("report", END)
    return builder.compile(checkpointer=checkpointer)
