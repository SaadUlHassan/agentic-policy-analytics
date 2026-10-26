"""Export resolution of the dataset version a report relied on (plan FE-4)."""

from __future__ import annotations

from app.agents.export import observation_rows
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.connectors.registry import fetch
from app.data.taxonomy import get_taxonomy

EMPLOYMENT = "M182841:3.4@SSIC2020"


async def _two_versions():
    original = await fetch(
        "M182841", get_catalog(), get_taxonomy(), Fetcher(mode="snapshot", snapshots=get_snapshot_store())
    )
    revised = original.model_copy(deep=True)
    point = next(o for o in revised.find("info_comms")[0].observations if o.period == "2024")
    point.value, point.raw = 999.0, "999.0"  # e.g. a later source revision
    return original, revised.with_artifact_id()


def _report(selected: dict, cited_artifact: str) -> dict:
    return {
        "plan": {"start_year": 2024, "end_year": 2024},
        "evidence": {"selected": [{"dataset_id": "M182841", "series_key": EMPLOYMENT, **selected}]},
        "citations": [{"id": "S1", "artifact_id": cited_artifact, "dataset_id": "M182841"}],
    }


async def test_an_older_report_exports_the_version_its_citation_pins():
    original, revised = await _two_versions()
    both = {original.artifact_id: original, revised.artifact_id: revised}
    (row,) = observation_rows(_report({}, revised.artifact_id), both)  # no selected.artifact_id yet
    assert (row["artifact_id"], row["value"], row["citation"]) == (revised.artifact_id, 999.0, "S1")


async def test_the_selection_s_own_version_wins_and_ambiguity_is_never_guessed():
    original, revised = await _two_versions()
    both = {original.artifact_id: original, revised.artifact_id: revised}
    (row,) = observation_rows(_report({"artifact_id": original.artifact_id}, original.artifact_id), both)
    assert row["value"] == 180.3
    legacy = {
        "plan": {"start_year": 2024, "end_year": 2024},
        "evidence": {"selected": [{"dataset_id": "M182841", "series_key": EMPLOYMENT}]},
    }
    assert observation_rows(legacy, both) == [], (
        "two stored versions and nothing pinned: export nothing rather than guess"
    )
