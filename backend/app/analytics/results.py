"""Computation results: every number a report may state comes from one of these (plan §3.6)."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.data.identity import SeriesIdentity
from app.data.models import PARSER_VERSION

METHOD_VERSION = "1"


class ValueKind(StrEnum):
    LEVEL = "level"
    FLOW = "flow"
    RATE = "rate"
    ABS_CHANGE = "abs_change"
    PCT_CHANGE = "pct_change"
    PP_CHANGE = "pp_change"
    CAGR_PCT = "cagr_pct"
    SLOPE = "slope"
    SLOPE_BOUND = "slope_bound"
    MEAN = "mean"
    DIFFERENCE = "difference"
    TOTAL = "total"
    COEFFICIENT = "coefficient"  # a correlation coefficient: unitless, in [-1, 1]
    COUNT = "count"


class Interpretation(StrEnum):
    DESCRIPTIVE = "descriptive"
    EXPLORATORY_ASSOCIATION = "exploratory_association"
    PROJECTION = "projection"


class Interval(BaseModel):
    start: str
    end: str


class ResultField(BaseModel):
    value: float
    metric: str
    value_kind: ValueKind
    unit: str
    scale: int
    interval: Interval


class SeriesInput(BaseModel):
    """A series as evidence: which normalised artifact it came from and what it measures."""

    artifact_id: str
    dataset_id: str
    series_key: str
    identity: SeriesIdentity


class SeriesRef(SeriesInput):
    periods_used: list[str]


class Computation(BaseModel):
    id: str
    fingerprint: str
    tool: str
    method_version: str = METHOD_VERSION
    params: dict[str, Any]
    inputs: list[SeriesRef]
    result: dict[str, ResultField]
    interpretation_allowed: Interpretation = Interpretation.DESCRIPTIVE
    notes: list[str] = []


class RefusalCode(StrEnum):
    MISSING_PERIODS = "MISSING_PERIODS"
    MISSING_PRIOR_PERIOD = "MISSING_PRIOR_PERIOD"
    INVALID_WINDOW = "INVALID_WINDOW"
    ZERO_BASE = "ZERO_BASE"
    NOT_A_LEVEL = "NOT_A_LEVEL"
    NOT_A_FLOW = "NOT_A_FLOW"
    NON_POSITIVE_ENDPOINT = "NON_POSITIVE_ENDPOINT"
    INSUFFICIENT_SPAN = "INSUFFICIENT_SPAN"
    INSUFFICIENT_POINTS = "INSUFFICIENT_POINTS"
    CONSTANT_SERIES = "CONSTANT_SERIES"
    # correlate (plan §4.5)
    CLASSIFICATION_MISMATCH = "CLASSIFICATION_MISMATCH"
    FREQ_MISMATCH = "FREQ_MISMATCH"
    REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
    NO_PAIRING_RULE = "NO_PAIRING_RULE"
    INSUFFICIENT_PAIRS = "INSUFFICIENT_PAIRS"


class Refusal(BaseModel):
    tool: str
    code: RefusalCode
    detail: str
    params: dict[str, Any]
    series_key: str
    other_series_key: str | None = None  # the second series of a refused correlation


def fingerprint(tool: str, params: dict[str, Any], inputs: list[SeriesInput], taxonomy_version: str) -> str:
    """Canonical evidence + method fingerprint (plan F3): the same evidence and options always
    yield the same computation; any change to source content, series, periods, parser, taxonomy
    or method yields a new one."""
    content = {
        "tool": tool,
        "method_version": METHOD_VERSION,
        "parser_version": PARSER_VERSION,
        "taxonomy_version": taxonomy_version,
        "inputs": [
            {
                "artifact_id": i.artifact_id,
                "series_key": i.series_key,
                "identity": i.identity.model_dump(mode="json"),
            }
            for i in inputs
        ],
        "params": params,
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
