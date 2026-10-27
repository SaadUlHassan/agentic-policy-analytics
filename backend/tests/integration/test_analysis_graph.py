"""Full multi-agent run on real snapshot data with a scripted LLM (deterministic, offline)."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import botocore.exceptions
import pytest
from langchain_core.messages import ToolMessage
from sqlalchemy import select, text

from app.core.config import Settings
from app.db.models import OutboxIntent, ReportRow
from app.events.stream import events_after
from app.jobs import runner
from app.jobs.lifecycle import claim, create_analysis, reconcile, request_cancel, submit_clarification
from app.jobs.runner import execute
from app.jobs.writer import FencedWriter
from app.llm.scripted import ScriptedChatModel, tool_call
from tests.integration.test_lifecycle import FakeQueue, _expire_lease

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


async def test_full_run_produces_a_verified_two_platform_report(sessions, database_url, checkpoints):
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
        "narrative_check": {"writers": ["bedrock"], "judges": ["openai"], "independent": True},
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


async def test_title_and_summary_the_judge_finds_unsupported_are_removed(sessions, database_url, checkpoints):
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

    await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models=models,
    )

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


async def test_primary_provider_denied_falls_back_and_is_visible(sessions, database_url, checkpoints):
    analysis_id, intent = await _start(sessions)
    denied = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Converse"
    )
    models = {
        "bedrock": ScriptedChatModel(replies=[denied]),
        "openai": ScriptedChatModel(replies=[*_happy_path_script(), ALL_SUPPORTED]),
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


async def test_total_outage_before_a_plan_fails_clearly(sessions, database_url, checkpoints):
    analysis_id, intent = await _start(sessions)
    models = {
        "bedrock": ScriptedChatModel(replies=[TimeoutError(), TimeoutError()]),
        "openai": ScriptedChatModel(replies=[TimeoutError(), TimeoutError()]),
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

    assert status == "failed"
    async with sessions() as session:
        row = (
            await session.execute(
                text("SELECT status, error FROM analyses WHERE id = :id"), {"id": analysis_id}
            )
        ).one()
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert row.status == "failed" and row.error["code"] == "LLM_UNAVAILABLE" and report is None


async def test_out_of_scope_question_gets_a_limitation_not_figures(sessions, database_url, checkpoints):
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
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models=models,
    )

    assert status == "completed_with_limitations"
    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert report["findings"] == [] and report["limitations"][0]["text"] == "Housing prices are not covered."


async def test_unanswered_planned_metric_is_a_limitation_not_completed(sessions, database_url, checkpoints):
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
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models=models,
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
        "text": "No verified finding covers job vacancies in Information & Communications: "
        "a series was selected, but no finding about it was verified.",
    }


AMBIGUOUS_PLAN = {
    **PLAN,
    "needs_clarification": True,
    "clarification_question": "Which sector do you mean by 'technology'?",
    "clarification_options": ["Information & Communications", "IT & Other Information Services"],
}


async def _resume_intent(sessions, analysis_id: str) -> int:
    async with sessions() as session:
        return await session.scalar(
            select(OutboxIntent.id).where(
                OutboxIntent.analysis_id == analysis_id,
                OutboxIntent.kind == "resume",
                OutboxIntent.acked_at.is_(None),
                OutboxIntent.superseded_at.is_(None),
            )
        )


async def _pause_for_clarification(sessions, database_url, checkpoints) -> tuple[str, int]:
    analysis_id, intent = await _start(sessions)
    models = {"bedrock": ScriptedChatModel(replies=[tool_call("ResearchPlan", AMBIGUOUS_PLAN)])}
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
    assert status == "awaiting_input"
    question = next(e for e in await _events(sessions, analysis_id) if e["type"] == "clarification")
    return analysis_id, question["detail"]["version"]


async def test_clarification_round_trip_resumes_the_same_thread(sessions, database_url, checkpoints):
    analysis_id, version = await _pause_for_clarification(sessions, database_url, checkpoints)
    async with sessions() as session:
        row = (
            await session.execute(
                text("SELECT status, lease_owner, pending_interrupt_id FROM analyses WHERE id = :id"),
                {"id": analysis_id},
            )
        ).one()
    assert row.status == "awaiting_input" and row.lease_owner is None and row.pending_interrupt_id
    question = next(e for e in await _events(sessions, analysis_id) if e["type"] == "clarification")
    assert question["detail"]["question"] == AMBIGUOUS_PLAN["clarification_question"]
    assert question["detail"]["options"] == AMBIGUOUS_PLAN["clarification_options"]

    await submit_clarification(sessions, analysis_id, version, {"answer": "Information & Communications"})
    planner = ScriptedChatModel(replies=_happy_path_script())
    models = {"bedrock": planner, "openai": ScriptedChatModel(replies=[ALL_SUPPORTED])}
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        await _resume_intent(sessions, analysis_id),
        "test",
        checkpoints=checkpoints,
        models=models,
    )

    assert status == "completed"
    # The planner re-plans once with the answer; it is not asked the original question again.
    assert "The researcher clarified: Information & Communications" in str(planner.calls[0][-1].content)
    titles = [e["title"] for e in await _events(sessions, analysis_id)]
    assert "Researcher answered" in titles and "Analysis resumed" in titles


async def test_clarification_pause_excluded_from_deadline(sessions, database_url, checkpoints, monkeypatch):
    analysis_id, version = await _pause_for_clarification(sessions, database_url, checkpoints)
    async with sessions() as session:
        paused_ms = await session.scalar(
            text("SELECT active_ms_used FROM analyses WHERE id = :id"), {"id": analysis_id}
        )
        # The researcher took an hour to answer, and earlier active work had used 200 s of the 240 s budget.
        await session.execute(
            text(
                "UPDATE analyses SET active_ms_used = 200000, created_at = now() - interval '1 hour', "
                "updated_at = now() - interval '1 hour' WHERE id = :id"
            ),
            {"id": analysis_id},
        )
        await session.commit()
    assert 0 < paused_ms < 60_000  # only time spent running was counted at the pause

    budgets: list[float] = []
    real_context = runner.AgentContext

    def recording_context(**kwargs):
        budgets.append(kwargs["deadline"] - time.monotonic())
        return real_context(**kwargs)

    monkeypatch.setattr(runner, "AgentContext", recording_context)
    await submit_clarification(sessions, analysis_id, version, {"proceed": True})
    models = {
        "bedrock": ScriptedChatModel(replies=_happy_path_script()[1:]),  # proceeds without re-planning
        "openai": ScriptedChatModel(replies=[ALL_SUPPORTED]),
    }
    status = await execute(
        sessions,
        None,
        _settings(database_url, analysis_deadline_s=240),
        analysis_id,
        await _resume_intent(sessions, analysis_id),
        "test",
        checkpoints=checkpoints,
        models=models,
    )

    assert status == "completed"
    assert budgets and 38 < budgets[0] <= 40  # 240 s - 200 s active; the hour of waiting is not charged
    async with sessions() as session:
        plan = await session.scalar(text("SELECT plan FROM analyses WHERE id = :id"), {"id": analysis_id})
    assert "The researcher chose to proceed without clarifying." in plan["assumptions"]


class WorkerKilled(BaseException):
    """Stands in for the process dying: nothing in the runner handles it."""


async def test_crash_after_computation_write_resumes_without_duplicates(
    sessions, database_url, checkpoints, monkeypatch
):
    analysis_id, intent = await _start(sessions)
    script = _happy_path_script()
    real_save = FencedWriter.save_computation

    async def save_then_die(self, computation):
        await real_save(self, computation)
        raise WorkerKilled

    monkeypatch.setattr(FencedWriter, "save_computation", save_then_die)
    with pytest.raises(WorkerKilled):
        await execute(
            sessions,
            None,
            _settings(database_url),
            analysis_id,
            intent,
            "test",
            checkpoints=checkpoints,
            models={"bedrock": ScriptedChatModel(replies=script)},
        )
    monkeypatch.setattr(FencedWriter, "save_computation", real_save)

    await _expire_lease(sessions, analysis_id)
    assert (await reconcile(sessions, FakeQueue())).resumed == 1
    # The interrupted analytics step restarts from its beginning; extraction is not repeated.
    first_compute = next(
        i for i, r in enumerate(script) if not callable(r) and r.tool_calls[0]["name"] == "compute"
    )
    analytics_onwards = script[first_compute:]
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        await _resume_intent(sessions, analysis_id),
        "test",
        checkpoints=checkpoints,
        models={
            "bedrock": ScriptedChatModel(replies=analytics_onwards),
            "openai": ScriptedChatModel(replies=[ALL_SUPPORTED]),
        },
    )

    assert status == "completed"
    async with sessions() as session:
        tools = (
            await session.scalars(
                text("SELECT tool FROM computations WHERE analysis_id = :id ORDER BY id"), {"id": analysis_id}
            )
        ).all()
        attempt = await session.scalar(
            text("SELECT attempt FROM analyses WHERE id = :id"), {"id": analysis_id}
        )
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert tools == ["cagr", "change_between"] and attempt == 2
    assert len(report["findings"]) == 2


async def test_cancel_while_running_stops_at_the_next_step(sessions, database_url, checkpoints, monkeypatch):
    analysis_id, intent = await _start(sessions)
    real_save_plan = FencedWriter.save_plan

    async def save_plan_then_cancel(self, plan):
        await real_save_plan(self, plan)
        await request_cancel(sessions, analysis_id)  # the researcher clicks cancel mid-run

    monkeypatch.setattr(FencedWriter, "save_plan", save_plan_then_cancel)
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models={"bedrock": ScriptedChatModel(replies=[tool_call("ResearchPlan", PLAN)])},
    )

    assert status == "cancelled"
    events = await _events(sessions, analysis_id)
    assert events[-1]["detail"] == {"status": "cancelled"}
    assert "decision" not in [e["type"] for e in events]  # the supervisor never ran


async def test_incompatible_checkpoint_fails_cleanly(sessions, database_url, checkpoints):
    analysis_id, intent = await _start(sessions)
    async with sessions() as session:
        await session.execute(
            text("UPDATE analyses SET graph_version = '0' WHERE id = :id"), {"id": analysis_id}
        )
        await session.commit()

    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models={},
    )

    assert status == "failed"
    async with sessions() as session:
        error = await session.scalar(text("SELECT error FROM analyses WHERE id = :id"), {"id": analysis_id})
    assert error["code"] == "INCOMPATIBLE_CHECKPOINT"
    assert (await _events(sessions, analysis_id))[-1]["detail"] == {"status": "failed"}


async def test_cancel_arriving_just_before_the_pause_cancels(
    sessions, database_url, checkpoints, monkeypatch
):
    analysis_id, intent = await _start(sessions)
    real_pause = FencedWriter.pause

    async def cancel_then_pause(self, *args, **kwargs):
        await request_cancel(sessions, analysis_id)  # after the last step boundary, before the commit
        return await real_pause(self, *args, **kwargs)

    monkeypatch.setattr(FencedWriter, "pause", cancel_then_pause)
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models={"bedrock": ScriptedChatModel(replies=[tool_call("ResearchPlan", AMBIGUOUS_PLAN)])},
    )

    assert status == "cancelled"
    async with sessions() as session:
        row = (
            await session.execute(
                text("SELECT status, lease_owner, pending_interrupt_id FROM analyses WHERE id = :id"),
                {"id": analysis_id},
            )
        ).one()
    assert tuple(row) == ("cancelled", None, None)
    events = await _events(sessions, analysis_id)
    assert events[-1]["detail"] == {"status": "cancelled"}
    assert "clarification" not in [e["type"] for e in events]


async def test_cancel_during_the_report_step_discards_the_report(
    sessions, database_url, checkpoints, monkeypatch
):
    analysis_id, intent = await _start(sessions)
    real_emit = FencedWriter.emit

    async def emit_then_cancel(self, agent, type, title, detail=None):
        seq = await real_emit(self, agent, type, title, detail)
        if type == "report":  # the last step boundary has passed
            await request_cancel(sessions, analysis_id)
        return seq

    monkeypatch.setattr(FencedWriter, "emit", emit_then_cancel)
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models={
            "bedrock": ScriptedChatModel(replies=_happy_path_script()),
            "openai": ScriptedChatModel(replies=[ALL_SUPPORTED]),
        },
    )

    assert status == "cancelled"
    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert report is None
    assert (await _events(sessions, analysis_id))[-1]["detail"] == {"status": "cancelled"}


async def test_accepted_answer_survives_a_crash_before_the_graph_resumes(sessions, database_url, checkpoints):
    analysis_id, version = await _pause_for_clarification(sessions, database_url, checkpoints)
    await submit_clarification(sessions, analysis_id, version, {"answer": "Information & Communications"})
    # A worker claims the answer and dies before the graph records it.
    assert await claim(sessions, analysis_id, await _resume_intent(sessions, analysis_id), "killed")
    await _expire_lease(sessions, analysis_id)
    assert (await reconcile(sessions, FakeQueue())).resumed == 1

    planner = ScriptedChatModel(replies=_happy_path_script())
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        await _resume_intent(sessions, analysis_id),  # the reconciler's intent carries no answer
        "recovery",
        checkpoints=checkpoints,
        models={"bedrock": planner, "openai": ScriptedChatModel(replies=[ALL_SUPPORTED])},
    )

    assert status == "completed"
    assert "The researcher clarified: Information & Communications" in str(planner.calls[0][-1].content)
    assert [e["type"] for e in await _events(sessions, analysis_id)].count("clarification") == 1


async def test_crash_before_the_pause_commits_asks_again(sessions, database_url, checkpoints, monkeypatch):
    analysis_id, intent = await _start(sessions)

    async def die(self, *args, **kwargs):
        raise WorkerKilled

    monkeypatch.setattr(FencedWriter, "pause", die)
    with pytest.raises(WorkerKilled):
        await execute(
            sessions,
            None,
            _settings(database_url),
            analysis_id,
            intent,
            "killed",
            checkpoints=checkpoints,
            models={"bedrock": ScriptedChatModel(replies=[tool_call("ResearchPlan", AMBIGUOUS_PLAN)])},
        )
    monkeypatch.undo()
    await _expire_lease(sessions, analysis_id)
    await reconcile(sessions, FakeQueue())

    # The question was never shown, so the resumed run raises it again rather than inventing an answer.
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        await _resume_intent(sessions, analysis_id),
        "recovery",
        checkpoints=checkpoints,
        models={},
    )
    assert status == "awaiting_input"


async def test_crashed_execution_time_is_charged_on_resume(sessions, database_url, checkpoints, monkeypatch):
    analysis_id, intent = await _start(sessions)
    clock = [time.monotonic()]
    # Only the runner's clock is faked; the event loop keeps real time, so heartbeats still fire.
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(runner, "HEARTBEAT_S", 0.01)
    real_save_plan = FencedWriter.save_plan

    async def work_200s_then_die(self, plan):
        await real_save_plan(self, plan)
        clock[0] += 200  # 200 s of active work...
        await asyncio.sleep(0.1)  # ...across which heartbeats keep reporting it
        raise WorkerKilled

    monkeypatch.setattr(FencedWriter, "save_plan", work_200s_then_die)
    with pytest.raises(WorkerKilled):
        await execute(
            sessions,
            None,
            _settings(database_url),
            analysis_id,
            intent,
            "killed",
            checkpoints=checkpoints,
            models={"bedrock": ScriptedChatModel(replies=[tool_call("ResearchPlan", PLAN)])},
        )
    monkeypatch.setattr(FencedWriter, "save_plan", real_save_plan)
    await _expire_lease(sessions, analysis_id)
    await reconcile(sessions, FakeQueue())

    budgets: list[float] = []
    real_context = runner.AgentContext

    def recording_context(**kwargs):
        budgets.append(kwargs["deadline"] - clock[0])
        return real_context(**kwargs)

    monkeypatch.setattr(runner, "AgentContext", recording_context)
    await execute(
        sessions,
        None,
        _settings(database_url, analysis_deadline_s=240),
        analysis_id,
        await _resume_intent(sessions, analysis_id),
        "recovery",
        checkpoints=checkpoints,
        models={},
    )
    # 240 s budget - 200 s reported by heartbeats - 15 s charged for the unreported interval.
    assert budgets == [pytest.approx(25, abs=0.5)]


@pytest.mark.parametrize("plan", [AMBIGUOUS_PLAN, {**PLAN, "in_scope": False, "scope_note": "Not covered."}])
async def test_heartbeat_in_flight_during_pause_or_finish_is_not_lost(
    sessions, database_url, checkpoints, monkeypatch, plan
):
    """A heartbeat that has measured its interval but not yet committed it must not lose that time
    when the run pauses (ambiguous plan) or finishes (out-of-scope plan) meanwhile."""
    analysis_id, intent = await _start(sessions)
    clock = [time.monotonic()]
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(runner, "HEARTBEAT_S", 0.01)
    real_renew = runner.renew_lease

    async def slow_renew(*args, active_ms=0, **kwargs):
        if active_ms:
            await asyncio.sleep(0.3)  # the write carrying the 100 s is still in flight as the run ends
        return await real_renew(*args, active_ms=active_ms, **kwargs)

    monkeypatch.setattr(runner, "renew_lease", slow_renew)

    def plan_after_100s(messages):
        clock[0] += 100  # 100 s of active work...
        time.sleep(0.05)  # ...measured by a heartbeat while this reply is produced (executor thread)
        return tool_call("ResearchPlan", plan)

    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models={"bedrock": ScriptedChatModel(replies=[plan_after_100s])},
    )

    assert status in {"awaiting_input", "completed_with_limitations"}
    async with sessions() as session:
        active_ms = await session.scalar(
            text("SELECT active_ms_used FROM analyses WHERE id = :id"), {"id": analysis_id}
        )
    assert 100_000 <= active_ms < 101_000


async def test_a_narrative_checked_by_its_own_writer_is_disclosed_as_not_independent(
    sessions, database_url, checkpoints
):
    analysis_id, intent = await _start(sessions)
    models = {
        # The independent judge (OpenAI) is unavailable, so the writer (Bedrock) has to judge itself.
        "bedrock": ScriptedChatModel(replies=[*_happy_path_script(), ALL_SUPPORTED]),
        "openai": ScriptedChatModel(replies=[TimeoutError(), TimeoutError()]),
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
    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))
    assert report["verification"]["narrative_check"] == {
        "writers": ["bedrock"],
        "judges": ["bedrock"],
        "independent": False,
    }
    assert any("check was not independent" in item["text"] for item in report["limitations"])


async def test_report_lists_what_was_checked_on_each_dataset(sessions, database_url, checkpoints):
    analysis_id, intent = await _start(sessions)
    models = {
        "bedrock": ScriptedChatModel(replies=_happy_path_script()),
        "openai": ScriptedChatModel(replies=[ALL_SUPPORTED]),
    }
    await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models=models,
    )
    async with sessions() as session:
        report = await session.scalar(select(ReportRow.content).where(ReportRow.analysis_id == analysis_id))

    panel = {d["dataset_id"]: d for d in report["data_quality"]}
    assert panel["M182841"]["role"] == "evidence" and panel["M182841"]["series"] == [EMPLOYMENT]
    assert panel[VACANCIES_DS]["role"] == "evidence"
    # The mirror of M182841 was only used to cross-check it.
    assert panel["d_d2518fed6cc2014f0cd061b4570a9592"]["role"] == "cross-check"
    codes = {c["code"] for c in panel["M182841"]["checks"]}
    assert "SERVED_FROM_SNAPSHOT" in codes
    for dataset in panel.values():
        for marker in dataset["markers"]:
            assert marker["meaning"] and marker["treatment"].startswith("set to null")


async def test_fallback_events_say_the_outage_was_injected(sessions, database_url, checkpoints, redis_client):
    from app.core.faults import Faults

    analysis_id, intent = await _start(sessions)
    await Faults(redis_client, enabled=True).switch_on("llm:bedrock")
    models = {"openai": ScriptedChatModel(replies=[*_happy_path_script(), ALL_SUPPORTED])}

    status = await execute(
        sessions,
        redis_client,
        _settings(database_url, enable_fault_injection=True),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models=models,
    )

    assert status == "completed"
    fallbacks = [e for e in await _events(sessions, analysis_id) if e["type"] == "provider_fallback"]
    # Including those after the circuit opened: the cause it remembers is the injected fault.
    assert fallbacks and all(
        e["title"] == "bedrock switched off (injected fault (demo)); answered by openai" for e in fallbacks
    )
    assert all("injected fault (demo)" in e["detail"]["reason"] for e in fallbacks)


async def test_proceeding_without_a_sector_plans_again_with_a_default(sessions, database_url, checkpoints):
    # "How is the sector doing?": the question is about the sector, so there is no plan to proceed with.
    open_question = {**AMBIGUOUS_PLAN, "sectors": [], "clarification_question": "Which sector do you mean?"}
    analysis_id, intent = await _start(sessions)
    paused = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models={"bedrock": ScriptedChatModel(replies=[tool_call("ResearchPlan", open_question)])},
    )
    assert paused == "awaiting_input"
    question = next(e for e in await _events(sessions, analysis_id) if e["type"] == "clarification")

    await submit_clarification(sessions, analysis_id, question["detail"]["version"], {"proceed": True})
    # The re-plan still says it would like to ask: once the researcher has chosen, it does not ask again.
    planner = ScriptedChatModel(
        replies=[
            tool_call("ResearchPlan", {**AMBIGUOUS_PLAN, "needs_clarification": True}),
            *_happy_path_script()[1:],
        ]
    )
    status = await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        await _resume_intent(sessions, analysis_id),
        "test",
        checkpoints=checkpoints,
        models={"bedrock": planner, "openai": ScriptedChatModel(replies=[ALL_SUPPORTED])},
    )

    assert status == "completed"
    assert "most sensible default sector and measure" in str(planner.calls[0][-1].content)
    assert [e["type"] for e in await _events(sessions, analysis_id)].count("clarification") == 1


async def test_a_policy_route_gives_its_own_objective_not_the_refused_one(
    sessions, database_url, checkpoints
):
    refused_objective = "Find the recruitment rate in info_comms"
    script = [
        tool_call("ResearchPlan", PLAN),
        tool_call(
            "NextAction", {"action": "extract", "objective": "Find the series", "rationale": "None yet."}
        ),
        act("fetch_dataset", {"dataset_id": "M182841"}),
        act("select_series", {"series_key": EMPLOYMENT, "reason": "ICT employment, full coverage"}),
        act("finish", {"summary": "Employment selected."}),
        tool_call(
            "NextAction", {"action": "extract", "objective": "Find vacancies", "rationale": "One missing."}
        ),
        act("finish", {"summary": "Nothing else fits."}),
        # Both extraction rounds are used: this proposal is refused and policy routes to analytics.
        tool_call(
            "NextAction", {"action": "extract", "objective": refused_objective, "rationale": "Try again."}
        ),
        act("finish", {"summary": "No statistics drafted."}),
        tool_call("NextAction", {"action": "report", "objective": "Write the report", "rationale": "Done."}),
        tool_call("ReportNarrative", {"title": "ICT employment", "summary": "", "limitations": []}),
    ]
    planner = ScriptedChatModel(replies=script)
    analysis_id, intent = await _start(sessions)
    await execute(
        sessions,
        None,
        _settings(database_url),
        analysis_id,
        intent,
        "test",
        checkpoints=checkpoints,
        models={"bedrock": planner, "openai": ScriptedChatModel(replies=[ALL_SUPPORTED])},
    )

    overridden = next(
        e["detail"]
        for e in await _events(sessions, analysis_id)
        if e["type"] == "decision" and e["detail"]["policy_override"]
    )
    assert overridden["action"] == "analyse"
    assert (
        overridden["objective"]
        == "Compute statistics on the selected series and draft findings (policy route)"
    )
    analytics_task = next(
        str(m.content)
        for call in planner.calls
        for m in call
        if "Objective from the Coordinator: Compute" in str(m.content)
    )
    assert refused_objective not in analytics_task
