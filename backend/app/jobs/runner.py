"""Executes one claimed analysis: heartbeat, graph run or resume, pause, terminal status (plan §3.5, §3.7)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
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
from app.connectors.http import Fetcher, api_keys, get_snapshot_store
from app.connectors.ratelimit import SharedRateLimiter
from app.core.config import Provider, Settings
from app.core.faults import INJECTED, Faults
from app.data.models import NormalizedDataset
from app.data.taxonomy import get_taxonomy
from app.db.models import Analysis, AnalysisArtifact, AnalysisStatus, ComputationRow, DatasetArtifact
from app.jobs.checkpoint import FencedPostgresSaver, Pool
from app.jobs.lifecycle import (
    GRAPH_VERSION,
    HEARTBEAT_INTERVAL,
    AnalysisCancelled,
    LeaseLost,
    accepted_answer,
    claim,
    renew_lease,
)
from app.jobs.writer import FencedWriter
from app.llm.router import CallRecord, LLMRouter, LLMUnavailable

log = structlog.get_logger()
HEARTBEAT_S = HEARTBEAT_INTERVAL.total_seconds()


def _major(version: str) -> str:
    return version.split(".", 1)[0]


class ActiveClock:
    """This execution's running time, reported to active_ms_used by the heartbeat every interval
    and by the final pause/finish for the rest.

    Reports are serialised, and an interval counts as reported only once the write carrying it has
    committed. So the final transition waits for a heartbeat write in flight instead of racing it,
    and an interval whose write failed or was cancelled is carried by the next report."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self._reported_ms = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def report(self) -> AsyncIterator[int]:
        """Yield the unreported milliseconds; they count as reported if the block completes."""
        async with self._lock:
            elapsed = round((time.monotonic() - self.started) * 1000)
            yield elapsed - self._reported_ms
            self._reported_ms = elapsed


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
            # Say why: an injected demo fault must read as injected, never as a real outage.
            cause = (
                "switched off (injected fault (demo))"
                if INJECTED in (record.fallback_reason or "")
                else "unavailable"
            )
            await writer.emit(
                record.agent,
                "provider_fallback",
                f"{record.fallback_from} {cause}; answered by {record.provider}",
                {
                    "from": record.fallback_from,
                    "to": record.provider,
                    "purpose": record.purpose,
                    "reason": record.fallback_reason,
                },
            )

    # Only time spent running counts against the budget; a pause for clarification does not.
    clock = ActiveClock()
    remaining_s = max(0.0, settings.analysis_deadline_s - analysis.active_ms_used / 1000)
    faults = Faults(publisher, enabled=settings.enable_fault_injection)
    ctx = AgentContext(
        router=LLMRouter(settings=settings, models=dict(models or {}), on_record=on_record, faults=faults),
        writer=writer,
        catalog=get_catalog(),
        taxonomy=get_taxonomy(),
        fetcher=Fetcher(
            mode=settings.data_mode,
            snapshots=get_snapshot_store(),
            keys=api_keys(settings),
            limiter=SharedRateLimiter(publisher),
            faults=faults,
        ),
        deadline=clock.started + remaining_s,
    )

    graph = build_graph(FencedPostgresSaver(checkpoints, analysis_id=analysis_id, epoch=claimed.epoch))
    config: dict[str, Any] = {
        "configurable": {"thread_id": analysis.thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }

    async def finish(status: AnalysisStatus, **outcome: Any) -> str:
        async with clock.report() as ms:
            return (await writer.finish(status, active_ms=ms, **outcome)).value

    lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat(sessions, analysis_id, claimed.epoch, clock, lost, asyncio.current_task())
    )
    try:
        graph_input = await _graph_input(graph, config, claimed.kind, analysis.query, ctx, sessions)
        started_title = "Analysis started" if claimed.kind == "start" else "Analysis resumed"
        await writer.emit(
            "system", "status", started_title, {"status": "running", "attempt": claimed.attempt}
        )
        # durability="sync": each step's checkpoint commits before the next step starts.
        result = await graph.ainvoke(graph_input, config, context=ctx, durability="sync")
        if interrupts := result.get("__interrupt__"):
            async with clock.report() as ms:
                version = await writer.pause(interrupts[0].id, interrupts[0].value, active_ms=ms)
            return (AnalysisStatus.AWAITING_INPUT if version is not None else AnalysisStatus.CANCELLED).value
        return await finish(AnalysisStatus(result["status"]), report=result["report"])
    except LeaseLost:
        log.warning("lease_lost")
        return "lease_lost"
    except AnalysisCancelled:
        return await finish(AnalysisStatus.CANCELLED)
    except asyncio.CancelledError:
        if lost.is_set():
            log.warning("lease_lost_during_run")
            return "lease_lost"
        raise
    except (LLMUnavailable, GraphRecursionError) as exc:
        return await _finish_degraded(ctx, exc, analysis.query, finish)
    except Exception as exc:
        log.exception("analysis_failed")
        await writer.emit("system", "error", "Analysis failed", {"code": "INTERNAL_ERROR"})
        return await finish(
            AnalysisStatus.FAILED, error={"code": "INTERNAL_ERROR", "type": type(exc).__name__}
        )
    finally:
        await ctx.fetcher.aclose()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        structlog.contextvars.unbind_contextvars("analysis_id", "epoch")


async def _graph_input(
    graph: Any,
    config: dict[str, Any],
    kind: str,
    query: str,
    ctx: AgentContext,
    sessions: async_sessionmaker[AsyncSession],
) -> Any:
    """What to feed the graph for this claim: a fresh question, the researcher's answer to the
    pending interrupt, or nothing (continue from the last checkpoint). Resumes rebuild the evidence.

    The answer is looked up by interrupt id rather than taken from this claim's intent, so it
    survives a crash of the worker that first claimed it; once the checkpoint records that the
    interrupt was answered, it is no longer pending and the answer is not applied again."""
    snapshot = await graph.aget_state(config)
    if kind == "start" or not snapshot.values:
        return {"query": query}
    values = snapshot.values
    if values.get("plan"):
        ctx.plan = ResearchPlan.model_validate(values["plan"])
    if refs := values.get("evidence"):
        ctx.evidence = await _load_evidence(sessions, ctx.writer.analysis_id, refs)
    for pending in snapshot.interrupts:
        if (answer := await accepted_answer(sessions, ctx.writer.analysis_id, pending.id)) is not None:
            return Command(resume=answer)
    return None  # an unanswered interrupt is raised again, and the run pauses for it


async def _load_evidence(
    sessions: async_sessionmaker[AsyncSession], analysis_id: str, refs: dict[str, Any]
) -> Any:
    async with sessions() as session:
        rows = await session.execute(
            select(DatasetArtifact.content, AnalysisArtifact.fetch_record)
            .join(AnalysisArtifact, AnalysisArtifact.artifact_id == DatasetArtifact.artifact_id)
            .where(
                AnalysisArtifact.analysis_id == analysis_id,
                DatasetArtifact.artifact_id.in_(refs.get("artifacts", [])),
            )
        )
        computations = await session.scalars(
            select(ComputationRow).where(ComputationRow.analysis_id == analysis_id)
        )
        datasets = {}
        for content, fetch_record in rows:
            dataset = NormalizedDataset.model_validate(content).as_fetched(fetch_record)
            datasets[dataset.artifact_id] = dataset
        computed = {c.computation_id: Computation.model_validate(c.content) for c in computations}
    return from_refs(refs, datasets, computed)


async def _finish_degraded(
    ctx: AgentContext, exc: Exception, query: str, finish: Callable[..., Awaitable[str]]
) -> str:
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
        return await finish(AnalysisStatus.COMPLETED_WITH_LIMITATIONS, report=report)
    return await finish(AnalysisStatus.FAILED, error={"code": code, "detail": str(exc)[:500]})


async def _heartbeat(
    sessions: async_sessionmaker[AsyncSession],
    analysis_id: str,
    epoch: int,
    clock: ActiveClock,
    lost: asyncio.Event,
    main: asyncio.Task | None,
) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        async with clock.report() as ms:
            renewed = await renew_lease(sessions, analysis_id, epoch, active_ms=ms)
        if not renewed:
            lost.set()
            if main is not None:
                main.cancel()
            return
