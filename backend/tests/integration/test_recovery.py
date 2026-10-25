"""Reconciler, clarification and cancellation contracts (plan §3.7, §8.1)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text

from app.db.models import AnalysisStatus, OutboxIntent
from app.events.stream import events_after
from app.jobs.lifecycle import (
    LeaseLost,
    LifecycleConflict,
    Reconciled,
    claim,
    dispatch_pending,
    reconcile,
    renew_lease,
    request_cancel,
    submit_clarification,
)
from app.jobs.writer import FencedWriter
from tests.integration.test_lifecycle import FakeQueue, _expire_lease, _new

pytestmark = pytest.mark.integration


async def _sql(sessions, sql: str, **params):
    async with sessions() as session:
        result = await session.execute(text(sql), params)
        await session.commit()
        return result


async def _row(sessions, analysis_id: str):
    result = await _sql(sessions, "SELECT * FROM analyses WHERE id = :id", id=analysis_id)
    return result.one()


async def _age_dispatch(sessions, analysis_id: str) -> None:
    """Pretend the dispatch happened long ago and no worker ever picked the job up."""
    await _sql(
        sessions,
        "UPDATE outbox SET dispatched_at = now() - interval '5 minutes' WHERE analysis_id = :id",
        id=analysis_id,
    )


async def _open_intents(sessions, analysis_id: str) -> list[OutboxIntent]:
    async with sessions() as session:
        return list(
            await session.scalars(
                select(OutboxIntent).where(
                    OutboxIntent.analysis_id == analysis_id,
                    OutboxIntent.acked_at.is_(None),
                    OutboxIntent.superseded_at.is_(None),
                )
            )
        )


async def _paused(sessions) -> tuple[str, FencedWriter, int]:
    """An analysis waiting for the researcher, as the runner leaves it after an interrupt."""
    analysis_id, intent = await _new(sessions)
    c = await claim(sessions, analysis_id, intent, "w")
    writer = FencedWriter(sessions, None, analysis_id, c.epoch)
    version = await writer.pause("interrupt-1", {"question": "Which sector?", "options": []}, active_ms=10)
    return analysis_id, writer, version


async def test_dispatched_job_lost_in_redis_before_pickup_redelivered_once(sessions):
    analysis_id, intent = await _new(sessions)
    await dispatch_pending(sessions, FakeQueue())  # delivered to a queue that is then lost
    await _age_dispatch(sessions, analysis_id)

    queue = FakeQueue()
    result = await reconcile(sessions, queue)
    assert result.redelivered == 1 and result.dispatched == 1
    assert queue.jobs == [("run_analysis", (analysis_id, intent), f"{analysis_id}:{intent}:2")]
    assert (await reconcile(sessions, queue)).redelivered == 0  # just redelivered: not stale yet

    assert await claim(sessions, analysis_id, intent, "w1") is not None
    assert await claim(sessions, analysis_id, intent, "w2") is None  # the lost copy, if it reappears


async def test_delivery_retries_do_not_consume_execution_attempts(sessions):
    analysis_id, intent = await _new(sessions)
    for _ in range(4):
        await dispatch_pending(sessions, FakeQueue())
        await _age_dispatch(sessions, analysis_id)
        await reconcile(sessions, FakeQueue())
    row = await _row(sessions, analysis_id)
    assert row.attempt == 0 and row.status == "queued"
    claimed = await claim(sessions, analysis_id, intent, "w")
    assert claimed.attempt == 1


async def test_expired_lease_reconciled_without_restart(sessions):
    analysis_id, intent = await _new(sessions)
    first = await claim(sessions, analysis_id, intent, "crashed-worker")
    await _expire_lease(sessions, analysis_id)

    queue = FakeQueue()
    result = await reconcile(sessions, queue)
    assert result.resumed == 1 and result.dispatched == 1
    (resume,) = await _open_intents(sessions, analysis_id)
    assert resume.kind == "resume" and queue.jobs[0][1] == (analysis_id, resume.id)
    assert (await reconcile(sessions, FakeQueue())).resumed == 0  # one recovery per expiry

    second = await claim(sessions, analysis_id, resume.id, "new-worker")
    assert second.epoch == first.epoch + 1 and second.attempt == 2
    with pytest.raises(LeaseLost):
        await FencedWriter(sessions, None, analysis_id, first.epoch).emit("system", "status", "stale")


async def test_exhausted_execution_attempts_fail_and_fence_the_old_owner(sessions):
    analysis_id, intent = await _new(sessions)
    c = await claim(sessions, analysis_id, intent, "w")
    await _sql(sessions, "UPDATE analyses SET attempt = 3 WHERE id = :id", id=analysis_id)
    await _expire_lease(sessions, analysis_id)

    result = await reconcile(sessions, FakeQueue())

    assert result.failed == 1 and result.resumed == 0
    row = await _row(sessions, analysis_id)
    assert row.status == "failed" and row.error["code"] == "RETRIES_EXHAUSTED"
    async with sessions() as session:
        last = (await events_after(session, analysis_id, 0))[-1]
    assert last["detail"] == {"status": "failed"}
    with pytest.raises(LeaseLost):
        await FencedWriter(sessions, None, analysis_id, c.epoch).finish(AnalysisStatus.COMPLETED)


async def test_healthy_long_run_not_reaped(sessions):
    analysis_id, intent = await _new(sessions)
    c = await claim(sessions, analysis_id, intent, "w")
    await _sql(
        sessions, "UPDATE analyses SET created_at = now() - interval '2 hours' WHERE id = :id", id=analysis_id
    )
    for _ in range(3):  # many reconcile passes over a run that keeps renewing its lease
        assert await renew_lease(sessions, analysis_id, c.epoch)
        assert await reconcile(sessions, FakeQueue()) == Reconciled()
    row = await _row(sessions, analysis_id)
    assert row.status == "running" and row.execution_epoch == c.epoch and row.attempt == 1


async def test_no_redelivery_for_terminal_or_awaiting_input(sessions):
    paused_id, _, _ = await _paused(sessions)
    done_id, intent = await _new(sessions)
    c = await claim(sessions, done_id, intent, "w")
    await FencedWriter(sessions, None, done_id, c.epoch).finish(AnalysisStatus.COMPLETED)
    for analysis_id in (paused_id, done_id):
        # A stray, never-acknowledged intent from earlier must not wake the analysis.
        await _sql(
            sessions,
            "INSERT INTO outbox (analysis_id, kind, payload, delivery_generation, dispatched_at) "
            "VALUES (:id, 'resume', '{}', 1, now() - interval '5 minutes')",
            id=analysis_id,
        )
    await _expire_lease(sessions, paused_id)

    queue = FakeQueue()
    result = await reconcile(sessions, queue)

    assert result.redelivered == 0 and result.resumed == 0 and queue.jobs == []


async def test_redis_restart_queue_rebuilt_from_outbox(sessions):
    queued_id, queued_intent = await _new(sessions)
    crashed_id, crashed_intent = await _new(sessions)
    await dispatch_pending(sessions, FakeQueue())
    await claim(sessions, crashed_id, crashed_intent, "w")
    # Redis restarts empty: the queued job is gone and the running worker died with it.
    await _age_dispatch(sessions, queued_id)
    await _expire_lease(sessions, crashed_id)

    queue = FakeQueue()
    await reconcile(sessions, queue)

    (resume,) = await _open_intents(sessions, crashed_id)
    assert sorted(job[1] for job in queue.jobs) == sorted(
        [(queued_id, queued_intent), (crashed_id, resume.id)]
    )


async def test_clarification_queues_one_resume_and_a_duplicate_is_stale(sessions):
    analysis_id, _, version = await _paused(sessions)
    change = await submit_clarification(sessions, analysis_id, version, {"answer": "ICT"})
    assert change.status == "queued"

    with pytest.raises(LifecycleConflict) as duplicate:
        await submit_clarification(sessions, analysis_id, version, {"answer": "ICT"})
    assert duplicate.value.code == "CLARIFICATION_STALE"
    (resume,) = await _open_intents(sessions, analysis_id)
    # Keyed by the interrupt it answers, so a later resume of that interrupt can always find it.
    assert resume.kind == "resume"
    assert resume.payload == {"clarification": {"answer": "ICT"}, "interrupt_id": "interrupt-1"}
    assert (await _row(sessions, analysis_id)).status == "queued"


async def test_concurrent_duplicate_clarifications_resume_once(sessions):
    analysis_id, _, version = await _paused(sessions)
    results = await asyncio.gather(
        *(submit_clarification(sessions, analysis_id, version, {"answer": "ICT"}) for _ in range(5)),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert {r.code for r in results if isinstance(r, LifecycleConflict)} == {"CLARIFICATION_STALE"}
    assert len(await _open_intents(sessions, analysis_id)) == 1


async def test_stale_clarification_version_409(sessions):
    analysis_id, _, version = await _paused(sessions)
    with pytest.raises(LifecycleConflict) as stale:
        await submit_clarification(sessions, analysis_id, version - 1, {"proceed": True})
    assert stale.value.code == "CLARIFICATION_STALE"

    running_id, intent = await _new(sessions)
    await claim(sessions, running_id, intent, "w")
    with pytest.raises(LifecycleConflict) as not_waiting:
        await submit_clarification(sessions, running_id, 0, {"proceed": True})
    assert not_waiting.value.code == "NOT_AWAITING_INPUT"


async def test_cancel_vs_clarify_race_single_winner(sessions):
    # Cancellation takes precedence: whichever request lands first, the analysis never resumes.
    for _ in range(5):
        analysis_id, _, version = await _paused(sessions)
        await asyncio.gather(
            submit_clarification(sessions, analysis_id, version, {"answer": "ICT"}),
            request_cancel(sessions, analysis_id),
            return_exceptions=True,
        )
        row = await _row(sessions, analysis_id)
        assert row.status == "cancelled" and await _open_intents(sessions, analysis_id) == []
        async with sessions() as session:
            intent = await session.scalar(
                select(OutboxIntent.id).where(
                    OutboxIntent.analysis_id == analysis_id, OutboxIntent.kind == "resume"
                )
            )
        if intent is not None:  # the answer landed first; its resume must not run
            assert await claim(sessions, analysis_id, intent, "w") is None


async def test_cancel_queued_now_running_on_request_terminal_409(sessions):
    queued_id, intent = await _new(sessions)
    change = await request_cancel(sessions, queued_id)
    assert change.status == "cancelled" and change.event_seq == 1
    assert await claim(sessions, queued_id, intent, "w") is None

    running_id, intent = await _new(sessions)
    await claim(sessions, running_id, intent, "w")
    change = await request_cancel(sessions, running_id)
    row = await _row(sessions, running_id)
    assert change.status == "running" and row.cancel_requested_at is not None

    with pytest.raises(LifecycleConflict) as terminal:
        await request_cancel(sessions, queued_id)
    assert terminal.value.code == "ALREADY_TERMINAL"


async def test_expired_lease_with_cancel_requested_is_cancelled_not_resumed(sessions):
    analysis_id, intent = await _new(sessions)
    c = await claim(sessions, analysis_id, intent, "crashed-worker")
    await request_cancel(sessions, analysis_id)
    await _expire_lease(sessions, analysis_id)

    result = await reconcile(sessions, FakeQueue())

    assert result.cancelled == 1 and result.resumed == 0
    assert (await _row(sessions, analysis_id)).status == "cancelled"
    with pytest.raises(LeaseLost):
        await FencedWriter(sessions, None, analysis_id, c.epoch).emit("system", "status", "stale")


async def test_recovery_charges_the_unreported_heartbeat_interval(sessions):
    analysis_id, intent = await _new(sessions)
    c = await claim(sessions, analysis_id, intent, "crashed-worker")
    assert await renew_lease(sessions, analysis_id, c.epoch, active_ms=30_000)  # two heartbeats' worth
    await _expire_lease(sessions, analysis_id)

    await reconcile(sessions, FakeQueue())

    # 30 s reported, plus at most one interval the worker ran before dying without reporting.
    assert (await _row(sessions, analysis_id)).active_ms_used == 30_000 + 15_000
