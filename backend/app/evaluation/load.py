"""Load run (plan §8.4): `python -m app.evaluation.load` (or `make load`) against the offline stack.

The workload, for --duration seconds:
- 10 analysis slots, each submitting an analysis, following it over the WebSocket to its terminal
  event, checking the stored result, and submitting the next;
- 40 more WebSocket listeners following analyses in flight (50 in all);
- 20 reads a second of the history list and of finished analyses.

It measures what the targets name: POST acknowledgement and read latency, event delivery (client
receipt minus the event's commit time, `committed_at`, which the end-to-end stack's database
records; only events committed after the connection opened count, since replayed history is not a
delivery), queue wait (submission to the analysis starting), throughput and errors. A target with no
samples is reported as not measured, never as met. Reads arrive at the requested rate however long
each takes.

WebSocket follows stop when the window closes; then every submitted analysis is waited for over the
API: one that never reaches a terminal status with a stored report is a lost result. A result is
correct when it completed with exactly the expected findings (their values from the independently
computed golden expectations) and no rejected claim; a malformed report is incorrect. A run that
checked no analysis fails. The LLM is the offline stand-in, so this measures the platform (API,
queue, worker, database, event delivery), not a model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from websockets.asyncio.client import connect

from app.evaluation.golden import expected, golden_dir

QUESTION = "Analyse employment trends in the technology sector from 2020-2024"
TERMINAL = {"completed", "completed_with_limitations", "failed", "cancelled"}
TARGETS_MS = {"post_ack_p95": 300, "read_p95": 300, "event_delivery_p95": 1000}


@dataclass
class Measures:
    post_ms: list[float] = field(default_factory=list)
    read_ms: list[float] = field(default_factory=list)
    delivery_ms: list[float] = field(default_factory=list)
    queue_wait_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    submitted: dict[str, float] = field(default_factory=dict)  # analysis id -> submission time
    finished: set[str] = field(default_factory=set)
    reads: int = 0


def expected_findings() -> list[tuple[list[str], str]]:
    """The findings a correct analysis of QUESTION reports (series, text): the offline stand-in's two
    claims, rendered with the golden values C02 (CAGR) and C07 (vacancy change; the Data.gov.sg
    series mirrors M184071, value for value)."""
    golden = expected()["computations"]
    cagr = golden["C02"]["fields"]["cagr_pct"]["value"]
    vacancies = golden["C07"]["fields"]["pct_change"]["value"]
    return [
        (
            ["M182841:3.4@SSIC2020"],
            "Employment level in Information & Communications grew at a compound rate of "
            f"{cagr:.1f}% a year between 2020 and 2024.",
        ),
        (
            ["d_3f17bbf67d31d4d402caa8755eb74afc:information and communications@SSIC2020"],
            "Over the same period, job vacancies in Information & Communications rose by "
            f"{vacancies:.1f}% between 2020-Q1 and 2024-Q4.",
        ),
    ]


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


async def _follow(
    ws_url: str, analysis_id: str, m: Measures, deadline: float, *, owner: bool = False
) -> str | None:
    """Follow an analysis's events to the terminal one, until the workload window closes; records
    delivery of events committed after the connection opened (an event without a commit time is not
    measured), and, for the slot that submitted it (`owner`), its queue wait. Returns the terminal
    status, or None if cut off."""
    window = asyncio.timeout(max(0.0, deadline - time.time()))
    try:
        async with window, connect(f"{ws_url}/ws/analyses/{analysis_id}", open_timeout=10) as ws:
            opened = time.time()
            async for raw in ws:
                received = time.time()
                event = json.loads(raw)
                if event.get("committed_at") and (committed := _epoch(event["committed_at"])) >= opened:
                    m.delivery_ms.append((received - committed) * 1000)
                if event["type"] == "status":
                    status = event["detail"].get("status")
                    if owner and status == "running":
                        started = _epoch(event["ts"])
                        m.queue_wait_ms.append((started - m.submitted[analysis_id]) * 1000)
                    if status in TERMINAL:
                        return str(status)
    except TimeoutError:
        if not window.expired():
            raise
    return None


async def _slot(client: httpx.AsyncClient, ws_url: str, m: Measures, deadline: float) -> None:
    while time.time() < deadline:
        started = time.time()
        try:
            response = await client.post("/api/analyses", json={"query": QUESTION})
            m.post_ms.append((time.time() - started) * 1000)
            response.raise_for_status()
            analysis_id = response.json()["id"]
            m.submitted[analysis_id] = started
            await _follow(ws_url, analysis_id, m, deadline, owner=True)
            m.finished.add(analysis_id)
        except Exception as exc:  # recorded and counted; the run goes on
            m.errors.append(f"slot: {type(exc).__name__}: {exc}"[:200])
            await asyncio.sleep(1)


async def _listener(ws_url: str, m: Measures, deadline: float) -> None:
    while time.time() < deadline:
        in_flight = [a for a in m.submitted if a not in m.finished]
        if not in_flight:
            await asyncio.sleep(0.2)
            continue
        try:
            await _follow(ws_url, random.choice(in_flight), m, deadline)  # noqa: S311 (sampling)
        except Exception as exc:
            m.errors.append(f"listener: {type(exc).__name__}: {exc}"[:200])
            await asyncio.sleep(1)


async def _read(client: httpx.AsyncClient, m: Measures, path: str) -> None:
    started = time.time()
    try:
        response = await client.get(path)
        m.read_ms.append((time.time() - started) * 1000)
        response.raise_for_status()
        m.reads += 1
    except Exception as exc:
        m.errors.append(f"read: {type(exc).__name__}: {exc}"[:200])


async def _reader(client: httpx.AsyncClient, m: Measures, deadline: float, rate: float) -> None:
    """Reads arrive on a fixed schedule, `rate` a second: a slow read does not delay the next."""
    reads: list[asyncio.Task[None]] = []
    arrival = time.time()
    while arrival < deadline:
        done = list(m.finished)
        detail = f"/api/analyses/{random.choice(done)}" if done else None  # noqa: S311 (sampling)
        path = detail if detail and len(reads) % 2 else "/api/analyses?limit=20"
        reads.append(asyncio.create_task(_read(client, m, path)))
        arrival += 1 / rate
        await asyncio.sleep(max(0.0, arrival - time.time()))
    await asyncio.gather(*reads)


async def _settle(client: httpx.AsyncClient, m: Measures, grace_s: float) -> tuple[list[str], list[str]]:
    """Wait for every submitted analysis to finish; return the lost ones and the incorrect ones."""
    wanted = expected_findings()
    ends = time.time() + grace_s
    pending = set(m.submitted)
    results: dict[str, dict[str, Any]] = {}
    while pending and time.time() < ends:
        for analysis_id in list(pending):
            detail = (await client.get(f"/api/analyses/{analysis_id}")).json()
            if isinstance(detail, dict) and detail.get("status") in TERMINAL:
                results[analysis_id] = detail
                pending.discard(analysis_id)
        if pending:
            await asyncio.sleep(2)
    lost = sorted(pending) + sorted(a for a, d in results.items() if d.get("report") is None)
    incorrect = sorted(
        a for a, d in results.items() if d.get("report") is not None and not _correct(d, wanted)
    )
    return lost, incorrect


def _correct(detail: dict[str, Any], wanted: list[tuple[list[str], str]]) -> bool:
    """Completed with exactly the wanted findings and no rejected claim; anything malformed is not."""
    report = detail["report"]
    if detail.get("status") != "completed" or not isinstance(report, dict):
        return False
    findings, verification = report.get("findings"), report.get("verification")
    if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
        return False
    return (
        [(f.get("series"), f.get("text")) for f in findings] == wanted
        and isinstance(verification, dict)
        and verification.get("claims_rejected") == 0
    )


def _within(value: float | None, limit: float) -> bool | None:
    """None when there were no samples: the target was not measured, which never counts as met."""
    return None if value is None else value < limit


def _p(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile: the smallest value at or above which a fraction q of values lie."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(q * len(ordered)) - 1)], 1)


async def run(base: str, duration_s: float, slots: int, listeners: int, read_rate: float) -> dict[str, Any]:
    ws_url = base.replace("http", "ws", 1)
    m = Measures()
    started = time.time()
    deadline = started + duration_s
    limits = httpx.Limits(max_connections=100)
    async with httpx.AsyncClient(base_url=base, timeout=30, limits=limits) as client:
        await asyncio.gather(
            *(_slot(client, ws_url, m, deadline) for _ in range(slots)),
            *(_listener(ws_url, m, deadline) for _ in range(listeners)),
            _reader(client, m, deadline, read_rate),
        )
        lost, incorrect = await _settle(client, m, grace_s=120)
    elapsed = time.time() - started
    measured = {
        "post_ack_p50": _p(m.post_ms, 0.5),
        "post_ack_p95": _p(m.post_ms, 0.95),
        "read_p50": _p(m.read_ms, 0.5),
        "read_p95": _p(m.read_ms, 0.95),
        "event_delivery_p50": _p(m.delivery_ms, 0.5),
        "event_delivery_p95": _p(m.delivery_ms, 0.95),
        "queue_wait_p50": _p(m.queue_wait_ms, 0.5),
        "queue_wait_p95": _p(m.queue_wait_ms, 0.95),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpus": os.cpu_count(),
        },
        "workload": {
            "duration_s": duration_s,
            "analysis_slots": slots,
            "websocket_listeners": slots + listeners,
            "read_rate_per_s": read_rate,
            "question": QUESTION,
            "llm": "offline stand-in (LLM_MODE=offline), snapshot data",
        },
        "analyses_submitted": len(m.submitted),
        "analyses_per_minute": round(len(m.submitted) / (duration_s / 60), 1),
        "reads": m.reads,
        "events_delivered_live": len(m.delivery_ms),
        "errors": len(m.errors),
        "error_samples": m.errors[:10],
        "error_rate": round(len(m.errors) / max(1, len(m.post_ms) + m.reads), 4),
        "lost_terminal_results": lost,
        "incorrect_results": incorrect,
        "latency_ms": measured,
        "targets": {
            "analyses_checked": bool(m.submitted),
            "zero_lost_terminal_results": not lost,
            "zero_correctness_failures": not incorrect,
            **{f"{name} < {limit} ms": _within(measured[name], limit) for name, limit in TARGETS_MS.items()},
        },
        "elapsed_s": round(elapsed, 1),
        "mean_delivery_ms": round(statistics.mean(m.delivery_ms), 1) if m.delivery_ms else None,
    }


_VERDICT = {True: "met", False: "**missed**", None: "**not measured**"}


def markdown(r: dict[str, Any]) -> str:
    w = r["workload"]
    lat = {k: "not measured" if v is None else v for k, v in r["latency_ms"].items()}
    lines = [
        "# Load run",
        "",
        f"Generated {r['generated_at']} on {r['machine']['platform']} ({r['machine']['cpus']} CPUs), "
        "against the stack in offline mode (deterministic LLM stand-in, snapshot data).",
        "",
        f"Workload: {w['duration_s']:.0f} s; {w['analysis_slots']} analysis slots resubmitting continuously; "
        f"{w['websocket_listeners']} WebSocket listeners; {w['read_rate_per_s']:.0f} reads a second.",
        "",
        "| Target | Result |",
        "|---|---|",
        *[f"| {name.replace('_', ' ')} | {_VERDICT[ok]} |" for name, ok in r["targets"].items()],
        "",
        "| Measure | p50 | p95 |",
        "|---|---|---|",
        f"| POST acknowledgement (ms) | {lat['post_ack_p50']} | {lat['post_ack_p95']} |",
        f"| Read, history or detail (ms) | {lat['read_p50']} | {lat['read_p95']} |",
        f"| Event delivery, commit to client (ms) | {lat['event_delivery_p50']} "
        f"| {lat['event_delivery_p95']} |",
        f"| Queue wait, submission to start (ms) | {lat['queue_wait_p50']} | {lat['queue_wait_p95']} |",
        "",
        f"- Analyses submitted: {r['analyses_submitted']} ({r['analyses_per_minute']} a minute).",
        f"- Live events delivered: {r['events_delivered_live']}; reads: {r['reads']}.",
        f"- Errors: {r['errors']} (rate {r['error_rate']:.2%}).",
        f"- Lost terminal results: {len(r['lost_terminal_results'])}; incorrect results: "
        f"{len(r['incorrect_results'])}.",
    ]
    if r["error_samples"]:
        lines += ["", "Error samples:", *[f"- {e}" for e in r["error_samples"]]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", default="http://localhost:8200", help="API of the offline stack")
    parser.add_argument("--duration", type=float, default=300, help="seconds")
    parser.add_argument("--slots", type=int, default=10)
    parser.add_argument("--listeners", type=int, default=40, help="in addition to one per slot")
    parser.add_argument("--read-rate", type=float, default=20, help="reads a second")
    parser.add_argument("--out", type=Path, default=golden_dir().parent / "results" / "load")
    args = parser.parse_args()
    result = asyncio.run(run(args.base, args.duration, args.slots, args.listeners, args.read_rate))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "load.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.out / "load.md").write_text(markdown(result))
    print(markdown(result))
    met = result["targets"]
    hard = ("analyses_checked", "zero_lost_terminal_results", "zero_correctness_failures")
    return 0 if all(met[t] for t in hard) else 1


if __name__ == "__main__":
    raise SystemExit(main())
