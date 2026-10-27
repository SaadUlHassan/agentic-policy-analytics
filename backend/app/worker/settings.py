"""arq worker entrypoint: `arq app.worker.settings.WorkerSettings`."""

from __future__ import annotations

import os
import socket
from typing import Any

import redis.asyncio as redis
import structlog
from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.jobs.checkpoint import ensure_tables, open_pool
from app.jobs.lifecycle import Reconciled, reconcile
from app.jobs.runner import execute

log = structlog.get_logger()


async def ping(ctx: dict[str, Any]) -> str:
    """Liveness job used by `app.worker.smoke`."""
    return "pong"


async def run_analysis(ctx: dict[str, Any], analysis_id: str, intent_id: int) -> str:
    settings = get_settings()
    return await execute(
        get_sessionmaker(),
        ctx["publisher"],
        settings,
        analysis_id,
        intent_id,
        owner=ctx["owner"],
        checkpoints=ctx["checkpoints"],
    )


async def reconciler(ctx: dict[str, Any]) -> None:
    """Dispatch, redeliver and recover analyses without relying on any process restarting."""
    result = await reconcile(get_sessionmaker(), ctx["redis"])
    if result != Reconciled():
        log.info("reconciled", **vars(result))


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["publisher"] = redis.from_url(settings.redis_url)
    ctx["owner"] = f"{socket.gethostname()}:{os.getpid()}"
    ctx["checkpoints"] = open_pool(settings.database_url)
    await ctx["checkpoints"].open()
    await ensure_tables(ctx["checkpoints"])
    log.info("worker_started", owner=ctx["owner"], llm_mode=settings.llm_mode)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["publisher"].aclose()
    await ctx["checkpoints"].close()


class WorkerSettings:
    functions = [ping, run_analysis]
    cron_jobs = [cron(reconciler, second={0, 15, 30, 45}, run_at_startup=True)]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 600
    # Heartbeat read by `arq --check` (compose healthcheck).
    health_check_interval = 15
