"""Fault injection for demos and resilience checks (plan §2, §9.2). Dev and test only.

A fault is a named switch in Redis with an expiry, so the API can set it and every worker sees it,
and a forgotten switch turns itself off. Switches only take effect when ENABLE_FAULT_INJECTION is
true, which the settings refuse in production. An injected failure is never disguised: it is
reported as injected wherever the real failure would be reported.
"""

from __future__ import annotations

import httpx
import redis.asyncio as redis
import structlog

log = structlog.get_logger()

# What can be switched off: an LLM provider, or a data source platform (by the hosts it serves from).
LLM_FAULTS = ("llm:bedrock", "llm:openai")
SOURCE_HOSTS = {
    "source:singstat": ("tablebuilder.singstat.gov.sg",),
    "source:datagov": ("data.gov.sg",),
    "source:mom": ("stats.mom.gov.sg",),
}
FAULTS = (*LLM_FAULTS, *SOURCE_HOSTS)
DEFAULT_TTL_S = 600
MAX_TTL_S = 3600
INJECTED = "injected fault (demo)"


class InjectedFault(Exception):
    """Raised in place of a provider call while its fault is switched on."""


def source_fault(url: str) -> str | None:
    host = httpx.URL(url).host
    return next(
        (
            name
            for name, hosts in SOURCE_HOSTS.items()
            if any(host == h or host.endswith(f".{h}") for h in hosts)
        ),
        None,
    )


class Faults:
    def __init__(self, client: redis.Redis | None, *, enabled: bool) -> None:
        self.client = client if enabled else None

    async def active(self, name: str) -> bool:
        if self.client is None:
            return False
        try:
            return bool(await self.client.exists(_key(name)))
        except redis.RedisError:
            return False  # a switchboard outage must not become an outage of its own

    async def switch_on(self, name: str, ttl_s: int = DEFAULT_TTL_S) -> None:
        assert self.client is not None and name in FAULTS
        await self.client.set(_key(name), "on", ex=min(ttl_s, MAX_TTL_S))
        log.warning("fault_switched_on", fault=name, ttl_s=ttl_s)

    async def switch_off(self, name: str | None = None) -> None:
        assert self.client is not None
        await self.client.delete(*[_key(n) for n in ([name] if name else FAULTS)])
        log.info("fault_switched_off", fault=name or "all")

    async def status(self) -> dict[str, int]:
        """Seconds until each switched-on fault turns itself off."""
        assert self.client is not None
        out: dict[str, int] = {}
        for name in FAULTS:
            ttl = await self.client.ttl(_key(name))
            if ttl >= 0:
                out[name] = ttl
        return out


def _key(name: str) -> str:
    return f"fault:{name}"
