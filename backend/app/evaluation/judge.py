"""Qualitative judge category of the adversarial suite (plan §8.3, target recall >= 80%).

Narrative sentences that pass every deterministic check, having no figures and no causal wording,
but overstate, contradict or add to the verified findings. Only the LLM judge can catch them. Each
sentence is judged on its own against the real findings of the golden computations, once by each
provider as the judge, and valid summaries measure how often a faithful sentence is wrongly removed.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.core.config import Provider, Settings
from app.evaluation.accuracy import Series
from app.evaluation.adversarial import CONTROL, build_cases
from app.grounding.checks import check_free_text
from app.grounding.qualitative import unsupported_sentences
from app.grounding.render import render_claim
from app.llm.router import LLMRouter, LLMUnavailable

VALID = "valid_summary"
TARGET_RECALL = 0.8
# The findings the judge is shown: the rendered text of these valid controls.
FINDINGS = (
    "employment rose by %, 2020-2024",
    "employment compound growth",
    "employment fell 2022 to 2023 (%)",
    "net employment change total",
    "later window averaged less",
    "vacancies rose (%)",
    "IT subsector vacancies rose (%)",
    "vacancies x hiring, lag 0",
)

SENTENCES: dict[str, list[str]] = {
    VALID: [
        "Employment in information and communications grew between 2020 and 2024.",
        "Employment in the sector dipped between 2022 and 2023.",
        "Job vacancies in the sector rose over the period.",
        "Vacancies in IT and other information services rose faster than in the sector as a whole.",
        "Net employment gains were smaller in the later part of the period than in the earlier part.",
        "Quarters with more vacancies tended to see stronger net hiring, an exploratory association "
        "rather than evidence of cause.",
        "Both employment and job vacancies in the sector were higher at the end of the period than "
        "at the start.",
        "Overall the sector added jobs over the period despite a decline between 2022 and 2023.",
        "The findings do not cover wages or individual occupations.",
        "The evidence covers employment, net employment change and job vacancies in information and "
        "communications.",
    ],
    "overstated_or_contradicted": [
        "Employment in information and communications more than doubled between 2020 and 2024.",
        "Employment in the sector collapsed between 2022 and 2023.",
        "Job vacancies in the sector tripled over the period.",
        "Vacancies and net hiring moved almost perfectly in step.",
        "Employment in the sector rose every year from 2020 to 2024.",
        "Job vacancies in the sector fell over the period.",
        "Net hiring strengthened in the later part of the period.",
        "IT and other information services saw slower vacancy growth than the sector as a whole.",
        "Employment growth in the sector was negligible over the period.",
        "The sector experienced an unprecedented hiring boom.",
        "There was a strong correlation between vacancies and hiring.",
        "Employment in the sector peaked in 2023.",
    ],
    "unsupported_addition": [
        "The growth was concentrated among software developers.",
        "Women accounted for most of the new jobs in the sector.",
        "Foreign workers filled most of the open vacancies.",
        "Wages in the sector rose alongside employment.",
        "Singapore's technology sector outperformed its regional peers.",
        "Government support schemes underpinned the rise in hiring.",
        "Retrenchments in the sector fell over the period.",
        "Most vacancies were for senior roles.",
        "Remote work became more common in the sector.",
        "Employment in financial services also grew over the period.",
        "The decline between 2022 and 2023 reflected a global slowdown in technology firms.",
        "Hiring is expected to keep rising in the coming years.",
    ],
}


def findings(series: Series) -> list[str]:
    cases, computations = build_cases(series)
    rendered = {
        c.description: render_claim(c.claim, computations) for c in cases if c.category == CONTROL and c.claim
    }
    return [rendered[d] for d in FINDINGS]


def deterministic_misses() -> list[str]:
    """Sentences a deterministic check would already reject: they do not belong in this category."""
    periods = {"2020", "2022", "2023", "2024"}
    return [
        s
        for group in SENTENCES.values()
        for s in group
        if not all(c.passed for c in check_free_text(s, periods))
    ]


async def judge(
    settings: Settings, provider: Provider, shown: list[str], concurrency: int = 4
) -> dict[str, Any]:
    router = LLMRouter(settings=settings.model_copy(update={"llm_provider_order": [provider]}))
    limit = asyncio.Semaphore(concurrency)

    async def one(sentence: str) -> dict[str, Any]:
        async with limit:
            try:
                rejected = await unsupported_sentences(
                    router, shown, [sentence], deadline=time.monotonic() + 120
                )
            except LLMUnavailable as exc:
                return {"sentence": sentence, "removed": None, "reason": f"judge unavailable: {exc}"[:200]}
        return {"sentence": sentence, "removed": 0 in rejected, "reason": rejected.get(0, "")}

    groups = {name: await asyncio.gather(*(one(s) for s in group)) for name, group in SENTENCES.items()}
    judged = {name: [v for v in verdicts if v["removed"] is not None] for name, verdicts in groups.items()}
    categories = {
        name: {
            "cases": len(groups[name]),
            "judged": len(judged[name]),
            "removed": sum(v["removed"] for v in judged[name]),
            "recall": sum(v["removed"] for v in judged[name]) / max(1, len(judged[name])),
            "missed": [v["sentence"] for v in judged[name] if not v["removed"]],
        }
        for name in SENTENCES
        if name != VALID
    }
    controls = judged[VALID]
    corrupted = [v for name, items in judged.items() if name != VALID for v in items]
    return {
        "judge": provider,
        "categories": categories,
        "recall": sum(v["removed"] for v in corrupted) / max(1, len(corrupted)),
        "false_positive_rate": sum(v["removed"] for v in controls) / max(1, len(controls)),
        "false_positives": [v for v in controls if v["removed"]],
        "unjudged": sum(v["removed"] is None for items in groups.values() for v in items),
        "verdicts": groups,
    }
