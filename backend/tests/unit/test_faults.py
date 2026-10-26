"""Fault injection (plan §2, §9.2): switches take effect only when enabled, and an injected failure
is reported as injected wherever the real failure would be."""

from __future__ import annotations

import pytest
import respx
from langchain_core.messages import AIMessage, HumanMessage

from app.connectors import singstat
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.connectors.registry import fetch
from app.core.config import Settings
from app.core.faults import Faults, source_fault
from app.data.taxonomy import get_taxonomy
from app.llm.router import LLMRouter
from app.llm.scripted import ScriptedChatModel
from tests.unit.connectors.test_connectors import Unthrottled


class Switched(Faults):
    """A switchboard with the given faults on, without Redis."""

    def __init__(self, *on: str) -> None:
        self.on = set(on)

    async def active(self, name: str) -> bool:
        return name in self.on


def test_sources_are_recognised_by_host():
    assert source_fault(singstat.tabledata_url("M182841", 0)) == "source:singstat"
    assert (
        source_fault("https://api-open.data.gov.sg/v1/public/api/datasets/x/poll-download")
        == "source:datagov"
    )
    assert source_fault("https://stats.mom.gov.sg/iMAS_Tables1/x.xlsx") == "source:mom"
    assert source_fault("https://s3.amazonaws.com/bucket/file.csv") is None


async def test_a_disabled_switchboard_never_reports_a_fault():
    assert not await Faults(object(), enabled=False).active("llm:bedrock")  # type: ignore[arg-type]


@pytest.mark.parametrize(("off", "answers"), [("llm:bedrock", "openai"), ("llm:openai", "bedrock")])
async def test_switching_a_provider_off_falls_back_to_the_other_in_both_directions(off, answers):
    records = []

    async def record(r):
        records.append(r)

    models = {p: ScriptedChatModel(replies=[AIMessage(content=f"from {p}")]) for p in ("bedrock", "openai")}
    router = LLMRouter(
        settings=Settings(_env_file=None), models=models, on_record=record, backoff_s=0, faults=Switched(off)
    )
    order = ["bedrock", "openai"] if off == "llm:bedrock" else ["openai", "bedrock"]
    router.settings.llm_provider_order = order

    reply = await router.step([HumanMessage("hi")], [], agent="coordinator", purpose="test")

    assert reply.content == f"from {answers}"
    failed = records[0]
    assert not failed.ok and "injected fault (demo)" in failed.error
    assert records[-1].ok and records[-1].fallback_from == off.removeprefix("llm:")
    assert router.answered_by == {"test": [answers]}


@respx.mock
async def test_a_switched_off_source_is_served_from_its_snapshot_and_says_why():
    route = respx.get(singstat.tabledata_url("M182841", 0))
    fetcher = Fetcher(
        mode="live",
        snapshots=get_snapshot_store(),
        backoff_s=0,
        limiter=Unthrottled(),
        faults=Switched("source:singstat"),
    )

    ds = await fetch("M182841", get_catalog(), get_taxonomy(), fetcher)

    assert not route.called, "no request reaches a switched-off source"
    disclosure = next(i for i in ds.quality if i.code == "SERVED_FROM_SNAPSHOT")
    assert "source:singstat switched off (injected fault (demo))" in disclosure.message
    assert disclosure.severity == "warning"
