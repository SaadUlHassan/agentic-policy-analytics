"""Source rate limits shared by every worker process (plan §4.4).

Each call to a rate-limited endpoint class claims the next slot in Redis with `SET NX PX`, so all
workers together stay within the published limit. When Redis is unreachable, calls fall back to
process-local spacing at twice the interval: with several workers that is still conservative.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass

import redis.asyncio as redis
import structlog

log = structlog.get_logger()

# Published limits are approached, never met: a slot is a little longer than window / calls.
SAFETY_MARGIN = 1.1
LOCAL_FALLBACK_FACTOR = 2.0


@dataclass(frozen=True)
class RateLimit:
    """Calls allowed per window for one endpoint class, by access tier ("none" = no API key)."""

    name: str
    window_s: float
    calls: Mapping[str, int]

    def interval_s(self, tier: str) -> float:
        return self.window_s / self.calls.get(tier, self.calls["none"]) * SAFETY_MARGIN


# Fallback spacing is per process, not per limiter: every analysis a worker runs shares it.
_local_last: dict[str, float] = {}
# One lock per (limit, event loop): an asyncio.Lock cannot be shared between loops.
_local_locks: dict[tuple[str, int], asyncio.Lock] = {}


class SharedRateLimiter:
    def __init__(self, client: redis.Redis | None) -> None:
        self.client = client

    async def wait(self, limit: RateLimit, tier: str) -> None:
        interval = limit.interval_s(tier)
        if self.client is not None:
            try:
                await self._shared(f"ratelimit:{limit.name}", interval)
                return
            except redis.RedisError as exc:
                log.warning("rate_limit_redis_unavailable", limit=limit.name, error=type(exc).__name__)
        await self._local(limit.name, interval * LOCAL_FALLBACK_FACTOR)

    async def _shared(self, key: str, interval_s: float) -> None:
        assert self.client is not None
        ttl_ms = math.ceil(interval_s * 1000)
        while not await self.client.set(key, "1", nx=True, px=ttl_ms):
            remaining = await self.client.pttl(key)
            await asyncio.sleep(max(remaining, 5) / 1000)

    async def _local(self, name: str, interval_s: float) -> None:
        lock = _local_locks.setdefault((name, id(asyncio.get_running_loop())), asyncio.Lock())
        async with lock:
            delay = interval_s - (time.monotonic() - _local_last.get(name, 0.0))
            if delay > 0:
                await asyncio.sleep(delay)
            _local_last[name] = time.monotonic()
