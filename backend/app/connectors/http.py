"""HTTP fetching for connectors: retries, shared rate limits, API keys, snapshot mode and fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import httpx
import structlog
from pydantic import BaseModel

from app.connectors.ratelimit import RateLimit, SharedRateLimiter
from app.core.config import Settings, get_settings

log = structlog.get_logger()

USER_AGENT = "policy-analytics/0.1 (research prototype)"


class RawPayload(BaseModel):
    url: str
    body: bytes
    sha256: str
    retrieved_at: datetime
    from_snapshot: bool
    fallback_reason: str | None = None
    content_type: str | None = None

    def json_body(self) -> dict:
        return json.loads(self.body)


class SourceSchemaError(Exception):
    """A payload arrived but no longer has the structure the parser relies on (schema drift)."""

    def __init__(self, url: str, problem: str) -> None:
        super().__init__(f"{url}: {problem}")
        self.url, self.problem = url, problem


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
            content_type=entry.get("content_type"),
        )


@lru_cache
def get_snapshot_store() -> SnapshotStore:
    return SnapshotStore(get_settings().data_dir / "snapshots")


@dataclass(frozen=True)
class ApiKey:
    """A credential sent only to hosts under `host_suffix` (never to e.g. pre-signed storage URLs)."""

    host_suffix: str
    header: str
    value: str
    tier: str  # the rate-limit tier this key grants

    def applies_to(self, url: str) -> bool:
        host = httpx.URL(url).host
        return host == self.host_suffix or host.endswith(f".{self.host_suffix}")


def api_keys(settings: Settings) -> list[ApiKey]:
    keys = []
    if settings.datagov_api_key is not None:
        secret = settings.datagov_api_key.get_secret_value()
        keys.append(ApiKey("data.gov.sg", "x-api-key", secret, settings.datagov_key_tier))
    return keys


class Fetcher:
    def __init__(
        self,
        *,
        mode: str,
        snapshots: SnapshotStore,
        client: httpx.AsyncClient | None = None,
        keys: list[ApiKey] | None = None,
        limiter: SharedRateLimiter | None = None,
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
        self.keys = keys or []
        self.limiter = limiter or SharedRateLimiter(None)
        self.attempts = attempts
        self.backoff_s = backoff_s
        # Every payload used so far, by hash: stored alongside the datasets built from them.
        self.payloads: dict[str, RawPayload] = {}

    async def aclose(self) -> None:
        await self.client.aclose()

    def _key_for(self, url: str) -> ApiKey | None:
        return next((k for k in self.keys if k.applies_to(url)), None)

    async def get(
        self,
        url: str,
        *,
        rate: RateLimit | None = None,
        must_contain: bytes | None = None,
        accept: str | None = None,
    ) -> RawPayload:
        """Fetch live, or from snapshots in snapshot mode. A live failure falls back to the
        snapshot of the same URL when one exists, recording why (it is disclosed downstream)."""
        return await self._fetch(url, rate=rate, must_contain=must_contain, accept=accept)

    async def get_resolved(
        self, url: str, resolve: Callable[[], Awaitable[str]], *, rate: RateLimit | None = None
    ) -> RawPayload:
        """Fetch content whose real location is only known at request time (e.g. a pre-signed
        download URL). `url` is the stable identity used for snapshots and provenance; the resolved
        location is used once and never recorded."""
        return await self._fetch(url, rate=rate, resolve=resolve, accept="*/*")

    async def call(self, url: str, *, rate: RateLimit | None = None) -> RawPayload:
        """A live control-plane request (e.g. starting a download) whose response is used once and
        never recorded: such responses can embed temporary credentials."""
        return await self._live(url, rate, None, None)

    async def _fetch(
        self,
        url: str,
        *,
        rate: RateLimit | None,
        must_contain: bytes | None = None,
        resolve: Callable[[], Awaitable[str]] | None = None,
        accept: str | None = None,
    ) -> RawPayload:
        if self.mode == "snapshot":
            if (snap := self.snapshots.load(url)) is None:
                raise SourceUnavailable(url, "no snapshot for this request")
            return self._keep(snap)
        try:
            location = await resolve() if resolve else url
            payload = await self._live(location, rate, must_contain, accept)
            return self._keep(payload.model_copy(update={"url": url}))
        except SourceUnavailable as exc:
            snap = self.snapshots.load(url)
            if snap is None:
                raise
            log.warning("source_fallback_to_snapshot", url=url, reason=exc.reason)
            return self._keep(snap.model_copy(update={"fallback_reason": exc.reason}))

    def _keep(self, payload: RawPayload) -> RawPayload:
        self.payloads[payload.sha256] = payload
        return payload

    def _headers(self, url: str, accept: str | None) -> dict[str, str]:
        key = self._key_for(url)
        headers = {key.header: key.value} if key else {}
        if accept:
            headers["Accept"] = accept
        return headers

    async def _request(self, url: str, accept: str | None) -> httpx.Response:
        """GET, following one redirect by hand when a key is attached: httpx strips only the
        Authorization header across origins, so a custom key header would otherwise be forwarded
        to whatever host the redirect names."""
        if self._key_for(url) is None:
            return await self.client.get(url, headers=self._headers(url, accept))
        resp = await self.client.get(url, headers=self._headers(url, accept), follow_redirects=False)
        if resp.next_request is None:
            return resp
        target = str(resp.next_request.url)
        return await self.client.get(target, headers=self._headers(target, accept), follow_redirects=False)

    async def _live(
        self, url: str, rate: RateLimit | None, must_contain: bytes | None, accept: str | None
    ) -> RawPayload:
        key = self._key_for(url)
        reason = "no attempt made"
        for attempt in range(self.attempts):
            if attempt:
                await asyncio.sleep(self.backoff_s * attempt)
            if rate:
                await self.limiter.wait(rate, key.tier if key else "none")
            try:
                resp = await self._request(url, accept)
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
                content_type=resp.headers.get("content-type"),
            )
        raise SourceUnavailable(url, f"failed after {self.attempts} attempts: {reason}")
