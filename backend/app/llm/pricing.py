"""LLM usage and cost per analysis, from the call ledger (plan §4.7).

Prices are configuration, never guesses: LLM_PRICES maps a model id to USD per million input and
output tokens. When any model used is unpriced, the cost is reported as unknown rather than as a
partial total that would look complete.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from app.db.models import LLMCall


def usage_summary(calls: Iterable[LLMCall], prices: Mapping[str, tuple[float, float]]) -> dict[str, Any]:
    calls = list(calls)
    ok = [c for c in calls if c.ok]
    tokens_in = sum(c.input_tokens or 0 for c in ok)
    tokens_out = sum(c.output_tokens or 0 for c in ok)
    unpriced = sorted({c.model for c in ok if c.model not in prices})
    cost = None
    if ok and not unpriced:
        cost = sum(
            ((c.input_tokens or 0) * prices[c.model][0] + (c.output_tokens or 0) * prices[c.model][1]) / 1e6
            for c in ok
        )
    return {
        "llm_calls": len(calls),
        "failed_calls": len(calls) - len(ok),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "llm_latency_ms": sum(c.latency_ms for c in calls),
        "providers": dict(Counter(c.provider for c in ok)),
        "cost_usd": None if cost is None else round(cost, 6),
        "unpriced_models": unpriced,
    }
