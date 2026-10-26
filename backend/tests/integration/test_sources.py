"""Shared source rate limits and the raw-payload store, against real Redis and Postgres."""

from __future__ import annotations

import asyncio
import time

import pytest
import respx
from sqlalchemy import text

from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.connectors.ratelimit import RateLimit, SharedRateLimiter
from app.connectors.registry import fetch
from app.data.taxonomy import get_taxonomy
from app.jobs.lifecycle import claim
from app.jobs.writer import FencedWriter
from tests.integration.test_lifecycle import _new

pytestmark = pytest.mark.integration


async def test_rate_limit_is_shared_by_every_worker(redis_client):
    limit = RateLimit("test-shared", 1.0, {"none": 10})  # one call per 0.11 s across all workers
    workers = [SharedRateLimiter(redis_client), SharedRateLimiter(redis_client)]
    starts: list[float] = []

    async def call(limiter: SharedRateLimiter) -> None:
        await limiter.wait(limit, "none")
        starts.append(time.monotonic())

    await asyncio.gather(*(call(workers[i % 2]) for i in range(6)))

    starts.sort()
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert min(gaps) >= limit.interval_s("none") * 0.9, gaps


async def test_dataset_raw_bytes_are_stored_once_by_hash(sessions):
    analysis_id, intent = await _new(sessions)
    c = await claim(sessions, analysis_id, intent, "w")
    writer = FencedWriter(sessions, None, analysis_id, c.epoch)
    fetcher = Fetcher(mode="snapshot", snapshots=get_snapshot_store())
    dataset = await fetch("mrsd_3_qtly_emp_chg_by_ind", get_catalog(), get_taxonomy(), fetcher)
    used = [fetcher.payloads[h] for h in dataset.provenance.raw_sha256]

    await writer.save_artifact(dataset, used)
    await writer.save_artifact(dataset, used)

    async with sessions() as session:
        rows = (await session.execute(text("SELECT sha256, url, body, size_bytes FROM raw_payloads"))).all()
    (row,) = rows
    assert row.sha256 == dataset.provenance.raw_sha256[0] and bytes(row.body) == used[0].body
    assert row.url.endswith(".xlsx") and row.size_bytes == len(used[0].body)


async def test_a_changed_workbook_is_stored_and_reloaded_with_its_own_quality(sessions):
    from app.agents.evidence import EvidenceStore, to_refs
    from app.jobs.runner import _load_evidence
    from tests.unit.data.test_quality_mutations import MOM_Q, MOM_Q_XLSX, _cells, _edit_workbook, _fetch

    def hundreds(sheet) -> None:
        for cell in _cells(sheet, lambda v: v == "In Thousands"):
            cell.value = "In Hundreds"

    clean, changed = await _fetch(MOM_Q, {}), await _fetch(MOM_Q, {MOM_Q_XLSX: _edit_workbook(hundreds)})
    analysis_id, intent = await _new(sessions)
    c = await claim(sessions, analysis_id, intent, "w")
    writer = FencedWriter(sessions, None, analysis_id, c.epoch)
    await writer.save_artifact(clean)  # the clean copy was stored first...
    await writer.save_artifact(changed)

    # ...but resuming with the changed workbook restores the changed workbook, errors included.
    restored = await _load_evidence(
        sessions, analysis_id, to_refs(EvidenceStore(datasets={changed.artifact_id: changed}))
    )
    reloaded = restored.dataset(MOM_Q)
    assert [i.code for i in reloaded.blocking_issues(reloaded.find("info_comms")[0])] == ["UNIT_MISMATCH"]


@respx.mock
async def test_a_reused_artifact_keeps_each_analysis_own_disclosures_on_resume(sessions):
    """Two analyses fetch the same workbook (same artifact): one after live discovery, one after an
    index outage. Resuming the second restores its own DISCOVERY_FALLBACK, not the first one's
    clean view, and the first keeps its clean view."""
    from app.agents.evidence import EvidenceStore, to_refs
    from app.connectors import mom
    from app.jobs.runner import _load_evidence
    from tests.unit.connectors.test_connectors import Unthrottled

    catalog, snapshots, dataset_id = get_catalog(), get_snapshot_store(), "mrsd_3_qtly_emp_chg_by_ind"
    workbook = catalog.get(dataset_id).last_known["xlsx"]
    index = respx.get(mom.INDEX_URL).respond(content=snapshots.load(mom.INDEX_URL).body)
    respx.get(workbook).respond(content=snapshots.load(workbook).body)

    async def fetch_live():
        fetcher = Fetcher(mode="live", snapshots=snapshots, backoff_s=0, limiter=Unthrottled())
        try:
            return await fetch(dataset_id, catalog, get_taxonomy(), fetcher)
        finally:
            await fetcher.aclose()

    clean = await fetch_live()
    index.respond(503)
    after_outage = await fetch_live()
    assert clean.artifact_id == after_outage.artifact_id, "same values, same shared artifact"

    resumed = {}
    for name, dataset in (("first", clean), ("second", after_outage)):
        analysis_id, intent = await _new(sessions)
        c = await claim(sessions, analysis_id, intent, name)
        await FencedWriter(sessions, None, analysis_id, c.epoch).save_artifact(dataset)
        refs = to_refs(EvidenceStore(datasets={dataset.artifact_id: dataset}))
        resumed[name] = (await _load_evidence(sessions, analysis_id, refs)).dataset(dataset_id)

    assert "DISCOVERY_FALLBACK" not in {i.code for i in resumed["first"].quality}
    assert "DISCOVERY_FALLBACK" in {i.code for i in resumed["second"].quality}
    assert resumed["second"].provenance.retrieved_at == after_outage.provenance.retrieved_at


async def test_worker_health_check_reads_the_arq_health_key(redis_client, monkeypatch):
    from arq.constants import default_queue_name, health_check_key_suffix

    from app.core.config import Settings
    from app.worker import health

    url = redis_client.connection_pool.connection_kwargs
    monkeypatch.setattr(
        health,
        "get_settings",
        lambda: Settings(_env_file=None, redis_url=f"redis://{url['host']}:{url['port']}/{url['db']}"),
    )
    assert await health.main() == 1, "no health record: the worker is not running"
    await redis_client.set(default_queue_name + health_check_key_suffix, "j_complete=0", ex=16)
    assert await health.main() == 0
