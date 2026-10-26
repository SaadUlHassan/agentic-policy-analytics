from app.db.models import LLMCall
from app.llm.pricing import usage_summary


def _call(model, ok=True, tin=1000, tout=500, provider="openai", latency=100):
    return LLMCall(
        analysis_id="a",
        agent="x",
        purpose="p",
        provider=provider,
        model=model,
        ok=ok,
        latency_ms=latency,
        input_tokens=tin,
        output_tokens=tout,
    )


def test_cost_counts_every_call_and_needs_every_model_priced():
    # A failed call (e.g. a reply rejected for its structure) was still generated, so it is billed.
    calls = [_call("m1"), _call("m1", tin=2000, tout=0), _call("m2", ok=False, provider="bedrock")]
    priced = usage_summary(calls, {"m1": (1.0, 4.0), "m2": (2.0, 8.0)})
    assert priced["cost_usd"] == (3000 * 1.0 + 500 * 4.0 + 1000 * 2.0 + 500 * 8.0) / 1e6
    assert priced["input_tokens"] == 4000 and priced["output_tokens"] == 1000
    assert priced["failed_calls"] == 1 and priced["providers"] == {"openai": 2}
    assert priced["llm_latency_ms"] == 300

    partial = usage_summary(calls, {"m1": (1.0, 4.0)})
    assert partial["cost_usd"] is None and partial["unpriced_models"] == ["m2"]


def test_a_call_without_token_usage_makes_the_cost_unknown_not_free():
    summary = usage_summary([_call("m1"), _call("m1", tin=None, tout=None)], {"m1": (2.0, 4.0)})
    assert summary["cost_usd"] is None and summary["calls_without_usage"] == 1


def test_a_failed_call_with_unknown_usage_makes_the_cost_unknown():
    # e.g. a timeout: the provider may have generated a reply nobody received.
    summary = usage_summary([_call("m1"), _call("m1", ok=False, tin=None, tout=None)], {"m1": (2.0, 4.0)})
    assert summary["cost_usd"] is None and summary["calls_without_usage"] == 1


def test_a_call_that_sent_no_request_costs_nothing_and_keeps_the_total_known():
    # An injected fault is recorded with zero usage: nothing was sent, so nothing can be billed.
    summary = usage_summary([_call("m1"), _call("m1", ok=False, tin=0, tout=0)], {"m1": (2.0, 4.0)})
    assert summary["cost_usd"] == (1000 * 2.0 + 500 * 4.0) / 1e6
