"""Deterministic chat model double for tests and offline load runs. Never used for real analyses."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

Reply = AIMessage | Exception | Callable[[list[BaseMessage]], AIMessage]


class ScriptedChatModel(BaseChatModel):
    """Plays back a fixed list of replies. A reply may be a message, an exception to raise, or a
    function of the conversation so far. Tool binding is recorded but does not change replies."""

    replies: list[Any] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        self.bound_tools = list(tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        if not self.replies:
            raise AssertionError("ScriptedChatModel ran out of replies")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        message = reply(list(messages)) if callable(reply) else reply
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, args: dict[str, Any], call_id: str = "call_1", text: str = "") -> AIMessage:
    return AIMessage(
        content=text, tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}]
    )
