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
# "before 2020", "prior to 2020": an exclusive upper bound, unless the question names later years too.
_BEFORE = re.compile(r"\b(?:before|prior to)\s+(?:mid-|the end of\s+)?(19\d{2}|20\d{2})\b", re.IGNORECASE)
# "after mid-2022", "since 2020": what came after a year, through the latest complete year.
_AFTER = re.compile(
    r"\b(?:after|since)\s+(?:mid-|early\s+|late\s+|the end of\s+)?(19\d{2}|20\d{2})\b", re.IGNORECASE
)


# One year in a clarification moves one bound: "start from 2018", "since 2018" / "until 2022".
_FROM = re.compile(
    r"\b(?:from|since|after|starting(?:\s+(?:in|from|at))?|start(?:ing)?\s+(?:in|from|at)|beginning(?:\s+in)?)"
    r"\s+(?:mid-|early\s+|late\s+|the end of\s+)?(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
# In a before/after comparison, one year in a clarification names the pivot, not a bound.
_PIVOT = re.compile(
    r"\b(after|since|before|prior to)\s+(mid-|early\s+|late\s+|the end of\s+)?(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
# A before/after question names both sides; "compare ICT with manufacturing" compares sectors, not times.
_BEFORE_AND_AFTER = re.compile(
    r"\b(?:before|prior to)\b.*\b(?:after|since)\b|\b(?:after|since)\b.*\b(?:before|prior to)\b",
    re.IGNORECASE | re.DOTALL,
)
_UNTIL = re.compile(
    r"\b(?:to|until|till|through|up to|ending(?:\s+in)?)\s+(19\d{2}|20\d{2})\b", re.IGNORECASE
)


def _named_period(plan: ResearchPlan, text: str, latest_year: int) -> tuple[int, int]:
    """The period `text` names, by the rules `align_period` documents."""
    years = [int(y) for y in _YEAR.findall(text)]
    start: int | None
    if not years:
        span = plan.end_year - plan.start_year if plan.start_year and plan.end_year else 4
        return latest_year - max(span, 0), latest_year
    last = max(years)
    before = [int(y) for y in _BEFORE.findall(text)]
    if last in {int(y) for y in _AFTER.findall(text)}:
        start, end = min(years), latest_year
    elif before and last <= min(before):
        end = min(before) - 1
        start = min((y for y in years if y < min(before)), default=plan.start_year)
    else:
        start, end = min(years), last
    if start is None or start > end:
        start = end - 4
    return start, end


def _pivot(answer: str) -> str | None:
    """The first period of the later part a one-year answer names: "since 2021" → 2021, "after 2023"
    → 2024, "after mid-2023" → 2023-Q3, "before 2021" → 2021."""
    m = _PIVOT.search(answer)
    if m is None:
        return None
    word, qualifier, year = m.group(1).lower(), (m.group(2) or "").strip().lower(), int(m.group(3))
    if qualifier == "mid-":
        return f"{year}-Q3"
    if (
        word == "since"
        or qualifier == "early"
        or (word in {"before", "prior to"} and qualifier != "the end of")
    ):
        return str(year)
    return str(year + 1)


def align_period(
    plan: ResearchPlan, question: str, latest_year: int, answer: str | None = None
) -> ResearchPlan:
    """The plan's period is the one the question names, decided in this order:
    - "after" or "since" the latest year named: from the earliest year named to `latest_year` (the
      last complete year), so a before/after comparison keeps its later side;
    - "before" the latest year named: up to the year before it, from the earliest earlier year named,
      or the plan's own start when none is (e.g. "the five years before 2020");
    - otherwise: from the earliest year named to the latest.
    A question that names no year ("recently", "the last five years") gets a period ending at
    `latest_year`, keeping the plan's span (five years when it has none): models default to stale
    years when left to choose.
    A clarification `answer` that names years has the last word: one year with a direction moves
    only that bound ("start from 2018", "until 2022"), keeping the other; otherwise the answer's own
    period replaces the question's. In a before/after comparison, one year with "after", "since" or
    "before" moves the comparison's pivot instead, and the window keeps both sides of it."""
    if not plan.in_scope:
        return plan
    start, end = _named_period(plan, question, latest_year)
    reason = (
        "to match the years in the question"
        if _YEAR.search(question)
        else "because the question names no years, so it ends at the latest complete year"
    )
    pivot, notes = plan.comparison_start, []
    named = {int(y) for y in _YEAR.findall(answer or "")}
    comparing = plan.comparison_start is not None or bool(_BEFORE_AND_AFTER.search(question))
    if named:
        reason = "to match the years in the researcher's answer"
        year = next(iter(named)) if len(named) == 1 else None
        moved = _pivot(answer or "") if year is not None and comparing else None
        if moved is not None and int(moved[:4]) > latest_year:
            notes.append(
                f"The researcher's split at {moved} is after the latest complete year ({latest_year}), so "
                f"there is nothing after it to compare; the comparison keeps its split at "
                f"{plan.comparison_start or 'the middle of the period'}."
            )
        elif moved is not None:
            # Keep both sides of the new pivot inside the window.
            pivot, split = moved, int(moved[:4])
            start = min(start, split - 1 if len(moved) == 4 else split)
            end = max(end, min(split, latest_year))
        elif year is not None and _FROM.search(answer or "") and year <= end:
            start = year
        elif year is not None and _BEFORE.search(answer or "") and year - 1 >= start:
            end = year - 1
        elif year is not None and _UNTIL.search(answer or "") and year >= start:
            end = year
        else:
            start, end = _named_period(plan, answer or "", latest_year)
    had = f"{plan.start_year}-{plan.end_year}" if plan.start_year and plan.end_year else "no period"
    if pivot != plan.comparison_start:
        notes.append(
            f"The comparison was set to split at {pivot}, over {start}-{end}, {reason} "
            f"(the plan split at {plan.comparison_start or 'no point'} over {had})."
        )
    elif (start, end) != (plan.start_year, plan.end_year):
        notes.append(f"The period was set to {start}-{end} {reason} (the plan had {had}).")
    if not notes:
        return plan
    return plan.model_copy(
        update={
            "start_year": start,
            "end_year": end,
            "comparison_start": pivot,
            "assumptions": [*plan.assumptions, *notes],
        }
    )
