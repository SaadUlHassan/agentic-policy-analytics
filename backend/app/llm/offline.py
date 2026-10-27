"""Offline stand-in for the LLM providers (LLM_MODE=offline): end-to-end tests and load runs.

It answers each step the way an agent following the prompts would, from what the step asks for
(the tool or schema bound) and the conversation so far, so a full analysis runs without any model,
cost or network. It knows one research topic: ICT employment and vacancies. An ambiguous question
("How is the sector doing?") is asked about. The deterministic checks verify everything it drafts,
exactly as for a real model. The settings refuse this mode in production, and the ledger records
its calls as offline-<provider>, so its output can never pass for a real model's.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.core.config import Provider

EMPLOYMENT_DATASET, EMPLOYMENT = "M182841", "M182841:3.4@SSIC2020"
VACANCIES_DATASET = "d_3f17bbf67d31d4d402caa8755eb74afc"
VACANCIES = f"{VACANCIES_DATASET}:information and communications@SSIC2020"
_AMBIGUOUS = re.compile(r"how is the sector doing", re.IGNORECASE)
_YEARS = re.compile(r"\b(20\d{2})\b")


def _call(name: str, args: dict[str, Any], n: int = 0) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": f"call_{n}", "type": "tool_call"}]
    )


def _act(name: str, args: dict[str, Any], rationale: str, n: int) -> AIMessage:
    return _call(name, {**args, "rationale": rationale}, n)


def _question(messages: Sequence[BaseMessage]) -> str:
    return next((str(m.content) for m in messages if isinstance(m, HumanMessage)), "")


def _plan(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    question = _question(messages)
    clarified = any("The researcher clarified" in str(m.content) for m in messages)
    years = sorted({int(y) for y in _YEARS.findall(question)})
    if len(years) < 2:  # its computations need a span of at least two years
        years = [2020, 2024]
    plan: dict[str, Any] = {
        "intent": "Employment and job vacancies in Information & Communications",
        "in_scope": True,
        "sectors": ["info_comms"],
        "metrics": ["employment_level", "job_vacancies"],
        "start_year": years[0],
        "end_year": years[-1],
        "sub_questions": ["How did ICT employment change?", "How did ICT vacancies change?"],
        "assumptions": ["'Technology sector' is read as Information & Communications (SSIC 2020 J)."],
        "rationale": "Employment levels and vacancies together show realised and unmet labour demand.",
    }
    if _AMBIGUOUS.search(question) and not clarified:
        plan |= {
            "sectors": [],
            "needs_clarification": True,
            "clarification_question": "Which sector do you mean?",
            "clarification_options": ["Information & Communications", "IT & Other Information Services"],
        }
    return plan


def _next_action(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    evidence = json.loads(str(messages[-1].content).split("Evidence so far: ", 1)[1])
    if not evidence["selected_series"]:
        return {
            "action": "extract",
            "objective": "Find ICT employment and vacancies",
            "rationale": "No evidence yet.",
        }
    if not evidence["claims_verified"] and evidence["rounds_used"]["analytics"] < 2:
        return {"action": "analyse", "objective": "Quantify changes", "rationale": "Series are selected."}
    return {"action": "report", "objective": "Write the report", "rationale": "Findings are verified."}


def _observations(messages: Sequence[BaseMessage]) -> list[str]:
    return [str(m.content) for m in messages if isinstance(m, ToolMessage)]


def _last_computation(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    for text in reversed(_observations(messages)):
        if text.startswith("{") and "computation_id" in text:
            return json.loads(text)
    raise RuntimeError("no computation observed yet")


def _claim_on_last(
    messages: Sequence[BaseMessage], predicate: str, field: str, n: int, lead_in: str = ""
) -> AIMessage:
    computation = _last_computation(messages)
    result = computation["fields"][field]
    assertion = {
        "predicate": predicate,
        "computation_id": computation["computation_id"],
        "field": field,
        "metric": result["metric"],
        "series_key": computation["series_key"],
        "interval_start": result["interval"]["start"],
        "interval_end": result["interval"]["end"],
    }
    return _act("draft_claim", {"lead_in": lead_in, "assertions": [assertion]}, "Drafting a finding.", n)


def _extraction_step(messages: Sequence[BaseMessage]) -> AIMessage:
    steps = [
        ("fetch_dataset", {"dataset_id": EMPLOYMENT_DATASET}, "Fetching year-end employment by sector."),
        ("fetch_dataset", {"dataset_id": VACANCIES_DATASET}, "Fetching quarterly vacancies."),
        (
            "select_series",
            {"series_key": EMPLOYMENT, "reason": "ICT employment, full coverage"},
            "Selecting.",
        ),
        ("select_series", {"series_key": VACANCIES, "reason": "ICT vacancies, full coverage"}, "Selecting."),
        ("finish", {"summary": "Employment and vacancies selected."}, "Done."),
    ]
    n = len(_observations(messages))
    name, args, rationale = steps[min(n, len(steps) - 1)]
    return _act(name, args, rationale, n)


def _analytics_step(messages: Sequence[BaseMessage], window: tuple[str, str]) -> AIMessage:
    n = len(_observations(messages))
    start, end = window
    if n == 0:
        return _act(
            "compute", {"tool": "cagr", "series_key": EMPLOYMENT, "start": start, "end": end}, "CAGR.", n
        )
    if n == 1:
        return _claim_on_last(messages, "cagr.growth", "cagr_pct", n)
    if n == 2:
        args = {"tool": "change_between", "series_key": VACANCIES, "start": f"{start}-Q1", "end": f"{end}-Q4"}
        return _act("compute", args, "Vacancy change.", n)
    if n == 3:
        return _claim_on_last(messages, "change.increase", "pct_change", n, "Over the same period,")
    return _act("finish", {"summary": "Two findings verified."}, "Done.", n)


def _window(messages: Sequence[BaseMessage]) -> tuple[str, str]:
    plan = json.loads(str(messages[1].content).split("Research plan: ", 1)[1].split("\n", 1)[0])
    return str(plan["start_year"]), str(plan["end_year"])


def _verdicts(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    sentences = str(messages[-1].content).split("Sentences to check:\n", 1)[1].splitlines()
    return {
        "verdicts": [
            {"index": i, "supported": True, "reason": "restates the findings"} for i in range(len(sentences))
        ]
    }


class OfflineChatModel(BaseChatModel):
    provider: Provider
    bound: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "offline"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> OfflineChatModel:
        names = [getattr(t, "name", None) or getattr(t, "__name__", None) or t.get("name", "") for t in tools]
        return self.model_copy(update={"bound": [str(n) for n in names]})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        reply = self._reply(messages)
        # Offline replies report a token count of zero, so usage and cost are known (and nil).
        reply.usage_metadata = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        bound = set(self.bound)
        if "ResearchPlan" in bound:
            return _call("ResearchPlan", _plan(messages))
        if "NextAction" in bound:
            return _call("NextAction", _next_action(messages))
        if "ReportNarrative" in bound:
            narrative = {
                "title": "ICT employment and vacancies",
                "summary": "Employment and vacancies rose.",
                "limitations": [],
            }
            return _call("ReportNarrative", narrative)
        if "SupportVerdicts" in bound:
            return _call("SupportVerdicts", _verdicts(messages))
        if "OptionChoice" in bound:
            return _call("OptionChoice", {"options": []})  # falls back to the plan's first options
        if "fetch_dataset" in bound:
            return _extraction_step(messages)
        if "compute" in bound:
            return _analytics_step(messages, _window(messages))
        raise RuntimeError(f"offline model: no answer for tools {sorted(bound)}")


def offline_models() -> dict[Provider, BaseChatModel]:
    return {"bedrock": OfflineChatModel(provider="bedrock"), "openai": OfflineChatModel(provider="openai")}
