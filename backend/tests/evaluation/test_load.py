"""The load run's measures and report (no stack needed)."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

import httpx
import pytest

from app.evaluation import load


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="http://load.test", transport=httpx.MockTransport(handler))


def _report(findings: list[tuple[list[str], str]]) -> dict:
    return {
        "findings": [{"series": series, "text": text} for series, text in findings],
        "verification": {"claims_rejected": 0},
    }


async def _settle_one(report: dict) -> tuple[list[str], list[str]]:
    def detail(request):
        return httpx.Response(200, json={"id": "a", "status": "completed", "report": report})

    async with _client(detail) as client:
        return await load._settle(client, load.Measures(submitted={"a": time.time()}), grace_s=1)


async def test_a_result_is_correct_only_with_the_expected_findings():
    wanted = load.expected_findings()
    assert await _settle_one(_report(wanted)) == ([], [])
    wrong_value = [wanted[0], (wanted[1][0], wanted[1][1].replace("21.7%", "99.9%"))]
    assert await _settle_one(_report(wrong_value)) == ([], ["a"])
    assert await _settle_one(_report([wanted[1], wanted[0]])) == ([], ["a"])  # same count, out of order


@pytest.mark.parametrize(
    "report",
    [{}, {"findings": None}, {"findings": [None]}, {"findings": "text"}, "report"],
    ids=["no findings", "null findings", "null finding", "findings not a list", "report not an object"],
)
async def test_a_malformed_report_is_incorrect_not_an_error(report):
    assert await _settle_one(report) == ([], ["a"])


async def test_a_report_without_its_verification_is_incorrect():
    report = _report(load.expected_findings())
    del report["verification"]
    assert await _settle_one(report) == ([], ["a"])


def test_the_expected_findings_carry_the_golden_values():
    texts = [text for _, text in load.expected_findings()]
    assert "3.4% a year between 2020 and 2024" in texts[0]
    assert "rose by 21.7% between 2020-Q1 and 2024-Q4" in texts[1]


class _Socket:
    """A WebSocket that runs `opening` when it opens and `sending` before each of `events`, then
    stays open."""

    def __init__(self, events: list[dict], opening=lambda: None, sending=lambda: None):
        self.events, self.opening, self.sending = list(events), opening, sending

    async def __aenter__(self):
        self.opening()
        return self

    async def __aexit__(self, *args):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.events:
            self.sending()
            return json.dumps(self.events.pop(0))
        await asyncio.Event().wait()


def _stamp(at: float | None) -> str | None:
    return None if at is None else datetime.fromtimestamp(at, UTC).isoformat()


def _event(started: float, committed: float | None, status: str) -> dict:
    return {
        "ts": _stamp(started),
        "committed_at": _stamp(committed),
        "type": "status",
        "detail": {"status": status},
    }


async def _follow(monkeypatch, events: list[dict], opened: float, received: float) -> load.Measures:
    """Follow `events` over a connection that opens at `opened` and receives each at `received`."""
    clock = [0.0]
    socket = _Socket(
        events, opening=lambda: clock.__setitem__(0, opened), sending=lambda: clock.__setitem__(0, received)
    )
    monkeypatch.setattr(load.time, "time", lambda: clock[0])
    monkeypatch.setattr(load, "connect", lambda *a, **k: socket)
    m = load.Measures()
    assert await load._follow("ws://load.test", "a", m, deadline=received + 60) == "completed"
    return m


async def test_delivery_is_measured_from_commit_not_from_the_transaction_start(monkeypatch):
    # The event's transaction started at 1001.000 and committed at 1001.150; it arrived 5 ms later.
    m = await _follow(monkeypatch, [_event(1001.0, 1001.150, "completed")], opened=1000.0, received=1001.155)
    assert m.delivery_ms == [pytest.approx(5.0, abs=0.01)]


async def test_events_committed_before_the_connection_opened_are_replay_not_delivery(monkeypatch):
    events = [_event(1000.5, 1001.0, "running"), _event(1002.5, 1003.0, "completed")]
    m = await _follow(monkeypatch, events, opened=1002.0, received=1003.01)
    assert m.delivery_ms == [pytest.approx(10.0, abs=0.01)]  # only the event committed after opening


async def test_an_event_without_a_commit_time_is_not_measured(monkeypatch):
    m = await _follow(monkeypatch, [_event(1001.0, None, "completed")], opened=1000.0, received=1002.0)
    assert m.delivery_ms == []


async def test_a_stalled_stream_is_cut_off_when_the_window_closes(monkeypatch):
    monkeypatch.setattr(load, "connect", lambda *a, **k: _Socket([]))
    m = load.Measures()
    started = time.time()

    assert await load._follow("ws://load.test", "a", m, deadline=started + 0.1) is None
    assert time.time() - started < 1 and not m.errors


async def test_reads_keep_the_requested_arrival_rate_when_each_is_slow():
    async def slow(request):
        await asyncio.sleep(0.15)
        return httpx.Response(200, json={})

    m = load.Measures()
    async with _client(slow) as client:
        await load._reader(client, m, deadline=time.time() + 0.4, rate=20)
    assert m.reads >= 7  # 8 arrivals in 0.4 s at 20 a second, though each read takes 0.15 s


async def test_a_latency_target_without_samples_is_not_measured_not_met(monkeypatch):
    async def slot(client, ws_url, m, deadline):
        m.submitted["a"] = time.time()
        m.post_ms.append(1.0)

    async def reader(client, m, deadline, rate):
        m.read_ms.append(1.0)

    async def settle(*args, **kwargs):
        return [], []

    monkeypatch.setattr(load, "_slot", slot)
    monkeypatch.setattr(load, "_reader", reader)
    monkeypatch.setattr(load, "_settle", settle)
    result = await load.run("http://load.test", 0.01, 1, 0, 20)

    assert result["latency_ms"]["event_delivery_p95"] is None
    assert result["targets"]["event_delivery_p95 < 1000 ms"] is None
    assert result["targets"]["post_ack_p95 < 300 ms"] is True
    text = load.markdown(result)
    assert "| event delivery p95 < 1000 ms | **not measured** |" in text
    assert "| Event delivery, commit to client (ms) | not measured | not measured |" in text


def test_a_run_that_checked_no_analysis_fails(monkeypatch, tmp_path):
    def refuse(request):
        return httpx.Response(500, json={"detail": "server failure"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        load.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(refuse))
    )
    monkeypatch.setattr(
        "sys.argv",
        ["load", "--duration", "0.05", "--slots", "1", "--listeners", "0", "--out", str(tmp_path)],
    )
    assert load.main() == 1
    assert json.loads((tmp_path / "load.json").read_text())["targets"]["analyses_checked"] is False


def test_percentiles_are_taken_from_the_measured_values():
    values = [float(v) for v in range(1, 101)]
    assert load._p(values, 0.5) == 50.0 and load._p(values, 0.95) == 95.0
    assert load._p([], 0.95) is None


def test_the_report_states_every_target_and_any_loss():
    result = {
        "generated_at": "t",
        "machine": {"platform": "p", "cpus": 8},
        "workload": {
            "duration_s": 300,
            "analysis_slots": 10,
            "websocket_listeners": 50,
            "read_rate_per_s": 20,
        },
        "analyses_submitted": 3,
        "analyses_per_minute": 0.6,
        "reads": 10,
        "events_delivered_live": 5,
        "errors": 0,
        "error_samples": [],
        "error_rate": 0.0,
        "lost_terminal_results": ["a"],
        "incorrect_results": [],
        "latency_ms": {
            k: 1.0
            for k in (
                "post_ack_p50",
                "post_ack_p95",
                "read_p50",
                "read_p95",
                "event_delivery_p50",
                "event_delivery_p95",
                "queue_wait_p50",
                "queue_wait_p95",
            )
        },
        "targets": {"zero_lost_terminal_results": False, "zero_correctness_failures": True},
    }
    text = load.markdown(result)
    assert "| zero lost terminal results | **missed** |" in text
    assert "Lost terminal results: 1" in text
