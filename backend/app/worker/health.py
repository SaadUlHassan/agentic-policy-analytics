"""Container health check for the worker: `python -m app.worker.health`.

Equivalent to `arq --check`, which passes while the worker keeps refreshing its health key in
Redis, but without importing the worker's settings module: that imports the whole application
(statistics, data and LLM libraries), which alone takes most of the check's time budget.
"""

from __future__ import annotations

import asyncio
import sys

import redis.asyncio as redis
from arq.constants import default_queue_name, health_check_key_suffix

from app.core.config import get_settings


async def main() -> int:
    client = redis.from_url(get_settings().redis_url)
    try:
        return 0 if await client.get(default_queue_name + health_check_key_suffix) else 1
    except redis.RedisError:
        return 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
