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


def test_cost_is_computed_only_when_every_model_used_is_priced():
    calls = [_call("m1"), _call("m1", tin=2000, tout=0), _call("m2", ok=False, provider="bedrock")]
    priced = usage_summary(calls, {"m1": (1.0, 4.0)})
    assert priced["cost_usd"] == (3000 * 1.0 + 500 * 4.0) / 1e6
    assert priced["failed_calls"] == 1 and priced["providers"] == {"openai": 2}
    assert priced["llm_latency_ms"] == 300

    partial = usage_summary([*calls, _call("m3")], {"m1": (1.0, 4.0)})
    assert partial["cost_usd"] is None and partial["unpriced_models"] == ["m3"]
