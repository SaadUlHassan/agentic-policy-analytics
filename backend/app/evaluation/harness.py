"""Live runs for the evaluation (plan §8.3): real providers, snapshot data, an isolated database.

Each analysis is executed by this process, with the provider order under test, through the same
runner the worker uses. The evaluation database and Redis db are separate from the stack's, so no
other worker's reconciler can claim these analyses, and fault switches set here affect only them.
Data comes from the committed snapshots, so the expected values stay pinned.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Provider, Settings, get_settings
from app.core.faults import Faults
from app.db.models import Analysis, AnalysisEvent, AnalysisStatus, OutboxIntent
from app.jobs.checkpoint import Pool, ensure_tables, open_pool
from app.jobs.lifecycle import create_analysis, submit_clarification
from app.jobs.runner import execute

EVAL_DATABASE_URL = os.environ.get(
    "EVAL_DATABASE_URL", "postgresql+asyncpg://policy:policy@localhost:5432/policy_eval"
)
EVAL_REDIS_URL = os.environ.get("EVAL_REDIS_URL", "redis://localhost:6379/14")
BACKEND = Path(__file__).resolve().parents[2]
FAULT_TTL_S = 900
_POLL_S = 0.25


async def _ensure_database(url: str) -> None:
    admin = url.replace("+asyncpg", "").rsplit("/", 1)[0] + "/postgres"
    name = url.rsplit("/", 1)[1]
    conn = await asyncpg.connect(admin)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@dataclass
class Environment:
    sessions: async_sessionmaker[AsyncSession]
    checkpoints: Pool
    redis: redis.Redis
    faults: Faults

    @classmethod
    async def open(cls) -> Environment:
        await _ensure_database(EVAL_DATABASE_URL)
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            check=True,
            env={**os.environ, "DATABASE_URL": EVAL_DATABASE_URL},
            capture_output=True,
        )
        checkpoints = open_pool(EVAL_DATABASE_URL)
        await checkpoints.open()
        await ensure_tables(checkpoints)
        client = redis.from_url(EVAL_REDIS_URL)
        await client.ping()
        engine = create_async_engine(EVAL_DATABASE_URL, pool_size=10)
        return cls(
            async_sessionmaker(engine, expire_on_commit=False),
            checkpoints,
            client,
            Faults(client, enabled=True),
        )

    async def close(self) -> None:
        await self.faults.switch_off()
        await self.checkpoints.close()
        await self.redis.aclose()

    def settings(self, order: tuple[Provider, ...]) -> Settings:
        return get_settings().model_copy(
            update={
                "database_url": EVAL_DATABASE_URL,
                "redis_url": EVAL_REDIS_URL,
                "data_mode": "snapshot",
                "llm_provider_order": list(order),
                "enable_fault_injection": True,
            }
        )


@dataclass(frozen=True)
class RunSpec:
    query: str
    order: tuple[Provider, ...]
    # Switched on before the run starts.
    faults: tuple[str, ...] = ()
    # Switched on once the first finding has been verified: a failure after evidence exists.
    late_faults: tuple[str, ...] = ()
    # An unexpected question is answered with "proceed with stated assumptions", so the rest of
    # the run can still be scored; an expected one ends the run.
    proceed_on_clarification: bool = True


@dataclass
class RunResult:
    analysis_id: str
    clarification: dict[str, Any] | None = None
    late_faults_after_seq: int | None = None


async def _events(sessions: async_sessionmaker[AsyncSession], analysis_id: str) -> list[AnalysisEvent]:
    async with sessions() as session:
        return list(
            await session.scalars(
                select(AnalysisEvent)
                .where(AnalysisEvent.analysis_id == analysis_id)
                .order_by(AnalysisEvent.seq)
            )
        )


async def _open_intent(sessions: async_sessionmaker[AsyncSession], analysis_id: str) -> int:
    async with sessions() as session:
        intent = await session.scalar(
            select(OutboxIntent.id)
            .where(
                OutboxIntent.analysis_id == analysis_id,
                OutboxIntent.acked_at.is_(None),
                OutboxIntent.superseded_at.is_(None),
            )
            .order_by(OutboxIntent.id.desc())
        )
    assert intent is not None, f"{analysis_id} has no open intent"
    return intent


async def _switch_on_after_first_finding(
    env: Environment, analysis_id: str, result: RunResult, names: tuple[str, ...]
) -> None:
    while True:
        for event in await _events(env.sessions, analysis_id):
            if event.type == "claim_verdict" and event.detail.get("passed"):
                for name in names:
                    await env.faults.switch_on(name, FAULT_TTL_S)
                result.late_faults_after_seq = event.seq
                return
        await asyncio.sleep(_POLL_S)


async def run(env: Environment, spec: RunSpec) -> RunResult:
    async with env.sessions() as session:
        analysis = await create_analysis(session, spec.query)
    result = RunResult(analysis.id)
    for name in spec.faults:
        await env.faults.switch_on(name, FAULT_TTL_S)
    watcher = (
        asyncio.create_task(_switch_on_after_first_finding(env, analysis.id, result, spec.late_faults))
        if spec.late_faults
        else None
    )
    settings = env.settings(spec.order)
    try:
        while True:
            outcome = await execute(
                env.sessions,
                env.redis,
                settings,
                analysis.id,
                await _open_intent(env.sessions, analysis.id),
                owner=f"eval:{os.getpid()}",
                checkpoints=env.checkpoints,
            )
            if outcome != AnalysisStatus.AWAITING_INPUT or result.clarification is not None:
                break
            question = next(
                e for e in reversed(await _events(env.sessions, analysis.id)) if e.type == "clarification"
            )
            result.clarification = question.detail
            if not spec.proceed_on_clarification:
                break
            async with env.sessions() as session:
                version = await session.scalar(
                    select(Analysis.clarification_version).where(Analysis.id == analysis.id)
                )
            assert version is not None
            await submit_clarification(env.sessions, analysis.id, version, {"proceed": True})
    finally:
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        for name in {*spec.faults, *spec.late_faults}:
            await env.faults.switch_off(name)
    return result
