"""Live-mode behaviour of the MOM and Data.gov.sg file paths, against recorded real payloads."""

from __future__ import annotations

import httpx
import pytest
import redis.asyncio as redis
import respx
from pydantic import SecretStr

from app.connectors import datagov, mom
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, SnapshotStore, api_keys, get_snapshot_store
from app.connectors.ratelimit import RateLimit, SharedRateLimiter
from app.connectors.registry import fetch
from app.core.config import Settings
from app.data.taxonomy import get_taxonomy
from tests.unit.connectors.test_connectors import Unthrottled

CATALOG = get_catalog()
TAXONOMY = get_taxonomy()
SNAPSHOTS = get_snapshot_store()
MOM_Q = "mrsd_3_qtly_emp_chg_by_ind"
VACANCIES_Q = "d_3f17bbf67d31d4d402caa8755eb74afc"
BASE = "https://stats.mom.gov.sg/iMAS_Tables1"


def _body(url: str) -> bytes:
    payload = SNAPSHOTS.load(url)
    assert payload is not None, url
    return payload.body


def _fetcher(tmp_path, **kw) -> Fetcher:
    return Fetcher(mode="live", snapshots=SnapshotStore(tmp_path), backoff_s=0, limiter=Unthrottled(), **kw)


def _index(*names: str) -> str:
    links = "".join(f'<a href="/iMAS_Tables1/Time-Series-Table/{n}">x</a>' for n in names)
    return f"<html><body>{links}</body></html>"


@respx.mock
async def test_mom_discovery_picks_the_newest_release_on_the_index_page(tmp_path):
    newest = f"{MOM_Q}_21092026.xlsx"
    respx.get(mom.INDEX_URL).respond(text=_index(f"{MOM_Q}_20062026.xlsx", newest, "other_01012027.xlsx"))
    route = respx.get(f"{BASE}/Time-Series-Table/{newest}").respond(
        content=_body(CATALOG.get(MOM_Q).last_known["xlsx"])
    )

    ds = await fetch(MOM_Q, CATALOG, TAXONOMY, _fetcher(tmp_path))

    assert route.called and ds.provenance.source_updated_at == "2026-09-21"
    assert "DISCOVERY_FALLBACK" not in {i.code for i in ds.quality}
    (ict,) = ds.find("info_comms")
    assert ict.identity.scale == 1000 and ict.value_map()["2024-Q4"].value == -1.1


@respx.mock
async def test_mom_index_outage_uses_the_last_known_release_and_says_so(tmp_path):
    respx.get(mom.INDEX_URL).respond(503)
    xlsx = CATALOG.get(MOM_Q).last_known["xlsx"]
    respx.get(xlsx).respond(content=_body(xlsx))

    ds = await fetch(MOM_Q, CATALOG, TAXONOMY, _fetcher(tmp_path))

    fallback = next(i for i in ds.quality if i.code == "DISCOVERY_FALLBACK")
    assert "index page unavailable" in fallback.message and "2026-09-21" in fallback.message
    assert ds.find("info_comms")


@respx.mock
async def test_datagov_csv_download_keeps_the_key_and_signed_url_away_from_storage(tmp_path):
    signed = "https://s3.ap-southeast-1.amazonaws.com/bucket/file.csv?X-Amz-Signature=secret"
    respx.get(datagov.metadata_url(VACANCIES_Q)).respond(
        json={"data": {"name": "JV", "lastUpdatedAt": "2026"}}
    )
    initiate = respx.get(f"{datagov.OPEN_API}/{VACANCIES_Q}/initiate-download").respond(json={"code": 0})
    poll = respx.get(datagov.download_url(VACANCIES_Q))
    poll.side_effect = [
        httpx.Response(200, json={"data": {"status": "DOWNLOAD_PENDING"}}),
        httpx.Response(200, json={"data": {"status": "DOWNLOAD_SUCCESS", "url": signed}}),
    ]
    s3 = respx.get(signed).respond(content=_body(datagov.download_url(VACANCIES_Q)))
    settings = Settings(_env_file=None, datagov_api_key=SecretStr("k-123"), datagov_key_tier="prod")
    limiter = Unthrottled()
    fetcher = Fetcher(
        mode="live", snapshots=SnapshotStore(tmp_path), backoff_s=0, limiter=limiter, keys=api_keys(settings)
    )
    datagov.DOWNLOAD_POLL_WAIT_S, wait = 0, datagov.DOWNLOAD_POLL_WAIT_S
    try:
        ds = await fetch(VACANCIES_Q, CATALOG, TAXONOMY, fetcher)
    finally:
        datagov.DOWNLOAD_POLL_WAIT_S = wait

    assert initiate.calls.last.request.headers["x-api-key"] == "k-123"
    assert poll.calls.last.request.headers["x-api-key"] == "k-123"
    assert "x-api-key" not in s3.calls.last.request.headers, "the key must never go to the storage host"
    assert ("datagov-downloads", "prod") in limiter.applied
    stored = [p.url for p in fetcher.payloads.values()]
    assert signed not in str(ds.provenance.url_api) and signed not in str(stored)
    assert datagov.download_url(VACANCIES_Q) in ds.provenance.url_api
    # Same records as the snapshot's datastore pages, so the same artifact.
    offline = await fetch(VACANCIES_Q, CATALOG, TAXONOMY, Fetcher(mode="snapshot", snapshots=SNAPSHOTS))
    assert [s.model_dump() for s in ds.series] == [s.model_dump() for s in offline.series]


async def test_csv_download_and_datastore_paths_yield_the_same_artifact():
    entry = CATALOG.get(VACANCIES_Q)
    snapshot = Fetcher(mode="snapshot", snapshots=SNAPSHOTS)
    via_csv = await datagov.fetch_dataset(entry, CATALOG.platforms["datagov"], TAXONOMY, snapshot)
    datastore_only = entry.model_copy(update={"formats": ["json_api"]})
    via_api = await datagov.fetch_dataset(datastore_only, CATALOG.platforms["datagov"], TAXONOMY, snapshot)
    assert via_csv.artifact_id == via_api.artifact_id
    assert len(via_api.provenance.url_api) > len(via_csv.provenance.url_api)


def test_api_key_tier_sets_the_limit_and_unauthenticated_calls_use_the_published_floor():
    downloads = datagov.DOWNLOADS
    assert downloads.interval_s("none") == pytest.approx(10 / 2 * 1.1)
    assert downloads.interval_s("prod") == pytest.approx(10 / 10 * 1.1)
    assert api_keys(Settings(_env_file=None)) == []


class BrokenRedis:
    async def set(self, *args, **kwargs):
        raise redis.ConnectionError("down")


async def test_limiter_falls_back_to_slower_local_spacing_without_redis(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.connectors.ratelimit.asyncio.sleep", fake_sleep)
    limiter = SharedRateLimiter(BrokenRedis())  # type: ignore[arg-type]
    limit = RateLimit("test", 1, {"none": 10})
    await limiter.wait(limit, "none")
    await limiter.wait(limit, "none")
    assert sleeps and sleeps[-1] == pytest.approx(limit.interval_s("none") * 2, rel=0.05)


@respx.mock
async def test_api_key_is_not_forwarded_across_a_redirect_to_another_host(tmp_path):
    elsewhere = "https://elsewhere.example.com/data.json"
    respx.get(datagov.metadata_url(VACANCIES_Q)).respond(301, headers={"Location": elsewhere})
    target = respx.get(elsewhere).respond(json={"data": {}})
    settings = Settings(_env_file=None, datagov_api_key=SecretStr("k-123"))
    fetcher = _fetcher(tmp_path, keys=api_keys(settings))

    await fetcher.get(datagov.metadata_url(VACANCIES_Q))

    assert "x-api-key" not in target.calls.last.request.headers


@respx.mock
async def test_mom_index_served_from_its_snapshot_is_still_a_discovery_fallback():
    xlsx = CATALOG.get(MOM_Q).last_known["xlsx"]
    respx.get(mom.INDEX_URL).respond(503)  # the snapshot store holds a copy of the page
    respx.get(xlsx).respond(content=_body(xlsx))
    fetcher = Fetcher(mode="live", snapshots=SNAPSHOTS, backoff_s=0, limiter=Unthrottled())

    ds = await fetch(MOM_Q, CATALOG, TAXONOMY, fetcher)

    assert not ds.provenance.from_snapshot, "the workbook itself was fetched live"
    fallback = next(i for i in ds.quality if i.code == "DISCOVERY_FALLBACK")
    assert (
        "taken from its snapshot of 2026-10-25" in fallback.message
        and "newer release may exist" in fallback.message
    )


async def test_redis_outage_spacing_is_shared_by_every_limiter_in_the_process(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.connectors.ratelimit.asyncio.sleep", fake_sleep)
    limit = RateLimit("shared-in-process", 1, {"none": 10})
    first_analysis, second_analysis = SharedRateLimiter(BrokenRedis()), SharedRateLimiter(None)  # type: ignore[arg-type]

    await first_analysis.wait(limit, "none")
    await second_analysis.wait(limit, "none")

    assert sleeps and sleeps[-1] > 0, "the second analysis waited for the first one's slot"
