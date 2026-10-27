"""LLM_MODE=offline: full analyses with the deterministic stand-in used by end-to-end and load runs."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import LLMCall, OutboxIntent, ReportRow
from app.jobs.lifecycle import create_analysis, submit_clarification
from app.jobs.runner import execute
from app.llm.offline import offline_models
from tests.integration.test_analysis_graph import _events, _resume_intent, _settings, _start

pytestmark = pytest.mark.integration


async def _run(sessions, database_url, checkpoints, analysis_id, intent):
    settings = _settings(database_url, llm_mode="offline")
    return await execute(
        sessions,
        None,
        settings,
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models=offline_models(),
    )


async def test_an_offline_analysis_completes_with_verified_findings(sessions, database_url, checkpoints):
    analysis_id, intent = await _start(sessions)

    assert await _run(sessions, database_url, checkpoints, analysis_id, intent) == "completed"

    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
        models = set(await session.scalars(select(LLMCall.model).where(LLMCall.analysis_id == analysis_id)))
    assert [f["text"][:40] for f in report["findings"]] == [
        "Employment level in Information & Commun",
        "Over the same period, job vacancies in I",
    ]
    assert report["verification"]["claims_rejected"] == 0
    assert models == {"offline-bedrock", "offline-openai"}  # recorded as offline, never as a real model


async def test_an_ambiguous_offline_question_is_asked_about_then_answered(
    sessions, database_url, checkpoints
):
    async with sessions() as session:
        analysis = await create_analysis(session, "How is the sector doing?")
    async with sessions() as session:
        intent = await session.scalar(select(OutboxIntent.id).where(OutboxIntent.analysis_id == analysis.id))

    assert await _run(sessions, database_url, checkpoints, analysis.id, intent) == "awaiting_input"
    question = next(e for e in await _events(sessions, analysis.id) if e["type"] == "clarification")
    assert question["detail"]["options"] == [
        "Information & Communications",
        "IT & Other Information Services",
    ]

    await submit_clarification(
        sessions, analysis.id, question["detail"]["version"], {"answer": "Information & Communications"}
    )
    resumed = await _run(
        sessions, database_url, checkpoints, analysis.id, await _resume_intent(sessions, analysis.id)
    )
    assert resumed == "completed"
