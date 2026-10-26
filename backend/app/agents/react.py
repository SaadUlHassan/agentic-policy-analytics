"""ReAct loop (Reason -> Action -> Observation) shared by the Extraction and Analytics agents."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agents.context import AgentContext

FINISH_TOOL = "finish"
_MAX_OBSERVATION_CHARS = 6000


@dataclass
class ReactOutcome:
    finished: bool
    summary: str
    tool_calls: int
    stop_reason: str


def _short(value: object, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def run_react(
    ctx: AgentContext, *, agent: str, system: str, task: str, tools: Sequence[BaseTool], max_tool_calls: int
) -> ReactOutcome:
    """Drive the model through tool calls until it calls `finish`, stops calling tools, or hits
    the tool-call budget. Tool errors are returned to the model as observations so it can adapt."""
    by_name = {t.name: t for t in tools}
    messages: list[BaseMessage] = [SystemMessage(system), HumanMessage(task)]
    calls = 0
    consecutive_errors: dict[str, int] = {}
    while True:
        reply = await ctx.router.step(
            messages, tools, agent=agent, purpose="react_step", deadline=ctx.deadline
        )
        messages.append(reply)
        if not reply.tool_calls:
            return ReactOutcome(False, str(reply.content), calls, "model stopped calling tools")
        stop: ReactOutcome | None = None
        for call in reply.tool_calls:
            name, args = call["name"], call.get("args", {})
            if stop is None and calls >= max_tool_calls:
                stop = ReactOutcome(False, "tool-call budget reached", calls, "budget")
            if stop is not None:
                # Every tool call in a reply needs an answer, even the ones we decline to run.
                messages.append(ToolMessage(f"SKIPPED: {stop.stop_reason}", tool_call_id=call["id"]))
                continue
            calls += 1
            await ctx.check_cancel()
            # The public reasoning summary travels as a tool argument, so it is visible whatever the
            # provider does with free text (some return their explanation only as private reasoning).
            if rationale := str(args.get("rationale", "")).strip():
                await ctx.writer.emit(agent, "rationale", _short(rationale, 600), {"tool": name})
            if name == FINISH_TOOL:
                summary = str(args.get("summary", ""))
                await ctx.writer.emit(agent, "handoff", "Finished", {"summary": _short(summary, 1000)})
                return ReactOutcome(True, summary, calls, "finished")
            await ctx.writer.emit(
                agent, "tool_call", name, {"args": {k: v for k, v in args.items() if k != "rationale"}}
            )
            tool = by_name.get(name)
            if tool is None:
                observation, ok = f"ERROR: unknown tool {name!r}", False
            else:
                try:
                    observation, ok = await tool.ainvoke(args), True
                except Exception as exc:  # returned to the model, not raised: the agent decides what next
                    observation, ok = f"ERROR: {type(exc).__name__}: {exc}", False
            consecutive_errors[name] = 0 if ok else consecutive_errors.get(name, 0) + 1
            text = observation if isinstance(observation, str) else json.dumps(observation, default=str)
            await ctx.writer.emit(agent, "tool_result", name, {"ok": ok, "summary": _short(text)})
            messages.append(ToolMessage(text[:_MAX_OBSERVATION_CHARS], tool_call_id=call["id"]))
            if consecutive_errors[name] >= 2:
                stop = ReactOutcome(False, f"{name} failed twice in a row", calls, "repeated tool errors")
        if stop is not None:
            return stop
