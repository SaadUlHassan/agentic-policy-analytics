# Data Sources

The platform analyses real, public Singapore government statistics from three platforms: SingStat Table Builder, Data.gov.sg and MOM's statistics site. **There is no mock or synthetic research data.** Offline runs use byte-for-byte captures of the real responses (see [Snapshots](#snapshots)), and test doubles for corrupted data live only under `backend/tests/` and `eval/`, never on a production path.

Everything here is recorded machine-readably in [`data/manifest/sources.yaml`](data/manifest/sources.yaml), which the connectors and the agents read, and [`data/taxonomy.yaml`](data/taxonomy.yaml), which identifies industry sectors. Facts were verified against live responses on 24–25 October 2026. Anything not confirmed from the source is marked `unverified` there and is not relied on.

- [Platforms](#platforms)
- [Catalogued datasets](#catalogued-datasets)
- [Definitions that matter](#definitions-that-matter)
- [Series identity and join rules](#series-identity-and-join-rules)
- [Markers and missing values](#markers-and-missing-values)
- [Data quality checks](#data-quality-checks)
- [Same-origin mirrors](#same-origin-mirrors)
- [Snapshots](#snapshots)
- [Rate limits and API keys](#rate-limits-and-api-keys)
- [Adding a dataset or a source](#adding-a-dataset-or-a-source)

## Platforms

| Platform | Publisher | Access | Formats used | Documentation |
|---|---|---|---|---|
| **SingStat Table Builder** | Department of Statistics Singapore | No key | JSON API | `https://tablebuilder.singstat.gov.sg/api/table/tabledata/{table_id}?limit=&offset=`; human view `https://tablebuilder.singstat.gov.sg/table/TS/{table_id}` |
| **Data.gov.sg** | GovTech Singapore (platform operator; each dataset is managed by its originating agency) | Optional API key | CSV download (preferred), datastore JSON API (fallback), metadata API | Datastore `https://data.gov.sg/api/action/datastore_search?resource_id=`; download `https://api-open.data.gov.sg/v1/public/api/datasets/{id}/initiate-download` then `/poll-download`; metadata `https://api-production.data.gov.sg/v2/public/api/datasets/{id}/metadata` |
| **MOM Statistics** | Ministry of Manpower, Manpower Research & Statistics Department | No key | Excel workbook (preferred), CSV (fallback) | Index page `https://stats.mom.gov.sg/Pages/EmploymentTimeSeries.aspx` |

What each platform does that a connector has to handle:

- **SingStat.** `limit` and `offset` count **data points, not rows**, and the server caps every page at 5,000 points whatever `limit` asks for. A series can be split across pages, so the connector merges fragments by `seriesNo` and stops at a short page. Values are strings, and the sector hierarchy is encoded in `seriesNo` (`1.2.4` is Information & Communications, `1.2.4.2` its IT subsector). Every response carries a fresh `dateGenerated`, so raw bytes change daily for unchanged data.
- **Data.gov.sg.** A CSV download is one `initiate-download` request and then up to six `poll-download` requests, 2 s apart, until the file is ready, all counted against the downloads limit. The final poll returns a pre-signed S3 URL, fetched once (S3 is not rate-limited) and never stored; the download is identified by its `poll-download` URL. The datastore instead needs one request per 1,000 records against the datastore limit. Each fetch also makes one metadata request, spaced on the datastore limit. An over-limit datastore call was observed returning a body without `result` rather than an HTTP 429, so both are treated as throttling.
- **MOM.** File names embed the release date (`mrsd_4_annl_emp_chg_by_ind_20032026.xlsx` is the 20 March 2026 release), so files are **discovered on every fetch**: the index page is scanned for the dataset's stable prefix and the newest release wins. If the page is down or no longer links the dataset, the last-known URL in the catalogue is used and a `DISCOVERY_FALLBACK` warning is disclosed. Workbooks carry one sheet per SSIC edition; only the `SSIC2020` sheet is read.

## Catalogued datasets

Nine datasets, all originated by MOM. "Mirror" means the same statistic republished on another platform.

| Dataset | Platform | What one value is | Frequency | Unit | Coverage | Mirror |
|---|---|---|---|---|---|---|
| **M182841** Employment (Persons) By Sector, (As At Year-End), Annual | SingStat | Employment level at year end (stock), total employment | Annual | thousand persons | 2001–2025 (SSIC 2020 from 2008, SSIC 2005 for 2001–2007) | `d_d2518fed…` |
| **M183891** Changes In Employment By Sector, (Compared To The Previous Period), Quarterly | SingStat | Change between consecutive quarter-end levels (flow) | Quarterly | persons | ICT from 2017-Q1 (SSIC 2020 from 2009-Q1) | `mrsd_3_qtly…` |
| **M184071** Job Vacancies By Industry And Occupational Group (SSIC 2020) (End Of Period), Quarterly | SingStat | Vacancies open at quarter end (stock), establishment survey | Quarterly | vacancies, rounded to 100 | SSIC 2020 from 2006-Q1 | `d_3f17bbf6…` |
| **M184021** Average Monthly Recruitment Rate By Industry And Occupational Group, (SSIC 2020), Quarterly | SingStat | Average monthly recruitment rate within the quarter | Quarterly | percent | SSIC 2020 from 2006-Q1 | — |
| **d_01966fdb498fa7fa2863635e25539693** Number of Job Vacancy by Industry – Annual | Data.gov.sg | **Mean of the four quarter-end values**, rounded to 100 | Annual | vacancies | SSIC 2020 from 2006 | — |
| **d_3f17bbf67d31d4d402caa8755eb74afc** Number of Job Vacancy by Industry – Quarterly | Data.gov.sg | Vacancies at quarter end | Quarterly | vacancies, rounded to 100 | SSIC 2020 from 2006-Q1 | of M184071 |
| **d_d2518fed6cc2014f0cd061b4570a9592** Employment (Persons) By Sector, (As At Year-End), Annual | Data.gov.sg | Year-end employment level (wide layout) | Annual | thousand persons | as M182841 | of M182841 |
| **mrsd_4_annl_emp_chg_by_ind** Annual Employment Change by Industry (SSIC 2020) | MOM | Change between consecutive year-end levels | Annual | thousand persons, to 0.1 | SSIC 2020 from 2009 | — |
| **mrsd_3_qtly_emp_chg_by_ind** Quarterly Employment Change by Industry (SSIC 2020) | MOM | Change between consecutive quarter-end levels | Quarterly | thousand persons, to 0.1 | SSIC 2020 from 2009-Q1 | of M183891 |

**Human-readable links:** SingStat tables at `https://tablebuilder.singstat.gov.sg/table/TS/{id}` (for example [M182841](https://tablebuilder.singstat.gov.sg/table/TS/M182841)); Data.gov.sg datasets at `https://data.gov.sg/datasets/{id}/view`; MOM files on the [employment time-series page](https://stats.mom.gov.sg/Pages/EmploymentTimeSeries.aspx). Every report citation carries the human URL of the dataset it cites, with the dataset version (artifact ID) and retrieval time. The API URL each version was fetched from is in the JSON export bundle, under `datasets[].url_api`, alongside the raw payload hashes.

**Supported domain:** the Singapore labour market by industry at national level: employment levels and changes, job vacancies and recruitment rates. Questions outside it (housing prices, health, forecasts beyond the data) are declined with a clear explanation, never answered with unrelated data.

**Licences and terms** are recorded as `unverified` in the manifest: the platforms' terms were not confirmed for this build and should be checked before any redistribution.

## Definitions that matter

These are the facts that decide whether two numbers can be compared. Each was confirmed from the source and is recorded in the manifest.

- **"Technology sector" means SSIC 2020 Section J, Information & Communications (J58–63).** This is recorded as a plan assumption. Its subsector **IT & Other Information Services (J62–63)** is a different sector and is never merged with its parent.
- **MOM's annual vacancies are a quarterly average.** Each annual value is the mean of the four quarter-end values, rounded to 100 (ICT 2022: quarterly mean 10,325, published 10,300). Annual vacancies therefore can't be paired with year-end employment: the correlation is refused with `REFERENCE_MISMATCH`.
- **M182841 is a year-end stock** from administrative records, with the self-employed estimated from the Labour Force Survey. It is classified under SSIC 2020 from 2008; earlier years use SSIC 2005 and are a different classification.
- **Employment change is published in two units.** SingStat M183891 reports persons; MOM's files report the same statistic in thousands to 0.1. Values are normalised internally and shown in the source's unit.
- **Vacancies and employment cover different populations.** Vacancies come from a survey of establishments (private establishments with at least 25 employees before 2006, the public sector included from 2006); employment from administrative records of total employment. The correlation between them carries this as a caveat.
- **The demo correlation pair** is M184071 ICT vacancies (stock at quarter end) against M183891 ICT employment change (flow over the quarter). Over 2020-Q1 to 2024-Q4 it aligns 20 pairs at lag 0 and 19 at lag 1. It is an exploratory association with no p-values, because consecutive quarters are serially dependent.

## Series identity and join rules

Every series gets a `SeriesIdentity` (`backend/app/data/identity.py`): classification system and version, sector code set, hierarchy level, population, measure type (stock, flow, rate), unit, scale, frequency and reference convention (year end, quarter end, quarter-end difference, average of quarter ends, monthly average within the quarter).

- **Labels are matched after normalisation** (lower case, collapsed whitespace, `&` → `and`), and only aliases recorded in the taxonomy count as the same sector. MOM's misspelt "Telecomunications" is one such recorded alias.
- **A MOM row is identified by its stated SSIC code and its label together.** A row whose code contradicts its label (a child relabelled with its parent's name) is an `IDENTITY_CONFLICT` and is not used.
- **No join by letter alone.** SSIC 2020 J and SSIC 2005 J are different classifications, and no crosswalk is assumed.
- **Comparisons and correlations need compatible identities:** the same classification and code set, the same frequency, a compatible reference convention and a declared pairing rule. Anything else is refused with a reason code (`CLASSIFICATION_MISMATCH`, `FREQ_MISMATCH`, `REFERENCE_MISMATCH`, `NO_PAIRING_RULE`, `INSUFFICIENT_PAIRS`).
- **Nothing is resampled.** An annual series is never converted to quarterly by repetition.

## Markers and missing values

Markers keep the meaning the **source** gives them; nothing is imputed.

| Platform | Marker | Meaning | Treatment |
|---|---|---|---|
| MOM | `-` | Nil or negligible (from the legend in the workbook's SSIC 2020 sheet, re-read on every fetch) | Null, excluded from calculations, disclosed |
| MOM CSV | `n.a.` | Not defined: the CSV carries no legend | Unknown marker: null and flagged |
| SingStat | `-` | Not confirmed from the source | Unknown marker: null and flagged |
| Data.gov.sg | `-`, `na` | Not confirmed from the source | Unknown marker: null and flagged |

The report's data-quality panel lists the markers actually present in the values used, with their meaning and treatment. If a workbook's legend changes from what the manifest records, a `LEGEND_CHANGED` warning is raised.

## Data quality checks

Every fetch is validated before an agent can use it, and the results appear in the timeline and the report's data-quality panel.

- **Schema drift.** pandera schemas check the columns each parser relies on. A missing column is a `SourceSchemaError` reported to the agent, never a crash.
- **Units.** MOM's stated unit (`In Thousands`) is read from the sheet and checked against the manifest (`UNIT_MISMATCH`). An unstated or unrecognised unit is a blocking `UNIT_UNVERIFIED` error, never a silent assumption.
- **Period footnotes.** MOM's newest quarter header reads `1Q^`, a footnote mark the sheet doesn't explain. It is stripped and disclosed (`PERIOD_FOOTNOTE`).
- **Messy files.** MOM's quarterly workbook sheet is six side-by-side blocks of three years each, merged row by row; its CSV carries six empty trailing columns.
- **Identity conflicts, duplicate periods and unknown markers** are flagged per series; a series with a blocking error can't be selected.
- **Mutation suite.** `backend/tests/unit/data/test_quality_mutations.py` corrupts real fixtures (a dropped column, a renamed label, a new marker, a duplicate period, a unit or scale change, a parent/child relabel, a mirror mismatch) and checks each is detected.

## Same-origin mirrors

Several datasets republish the same MOM statistic. A mirror on a second platform is **platform diversity, not independent corroboration**, and the report never presents agreement between mirrors as confirmation.

- **The consistency check runs automatically** whenever a selected series has a catalogued mirror, in both directions, and only when both sides are free of blocking errors (otherwise the result is "not comparable", never "consistent").
- **Mirrors agree within half the coarser published increment.** MOM publishes thousands to 0.1 and SingStat whole persons, so they are compared at ±50 persons.
- **Recorded results on the snapshots:**
  - Data.gov.sg quarterly vacancies are identical to M184071 for ICT, 2020-Q1 to 2024-Q4.
  - MOM's quarterly workbook agrees with M183891 for ICT on all 37 shared quarters (2017-Q1 to 2026-Q2) at 0.1 thousand.
  - The Data.gov.sg employment mirror matches M182841. Its `na` cells for 2001–2003 are rows SingStat doesn't publish for those years (Real Estate, Professional, Administrative & Support), not conflicting values.
- **A republished copy of an already-selected statistic is refused,** so one figure is never reported twice.

## Snapshots

`data/snapshots/` holds real responses captured byte for byte on 25 October 2026 by `scripts/capture_snapshots.py` (`make snapshots` re-captures them): 26 payloads across the three platforms, about 2.4 MB. `data/snapshots/manifest.json` records each payload's source, dataset, request URL, path, SHA-256, size, content type and retrieval time.

- **`DATA_MODE=snapshot`** serves every request from the snapshots, keyed by request URL. Live LLMs still need the network; fully offline runs also set `LLM_MODE=offline`.
- **Live fallback.** In live mode, a source that fails (or a demo fault switch) is served from its snapshot of the same URL when one exists. The report discloses it, with the retrieval date.
- **The evaluation is pinned to these snapshots.** `eval/compute_expected.py` derives every golden expected value from the raw snapshot payloads with its own parsing, and a gate fails if `eval/golden/expected.json` is stale for the current snapshots.
- **Provenance in the database.** Every dataset version an analysis uses is an immutable artifact identified by a hash of its normalised observations, source metadata and blocking issues. The raw payload bytes are stored by SHA-256 alongside it, and each analysis records how it fetched them (live or snapshot, fallbacks, retrieval time).

## Rate limits and API keys

| Platform and endpoint | Limit used per 10 s | Requests it covers |
|---|---|---|
| Data.gov.sg datastore | 4 without a key; 8 or 20 with a key, by `DATAGOV_KEY_TIER` (`dev` or `prod`) | Datastore pages and metadata requests |
| Data.gov.sg downloads | 2 without a key; 4 or 10 with a key | `initiate-download` and each `poll-download` |
| MOM | 10 (one a second) | Index page, workbook and CSV |
| SingStat | not spaced | — |

**Where these numbers come from.** The Data.gov.sg figures are the limits its developer guide ("API Rate Limits") published when this was built; MOM and SingStat publish none, so MOM is given one request a second as a courtesy. They are configuration in the connectors (`DATASTORE`, `DOWNLOADS`, `POLITE`), not values read from the platforms, and Data.gov.sg may change them.

**What the spacing guarantees, and what it doesn't.**
- Each slot is 10% longer than the published rate allows, so the platform stays below the limit rather than at it.
- **Shared only through one Redis.** Every worker using the same Redis takes slots from one schedule (`SET NX PX` on the next slot). Processes on separate Redis instances don't coordinate. If Redis can't be reached, each process falls back to its own schedule at twice the interval, so a few processes stay under the limit but many could exceed it together.
- **Only this platform's own requests are counted.** Other software calling Data.gov.sg from the same address, or with the same key, draws on the same allowance without the spacing knowing. An over-limit response is still handled: an HTTP 429 or 5xx, or a datastore body without `result` (observed when keyless), is retried.
- **Retries take slots too.** Every request gets up to three attempts with increasing backoff, each waiting for its own slot. After that the request falls back to its snapshot when one exists, and the report discloses it.

**API key.** `DATAGOV_API_KEY` is sent as `x-api-key`, only to `data.gov.sg` and its subdomains (never to the pre-signed S3 URL), and `DATAGOV_KEY_TIER` must match the tier the key was issued for, since it sets the spacing. A free key is recommended for live demos.

## Adding a dataset or a source

**A dataset on an existing platform** needs only a catalogue entry:

1. Add it to `datasets:` in `data/manifest/sources.yaml` with its full identity: `metric`, `measure_type`, `reference_convention`, `population`, `frequency`, `unit`, `scale`, `classification`, keywords for the catalogue search, and `mirrors` / `mirror_of` where it republishes another dataset. For Data.gov.sg and MOM, `fields` names the columns to read.
2. If its sector labels or codes are new, add them to `data/taxonomy.yaml` as aliases or `source_codes`.
3. Capture it: add it to `scripts/capture_snapshots.py` and run `make snapshots`, then add connector tests on the captured payload.
4. If it should be part of the evaluation, add golden computations to `eval/golden/queries.yaml` and run `make eval-expected`.

**A new platform** needs a connector in `backend/app/connectors/`: an async `fetch` function that takes the catalogue entry, the platform entry, the taxonomy and the shared `Fetcher` (which provides rate limits, retries, snapshots and fallback) and returns a `NormalizedDataset` of identified series with their quality issues. Register it in `_FETCHERS` in `connectors/registry.py`, add the platform under `platforms:` in the manifest, and add a pandera schema for the columns it relies on.
