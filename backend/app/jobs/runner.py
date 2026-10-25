"""Executes one claimed analysis: heartbeat, graph run or resume, pause, terminal status (plan §3.5, §3.7)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Mapping
from typing import Any

import redis.asyncio as redis
import structlog
from langchain_core.language_models import BaseChatModel
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.context import AgentContext
from app.agents.evidence import from_refs
from app.agents.graph import RECURSION_LIMIT, build_graph
from app.agents.plan import ResearchPlan
from app.agents.report import build_report
from app.analytics.results import Computation
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.core.config import Provider, Settings
from app.data.models import NormalizedDataset
from app.data.taxonomy import get_taxonomy
from app.db.models import Analysis, AnalysisStatus, ComputationRow, DatasetArtifact
from app.jobs.checkpoint import FencedPostgresSaver, Pool
from app.jobs.lifecycle import GRAPH_VERSION, AnalysisCancelled, Claim, LeaseLost, claim, renew_lease
from app.jobs.writer import FencedWriter
from app.llm.router import CallRecord, LLMRouter, LLMUnavailable

log = structlog.get_logger()
HEARTBEAT_S = 15


def _major(version: str) -> str:
    return version.split(".", 1)[0]


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    publisher: redis.Redis | None,
    settings: Settings,
    analysis_id: str,
    intent_id: int,
    owner: str,
    *,
    checkpoints: Pool,
    models: Mapping[Provider, BaseChatModel] | None = None,
) -> str:
    claimed = await claim(sessions, analysis_id, intent_id, owner)
    if claimed is None:
        return "skipped"
    structlog.contextvars.bind_contextvars(analysis_id=analysis_id, epoch=claimed.epoch)
    writer = FencedWriter(sessions, publisher, analysis_id, claimed.epoch)
    async with sessions() as session:
        analysis = await session.get(Analysis, analysis_id)
    assert analysis is not None

    if _major(analysis.graph_version) != _major(GRAPH_VERSION):
        # A checkpoint from an incompatible graph cannot be resumed safely.
        await writer.finish(
            AnalysisStatus.FAILED,
            error={
                "code": "INCOMPATIBLE_CHECKPOINT",
                "detail": f"saved by graph {analysis.graph_version}, "
                f"this worker runs {GRAPH_VERSION}; start a new analysis",
            },
        )
        structlog.contextvars.unbind_contextvars("analysis_id", "epoch")
        return AnalysisStatus.FAILED.value

    async def on_record(record: CallRecord) -> None:
        await writer.record_llm_call(record)
        if record.ok and record.fallback_from:
            await writer.emit(
                record.agent,
                "provider_fallback",
                f"{record.fallback_from} unavailable; answered by {record.provider}",
                {"from": record.fallback_from, "to": record.provider, "purpose": record.purpose},
            )

    # Only time spent running counts against the budget; a pause for clarification does not.
    started = time.monotonic()
    remaining_s = max(0.0, settings.analysis_deadline_s - analysis.active_ms_used / 1000)
    ctx = AgentContext(
        router=LLMRouter(settings=settings, models=dict(models or {}), on_record=on_record),
        writer=writer,
        catalog=get_catalog(),
        taxonomy=get_taxonomy(),
        fetcher=Fetcher(mode=settings.data_mode, snapshots=get_snapshot_store()),
        deadline=started + remaining_s,
    )

    def active_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    graph = build_graph(FencedPostgresSaver(checkpoints, analysis_id=analysis_id, epoch=claimed.epoch))
    config: dict[str, Any] = {
        "configurable": {"thread_id": analysis.thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }
    lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat(sessions, analysis_id, claimed.epoch, lost, asyncio.current_task())
    )
    try:
        graph_input = await _graph_input(graph, config, claimed, analysis.query, ctx, sessions)
        started_title = "Analysis started" if claimed.kind == "start" else "Analysis resumed"
        await writer.emit(
            "system", "status", started_title, {"status": "running", "attempt": claimed.attempt}
        )
        # durability="sync": each step's checkpoint commits before the next step starts.
        result = await graph.ainvoke(graph_input, config, context=ctx, durability="sync")
        if interrupts := result.get("__interrupt__"):
            await ctx.check_cancel()  # a cancel that arrived during planning wins over the question
            await writer.pause(interrupts[0].id, interrupts[0].value, active_ms=active_ms())
            return AnalysisStatus.AWAITING_INPUT.value
        await writer.finish(AnalysisStatus(result["status"]), report=result["report"], active_ms=active_ms())
        return str(result["status"])
    except LeaseLost:
        log.warning("lease_lost")
        return "lease_lost"
    except AnalysisCancelled:
        await writer.finish(AnalysisStatus.CANCELLED, active_ms=active_ms())
        return AnalysisStatus.CANCELLED.value
    except asyncio.CancelledError:
        if lost.is_set():
            log.warning("lease_lost_during_run")
            return "lease_lost"
        raise
    except (LLMUnavailable, GraphRecursionError) as exc:
        return await _finish_degraded(ctx, exc, analysis.query, active_ms())
    except Exception as exc:
        log.exception("analysis_failed")
        await writer.emit("system", "error", "Analysis failed", {"code": "INTERNAL_ERROR"})
        await writer.finish(
            AnalysisStatus.FAILED,
            error={"code": "INTERNAL_ERROR", "type": type(exc).__name__},
            active_ms=active_ms(),
        )
        return AnalysisStatus.FAILED.value
    finally:
        await ctx.fetcher.aclose()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        structlog.contextvars.unbind_contextvars("analysis_id", "epoch")


async def _graph_input(
    graph: Any,
    config: dict[str, Any],
    claimed: Claim,
    query: str,
    ctx: AgentContext,
    sessions: async_sessionmaker[AsyncSession],
) -> Any:
    """What to feed the graph for this claim: a fresh question, the researcher's clarification, or
    nothing (continue from the last checkpoint after a crash). Resumes rebuild the evidence store."""
    snapshot = await graph.aget_state(config)
    if claimed.kind == "start" or not snapshot.values:
        return {"query": query}
    values = snapshot.values
    if values.get("plan"):
        ctx.plan = ResearchPlan.model_validate(values["plan"])
    if refs := values.get("evidence"):
        ctx.evidence = await _load_evidence(sessions, claimed.analysis_id, refs)
    if "clarification" in claimed.payload:
        return Command(resume=claimed.payload["clarification"])
    return None


async def _load_evidence(
    sessions: async_sessionmaker[AsyncSession], analysis_id: str, refs: dict[str, Any]
) -> Any:
    async with sessions() as session:
        artifacts = await session.scalars(
            select(DatasetArtifact).where(DatasetArtifact.artifact_id.in_(refs.get("artifacts", [])))
        )
        computations = await session.scalars(
            select(ComputationRow).where(ComputationRow.analysis_id == analysis_id)
        )
        datasets = {a.artifact_id: NormalizedDataset.model_validate(a.content) for a in artifacts}
        computed = {c.computation_id: Computation.model_validate(c.content) for c in computations}
    return from_refs(refs, datasets, computed)


async def _finish_degraded(ctx: AgentContext, exc: Exception, query: str, active_ms: int) -> str:
    """Report verified findings without narrative when possible; otherwise fail clearly."""
    code = "LLM_UNAVAILABLE" if isinstance(exc, LLMUnavailable) else "STEP_LIMIT"
    await ctx.writer.emit(
        "system", "error", "Agents could not continue", {"code": code, "detail": str(exc)[:300]}
    )
    if ctx.plan is not None and ctx.evidence.verified_claims():
        report = build_report(ctx.plan, ctx.evidence, narrative=None, question=query)
        report["limitations"].insert(
            0,
            {
                "source": "system",
                "text": f"Analysis stopped early ({code}); only findings verified before then are shown.",
            },
        )
        await ctx.writer.finish(AnalysisStatus.COMPLETED_WITH_LIMITATIONS, report=report, active_ms=active_ms)
        return AnalysisStatus.COMPLETED_WITH_LIMITATIONS.value
    await ctx.writer.finish(
        AnalysisStatus.FAILED, error={"code": code, "detail": str(exc)[:500]}, active_ms=active_ms
    )
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
