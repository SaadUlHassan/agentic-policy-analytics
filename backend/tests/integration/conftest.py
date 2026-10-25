"""Integration fixtures: a dedicated test database, migrated once, truncated per test."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://policy:policy@localhost:5432/policy_test"
)
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def database_url() -> str:
    async def ensure_database() -> None:
        admin = TEST_DATABASE_URL.replace("+asyncpg", "").rsplit("/", 1)[0] + "/postgres"
        name = TEST_DATABASE_URL.rsplit("/", 1)[1]
        try:
            conn = await asyncpg.connect(admin)
        except (OSError, asyncpg.PostgresError) as exc:
            if os.environ.get("REQUIRE_INTEGRATION"):
                raise RuntimeError(f"Postgres required for integration tests: {exc}") from exc
            pytest.skip(f"Postgres not reachable for integration tests: {exc}")
        try:
            if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
                await conn.execute(f'CREATE DATABASE "{name}"')
        finally:
            await conn.close()

    import asyncio

    asyncio.run(ensure_database())
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=BACKEND,
        check=True,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
    )
    return TEST_DATABASE_URL


@pytest.fixture
async def sessions(database_url):
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE analyses, outbox, analysis_events, dataset_artifacts, analysis_artifacts, "
                "computations, reports, llm_calls RESTART IDENTITY CASCADE"
            )
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
