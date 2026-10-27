"""The live suites' fixed parts: judge sentences and resilience scenarios (no LLM calls)."""

from __future__ import annotations

from app.evaluation import judge, live
from app.evaluation.golden import golden_series
from app.evaluation.resilience import scenarios


def test_judge_sentences_pass_every_deterministic_check():
    # Otherwise the deterministic suite, not the judge, would be what catches them.
    assert judge.deterministic_misses() == []


async def test_the_judge_is_shown_real_rendered_findings():
    shown = judge.findings(await golden_series())
    assert len(shown) == len(judge.FINDINGS)
    assert "rose by 14.4% between 2020 and 2024" in shown[0]


def test_every_resilience_scenario_is_checked_or_explained():
    for s in scenarios("q"):
        assert (s.spec is not None and s.check is not None) or (s.spec is None and s.not_applicable)
    assert {s.name for s in scenarios("q")} >= {
        "fallback_bedrock_to_openai",
        "fallback_openai_to_bedrock",
        "verifier_provider_unavailable",
        "total_outage_early",
        "total_outage_late",
    }


def test_the_relevance_tally_counts_only_single_marks(tmp_path):
    def entry(query: str, relevant: str, not_relevant: str) -> str:
        heading = f"## {query} (bedrock primary): q\n\n"
        return heading + f"- [{relevant}] Relevant\n- [{not_relevant}] Not relevant. Why:\n\n"

    sheet = tmp_path / "relevance_review.md"
    sheet.write_text("# Relevance review\n\n" + entry("G01", " ", " ") + entry("G02", " ", " "))
    assert live.relevance_tally(tmp_path) is None  # not reviewed yet

    sheet.write_text(
        "# Relevance review\n\n"
        + entry("G01", "x", " ")
        + entry("G02", " ", "x")
        + entry("G03", " ", " ")
        + entry("G04", "x", "x")
    )
    assert live.relevance_tally(tmp_path) == {
        "bedrock": {"entries": 4, "relevant": 1, "not_relevant": ["G02"], "unmarked": ["G03", "G04"]}
    }
