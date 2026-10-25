"""arq worker entrypoint: `arq app.worker.settings.WorkerSettings`."""

from __future__ import annotations

from typing import Any

import structlog
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging

log = structlog.get_logger()


async def ping(ctx: dict[str, Any]) -> str:
    """Liveness job used by `app.worker.smoke`."""
    return "pong"


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)
    log.info("worker_started")


class WorkerSettings:
    functions = [ping]
    on_startup = on_startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Heartbeat read by `arq --check` (compose healthcheck).
    health_check_interval = 15
