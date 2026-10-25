"""Day-1 LLM capability probe (plan §4.7, gate G1).

Checks, per candidate model: basic invoke, tool call, structured output,
one full ReAct turn (reason -> tool call -> observation -> answer), streaming.
SDK-level retries are disabled so each router attempt maps to one HTTP request.

Usage (from backend/; credentials and default model IDs come from app Settings / .env):
    uv run python ../scripts/probe_llm.py [--bedrock ID ...] [--openai ID ...]

Writes eval/results/probe/probe-<utc timestamp>.json (never secrets). Exits non-zero if any
probed model fails a check.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "eval" / "results" / "probe"

sys.path.insert(0, str(REPO_ROOT / "backend"))
from app.core.config import get_settings  # noqa: E402
from app.llm.providers import build_bedrock, build_openai  # noqa: E402


@tool
def fetch_singstat_series(table_id: str, series_no: str) -> str:
    """Fetch one series from a SingStat Table Builder table by table ID and series number."""
    return "not executed in probe"


class ResearchPlan(BaseModel):
    """Structured interpretation of a policy research question."""

    intent: str = Field(description="One-sentence research intent")
    sector: str = Field(description="Industry sector in scope")
    start_year: int
    end_year: int
    metrics: list[str] = Field(description="Metrics to analyse, e.g. employment level, job vacancies")
    needs_clarification: bool
    rationale: str = Field(description="Public, two-sentence summary of why this plan was chosen")


QUERY = "Analyse employment trends in the technology sector from 2020-2024"

# Deliberately carries no numbers: the probe checks that the model can consume an
# observation and continue, not the accuracy of any statistic.
OBSERVATION = json.dumps(
    {
        "table_id": "M182841",
        "series": "Information And Communications",
        "unit": "Thousand",
        "computation_id": "c1",
        "note": "Numbers must be referenced via placeholders such as {{c1.pct_change}}; do not type numbers.",
    }
)


def timed(fn: Callable[[], Any]) -> tuple[bool, float, Any]:
    t0 = time.perf_counter()
    try:
        out = fn()
        return True, round((time.perf_counter() - t0) * 1000), out
    except Exception as exc:  # recorded, not raised: the probe reports every capability
        return False, round((time.perf_counter() - t0) * 1000), f"{type(exc).__name__}: {str(exc)[:400]}"


def usage_of(msg: Any) -> dict | None:
    return getattr(msg, "usage_metadata", None)


def probe_model(provider: str, model_id: str, llm: BaseChatModel) -> dict:
    result: dict[str, Any] = {"provider": provider, "model": model_id, "checks": {}}
    checks = result["checks"]

    ok, ms, out = timed(lambda: llm.invoke([HumanMessage("Reply with the single word: ready")]))
    checks["basic_invoke"] = {
        "pass": ok and "ready" in str(getattr(out, "content", "")).lower(),
        "ms": ms,
        "detail": None if ok else out,
        "usage": usage_of(out) if ok else None,
    }

    with_tools = llm.bind_tools([fetch_singstat_series])
    system = SystemMessage(
        "You are the Extraction agent for Singapore labour-market data. Use tools to fetch data. "
        "SingStat table M182841 holds year-end employment by sector; "
        "Information And Communications is series 3.4."
    )
    human = HumanMessage(f"Fetch the data needed for: {QUERY}")
    ok, ms, out = timed(lambda: with_tools.invoke([system, human]))
    calls = getattr(out, "tool_calls", []) if ok else []
    checks["tool_call"] = {
        "pass": ok and any(c["name"] == "fetch_singstat_series" for c in calls),
        "ms": ms,
        "detail": calls if ok else out,
    }

    ok, ms, out = timed(
        lambda: llm.with_structured_output(ResearchPlan).invoke(
            [
                SystemMessage(
                    "Interpret the research question into a plan. Map 'technology sector' to SSIC 2020 "
                    "Section J Information & Communications and state that as an assumption."
                ),
                HumanMessage(QUERY),
            ]
        )
    )
    is_plan = ok and isinstance(out, ResearchPlan)
    checks["structured_output"] = {
        "pass": is_plan and out.start_year == 2020 and out.end_year == 2024,
        "ms": ms,
        "detail": out.model_dump() if is_plan else str(out),
    }

    def react_turn() -> dict:
        first = with_tools.invoke([system, human])
        if not first.tool_calls:
            raise RuntimeError("no tool call in first step")
        call = first.tool_calls[0]
        final = with_tools.invoke([system, human, first, ToolMessage(OBSERVATION, tool_call_id=call["id"])])
        return {
            "action": call,
            "final_has_tool_calls": bool(final.tool_calls),
            "final_text": str(final.content)[:500],
        }

    ok, ms, out = timed(react_turn)
    checks["react_turn"] = {"pass": ok, "ms": ms, "detail": out}

    def stream() -> dict:
        t0 = time.perf_counter()
        first_ms, chunks, text = None, 0, ""
        for chunk in llm.stream([HumanMessage("Count from 1 to 5, one number per line.")]):
            if first_ms is None:
                first_ms = round((time.perf_counter() - t0) * 1000)
            chunks += 1
            text += str(chunk.content) if isinstance(chunk.content, str) else json.dumps(chunk.content)
        return {"chunks": chunks, "first_chunk_ms": first_ms, "text": text[:200]}

    ok, ms, out = timed(stream)
    checks["streaming"] = {"pass": ok and out["chunks"] > 1, "ms": ms, "detail": out}

    result["all_pass"] = all(c["pass"] for c in checks.values())
    return result


def main() -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--bedrock", nargs="*", default=[settings.bedrock_model_id], help="Bedrock model IDs")
    ap.add_argument("--openai", nargs="*", default=[settings.openai_model], help="OpenAI model IDs")
    args = ap.parse_args()

    results = []
    for provider, model_ids, build in (
        ("bedrock", args.bedrock, build_bedrock),
        ("openai", args.openai, build_openai),
    ):
        for model_id in model_ids:
            print(f"probing {provider}:{model_id} ...", flush=True)
            results.append(probe_model(provider, model_id, build(settings, model_id)))

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"probe-{stamp}.json"
    out_path.write_text(
        json.dumps(
            {"generated_at": stamp, "bedrock_region": settings.aws_bedrock_region, "results": results},
            indent=2,
            default=str,
        )
    )

    for r in results:
        summary = " ".join(
            f"{k}={'PASS' if v['pass'] else 'FAIL'}({v['ms']}ms)" for k, v in r["checks"].items()
        )
        print(f"{r['provider']}:{r['model']} all_pass={r['all_pass']} | {summary}")
    print(f"wrote {out_path.relative_to(REPO_ROOT)}")
    return 0 if all(r["all_pass"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
