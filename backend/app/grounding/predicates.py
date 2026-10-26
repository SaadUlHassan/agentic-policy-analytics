"""Closed registry of statement types a claim may make about a computed value."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from app.analytics.results import ValueKind
from app.grounding.contracts import ClaimKind

Sign = Literal["positive", "negative"] | None

_CHANGE_KINDS = frozenset({ValueKind.ABS_CHANGE, ValueKind.PCT_CHANGE, ValueKind.PP_CHANGE})


@dataclass(frozen=True)
class Predicate:
    id: str
    tools: frozenset[str]
    value_kinds: frozenset[ValueKind]
    claim_kinds: frozenset[ClaimKind]
    sign: Sign
    # Placeholders: {subject} {value} {t0} {t1}; compare_periods adds {a0} {a1} {b0} {b1};
    # correlate adds {subject_b} {lag_phrase} {measure} {n}.
    template: str
    description: str
    # Strength rule on |value| (correlations): at least `min_abs`, or below `max_abs`.
    min_abs: float | None = None
    max_abs: float | None = None


_MEASURED = frozenset({ClaimKind.MEASURED})
_COMPARISON = frozenset({ClaimKind.COMPARISON, ClaimKind.MEASURED})
_CHANGE_TOOLS = frozenset({"change_between", "yoy_change"})
_ASSOCIATION = frozenset({ClaimKind.ASSOCIATION})
# |r| below this is described as little association, never as positive or negative.
ASSOCIATION_STRENGTH = 0.3
_ASSOC_TAIL = (
    "between {t0} and {t1} ({measure} {value} over {n} quarters; exploratory, not evidence of cause)"
)


def _p(
    id: str,
    tools: Iterable[str],
    kinds: Iterable[ValueKind],
    claims: frozenset[ClaimKind],
    sign: Sign,
    template: str,
    description: str,
    min_abs: float | None = None,
    max_abs: float | None = None,
) -> Predicate:
    return Predicate(
        id=id,
        tools=frozenset(tools),
        value_kinds=frozenset(kinds),
        claim_kinds=claims,
        sign=sign,
        template=template,
        description=description,
        min_abs=min_abs,
        max_abs=max_abs,
    )


# fmt: off
_REGISTRY = [
    _p("level.at", {"value_at"}, {ValueKind.LEVEL, ValueKind.RATE}, _MEASURED, sign=None,
       template="{subject} was {value} in {t1}", description="the value of a stock or rate in one period"),
    _p("flow.at", {"value_at"}, {ValueKind.FLOW}, _MEASURED, sign=None,
       template="{subject} was {value} in {t1}", description="the net change recorded for one period"),
    _p("flow.total", {"cumulative"}, {ValueKind.TOTAL}, _COMPARISON, sign=None,
       template="{subject} totalled {value} between {t0} and {t1}",
       description="the summed net change of a flow over a window"),
    _p("change.increase", _CHANGE_TOOLS, _CHANGE_KINDS, _COMPARISON, sign="positive",
       template="{subject} rose by {value} between {t0} and {t1}", description="a rise between two periods"),
    _p("change.decrease", _CHANGE_TOOLS, _CHANGE_KINDS, _COMPARISON, sign="negative",
       template="{subject} fell by {value} between {t0} and {t1}", description="a fall between two periods"),
    _p("cagr.growth", {"cagr"}, {ValueKind.CAGR_PCT}, _COMPARISON, sign="positive",
       template="{subject} grew at a compound rate of {value} between {t0} and {t1}",
       description="compound annual growth over a span"),
    _p("cagr.decline", {"cagr"}, {ValueKind.CAGR_PCT}, _COMPARISON, sign="negative",
       template="{subject} declined at a compound rate of {value} between {t0} and {t1}",
       description="compound annual decline over a span"),
    _p("trend.upward", {"trend"}, {ValueKind.SLOPE}, _COMPARISON, sign="positive",
       template="{subject} trended upward by about {value} between {t0} and {t1}",
       description="a fitted upward trend"),
    _p("trend.downward", {"trend"}, {ValueKind.SLOPE}, _COMPARISON, sign="negative",
       template="{subject} trended downward by about {value} between {t0} and {t1}",
       description="a fitted downward trend"),
    _p("period.higher", {"compare_periods"}, {ValueKind.DIFFERENCE}, _COMPARISON, sign="positive",
       template="{subject} averaged {value} more in {b0} to {b1} than in {a0} to {a1}",
       description="a higher average in a later window"),
    _p("period.lower", {"compare_periods"}, {ValueKind.DIFFERENCE}, _COMPARISON, sign="negative",
       template="{subject} averaged {value} less in {b0} to {b1} than in {a0} to {a1}",
       description="a lower average in a later window"),
    _p("assoc.positive", {"correlate"}, {ValueKind.COEFFICIENT}, _ASSOCIATION, sign="positive",
       template="{subject} and {subject_b}{lag_phrase} tended to be higher together " + _ASSOC_TAIL,
       description=f"a positive correlation, |r| >= {ASSOCIATION_STRENGTH}", min_abs=ASSOCIATION_STRENGTH),
    _p("assoc.negative", {"correlate"}, {ValueKind.COEFFICIENT}, _ASSOCIATION, sign="negative",
       template="when {subject} was higher, {subject_b}{lag_phrase} tended to be lower " + _ASSOC_TAIL,
       description=f"a negative correlation, |r| >= {ASSOCIATION_STRENGTH}", min_abs=ASSOCIATION_STRENGTH),
    _p("assoc.weak", {"correlate"}, {ValueKind.COEFFICIENT}, _ASSOCIATION, sign=None,
       template="{subject} and {subject_b}{lag_phrase} showed little association " + _ASSOC_TAIL,
       description=f"a weak correlation, |r| < {ASSOCIATION_STRENGTH}", max_abs=ASSOCIATION_STRENGTH),
]
# fmt: on
PREDICATES: dict[str, Predicate] = {p.id: p for p in _REGISTRY}


def predicate_catalogue() -> list[dict[str, object]]:
    """Compact description of the registry for LLM prompts."""
    return [
        {
            "id": p.id,
            "tools": sorted(p.tools),
            "fields": sorted(p.value_kinds),
            "sign": p.sign,
            "means": p.description,
        }
        for p in PREDICATES.values()
    ]
