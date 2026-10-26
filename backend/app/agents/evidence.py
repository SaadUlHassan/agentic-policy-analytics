"""Evidence shared by the agents of one analysis: datasets, selected series, computations, claims."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
    tolerance: float = 0.0  # in base units: half the coarser published increment

    @property
    def verdict(self) -> str:
        if not self.periods:
            return "no overlapping periods"
        if self.mismatches:
            return f"{len(self.mismatches)} period(s) disagree"
        return (
            "consistent"
            if not self.tolerance
            else f"consistent within published rounding (±{self.tolerance:g})"
        )


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


# -- persistence across resume -----------------------------------------------------------------
# Graph state carries only small references; datasets and computations already live in their own
# tables (dataset_artifacts, computations), so a resumed execution reloads them instead of
# re-fetching or recomputing.


def to_refs(evidence: EvidenceStore) -> dict[str, Any]:
    return {
        "artifacts": list(evidence.datasets),
        "selected": [
            {"series_key": k, "artifact_id": s.source.artifact_id, "reason": s.reason}
            for k, s in evidence.selected.items()
        ],
        "rejected": [asdict(r) for r in evidence.rejected],
        "refusals": [r.model_dump(mode="json") for r in evidence.refusals],
        "computations": list(evidence.computations),
        "claims": [
            {"claim": c.model_dump(mode="json"), "verdict": v.model_dump(mode="json")}
            for c, v in evidence.claims
        ],
        "consistency": [asdict(c) for c in evidence.consistency],
    }


def from_refs(
    refs: dict[str, Any], datasets: dict[str, NormalizedDataset], computations: dict[str, Computation]
) -> EvidenceStore:
    """Rebuild the store from references plus the loaded datasets and computations."""
    missing = set(refs.get("artifacts", [])) - set(datasets)
    missing_computations = set(refs.get("computations", [])) - set(computations)
    if missing or missing_computations:
        raise LookupError(f"cannot restore evidence: missing {sorted(missing | missing_computations)}")
    store = EvidenceStore(
        datasets={a: datasets[a] for a in refs.get("artifacts", [])},
        computations={c: computations[c] for c in refs.get("computations", [])},
    )
    for sel in refs.get("selected", []):
        dataset = store.datasets[sel["artifact_id"]]
        series = next(s for s in dataset.series if s.key == sel["series_key"])
        assert series.identity is not None
        store.selected[sel["series_key"]] = Selection(
            source=SeriesInput(
                artifact_id=dataset.artifact_id,
                dataset_id=dataset.dataset_id,
                series_key=series.key,
                identity=series.identity,
            ),
            series=series,
            reason=sel["reason"],
        )
    store.rejected = [Rejection(**r) for r in refs.get("rejected", [])]
    store.refusals = [Refusal.model_validate(r) for r in refs.get("refusals", [])]
    store.claims = [
        (Claim.model_validate(c["claim"]), ClaimVerdict.model_validate(c["verdict"]))
        for c in refs.get("claims", [])
    ]
    store.consistency = [ConsistencyCheck(**c) for c in refs.get("consistency", [])]
    return store
