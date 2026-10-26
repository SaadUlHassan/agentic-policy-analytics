"""Exports of a finished analysis (plan FE-4): Markdown, a JSON bundle, and a CSV of the source
observations the findings rest on.

Everything is built from what was stored when the analysis finished: the report (which holds only
verified findings; drafts never reach it) and the pinned dataset artifacts. Nothing is recomputed or
regenerated, so an export always matches what the researcher saw.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.data.models import NormalizedDataset

EXPORT_VERSION = "1"
CSV_COLUMNS = (
    "dataset_id",
    "artifact_id",
    "series_key",
    "subject",
    "period",
    "value",
    "marker",
    "raw",
    "unit",
    "scale",
    "citation",
)


def _plan_periods(report: dict[str, Any]) -> tuple[int, int] | None:
    plan = report.get("plan") or {}
    start, end = plan.get("start_year"), plan.get("end_year")
    return (start, end) if start is not None and end is not None else None


def _citation_ids(report: dict[str, Any]) -> dict[str, str]:
    return {c["artifact_id"]: c["id"] for c in report.get("citations", [])}


def observation_rows(report: dict[str, Any], datasets: dict[str, NormalizedDataset]) -> list[dict[str, Any]]:
    """The stored observations of every selected series inside the plan window, exactly as parsed
    (value, source marker and the raw source text)."""
    window = _plan_periods(report)
    cited = _citation_ids(report)
    rows = []
    for selected in report.get("evidence", {}).get("selected", []):
        dataset = datasets.get(selected.get("artifact_id", "")) or next(
            (d for d in datasets.values() if d.dataset_id == selected["dataset_id"]), None
        )
        series = (
            next((s for s in dataset.series if s.key == selected["series_key"]), None) if dataset else None
        )
        if dataset is None or series is None or series.identity is None:
            continue
        for o in series.observations:
            if window and not window[0] <= int(o.period[:4]) <= window[1]:
                continue
            rows.append(
                {
                    "dataset_id": dataset.dataset_id,
                    "artifact_id": dataset.artifact_id,
                    "series_key": series.key,
                    "subject": series.identity.subject(),
                    "period": o.period,
                    "value": "" if o.value is None else o.value,
                    "marker": o.marker or "",
                    "raw": o.raw,
                    "unit": series.identity.unit,
                    "scale": series.identity.scale,
                    "citation": cited.get(dataset.artifact_id, ""),
                }
            )
    return rows


def to_csv(rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def to_bundle(
    analysis: dict[str, Any], report: dict[str, Any], datasets: dict[str, NormalizedDataset]
) -> dict[str, Any]:
    """Everything needed to audit the result: the analysis, the verified report and the pinned
    dataset versions (identity, provenance and raw payload hashes, not the data itself)."""
    return {
        "export_version": EXPORT_VERSION,
        "analysis": analysis,
        "report": report,
        "datasets": [
            {
                "artifact_id": d.artifact_id,
                "dataset_id": d.dataset_id,
                "title": d.provenance.title,
                "platform": d.provenance.platform,
                "origin_agency": d.provenance.origin_agency,
                "url_human": d.provenance.url_human,
                "url_api": d.provenance.url_api,
                "retrieved_at": d.provenance.retrieved_at.isoformat(),
                "source_updated_at": d.provenance.source_updated_at,
                "from_snapshot": d.provenance.from_snapshot,
                "raw_sha256": d.provenance.raw_sha256,
                "parser_version": d.parser_version,
                "taxonomy_version": d.taxonomy_version,
            }
            for d in datasets.values()
        ],
    }


def to_markdown(analysis: dict[str, Any], report: dict[str, Any]) -> str:
    lines = [f"# {report.get('title') or analysis['query']}", ""]
    lines += [f"**Question:** {analysis['query']}  ", f"**Status:** {analysis['status'].replace('_', ' ')}  "]
    if analysis.get("finished_at"):
        lines.append(f"**Finished:** {analysis['finished_at']}  ")
    lines.append("")
    if report.get("summary"):
        lines += [report["summary"], ""]

    lines += ["## Verified findings", ""]
    findings = report.get("findings", [])
    if not findings:
        lines.append("No finding passed verification.")
    for n, f in enumerate(findings, start=1):
        tag = " *(exploratory association)*" if f.get("kind") == "association" else ""
        refs = " ".join(f"[{c}]" for c in f.get("citations", []))
        lines.append(f"{n}. {f['text']}{tag} {refs}".rstrip())
    v = report.get("verification", {})
    lines += [
        "",
        f"_{v.get('claims_verified', 0)} of {v.get('claims_drafted', 0)} drafted findings passed the "
        "evidence checks; every number above was rendered from a stored computation._",
        "",
    ]

    if checks := report.get("consistency_checks"):
        lines += ["## Cross-platform consistency", ""]
        lines += [f"- {c['verdict']} ({', '.join(c['series'])})" for c in checks]
        lines.append("")

    if quality := report.get("data_quality"):
        lines += ["## Data quality", ""]
        for d in quality:
            problems = [c for c in d["checks"] if c["severity"] != "info"]
            role = "evidence" if d["role"] == "evidence" else "cross-check"
            lines.append(
                f"- **{d['dataset_id']}** ({d['platform']}, {role}): {len(problems)} warning(s) or error(s)"
            )
            lines += [f"  - {c['severity']}: {c['code']} {c['message']}" for c in problems]
            lines += [f"  - marker `{m['marker']}`: {m['meaning']} ({m['treatment']})" for m in d["markers"]]
        lines.append("")

    if limitations := report.get("limitations"):
        lines += ["## Limitations", ""]
        lines += [f"- {item['text']}" for item in limitations]
        lines.append("")

    lines += ["## Sources", ""]
    for c in report.get("citations", []):
        periods = f"{c['periods'][0]}–{c['periods'][-1]}" if c.get("periods") else ""
        lines.append(
            f"- [{c['id']}] {c['title']} ({c['dataset_id']}), {c['publisher']} via {c['platform']}; "
            f"originating agency {c['origin_agency']}; {periods}; retrieved {c['retrieved_at'][:10]}"
            f"{' from a stored snapshot' if c.get('from_snapshot') else ''}. {c['url_human']}  "
        )
        lines.append(f"  Dataset version `{c['artifact_id']}`")
    return "\n".join(lines).rstrip() + "\n"
