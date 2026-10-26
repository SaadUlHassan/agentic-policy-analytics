"""Analysis REST endpoints and the WebSocket event stream."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import export as exports
from app.api.problems import ProblemError
from app.core.config import get_settings
from app.data.models import NormalizedDataset
from app.db.models import (
    TERMINAL_STATUSES,
    Analysis,
    AnalysisArtifact,
    AnalysisEvent,
    AnalysisStatus,
    DatasetArtifact,
    LLMCall,
    ReportRow,
)
from app.db.session import get_sessionmaker
from app.events.stream import PAGE_SIZE, events_after
from app.jobs.lifecycle import (
    AnalysisNotFound,
    LifecycleConflict,
    Transition,
    create_analysis,
    dispatch_pending,
    request_cancel,
    submit_clarification,
)
from app.jobs.writer import event_channel
from app.llm.pricing import usage_summary

log = structlog.get_logger()
router = APIRouter(tags=["analyses"])
WAKE_INTERVAL_S = 2.0

Sessions = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]


class CreateAnalysis(BaseModel):
    query: str = Field(min_length=3, max_length=1000)


class Clarify(BaseModel):
    clarification_version: int
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = (
        None
    )
    proceed_with_assumptions: bool = False

    @model_validator(mode="after")
    def _one_choice(self) -> Clarify:
        if (self.answer is None) == (not self.proceed_with_assumptions):
            raise ValueError("send either an answer or proceed_with_assumptions=true, not both")
        return self


class AnalysisSummary(BaseModel):
    id: str
    query: str
    status: str
    created_at: datetime
    finished_at: datetime | None


def _summary(a: Analysis) -> AnalysisSummary:
    return AnalysisSummary(
        id=a.id, query=a.query, status=a.status, created_at=a.created_at, finished_at=a.finished_at
    )


async def _dispatch(request: Request, sessions: async_sessionmaker[AsyncSession], analysis_id: str) -> None:
    try:
        await dispatch_pending(sessions, request.app.state.queue)
    except Exception:  # the worker's reconciler picks the intent up; the request still succeeded
        log.warning("immediate_dispatch_failed", analysis_id=analysis_id)


@router.post("/api/analyses", status_code=202)
async def create(body: CreateAnalysis, request: Request, sessions: Sessions) -> JSONResponse:
    async with sessions() as session:
        analysis = await create_analysis(session, body.query.strip())
    await _dispatch(request, sessions, analysis.id)
    return JSONResponse({"id": analysis.id, "status": analysis.status}, status_code=202)


async def _hint(request: Request, analysis_id: str, change: Transition) -> None:
    if change.event_seq is not None:
        with contextlib.suppress(Exception):  # a hint only; WebSocket readers also poll
            await request.app.state.redis.publish(event_channel(analysis_id), str(change.event_seq))


def _as_problem(exc: Exception) -> ProblemError:
    if isinstance(exc, LifecycleConflict):
        return ProblemError(409, exc.code, "Conflicting analysis state", exc.detail)
    return ProblemError(404, "ANALYSIS_NOT_FOUND", "Analysis not found")


@router.post("/api/analyses/{analysis_id}/clarify", status_code=202)
async def clarify(analysis_id: str, body: Clarify, request: Request, sessions: Sessions) -> JSONResponse:
    response: dict[str, Any] = {"proceed": True} if body.proceed_with_assumptions else {"answer": body.answer}
    try:
        change = await submit_clarification(sessions, analysis_id, body.clarification_version, response)
    except (LifecycleConflict, AnalysisNotFound) as exc:
        raise _as_problem(exc) from exc
    await _hint(request, analysis_id, change)
    await _dispatch(request, sessions, analysis_id)
    return JSONResponse({"id": analysis_id, "status": change.status}, status_code=202)


@router.post("/api/analyses/{analysis_id}/cancel", status_code=202)
async def cancel(analysis_id: str, request: Request, sessions: Sessions) -> JSONResponse:
    try:
        change = await request_cancel(sessions, analysis_id)
    except (LifecycleConflict, AnalysisNotFound) as exc:
        raise _as_problem(exc) from exc
    await _hint(request, analysis_id, change)
    # A running analysis stops at its next step boundary and then reports "cancelled" itself.
    return JSONResponse(
        {"id": analysis_id, "status": change.status, "cancel_requested": True}, status_code=202
    )


def _encode_cursor(a: Analysis) -> str:
    return base64.urlsafe_b64encode(f"{a.created_at.isoformat()}|{a.id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        created, analysis_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(created), analysis_id
    except ValueError as exc:
        raise ProblemError(400, "INVALID_CURSOR", "Invalid pagination cursor") from exc


@router.get("/api/analyses")
async def list_analyses(
    sessions: Sessions,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    status: AnalysisStatus | None = None,
) -> dict[str, Any]:
    stmt = select(Analysis).order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(limit + 1)
    if status is not None:
        stmt = stmt.where(Analysis.status == status)
    if cursor:
        created, analysis_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Analysis.created_at < created, and_(Analysis.created_at == created, Analysis.id < analysis_id)
            )
        )
    async with sessions() as session:
        rows = list(await session.scalars(stmt))
    page = rows[:limit]
    return {
        "items": [_summary(a).model_dump(mode="json") for a in page],
        "next_cursor": _encode_cursor(page[-1]) if len(rows) > limit else None,
    }


@router.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str, sessions: Sessions) -> dict[str, Any]:
    async with sessions() as session:
        analysis = await session.get(Analysis, analysis_id)
        if analysis is None:
            raise ProblemError(404, "ANALYSIS_NOT_FOUND", "Analysis not found")
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
        calls = await session.scalars(select(LLMCall).where(LLMCall.analysis_id == analysis_id))
        usage = {
            **usage_summary(calls, get_settings().llm_prices),
            "active_ms": analysis.active_ms_used,
        }
        question = None
        if analysis.status == AnalysisStatus.AWAITING_INPUT:
            question = await session.scalar(
                select(AnalysisEvent.detail)
                .where(AnalysisEvent.analysis_id == analysis_id, AnalysisEvent.type == "clarification")
                .order_by(AnalysisEvent.seq.desc())
                .limit(1)
            )
    return {
        **_summary(analysis).model_dump(mode="json"),
        "plan": analysis.plan,
        "report": report,
        "error": analysis.error,
        "clarification": question,
        "cancel_requested": analysis.cancel_requested_at is not None,
        "usage": usage,
        "last_event_seq": analysis.last_event_seq,
    }


_EXPORT_TYPES = {
    "md": ("text/markdown; charset=utf-8", "md"),
    "json": ("application/json", "json"),
    "csv": ("text/csv; charset=utf-8", "csv"),
}


@router.get("/api/analyses/{analysis_id}/export")
async def export(
    analysis_id: str, sessions: Sessions, format: Literal["md", "json", "csv"] = "md"
) -> Response:
    """The finished, verified result as stored: Markdown, a JSON bundle with pinned dataset
    versions, or a CSV of the source observations the findings rest on."""
    async with sessions() as session:
        analysis = await session.get(Analysis, analysis_id)
        if analysis is None:
            raise ProblemError(404, "ANALYSIS_NOT_FOUND", "Analysis not found")
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
        if report is None:
            raise ProblemError(
                409, "REPORT_NOT_AVAILABLE", "No report to export", f"the analysis is {analysis.status}"
            )
        artifacts = await session.scalars(
            select(DatasetArtifact)
            .join(AnalysisArtifact, AnalysisArtifact.artifact_id == DatasetArtifact.artifact_id)
            .where(AnalysisArtifact.analysis_id == analysis_id)
        )
        datasets = {a.artifact_id: NormalizedDataset.model_validate(a.content) for a in artifacts}
    meta = {
        **_summary(analysis).model_dump(mode="json"),
        "graph_version": analysis.graph_version,
        "prompt_version": analysis.prompt_version,
    }
    if format == "json":
        body = json.dumps(exports.to_bundle(meta, report, datasets), indent=2)
    elif format == "csv":
        body = exports.to_csv(exports.observation_rows(report, datasets))
    else:
        body = exports.to_markdown(meta, report)
    media_type, ext = _EXPORT_TYPES[format]
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="analysis-{analysis_id}.{ext}"'},
    )


async def _is_terminal(sessions: async_sessionmaker[AsyncSession], analysis_id: str) -> bool:
    async with sessions() as session:
        status = await session.scalar(select(Analysis.status).where(Analysis.id == analysis_id))
    return status in TERMINAL_STATUSES


@router.websocket("/ws/analyses/{analysis_id}")
async def stream(websocket: WebSocket, analysis_id: str, sessions: Sessions, after_seq: int = 0) -> None:
    async with sessions() as session:
        exists = await session.get(Analysis, analysis_id) is not None
    if not exists:
        await websocket.close(code=4404, reason="analysis not found")
        return
    await websocket.accept()
    pubsub = websocket.app.state.redis.pubsub()
    await pubsub.subscribe(event_channel(analysis_id))  # subscribe before the first drain: no gap
    cursor, finished = after_seq, False
    try:
        while True:
            async with sessions() as session:
                batch = await events_after(session, analysis_id, cursor)
            for event in batch:
                await websocket.send_json(event)
                cursor = event["seq"]
                finished |= event["type"] == "status" and event["detail"].get("status") in TERMINAL_STATUSES
            if len(batch) == PAGE_SIZE:
                continue
            if finished or (not batch and await _is_terminal(sessions, analysis_id)):
                break  # the second case: a client resuming at or after the terminal event
            with contextlib.suppress(TimeoutError):
                # A hint only wakes us early; the timer guarantees progress if a hint is lost.
                await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=WAKE_INTERVAL_S),
                    WAKE_INTERVAL_S + 0.5,
                )
        await websocket.close()
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
