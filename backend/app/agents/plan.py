"""The Coordinator's research plan and the vocabulary it may use."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.connectors.catalog import Catalog
from app.data.taxonomy import Taxonomy

SCHEME = "SSIC2020"
MAX_CLARIFICATION_OPTIONS = 4
MAX_QUESTION_CHARS = 200


class ResearchPlan(BaseModel):
    intent: str = Field(description="One sentence: what the researcher wants to know")
    in_scope: bool = Field(
        description="False if the question is outside Singapore labour-market data by industry"
    )
    scope_note: str = Field(default="", description="If out of scope, why, in one sentence")
    sectors: list[str] = Field(default=[], description="Sector keys from the allowed list")
    metrics: list[str] = Field(default=[], description="Metric names from the allowed list")
    start_year: int | None = Field(default=None, description="First year of the period of interest")
    end_year: int | None = Field(default=None, description="Last year of the period of interest")
    comparison_start: str | None = Field(
        default=None,
        description="If the question compares before and after a point in time, the first period of "
        "the later part, e.g. '2022-Q3' for 'after mid-2022' or '2023' for 'since 2023'; otherwise null",
    )
    frequency: Literal["annual", "quarterly"] | None = Field(
        default=None,
        description="Only if the researcher asks for annual or quarterly figures; otherwise null",
    )
    sub_questions: list[str] = Field(default=[], description="Two to four concrete questions to answer")
    assumptions: list[str] = Field(
        default=[], description="Interpretations made, e.g. how a sector was mapped"
    )
    rationale: str = Field(description="Two sentences, shown to the user, explaining this plan")
    needs_clarification: bool = Field(
        default=False, description="True only if no sensible default interpretation exists"
    )
    clarification_question: str = Field(default="", description="One question for the researcher")
    clarification_options: list[str] = Field(default=[], description="Two to four concrete answers to offer")


class NextAction(BaseModel):
    action: Literal["extract", "analyse", "report"]
    objective: str = Field(description="What the delegated agent should achieve next")
    rationale: str = Field(description="One or two sentences, shown to the user, explaining the decision")


def vocabulary(catalog: Catalog, taxonomy: Taxonomy) -> tuple[dict[str, str], dict[str, str]]:
    sectors = {s.key: s.label for s in taxonomy.sectors(SCHEME)}
    metrics: dict[str, str] = {}
    for entry in catalog.datasets.values():
        if entry.catalogued and entry.metric:
            metrics.setdefault(entry.metric, entry.description.split(".")[0])
    return sectors, metrics


def validate_plan(plan: ResearchPlan, sectors: dict[str, str], metrics: dict[str, str]) -> list[str]:
    """Problems with a plan the LLM produced; empty when it only uses known vocabulary. A plan that
    asks the researcher may leave the sector or metric open: that is what it asks about."""
    problems = [f"unknown sector {s!r}" for s in plan.sectors if s not in sectors]
    problems += [f"unknown metric {m!r}" for m in plan.metrics if m not in metrics]
    if plan.in_scope:
        if not plan.sectors and not plan.needs_clarification:
            problems.append("no sector chosen")
        if not plan.metrics and not plan.needs_clarification:
            problems.append("no metric chosen")
        if plan.start_year and plan.end_year and plan.start_year > plan.end_year:
            problems.append("start_year is after end_year")
    return problems


def clarification_problems(plan: ResearchPlan) -> list[str]:
    """How a question for the researcher should be put. Asked to be fixed, never a reason to refuse."""
    if not plan.needs_clarification:
        return []
    problems = []
    if len(plan.clarification_options) > MAX_CLARIFICATION_OPTIONS:
        problems.append(
            f"offer at most {MAX_CLARIFICATION_OPTIONS} clarification options, "
            f"not {len(plan.clarification_options)}"
        )
    if len(plan.clarification_question) > MAX_QUESTION_CHARS:
        problems.append(
            "ask one short question; put the choices in clarification_options, not in the question"
        )
    return problems


def shorten_question(plan: ResearchPlan) -> ResearchPlan:
    """A question that still lists its choices after a repair is cut to its first sentence: the
    choices are shown as options."""
    if len(plan.clarification_question) <= MAX_QUESTION_CHARS:
        return plan
    first = re.match(r"[^?.]*[?.]", plan.clarification_question)
    question = first.group(0) if first else plan.clarification_question[:MAX_QUESTION_CHARS]
    return plan.model_copy(update={"clarification_question": question.strip()})


def cap_options(plan: ResearchPlan) -> ResearchPlan:
    """The last resort for a long option list: shortened, never a reason to refuse the question."""
    return plan.model_copy(
        update={"clarification_options": plan.clarification_options[:MAX_CLARIFICATION_OPTIONS]}
    )


# A year the question names ("SSIC 2020" names a classification, not a year).
_YEAR = re.compile(r"(?<!SSIC )(?<!SSIC)\b(19\d{2}|20\d{2})\b", re.IGNORECASE)
# "before 2020", "until 2020", "prior to 2020": the period ends the year before.
_BEFORE = re.compile(
    r"\b(?:before|until|prior to)\s+(?:mid-|the end of\s+)?(19\d{2}|20\d{2})\b", re.IGNORECASE
)


def align_period(plan: ResearchPlan, question: str, latest_year: int) -> ResearchPlan:
    """The plan's period is the one the question names. It runs from the earliest year named to the
    latest; to `latest_year` (the last complete year) when the question asks about what came after or
    since its latest year; and up to the year before one it is "before". Where the question names no
    start (e.g. "the five years before 2020"), the plan's own start is kept."""
    years = [int(y) for y in _YEAR.findall(question)]
    if not plan.in_scope or not years:
        return plan
    before = [int(y) for y in _BEFORE.findall(question)]
    within = [y for y in years if y not in before]
    open_ended = bool(within) and re.search(
        rf"\b(after|since)\b[^?.]*\b{max(within)}\b", question, re.IGNORECASE
    )
    if before:
        end = min(before) - 1
    elif open_ended:
        end = latest_year
    else:
        end = max(within)
    start = min(within) if within else plan.start_year
    if start is None or start > end:
        start = end - 4
    if (start, end) == (plan.start_year, plan.end_year):
        return plan
    had = f"{plan.start_year}-{plan.end_year}" if plan.start_year and plan.end_year else "no period"
    note = f"The period was set to {start}-{end} to match the years in the question (the plan had {had})."
    return plan.model_copy(
        update={"start_year": start, "end_year": end, "assumptions": [*plan.assumptions, note]}
    )
