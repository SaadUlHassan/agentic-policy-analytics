"""Every write an execution makes goes through FencedWriter, conditioned on its epoch (plan F2)."""

from __future__ import annotations

import contextlib
import json
from typing import Any

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analytics.results import Computation
from app.data.models import NormalizedDataset
from app.db.models import (
    TERMINAL_STATUSES,
    AnalysisArtifact,
    AnalysisEvent,
    AnalysisStatus,
    ComputationRow,
    DatasetArtifact,
    LLMCall,
    ReportRow,
)
from app.jobs.lifecycle import LeaseLost
from app.llm.router import CallRecord


def event_channel(analysis_id: str) -> str:
    return f"analysis:{analysis_id}:events"


class FencedWriter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        publisher: redis.Redis | None,
        analysis_id: str,
        epoch: int,
    ) -> None:
        self.sessions, self.publisher = sessions, publisher
        self.analysis_id, self.epoch = analysis_id, epoch

    async def _fence(
        self,
        session: AsyncSession,
        set_clause: str = "updated_at = now()",
        params: dict[str, Any] | None = None,
        returning: str = "id",
    ) -> Any:
        # set_clause/returning are fixed fragments from this module; values are always bound parameters.
        sql = f"UPDATE analyses SET {set_clause} WHERE id = :id AND execution_epoch = :epoch RETURNING {returning}"  # noqa: S608, E501
        bound = {"id": self.analysis_id, "epoch": self.epoch, **(params or {})}
        row = (await session.execute(text(sql), bound)).first()
        if row is None:
            raise LeaseLost(f"{self.analysis_id}: epoch {self.epoch} is no longer current")
        return row

    async def emit(self, agent: str, type: str, title: str, detail: dict[str, Any] | None = None) -> int:
        """Commit the event with the next per-analysis sequence number, then publish a wake-up hint."""
        async with self.sessions() as session:
            (seq,) = await self._fence(
                session, "last_event_seq = last_event_seq + 1", returning="last_event_seq"
            )
            session.add(
                AnalysisEvent(
                    analysis_id=self.analysis_id,
                    seq=seq,
                    agent=agent,
                    type=type,
                    title=title,
                    detail=detail or {},
                )
            )
            await session.commit()
        if self.publisher is not None:
            # Hints are best-effort; WebSocket readers also poll committed events.
            with contextlib.suppress(redis.RedisError):
                await self.publisher.publish(event_channel(self.analysis_id), str(seq))
        return seq

    async def save_artifact(self, dataset: NormalizedDataset) -> None:
        async with self.sessions() as session:
            await self._fence(session)
            await session.execute(
                insert(DatasetArtifact)
                .values(
                    artifact_id=dataset.artifact_id,
                    dataset_id=dataset.dataset_id,
                    platform=dataset.provenance.platform,
                    content=dataset.model_dump(mode="json"),
                )
                .on_conflict_do_nothing()
            )
            await session.execute(
                insert(AnalysisArtifact)
                .values(analysis_id=self.analysis_id, artifact_id=dataset.artifact_id)
                .on_conflict_do_nothing()
            )
            await session.commit()

    async def save_computation(self, computation: Computation) -> None:
        async with self.sessions() as session:
            await self._fence(session)
            await session.execute(
                insert(ComputationRow)
                .values(
                    analysis_id=self.analysis_id,
                    computation_id=computation.id,
                    fingerprint=computation.fingerprint,
                    tool=computation.tool,
                    content=computation.model_dump(mode="json"),
                )
                .on_conflict_do_nothing(index_elements=["analysis_id", "fingerprint"])
            )
            await session.commit()

    async def record_llm_call(self, record: CallRecord) -> None:
        async with self.sessions() as session:
            await self._fence(
                session,
                "input_tokens = input_tokens + :inp, output_tokens = output_tokens + :out",
                {"inp": record.input_tokens or 0, "out": record.output_tokens or 0},
            )
            session.add(
                LLMCall(
                    analysis_id=self.analysis_id,
                    agent=record.agent,
                    purpose=record.purpose,
                    provider=record.provider,
                    model=record.model,
                    ok=record.ok,
                    latency_ms=record.latency_ms,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    error=record.error,
                    fallback_from=record.fallback_from,
                )
            )
            await session.commit()

    async def save_plan(self, plan: dict[str, Any]) -> None:
        async with self.sessions() as session:
            await self._fence(session, "plan = CAST(:plan AS JSONB)", {"plan": _json(plan)})
            await session.commit()

    async def cancel_requested(self) -> bool:
        async with self.sessions() as session:
            (requested,) = await self._fence(session, returning="cancel_requested_at IS NOT NULL")
            await session.commit()
            return bool(requested)

    async def finish(
        self,
        status: AnalysisStatus,
        report: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Write the report and terminal status together, then announce it as the last event."""
        assert status in TERMINAL_STATUSES
        async with self.sessions() as session:
            await self._fence(
                session,
                "status = :status, finished_at = now(), lease_owner = NULL, "
                "lease_expires_at = NULL, error = CAST(:error AS JSONB), row_version = row_version + 1",
                {"status": status.value, "error": _json(error)},
            )
            if report is not None:
                await session.execute(
                    insert(ReportRow)
                    .values(analysis_id=self.analysis_id, content=report)
                    .on_conflict_do_update(index_elements=["analysis_id"], set_={"content": report})
                )
            await session.commit()
        await self.emit(
            "system", "status", f"Analysis {status.value.replace('_', ' ')}", {"status": status.value}
        )


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value)
