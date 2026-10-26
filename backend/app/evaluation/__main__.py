"""Deterministic evaluation gates: `python -m app.evaluation [--out DIR]` (or `make eval`).

Runs the computation-accuracy, refusal-correctness and adversarial-verifier gates offline (snapshot
data, no LLM) and writes deterministic.json and deterministic.md. Exits non-zero if a hard gate fails.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation.accuracy import check_computations, check_refusals
from app.evaluation.adversarial import MAX_FALSE_POSITIVE_RATE, build_cases, evaluate, summarise
from app.evaluation.golden import expected, golden_dir, golden_series


def expectations_are_current() -> bool:
    """expected.json matches what the independent script computes from today's snapshots."""
    spec = importlib.util.spec_from_file_location(
        "compute_expected", golden_dir().parent / "compute_expected.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    current = json.dumps(script.expected(), indent=2, sort_keys=True) + "\n"
    return (golden_dir() / "expected.json").read_text() == current


async def run() -> dict[str, Any]:
    series = await golden_series()
    fields = check_computations(series)
    refusals = check_refusals(series)
    cases, computations = build_cases(series)
    adversarial = summarise(evaluate(cases, computations))
    gates = {
        "expectations_current": expectations_are_current(),
        "computation_accuracy": all(f.ok for f in fields),
        "refusal_correctness": all(r.ok for r in refusals),
        "adversarial_recall": all(c["recall"] == 1.0 for c in adversarial["categories"].values()),
        "adversarial_false_positives": adversarial["false_positive_rate"] <= MAX_FALSE_POSITIVE_RATE,
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "snapshots_captured_at": expected()["snapshots_captured_at"],
        "gates": gates,
        "passed": all(gates.values()),
        "computation_accuracy": [asdict(f) for f in fields],
        "refusal_correctness": [asdict(r) for r in refusals],
        "adversarial": adversarial,
    }


def markdown(result: dict[str, Any]) -> str:
    fields, refusals, adv = (
        result["computation_accuracy"],
        result["refusal_correctness"],
        result["adversarial"],
    )
    lines = [
        "# Deterministic evaluation",
        "",
        f"Generated {result['generated_at']} from snapshots captured {result['snapshots_captured_at']}.",
        "",
        "| Gate | Result |",
        "|---|---|",
        *[
            f"| {name.replace('_', ' ')} | {'pass' if ok else '**FAIL**'} |"
            for name, ok in result["gates"].items()
        ],
        "",
        f"**Computation accuracy:** {sum(f['ok'] for f in fields)}/{len(fields)} result fields within "
        f"tolerance and in the expected unit and scale, across {len({f['computation'] for f in fields})} "
        "golden computations.",
        "",
        f"**Refusal correctness:** {sum(r['ok'] for r in refusals)}/{len(refusals)} "
        f"({', '.join(f'{r["refusal"]} {r["actual"]}' for r in refusals)}).",
        "",
        f"**Adversarial verifier suite:** {adv['corrupted']} corrupted claims, recall {adv['recall']:.0%}, "
        f"precision {adv['precision']:.0%}; {adv['controls']} valid controls, false-positive rate "
        f"{adv['false_positive_rate']:.0%}.",
        "",
        "A case counts as detected only when the rule it breaks rejected it.",
        "",
        "| Category | Rule that must reject it | Detected | Checks that fired |",
        "|---|---|---|---|",
        *[
            f"| {name.replace('_', ' ')} | {c['expected_check']} | {c['detected']}/{c['cases']} "
            f"| {', '.join(c['checks_fired'])} |"
            for name, c in adv["categories"].items()
        ],
    ]
    failing = [f for f in fields if not f["ok"]]
    if failing:
        lines += ["", "## Fields that do not match", ""]
        lines += [
            f"- {f['computation']}.{f['field']}: expected {f['expected']} ({f['expected_unit']}), "
            f"got {f['actual']} ({f['actual_unit']})"
            for f in failing
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=golden_dir().parent / "results")
    args = parser.parse_args()
    result = asyncio.run(run())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "deterministic.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.out / "deterministic.md").write_text(markdown(result))
    print(markdown(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
