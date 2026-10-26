"""The golden set (eval/golden/queries.yaml) and its independently computed expectations."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.analytics.results import SeriesInput
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.connectors.registry import fetch
from app.core.config import get_settings
from app.data.models import SeriesData
from app.data.taxonomy import get_taxonomy

# Relative tolerances by class (plan §8.3).
TOLERANCES = {"exact": 0.0, "closed_form": 1e-9, "estimator": 1e-6}


def golden_dir() -> Path:
    return get_settings().data_dir.parent / "eval" / "golden"


@lru_cache
def golden() -> dict[str, Any]:
    return yaml.safe_load((golden_dir() / "queries.yaml").read_text())


@lru_cache
def expected() -> dict[str, Any]:
    return json.loads((golden_dir() / "expected.json").read_text())


async def golden_series() -> dict[str, tuple[SeriesInput, SeriesData]]:
    """Each golden series as the application parses it from the snapshots."""
    fetcher = Fetcher(mode="snapshot", snapshots=get_snapshot_store())
    out: dict[str, tuple[SeriesInput, SeriesData]] = {}
    try:
        datasets = {}
        for name, spec in golden()["series"].items():
            if spec["dataset"] not in datasets:
                datasets[spec["dataset"]] = await fetch(
                    spec["dataset"], get_catalog(), get_taxonomy(), fetcher
                )
            dataset = datasets[spec["dataset"]]
            series = next(s for s in dataset.series if s.key == spec["key"])
            assert series.identity is not None, f"golden series {name} is not identified"
            source = SeriesInput(
                artifact_id=dataset.artifact_id,
                dataset_id=dataset.dataset_id,
                series_key=series.key,
                identity=series.identity,
            )
            out[name] = (source, series)
    finally:
        await fetcher.aclose()
    return out
