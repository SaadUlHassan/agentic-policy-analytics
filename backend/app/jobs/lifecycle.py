"""Durable analysis lifecycle: outbox intents, atomic claims, leases (plan §3.7)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Analysis, AnalysisStatus, OutboxIntent

GRAPH_VERSION = "1"
PROMPT_VERSION = "1"
LEASE_TTL = timedelta(seconds=60)


class LeaseLost(Exception):
    """This execution no longer owns the analysis; it must stop without writing anything."""


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


async def renew_lease(sessions: async_sessionmaker[AsyncSession], analysis_id: str, epoch: int) -> bool:
    async with sessions() as session:
        result = await session.execute(
            text(
                "UPDATE analyses SET lease_expires_at = now() + :ttl, heartbeat_at = now() "
                "WHERE id = :id AND execution_epoch = :epoch AND status = 'running' RETURNING id"
            ),
            {"id": analysis_id, "epoch": epoch, "ttl": LEASE_TTL},
        )
        renewed = result.first() is not None
        await session.commit()
        return renewed
