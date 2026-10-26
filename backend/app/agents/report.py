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
from app.connectors.catalog import get_catalog
from app.data.models import NormalizedDataset, QualityIssue
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
        "data_quality": _data_quality(evidence),
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
                    "artifact_id": s.source.artifact_id,
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
        "comparable": check.not_comparable is None,
        "periods_compared": len(check.periods),
        "mismatches": check.mismatches,
        # Nothing was compared when the check was refused, so there is nothing to cite.
        "citations": citations.cite(
            [ref(check.series_a, check.artifact_a), ref(check.series_b, check.artifact_b)]
        )
        if check.not_comparable is None
        else [],
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


def _finding_caveats(evidence: EvidenceStore) -> list[dict[str, str]]:
    """Caveats of the computations behind retained findings (e.g. a correlation between series that
    count different populations). Added deterministically: the narrative may not mention them."""
    out: list[dict[str, str]] = []
    for claim in evidence.verified_claims():
        for assertion in claim.assertions.values():
            computation = evidence.computations[assertion.computation_id]
            names = [i.identity.subject() for i in computation.inputs]
            subjects = " and ".join([names[0], *(n[:1].lower() + n[1:] for n in names[1:])])
            for caveat in computation.caveats:
                item = {"source": "analysis", "text": f"{subjects}: {caveat}"}
                if item not in out:
                    out.append(item)
    return out


def _derived_limitations(evidence: EvidenceStore) -> list[dict[str, str]]:
    out = [{"source": "analysis", "text": _refusal_text(r, evidence)} for r in evidence.refusals]
    out += _finding_caveats(evidence)
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
        for issue in _relevant_issues(dataset, selected_keys):
            if issue.severity != "info" or issue.code == "SERVED_FROM_SNAPSHOT":
                out.append({"source": "data", "text": f"{dataset.dataset_id}: {issue.message}"})
    return out


def _relevant_issues(dataset: NormalizedDataset, keys: set[str]) -> list[QualityIssue]:
    """Dataset-wide issues, and issues about the given series. Issues raised before regime
    splitting are keyed without the "@scheme" suffix."""
    return [
        i
        for i in dataset.quality
        if i.series_key is None or any(k == i.series_key or k.startswith(f"{i.series_key}@") for k in keys)
    ]


def _data_quality(evidence: EvidenceStore) -> list[dict[str, Any]]:
    """What was checked on each dataset the report relies on, and what was found (plan GD-4): the
    datasets of selected series ("evidence") and the republications they were cross-checked against
    ("cross-check"), including cross-checks that were refused. A dataset can play both roles: its
    checks cover every series of it that the report relied on either way. Marker meanings are the
    ones the fetched source states (e.g. a workbook's legend), else the reviewed manifest's."""
    selected = set(evidence.selected)
    compared = {k for c in evidence.consistency for k in (c.series_a, c.series_b)}
    platforms = get_catalog().platforms
    out = []
    for dataset in evidence.datasets.values():
        used = {s.key for s in dataset.series if s.key in selected}
        keys = used | {s.key for s in dataset.series if s.key in compared}
        if not keys:
            continue
        markers: dict[str, int] = defaultdict(int)
        for series in dataset.series:
            if series.key in keys:
                for o in series.observations:
                    if o.marker is not None:
                        markers[o.raw] += 1
        reviewed = {m: spec.meaning for m, spec in platforms[dataset.provenance.platform].markers.items()}
        legend = {**reviewed, **dataset.source_metadata.get("legend", {})}
        out.append(
            {
                "dataset_id": dataset.dataset_id,
                "title": dataset.provenance.title,
                "platform": dataset.provenance.platform,
                "role": "evidence" if used else "cross-check",
                "series": sorted(keys),
                "from_snapshot": dataset.provenance.from_snapshot,
                "retrieved_at": dataset.provenance.retrieved_at.isoformat(),
                "checks": [
                    {"code": i.code, "severity": i.severity, "message": i.message, "count": i.count}
                    for i in _relevant_issues(dataset, keys)
                ],
                "markers": [
                    {
                        "marker": raw,
                        "count": n,
                        "meaning": legend.get(raw, "not defined by the source"),
                        "treatment": "set to null and excluded from calculations",
                    }
                    for raw, n in sorted(markers.items())
                ],
            }
        )
    return out
