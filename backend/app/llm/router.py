"""Multi-provider LLM router: ordered fallback, bounded retries, circuit breaking (plan §4.7).

The router is the only place retries happen. A retryable error (throttling, timeout, 5xx) is
retried on the same provider; anything else (access denied, invalid request) fails over at once.
Provider replies are normalised to text + tool calls, so private reasoning blocks never leave
the router and a conversation can continue on another provider.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast

import botocore.exceptions
import openai
import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from app.core.config import Provider, Settings
from app.core.faults import INJECTED, Faults, InjectedFault
from app.llm import providers

log = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)

_RETRYABLE_BEDROCK_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "InternalServerException",
    "ModelNotReadyException",
}
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    botocore.exceptions.ReadTimeoutError,
    botocore.exceptions.ConnectTimeoutError,
    botocore.exceptions.EndpointConnectionError,
)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, botocore.exceptions.ClientError):
        return exc.response.get("Error", {}).get("Code") in _RETRYABLE_BEDROCK_CODES
    return isinstance(exc, _RETRYABLE_EXCEPTIONS)


class LLMUnavailable(Exception):
    """No provider produced a usable answer within the deadline."""


class StructuredOutputError(Exception):
    pass


@dataclass
class CallRecord:
    provider: Provider
    model: str
    agent: str
    purpose: str
    ok: bool
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    fallback_from: Provider | None = None
    # Why the previous provider was given up on (e.g. an injected fault), when this is a fallback.
    fallback_reason: str | None = None


@dataclass
class _Circuit:
    threshold: int
    cooldown_s: float
    failures: int = 0
    opened_at: float | None = None
    last_error: str | None = None  # the failure that opened it, reported while it stays open

    def is_open(self, now: float) -> bool:
        if self.opened_at is None:
            return False
        if now - self.opened_at >= self.cooldown_s:
            self.opened_at, self.failures = None, 0  # half-open: allow a trial call
            return False
        return True

    def record(self, ok: bool, now: float, error: str | None = None) -> None:
        if ok:
            self.failures, self.opened_at, self.last_error = 0, None, None
            return
        self.failures += 1
        self.last_error = error
        if self.failures >= self.threshold:
            self.opened_at = now


def normalise(message: BaseMessage) -> AIMessage:
    """Keep only visible text and tool calls; drop provider-specific blocks such as reasoning."""
    content = message.content
    if isinstance(content, list):
        text = "".join(
            b if isinstance(b, str) else b.get("text", "")
            for b in content
            if isinstance(b, str) or b.get("type") == "text"
        )
    else:
        text = content
    tool_calls = getattr(message, "tool_calls", [])
    return AIMessage(
        content=text, tool_calls=tool_calls, usage_metadata=getattr(message, "usage_metadata", None)
    )


RecordSink = Callable[[CallRecord], Awaitable[None]]


@dataclass
class LLMRouter:
    settings: Settings
    models: dict[Provider, BaseChatModel] = field(default_factory=dict)
    on_record: RecordSink | None = None
    attempts_per_provider: int = 2
    per_call_timeout_s: float = 45.0
    fallback_reserve_s: float = 30.0
    backoff_s: float = 1.0
    circuit_threshold: int = 3
    circuit_cooldown_s: float = 60.0
    clock: Callable[[], float] = time.monotonic
    faults: Faults | None = None
    # Which provider answered each purpose, in order: e.g. whether a narrative check was made by a
    # different model from the one that wrote the narrative.
    answered_by: dict[str, list[Provider]] = field(default_factory=dict)
    _circuits: dict[Provider, _Circuit] = field(default_factory=dict)

    def model(self, provider: Provider) -> BaseChatModel:
        if provider not in self.models:
            self.models[provider] = providers.build(provider, self.settings)
        return self.models[provider]

    async def step(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[Any],
        *,
        agent: str,
        purpose: str,
        deadline: float | None = None,
    ) -> AIMessage:
        """One model turn with tools bound (a ReAct step)."""

        async def call(model: BaseChatModel, limit_s: float) -> tuple[AIMessage, Any]:
            raw = await asyncio.wait_for(model.bind_tools(list(tools)).ainvoke(list(messages)), limit_s)
            return normalise(raw), raw

        return await self._run(call, agent=agent, purpose=purpose, deadline=deadline)

    async def structured(
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        agent: str,
        purpose: str,
        deadline: float | None = None,
        prefer_independent: bool = False,
    ) -> T:
        """A schema-validated answer, with one repair attempt per provider before failing over.

        `prefer_independent` tries the providers in reverse order, so a check of text written by the
        primary provider is made by a different model whenever that model is available."""

        async def call(model: BaseChatModel, limit_s: float) -> tuple[T, Any]:
            runnable = model.with_structured_output(schema, include_raw=True)
            history = list(messages)
            ends_at = (
                self.clock() + limit_s
            )  # the repair attempt shares this budget; it does not get a fresh one
            for repair in (False, True):
                remaining = ends_at - self.clock()
                if remaining <= 0:
                    raise TimeoutError("no time left for a structured-output repair")
                out = cast(dict[str, Any], await asyncio.wait_for(runnable.ainvoke(history), remaining))
                if out.get("parsed") is not None and out.get("parsing_error") is None:
                    return out["parsed"], out.get("raw")
                if repair:
                    break
                history = [
                    *history,
                    HumanMessage(
                        f"Your previous reply did not match the schema ({out.get('parsing_error')}). "
                        "Reply again using exactly the required structure."
                    ),
                ]
            raise StructuredOutputError(f"invalid {schema.__name__}: {out.get('parsing_error')}")

        order = list(reversed(self.settings.llm_provider_order)) if prefer_independent else None
        return await self._run(call, agent=agent, purpose=purpose, deadline=deadline, order=order)

    async def _run(
        self,
        call: Callable[[BaseChatModel, float], Awaitable[tuple[Any, Any]]],
        *,
        agent: str,
        purpose: str,
        deadline: float | None,
        order: list[Provider] | None = None,
    ) -> Any:
        order = order or list(self.settings.llm_provider_order)
        errors: list[str] = []
        previous_failed: Provider | None = None
        previous_error: str | None = None
        for index, provider in enumerate(order):
            circuit = self._circuits.setdefault(
                provider, _Circuit(self.circuit_threshold, self.circuit_cooldown_s)
            )
            if circuit.is_open(self.clock()):
                errors.append(f"{provider}: circuit open")
                previous_failed = provider
                previous_error = f"circuit open after {circuit.last_error or 'repeated failures'}"
                continue
            is_last = index == len(order) - 1
            for attempt in range(self.attempts_per_provider):
                timeout = self._timeout(deadline, reserve=not is_last)
                if timeout <= 0 and not is_last and self._timeout(deadline, reserve=False) > 0:
                    # Too little time for this provider and a fallback: give it all to the fallback.
                    errors.append(f"{provider}: skipped to leave the remaining time to the fallback")
                    previous_failed = provider
                    previous_error = "skipped to leave the remaining time to the fallback"
                    break
                if timeout <= 0:
                    raise LLMUnavailable("; ".join([*errors, "deadline exceeded"]))
                started = self.clock()
                try:
                    if self.faults is not None and await self.faults.active(f"llm:{provider}"):
                        raise InjectedFault(f"{provider} switched off ({INJECTED})")
                    result, raw = await call(self.model(provider), timeout)
                except Exception as exc:
                    retry = is_retryable(exc) and attempt + 1 < self.attempts_per_provider
                    await self._record(
                        provider, agent, purpose, started, None, exc, previous_failed, previous_error
                    )
                    if retry:
                        await asyncio.sleep(self.backoff_s * (attempt + 1))
                        continue
                    failure = f"{type(exc).__name__}: {str(exc)[:160]}"
                    circuit.record(False, self.clock(), failure)
                    errors.append(f"{provider}: {failure}")
                    previous_failed, previous_error = provider, failure
                    break
                circuit.record(True, self.clock())
                await self._record(
                    provider, agent, purpose, started, raw, None, previous_failed, previous_error
                )
                self.answered_by.setdefault(purpose, []).append(provider)
                return result
        raise LLMUnavailable("; ".join(errors) or "no providers configured")

    def _timeout(self, deadline: float | None, *, reserve: bool) -> float:
        if deadline is None:
            return self.per_call_timeout_s
        remaining = deadline - self.clock() - (self.fallback_reserve_s if reserve else 0)
        return min(self.per_call_timeout_s, remaining)

    async def _record(
        self,
        provider: Provider,
        agent: str,
        purpose: str,
        started: float,
        raw: Any,
        exc: BaseException | None,
        fallback_from: Provider | None,
        fallback_reason: str | None = None,
    ) -> None:
        usage = getattr(raw, "usage_metadata", None) or {}
        record = CallRecord(
            provider=provider,
            model=providers.model_id(provider, self.settings),
            agent=agent,
            purpose=purpose,
            ok=exc is None,
            latency_ms=int((self.clock() - started) * 1000),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            error=None if exc is None else f"{type(exc).__name__}: {str(exc)[:200]}",
            fallback_from=fallback_from,
            fallback_reason=fallback_reason if fallback_from else None,
        )
        log.info("llm_call", **{k: v for k, v in record.__dict__.items() if k != "error"}, error=record.error)
        if self.on_record is not None:
            await self.on_record(record)
