"""Pieces shared by connectors: assembling a NormalizedDataset with provenance and disclosures."""

from __future__ import annotations

from typing import Any

from app.connectors.catalog import DatasetEntry, PlatformInfo
from app.connectors.http import RawPayload
from app.data.models import NormalizedDataset, Provenance, QualityIssue, SeriesData, Severity
from app.data.series import flag_ambiguous_sectors
from app.data.taxonomy import Taxonomy


def assemble(
    entry: DatasetEntry,
    platform: PlatformInfo,
    taxonomy: Taxonomy,
    payloads: list[RawPayload],
    series: list[SeriesData],
    issues: list[QualityIssue],
    *,
    title: str,
    source_updated_at: str | None,
    footnotes: str | None,
    source_metadata: dict[str, Any] | None = None,
) -> NormalizedDataset:
    issues = [*issues, *flag_ambiguous_sectors(series)]
    if unidentified := [s for s in series if s.identity is None]:
        labels = ", ".join(dict.fromkeys(s.label for s in unidentified))
        issues.append(
            QualityIssue(
                code="UNIDENTIFIED_SERIES",
                severity=Severity.INFO,
                count=len(unidentified),
                message=f"rows matching no catalogued sector are kept but not used: {labels[:300]}",
            )
        )
    if any(p.from_snapshot for p in payloads):
        fallbacks = {p.fallback_reason for p in payloads if p.fallback_reason}
        retrieved = min(p.retrieved_at for p in payloads if p.from_snapshot).date().isoformat()
        issues.append(
            QualityIssue(
                code="SERVED_FROM_SNAPSHOT",
                severity=Severity.WARNING if fallbacks else Severity.INFO,
                message=(f"live source unavailable ({'; '.join(sorted(fallbacks))}); " if fallbacks else "")
                + f"using snapshot retrieved {retrieved}",
            )
        )
    provenance = Provenance(
        platform=entry.platform,
        publisher=platform.publisher,
        origin_agency=entry.origin_agency,
        dataset_id=entry.id,
        title=title,
        url_human=entry.human_url(platform),
        url_api=[p.url for p in payloads],
        retrieved_at=max(p.retrieved_at for p in payloads),
        source_updated_at=source_updated_at,
        from_snapshot=any(p.from_snapshot for p in payloads),
        raw_sha256=[p.sha256 for p in payloads],
        footnotes=footnotes,
        licence=platform.licence,
    )
    dataset = NormalizedDataset(
        dataset_id=entry.id,
        provenance=provenance,
        series=series,
        quality=issues,
        source_metadata=source_metadata or {},
        taxonomy_version=taxonomy.version,
    )
    return dataset.with_artifact_id()
