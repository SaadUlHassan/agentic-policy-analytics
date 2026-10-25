"""Per-analysis dependencies handed to graph nodes through LangGraph's runtime context."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.evidence import EvidenceStore
from app.agents.plan import ResearchPlan
from app.analytics.tools import Toolkit
from app.connectors.catalog import Catalog
from app.connectors.http import Fetcher
from app.data.taxonomy import Taxonomy
from app.jobs.lifecycle import AnalysisCancelled
from app.jobs.writer import FencedWriter
from app.llm.router import LLMRouter


@dataclass
class AgentContext:
    router: LLMRouter
    writer: FencedWriter
    catalog: Catalog
    taxonomy: Taxonomy
    fetcher: Fetcher
    deadline: float  # time.monotonic() value after which no new LLM call starts
    evidence: EvidenceStore = field(default_factory=EvidenceStore)
    plan: ResearchPlan | None = None

    async def check_cancel(self) -> None:
        """Called between steps: a cancel request stops the run at the next boundary."""
        if await self.writer.cancel_requested():
            raise AnalysisCancelled()

    @property
    def toolkit(self) -> Toolkit:
        return Toolkit(self.taxonomy.version)
