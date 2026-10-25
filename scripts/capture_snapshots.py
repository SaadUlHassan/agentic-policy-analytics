"""Capture real-data snapshots for offline/demo use (plan §4.5-4.6, DATA_MODE=snapshot).

Raw payloads are stored byte-for-byte as received, content-addressed by SHA-256,
with a manifest recording the request URL, retrieval time and hash. These are real
public datasets, not mock data.

Usage (from backend/):  uv run python ../scripts/capture_snapshots.py
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = REPO_ROOT / "data" / "snapshots"
UA = {"User-Agent": "policy-analytics-snapshot/0.1 (research prototype)", "Accept": "application/json"}

SINGSTAT_TABLES = ["M182841", "M183891", "M184071", "M184021", "M184041", "M182081"]
DATAGOV_DATASETS = [
    "d_01966fdb498fa7fa2863635e25539693",  # Job Vacancy by Industry - Annual (MOM)
    "d_3f17bbf67d31d4d402caa8755eb74afc",  # Job Vacancy by Industry - Quarterly (MOM)
    "d_d2518fed6cc2014f0cd061b4570a9592",  # Employment by Sector, annual (mirror of SingStat M182841)
]
DATAGOV_CSV_DOWNLOADS = ["d_3f17bbf67d31d4d402caa8755eb74afc"]
MOM_PAGE = "https://stats.mom.gov.sg/Pages/EmploymentTimeSeries.aspx"
MOM_PREFIXES = ["mrsd_4_annl_emp_chg_by_ind_", "mrsd_3_qtly_emp_chg_by_ind_"]

SINGSTAT_PAGE_POINTS = 5000  # server-side cap per response, regardless of requested limit
DATAGOV_MIN_INTERVAL_S = 3.0  # 4 datastore calls / 10 s without an API key


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Recorder:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.client = httpx.Client(headers=UA, timeout=60, follow_redirects=True)
        self._last_datagov = 0.0

    def fetch(
        self, url: str, *, datagov: bool = False, throttle_marker: bytes | None = None
    ) -> httpx.Response:
        """GET with retries. data.gov.sg calls are spaced to its unauthenticated rate limit;
        `throttle_marker` is a byte string a successful body must contain (an over-limit
        datastore call has been observed returning 200 without its "result" key)."""
        if datagov:
            wait = DATAGOV_MIN_INTERVAL_S - (time.monotonic() - self._last_datagov)
            if wait > 0:
                time.sleep(wait)
        for attempt in range(4):
            try:
                resp = self.client.get(url)
            except httpx.TransportError as exc:
                print(f"  transport error ({type(exc).__name__}) on attempt {attempt + 1}; retrying")
                time.sleep(5 * (attempt + 1))
                continue
            if datagov:
                self._last_datagov = time.monotonic()
            throttled = resp.status_code == 429 or (
                throttle_marker is not None and resp.is_success and throttle_marker not in resp.content
            )
            if throttled:
                time.sleep(10 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"failed after retries (rate limit or network): {url}")

    def record(
        self,
        url: str,
        *,
        source: str,
        dataset: str,
        kind: str,
        ext: str,
        datagov: bool = False,
        throttle_marker: bytes | None = None,
        recorded_url: str | None = None,
    ) -> bytes:
        """Fetch and persist the body byte-for-byte, content-addressed, with a manifest entry."""
        resp = self.fetch(url, datagov=datagov, throttle_marker=throttle_marker)
        body = resp.content
        sha = hashlib.sha256(body).hexdigest()
        rel = Path(source) / dataset / f"{kind}-{sha[:16]}.{ext}"
        (SNAP_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
        (SNAP_DIR / rel).write_bytes(body)
        self.entries.append(
            {
                "source": source,
                "dataset": dataset,
                "kind": kind,
                "url": recorded_url or url,
                "path": str(rel),
                "sha256": sha,
                "bytes": len(body),
                "content_type": resp.headers.get("content-type"),
                "retrieved_at": now_iso(),
            }
        )
        return body


def capture_singstat(rec: Recorder) -> None:
    for table in SINGSTAT_TABLES:
        offset, page = 0, 0
        while True:
            url = (
                f"https://tablebuilder.singstat.gov.sg/api/table/tabledata/{table}"
                f"?limit={SINGSTAT_PAGE_POINTS}&offset={offset}"
            )
            body = rec.record(
                url, source="singstat", dataset=table, kind=f"tabledata-p{page:02d}", ext="json"
            )
            rows = json.loads(body)["Data"]["row"]
            points = sum(len(r["columns"]) for r in rows)
            print(f"singstat {table} page {page}: {len(rows)} rows, {points} points")
            if points < SINGSTAT_PAGE_POINTS:
                break
            offset += points
            page += 1


def capture_datagov(rec: Recorder) -> None:
    for ds in DATAGOV_DATASETS:
        rec.record(
            f"https://api-production.data.gov.sg/v2/public/api/datasets/{ds}/metadata",
            source="datagov",
            dataset=ds,
            kind="metadata",
            ext="json",
            datagov=True,
        )
        offset, page, limit = 0, 0, 1000
        while True:
            url = f"https://data.gov.sg/api/action/datastore_search?resource_id={ds}&limit={limit}&offset={offset}"
            body = rec.record(
                url,
                source="datagov",
                dataset=ds,
                kind=f"datastore-p{page:02d}",
                ext="json",
                datagov=True,
                throttle_marker=b'"result"',
            )
            result = json.loads(body)["result"]
            n = len(result["records"])
            print(f"datagov {ds} page {page}: {n} records (total {result['total']})")
            offset += n
            page += 1
            if n == 0 or offset >= result["total"]:
                break
    for ds in DATAGOV_CSV_DOWNLOADS:
        # initiate/poll responses embed a pre-signed S3 URL with temporary AWS credentials,
        # so they are used in memory only and never persisted.
        api = f"https://api-open.data.gov.sg/v1/public/api/datasets/{ds}"
        rec.fetch(f"{api}/initiate-download", datagov=True)
        for _ in range(10):
            data = rec.fetch(f"{api}/poll-download", datagov=True).json().get("data", {})
            if data.get("status") == "DOWNLOAD_SUCCESS" and data.get("url"):
                rec.record(
                    data["url"],
                    source="datagov",
                    dataset=ds,
                    kind="download",
                    ext="csv",
                    recorded_url=f"{api}/poll-download -> pre-signed S3 URL (not recorded)",
                )
                break
            time.sleep(3)
        else:
            raise RuntimeError(f"CSV download never became ready for {ds}")


def mom_release_date(href: str) -> str:
    """MOM file names end in a DDMMYYYY release date; return it as sortable YYYYMMDD."""
    m = re.search(r"_(\d{2})(\d{2})(\d{4})\.", href)
    return f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else ""


def capture_mom(rec: Recorder) -> None:
    html = rec.record(
        MOM_PAGE, source="mom", dataset="EmploymentTimeSeries", kind="index", ext="html"
    ).decode("utf-8", "replace")
    hrefs = sorted(set(re.findall(r'href="([^"]+\.(?:xlsx|csv))"', html, flags=re.I)))
    for prefix in MOM_PREFIXES:
        for ext in ("xlsx", "csv"):
            matches = [
                h for h in hrefs if Path(h).name.lower().startswith(prefix) and h.lower().endswith(ext)
            ]
            if not matches:
                print(f"mom: no {ext} link for {prefix}")
                continue
            href = max(matches, key=mom_release_date)
            name = prefix.rstrip("_")
            rec.record(
                urljoin(MOM_PAGE, href),
                source="mom",
                dataset=name,
                kind=f"timeseries-{mom_release_date(href)}",
                ext=ext,
            )
            print(f"mom {name}.{ext}: {Path(href).name}")


def main() -> int:
    rec = Recorder()
    failures = []
    for step in (capture_singstat, capture_datagov, capture_mom):
        try:
            step(rec)
        except Exception as exc:  # keep other sources; the failure is recorded, never hidden
            failures.append({"step": step.__name__, "error": f"{type(exc).__name__}: {exc}"[:500]})
            print(f"FAILED {step.__name__}: {exc}")
    manifest = {
        "captured_at": now_iso(),
        "note": "Real public data captured byte-for-byte; not mock data.",
        "failures": failures,
        "entries": rec.entries,
    }
    (SNAP_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(rec.entries)} payloads; manifest at data/snapshots/manifest.json")

    recorded = {e["path"] for e in rec.entries} | {"manifest.json"}
    stale = sorted(str(f.relative_to(SNAP_DIR)) for f in SNAP_DIR.rglob("*") if f.is_file())
    stale = [f for f in stale if f not in recorded]
    if stale:
        print(f"note: {len(stale)} files from earlier captures are not in this manifest:", *stale, sep="\n  ")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
