"""Computation-accuracy and refusal-correctness gates (plan §8.3, G5).

The application's toolkit is run on the golden series as the application parses them, and every
result field is compared with the value eval/compute_expected.py computed independently from the
raw payloads.
"""

from __future__ import annotations

import math
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
    """One result field against its independent expectation: value within tolerance, and the same
    unit and scale (a right number in the wrong unit is a wrong number). A field the expectation does
    not have, or one the result lacks, fails."""

    computation: str
    field: str
    expected: float | None
    actual: float | None
    tolerance: str
    expected_unit: str | None
    actual_unit: str | None
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
    """Exact, or within the declared relative tolerance of the expected value (never an absolute
    floor: correlations are below one, where an absolute 1e-6 would allow a larger relative error)."""
    if tolerance == "exact":
        return actual == value
    return math.isclose(actual, value, rel_tol=TOLERANCES[tolerance], abs_tol=0.0)


def _unit(unit: str | None, scale: int | None) -> str | None:
    return None if unit is None else f"{unit} x{scale}"


def check_computations(series: Series) -> list[FieldCheck]:
    toolkit = Toolkit(get_taxonomy().version)
    out = []
    for cid, spec in golden()["computations"].items():
        result = run_spec(toolkit, spec, series)
        fields = result.result if isinstance(result, Computation) else {}
        wanted = expected()["computations"][cid]["fields"]
        for name in sorted(set(wanted) | set(fields)):
            want, got = wanted.get(name), fields.get(name)
            expected_unit = _unit(want["unit"], want["scale"]) if want else None
            actual_unit = _unit(got.unit, got.scale) if got else None
            ok = (
                want is not None
                and got is not None
                and expected_unit == actual_unit
                and _agrees(got.value, want["value"], want["tolerance"])
            )
            out.append(
                FieldCheck(
                    cid,
                    name,
                    want["value"] if want else None,
                    got.value if got else None,
                    want["tolerance"] if want else "unexpected field",
                    expected_unit,
                    actual_unit,
                    ok,
                )
            )
    return out


def check_refusals(series: Series) -> list[RefusalCheck]:
    toolkit = Toolkit(get_taxonomy().version)
    out = []
    for rid, spec in golden()["refusals"].items():
        result = run_spec(toolkit, spec, series)
        actual = result.code.value if isinstance(result, Refusal) else "COMPUTED"
        out.append(RefusalCheck(rid, spec["code"], actual, actual == spec["code"]))
    return out
