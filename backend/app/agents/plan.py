"""The Coordinator's research plan and the vocabulary it may use."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.connectors.catalog import Catalog
from app.data.taxonomy import Taxonomy

SCHEME = "SSIC2020"


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
    sub_questions: list[str] = Field(default=[], description="Two to four concrete questions to answer")
    assumptions: list[str] = Field(
        default=[], description="Interpretations made, e.g. how a sector was mapped"
    )
    rationale: str = Field(description="Two sentences, shown to the user, explaining this plan")


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
    """Problems with a plan the LLM produced; empty when it only uses known vocabulary."""
    problems = [f"unknown sector {s!r}" for s in plan.sectors if s not in sectors]
    problems += [f"unknown metric {m!r}" for m in plan.metrics if m not in metrics]
    if plan.in_scope:
        if not plan.sectors:
            problems.append("no sector chosen")
        if not plan.metrics:
            problems.append("no metric chosen")
        if plan.start_year and plan.end_year and plan.start_year > plan.end_year:
            problems.append("start_year is after end_year")
    return problems
