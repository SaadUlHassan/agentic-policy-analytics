"""Exports, usage and history filtering on a real (scripted) finished analysis (plan FE-4)."""

from __future__ import annotations

import csv
import io

import pytest

from app.jobs.runner import execute
from app.llm.scripted import ScriptedChatModel
from tests.integration.test_analysis_graph import (
    ALL_SUPPORTED,
    EMPLOYMENT,
    _happy_path_script,
    _settings,
    _start,
)
from tests.integration.test_api import client  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration


@pytest.fixture
async def finished(sessions, database_url, checkpoints) -> str:
    analysis_id, intent = await _start(sessions)
    models = {
        "bedrock": ScriptedChatModel(replies=_happy_path_script()),
        "openai": ScriptedChatModel(replies=[ALL_SUPPORTED]),
    }
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models=models,
    )
    assert status == "completed"
    return analysis_id


def test_markdown_export_holds_the_verified_findings_and_their_sources(client, finished):  # noqa: F811
    resp = client.get(f"/api/analyses/{finished}/export?format=md")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/markdown")
    assert f'filename="analysis-{finished}.md"' in resp.headers["content-disposition"]
    text = resp.text
    report = client.get(f"/api/analyses/{finished}").json()["report"]
    for finding in report["findings"]:
        assert finding["text"] in text
    assert "## Sources" in text and "Dataset version `" in text
    # The draft that failed verification is not in the export.
    assert "2021-Q1" not in text


def test_json_bundle_pins_every_dataset_version(client, finished):  # noqa: F811
    bundle = client.get(f"/api/analyses/{finished}/export?format=json").json()
    assert bundle["export_version"] == "1" and bundle["analysis"]["id"] == finished
    pinned = {d["artifact_id"] for d in bundle["datasets"]}
    assert {c["artifact_id"] for c in bundle["report"]["citations"]} <= pinned
    assert all(d["raw_sha256"] for d in bundle["datasets"])


def test_csv_lists_the_exact_observations_used_with_their_citation(client, finished):  # noqa: F811
    resp = client.get(f"/api/analyses/{finished}/export?format=csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    employment = [r for r in rows if r["series_key"] == EMPLOYMENT]
    assert [r["period"] for r in employment] == ["2020", "2021", "2022", "2023", "2024"]
    assert employment[-1]["value"] == "180.3" and employment[-1]["raw"] == "180.3"
    assert employment[-1]["scale"] == "1000" and employment[-1]["citation"].startswith("S")
    assert {r["series_key"] for r in rows} == {
        s["series_key"]
        for s in client.get(f"/api/analyses/{finished}").json()["report"]["evidence"]["selected"]
    }


def test_export_before_a_report_exists_is_a_conflict(client):  # noqa: F811
    queued = client.post("/api/analyses", json={"query": "Analyse ICT employment"}).json()["id"]
    resp = client.get(f"/api/analyses/{queued}/export?format=md")
    assert resp.status_code == 409 and resp.json()["code"] == "REPORT_NOT_AVAILABLE"
    assert client.get(f"/api/analyses/{queued}/export?format=pdf").status_code == 422


def test_usage_reports_calls_tokens_and_cost_only_when_priced(client, finished, monkeypatch):  # noqa: F811
    usage = client.get(f"/api/analyses/{finished}").json()["usage"]
    assert usage["llm_calls"] > 0 and usage["failed_calls"] == 0
    assert set(usage["providers"]) == {"bedrock", "openai"}
    assert usage["cost_usd"] is None and usage["unpriced_models"], "no prices configured: cost is unknown"
    assert usage["active_ms"] >= 0


def test_history_can_be_filtered_by_status(client, finished):  # noqa: F811
    client.post("/api/analyses", json={"query": "Analyse ICT employment"})
    completed = client.get("/api/analyses?status=completed").json()["items"]
    assert [a["id"] for a in completed] == [finished]
    assert client.get("/api/analyses?status=nonsense").status_code == 422
