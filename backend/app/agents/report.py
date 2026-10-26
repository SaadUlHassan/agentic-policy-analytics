"""Final report assembly: verified claims, charts from source observations, derived limitations."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agents.evidence import ConsistencyCheck, EvidenceStore
from app.agents.plan import ResearchPlan
from app.agents.tools import plan_window
from app.analytics.results import Refusal
from app.grounding.checks import check_free_text
from app.grounding.citations import CitationIndex, EvidenceRef, claim_refs
from app.grounding.render import DISPLAY_ROUNDING_VERSION, render_claim

REPORT_VERSION = "1"


class ReportNarrative(BaseModel):
    title: str = Field(description="Short report title, no numbers")
    summary: str = Field(description="Two to three sentences, no numbers, no causes")
    limitations: list[str] = Field(default=[], description="Plain-language limitations, no numbers")


def _passes(text: str, allowed_periods: set[str]) -> bool:
    return all(c.passed for c in check_free_text(text, allowed_periods))


def build_report(
    plan: ResearchPlan, evidence: EvidenceStore, narrative: ReportNarrative | None, *, question: str
) -> dict[str, Any]:
    citations = CitationIndex(evidence.datasets)
    verified = evidence.verified_claims()
    allowed_periods = {
        p for c in verified for a in c.assertions.values() for p in (a.interval.start, a.interval.end)
    }

    findings = [
        {
            "id": c.id,
            "kind": c.kind,
            "text": render_claim(c, evidence.computations),
            "citations": citations.cite(claim_refs(c, evidence.computations)),
            "computations": sorted({a.computation_id for a in c.assertions.values()}),
        }
        for c in verified
    ]

    charts = _charts(plan, evidence, citations)
    coverage = _coverage(plan, evidence)
    consistency = [_consistency(c, evidence, citations) for c in evidence.consistency]
    limitations = _derived_limitations(evidence)
    # The fallback title is the researcher's own question: it is never generated text.
    title, summary, narrative_note = question, "", None
    if narrative is not None:
        kept = [
            t
            for t in [narrative.title, narrative.summary, *narrative.limitations]
            if _passes(t, allowed_periods)
        ]
        if narrative.title and narrative.title in kept:
            title = narrative.title
        if narrative.summary in kept:
            summary = narrative.summary
        limitations += [{"source": "coordinator", "text": t} for t in narrative.limitations if t in kept]
        removed = 2 + len(narrative.limitations) - len(kept)
        if removed:
            narrative_note = (
                f"{removed} narrative sentence(s) removed for containing unverified figures or causes"
            )
    else:
        narrative_note = "narrative unavailable; findings are shown as verified"

    drafted = len(evidence.claims)
    return {
        "version": REPORT_VERSION,
        "display_rounding_version": DISPLAY_ROUNDING_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "title": title,
        "summary": summary,
        "plan": plan.model_dump(),
        "findings": findings,
        "charts": charts,
        "consistency_checks": consistency,
        "coverage": coverage,
        "limitations": [
            *[
                {"source": "coverage", "text": f"No verified finding covers {gap['label']}."}
                for gap in coverage["uncovered"]
            ],
            *limitations,
        ],
        "citations": [c.model_dump(mode="json") for c in citations.citations()],
        "evidence": {
            "selected": [
                {
                    "series_key": k,
                    "dataset_id": s.source.dataset_id,
                    "subject": s.source.identity.subject(),
                    "reason": s.reason,
                }
                for k, s in evidence.selected.items()
            ],
            "rejected": [{"series_key": r.series_key, "reason": r.reason} for r in evidence.rejected],
            "refusals": [r.model_dump(mode="json") for r in evidence.refusals],
        },
        "verification": {
            "claims_drafted": drafted,
            "claims_verified": len(verified),
            "claims_rejected": drafted - len(verified),
            "narrative_note": narrative_note,
        },
    }


def _consistency(
    check: ConsistencyCheck, evidence: EvidenceStore, citations: CitationIndex
) -> dict[str, Any]:
    def ref(series_key: str, artifact_id: str) -> EvidenceRef:
        found = evidence.find_series(series_key)
        subject = found[1].identity.subject() if found and found[1].identity else series_key
        return EvidenceRef(artifact_id, subject, tuple(check.periods))

    return {
        "series": [check.series_a, check.series_b],
        "verdict": check.verdict,
        "periods_compared": len(check.periods),
        "mismatches": check.mismatches,
        "citations": citations.cite(
            [ref(check.series_a, check.artifact_a), ref(check.series_b, check.artifact_b)]
        ),
    }


def _coverage(plan: ResearchPlan, evidence: EvidenceStore) -> dict[str, Any]:
    """Which planned (sector, metric) pairs at least one verified finding actually answers."""
    covered = {
        (ref.identity.sector, ref.identity.metric)
        for claim in evidence.verified_claims()
        for a in claim.assertions.values()
        for ref in evidence.computations[a.computation_id].inputs
    }
    labels = {s.source.identity.sector: s.source.identity.sector_label for s in evidence.selected.values()}

    def label(sector: str, metric: str) -> str:
        return f"{metric.replace('_', ' ')} in {labels.get(sector, sector.replace('_', ' '))}"

    planned = [(s, m) for s in plan.sectors for m in plan.metrics] if plan.in_scope else []
    return {
        "planned": [label(s, m) for s, m in planned],
        "uncovered": [
            {"sector": s, "metric": m, "label": label(s, m)} for s, m in planned if (s, m) not in covered
        ],
    }


def _charts(plan: ResearchPlan, evidence: EvidenceStore, citations: CitationIndex) -> list[dict[str, Any]]:
    """One chart per (metric, frequency, unit); points are the source observations, never computed."""
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for key, sel in evidence.selected.items():
        identity = sel.source.identity
        window = set(plan_window(plan, identity.frequency))
        observed = [o for o in sel.series.observations if o.period in window]
        points = [{"period": o.period, "value": o.value} for o in observed]
        ref = EvidenceRef(sel.source.artifact_id, identity.subject(), tuple(o.period for o in observed))
        groups[(identity.metric, identity.frequency.value, identity.unit, identity.scale)].append(
            {
                "series_key": key,
                "label": identity.sector_label,
                "dataset_id": sel.source.dataset_id,
                "citation": citations.cite([ref])[0],
                "points": points,
            }
        )
    return [
        {
            "id": f"chart{n}",
            "metric": metric,
            "frequency": freq,
            "unit": unit,
            "scale": scale,
            "title": f"{metric.replace('_', ' ').capitalize()} ({freq})",
            "series": series,
        }
        for n, ((metric, freq, unit, scale), series) in enumerate(groups.items(), start=1)
    ]


def _refusal_text(refusal: Refusal, evidence: EvidenceStore) -> str:
    def name(series_key: str) -> str:
        found = evidence.find_series(series_key)
        identity = found[1].identity if found else None
        return f"{identity.subject()} ({identity.frequency})" if identity else series_key

    if refusal.other_series_key:
        other = name(refusal.other_series_key)
        return (
            f"{name(refusal.series_key)} and {other[:1].lower() + other[1:]} were not correlated: "
            f"{refusal.code} ({refusal.detail})"
        )
    return f"{refusal.tool} on {name(refusal.series_key)} was not computed: {refusal.code} ({refusal.detail})"


def _derived_limitations(evidence: EvidenceStore) -> list[dict[str, str]]:
    out = [{"source": "analysis", "text": _refusal_text(r, evidence)} for r in evidence.refusals]
    rejected = len(evidence.claims) - len(evidence.verified_claims())
    if rejected:
        out.append(
            {
                "source": "verification",
                "text": f"{rejected} draft finding(s) failed evidence checks and were removed",
            }
        )
    selected_keys = set(evidence.selected)
    for dataset in evidence.datasets.values():
        if not any(s.key in selected_keys for s in dataset.series):
            continue
        for issue in dataset.quality:
            # Issues raised before regime splitting are keyed without the "@scheme" suffix.
            relevant = issue.series_key is None or any(
                k == issue.series_key or k.startswith(f"{issue.series_key}@") for k in selected_keys
            )
            if relevant and (issue.severity != "info" or issue.code == "SERVED_FROM_SNAPSHOT"):
                out.append({"source": "data", "text": f"{dataset.dataset_id}: {issue.message}"})
    return out
