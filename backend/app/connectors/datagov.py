"""Data.gov.sg connector (dataset metadata + datastore JSON API)."""

from __future__ import annotations

from collections import defaultdict

from app.connectors.base import assemble
from app.connectors.catalog import DatasetEntry, FieldMap, PlatformInfo
from app.connectors.http import Fetcher, MinIntervalLimiter, RawPayload
from app.data.models import NormalizedDataset, QualityIssue, SeriesData
from app.data.periods import Period
from app.data.series import build_series
from app.data.taxonomy import Taxonomy

PAGE_RECORDS = 1000
# 4 datastore calls per 10 s without an API key.
_limiter = MinIntervalLimiter(min_interval_s=2.6)


def metadata_url(dataset_id: str) -> str:
    return f"https://api-production.data.gov.sg/v2/public/api/datasets/{dataset_id}/metadata"


def datastore_url(dataset_id: str, offset: int) -> str:
    return (
        f"https://data.gov.sg/api/action/datastore_search?resource_id={dataset_id}"
        f"&limit={PAGE_RECORDS}&offset={offset}"
    )


def _record_points(record: dict, fields: FieldMap) -> list[tuple[str, str]]:
    if fields.layout == "wide":
        return [(str(k), str(v)) for k, v in record.items() if _is_period(k)]
    assert fields.period and fields.value, "long layout needs period and value fields"
    return [(str(record[fields.period]), str(record[fields.value]))]


def _is_period(key: str) -> bool:
    try:
        Period.parse(key)
        return True
    except ValueError:
        return False


async def fetch_dataset(
    entry: DatasetEntry, platform: PlatformInfo, taxonomy: Taxonomy, fetcher: Fetcher
) -> NormalizedDataset:
    assert entry.fields is not None, f"{entry.id} needs a field map"
    fields = entry.fields
    meta_payload = await fetcher.get(metadata_url(entry.id), limiter=_limiter)
    meta = meta_payload.json_body().get("data", {})
    payloads: list[RawPayload] = [meta_payload]

    points: dict[str, list[tuple[str, str]]] = defaultdict(list)
    offset = 0
    while True:
        payload = await fetcher.get(
            datastore_url(entry.id, offset), limiter=_limiter, must_contain=b'"result"'
        )
        payloads.append(payload)
        result = payload.json_body()["result"]
        for record in result["records"]:
            points[record[fields.label]].extend(_record_points(record, fields))
        offset += len(result["records"])
        if not result["records"] or offset >= result["total"]:
            break

    series: list[SeriesData] = []
    issues: list[QualityIssue] = []
    for label, label_points in points.items():
        built, label_issues = build_series(
            entry, platform, taxonomy, source_ref=label, label=label, points=label_points
        )
        series.extend(built)
        issues.extend(label_issues)

    return assemble(
        entry,
        platform,
        taxonomy,
        payloads,
        series,
        issues,
        title=meta.get("name") or entry.title,
        source_updated_at=meta.get("lastUpdatedAt"),
        footnotes=meta.get("description"),
    )
