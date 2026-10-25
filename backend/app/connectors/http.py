"""HTTP fetching for connectors: retries, rate spacing, snapshot mode and snapshot fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import httpx
import structlog
from pydantic import BaseModel

from app.core.config import get_settings

log = structlog.get_logger()

USER_AGENT = "policy-analytics/0.1 (research prototype)"


class RawPayload(BaseModel):
    url: str
    body: bytes
    sha256: str
    retrieved_at: datetime
    from_snapshot: bool
    fallback_reason: str | None = None

    def json_body(self) -> dict:
        return json.loads(self.body)


class SourceUnavailable(Exception):
    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{url}: {reason}")
        self.url, self.reason = url, reason


class SnapshotStore:
    """Real payloads captured by scripts/capture_snapshots.py, looked up by request URL."""

    def __init__(self, root: Path) -> None:
        self.root = root
        manifest = root / "manifest.json"
        entries = json.loads(manifest.read_text())["entries"] if manifest.exists() else []
        self._by_url = {e["url"]: e for e in entries}

    def load(self, url: str) -> RawPayload | None:
        entry = self._by_url.get(url)
        if entry is None:
            return None
        body = (self.root / entry["path"]).read_bytes()
        return RawPayload(
            url=url,
            body=body,
            sha256=entry["sha256"],
            retrieved_at=datetime.fromisoformat(entry["retrieved_at"]),
            from_snapshot=True,
        )


@lru_cache
def get_snapshot_store() -> SnapshotStore:
    return SnapshotStore(get_settings().data_dir / "snapshots")


class MinIntervalLimiter:
    """Spaces calls to one host. Process-local; sharing limits across workers comes with Redis."""

    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = min_interval_s
        self._last = 0.0
        self._locks: dict[int, asyncio.Lock] = {}

    async def wait(self) -> None:
        # One lock per event loop: an asyncio.Lock cannot be shared between loops.
        lock = self._locks.setdefault(id(asyncio.get_running_loop()), asyncio.Lock())
        async with lock:
            delay = self.min_interval_s - (time.monotonic() - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


class Fetcher:
    def __init__(
        self,
        *,
        mode: str,
        snapshots: SnapshotStore,
        client: httpx.AsyncClient | None = None,
        attempts: int = 3,
        backoff_s: float = 2.0,
    ) -> None:
        self.mode = mode
        self.snapshots = snapshots
        self.client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30,
            follow_redirects=True,
        )
        self.attempts = attempts
        self.backoff_s = backoff_s

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get(
        self, url: str, *, limiter: MinIntervalLimiter | None = None, must_contain: bytes | None = None
    ) -> RawPayload:
        """Fetch live, or from snapshots in snapshot mode. A live failure falls back to the
        snapshot of the same URL when one exists, recording why (it is disclosed downstream)."""
        if self.mode == "snapshot":
            if (snap := self.snapshots.load(url)) is not None:
                return snap
            raise SourceUnavailable(url, "no snapshot for this request")
        try:
            return await self._live(url, limiter, must_contain)
        except SourceUnavailable as exc:
            snap = self.snapshots.load(url)
            if snap is None:
                raise
            log.warning("source_fallback_to_snapshot", url=url, reason=exc.reason)
            return snap.model_copy(update={"fallback_reason": exc.reason})

    async def _live(
        self, url: str, limiter: MinIntervalLimiter | None, must_contain: bytes | None
    ) -> RawPayload:
        reason = "no attempt made"
        for attempt in range(self.attempts):
            if attempt:
                await asyncio.sleep(self.backoff_s * attempt)
            if limiter:
                await limiter.wait()
            try:
                resp = await self.client.get(url)
            except httpx.HTTPError as exc:
                reason = f"{type(exc).__name__}"
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                reason = f"HTTP {resp.status_code}"
                continue
            if resp.status_code >= 400:
                raise SourceUnavailable(url, f"HTTP {resp.status_code}")
            if must_contain is not None and must_contain not in resp.content:
                reason = "throttled (response missing expected content)"
                continue
            return RawPayload(
                url=url,
                body=resp.content,
                sha256=hashlib.sha256(resp.content).hexdigest(),
                retrieved_at=datetime.now(UTC),
                from_snapshot=False,
            )
        raise SourceUnavailable(url, f"failed after {self.attempts} attempts: {reason}")
