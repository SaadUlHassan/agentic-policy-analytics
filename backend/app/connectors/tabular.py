"""Tabular payloads (CSV files, datastore records) read as text and checked for the structure the
parsers rely on. A missing column is schema drift: reported as such, never a KeyError."""

from __future__ import annotations

import io
from collections.abc import Iterable

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

from app.connectors.http import RawPayload, SourceSchemaError


def read_csv(payload: RawPayload) -> pd.DataFrame:
    """Every cell as source text: markers such as "na" or "-" must survive to the marker rules.
    Unnamed, entirely empty columns (MOM files carry trailing ones) are dropped."""
    try:
        frame = pd.read_csv(io.BytesIO(payload.body), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, UnicodeDecodeError, pd.errors.EmptyDataError) as exc:
        raise SourceSchemaError(payload.url, f"not a readable CSV ({type(exc).__name__})") from exc
    blank = [c for c in frame.columns if str(c).startswith("Unnamed:") and not frame[c].str.strip().any()]
    return frame.drop(columns=blank)


def records_frame(records: list[dict]) -> pd.DataFrame:
    """A key missing from some records becomes a null there, which require_columns reports."""
    return pd.DataFrame.from_records(records) if records else pd.DataFrame()


def require_columns(frame: pd.DataFrame, columns: Iterable[str], url: str) -> pd.DataFrame:
    """The named columns must exist and hold text; anything else in the frame is left alone."""
    schema = pa.DataFrameSchema({c: pa.Column(str, nullable=False) for c in columns}, strict=False)
    try:
        return schema.validate(frame, lazy=True)
    except SchemaErrors as exc:
        cases = exc.failure_cases
        missing = sorted(cases.loc[cases["check"] == "column_in_dataframe", "failure_case"].astype(str))
        other = sorted(
            {f"{c.check} on {c.column}" for c in cases.itertuples() if c.check != "column_in_dataframe"}
        )
        problems = [f"missing column(s) {', '.join(missing)}"] if missing else []
        raise SourceSchemaError(url, "unexpected structure: " + "; ".join([*problems, *other][:5])) from exc
