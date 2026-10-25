from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.agents.react import run_react
from app.core.config import Settings
from app.llm.router import LLMRouter
from app.llm.scripted import ScriptedChatModel


class FakeWriter:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, dict]] = []

    async def emit(self, agent, type, title, detail=None):
        self.events.append((agent, type, title, detail or {}))
        return len(self.events)


class _Args(BaseModel):
    n: int
    rationale: str


class FakeCtx:
    def __init__(self, replies) -> None:
        self.model = ScriptedChatModel(replies=replies)
        self.router = LLMRouter(
            settings=Settings(_env_file=None), models={"bedrock": self.model}, backoff_s=0
        )
        self.writer = FakeWriter()
        self.deadline = float("inf")

    async def check_cancel(self) -> None:
        pass


def _many_calls(count: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "probe", "args": {"n": i, "rationale": f"step {i}"}, "id": f"c{i}", "type": "tool_call"}
            for i in range(count)
        ],
    )


def _probe_tool(executed: list[int]) -> StructuredTool:
    async def probe(n: int, rationale: str) -> str:
        executed.append(n)
        return f"ok {n}"

    return StructuredTool.from_function(coroutine=probe, name="probe", args_schema=_Args, description="probe")


async def test_budget_is_enforced_per_call_and_skipped_calls_are_answered():
    executed: list[int] = []
    ctx = FakeCtx([_many_calls(20)])

    outcome = await run_react(
        ctx, agent="analytics", system="s", task="t", tools=[_probe_tool(executed)], max_tool_calls=5
    )

    assert outcome.stop_reason == "budget" and executed == [0, 1, 2, 3, 4]
    assert len(ctx.model.calls) == 1  # no further model turn after the budget stop


async def test_rationale_is_taken_from_tool_arguments():
    executed: list[int] = []
    ctx = FakeCtx(
        [
            _many_calls(1),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "finish",
                        "args": {"summary": "done", "rationale": "All done."},
                        "id": "f",
                        "type": "tool_call",
                    }
                ],
            ),
        ]
    )

    outcome = await run_react(
        ctx, agent="extraction", system="s", task="t", tools=[_probe_tool(executed)], max_tool_calls=10
    )

    assert outcome.finished
    rationales = [title for _, type_, title, _ in ctx.writer.events if type_ == "rationale"]
    assert rationales == ["step 0", "All done."]
    calls = [detail for _, type_, _, detail in ctx.writer.events if type_ == "tool_call"]
    assert calls == [{"args": {"n": 0}}]  # rationale is shown once, not repeated in the call arguments


async def test_tool_errors_become_observations_and_two_in_a_row_stop_the_loop():
    ctx = FakeCtx(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "probe",
                        "args": {"n": "not-a-number", "rationale": "x"},
                        "id": "e1",
                        "type": "tool_call",
                    },
                    {
                        "name": "probe",
                        "args": {"n": "nope", "rationale": "x"},
                        "id": "e2",
                        "type": "tool_call",
                    },
                ],
            )
        ]
    )

    outcome = await run_react(
        ctx, agent="analytics", system="s", task="t", tools=[_probe_tool([])], max_tool_calls=10
    )

    assert outcome.stop_reason == "repeated tool errors"
    results = [d for _, type_, _, d in ctx.writer.events if type_ == "tool_result"]
    assert all(not r["ok"] and r["summary"].startswith("ERROR") for r in results)
