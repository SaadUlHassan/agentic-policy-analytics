"""Reading committed events for WebSocket delivery (plan §3.8).

PostgreSQL is authoritative. Redis pub/sub only wakes readers early; a periodic timer re-drains
committed rows, so an event published during replay, or a hint lost after commit, is still sent.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalysisEvent

PAGE_SIZE = 200


def serialise(event: AnalysisEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "ts": event.ts.isoformat(),
        "agent": event.agent,
        "type": event.type,
        "title": event.title,
        "detail": event.detail,
    }


async def events_after(
    session: AsyncSession, analysis_id: str, after_seq: int, limit: int = PAGE_SIZE
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(AnalysisEvent)
        .where(AnalysisEvent.analysis_id == analysis_id, AnalysisEvent.seq > after_seq)
        .order_by(AnalysisEvent.seq)
        .limit(limit)
    )
    return [serialise(e) for e in rows]
