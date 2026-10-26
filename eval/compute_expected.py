"""Expected values for the golden computations, computed independently of the application.

Deliberately shares no code with backend/app: it reads the raw snapshot payloads itself, parses
them itself and computes every statistic from its definition (no statsmodels, no scipy, none of the
application's parsers or tools). Agreement between this script and the application's toolkit is
therefore evidence that both are right, not that one copied the other.

Usage (from the repository root):
    uv run --project backend python eval/compute_expected.py          # write eval/golden/expected.json
    uv run --project backend python eval/compute_expected.py --check  # fail if the file is stale
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "snapshots"
GOLDEN = ROOT / "eval" / "golden"

# Tolerance classes (plan §8.3): integer arithmetic on source values is exact; closed-form float
# formulas agree to a relative 1e-9; iterative or statistical estimators to 1e-6.
EXACT, CLOSED_FORM, ESTIMATOR = "exact", "closed_form", "estimator"


# -- reading the raw payloads -------------------------------------------------------------------


def _payloads(dataset: str) -> list[dict]:
    manifest = json.loads((SNAPSHOTS / "manifest.json").read_text())
    entries = [e for e in manifest["entries"] if e["dataset"] == dataset]
    return [{**e, "body": (SNAPSHOTS / e["path"]).read_bytes()} for e in entries]


def _singstat(dataset: str, row: str) -> dict[str, float]:
    """SingStat Table Builder pages: a row's columns may be split across pages."""
    values: dict[str, float] = {}
    for p in sorted(_payloads(dataset), key=lambda e: e["kind"]):
        for r in json.loads(p["body"])["Data"]["row"]:
            if r["seriesNo"] != row:
                continue
            for c in r["columns"]:
                key = c["key"].strip()
                period = f"{key[:4]}-Q{key[5]}" if key.endswith("Q") else key
                with contextlib.suppress(ValueError):  # a marker: no value
                    values[period] = float(c["value"])
    return values


def _datagov(dataset: str, label: str, period_field: str, value_field: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for p in _payloads(dataset):
        if not p["kind"].startswith("datastore"):
            continue
        for record in json.loads(p["body"])["result"]["records"]:
            if record["industry"] == label:
                with contextlib.suppress(ValueError):  # a marker: no value
                    values[record[period_field]] = float(record[value_field])
    return values


def load_series(spec: dict) -> dict[str, float]:
    if spec["dataset"].startswith("d_"):
        return _datagov(spec["dataset"], spec["source_row"], "year", "job_vacancy")
    return _singstat(spec["dataset"], spec["source_row"])


# -- periods ------------------------------------------------------------------------------------


def _index(period: str) -> int:
    return int(period[:4]) * 4 + int(period[-1]) - 1 if "-Q" in period else int(period)


def _period(index: int, quarterly: bool) -> str:
    return f"{index // 4}-Q{index % 4 + 1}" if quarterly else str(index)


def span(start: str, end: str) -> list[str]:
    quarterly = "-Q" in start
    return [_period(i, quarterly) for i in range(_index(start), _index(end) + 1)]


def per_year(period: str) -> int:
    return 4 if "-Q" in period else 1


# -- statistics from their definitions ----------------------------------------------------------


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def ols_slope(ys: list[float], step: float) -> float:
    ts = [i * step for i in range(len(ys))]
    mt, my = mean(ts), mean(ys)
    return sum((t - mt) * (y - my) for t, y in zip(ts, ys, strict=True)) / sum((t - mt) ** 2 for t in ts)


def pearson(x: list[float], y: list[float]) -> float:
    mx, my = mean(x), mean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    return cov / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))


def average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def integral(*values: float) -> str:
    return EXACT if all(float(v).is_integer() for v in values) else CLOSED_FORM


# -- one function per golden tool -----------------------------------------------------------------


def change_between(v: dict[str, float], start: str, end: str) -> dict:
    a, b = v[start], v[end]
    return {
        "start_value": (a, EXACT),
        "end_value": (b, EXACT),
        "abs_change": (b - a, integral(a, b)),
        "pct_change": ((b - a) / abs(a) * 100, CLOSED_FORM),
    }


def yoy_change(v: dict[str, float], period: str) -> dict:
    prior = _period(_index(period) - per_year(period), "-Q" in period)
    return change_between(v, prior, period)


def cagr(v: dict[str, float], start: str, end: str) -> dict:
    years = (_index(end) - _index(start)) / per_year(start)
    return {"cagr_pct": (((v[end] / v[start]) ** (1 / years) - 1) * 100, CLOSED_FORM)}


def trend(v: dict[str, float], start: str, end: str) -> dict:
    ys = [v[p] for p in span(start, end)]
    return {"slope": (ols_slope(ys, 1 / per_year(start)), ESTIMATOR)}


def cumulative(v: dict[str, float], start: str, end: str) -> dict:
    values = [v[p] for p in span(start, end)]
    return {"total": (sum(values), integral(*values))}


def compare_periods(v: dict[str, float], a_start: str, a_end: str, b_start: str, b_end: str) -> dict:
    a = mean([v[p] for p in span(a_start, a_end)])
    b = mean([v[p] for p in span(b_start, b_end)])
    return {"mean_a": (a, CLOSED_FORM), "mean_b": (b, CLOSED_FORM), "difference": (b - a, CLOSED_FORM)}


def correlate(x: dict[str, float], y: dict[str, float], start: str, end: str, lag: str) -> dict:
    """Pairs (x_t, y_t+lag) with both periods inside the window; incomplete pairs are skipped."""
    periods = span(start, end)
    pairs = [(x[p], y[q]) for p, q in zip(periods, periods[int(lag) :], strict=False) if p in x and q in y]
    a, b = [p[0] for p in pairs], [p[1] for p in pairs]
    return {
        "pearson_r": (pearson(a, b), ESTIMATOR),
        "spearman_rho": (pearson(average_ranks(a), average_ranks(b)), ESTIMATOR),
        "pairs": (float(len(pairs)), EXACT),
    }


TOOLS = {
    "change_between": change_between,
    "yoy_change": yoy_change,
    "cagr": cagr,
    "trend": trend,
    "cumulative": cumulative,
    "compare_periods": compare_periods,
}


def expected() -> dict:
    golden = yaml.safe_load((GOLDEN / "queries.yaml").read_text())
    series = {name: load_series(spec) for name, spec in golden["series"].items()}
    out = {}
    for cid, c in golden["computations"].items():
        if c["tool"] == "correlate":
            fields = correlate(series[c["series"]], series[c["other"]], **c["params"])
        else:
            fields = TOOLS[c["tool"]](series[c["series"]], **c["params"])
        out[cid] = {
            "tool": c["tool"],
            "fields": {name: {"value": value, "tolerance": tol} for name, (value, tol) in fields.items()},
        }
    captured = json.loads((SNAPSHOTS / "manifest.json").read_text())["captured_at"]
    return {"snapshots_captured_at": captured, "computations": out}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if expected.json is out of date")
    args = parser.parse_args()
    text = json.dumps(expected(), indent=2, sort_keys=True) + "\n"
    target = GOLDEN / "expected.json"
    if args.check:
        if not target.exists() or target.read_text() != text:
            print("eval/golden/expected.json is stale: rerun eval/compute_expected.py", file=sys.stderr)
            return 1
        return 0
    target.write_text(text)
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
