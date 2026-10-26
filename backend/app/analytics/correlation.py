"""Exploratory correlation between two series under declared pairing rules (plan §4.5, F5).

Which observations may be paired depends on what each series measures and when within a period it
is observed. A stock counted at the end of a quarter and a flow over a quarter share an end date,
so they align at lag 0, and the stock can lead the next quarter's flow at lag 1. Any combination
without a declared rule is refused rather than paired by period label alone.

Results are descriptive: Pearson and Spearman coefficients with the actual number of aligned
pairs. No p-values are reported, because consecutive quarters are serially dependent and the
usual test would overstate certainty. A correlation never says why two series move together.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from app.data.identity import MeasureType, SeriesIdentity
from app.data.models import SeriesData
from app.data.periods import Frequency, Period

MIN_PAIRS = 12
EXPLORATORY_NOTE = "exploratory association; observations are serially dependent; not causal"


@dataclass(frozen=True)
class PairingRule:
    """How a `leader` series pairs with a `follower` series, and at which lags (in periods)."""

    name: str
    leader: tuple[MeasureType, str]  # (measure type, reference convention)
    follower: tuple[MeasureType, str]
    lags: frozenset[int]
    lag_meaning: dict[int, str]
    caveats: tuple[str, ...] = ()


RULES = (
    PairingRule(
        name="stock_at_quarter_end__x__flow_over_quarter",
        leader=(MeasureType.STOCK, "quarter_end"),
        follower=(MeasureType.FLOW, "quarter_end_difference"),
        lags=frozenset({0, 1}),
        lag_meaning={
            0: "the stock at the end of each quarter with the flow over that same quarter",
            1: "the stock at the end of each quarter with the flow over the following quarter",
        },
    ),
    PairingRule(
        name="stock_at_quarter_end__x__stock_at_quarter_end",
        leader=(MeasureType.STOCK, "quarter_end"),
        follower=(MeasureType.STOCK, "quarter_end"),
        lags=frozenset({0}),
        lag_meaning={0: "both stocks at the end of the same quarter"},
    ),
    PairingRule(
        name="rate_monthly_average__x__stock_at_quarter_end",
        leader=(MeasureType.RATE, "monthly_average_within_quarter"),
        follower=(MeasureType.STOCK, "quarter_end"),
        lags=frozenset({0}),
        lag_meaning={0: "the quarter's average monthly rate with the stock at that quarter's end"},
        caveats=("the rate is an average over the quarter, the stock a single end-of-quarter count",),
    ),
)


def _role(identity: SeriesIdentity) -> tuple[MeasureType, str]:
    return identity.measure_type, identity.reference_convention


def find_rule(x: SeriesIdentity, y: SeriesIdentity) -> PairingRule | None:
    """The declared rule with x as leader and y as follower, if any (order matters for lags)."""
    return next((r for r in RULES if (r.leader, r.follower) == (_role(x), _role(y))), None)


class Ineligible(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Aligned:
    rule: PairingRule
    pairs: list[tuple[str, str]]  # (x period, y period)
    x: list[float]
    y: list[float]
    skipped: list[str]  # x periods whose pair had a missing value


def eligibility(x: SeriesIdentity, y: SeriesIdentity, lag: int) -> PairingRule:
    """The rule under which x (leading) and y may be paired at this lag, or Ineligible with a code."""
    if x.scheme != y.scheme or x.sector != y.sector:
        raise Ineligible(
            "CLASSIFICATION_MISMATCH",
            f"{x.scheme} {x.sector} vs {y.scheme} {y.sector}: correlations need the same "
            "classification and code set",
        )
    if x.frequency != y.frequency:
        raise Ineligible("FREQ_MISMATCH", f"{x.frequency} vs {y.frequency}; series are never resampled")
    if x.measure_type == y.measure_type and x.reference_convention != y.reference_convention:
        raise Ineligible(
            "REFERENCE_MISMATCH",
            f"both are {x.measure_type}s but observed differently ({x.reference_convention} vs "
            f"{y.reference_convention}), so equal period labels do not describe the same moment",
        )
    rule = find_rule(x, y)
    if rule is None or x.frequency is not Frequency.QUARTERLY:
        raise Ineligible(
            "NO_PAIRING_RULE",
            f"no declared rule pairs a {x.measure_type} ({x.reference_convention}) with a "
            f"{y.measure_type} ({y.reference_convention}) at {x.frequency} frequency",
        )
    if lag not in rule.lags:
        raise Ineligible("NO_PAIRING_RULE", f"{rule.name} allows lags {sorted(rule.lags)}, not {lag}")
    return rule


def align(x: SeriesData, y: SeriesData, rule: PairingRule, lag: int, start: Period, end: Period) -> Aligned:
    """Pairs (x_t, y_t+lag) with both periods inside [start, end]; incomplete pairs are skipped
    and listed, never filled in."""
    xs, ys = x.value_map(), y.value_map()
    pairs, xv, yv, skipped = [], [], [], []
    for i in range(end.ordinal - start.ordinal + 1 - lag):
        px, py = str(start.shift(i)), str(start.shift(i + lag))
        a, b = xs.get(px), ys.get(py)
        if a is None or b is None or a.value is None or b.value is None:
            skipped.append(px)
            continue
        pairs.append((px, py))
        xv.append(a.value)
        yv.append(b.value)
    return Aligned(rule, pairs, xv, yv, skipped)


def coefficients(aligned: Aligned) -> tuple[float, float]:
    if len(aligned.pairs) < MIN_PAIRS:
        raise Ineligible(
            "INSUFFICIENT_PAIRS", f"{len(aligned.pairs)} aligned complete pairs; need at least {MIN_PAIRS}"
        )
    x, y = np.asarray(aligned.x, dtype=float), np.asarray(aligned.y, dtype=float)
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        raise Ineligible("CONSTANT_SERIES", "a constant series has no correlation")
    return float(stats.pearsonr(x, y).statistic), float(stats.spearmanr(x, y).statistic)
