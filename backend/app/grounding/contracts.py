"""Report, claim and citation contracts (plan §3.6).

An LLM never writes a number. It picks a predicate from a closed registry, binds it to a field of
a computation, and may add connective prose with slots such as "{a1}". The renderer produces the
numeric text; the checks decide whether the claim may appear at all.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.analytics.results import Interval


class ClaimKind(StrEnum):
    MEASURED = "measured"
    COMPARISON = "comparison"
    ASSOCIATION = "association"
    PROJECTION = "projection"
    RECOMMENDATION = "recommendation"
    LIMITATION = "limitation"


class Assertion(BaseModel):
    predicate: str = Field(description="Predicate id from the registry, e.g. 'change.increase'")
    computation_id: str
    field: str = Field(description="Result field of the computation, e.g. 'pct_change'")
    metric: str = Field(description="Metric the assertion is about; must equal the field's metric")
    series_key: str = Field(description="Series the assertion is about; must be the computation's input")
    interval: Interval = Field(description="Exact interval asserted; must equal the field's interval")


class Claim(BaseModel):
    id: str
    kind: ClaimKind
    text: str = Field(description="Prose with {slot} placeholders for assertions; no digits of its own")
    assertions: dict[str, Assertion] = {}


class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class ClaimVerdict(BaseModel):
    claim_id: str
    passed: bool
    checks: list[CheckResult]

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


class Citation(BaseModel):
    id: str
    dataset_id: str
    artifact_id: str
    title: str
    publisher: str
    origin_agency: str
    platform: str
    series: list[str]
    periods: list[str]
    url_human: str
    retrieved_at: datetime
    source_updated_at: str | None
    from_snapshot: bool


class VerifiedClaim(BaseModel):
    claim: Claim
    rendered: str
    citation_ids: list[str]
    verdict: ClaimVerdict
