from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import AnalysisEvent, AnalysisStatus, OutboxIntent
from app.events.stream import events_after
from app.jobs.lifecycle import LeaseLost, claim, create_analysis, dispatch_pending, renew_lease
from app.jobs.writer import FencedWriter
from tests.unit.test_analytics_tools import ICT_EMPLOYMENT, TOOLS, _ok, _series

pytestmark = pytest.mark.integration


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple, str | None]] = []

    async def enqueue_job(self, function, *args, _job_id=None):
        self.jobs.append((function, args, _job_id))


async def _new(sessions) -> tuple[str, int]:
    async with sessions() as session:
        analysis = await create_analysis(session, "Analyse ICT employment 2020-2024")
    async with sessions() as session:
        intent_id = await session.scalar(
            select(OutboxIntent.id).where(OutboxIntent.analysis_id == analysis.id)
        )
    return analysis.id, intent_id


async def _expire_lease(sessions, analysis_id: str) -> None:
    async with sessions() as session:
        await session.execute(
            text("UPDATE analyses SET lease_expires_at = now() - interval '1 second' WHERE id = :id"),
            {"id": analysis_id},
        )
        await session.commit()


async def _add_intent(sessions, analysis_id: str) -> int:
    async with sessions() as session:
        intent = OutboxIntent(analysis_id=analysis_id, kind="resume", payload={})
        session.add(intent)
        await session.commit()
        return intent.id


async def test_create_writes_analysis_and_start_intent_together(sessions):
    analysis_id, intent_id = await _new(sessions)
    async with sessions() as session:
        status = await session.scalar(text("SELECT status FROM analyses WHERE id = :id"), {"id": analysis_id})
    assert status == "queued" and intent_id is not None


async def test_dispatch_is_idempotent(sessions):
    analysis_id, intent_id = await _new(sessions)
    queue = FakeQueue()
    assert await dispatch_pending(sessions, queue) == 1
    assert await dispatch_pending(sessions, queue) == 0
    assert queue.jobs == [("run_analysis", (analysis_id, intent_id), f"{analysis_id}:{intent_id}:1")]


async def test_concurrent_claims_have_exactly_one_winner(sessions):
    analysis_id, intent_id = await _new(sessions)
    results = await asyncio.gather(
        *(claim(sessions, analysis_id, intent_id, f"worker-{i}") for i in range(5))
    )
    winners = [r for r in results if r is not None]
    assert len(winners) == 1 and winners[0].epoch == 1 and winners[0].attempt == 1


async def test_duplicate_delivery_after_ack_does_not_run_again(sessions):
    analysis_id, intent_id = await _new(sessions)
    assert await claim(sessions, analysis_id, intent_id, "w1") is not None
    await _expire_lease(sessions, analysis_id)
    assert await claim(sessions, analysis_id, intent_id, "w2") is None  # intent already acknowledged


async def test_claim_supersedes_other_open_intents(sessions):
    analysis_id, intent_id = await _new(sessions)
    extra = await _add_intent(sessions, analysis_id)
    assert await claim(sessions, analysis_id, intent_id, "w1") is not None
    async with sessions() as session:
        superseded = await session.scalar(select(OutboxIntent.superseded_at).where(OutboxIntent.id == extra))
    assert superseded is not None


async def test_stale_worker_is_fenced_after_takeover(sessions):
    analysis_id, intent_id = await _new(sessions)
    first = await claim(sessions, analysis_id, intent_id, "worker-a")
    old = FencedWriter(sessions, None, analysis_id, first.epoch)
    await old.emit("coordinator", "plan", "first plan")

    await _expire_lease(sessions, analysis_id)
    resume = await _add_intent(sessions, analysis_id)
    second = await claim(sessions, analysis_id, resume, "worker-b")
    assert second.epoch == first.epoch + 1 and second.attempt == 2

    with pytest.raises(LeaseLost):
        await old.emit("coordinator", "plan", "stale write")
    with pytest.raises(LeaseLost):
        await old.finish(AnalysisStatus.COMPLETED, report={"stale": True})
    assert not await renew_lease(sessions, analysis_id, first.epoch)
    assert await renew_lease(sessions, analysis_id, second.epoch)
    async with sessions() as session:
        titles = (await session.scalars(select(AnalysisEvent.title).order_by(AnalysisEvent.seq))).all()
    assert titles == ["first plan"]


async def test_events_get_consecutive_sequence_numbers_and_replay_in_order(sessions):
    analysis_id, intent_id = await _new(sessions)
    c = await claim(sessions, analysis_id, intent_id, "w")
    writer = FencedWriter(sessions, None, analysis_id, c.epoch)
    seqs = [await writer.emit("extraction", "tool_call", f"step {i}") for i in range(5)]
    assert seqs == [1, 2, 3, 4, 5]
    async with sessions() as session:
        replay = await events_after(session, analysis_id, after_seq=2)
    assert [e["seq"] for e in replay] == [3, 4, 5]


async def test_replayed_events_carry_their_commit_time_where_the_database_tracks_it(sessions):
    analysis_id, intent_id = await _new(sessions)
    c = await claim(sessions, analysis_id, intent_id, "w")
    async with sessions() as session:
        await FencedWriter(sessions, None, analysis_id, c.epoch)._append_event(
            session, "system", "status", "held", None
        )
        await asyncio.sleep(0.1)  # the transaction stays open after the event's timestamp is taken
        await session.commit()
    async with sessions() as session:
        tracked = await session.scalar(text("SELECT current_setting('track_commit_timestamp')::boolean"))
        (event,) = await events_after(session, analysis_id, 0)
    if tracked:  # the end-to-end stack: the commit came at least the held time after the start
        assert (
            datetime.fromisoformat(event["committed_at"]) - datetime.fromisoformat(event["ts"])
        ).total_seconds() >= 0.1
    else:  # not tracked: no commit time is claimed, and reading events still works
        assert event["committed_at"] is None


async def test_finish_writes_report_and_terminal_event(sessions):
    analysis_id, intent_id = await _new(sessions)
    c = await claim(sessions, analysis_id, intent_id, "w")
    writer = FencedWriter(sessions, None, analysis_id, c.epoch)
    await writer.finish(AnalysisStatus.COMPLETED, report={"claims": []})
    async with sessions() as session:
        status = await session.scalar(text("SELECT status FROM analyses WHERE id = :id"), {"id": analysis_id})
        last = (await events_after(session, analysis_id, 0))[-1]
    assert status == "completed" and last["type"] == "status" and last["detail"] == {"status": "completed"}


async def test_saving_the_same_computation_twice_is_idempotent(sessions):
    analysis_id, intent_id = await _new(sessions)
    c = await claim(sessions, analysis_id, intent_id, "w")
    writer = FencedWriter(sessions, None, analysis_id, c.epoch)
    computation = _ok(TOOLS.cagr(*_series(ICT_EMPLOYMENT), "2020", "2024"))
    await writer.save_computation(computation)
    await writer.save_computation(computation)
    async with sessions() as session:
        count = await session.scalar(select(func.count()).select_from(text("computations")))
    assert count == 1


async def test_report_status_and_terminal_event_commit_together_or_not_at_all(sessions):
    analysis_id, intent_id = await _new(sessions)
    c = await claim(sessions, analysis_id, intent_id, "w")
    writer = FencedWriter(sessions, None, analysis_id, c.epoch)
    await writer.emit("coordinator", "plan", "plan")
    # Occupy the next sequence number so the terminal event's insert fails inside finish().
    async with sessions() as session:
        await session.execute(
            text(
                "INSERT INTO analysis_events (analysis_id, seq, agent, type, title, detail) "
                "VALUES (:id, 2, 'x', 'x', 'blocker', '{}')"
            ),
            {"id": analysis_id},
        )
        await session.commit()

    with pytest.raises(IntegrityError):
        await writer.finish(AnalysisStatus.COMPLETED, report={"findings": []})

    async with sessions() as session:
        status = await session.scalar(text("SELECT status FROM analyses WHERE id = :id"), {"id": analysis_id})
        report = await session.scalar(
            text("SELECT count(*) FROM reports WHERE analysis_id = :id"), {"id": analysis_id}
        )
    assert status == "running" and report == 0  # nothing from finish() was committed
