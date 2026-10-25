"""Full multi-agent run on real snapshot data with a scripted LLM (deterministic, offline)."""

from __future__ import annotations

import json

import botocore.exceptions
import pytest
from langchain_core.messages import ToolMessage
from sqlalchemy import select, text

from app.core.config import Settings
from app.db.models import OutboxIntent, ReportRow
from app.events.stream import events_after
from app.jobs.lifecycle import create_analysis
from app.jobs.runner import execute
from app.llm.scripted import ScriptedChatModel, tool_call

pytestmark = pytest.mark.integration

EMPLOYMENT = "M182841:3.4@SSIC2020"
VACANCIES_DS = "d_3f17bbf67d31d4d402caa8755eb74afc"
VACANCIES = f"{VACANCIES_DS}:information and communications@SSIC2020"
IT_SUBSECTOR = f"{VACANCIES_DS}:it and other information services@SSIC2020"

PLAN = {
    "intent": "Employment trends in Information & Communications, 2020-2024",
    "in_scope": True,
    "sectors": ["info_comms"],
    "metrics": ["employment_level", "job_vacancies"],
    "start_year": 2020,
    "end_year": 2024,
    "sub_questions": ["How did ICT employment change?", "How did ICT vacancies change?"],
    "assumptions": ["'Technology sector' is read as Information & Communications (SSIC 2020 J)."],
    "rationale": "Employment levels and vacancies together show realised and unmet labour demand.",
}


def act(name: str, args: dict, text: str = "") -> object:
    """An agent tool call carrying its public rationale, as real models are required to send."""
    return tool_call(name, {**args, "rationale": text or f"Calling {name}."})


def _last_computation_id(messages) -> str:
    """The id from the most recent compute observation (later observations may be claim verdicts)."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.content.startswith("{"):
            return json.loads(message.content)["computation_id"]
    raise AssertionError("no computation observed yet")


def _claim_on_last(predicate: str, field: str, metric: str, series: str, start: str, end: str, prose: str):
    def reply(messages):
        cid = _last_computation_id(messages)
        return act(
            "draft_claim",
            {
                "kind": "comparison",
                "lead_in": prose,
                "assertions": [
                    {
                        "predicate": predicate,
                        "computation_id": cid,
                        "field": field,
                        "metric": metric,
                        "series_key": series,
                        "interval_start": start,
                        "interval_end": end,
                    }
                ],
            },
            "Drafting a finding.",
        )

    return reply


def _happy_path_script() -> list:
    return [
        tool_call("ResearchPlan", PLAN),
        tool_call(
            "NextAction",
            {
                "action": "extract",
                "objective": "Find ICT employment and vacancies",
                "rationale": "No evidence yet.",
            },
        ),
        act("fetch_dataset", {"dataset_id": "M182841"}, "Fetching year-end employment by sector."),
        act("fetch_dataset", {"dataset_id": VACANCIES_DS}, "Fetching quarterly vacancies."),
        act("select_series", {"series_key": EMPLOYMENT, "reason": "ICT employment, full coverage"}),
        act("select_series", {"series_key": VACANCIES, "reason": "ICT vacancies, full coverage"}),
        act(
            "select_series",
            {"series_key": IT_SUBSECTOR, "reason": "also tech"},
            "Trying the IT subsector too.",
        ),
        act("finish", {"summary": "Employment and vacancies selected."}),
        tool_call(
            "NextAction",
            {
                "action": "analyse",
                "objective": "Quantify changes 2020-2024",
                "rationale": "Two fitting series are selected.",
            },
        ),
        act("compute", {"tool": "cagr", "series_key": EMPLOYMENT, "start": "2020", "end": "2024"}),
        _claim_on_last("cagr.growth", "cagr_pct", "employment_level", EMPLOYMENT, "2020", "2024", ""),
        act(
            "compute",
            {"tool": "change_between", "series_key": VACANCIES, "start": "2020-Q1", "end": "2024-Q4"},
        ),
        _claim_on_last(
            "change.increase",
            "pct_change",
            "job_vacancies",
            VACANCIES,
            "2021-Q1",  # restates the 2020-Q1..2024-Q4 change over a shorter interval: must be rejected
            "2024-Q4",
            "",
        ),
        _claim_on_last(
            "change.increase",
            "pct_change",
            "job_vacancies",
            VACANCIES,
            "2020-Q1",
            "2024-Q4",
            "Over the same period,",
        ),
        act("finish", {"summary": "Two findings verified."}),
        tool_call("NextAction", {"action": "report", "objective": "Write the report", "rationale": "Done."}),
        tool_call(
            "ReportNarrative",
            {
                "title": "ICT employment and vacancies",
                "summary": "Employment in the sector grew while vacancies also rose.",
                "limitations": ["Vacancy figures are rounded by the source."],
            },
        ),
    ]


# The narrative judge runs on the other provider first (independent check).
ALL_SUPPORTED = tool_call(
    "SupportVerdicts",
    {
        "verdicts": [
            {"index": 0, "supported": True, "reason": "names the findings' subject"},
            {"index": 1, "supported": True, "reason": "summarises findings"},
            {"index": 2, "supported": True, "reason": "source rounding"},
        ]
    },
)


def _settings(database_url: str, **overrides) -> Settings:
    return Settings(_env_file=None, database_url=database_url, data_mode="snapshot", **overrides)


async def _start(sessions) -> tuple[str, int]:
    async with sessions() as session:
        analysis = await create_analysis(
            session, "Analyse employment trends in the technology sector 2020-2024"
        )
    async with sessions() as session:
        intent = await session.scalar(select(OutboxIntent.id).where(OutboxIntent.analysis_id == analysis.id))
    return analysis.id, intent


async def _events(sessions, analysis_id):
    async with sessions() as session:
        return await events_after(session, analysis_id, 0, limit=1000)


async def test_full_run_produces_a_verified_two_platform_report(sessions, database_url):
    analysis_id, intent = await _start(sessions)
    models = {
        "bedrock": ScriptedChatModel(replies=_happy_path_script()),
        "openai": ScriptedChatModel(replies=[ALL_SUPPORTED]),
    }

    status = await execute(
        sessions, None, _settings(database_url), analysis_id, intent, "test", models=models
    )

    assert status == "completed"
    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    texts = [f["text"] for f in report["findings"]]
    assert texts == [
        "Employment level in Information & Communications grew at a compound rate of 3.4% a year "
        "between 2020 and 2024.",
        "Over the same period, job vacancies in Information & Communications rose by 21.7% "
        "between 2020-Q1 and 2024-Q4.",
    ]
    assert {c["platform"] for c in report["citations"]} == {"singstat", "datagov"}
    assert report["verification"] == {
        "claims_drafted": 3,
        "claims_verified": 2,
        "claims_rejected": 1,
        "narrative_note": None,
        "narrative_removed": [],
    }
    assert report["charts"][0]["series"][0]["points"][-1] == {"period": "2024", "value": 180.3}
    assert any("failed evidence checks" in lim["text"] for lim in report["limitations"])

    events = await _events(sessions, analysis_id)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    types = [e["type"] for e in events]
    for expected in (
        "plan",
        "decision",
        "rationale",
        "tool_call",
        "tool_result",
        "quality_report",
        "selection",
        "selection_refused",
        "computation",
        "claim_verdict",
        "report",
        "status",
    ):
        assert expected in types, expected
    refused = next(e for e in events if e["type"] == "selection_refused")
    assert "it_info_services is not in the plan" in refused["detail"]["problems"][0]
    assert events[-1]["detail"] == {"status": "completed"}
    assert {e["agent"] for e in events} >= {"coordinator", "extraction", "analytics"}


async def test_title_and_summary_the_judge_finds_unsupported_are_removed(sessions, database_url):
    analysis_id, intent = await _start(sessions)
    judge = tool_call(
        "SupportVerdicts",
        {
            "verdicts": [
                {"index": 0, "supported": False, "reason": "the title claims a boom"},
                {"index": 1, "supported": False, "reason": "adds regional patterns not in the findings"},
                {"index": 2, "supported": True, "reason": "source rounding"},
            ]
        },
    )
    models = {
        "bedrock": ScriptedChatModel(replies=_happy_path_script()),
        "openai": ScriptedChatModel(replies=[judge]),
    }

    await execute(sessions, None, _settings(database_url), analysis_id, intent, "test", models=models)

    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert report["summary"] == ""
    # A rejected title falls back to the researcher's own question, never to other generated text.
    assert report["title"] == "Analyse employment trends in the technology sector 2020-2024"
    assert report["verification"]["narrative_removed"] == [
        {"text": "ICT employment and vacancies", "reason": "the title claims a boom"},
        {
            "text": "Employment in the sector grew while vacancies also rose.",
            "reason": "adds regional patterns not in the findings",
        },
    ]
    assert {"source": "coordinator", "text": "Vacancy figures are rounded by the source."} in report[
        "limitations"
    ]


async def test_primary_provider_denied_falls_back_and_is_visible(sessions, database_url):
    analysis_id, intent = await _start(sessions)
    denied = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Converse"
    )
    models = {
        "bedrock": ScriptedChatModel(replies=[denied]),
        "openai": ScriptedChatModel(replies=[*_happy_path_script(), ALL_SUPPORTED]),
    }

    status = await execute(
        sessions, None, _settings(database_url), analysis_id, intent, "test", models=models
    )

    assert status == "completed"
    events = await _events(sessions, analysis_id)
    fallback = next(e for e in events if e["type"] == "provider_fallback")
    assert fallback["detail"]["from"] == "bedrock" and fallback["detail"]["to"] == "openai"
    async with sessions() as session:
        providers = (
            await session.execute(
                text("SELECT provider, ok FROM llm_calls WHERE analysis_id = :id ORDER BY id"),
                {"id": analysis_id},
            )
        ).all()
    assert providers[0] == ("bedrock", False) and providers[1] == ("openai", True)


async def test_total_outage_before_a_plan_fails_clearly(sessions, database_url):
    analysis_id, intent = await _start(sessions)
    models = {
        "bedrock": ScriptedChatModel(replies=[TimeoutError(), TimeoutError()]),
        "openai": ScriptedChatModel(replies=[TimeoutError(), TimeoutError()]),
    }

    status = await execute(
        sessions, None, _settings(database_url), analysis_id, intent, "test", models=models
    )

    assert status == "failed"
    async with sessions() as session:
        row = (
            await session.execute(
                text("SELECT status, error FROM analyses WHERE id = :id"), {"id": analysis_id}
            )
        ).one()
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert row.status == "failed" and row.error["code"] == "LLM_UNAVAILABLE" and report is None


async def test_out_of_scope_question_gets_a_limitation_not_figures(sessions, database_url):
    analysis_id, intent = await _start(sessions)
    plan = {
        **PLAN,
        "in_scope": False,
        "sectors": [],
        "metrics": [],
        "scope_note": "Housing prices are not covered.",
    }
    models = {
        "bedrock": ScriptedChatModel(replies=[tool_call("ResearchPlan", plan)]),
        "openai": ScriptedChatModel(),
    }

    status = await execute(
        sessions, None, _settings(database_url), analysis_id, intent, "test", models=models
    )

    assert status == "completed_with_limitations"
    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert report["findings"] == [] and report["limitations"][0]["text"] == "Housing prices are not covered."


async def test_unanswered_planned_metric_is_a_limitation_not_completed(sessions, database_url):
    analysis_id, intent = await _start(sessions)
    script = _happy_path_script()
    # Keep everything up to the first verified finding (employment), then stop analysing.
    first_claim = next(i for i, reply in enumerate(script) if callable(reply))
    employment_only = [
        *script[: first_claim + 1],
        act("finish", {"summary": "Employment analysed."}),
        tool_call("NextAction", {"action": "report", "objective": "Write the report", "rationale": "Done."}),
        script[-1],  # ReportNarrative
    ]
    models = {
        "bedrock": ScriptedChatModel(replies=employment_only),
        "openai": ScriptedChatModel(replies=[ALL_SUPPORTED]),
    }

    status = await execute(
        sessions, None, _settings(database_url), analysis_id, intent, "test", models=models
    )

    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert status == "completed_with_limitations"
    (finding,) = report["findings"]
    assert finding["text"].startswith("Employment level in Information & Communications")
    assert report["coverage"]["uncovered"] == [
        {
            "sector": "info_comms",
            "metric": "job_vacancies",
            "label": "job vacancies in Information & Communications",
        }
    ]
    assert report["limitations"][0] == {
        "source": "coverage",
        "text": "No verified finding covers job vacancies in Information & Communications.",
    }
