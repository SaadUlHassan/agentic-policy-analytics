"""Computation-accuracy and refusal-correctness gates (plan §8.3, G5).

The application's toolkit is run on the golden series as the application parses them, and every
result field is compared with the value eval/compute_expected.py computed independently from the
raw payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.analytics.results import Computation, Refusal, SeriesInput
from app.analytics.tools import Toolkit
from app.data.models import SeriesData
from app.data.taxonomy import get_taxonomy
from app.evaluation.golden import TOLERANCES, expected, golden

Series = dict[str, tuple[SeriesInput, SeriesData]]


@dataclass(frozen=True)
class FieldCheck:
    computation: str
    field: str
    expected: float
    actual: float | None
    tolerance: str
    ok: bool


@dataclass(frozen=True)
class RefusalCheck:
    refusal: str
    expected_code: str
    actual: str
    ok: bool


def run_spec(toolkit: Toolkit, spec: dict[str, Any], series: Series) -> Computation | Refusal:
    """Run one golden computation or refusal spec on the golden series."""
    params = spec["params"]
    if spec["tool"] == "correlate":
        return toolkit.correlate(*series[spec["series"]], *series[spec["other"]], **params)
    return getattr(toolkit, spec["tool"])(*series[spec["series"]], **params)


def _agrees(actual: float, value: float, tolerance: str) -> bool:
    if tolerance == "exact":
        return actual == value
    return abs(actual - value) <= TOLERANCES[tolerance] * max(1.0, abs(value))


def check_computations(series: Series) -> list[FieldCheck]:
    toolkit = Toolkit(get_taxonomy().version)
    out = []
    for cid, spec in golden()["computations"].items():
        result = run_spec(toolkit, spec, series)
        for name, want in expected()["computations"][cid]["fields"].items():
            got = (
                result.result[name].value
                if isinstance(result, Computation) and name in result.result
                else None
            )
            ok = got is not None and _agrees(got, want["value"], want["tolerance"])
            out.append(FieldCheck(cid, name, want["value"], got, want["tolerance"], ok))
    return out


def check_refusals(series: Series) -> list[RefusalCheck]:
    toolkit = Toolkit(get_taxonomy().version)
    out = []
    for rid, spec in golden()["refusals"].items():
        result = run_spec(toolkit, spec, series)
        actual = result.code.value if isinstance(result, Refusal) else "COMPUTED"
        out.append(RefusalCheck(rid, spec["code"], actual, actual == spec["code"]))
    return out
