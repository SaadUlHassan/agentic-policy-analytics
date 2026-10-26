"""Single entry point for fetching any catalogued dataset, whichever platform hosts it."""

from __future__ import annotations

from app.connectors import datagov, mom, singstat
from app.connectors.catalog import Catalog
from app.connectors.http import Fetcher
from app.data.models import NormalizedDataset
from app.data.taxonomy import Taxonomy

_FETCHERS = {"singstat": singstat.fetch_table, "datagov": datagov.fetch_dataset, "mom": mom.fetch_timeseries}


class UnknownDataset(Exception):
    pass


async def fetch(dataset_id: str, catalog: Catalog, taxonomy: Taxonomy, fetcher: Fetcher) -> NormalizedDataset:
    entry = catalog.get(dataset_id)
    if entry is None or entry.platform not in _FETCHERS:
        raise UnknownDataset(f"{dataset_id} is not a catalogued, supported dataset")
    return await _FETCHERS[entry.platform](entry, catalog.platforms[entry.platform], taxonomy, fetcher)
