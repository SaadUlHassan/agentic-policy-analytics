"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, analyses, health
from app.api.problems import install_problem_handlers
from app.core.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.redis = redis.from_url(settings.redis_url)
    try:
        yield
    finally:
        await app.state.queue.aclose()
        await app.state.redis.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Agentic Policy Analytics API", version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_problem_handlers(app)
    app.include_router(health.router)
    app.include_router(analyses.router)
    if settings.enable_fault_injection:
        app.include_router(admin.router)
    return app


app = create_app()
