"""Analysis REST endpoints and the WebSocket event stream."""

from __future__ import annotations

import asyncio
import base64
import contextlib
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.problems import ProblemError
from app.db.models import TERMINAL_STATUSES, Analysis, ReportRow
from app.db.session import get_sessionmaker
from app.events.stream import PAGE_SIZE, events_after
from app.jobs.lifecycle import create_analysis, dispatch_pending
from app.jobs.writer import event_channel

log = structlog.get_logger()
router = APIRouter(tags=["analyses"])
WAKE_INTERVAL_S = 2.0

Sessions = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]


class CreateAnalysis(BaseModel):
    query: str = Field(min_length=3, max_length=1000)


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


@router.post("/api/analyses", status_code=202)
async def create(body: CreateAnalysis, request: Request, sessions: Sessions) -> JSONResponse:
    async with sessions() as session:
        analysis = await create_analysis(session, body.query.strip())
    try:
        await dispatch_pending(sessions, request.app.state.queue)
    except Exception:  # the worker's dispatch cron picks the intent up; the request still succeeded
        log.warning("immediate_dispatch_failed", analysis_id=analysis.id)
    return JSONResponse({"id": analysis.id, "status": analysis.status}, status_code=202)


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
    sessions: Sessions, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None
) -> dict[str, Any]:
    stmt = select(Analysis).order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(limit + 1)
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
    return {
        **_summary(analysis).model_dump(mode="json"),
        "plan": analysis.plan,
        "report": report,
        "error": analysis.error,
        "last_event_seq": analysis.last_event_seq,
    }


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
