"""Normalised dataset artifacts produced by connectors and consumed by analytics."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.data.identity import SeriesIdentity
from app.data.periods import Period

PARSER_VERSION = "1"


class MarkerCode(StrEnum):
    UNKNOWN = "unknown"
    NIL_OR_NEGLIGIBLE = "nil_or_negligible"


class Observation(BaseModel):
    period: str
    value: float | None
    marker: MarkerCode | None = None
    raw: str

    @property
    def parsed_period(self) -> Period:
        return Period.parse(self.period)


class SeriesData(BaseModel):
    key: str
    label: str
    source_ref: str
    identity: SeriesIdentity | None
    unidentified_reason: str | None = None
    observations: list[Observation]

    def value_map(self) -> dict[str, Observation]:
        return {o.period: o for o in self.observations}


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class QualityIssue(BaseModel):
    code: str
    severity: Severity
    message: str
    series_key: str | None = None
    count: int = 1


class Provenance(BaseModel):
    platform: str
    publisher: str
    origin_agency: str
    dataset_id: str
    title: str
    url_human: str
    url_api: list[str]
    retrieved_at: datetime
    source_updated_at: str | None
    from_snapshot: bool
    raw_sha256: list[str]
    footnotes: str | None = None
    licence: str = "unverified"


class NormalizedDataset(BaseModel):
    """One fetched dataset after parsing and identification.

    `artifact_id` hashes the normalised content plus parser/taxonomy versions, never the raw
    bytes: sources stamp responses (e.g. SingStat's dateGenerated), so unchanged data can arrive
    with different bytes and must keep the same identity.
    """

    artifact_id: str = ""
    dataset_id: str
    provenance: Provenance
    series: list[SeriesData]
    quality: list[QualityIssue] = Field(default_factory=list)
    parser_version: str = PARSER_VERSION
    taxonomy_version: str

    def with_artifact_id(self) -> NormalizedDataset:
        content = {
            "dataset_id": self.dataset_id,
            "title": self.provenance.title,
            "footnotes": self.provenance.footnotes,
            "source_updated_at": self.provenance.source_updated_at,
            "series": [s.model_dump(mode="json") for s in self.series],
            "parser_version": self.parser_version,
            "taxonomy_version": self.taxonomy_version,
        }
        digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        return self.model_copy(update={"artifact_id": digest})

    def identified_series(self) -> list[SeriesData]:
        return [s for s in self.series if s.identity is not None]

    def find(self, sector: str) -> list[SeriesData]:
        return [s for s in self.series if s.identity is not None and s.identity.sector == sector]
