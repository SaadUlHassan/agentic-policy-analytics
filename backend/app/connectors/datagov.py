"""Data.gov.sg connector: dataset metadata, then the CSV download or the datastore JSON API.

The CSV download is preferred where the catalogue lists one: one rate-limited request for the
whole file instead of one per 1000 records. The datastore is the fallback. Both carry the same
records as text, so either path yields the same normalised dataset.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

import pandas as pd

from app.connectors.base import assemble
from app.connectors.catalog import DatasetEntry, FieldMap, PlatformInfo
from app.connectors.http import Fetcher, RawPayload, SourceSchemaError, SourceUnavailable
from app.connectors.ratelimit import RateLimit
from app.connectors.tabular import read_csv, records_frame, require_columns
from app.data.models import NormalizedDataset, QualityIssue, SeriesData, Severity
from app.data.periods import Period
from app.data.series import build_series
from app.data.taxonomy import Taxonomy

PAGE_RECORDS = 1000
# Published per 10 s (guide.data.gov.sg, "API Rate Limits"); the metadata API is spaced like search.
DATASTORE = RateLimit("datagov-datastore", 10, {"none": 4, "dev": 8, "prod": 20})
DOWNLOADS = RateLimit("datagov-downloads", 10, {"none": 2, "dev": 4, "prod": 10})
DOWNLOAD_POLLS = 6
DOWNLOAD_POLL_WAIT_S = 2.0
OPEN_API = "https://api-open.data.gov.sg/v1/public/api/datasets"


def metadata_url(dataset_id: str) -> str:
    return f"https://api-production.data.gov.sg/v2/public/api/datasets/{dataset_id}/metadata"


def datastore_url(dataset_id: str, offset: int) -> str:
    return (
        f"https://data.gov.sg/api/action/datastore_search?resource_id={dataset_id}"
        f"&limit={PAGE_RECORDS}&offset={offset}"
    )


def download_url(dataset_id: str) -> str:
    """Stable identity of a dataset's CSV download (the file itself sits behind a pre-signed URL)."""
    return f"{OPEN_API}/{dataset_id}/poll-download"


def _columns(fields: FieldMap) -> list[str]:
    if fields.layout == "wide":
        return [fields.label]
    assert fields.period and fields.value, "long layout needs period and value fields"
    return [fields.label, fields.period, fields.value]


def _points(frame: pd.DataFrame, fields: FieldMap) -> dict[str, list[tuple[str, str]]]:
    points: dict[str, list[tuple[str, str]]] = defaultdict(list)
    if fields.layout == "wide":
        periods = [c for c in frame.columns if _is_period(str(c))]
        for record in frame.to_dict("records"):
            points[record[fields.label]].extend((str(p), str(record[p])) for p in periods)
        return points
    assert fields.period and fields.value
    for label, period, value in frame[[fields.label, fields.period, fields.value]].itertuples(index=False):
        points[label].append((str(period), str(value)))
    return points


def _is_period(key: str) -> bool:
    try:
        Period.parse(key)
        return True
    except ValueError:
        return False


async def _download_csv(dataset_id: str, fetcher: Fetcher) -> RawPayload:
    async def signed_location() -> str:
        await fetcher.call(f"{OPEN_API}/{dataset_id}/initiate-download", rate=DOWNLOADS)
        for attempt in range(DOWNLOAD_POLLS):
            if attempt:
                await asyncio.sleep(DOWNLOAD_POLL_WAIT_S)
            poll = await fetcher.call(download_url(dataset_id), rate=DOWNLOADS)
            try:
                data = poll.json_body().get("data", {})
            except ValueError as exc:
                raise SourceUnavailable(download_url(dataset_id), "download status was not JSON") from exc
            if data.get("status") == "DOWNLOAD_SUCCESS" and data.get("url"):
                return str(data["url"])
        raise SourceUnavailable(download_url(dataset_id), "download was not ready in time")

    return await fetcher.get_resolved(download_url(dataset_id), signed_location)


async def _datastore(dataset_id: str, fetcher: Fetcher) -> tuple[pd.DataFrame, list[RawPayload]]:
    payloads: list[RawPayload] = []
    records: list[dict] = []
    while True:
        payload = await fetcher.get(
            datastore_url(dataset_id, len(records)), rate=DATASTORE, must_contain=b'"result"'
        )
        payloads.append(payload)
        result = payload.json_body()["result"]
        records.extend(result["records"])
        if not result["records"] or len(records) >= result["total"]:
            return records_frame(records), payloads


async def fetch_dataset(
    entry: DatasetEntry, platform: PlatformInfo, taxonomy: Taxonomy, fetcher: Fetcher
) -> NormalizedDataset:
    assert entry.fields is not None, f"{entry.id} needs a field map"
    fields = entry.fields
    meta_payload = await fetcher.get(metadata_url(entry.id), rate=DATASTORE)
    meta = meta_payload.json_body().get("data", {})
    payloads: list[RawPayload] = [meta_payload]
    issues: list[QualityIssue] = []

    frame: pd.DataFrame | None = None
    if "csv_download" in entry.formats:
        try:
            csv = await _download_csv(entry.id, fetcher)
            frame = require_columns(read_csv(csv), _columns(fields), csv.url)
            payloads.append(csv)
        except (SourceUnavailable, SourceSchemaError) as exc:
            reason = exc.reason if isinstance(exc, SourceUnavailable) else exc.problem
            issues.append(
                QualityIssue(
                    code="FORMAT_FALLBACK",
                    severity=Severity.INFO,
                    message=f"CSV download unusable ({reason}); records read from the datastore API",
                )
            )
    if frame is None:
        frame, pages = await _datastore(entry.id, fetcher)
        payloads.extend(pages)
        frame = require_columns(frame, _columns(fields), pages[0].url)

    series: list[SeriesData] = []
    for label, label_points in _points(frame, fields).items():
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
