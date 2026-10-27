"""Reading committed events for WebSocket delivery (plan §3.8).

PostgreSQL is authoritative. Redis pub/sub only wakes readers early; a periodic timer re-drains
committed rows, so an event published during replay, or a hint lost after commit, is still sent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalysisEvent

PAGE_SIZE = 200

# When the event's transaction committed, where the server tracks it (track_commit_timestamp, on in
# the end-to-end stack, which the load run measures). `ts` is when that transaction started.
_COMMITTED_AT = literal_column(
    "CASE WHEN current_setting('track_commit_timestamp')::boolean"
    " THEN pg_xact_commit_timestamp(analysis_events.xmin) END",
    type_=DateTime(timezone=True),
)


def serialise(event: AnalysisEvent, committed_at: datetime | None = None) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "ts": event.ts.isoformat(),
        "committed_at": committed_at.isoformat() if committed_at else None,
        "agent": event.agent,
        "type": event.type,
        "title": event.title,
        "detail": event.detail,
    }


async def events_after(
    session: AsyncSession, analysis_id: str, after_seq: int, limit: int = PAGE_SIZE
) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(AnalysisEvent, _COMMITTED_AT)
        .where(AnalysisEvent.analysis_id == analysis_id, AnalysisEvent.seq > after_seq)
        .order_by(AnalysisEvent.seq)
        .limit(limit)
    )
    return [serialise(event, committed_at) for event, committed_at in rows]
