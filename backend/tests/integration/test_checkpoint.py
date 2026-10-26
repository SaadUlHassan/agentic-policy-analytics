"""The fenced checkpointer: a stale execution cannot advance the graph (plan F2)."""

from __future__ import annotations

from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text

from app.jobs.checkpoint import FencedPostgresSaver
from app.jobs.lifecycle import LeaseLost, claim
from tests.integration.test_lifecycle import _add_intent, _expire_lease, _new

pytestmark = pytest.mark.integration


class S(TypedDict, total=False):
    steps: list[str]


def _graph(saver, on_second=None):
    async def first(state: S) -> S:
        return {"steps": [*state.get("steps", []), "first"]}

    async def second(state: S) -> S:
        if on_second:
            await on_second()
        return {"steps": [*state["steps"], "second"]}

    b = StateGraph(S)
    b.add_node("first", first)
    b.add_node("second", second)
    b.add_edge(START, "first")
    b.add_edge("first", "second")
    b.add_edge("second", END)
    return b.compile(checkpointer=saver)


async def test_stale_execution_cannot_write_a_checkpoint_and_the_new_owner_resumes(sessions, checkpoints):
    analysis_id, intent = await _new(sessions)
    a = await claim(sessions, analysis_id, intent, "worker-a")
    config = {"configurable": {"thread_id": analysis_id}}

    async def takeover() -> None:
        # While A runs node "second", its lease expires and B claims the analysis (epoch + 1).
        await _expire_lease(sessions, analysis_id)
        resume = await _add_intent(sessions, analysis_id)
        assert await claim(sessions, analysis_id, resume, "worker-b") is not None

    stale = _graph(
        FencedPostgresSaver(checkpoints, analysis_id=analysis_id, epoch=a.epoch), on_second=takeover
    )
    with pytest.raises(LeaseLost):
        # durability="sync": each checkpoint is committed before the next step starts.
        await stale.ainvoke({"steps": []}, config, durability="sync")

    # A's checkpoint after "first" was written while it owned the epoch; nothing after the takeover.
    async with sessions() as session:
        epoch = await session.scalar(
            text("SELECT execution_epoch FROM analyses WHERE id = :id"), {"id": analysis_id}
        )
    owner = _graph(FencedPostgresSaver(checkpoints, analysis_id=analysis_id, epoch=epoch))
    snapshot = await owner.aget_state(config)
    assert snapshot.values["steps"] == ["first"] and snapshot.next == ("second",)

    result = await owner.ainvoke(None, config, durability="sync")  # resume from the last good checkpoint
    assert result["steps"] == ["first", "second"]


async def test_checkpoint_write_with_a_wrong_epoch_is_refused(sessions, checkpoints):
    analysis_id, intent = await _new(sessions)
    c = await claim(sessions, analysis_id, intent, "w")
    wrong = _graph(FencedPostgresSaver(checkpoints, analysis_id=analysis_id, epoch=c.epoch + 5))
    with pytest.raises(LeaseLost):
        await wrong.ainvoke({"steps": []}, {"configurable": {"thread_id": analysis_id}}, durability="sync")
    async with checkpoints.connection() as conn:
        rows = await (
            await conn.execute("SELECT count(*) AS n FROM checkpoints WHERE thread_id = %s", (analysis_id,))
        ).fetchone()
    assert rows["n"] == 0
