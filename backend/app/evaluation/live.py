"""Live evaluation (plan §8.3): `python -m app.evaluation.live` (or `make eval-live`).

Spends real LLM calls on both providers. Phases, each written to its own file under --out so they
can be run separately, and summarised together into live.json, live.md and a relevance review
sheet for a human:

- golden: the golden queries, `--runs` times with each provider order (runs.jsonl). The first run
  of each order is the golden run; all runs together measure consistency.
- resilience: the provider-failure scenarios (resilience.json).
- judge: the qualitative judge category, with each provider as the judge (judge.json).

`--rescore` scores the stored runs again without new LLM calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select

from app.core.config import Provider, get_settings
from app.db.models import LLMCall
from app.evaluation import judge as judge_suite
from app.evaluation.accuracy import Series
from app.evaluation.golden import golden, golden_dir, golden_series
from app.evaluation.harness import Environment, RunResult, RunSpec, run
from app.evaluation.resilience import Scenario, scenarios
from app.evaluation.scoring import ACCOUNT_REFUSALS, account_outage, load, score

ORDERS: dict[str, tuple[Provider, ...]] = {"bedrock": ("bedrock", "openai"), "openai": ("openai", "bedrock")}
RESILIENCE_QUERY = "G01"
MIN_IDENTITIES = 11
MIN_JACCARD = 0.8
MIN_RELEVANT = 10


def _queries(ids: list[str] | None) -> list[dict[str, Any]]:
    queries = golden()["queries"]
    return [q for q in queries if ids is None or q["id"] in ids]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


async def _score_golden(env: Environment, series: Series, record: dict[str, Any]) -> dict[str, Any]:
    query = next(q for q in golden()["queries"] if q["id"] == record["query_id"])
    stored = await load(env.sessions, record["analysis_id"])
    return {**record, "score": score(stored, query["expect"], series, record["clarification"])}


async def golden_phase(
    env: Environment,
    series: Series,
    orders: list[str],
    runs: int,
    ids: list[str] | None,
    concurrency: int,
    out: Path,
) -> None:
    path = out / "runs.jsonl"
    path.write_text("")
    # Per provider order: the orders run side by side, each kept under its primary's rate limits.
    limits = {o: asyncio.Semaphore(concurrency) for o in orders}

    async def one(order: str, index: int, query: dict[str, Any]) -> None:
        async with limits[order]:
            record = await _golden_run(env, series, query, order, index)
        with path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    # Run index outermost: the golden runs (index 0) of every query finish first.
    for index in range(runs):
        await asyncio.gather(*(one(o, index, q) for o in orders for q in _queries(ids)))


async def _golden_run(
    env: Environment, series: Series, query: dict[str, Any], order: str, index: int
) -> dict[str, Any]:
    """One run of a golden query with one provider order, scored."""
    spec = RunSpec(
        query["query"], ORDERS[order], proceed_on_clarification=not query["expect"].get("clarification")
    )
    result = await run(env, spec)
    record = {
        "query_id": query["id"],
        "order": order,
        "run": index,
        "analysis_id": result.analysis_id,
        "clarification": result.clarification,
    }
    try:
        scored = await _score_golden(env, series, record)
    except Exception as exc:  # a scorer bug must not lose the run: fix it, then --rescore
        scored = {**record, "scoring_error": f"{type(exc).__name__}: {exc}"}
    label = f"{query['id']} {order} #{index}"
    if "score" not in scored:
        print(f"{label}: not scored ({scored['scoring_error']})", flush=True)
    else:
        s = scored["score"]
        print(
            f"{label}: {s['status']} refusal={'ok' if s['refusal_correct'] else 'FAIL'} "
            f"retained={len(s['retained_failures'])} findings={len(s['findings'])}",
            flush=True,
        )
    return scored


def _resilience_query() -> str:
    return next(q for q in golden()["queries"] if q["id"] == RESILIENCE_QUERY)["query"]


async def resilience_phase(env: Environment, out: Path) -> None:
    _write_json(
        out / "resilience.json", [await _run_scenario(env, s) for s in scenarios(_resilience_query())]
    )


async def _run_scenario(env: Environment, scenario: Scenario) -> dict[str, Any]:
    """One resilience scenario, checked. Scenarios run one at a time: fault switches are shared."""
    record: dict[str, Any] = {"name": scenario.name, "expected": scenario.expected}
    if scenario.spec is None:
        return {**record, "passed": None, "not_applicable": scenario.not_applicable}
    await env.faults.switch_off()
    result = await run(env, scenario.spec)
    record |= {
        "analysis_id": result.analysis_id,
        "order": list(scenario.spec.order),
        "faults": list(scenario.spec.faults),
        "late_faults": list(scenario.spec.late_faults),
        "late_faults_after_seq": result.late_faults_after_seq,
    }
    checked = await _check_scenario(env, record)
    print(
        f"{scenario.name}: {'pass' if checked['passed'] else 'FAIL ' + str(checked['problems'])}", flush=True
    )
    return checked


async def _check_scenario(env: Environment, record: dict[str, Any]) -> dict[str, Any]:
    scenario = next(s for s in scenarios("") if s.name == record["name"])
    assert scenario.check is not None
    stored = await load(env.sessions, record["analysis_id"])
    problems = scenario.check(
        stored, RunResult(record["analysis_id"], late_faults_after_seq=record["late_faults_after_seq"])
    )
    calls = [
        {"provider": c.provider, "purpose": c.purpose, "ok": c.ok, "error": (c.error or "")[:120]}
        for c in stored.calls
    ]
    return {
        **record,
        "status": stored.analysis.status,
        "error": stored.analysis.error,
        "findings": len((stored.report or {}).get("findings", [])),
        "fallback_events": [e.title for e in stored.events if e.type == "provider_fallback"],
        "answered_by": sorted({c["provider"] for c in calls if c["ok"]}),
        "failed_calls": sum(not c["ok"] for c in calls),
        "problems": problems,
        "passed": not problems,
        "account_outage": account_outage(stored),
    }


async def judge_phase(series: Series, out: Path) -> None:
    if misses := judge_suite.deterministic_misses():
        raise SystemExit(f"these sentences belong to the deterministic suite: {misses}")
    shown = judge_suite.findings(series)
    results = [await judge_suite.judge(get_settings(), p, shown) for p in ("bedrock", "openai")]
    for r in results:
        print(
            f"judge {r['judge']}: recall {r['recall']:.0%}, false positives {r['false_positive_rate']:.0%}",
            flush=True,
        )
    _write_json(out / "judge.json", {"findings_shown": shown, "results": results})


REDO_REASON = "a provider account had no credits (recorded as such in the call ledger)"
JUDGE_REDO_REASON = "the judge's provider gave no verdict"


async def _account_refused(env: Environment, analysis_ids: list[str]) -> set[str]:
    async with env.sessions() as session:
        rows = await session.scalars(
            select(LLMCall.analysis_id)
            .where(
                LLMCall.analysis_id.in_(analysis_ids),
                or_(*(LLMCall.error.contains(marker) for marker in ACCOUNT_REFUSALS)),
            )
            .distinct()
        )
    return set(rows)


async def redo_phase(env: Environment, series: Series, out: Path, concurrency: int) -> bool:
    """Run again what a provider account outage spoiled, chosen from the call ledger and never from
    the outcome. Each replacement records what it replaces and why. Returns whether a golden run
    (the reviewed one) was replaced."""
    path = out / "runs.jsonl"
    records = _read_jsonl(path)
    golden_before = [r for r in records if r["run"] == 0]
    spoiled = await _account_refused(env, [r["analysis_id"] for r in records])
    limits = {o: asyncio.Semaphore(concurrency) for o in ORDERS}

    async def again(i: int, old: dict[str, Any]) -> None:
        query = next(q for q in golden()["queries"] if q["id"] == old["query_id"])
        async with limits[old["order"]]:
            new = await _golden_run(env, series, query, old["order"], old["run"])
        records[i] = {**new, "replaces": {"analysis_id": old["analysis_id"], "reason": REDO_REASON}}
        path.write_text("".join(json.dumps(r, default=str) + "\n" for r in records))

    await asyncio.gather(*(again(i, r) for i, r in enumerate(records) if r["analysis_id"] in spoiled))

    resilience_path = out / "resilience.json"
    if resilience_path.exists():
        checked = json.loads(resilience_path.read_text())
        hit = await _account_refused(env, [r["analysis_id"] for r in checked if "analysis_id" in r])
        for i, old in enumerate(checked):
            if old.get("analysis_id") in hit:
                scenario = next(s for s in scenarios(_resilience_query()) if s.name == old["name"])
                replaces = {"analysis_id": old["analysis_id"], "reason": REDO_REASON}
                checked[i] = {**await _run_scenario(env, scenario), "replaces": replaces}
        _write_json(resilience_path, checked)

    judge_path = out / "judge.json"
    if judge_path.exists():
        judged = json.loads(judge_path.read_text())
        for i, old in enumerate(judged["results"]):
            if old["unjudged"]:
                new = await judge_suite.judge(get_settings(), old["judge"], judged["findings_shown"])
                judged["results"][i] = {
                    **new,
                    "replaces": {"unjudged": old["unjudged"], "reason": JUDGE_REDO_REASON},
                }
        _write_json(judge_path, judged)
    return any(r["analysis_id"] in spoiled for r in golden_before)


async def rescore(env: Environment, series: Series, out: Path) -> None:
    runs = [
        await _score_golden(env, series, {k: v for k, v in r.items() if k not in ("score", "scoring_error")})
        for r in _read_jsonl(out / "runs.jsonl")
    ]
    (out / "runs.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in runs))
    path = out / "resilience.json"
    if path.exists():
        records = json.loads(path.read_text())
        _write_json(path, [r if r.get("passed") is None else await _check_scenario(env, r) for r in records])


# -- summary ------------------------------------------------------------------------------------


def _found(score: dict[str, Any]) -> int:
    return len(set(score["expected_computations"]) & set(score["golden_computations_found"]))


def _jaccard(a: set[str], b: set[str]) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def _cost(runs: list[dict[str, Any]]) -> dict[str, Any]:
    tokens: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in runs:
        for model, (inp, outp) in r["score"]["usage"]["by_model"].items():
            tokens[model][0] += inp
            tokens[model][1] += outp
    prices = get_settings().llm_prices
    unmetered = sum(r["score"]["usage"]["calls_without_usage"] for r in runs)
    # As in the app: an unpriced model or a call with unknown usage makes the total unknown, not smaller.
    priced = all(m in prices for m in tokens) and not unmetered
    total = (
        sum(inp / 1e6 * prices[m][0] + outp / 1e6 * prices[m][1] for m, (inp, outp) in tokens.items())
        if priced
        else None
    )
    return {
        "tokens_by_model": dict(tokens),
        "usd": round(total, 4) if total is not None else None,
        "priced": priced,
        "calls_without_usage": unmetered,
    }


def summarise(out: Path) -> dict[str, Any]:
    recorded = _read_jsonl(out / "runs.jsonl")
    scored = [r for r in recorded if "score" in r]
    # A run a provider account outage spoiled shows the account, not the product: it is listed as
    # not evaluated and left out of the completion, refusal-over-all-runs and consistency measures.
    # What it stored is still checked (retained claims, computations): anything kept must be right.
    spoiled = [r for r in scored if r["score"].get("account_outage")]
    runs = [r for r in scored if not r["score"].get("account_outage")]
    resilience = (
        json.loads((out / "resilience.json").read_text()) if (out / "resilience.json").exists() else None
    )
    judged = json.loads((out / "judge.json").read_text()) if (out / "judge.json").exists() else None
    total_queries = len(golden()["queries"])
    gates: dict[str, bool] = {}
    targets: dict[str, bool] = {}
    summary: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds")}

    if runs:
        orders = sorted({r["order"] for r in runs})
        golden_runs = {o: [r for r in runs if r["order"] == o and r["run"] == 0] for o in orders}
        per_order = {}
        for order, items in golden_runs.items():
            s = [r["score"] for r in items]
            active = [x["usage"]["active_ms"] for x in s]
            answered = Counter[str]()
            for x in s:
                answered.update(x["usage"]["answered_by"])
            per_order[order] = {
                "queries": len(items),
                "refusal_correct": sum(x["refusal_correct"] for x in s),
                "refusal_problems": {
                    r["query_id"]: r["score"]["refusal_problems"]
                    for r in items
                    if r["score"]["refusal_problems"]
                },
                "identities_correct": sum(x["identities_correct"] for x in s),
                "identity_misses": {
                    r["query_id"]: r["score"]["selected"]
                    for r in items
                    if not r["score"]["identities_correct"]
                },
                "golden_computations": f"{sum(_found(x) for x in s)}"
                f"/{sum(len(x['expected_computations']) for x in s)}",
                "unexpected_clarifications": [
                    r["query_id"] for r in items if r["score"]["unexpected_clarification"]
                ],
                "active_s_p50": (_percentile(active, 0.5) or 0) / 1000,
                "active_s_p95": (_percentile(active, 0.95) or 0) / 1000,
                "calls_per_run": statistics.mean(x["usage"]["calls"] for x in s) if s else 0,
                # Share of answered calls made by this order's primary (the rest are fallbacks or the
                # independent narrative check).
                "answered_by_primary": answered[order] / max(1, sum(answered.values())),
                "statuses": dict(Counter(x["status"] for x in s)),
            }
        retained = [
            {"query": r["query_id"], "order": r["order"], "run": r["run"], "failure": f}
            for r in scored
            for f in r["score"]["retained_failures"]
        ]
        mismatches = [
            {"query": r["query_id"], "order": r["order"], "run": r["run"], "field": f}
            for r in scored
            for f in r["score"]["computation_mismatches"]
        ]
        refusal_all = {
            o: f"{sum(r['score']['refusal_correct'] for r in runs if r['order'] == o)}"
            f"/{sum(r['order'] == o for r in runs)}"
            for o in orders
        }
        evidence_driven = [
            {"query": r["query_id"], "order": r["order"], **d}
            for items in golden_runs.values()
            for r in items
            for d in r["score"]["autonomy"]["evidence_driven"]
        ]
        consistency: dict[str, dict[str, Any]] = {}
        for q in golden()["queries"]:
            items = [r for r in runs if r["query_id"] == q["id"]]
            if len(items) < 2:
                continue
            sets = [set(r["score"]["selected"]) for r in items]
            stated: dict[str, set[str]] = defaultdict(set)
            for r in items:
                for key, direction in r["score"]["directions"].items():
                    stated[key].add(direction)
            consistency[q["id"]] = {
                "runs": len(items),
                "jaccard": statistics.mean(_jaccard(a, b) for a, b in combinations(sets, 2)),
                "direction_conflicts": {k: sorted(v) for k, v in stated.items() if len(v) > 1},
            }
        complete = all(per_order[o]["queries"] == total_queries for o in orders) and set(orders) == set(
            ORDERS
        )
        gates["refusal_correctness"] = complete and all(
            p["refusal_correct"] == total_queries for p in per_order.values()
        )
        gates["retained_claim_correctness"] = not retained
        gates["live_computation_accuracy"] = not mismatches
        gates["three_agents_decide"] = all(r["score"]["all_agents_decided"] for r in scored)
        gates["evidence_driven_decisions"] = bool(evidence_driven)
        targets["series_identities"] = complete and all(
            p["identities_correct"] >= MIN_IDENTITIES for p in per_order.values()
        )
        targets["clarification_only_when_ambiguous"] = not any(
            p["unexpected_clarifications"] for p in per_order.values()
        )
        if consistency:
            mean_jaccard = statistics.mean(c["jaccard"] for c in consistency.values())
            targets["consistency_jaccard"] = mean_jaccard >= MIN_JACCARD
            targets["direction_agreement"] = not any(c["direction_conflicts"] for c in consistency.values())
            summary["consistency"] = {"mean_jaccard": mean_jaccard, "per_query": consistency}
        summary |= {
            "runs": len(scored),
            "evaluated_runs": len(runs),
            "per_order": per_order,
            "retained_failures": retained,
            "computation_mismatches": mismatches,
            "refusal_correct_all_runs": refusal_all,
            "republished_computations": [
                {
                    "query": r["query_id"],
                    "order": r["order"],
                    "run": r["run"],
                    "computation": cid,
                    "fields": f,
                }
                for r in runs
                for cid, f in r["score"].get("republished_computations", {}).items()
            ],
            "evidence_driven_decisions": evidence_driven,
            "cost": _cost(runs),
        }
    summary["replaced"] = {
        "runs": [
            {"query": r["query_id"], "order": r["order"], "run": r["run"], **r["replaces"]}
            for r in recorded
            if "replaces" in r
        ],
        "scenarios": [r["name"] for r in (resilience or []) if "replaces" in r],
        "judges": [r["judge"] for r in (judged or {}).get("results", []) if "replaces" in r],
    }
    if recorded:
        # Over every recorded run: one that could not be scored has not been shown to complete.
        summary["unscored"] = [r["analysis_id"] for r in recorded if "score" not in r]
        gates["runs_completed"] = not summary["unscored"] and all(r["score"]["completed"] for r in runs)
    not_evaluated: dict[str, list[Any]] = {
        "runs": [{"query": r["query_id"], "order": r["order"], "run": r["run"]} for r in spoiled],
        "scenarios": [],
        "judges": [],
    }
    if resilience is not None:
        applicable = [r for r in resilience if r["passed"] is not None and not r.get("account_outage")]
        not_evaluated["scenarios"] = [r["name"] for r in resilience if r.get("account_outage")]
        gates["provider_resilience"] = all(r["passed"] for r in applicable)
        summary["resilience"] = resilience
    if judged is not None:
        total = sum(len(group) for group in judge_suite.SENTENCES.values())
        asked = [r for r in judged["results"] if r["unjudged"] < total]
        not_evaluated["judges"] = [r["judge"] for r in judged["results"] if r["unjudged"] == total]
        # A sentence the judge could not be asked about (provider unavailable) is not a pass.
        targets["qualitative_recall"] = bool(asked) and all(
            r["recall"] >= judge_suite.TARGET_RECALL and not r["unjudged"] for r in asked
        )
        summary["judge"] = [{k: v for k, v in r.items() if k != "verdicts"} for r in judged["results"]]
    summary["not_evaluated"] = not_evaluated
    summary["complete"] = not any(not_evaluated.values())
    if (relevance := relevance_tally(out)) is not None:
        targets["human_relevance"] = relevance_met(relevance)
        summary["relevance"] = relevance
    summary["gates"], summary["targets"] = gates, targets
    summary["hard_gates_passed"] = bool(gates) and all(gates.values())
    return summary


def _mark(ok: bool | None) -> str:
    return "n/a" if ok is None else ("pass" if ok else "**FAIL**")


def markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Live evaluation",
        "",
        f"Generated {summary['generated_at']} from snapshot data with real providers.",
        "",
    ]
    if not summary.get("complete", True):
        missing = summary["not_evaluated"]
        runs = ", ".join(f"{r['query']} {r['order']} #{r['run']}" for r in missing["runs"]) or "none"
        lines += [
            f"**Incomplete: not evaluated because {REDO_REASON}.** The gates below cover only what was "
            "evaluated; this is not a full pass.",
            "",
            f"- Runs ({len(missing['runs'])}): {runs}",
            f"- Resilience scenarios: {', '.join(missing['scenarios']) or 'none'}",
            f"- Judges: {', '.join(missing['judges']) or 'none'}",
            "",
        ]
    lines += [
        "| Hard gate | Result |",
        "|---|---|",
        *[f"| {k.replace('_', ' ')} | {_mark(v)} |" for k, v in summary["gates"].items()],
        "",
    ]
    lines += [
        "| Target | Result |",
        "|---|---|",
        *[f"| {k.replace('_', ' ')} | {_mark(v)} |" for k, v in summary["targets"].items()],
        "",
    ]
    if per_order := summary.get("per_order"):
        lines += [
            "## Golden runs",
            "",
            "| Primary provider | Refusal correctness | Series identities | Golden computations "
            "| Unexpected clarifications | Active time p50 / p95 (s) | Calls per run | Answered by primary |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for order, p in per_order.items():
            lines.append(
                f"| {order} | {p['refusal_correct']}/{p['queries']} "
                f"| {p['identities_correct']}/{p['queries']} "
                f"| {p['golden_computations']} | {', '.join(p['unexpected_clarifications']) or 'none'} "
                f"| {p['active_s_p50']:.0f} / {p['active_s_p95']:.0f} | {p['calls_per_run']:.1f} "
                f"| {p['answered_by_primary']:.0%} |"
            )
        for order, p in per_order.items():
            for qid, problems in p["refusal_problems"].items():
                lines.append(f"- {order} {qid}: {'; '.join(problems)}")
            for qid, selected in p["identity_misses"].items():
                lines.append(f"- {order} {qid}: selected {selected or 'nothing'}")
        lines += [
            "",
            f"**Retained-claim failures:** {len(summary['retained_failures'])} "
            f"across {summary['runs']} runs.",
            "",
        ]
        lines += [
            f"- {f['query']} {f['order']} #{f['run']}: {f['failure']}" for f in summary["retained_failures"]
        ]
        lines += [f"**Live computation mismatches:** {len(summary['computation_mismatches'])}.", ""]
        refusal_all = ", ".join(f"{o} {v}" for o, v in summary["refusal_correct_all_runs"].items())
        lines += [f"**Refusal correctness over all runs:** {refusal_all}.", ""]
        differing = [
            f"{c['query']} {c['order']} #{c['run']} {c['computation']}.{name}: {want:g} vs {got:g}"
            for c in summary["republished_computations"]
            for name, (want, got) in c["fields"].items()
            if got is None or abs(got - want) > 1e-9 * max(1.0, abs(want))
        ]
        lines += [
            f"**Golden computations made on a republication:** {len(summary['republished_computations'])}, "
            f"compared in base units: {'; '.join(differing) or 'all equal'}.",
            "",
        ]
        if summary["unscored"]:
            lines += [f"**Not scored:** {', '.join(summary['unscored'])}.", ""]
        lines += ["**Evidence-driven decisions (golden runs, no faults):**", ""]
        lines += [
            f"- {d['query']} {d['order']}: {d['agent']} {d['decision']}: {d['detail'][:160]}"
            for d in summary["evidence_driven_decisions"][:12]
        ]
        cost = summary["cost"]
        tokens = ", ".join(f"{m}: {i:,} in / {o:,} out" for m, (i, o) in cost["tokens_by_model"].items())
        lines += [
            "",
            f"**Tokens:** {tokens}. **Cost:** "
            + (
                f"${cost['usd']:.2f}"
                if cost["priced"]
                else f"unknown ({cost['calls_without_usage']} call(s) without usage, or LLM_PRICES not set)"
            )
            + ".",
        ]
    if consistency := summary.get("consistency"):
        lines += [
            "",
            "## Consistency",
            "",
            f"Mean pairwise Jaccard of selected series: {consistency['mean_jaccard']:.2f}.",
            "",
        ]
        lines += ["| Query | Runs | Jaccard | Direction conflicts |", "|---|---|---|---|"]
        lines += [
            f"| {q} | {c['runs']} | {c['jaccard']:.2f} | {', '.join(c['direction_conflicts']) or 'none'} |"
            for q, c in consistency["per_query"].items()
        ]
    if resilience := summary.get("resilience"):
        lines += ["", "## Provider resilience", "", "| Scenario | Expected | Result |", "|---|---|---|"]
        for r in resilience:
            if r.get("not_applicable"):
                result = f"n/a: {r['not_applicable']}"
            elif r.get("account_outage"):
                result = "not evaluated: a provider account had no credits"
            elif r["passed"]:
                result = f"pass ({r['status']}, answered by {', '.join(r['answered_by']) or 'none'})"
            else:
                result = f"**FAIL**: {'; '.join(r['problems'])}"
            lines.append(f"| {r['name'].replace('_', ' ')} | {r['expected']} | {result} |")
    replaced = summary.get("replaced", {})
    if any(replaced.values()):
        lines += [
            "",
            f"**Re-run because {REDO_REASON}:** {len(replaced['runs'])} run(s), "
            f"scenarios: {', '.join(replaced['scenarios']) or 'none'}, "
            f"judges: {', '.join(replaced['judges']) or 'none'}. "
            "Chosen from the call ledger, not from the outcome; each replacement records what it replaced.",
        ]
    if relevance := summary.get("relevance"):
        lines += [
            "",
            "## Human relevance review",
            "",
            "| Primary provider | Relevant | Not relevant | Not reviewed |",
        ]
        lines += ["|---|---|---|---|"]
        lines += [
            f"| {o} | {t['relevant']}/{t['runs']} | {', '.join(t['not_relevant']) or 'none'} "
            f"| {', '.join(t['not_reviewed']) or 'none'} |"
            for o, t in relevance.items()
        ]
    if judges := summary.get("judge"):
        lines += [
            "",
            "## Qualitative judge",
            "",
            "| Judge | Judged | Recall | False positives | Missed |",
            "|---|---|---|---|---|",
        ]
        total = sum(len(group) for group in judge_suite.SENTENCES.values())
        for j in judges:
            missed = [s for c in j["categories"].values() for s in c["missed"]]
            if j["unjudged"] == total:
                lines.append(
                    f"| {j['judge']} | 0/{total} | not evaluated: the provider gave no verdicts | | |"
                )
                continue
            lines.append(
                f"| {j['judge']} | {total - j['unjudged']}/{total} | {j['recall']:.0%} "
                f"| {j['false_positive_rate']:.0%} "
                f"| {'; '.join(missed) or 'none'} |"
            )
    return "\n".join(lines) + "\n"


_ENTRY = re.compile(r"(?m)^(?=## G\d\d \()")
_HEADING = re.compile(r"## (G\d\d) \((\w+) primary\)")
_ANALYSIS = re.compile(r"(?m)^Analysis id: (\S+)$")


def relevance_tally(out: Path) -> dict[str, dict[str, Any]] | None:
    """The reviewer's marks per primary provider, or None before review.

    A mark counts only for the golden run it was made on: each entry names its analysis, and each
    golden run in runs.jsonl must be reviewed exactly once. A run whose entry is missing, repeated,
    from another batch or not marked once is listed as not reviewed."""
    path = out / "relevance_review.md"
    if not path.exists():
        return None
    golden_runs = {
        (r["query_id"], r["order"]): r["analysis_id"]
        for r in _read_jsonl(out / "runs.jsonl")
        if r["run"] == 0
    }
    marks: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in _ENTRY.split(path.read_text())[1:]:
        heading, analysis = _HEADING.match(entry), _ANALYSIS.search(entry)
        if heading is None or analysis is None:
            continue
        key = (heading.group(1), heading.group(2))
        if golden_runs.get(key) != analysis.group(1):
            continue  # not about a golden run of this batch
        relevant = bool(re.search(r"(?m)^- \[[xX]\] Relevant", entry))
        not_relevant = bool(re.search(r"(?m)^- \[[xX]\] Not relevant", entry))
        marks[key].append("unmarked" if relevant == not_relevant else "relevant" if relevant else "not")
    if not any(m != "unmarked" for found in marks.values() for m in found):
        return None
    tally: dict[str, dict[str, Any]] = {}
    for query_id, order in sorted(golden_runs):
        t = tally.setdefault(order, {"runs": 0, "relevant": 0, "not_relevant": [], "not_reviewed": []})
        t["runs"] += 1
        found = marks.get((query_id, order), [])
        if len(found) != 1 or found[0] == "unmarked":
            t["not_reviewed"].append(query_id)
        elif found[0] == "relevant":
            t["relevant"] += 1
        else:
            t["not_relevant"].append(query_id)
    return tally


def relevance_met(tally: dict[str, dict[str, Any]]) -> bool:
    """Every golden query reviewed once for both provider orders, at least MIN_RELEVANT relevant."""
    total = len(golden()["queries"])
    return set(tally) == set(ORDERS) and all(
        t["runs"] == total and not t["not_reviewed"] and t["relevant"] >= MIN_RELEVANT for t in tally.values()
    )


def relevance_sheet(out: Path) -> str:
    """One entry per golden run for a human to mark relevant or not (target >= 10/12 per provider)."""
    lines = [
        "# Relevance review",
        "",
        "For each golden run, mark whether the report answers the question a policy researcher asked:",
        "the right sector, measures and period, findings that address the question, and limitations",
        "that explain any gap.",
        f"Target: at least {MIN_RELEVANT} of 12 relevant for each primary provider.",
        "",
    ]
    for r in sorted(_read_jsonl(out / "runs.jsonl"), key=lambda r: (r["order"], r["query_id"])):
        if r["run"] != 0:
            continue
        s = r["score"]
        query = next(q for q in golden()["queries"] if q["id"] == r["query_id"])
        lines += [
            f"## {r['query_id']} ({r['order']} primary): {query['query']}",
            "",
            f"Covers: {query['covers']}. Status: {s['status']}.",
            f"Analysis id: {r['analysis_id']}",
        ]
        if s["plan"]:
            p = s["plan"]
            lines.append(
                f"Plan: {p['intent']} (sectors {p['sectors']}, metrics {p['metrics']}, "
                f"{p['start_year']}-{p['end_year']})."
            )
        if s["clarification"]:
            lines.append(
                f"Asked: {s['clarification'].get('question')} Options: {s['clarification'].get('options')}"
            )
        if s["summary"]:
            lines.append(f"Summary: {s['summary']}")
        lines += ["", "Findings:", *([f"- {t}" for t in s["findings"]] or ["- none"]), ""]
        lines += ["Limitations:", *([f"- {t}" for t in s.get("limitations", [])] or ["- none"]), ""]
        lines += ["- [ ] Relevant", "- [ ] Not relevant. Why:", ""]
    return "\n".join(lines)


async def _main(args: argparse.Namespace) -> int:
    out: Path = args.out
    new_golden_runs = "golden" in args.phases and not (args.rescore or args.redo)
    series = await golden_series()
    env = await Environment.open()
    try:
        await env.faults.switch_off()
        if args.rescore:
            await rescore(env, series, out)
        elif args.redo:
            new_golden_runs = await redo_phase(env, series, out, args.concurrency)
        else:
            if "golden" in args.phases:
                await golden_phase(env, series, args.orders, args.runs, args.queries, args.concurrency, out)
            if "resilience" in args.phases:
                await resilience_phase(env, out)
            if "judge" in args.phases:
                await judge_phase(series, out)
    finally:
        await env.close()
    if new_golden_runs:
        # New golden runs get a new, unmarked sheet before they are summarised; a re-score, or a
        # redo that leaves the golden runs alone, keeps the reviewer's marks.
        (out / "relevance_review.md").write_text(relevance_sheet(out))
    summary = summarise(out)
    _write_json(out / "live.json", summary)
    (out / "live.md").write_text(markdown(summary))
    print(markdown(summary))
    return 0 if summary["hard_gates_passed"] and summary["complete"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--phases", type=lambda s: s.split(","), default=["golden", "resilience", "judge"])
    parser.add_argument("--orders", type=lambda s: s.split(","), default=list(ORDERS))
    parser.add_argument("--runs", type=int, default=3, help="runs per query and provider order")
    parser.add_argument("--queries", type=lambda s: s.split(","), default=None, help="e.g. G01,G05")
    parser.add_argument("--concurrency", type=int, default=1, help="concurrent runs per provider order")
    parser.add_argument("--out", type=Path, default=golden_dir().parent / "results" / "live")
    parser.add_argument("--rescore", action="store_true", help="score the stored runs again, no LLM calls")
    parser.add_argument(
        "--redo", action="store_true", help="run again only what a provider account outage spoiled"
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
