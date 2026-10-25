"""Curated dataset catalogue loaded from data/manifest/sources.yaml (plan §4.2)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import get_settings
from app.data.identity import MeasureType
from app.data.models import MarkerCode
from app.data.periods import Frequency, Period


class Regime(BaseModel):
    """Classification scheme in force over an inclusive period range."""

    scheme: str
    start: str = Field(alias="from")
    end: str | None = Field(default=None, alias="to")

    def covers(self, period: Period) -> bool:
        return _year_aware_le(self.start, period) and (self.end is None or _year_aware_le(period, self.end))


def _year_aware_le(a: str | Period, b: str | Period) -> bool:
    """a <= b, comparing by year when one bound is annual and the other quarterly."""
    pa = a if isinstance(a, Period) else Period.parse(a)
    pb = b if isinstance(b, Period) else Period.parse(b)
    if pa.frequency != pb.frequency:
        return pa.year <= pb.year
    return pa <= pb


class FieldMap(BaseModel):
    """Where values sit in datastore records. `long`: one record per (period, label, value).
    `wide`: one record per series, labelled by `label`, with one column per period."""

    layout: Literal["long", "wide"] = "long"
    label: str
    period: str | None = None
    value: str | None = None


class MarkerSpec(BaseModel):
    code: MarkerCode
    meaning: str


class PlatformInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    publisher: str
    human_url: str | None = None
    markers: dict[str, MarkerSpec] = {}
    licence: str = "unverified"


class DatasetEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    platform: str
    origin_agency: str
    title: str
    description: str = ""
    keywords: list[str] = []
    catalogued: bool = True
    metric: str | None = None
    measure_type: MeasureType | None = None
    reference_convention: str | None = None
    population: str | None = None
    frequency: Frequency | None = None
    unit: str | None = None
    scale: int = 1
    rounding: str | None = None
    classification: list[Regime] = []
    fields: FieldMap | None = None
    footnotes: str | None = None
    mirrors: list[str] = []
    mirror_of: str | None = None

    @model_validator(mode="after")
    def _catalogued_entries_are_identifiable(self) -> DatasetEntry:
        required = ("metric", "measure_type", "reference_convention", "population", "frequency", "unit")
        missing = [f for f in required if getattr(self, f) is None]
        if self.catalogued and (missing or not self.classification):
            raise ValueError(f"catalogued dataset {self.id} is missing {missing or ['classification']}")
        return self

    def regime_for(self, period: Period) -> Regime | None:
        return next((r for r in self.classification if r.covers(period)), None)

    def human_url(self, platform: PlatformInfo) -> str:
        return (platform.human_url or "").format(table_id=self.id, id=self.id)


_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"the", "a", "an", "of", "in", "and", "for", "from", "to", "by", "on", "analyse", "analyze"}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS}


class SearchHit(BaseModel):
    dataset_id: str
    title: str
    platform: str
    metric: str | None
    frequency: Frequency | None
    score: float
    matched: list[str]
    mirrors: list[str] = []
    mirror_of: str | None = None


class Catalog:
    def __init__(self, raw: dict) -> None:
        self.platforms = {k: PlatformInfo.model_validate(v) for k, v in raw["platforms"].items()}
        self.datasets = {d["id"]: DatasetEntry.model_validate(d) for d in raw["datasets"]}

    @classmethod
    def load(cls, path: Path) -> Catalog:
        return cls(yaml.safe_load(path.read_text()))

    def get(self, dataset_id: str) -> DatasetEntry | None:
        entry = self.datasets.get(dataset_id)
        return entry if entry and entry.catalogued else None

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        """Lexical relevance over keyword phrases, title and description."""
        q_text, q_tokens = query.lower(), _tokens(query)
        hits = []
        for entry in self.datasets.values():
            if not entry.catalogued:
                continue
            matched = [k for k in entry.keywords if k in q_text]
            score = 3.0 * len(matched)
            score += 2.0 * len(q_tokens & _tokens(entry.title))
            score += 1.0 * len(q_tokens & _tokens(entry.description))
            if score > 0:
                hits.append(
                    SearchHit(
                        dataset_id=entry.id,
                        title=entry.title,
                        platform=entry.platform,
                        metric=entry.metric,
                        frequency=entry.frequency,
                        score=score,
                        matched=matched,
                        mirrors=entry.mirrors,
                        mirror_of=entry.mirror_of,
                    )
                )
        return sorted(hits, key=lambda h: -h.score)[:limit]


@lru_cache
def get_catalog() -> Catalog:
    return Catalog.load(get_settings().data_dir / "manifest" / "sources.yaml")
