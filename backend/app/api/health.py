"""Liveness/readiness endpoint: reports database and Redis reachability."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.db.session import get_engine

router = APIRouter(tags=["health"])

Check = Callable[[], Awaitable[None]]


async def check_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis() -> None:
    client = redis.from_url(get_settings().redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


def get_checks() -> dict[str, Check]:
    return {"database": check_database, "redis": check_redis}


async def _run(check: Check, limit_s: float) -> str:
    try:
        await asyncio.wait_for(check(), limit_s)
        return "ok"
    except Exception as exc:
        return f"error: {type(exc).__name__}"


@router.get("/api/health")
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    checks: Annotated[dict[str, Check], Depends(get_checks)],
) -> JSONResponse:
    names = list(checks)
    results = await asyncio.gather(*(_run(checks[n], settings.health_check_timeout_s) for n in names))
    status = dict(zip(names, results, strict=True))
    healthy = all(r == "ok" for r in results)
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "version": settings.app_version, "checks": status},
        status_code=200 if healthy else 503,
    )
