"""Citations derived from computation and chart lineage. The LLM cannot author or alter them."""

from __future__ import annotations

from dataclasses import dataclass

from app.analytics.results import Computation
from app.data.models import NormalizedDataset
from app.grounding.contracts import Citation, Claim


@dataclass(frozen=True)
class EvidenceRef:
    artifact_id: str
    subject: str
    periods: tuple[str, ...]


def claim_refs(claim: Claim, computations: dict[str, Computation]) -> list[EvidenceRef]:
    return [
        EvidenceRef(ref.artifact_id, ref.identity.subject(), tuple(ref.periods_used))
        for assertion in claim.assertions.values()
        for ref in computations[assertion.computation_id].inputs
    ]


class CitationIndex:
    """Assigns one citation id (S1, S2, ...) per dataset artifact, accumulating series and periods."""

    def __init__(self, datasets: dict[str, NormalizedDataset]) -> None:
        self._datasets = datasets
        self._used: dict[str, tuple[set[str], set[str]]] = {}

    def cite(self, refs: list[EvidenceRef]) -> list[str]:
        ids = []
        for ref in refs:
            series, periods = self._used.setdefault(ref.artifact_id, (set(), set()))
            series.add(ref.subject)
            periods.update(ref.periods)
            ids.append(self.id_for(ref.artifact_id))
        return list(dict.fromkeys(ids))

    def id_for(self, artifact_id: str) -> str:
        return f"S{list(self._used).index(artifact_id) + 1}"

    def citations(self) -> list[Citation]:
        out = []
        for artifact_id, (series, periods) in self._used.items():
            ds = self._datasets[artifact_id]
            p = ds.provenance
            out.append(
                Citation(
                    id=self.id_for(artifact_id),
                    dataset_id=ds.dataset_id,
                    artifact_id=artifact_id,
                    title=p.title,
                    publisher=p.publisher,
                    origin_agency=p.origin_agency,
                    platform=p.platform,
                    series=sorted(series),
                    periods=sorted(periods),
                    url_human=p.url_human,
                    retrieved_at=p.retrieved_at,
                    source_updated_at=p.source_updated_at,
                    from_snapshot=p.from_snapshot,
                )
            )
        return out
