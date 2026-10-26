"""Expected values for the golden computations, computed independently of the application.

Deliberately shares no code with backend/app: it reads the raw snapshot payloads itself, parses
them itself and computes every statistic from its definition (numpy for 2x2 matrix algebra only; no
statsmodels, no scipy, none of the application's parsers or tools). Every field also records the
unit and scale it is in, derived from what it measures, so a correct number in the wrong unit fails.
Agreement between this script and the application's toolkit is therefore evidence that both are
right, not that one copied the other.

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
from statistics import NormalDist

import numpy as np
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


def newey_west_interval(ys: list[float], step: float, lags: int) -> tuple[float, float]:
    """95% interval for the OLS slope with Newey-West (HAC) errors: Bartlett kernel weights
    1 - l/(lags+1), no small-sample correction, normal critical value. This is the convention the
    plan specifies for quarterly trends (consecutive quarters are serially dependent)."""
    n = len(ys)
    x = np.column_stack([np.ones(n), np.arange(n) * step])
    y = np.asarray(ys, dtype=float)
    bread = np.linalg.inv(x.T @ x)
    beta = bread @ x.T @ y
    e = y - x @ beta
    meat = sum(e[i] ** 2 * np.outer(x[i], x[i]) for i in range(n))
    for lag in range(1, lags + 1):
        cross = sum(e[i] * e[i - lag] * np.outer(x[i], x[i - lag]) for i in range(lag, n))
        meat = meat + (1 - lag / (lags + 1)) * (cross + cross.T)
    se = math.sqrt((bread @ meat @ bread)[1, 1])
    z = NormalDist().inv_cdf(0.975)
    return float(beta[1] - z * se), float(beta[1] + z * se)


# -- one function per golden tool ---------------------------------------------------------------
# Each field is (value, tolerance class, kind); the kind says what the number measures, which fixes
# its unit and scale: "source" is the series' own unit and scale.

MIN_ANNUAL_POINTS_FOR_INTERVAL = 8  # fewer annual points: a descriptive slope only


def change_between(v: dict[str, float], start: str, end: str) -> dict:
    a, b = v[start], v[end]
    return {
        "start_value": (a, EXACT, "source"),
        "end_value": (b, EXACT, "source"),
        "abs_change": (b - a, integral(a, b), "source"),
        "pct_change": ((b - a) / abs(a) * 100, CLOSED_FORM, "percent"),
    }


def yoy_change(v: dict[str, float], period: str) -> dict:
    prior = _period(_index(period) - per_year(period), "-Q" in period)
    return change_between(v, prior, period)


def cagr(v: dict[str, float], start: str, end: str) -> dict:
    years = (_index(end) - _index(start)) / per_year(start)
    return {"cagr_pct": (((v[end] / v[start]) ** (1 / years) - 1) * 100, CLOSED_FORM, "percent_per_year")}


def trend(v: dict[str, float], start: str, end: str) -> dict:
    ys = [v[p] for p in span(start, end)]
    step = 1 / per_year(start)
    out = {"slope": (ols_slope(ys, step), ESTIMATOR, "per_year")}
    if per_year(start) > 1 or len(ys) >= MIN_ANNUAL_POINTS_FOR_INTERVAL:
        low, high = newey_west_interval(ys, step, lags=per_year(start))
        out["slope_ci_low"] = (low, ESTIMATOR, "per_year")
        out["slope_ci_high"] = (high, ESTIMATOR, "per_year")
    return out


def cumulative(v: dict[str, float], start: str, end: str) -> dict:
    values = [v[p] for p in span(start, end)]
    return {"total": (sum(values), integral(*values), "source")}


def compare_periods(v: dict[str, float], a_start: str, a_end: str, b_start: str, b_end: str) -> dict:
    a = mean([v[p] for p in span(a_start, a_end)])
    b = mean([v[p] for p in span(b_start, b_end)])
    return {
        "mean_a": (a, CLOSED_FORM, "source"),
        "mean_b": (b, CLOSED_FORM, "source"),
        "difference": (b - a, CLOSED_FORM, "source"),
    }


def correlate(x: dict[str, float], y: dict[str, float], start: str, end: str, lag: str) -> dict:
    """Pairs (x_t, y_t+lag) with both periods inside the window; incomplete pairs are skipped."""
    periods = span(start, end)
    pairs = [(x[p], y[q]) for p, q in zip(periods, periods[int(lag) :], strict=False) if p in x and q in y]
    a, b = [p[0] for p in pairs], [p[1] for p in pairs]
    return {
        "pearson_r": (pearson(a, b), ESTIMATOR, "correlation"),
        "spearman_rho": (pearson(average_ranks(a), average_ranks(b)), ESTIMATOR, "correlation"),
        "pairs": (float(len(pairs)), EXACT, "pairs"),
    }


TOOLS = {
    "change_between": change_between,
    "yoy_change": yoy_change,
    "cagr": cagr,
    "trend": trend,
    "cumulative": cumulative,
    "compare_periods": compare_periods,
}


def unit_and_scale(kind: str, series: dict) -> tuple[str, int]:
    return {
        "source": (series["unit"], series["scale"]),
        "per_year": (f"{series['unit']}_per_year", series["scale"]),
        "percent": ("percent", 1),
        "percent_per_year": ("percent_per_year", 1),
        "correlation": ("correlation", 1),
        "pairs": ("pairs", 1),
    }[kind]


def expected() -> dict:
    golden = yaml.safe_load((GOLDEN / "queries.yaml").read_text())
    series = {name: load_series(spec) for name, spec in golden["series"].items()}
    out = {}
    for cid, c in golden["computations"].items():
        if c["tool"] == "correlate":
            fields = correlate(series[c["series"]], series[c["other"]], **c["params"])
        else:
            fields = TOOLS[c["tool"]](series[c["series"]], **c["params"])
        spec = golden["series"][c["series"]]
        out[cid] = {
            "tool": c["tool"],
            "fields": {
                name: dict(
                    zip(("unit", "scale"), unit_and_scale(kind, spec), strict=True),
                    value=value,
                    tolerance=tol,
                )
                for name, (value, tol, kind) in fields.items()
            },
        }
    captured = json.loads((SNAPSHOTS / "manifest.json").read_text())["captured_at"]
    return {"snapshots_captured_at": captured, "computations": out}


# Recomputing on another platform can change the last digits of float results (e.g. a different BLAS
# behind the 2x2 algebra). The stored values are current if they match to far tighter than any gate.
FRESHNESS_REL_TOL = 1e-12


def matches(stored: object, fresh: object) -> bool:
    """Same structure and strings; numbers equal to FRESHNESS_REL_TOL."""
    if isinstance(stored, dict) and isinstance(fresh, dict):
        return stored.keys() == fresh.keys() and all(matches(stored[k], fresh[k]) for k in stored)
    if isinstance(stored, int | float) and isinstance(fresh, int | float):
        return math.isclose(stored, fresh, rel_tol=FRESHNESS_REL_TOL, abs_tol=0.0)
    return stored == fresh


def is_current(target: Path) -> bool:
    return target.exists() and matches(json.loads(target.read_text()), expected())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if expected.json is out of date")
    args = parser.parse_args()
    target = GOLDEN / "expected.json"
    if args.check:
        if not is_current(target):
            print("eval/golden/expected.json is stale: rerun eval/compute_expected.py", file=sys.stderr)
            return 1
        return 0
    target.write_text(json.dumps(expected(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
