"""The live suites' fixed parts: judge sentences and resilience scenarios (no LLM calls)."""

from __future__ import annotations

import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest

from app.evaluation import judge, live
from app.evaluation.golden import golden_dir, golden_series
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


def _batch(tmp_path, pairs) -> dict:
    """A runs.jsonl of golden runs for these (query, order) pairs; returns their analysis ids."""
    ids = {pair: f"{pair[0]}-{pair[1]}" for pair in pairs}
    records = [{"query_id": q, "order": o, "run": 0, "analysis_id": a} for (q, o), a in ids.items()]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return ids


def _sheet(tmp_path, entries) -> None:
    """entries: (query, order, analysis id, relevant box, not-relevant box)."""
    (tmp_path / "relevance_review.md").write_text(
        "# Relevance review\n\n"
        + "".join(
            f"## {q} ({o} primary): q\n\nAnalysis id: {a}\n\n- [{r}] Relevant\n- [{n}] Not relevant. Why:\n\n"
            for q, o, a, r, n in entries
        )
    )


ALL = [(f"G{i:02}", o) for o in live.ORDERS for i in range(1, 13)]


def test_a_complete_review_is_tallied_per_provider(tmp_path):
    ids = _batch(tmp_path, ALL)
    _sheet(tmp_path, [(q, o, ids[q, o], " ", " ") for q, o in ALL])
    assert live.relevance_tally(tmp_path) is None  # nothing marked yet

    _sheet(tmp_path, [(q, o, ids[q, o], *((" ", "x") if q == "G12" else ("x", " "))) for q, o in ALL])
    tally = live.relevance_tally(tmp_path)

    assert tally == {
        o: {"runs": 12, "relevant": 11, "not_relevant": ["G12"], "not_reviewed": []} for o in live.ORDERS
    }
    assert live.relevance_met(tally)


@pytest.mark.parametrize(
    ("entries", "not_reviewed"),
    [
        (lambda ids: [(q, o, ids[q, o], "x", " ") for q, o in ALL if o == "bedrock"], "openai: all 12"),
        (lambda ids: [(q, o, ids[q, o], "x", " ") for q, o in ALL if q not in ("G11", "G12")], "G11, G12"),
        (
            lambda ids: (
                [(q, o, ids[q, o], "x", " ") for q, o in ALL]
                + [("G01", "bedrock", ids["G01", "bedrock"], "x", " ")]
            ),
            "G01 twice",
        ),
        (
            lambda ids: [
                (q, o, "older-batch", "x", " ") if q == "G01" else (q, o, ids[q, o], "x", " ") for q, o in ALL
            ],
            "stale G01",
        ),
        (
            lambda ids: [(q, o, ids[q, o], "x", "x" if q == "G01" else " ") for q, o in ALL],
            "G01 marked both ways",
        ),
    ],
)
def test_an_incomplete_duplicate_or_stale_review_does_not_meet_the_target(tmp_path, entries, not_reviewed):
    ids = _batch(tmp_path, ALL)
    _sheet(tmp_path, entries(ids))
    tally = live.relevance_tally(tmp_path)
    assert tally is not None and not live.relevance_met(tally), not_reviewed


def test_a_new_golden_batch_starts_with_an_unreviewed_sheet(tmp_path, monkeypatch):
    # The committed runs and their marked sheet, then a fresh golden batch replaces the runs.
    results = golden_dir().parent / "results" / "live"
    for name in ("runs.jsonl", "relevance_review.md", "resilience.json", "judge.json"):
        shutil.copyfile(results / name, tmp_path / name)
    assert live.relevance_tally(tmp_path) is not None

    async def nothing(*args, **kwargs):
        return None

    async def environment():
        return SimpleNamespace(faults=SimpleNamespace(switch_off=nothing), close=nothing)

    async def fresh_batch(*args):
        records = [json.loads(line) for line in (tmp_path / "runs.jsonl").read_text().splitlines()]
        for r in records:
            r["analysis_id"] = "new-" + r["analysis_id"]
        (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    monkeypatch.setattr(live, "Environment", SimpleNamespace(open=environment))
    monkeypatch.setattr(live, "golden_series", nothing)
    monkeypatch.setattr(live, "golden_phase", fresh_batch)
    args = SimpleNamespace(
        out=tmp_path,
        rescore=False,
        phases=["golden"],
        orders=list(live.ORDERS),
        runs=3,
        queries=None,
        concurrency=1,
    )
    asyncio.run(live._main(args))

    assert live.relevance_tally(tmp_path) is None
    assert "human_relevance" not in json.loads((tmp_path / "live.json").read_text())["targets"]
