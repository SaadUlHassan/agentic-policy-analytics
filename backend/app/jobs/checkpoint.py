"""LangGraph checkpoints in Postgres, fenced by the execution epoch (plan §3.7, F2).

A worker that lost its lease must not advance the graph. Every checkpoint write therefore runs in
one transaction that takes a per-analysis advisory lock (serialising checkpoint commits) and
re-checks that this execution's epoch is still current. The epoch row is read FOR SHARE, so a
concurrent claim, which updates that row, waits until the checkpoint commit finishes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres import _ainternal
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, AsyncCursor
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from app.jobs.lifecycle import LeaseLost


def checkpoint_conninfo(database_url: str) -> str:
    """The checkpointer uses psycopg; the app's SQLAlchemy URL names the asyncpg driver."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


Pool = AsyncConnectionPool[AsyncConnection[DictRow]]


def open_pool(database_url: str) -> Pool:
    return AsyncConnectionPool(
        checkpoint_conninfo(database_url),
        connection_class=AsyncConnection[DictRow],
        open=False,
        max_size=8,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )


async def ensure_tables(pool: Pool) -> None:
    """Create LangGraph's checkpoint tables (idempotent)."""
    await AsyncPostgresSaver(pool).setup()


class FencedPostgresSaver(AsyncPostgresSaver):
    def __init__(self, pool: Pool, *, analysis_id: str, epoch: int) -> None:
        super().__init__(pool)
        self.analysis_id, self.epoch = analysis_id, epoch

    @asynccontextmanager
    async def _cursor(self, *, pipeline: bool = False) -> AsyncIterator[AsyncCursor[DictRow]]:
        if not pipeline:  # reads: no fencing needed
            async with super()._cursor() as cur:
                yield cur
            return
        # Writes (aput, aput_writes, adelete_thread): fence and commit atomically.
        async with (
            self.lock,
            _ainternal.get_connection(self.conn) as conn,
            conn.transaction(),
            conn.cursor(binary=True, row_factory=dict_row) as cur,
        ):
            await cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.analysis_id,))
            await cur.execute(
                "SELECT 1 FROM analyses WHERE id = %s AND execution_epoch = %s FOR SHARE",
                (self.analysis_id, self.epoch),
            )
            if await cur.fetchone() is None:
                raise LeaseLost(f"{self.analysis_id}: epoch {self.epoch} may not write checkpoints")
            yield cur
