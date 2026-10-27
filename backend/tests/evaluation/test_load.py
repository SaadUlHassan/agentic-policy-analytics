"""The load run's measures and report (no stack needed)."""

from __future__ import annotations

from app.evaluation import load


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
