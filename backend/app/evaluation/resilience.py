"""Provider-resilience scenarios (plan §4.7, §8.3): real providers switched off with the fault
switches, at the start of a run or once its first finding is verified, and the behaviour checked
against what §4.7 promises for that case."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.core.faults import INJECTED
from app.db.models import AnalysisStatus
from app.evaluation.harness import RunResult, RunSpec
from app.evaluation.scoring import COMPLETED, Stored, check_retained

Check = Callable[[Stored, RunResult], list[str]]


@dataclass(frozen=True)
class Scenario:
    name: str
    expected: str
    spec: RunSpec | None
    check: Check | None = None
    not_applicable: str | None = None


def _finished_with_findings(stored: Stored) -> list[str]:
    problems = [] if stored.analysis.status in COMPLETED else [f"status {stored.analysis.status}"]
    if not (stored.report or {}).get("findings"):
        problems.append("no verified findings")
    return problems + check_retained(stored)


def _fallback_events(stored: Stored, primary: str, after_seq: int = 0) -> list[str]:
    return [
        e.title
        for e in stored.events
        if e.type == "provider_fallback" and e.seq > after_seq and e.detail.get("from") == primary
    ]


def _all_answered_by(provider: str, primary: str) -> Check:
    def check(stored: Stored, _: RunResult) -> list[str]:
        problems = _finished_with_findings(stored)
        if others := {c.provider for c in stored.calls if c.ok} - {provider}:
            problems.append(f"calls answered by {sorted(others)}")
        if not any(INJECTED in t for t in _fallback_events(stored, primary)):
            problems.append(f"no fallback event naming the injected {primary} fault")
        if any(INJECTED not in (c.error or "") for c in stored.calls if c.provider == primary):
            problems.append(f"a {primary} failure is not recorded as injected")
        return problems

    return check


def _verifier_unavailable(stored: Stored, _: RunResult) -> list[str]:
    problems = _finished_with_findings(stored)
    check = (stored.report or {}).get("verification", {}).get("narrative_check")
    if not check or check["independent"]:
        problems.append(f"narrative check recorded as {check}")
    if not any("not independent" in lim["text"] for lim in (stored.report or {}).get("limitations", [])):
        problems.append("no limitation disclosing the dependent check")
    return problems


def _primary_lost_mid_run(stored: Stored, result: RunResult) -> list[str]:
    problems = _finished_with_findings(stored)
    if result.late_faults_after_seq is None:
        return [*problems, "the fault was never switched on (no finding verified)"]
    if not any(c.ok and c.provider == "bedrock" for c in stored.calls):
        problems.append("bedrock answered nothing before the fault")
    if not _fallback_events(stored, "bedrock", result.late_faults_after_seq):
        problems.append("no fallback after the fault")
    return problems


def _outage_early(stored: Stored, _: RunResult) -> list[str]:
    problems = []
    if stored.analysis.status != AnalysisStatus.FAILED:
        problems.append(f"status {stored.analysis.status}")
    if (stored.analysis.error or {}).get("code") != "LLM_UNAVAILABLE":
        problems.append(f"error {stored.analysis.error}")
    if stored.report is not None or stored.analysis.plan is not None:
        problems.append("a plan or report exists although no model answered")
    return problems


def _outage_late(stored: Stored, result: RunResult) -> list[str]:
    problems = _finished_with_findings(stored)
    report = stored.report or {}
    if result.late_faults_after_seq is None:
        problems.append("the faults were never switched on (no finding verified)")
    if stored.analysis.status != AnalysisStatus.COMPLETED_WITH_LIMITATIONS:
        problems.append("not reported as completed with limitations")
    if not report.get("verification", {}).get("narrative_note", "").startswith("narrative unavailable"):
        problems.append("narrative not disclosed as unavailable")
    # And actually absent: no generated title, summary or limitations, and nothing was judged.
    if report.get("summary") or report.get("title") != stored.analysis.query:
        problems.append("the report still carries a generated title or summary")
    if any(lim["source"] == "coordinator" for lim in report.get("limitations", [])):
        problems.append("the report still carries generated limitations")
    if "narrative_check" in report.get("verification", {}):
        problems.append("a narrative check is recorded although no narrative was written")
    if not any("LLM_UNAVAILABLE" in lim["text"] for lim in report.get("limitations", [])):
        problems.append("early stop not disclosed")
    return problems


def scenarios(query: str) -> list[Scenario]:
    both = ("llm:bedrock", "llm:openai")
    return [
        Scenario(
            "fallback_bedrock_to_openai",
            "Bedrock switched off: every call answered by OpenAI, each fallback disclosed as injected",
            RunSpec(query, ("bedrock", "openai"), faults=("llm:bedrock",)),
            _all_answered_by("openai", "bedrock"),
        ),
        Scenario(
            "fallback_openai_to_bedrock",
            "OpenAI primary and switched off: every call answered by Bedrock",
            RunSpec(query, ("openai", "bedrock"), faults=("llm:openai",)),
            _all_answered_by("bedrock", "openai"),
        ),
        Scenario(
            "verifier_provider_unavailable",
            "The judge's provider is down: the check runs on the writer's provider and is disclosed "
            "as not independent",
            RunSpec(query, ("bedrock", "openai"), faults=("llm:openai",)),
            _verifier_unavailable,
        ),
        Scenario(
            "primary_lost_mid_run",
            "Bedrock lost after the first verified finding: the run continues on OpenAI",
            RunSpec(query, ("bedrock", "openai"), late_faults=("llm:bedrock",)),
            _primary_lost_mid_run,
        ),
        Scenario(
            "total_outage_early",
            "Both providers down from the start: failed with LLM_UNAVAILABLE, no plan, no report",
            RunSpec(query, ("bedrock", "openai"), faults=both),
            _outage_early,
        ),
        Scenario(
            "total_outage_late",
            "Both providers lost after verified findings exist: completed with limitations, the "
            "verified findings without narrative, the early stop disclosed",
            RunSpec(query, ("bedrock", "openai"), late_faults=both),
            _outage_late,
        ),
        Scenario(
            "partial_stream_failure",
            "A provider failing mid-stream leaves no duplicated text",
            None,
            not_applicable="Model output is not streamed: every call returns a complete reply or "
            "fails, and only verified results are published (draft streaming, enhancement 5, is not built).",
        ),
    ]
