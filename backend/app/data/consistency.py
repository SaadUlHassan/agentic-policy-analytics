"""Comparing the same statistic published on two platforms (plan §4.4).

Sources round differently: MOM publishes employment change in thousands to one decimal, SingStat
republishes it in persons. Two values agree when they differ by no more than half the coarser
published increment; with no stated precision, they must be equal (up to float representation).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.connectors.catalog import DatasetEntry
from app.data.models import SeriesData

_FLOAT_EPSILON = 1e-9


def tolerance(a: DatasetEntry | None, b: DatasetEntry | None) -> float:
    """Half the coarser published increment of the two sources, in base units (e.g. persons)."""
    increments = [e.precision * e.scale for e in (a, b) if e is not None and e.precision is not None]
    return max(increments) / 2 if increments else 0.0


def agree(x: float, y: float, allowed: float) -> bool:
    return abs(x - y) <= allowed + _FLOAT_EPSILON * max(1.0, abs(x), abs(y))


def compare(
    a: SeriesData, b: SeriesData, periods: Iterable[str], allowed: float
) -> tuple[list[str], list[dict]]:
    """Periods both series report with a value, and those where the values disagree."""
    assert a.identity is not None and b.identity is not None
    values_a, values_b = a.value_map(), b.value_map()
    compared, mismatches = [], []
    for period in periods:
        va, vb = values_a.get(period), values_b.get(period)
        if va is None or vb is None or va.value is None or vb.value is None:
            continue
        compared.append(period)
        if not agree(va.value * a.identity.scale, vb.value * b.identity.scale, allowed):
            mismatches.append({"period": period, a.key: va.value, b.key: vb.value})
    return compared, mismatches
