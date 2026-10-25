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
from app.jobs.lifecycle import dispatch_pending
from app.jobs.runner import execute

log = structlog.get_logger()


async def ping(ctx: dict[str, Any]) -> str:
    """Liveness job used by `app.worker.smoke`."""
    return "pong"


async def run_analysis(ctx: dict[str, Any], analysis_id: str, intent_id: int) -> str:
    return await execute(
        get_sessionmaker(), ctx["publisher"], get_settings(), analysis_id, intent_id, owner=ctx["owner"]
    )


async def dispatch(ctx: dict[str, Any]) -> int:
    """Re-dispatch intents whose immediate enqueue never happened (e.g. the API crashed after commit)."""
    return await dispatch_pending(get_sessionmaker(), ctx["redis"])


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["publisher"] = redis.from_url(settings.redis_url)
    ctx["owner"] = f"{socket.gethostname()}:{os.getpid()}"
    log.info("worker_started", owner=ctx["owner"])


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["publisher"].aclose()


class WorkerSettings:
    functions = [ping, run_analysis]
    cron_jobs = [cron(dispatch, second=set(range(0, 60, 5)), run_at_startup=True)]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 600
    # Heartbeat read by `arq --check` (compose healthcheck).
    health_check_interval = 15
