from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.connectors import datagov, singstat
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, SnapshotStore, SourceUnavailable, get_snapshot_store
from app.connectors.registry import UnknownDataset, fetch
from app.data.taxonomy import get_taxonomy

CATALOG = get_catalog()
TAXONOMY = get_taxonomy()
VACANCIES_Q = "d_3f17bbf67d31d4d402caa8755eb74afc"


def _singstat_page(rows):
    return {"Data": {"title": "Employment", "footnote": "fn", "dataLastUpdated": "01/01/2026", "row": rows}}


def _row(series_no, label, cols, uom="Thousand"):
    return {
        "seriesNo": series_no,
        "rowText": label,
        "uoM": uom,
        "columns": [{"key": k, "value": v} for k, v in cols],
    }


def _live(tmp_path, **kw):
    return Fetcher(mode="live", snapshots=SnapshotStore(tmp_path), backoff_s=0, **kw)


@respx.mock
async def test_singstat_merges_a_series_split_across_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(singstat, "PAGE_POINTS", 3)
    page1 = _singstat_page(
        [
            _row("3.3", "Accommodation And Food Services", [("2020", "1")]),
            _row("3.4", "Information And Communications", [("2020", "157.6"), ("2021", "165.0")]),
        ]
    )
    page2 = _singstat_page([_row("3.4", "Information And Communications", [("2022", "176.4")])])
    respx.get(singstat.tabledata_url("M182841", 0)).respond(json=page1)
    respx.get(singstat.tabledata_url("M182841", 3)).respond(json=page2)

    ds = await fetch("M182841", CATALOG, TAXONOMY, _live(tmp_path))

    (ict,) = ds.find("info_comms")
    assert [(o.period, o.value) for o in ict.observations] == [
        ("2020", 157.6),
        ("2021", 165.0),
        ("2022", 176.4),
    ]
    assert len(ds.provenance.url_api) == 2


@respx.mock
async def test_singstat_retries_on_429_then_succeeds(tmp_path):
    ok = _singstat_page([_row("3.4", "Information And Communications", [("2024", "180.3")])])
    route = respx.get(singstat.tabledata_url("M182841", 0))
    route.side_effect = [httpx.Response(429), httpx.Response(200, json=ok)]

    ds = await fetch("M182841", CATALOG, TAXONOMY, _live(tmp_path))

    assert route.call_count == 2
    assert ds.find("info_comms")[0].observations[0].value == 180.3
    assert not ds.provenance.from_snapshot


@respx.mock
async def test_outage_falls_back_to_snapshot_and_discloses_it():
    respx.get(singstat.tabledata_url("M182841", 0)).respond(503)
    fetcher = Fetcher(mode="live", snapshots=get_snapshot_store(), backoff_s=0)

    ds = await fetch("M182841", CATALOG, TAXONOMY, fetcher)

    assert ds.provenance.from_snapshot
    disclosure = next(i for i in ds.quality if i.code == "SERVED_FROM_SNAPSHOT")
    assert disclosure.severity == "warning" and "HTTP 503" in disclosure.message


@respx.mock
async def test_outage_without_snapshot_raises_source_unavailable(tmp_path):
    respx.get(singstat.tabledata_url("M182841", 0)).mock(side_effect=httpx.ConnectTimeout("boom"))
    with pytest.raises(SourceUnavailable, match="ConnectTimeout"):
        await fetch("M182841", CATALOG, TAXONOMY, _live(tmp_path))


@respx.mock
async def test_unit_disagreeing_with_catalogue_is_an_error_issue(tmp_path):
    page = _singstat_page([_row("3.4", "Information And Communications", [("2024", "180300")], uom="Number")])
    respx.get(singstat.tabledata_url("M182841", 0)).respond(json=page)
    ds = await fetch("M182841", CATALOG, TAXONOMY, _live(tmp_path))
    assert any(i.code == "UNIT_MISMATCH" and i.severity == "error" for i in ds.quality)


@respx.mock
async def test_datagov_pages_until_total_and_retries_throttled_body(tmp_path, monkeypatch):
    monkeypatch.setattr(datagov, "PAGE_RECORDS", 2)
    monkeypatch.setattr(datagov._limiter, "min_interval_s", 0)
    rec = lambda q, v: {"quarter": q, "industry": "information and communications", "job_vacancy": v}  # noqa: E731
    respx.get(datagov.metadata_url(VACANCIES_Q)).respond(
        json={"data": {"name": "JV", "lastUpdatedAt": "2026"}}
    )
    first = respx.get(datagov.datastore_url(VACANCIES_Q, 0))
    first.side_effect = [
        httpx.Response(200, json={"code": 24, "errorMsg": "rate limited"}),  # observed throttle shape
        httpx.Response(
            200, json={"result": {"total": 3, "records": [rec("2024-Q1", "7300"), rec("2024-Q2", "6500")]}}
        ),
    ]
    respx.get(datagov.datastore_url(VACANCIES_Q, 2)).respond(
        json={"result": {"total": 3, "records": [rec("2024-Q3", "-")]}}
    )

    ds = await fetch(VACANCIES_Q, CATALOG, TAXONOMY, _live(tmp_path))

    (ict,) = ds.find("info_comms")
    assert [(o.period, o.value) for o in ict.observations] == [
        ("2024-Q1", 7300.0),
        ("2024-Q2", 6500.0),
        ("2024-Q3", None),
    ]
    assert first.call_count == 2


async def test_uncatalogued_dataset_is_refused():
    with pytest.raises(UnknownDataset):
        await fetch("mrsd_4_annl_emp_chg_by_ind", CATALOG, TAXONOMY, _live_snapshot())


def _live_snapshot():
    return Fetcher(mode="snapshot", snapshots=get_snapshot_store())


async def test_real_snapshots_reproduce_published_ict_values():
    employment = await fetch("M182841", CATALOG, TAXONOMY, _live_snapshot())
    vacancies_singstat = await fetch("M184071", CATALOG, TAXONOMY, _live_snapshot())
    vacancies_datagov = await fetch(VACANCIES_Q, CATALOG, TAXONOMY, _live_snapshot())

    (emp,) = employment.find("info_comms")
    assert emp.identity.scale == 1000 and emp.identity.metric == "employment_level"
    assert emp.value_map()["2024"].value == 180.3

    sg, dg = vacancies_singstat.find("info_comms")[0], vacancies_datagov.find("info_comms")[0]
    window = [f"{y}-Q{q}" for y in range(2020, 2025) for q in range(1, 5)]
    assert [sg.value_map()[p].value for p in window] == [dg.value_map()[p].value for p in window]
    assert vacancies_singstat.find("it_info_services"), "child sector kept separately"


async def test_artifact_identity_ignores_raw_bytes_but_tracks_content():
    a = await fetch("M182841", CATALOG, TAXONOMY, _live_snapshot())
    stamped = a.model_copy(
        update={"provenance": a.provenance.model_copy(update={"raw_sha256": ["different"]})}
    )
    assert stamped.with_artifact_id().artifact_id == a.artifact_id
    changed = json.loads(a.model_dump_json())
    changed["series"][0]["observations"][0]["value"] = 1.0
    assert type(a).model_validate(changed).with_artifact_id().artifact_id != a.artifact_id
