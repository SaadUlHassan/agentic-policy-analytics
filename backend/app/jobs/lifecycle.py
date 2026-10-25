"""Durable analysis lifecycle: outbox intents, atomic claims, leases (plan §3.7)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import TERMINAL_STATUSES, Analysis, AnalysisStatus, OutboxIntent

GRAPH_VERSION = "1"
PROMPT_VERSION = "1"
LEASE_TTL = timedelta(seconds=60)
REDELIVER_AFTER = timedelta(seconds=60)
# A running execution adds its active time at every heartbeat, so a crash loses at most one interval.
HEARTBEAT_INTERVAL = timedelta(seconds=15)
MAX_ATTEMPTS = 3


class LeaseLost(Exception):
    """This execution no longer owns the analysis; it must stop without writing anything."""


class AnalysisCancelled(Exception):
    """The researcher asked to cancel; the execution stops at its next step boundary."""


class JobQueue(Protocol):
    async def enqueue_job(self, function: str, *args: Any, _job_id: str | None = None) -> Any: ...


@dataclass(frozen=True)
class Claim:
    analysis_id: str
    intent_id: int
    epoch: int
    attempt: int
    kind: str
    payload: dict


async def create_analysis(session: AsyncSession, query: str) -> Analysis:
    """Insert the analysis and its start intent in one transaction (no crash window)."""
    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        id=analysis_id,
        query=query,
        status=AnalysisStatus.QUEUED,
        thread_id=analysis_id,
        graph_version=GRAPH_VERSION,
        prompt_version=PROMPT_VERSION,
    )
    session.add(analysis)
    await session.flush()
    session.add(OutboxIntent(analysis_id=analysis_id, kind="start", payload={}))
    await session.commit()
    return analysis


def job_id(analysis_id: str, intent_id: int, generation: int) -> str:
    return f"{analysis_id}:{intent_id}:{generation}"


async def dispatch_pending(
    sessions: async_sessionmaker[AsyncSession], queue: JobQueue, limit: int = 50
) -> int:
    """Push undispatched intents to the queue. Safe to run concurrently (SKIP LOCKED)."""
    async with sessions() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, analysis_id, delivery_generation FROM outbox "
                    "WHERE dispatched_at IS NULL AND acked_at IS NULL AND superseded_at IS NULL "
                    "ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED"
                ),
                {"limit": limit},
            )
        ).all()
        for intent_id, analysis_id, generation in rows:
            await queue.enqueue_job(
                "run_analysis", analysis_id, intent_id, _job_id=job_id(analysis_id, intent_id, generation)
            )
            await session.execute(
                text("UPDATE outbox SET dispatched_at = now() WHERE id = :id"), {"id": intent_id}
            )
        await session.commit()
        return len(rows)


async def claim(
    sessions: async_sessionmaker[AsyncSession], analysis_id: str, intent_id: int, owner: str
) -> Claim | None:
    """Atomically take ownership for this intent, or return None if it is not ours to run.

    One transaction: lease + status running + epoch and execution attempt incremented + this
    intent acknowledged + every other open intent superseded. Concurrent claims serialise on the
    analysis row, so at most one succeeds.
    """
    async with sessions() as session:
        row = (
            await session.execute(
                text(
                    "UPDATE analyses SET status = 'running', execution_epoch = execution_epoch + 1, "
                    "attempt = attempt + 1, "
                    "lease_owner = :owner, lease_expires_at = now() + :ttl, heartbeat_at = now(), "
                    "row_version = row_version + 1 "
                    "WHERE id = :id AND status IN ('queued', 'running') "
                    "AND (lease_owner IS NULL OR lease_expires_at < now()) "
                    "AND EXISTS (SELECT 1 FROM outbox WHERE id = :intent AND analysis_id = :id "
                    "            AND acked_at IS NULL AND superseded_at IS NULL) "
                    "RETURNING execution_epoch, attempt"
                ),
                {"id": analysis_id, "intent": intent_id, "owner": owner, "ttl": LEASE_TTL},
            )
        ).first()
        if row is None:
            await session.rollback()
            return None
        intent = (
            await session.execute(
                text("UPDATE outbox SET acked_at = now() WHERE id = :intent RETURNING kind, payload"),
                {"intent": intent_id},
            )
        ).one()
        await session.execute(
            text(
                "UPDATE outbox SET superseded_at = now() WHERE analysis_id = :id AND id <> :intent "
                "AND acked_at IS NULL AND superseded_at IS NULL"
            ),
            {"id": analysis_id, "intent": intent_id},
        )
        await session.commit()
        return Claim(
            analysis_id=analysis_id,
            intent_id=intent_id,
            epoch=row.execution_epoch,
            attempt=row.attempt,
            kind=intent.kind,
            payload=intent.payload,
        )


async def renew_lease(
    sessions: async_sessionmaker[AsyncSession], analysis_id: str, epoch: int, active_ms: int = 0
) -> bool:
    """Extend the lease and add the active time spent since the previous renewal."""
    async with sessions() as session:
        result = await session.execute(
            text(
                "UPDATE analyses SET lease_expires_at = now() + :ttl, heartbeat_at = now(), "
                "active_ms_used = active_ms_used + :ms "
                "WHERE id = :id AND execution_epoch = :epoch AND status = 'running' RETURNING id"
            ),
            {"id": analysis_id, "epoch": epoch, "ttl": LEASE_TTL, "ms": active_ms},
        )
        renewed = result.first() is not None
        await session.commit()
        return renewed


class LifecycleConflict(Exception):
    """A researcher action that does not apply to the analysis's current state (mapped to 409)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


class AnalysisNotFound(Exception):
    pass


@dataclass(frozen=True)
class Transition:
    status: str
    event_seq: int | None  # the event this change appended, for the caller's wake-up hint


async def _append_event(session: AsyncSession, analysis_id: str, seq: int, title: str, detail: dict) -> None:
    await session.execute(
        text(
            "INSERT INTO analysis_events (analysis_id, seq, agent, type, title, detail) "
            "VALUES (:id, :seq, 'system', 'status', :title, CAST(:detail AS JSONB))"
        ),
        {"id": analysis_id, "seq": seq, "title": title, "detail": json.dumps(detail)},
    )


async def _conflict_for(session: AsyncSession, analysis_id: str, version: int | None = None) -> Exception:
    row = (
        await session.execute(
            text("SELECT status, clarification_version FROM analyses WHERE id = :id"), {"id": analysis_id}
        )
    ).first()
    if row is None:
        return AnalysisNotFound(analysis_id)
    if row.status in TERMINAL_STATUSES:
        return LifecycleConflict("ALREADY_TERMINAL", f"the analysis is already {row.status}")
    if version is not None and version != row.clarification_version:
        return LifecycleConflict(
            "CLARIFICATION_STALE",
            f"this answer is for question version {version}; the current version is "
            f"{row.clarification_version}",
        )
    return LifecycleConflict("NOT_AWAITING_INPUT", f"the analysis is {row.status}, not awaiting input")


async def submit_clarification(
    sessions: async_sessionmaker[AsyncSession], analysis_id: str, version: int, response: dict[str, Any]
) -> Transition:
    """Accept the researcher's answer to question `version` and queue the resume, in one transaction.

    The version is bumped on acceptance, so a duplicate submission of the same answer is stale."""
    async with sessions() as session:
        row = (
            await session.execute(
                text(
                    "UPDATE analyses SET status = 'queued', "
                    "clarification_version = clarification_version + 1, row_version = row_version + 1, "
                    "last_event_seq = last_event_seq + 1 "
                    "WHERE id = :id AND status = 'awaiting_input' AND clarification_version = :v "
                    "RETURNING last_event_seq, pending_interrupt_id"
                ),
                {"id": analysis_id, "v": version},
            )
        ).first()
        if row is None:
            await session.rollback()
            raise await _conflict_for(session, analysis_id, version)
        title = "Proceeding with stated assumptions" if response.get("proceed") else "Researcher answered"
        await _append_event(session, analysis_id, row.last_event_seq, title, {"status": "queued", **response})
        # The answer is keyed by the interrupt it answers, so any later resume of that interrupt
        # (including one after this intent's worker crashed) finds it: see accepted_answer().
        session.add(
            OutboxIntent(
                analysis_id=analysis_id,
                kind="resume",
                payload={"clarification": response, "interrupt_id": row.pending_interrupt_id},
            )
        )
        await session.commit()
        return Transition(AnalysisStatus.QUEUED.value, row.last_event_seq)


async def accepted_answer(
    sessions: async_sessionmaker[AsyncSession], analysis_id: str, interrupt_id: str
) -> dict[str, Any] | None:
    """The researcher's accepted answer to this interrupt, if there is one."""
    async with sessions() as session:
        answer = await session.scalar(
            text(
                "SELECT payload->'clarification' FROM outbox WHERE analysis_id = :id "
                "AND payload->>'interrupt_id' = :iid ORDER BY id DESC LIMIT 1"
            ),
            {"id": analysis_id, "iid": interrupt_id},
        )
    return answer


async def request_cancel(sessions: async_sessionmaker[AsyncSession], analysis_id: str) -> Transition:
    """Cancel a queued or paused analysis now; ask a running one to stop at its next step boundary.

    Cancellation takes precedence: an answer queued just before it never resumes, because a claim
    only succeeds on a queued or running analysis."""
    async with sessions() as session:
        # SET expressions see the row as it was, so `status` below is the status before this update.
        row = (
            await session.execute(
                text(
                    "UPDATE analyses SET cancel_requested_at = now(), row_version = row_version + 1, "
                    "status = CASE WHEN status = 'running' THEN status ELSE 'cancelled' END, "
                    "finished_at = CASE WHEN status = 'running' THEN NULL ELSE now() END, "
                    "pending_interrupt_id = NULL, "
                    "last_event_seq = CASE WHEN status = 'running' THEN last_event_seq "
                    "                 ELSE last_event_seq + 1 END "
                    "WHERE id = :id AND status IN ('queued', 'running', 'awaiting_input') "
                    "RETURNING status, last_event_seq"
                ),
                {"id": analysis_id},
            )
        ).first()
        if row is None:
            await session.rollback()
            raise await _conflict_for(session, analysis_id)
        if row.status == AnalysisStatus.RUNNING:
            await session.commit()
            return Transition(row.status, None)
        await _append_event(
            session, analysis_id, row.last_event_seq, "Analysis cancelled", {"status": "cancelled"}
        )
        await session.execute(
            text(
                "UPDATE outbox SET superseded_at = now() WHERE analysis_id = :id "
                "AND acked_at IS NULL AND superseded_at IS NULL"
            ),
            {"id": analysis_id},
        )
        await session.commit()
        return Transition(row.status, row.last_event_seq)


@dataclass(frozen=True)
class Reconciled:
    dispatched: int = 0
    redelivered: int = 0
    resumed: int = 0
    failed: int = 0
    cancelled: int = 0


async def reconcile(
    sessions: async_sessionmaker[AsyncSession],
    queue: JobQueue,
    *,
    redeliver_after: timedelta = REDELIVER_AFTER,
    max_attempts: int = MAX_ATTEMPTS,
) -> Reconciled:
    """Bring every non-terminal, non-paused analysis back to a state that will make progress.

    (b) An intent dispatched but never acknowledged (the job was lost before a worker claimed it) is
        re-dispatched under a new delivery generation. This does not count as an execution attempt.
    (c) A running analysis whose lease expired (its worker died) gets a resume intent, and is
        charged one heartbeat interval for the active time its worker never reported. It is
        cancelled instead if that was requested, or fails once it has used its execution attempts.
        Both bump the epoch, so the old owner stays fenced.
    (a) Undispatched intents, including those written here, are then dispatched.
    """
    async with sessions() as session:
        redelivered = await session.execute(
            text(
                "UPDATE outbox o SET delivery_generation = delivery_generation + 1, dispatched_at = NULL "
                "FROM analyses a WHERE a.id = o.analysis_id "
                "AND o.dispatched_at < now() - CAST(:after AS INTERVAL) "
                "AND o.acked_at IS NULL AND o.superseded_at IS NULL "
                "AND a.status IN ('queued', 'running') "
                "AND (a.lease_expires_at IS NULL OR a.lease_expires_at < now()) RETURNING o.id"
            ),
            {"after": redeliver_after},
        )
        # Expired leases with no open intent: crashed executions. Row locks keep concurrent
        # reconcilers from both acting on one analysis.
        expired = (
            await session.execute(
                text(
                    "SELECT id, attempt, cancel_requested_at IS NOT NULL AS cancel FROM analyses a "
                    "WHERE status = 'running' "
                    "AND lease_expires_at < now() AND NOT EXISTS (SELECT 1 FROM outbox o "
                    "WHERE o.analysis_id = a.id AND o.acked_at IS NULL AND o.superseded_at IS NULL) "
                    "FOR UPDATE SKIP LOCKED"
                )
            )
        ).all()
        resumed = failed = cancelled = 0
        for analysis_id, attempt, cancel in expired:
            if cancel:
                await _end(session, analysis_id, AnalysisStatus.CANCELLED)
                cancelled += 1
            elif attempt < max_attempts:
                await session.execute(
                    text("UPDATE analyses SET active_ms_used = active_ms_used + :ms WHERE id = :id"),
                    {"id": analysis_id, "ms": int(HEARTBEAT_INTERVAL.total_seconds() * 1000)},
                )
                session.add(OutboxIntent(analysis_id=analysis_id, kind="resume", payload={}))
                resumed += 1
            else:
                await _end(session, analysis_id, AnalysisStatus.FAILED, _exhausted(attempt))
                failed += 1
        await session.commit()
    dispatched = await dispatch_pending(sessions, queue)
    return Reconciled(dispatched, len(redelivered.all()), resumed, failed, cancelled)


async def _end(
    session: AsyncSession, analysis_id: str, status: AnalysisStatus, error: dict[str, Any] | None = None
) -> None:
    """Finish an analysis whose worker is gone, fencing that worker by bumping the epoch."""
    (seq,) = (
        await session.execute(
            text(
                "UPDATE analyses SET status = :status, finished_at = now(), "
                "execution_epoch = execution_epoch + 1, lease_owner = NULL, lease_expires_at = NULL, "
                "error = CAST(:error AS JSONB), row_version = row_version + 1, "
                "last_event_seq = last_event_seq + 1 WHERE id = :id RETURNING last_event_seq"
            ),
            {"id": analysis_id, "status": status.value, "error": json.dumps(error) if error else None},
        )
    ).one()
    title = f"Analysis {status.value}"
    await _append_event(session, analysis_id, seq, title, {"status": status.value})


def _exhausted(attempts: int) -> dict[str, Any]:
    return {
        "code": "RETRIES_EXHAUSTED",
        "detail": f"the worker stopped responding on {attempts} execution attempts; start a new analysis",
    }
