from __future__ import annotations

import botocore.exceptions
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from app.core.config import Settings
from app.llm import providers
from app.llm.offline import OfflineChatModel
from app.llm.router import LLMRouter, LLMUnavailable, normalise
from app.llm.scripted import ScriptedChatModel, tool_call

QUESTION = [HumanMessage("question")]


class Plan(BaseModel):
    sector: str
    start_year: int


def _client_error(code: str) -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError({"Error": {"Code": code, "Message": code}}, "Converse")


def _router(bedrock: list, openai: list, **kw) -> tuple[LLMRouter, list]:
    records: list = []

    async def sink(record):
        records.append(record)

    models = {"bedrock": ScriptedChatModel(replies=bedrock), "openai": ScriptedChatModel(replies=openai)}
    router = LLMRouter(settings=Settings(_env_file=None), models=models, on_record=sink, backoff_s=0, **kw)
    return router, records


def test_offline_mode_never_builds_a_real_provider(monkeypatch):
    def real(provider, settings):
        raise AssertionError(f"built a real {provider} model in offline mode")

    monkeypatch.setattr(providers, "build", real)
    router = LLMRouter(settings=Settings(_env_file=None, llm_mode="offline"))
    assert isinstance(router.model("bedrock"), OfflineChatModel)
    assert isinstance(router.model("openai"), OfflineChatModel)


def test_normalise_drops_reasoning_blocks_and_keeps_tool_calls():
    raw = AIMessage(
        content=[
            {"type": "reasoning_content", "reasoning_content": {"text": "private"}},
            {"type": "text", "text": "public"},
        ],
        tool_calls=[{"name": "t", "args": {}, "id": "1", "type": "tool_call"}],
    )
    msg = normalise(raw)
    assert msg.content == "public" and msg.tool_calls[0]["name"] == "t"


async def test_retryable_error_is_retried_on_the_same_provider():
    router, records = _router([_client_error("ThrottlingException"), AIMessage("ok")], [])
    msg = await router.step(QUESTION, [], agent="extraction", purpose="test")
    assert msg.content == "ok"
    assert [(r.provider, r.ok) for r in records] == [("bedrock", False), ("bedrock", True)]


async def test_non_retryable_error_fails_over_immediately_and_records_fallback():
    router, records = _router([_client_error("AccessDeniedException")], [AIMessage("from openai")])
    msg = await router.step(QUESTION, [], agent="coordinator", purpose="test")
    assert msg.content == "from openai"
    assert [(r.provider, r.ok, r.fallback_from) for r in records] == [
        ("bedrock", False, None),
        ("openai", True, "bedrock"),
    ]


async def test_total_outage_names_every_provider():
    router, _ = _router(
        [_client_error("AccessDeniedException")], [TimeoutError("slow"), TimeoutError("slow")]
    )
    with pytest.raises(LLMUnavailable, match="bedrock: ClientError.*openai: TimeoutError"):
        await router.step(QUESTION, [], agent="a", purpose="p")


async def test_open_circuit_skips_the_failing_provider():
    denied = [_client_error("AccessDeniedException") for _ in range(2)]
    router, records = _router(denied, [AIMessage("1"), AIMessage("2"), AIMessage("3")], circuit_threshold=2)
    for _ in range(3):
        await router.step(QUESTION, [], agent="a", purpose="p")
    assert [r.provider for r in records].count("bedrock") == 2  # third call skipped bedrock entirely


async def test_structured_output_is_repaired_once_then_parsed():
    bad = tool_call("Plan", {"sector": "info_comms"})  # missing start_year
    good = tool_call("Plan", {"sector": "info_comms", "start_year": 2020})
    router, _ = _router([bad, good], [])
    plan = await router.structured(Plan, QUESTION, agent="coordinator", purpose="plan")
    assert plan == Plan(sector="info_comms", start_year=2020)
    assert "did not match" in router.models["bedrock"].calls[1][-1].content


async def test_structured_output_still_invalid_after_repair_fails_over():
    bad = tool_call("Plan", {"sector": "info_comms"})
    router, records = _router([bad, bad], [tool_call("Plan", {"sector": "x", "start_year": 2021})])
    plan = await router.structured(Plan, QUESTION, agent="coordinator", purpose="plan")
    assert plan.start_year == 2021 and records[-1].fallback_from == "bedrock"


async def test_expired_deadline_raises_without_calling_a_model():
    router, records = _router([AIMessage("never")], [AIMessage("never")], clock=lambda: 100.0)
    with pytest.raises(LLMUnavailable, match="deadline"):
        await router.step(QUESTION, [], agent="a", purpose="p", deadline=90.0)
    assert records == []


async def test_too_little_time_for_primary_plus_reserve_goes_straight_to_the_fallback():
    # 10 s left, 30 s reserved for the fallback: the primary is skipped, not a reason to give up.
    router, records = _router([AIMessage("never")], [AIMessage("fallback answer")], clock=lambda: 0.0)
    msg = await router.step(QUESTION, [], agent="a", purpose="p", deadline=10.0)
    assert msg.content == "fallback answer"
    assert router.models["bedrock"].calls == []
    assert [(r.provider, r.fallback_from) for r in records] == [("openai", "bedrock")]


async def test_structured_repair_shares_the_original_time_budget():
    now = [0.0]

    def slow_invalid_reply(messages):
        now[0] += 50.0  # the first answer uses up more than the 45 s per-call budget
        return tool_call("Plan", {"sector": "info_comms"})

    router, _ = _router(
        [slow_invalid_reply],
        [tool_call("Plan", {"sector": "x", "start_year": 2021})],
        clock=lambda: now[0],
        attempts_per_provider=1,
    )
    plan = await router.structured(Plan, QUESTION, agent="coordinator", purpose="plan")
    assert len(router.models["bedrock"].calls) == 1  # no repair attempt after the budget was spent
    assert plan.start_year == 2021


async def test_a_rejected_structured_reply_is_metered_and_a_repair_counts_both_replies():
    usage = {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500}
    bad = tool_call("Plan", {"sector": "info_comms"}).model_copy(update={"usage_metadata": usage})
    good = tool_call("Plan", {"sector": "info_comms", "start_year": 2020}).model_copy(
        update={"usage_metadata": usage}
    )
    # Bedrock: rejected, rejected (fails over). OpenAI: rejected, then repaired.
    router, records = _router([bad, bad], [bad, good])

    await router.structured(Plan, QUESTION, agent="coordinator", purpose="plan")

    failed, answered = records
    assert not failed.ok and "StructuredOutputError" in failed.error
    assert (failed.input_tokens, failed.output_tokens) == (2000, 1000), "both rejected replies were generated"
    assert answered.ok and (answered.input_tokens, answered.output_tokens) == (2000, 1000)


async def test_an_injected_fault_is_recorded_as_sending_nothing():
    from tests.unit.test_faults import Switched

    router, records = _router([], [tool_call("Plan", {"sector": "x", "start_year": 2020})])
    router.faults = Switched("llm:bedrock")

    await router.structured(Plan, QUESTION, agent="coordinator", purpose="plan")

    assert (records[0].input_tokens, records[0].output_tokens) == (0, 0)
