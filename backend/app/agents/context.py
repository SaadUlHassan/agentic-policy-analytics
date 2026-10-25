"""Per-analysis dependencies handed to graph nodes through LangGraph's runtime context."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.evidence import EvidenceStore
from app.agents.plan import ResearchPlan
from app.analytics.tools import Toolkit
from app.connectors.catalog import Catalog
from app.connectors.http import Fetcher
from app.data.taxonomy import Taxonomy
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

    @property
    def toolkit(self) -> Toolkit:
        return Toolkit(self.taxonomy.version)
