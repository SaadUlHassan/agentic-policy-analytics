"""Qualitative check of narrative prose against verified findings (plan §3.6).

Deterministic checks catch numbers and causal wording; they cannot catch a plausible sentence that
adds facts the evidence does not contain. An LLM judge, preferably a different provider from the
one that wrote the text, marks each sentence supported or not; unsupported sentences are removed.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm.router import LLMRouter

_JUDGE = """You check a policy report's narrative against its verified findings.
For each numbered sentence decide whether it is supported: it may summarise, combine or rephrase the
findings, or note what the findings do not cover, but it must not add any fact, trend, cause, group,
region or detail that the findings do not state. When unsure, mark it unsupported."""


class SentenceVerdict(BaseModel):
    index: int
    supported: bool
    reason: str = Field(description="One short phrase")


class SupportVerdicts(BaseModel):
    verdicts: list[SentenceVerdict]


async def unsupported_sentences(
    router: LLMRouter, findings: list[str], sentences: list[str], *, deadline: float
) -> dict[int, str]:
    """Index -> reason for each sentence the judge did not accept. A sentence the judge skipped is
    treated as unsupported."""
    if not sentences:
        return {}
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    verdicts = await router.structured(
        SupportVerdicts,
        [
            SystemMessage(_JUDGE),
            HumanMessage(
                "Verified findings:\n"
                + ("\n".join(f"- {f}" for f in findings) or "(none)")
                + f"\n\nSentences to check:\n{numbered}"
            ),
        ],
        agent="coordinator",
        purpose="narrative_check",
        deadline=deadline,
        prefer_independent=True,
    )
    judged = {v.index: v for v in verdicts.verdicts}
    return {
        i: (judged[i].reason if i in judged else "not judged")
        for i in range(len(sentences))
        if i not in judged or not judged[i].supported
    }
