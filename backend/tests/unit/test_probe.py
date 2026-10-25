"""The capability probe must only pass a ReAct turn that ends in an answer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.llm.scripted import ScriptedChatModel, tool_call

_spec = importlib.util.spec_from_file_location(
    "probe_llm", Path(__file__).parents[3] / "scripts" / "probe_llm.py"
)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

HISTORY = [HumanMessage("Fetch the data needed")]
FETCH = tool_call("fetch_singstat_series", {"table_id": "M182841", "series_no": "3.4"})


def test_tool_call_then_answer_passes():
    model = ScriptedChatModel(replies=[FETCH, AIMessage("Next I would compute the change over 2020-2024.")])
    out = probe.react_turn(model, HISTORY)
    assert out["tool_rounds"] == 1 and out["final_text"].startswith("Next I would")


def test_a_model_that_never_stops_calling_tools_fails():
    model = ScriptedChatModel(replies=[FETCH] * probe.MAX_REACT_ROUNDS)
    with pytest.raises(RuntimeError, match="no final answer after 3 tool rounds"):
        probe.react_turn(model, HISTORY)


def test_a_second_tool_call_is_answered_and_may_still_finish():
    model = ScriptedChatModel(replies=[FETCH, FETCH, AIMessage("Done: compute the change.")])
    assert probe.react_turn(model, HISTORY)["tool_rounds"] == 2


@pytest.mark.parametrize(
    "final",
    [
        AIMessage(""),
        AIMessage(content=[{"type": "reasoning_content", "reasoning_content": {"text": "private"}}]),
    ],
)
def test_empty_or_reasoning_only_reply_is_not_an_answer(final):
    with pytest.raises(RuntimeError, match="empty final answer"):
        probe.react_turn(ScriptedChatModel(replies=[FETCH, final]), HISTORY)


def test_answering_without_using_the_tool_fails():
    with pytest.raises(RuntimeError, match="without calling a tool"):
        probe.react_turn(ScriptedChatModel(replies=[AIMessage("I already know.")]), HISTORY)
