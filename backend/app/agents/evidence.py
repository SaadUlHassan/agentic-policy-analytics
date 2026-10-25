"""Evidence shared by the agents of one analysis: datasets, selected series, computations, claims."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analytics.results import Computation, Refusal, SeriesInput
from app.data.models import NormalizedDataset, SeriesData
from app.grounding.contracts import Claim, ClaimVerdict


@dataclass
class Selection:
    source: SeriesInput
    series: SeriesData
    reason: str


@dataclass
class Rejection:
    series_key: str
    reason: str


@dataclass
class ConsistencyCheck:
    """The same statistic compared across two platforms (same origin, so not independent evidence)."""

    series_a: str
    artifact_a: str
    series_b: str
    artifact_b: str
    periods: list[str]
    mismatches: list[dict]

    @property
    def verdict(self) -> str:
        if not self.periods:
            return "no overlapping periods"
        return "consistent" if not self.mismatches else f"{len(self.mismatches)} period(s) disagree"


@dataclass
class EvidenceStore:
    datasets: dict[str, NormalizedDataset] = field(default_factory=dict)  # by artifact_id
    selected: dict[str, Selection] = field(default_factory=dict)  # by series_key
    rejected: list[Rejection] = field(default_factory=list)
    computations: dict[str, Computation] = field(default_factory=dict)  # by computation id
    refusals: list[Refusal] = field(default_factory=list)
    claims: list[tuple[Claim, ClaimVerdict]] = field(default_factory=list)
    consistency: list[ConsistencyCheck] = field(default_factory=list)

    def dataset(self, dataset_id: str) -> NormalizedDataset | None:
        return next((d for d in self.datasets.values() if d.dataset_id == dataset_id), None)

    def find_series(self, series_key: str) -> tuple[NormalizedDataset, SeriesData] | None:
        for dataset in self.datasets.values():
            for s in dataset.series:
                if s.key == series_key:
                    return dataset, s
        return None

    def verified_claims(self) -> list[Claim]:
        return [c for c, v in self.claims if v.passed]
