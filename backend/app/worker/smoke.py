"""Enqueue a `ping` job and wait for the worker's reply: `python -m app.worker.smoke`.

Used by `make smoke` and the CI compose job to prove the API -> Redis -> worker path.
"""

from __future__ import annotations

import asyncio
import sys

from arq import create_pool

from app.worker.settings import WorkerSettings


async def main() -> int:
    pool = await create_pool(WorkerSettings.redis_settings)
    try:
        job = await pool.enqueue_job("ping")
        if job is None:
            print("worker smoke: enqueue failed", file=sys.stderr)
            return 1
        result = await job.result(timeout=30)
    finally:
        await pool.aclose()
    print(f"worker smoke: {result}")
    return 0 if result == "pong" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
