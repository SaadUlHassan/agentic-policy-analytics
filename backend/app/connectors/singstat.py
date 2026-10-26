"""SingStat Table Builder connector (JSON REST API, no key)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.connectors.base import assemble
from app.connectors.catalog import DatasetEntry, PlatformInfo
from app.connectors.http import Fetcher, RawPayload
from app.data.models import NormalizedDataset, QualityIssue, SeriesData, Severity
from app.data.series import build_series
from app.data.taxonomy import Taxonomy

PAGE_POINTS = 5000  # the server caps every response at this many data points, whatever `limit` says

# A source unit of measure tells us the scale (and that a rate is a percentage), not what is counted.
_UOM_SCALES = {"thousand": 1000, "number": 1, "per cent": 1}


def tabledata_url(table_id: str, offset: int) -> str:
    return f"https://tablebuilder.singstat.gov.sg/api/table/tabledata/{table_id}?limit={PAGE_POINTS}&offset={offset}"


@dataclass
class _Row:
    label: str
    uom: str | None
    columns: list[tuple[str, str]] = field(default_factory=list)


async def fetch_table(
    entry: DatasetEntry, platform: PlatformInfo, taxonomy: Taxonomy, fetcher: Fetcher
) -> NormalizedDataset:
    payloads: list[RawPayload] = []
    rows: dict[str, _Row] = {}
    offset = 0
    while True:
        payload = await fetcher.get(tabledata_url(entry.id, offset))
        payloads.append(payload)
        data = payload.json_body()["Data"]
        points = 0
        for r in data["row"]:
            # Paging splits a series across responses; fragments share the seriesNo.
            row = rows.setdefault(r["seriesNo"], _Row(r["rowText"], r.get("uoM")))
            row.columns.extend((c["key"], c["value"]) for c in r["columns"])
            points += len(r["columns"])
        if points < PAGE_POINTS:
            break
        offset += points

    first = payloads[0].json_body()["Data"]
    series: list[SeriesData] = []
    issues: list[QualityIssue] = []
    for series_no, row in rows.items():
        built, row_issues = build_series(
            entry, platform, taxonomy, source_ref=series_no, label=row.label, points=row.columns
        )
        series.extend(built)
        issues.extend(row_issues)
        if (unit_issue := _unit_issue(entry, series_no, row.uom)) is not None:
            issues.append(unit_issue)

    return assemble(
        entry,
        platform,
        taxonomy,
        payloads,
        series,
        issues,
        title=first.get("title") or entry.title,
        source_updated_at=first.get("dataLastUpdated"),
        footnotes=first.get("footnote"),
        source_metadata={"units": {series_no: row.uom for series_no, row in rows.items()}},
    )


def _unit_issue(entry: DatasetEntry, series_no: str, uom: str | None) -> QualityIssue | None:
    text = (uom or "").strip().lower()
    if text not in _UOM_SCALES:
        return None
    consistent = _UOM_SCALES[text] == entry.scale and (text == "per cent") == (entry.unit == "percent")
    if consistent:
        return None
    return QualityIssue(
        code="UNIT_MISMATCH",
        severity=Severity.ERROR,
        series_key=f"{entry.id}:{series_no}",
        message=f"source unit {uom!r} disagrees with catalogue {entry.unit} x{entry.scale}",
    )
