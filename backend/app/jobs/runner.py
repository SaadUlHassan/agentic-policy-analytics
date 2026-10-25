"""Executes one claimed analysis: heartbeat, graph run, terminal status (plan §3.5, §3.7)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Mapping

import redis.asyncio as redis
import structlog
from langchain_core.language_models import BaseChatModel
from langgraph.errors import GraphRecursionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.context import AgentContext
from app.agents.graph import RECURSION_LIMIT, build_graph
from app.agents.report import build_report
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.core.config import Provider, Settings
from app.data.taxonomy import get_taxonomy
from app.db.models import Analysis, AnalysisStatus
from app.jobs.lifecycle import LeaseLost, claim, renew_lease
from app.jobs.writer import FencedWriter
from app.llm.router import CallRecord, LLMRouter, LLMUnavailable

log = structlog.get_logger()
HEARTBEAT_S = 15


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    publisher: redis.Redis | None,
    settings: Settings,
    analysis_id: str,
    intent_id: int,
    owner: str,
    models: Mapping[Provider, BaseChatModel] | None = None,
) -> str:
    claimed = await claim(sessions, analysis_id, intent_id, owner)
    if claimed is None:
        return "skipped"
    structlog.contextvars.bind_contextvars(analysis_id=analysis_id, epoch=claimed.epoch)
    writer = FencedWriter(sessions, publisher, analysis_id, claimed.epoch)
    async with sessions() as session:
        query = await session.scalar(select(Analysis.query).where(Analysis.id == analysis_id))

    async def on_record(record: CallRecord) -> None:
        await writer.record_llm_call(record)
        if record.ok and record.fallback_from:
            await writer.emit(
                record.agent,
                "provider_fallback",
                f"{record.fallback_from} unavailable; answered by {record.provider}",
                {"from": record.fallback_from, "to": record.provider, "purpose": record.purpose},
            )

    ctx = AgentContext(
        router=LLMRouter(settings=settings, models=dict(models or {}), on_record=on_record),
        writer=writer,
        catalog=get_catalog(),
        taxonomy=get_taxonomy(),
        fetcher=Fetcher(mode=settings.data_mode, snapshots=get_snapshot_store()),
        deadline=time.monotonic() + settings.analysis_deadline_s,
    )
    lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat(sessions, analysis_id, claimed.epoch, lost, asyncio.current_task())
    )
    try:
        await writer.emit(
            "system", "status", "Analysis started", {"status": "running", "attempt": claimed.attempt}
        )
        result = await build_graph().ainvoke(
            {"query": query}, context=ctx, config={"recursion_limit": RECURSION_LIMIT}
        )
        await writer.finish(AnalysisStatus(result["status"]), report=result["report"])
        return result["status"]
    except LeaseLost:
        log.warning("lease_lost")
        return "lease_lost"
    except asyncio.CancelledError:
        if lost.is_set():
            log.warning("lease_lost_during_run")
            return "lease_lost"
        raise
    except (LLMUnavailable, GraphRecursionError) as exc:
        return await _finish_degraded(ctx, exc)
    except Exception as exc:
        log.exception("analysis_failed")
        await writer.emit("system", "error", "Analysis failed", {"code": "INTERNAL_ERROR"})
        await writer.finish(
            AnalysisStatus.FAILED, error={"code": "INTERNAL_ERROR", "type": type(exc).__name__}
        )
        return AnalysisStatus.FAILED.value
    finally:
        await ctx.fetcher.aclose()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        structlog.contextvars.unbind_contextvars("analysis_id", "epoch")


async def _finish_degraded(ctx: AgentContext, exc: Exception) -> str:
    """Report verified findings without narrative when possible; otherwise fail clearly."""
    code = "LLM_UNAVAILABLE" if isinstance(exc, LLMUnavailable) else "STEP_LIMIT"
    await ctx.writer.emit(
        "system", "error", "Agents could not continue", {"code": code, "detail": str(exc)[:300]}
    )
    if ctx.plan is not None and ctx.evidence.verified_claims():
        report = build_report(ctx.plan, ctx.evidence, narrative=None)
        report["limitations"].insert(
            0,
            {
                "source": "system",
                "text": f"Analysis stopped early ({code}); only findings verified before then are shown.",
            },
        )
        await ctx.writer.finish(AnalysisStatus.COMPLETED_WITH_LIMITATIONS, report=report)
        return AnalysisStatus.COMPLETED_WITH_LIMITATIONS.value
    await ctx.writer.finish(AnalysisStatus.FAILED, error={"code": code, "detail": str(exc)[:500]})
    return AnalysisStatus.FAILED.value


async def _heartbeat(
    sessions: async_sessionmaker[AsyncSession],
    analysis_id: str,
    epoch: int,
    lost: asyncio.Event,
    main: asyncio.Task | None,
) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        if not await renew_lease(sessions, analysis_id, epoch):
            lost.set()
            if main is not None:
                main.cancel()
            return
