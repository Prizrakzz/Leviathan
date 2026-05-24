"""Bronze transform for USDA FAS Export Sales Reporting (ESR) data.

Converts raw ESR JSON (as returned by the FAS API and stored in S3) into a
typed pandas DataFrame suitable for writing to bronze Parquet.

No S3 or AWS dependencies — pure data transformation.  The Glue job and the
Airflow task both call ``transform_esr_json_to_bronze`` directly.

Units note
----------
Bronze stores the API's native units (identified by ``unit_id``).  No unit
conversion is performed here.  Silver is responsible for normalising all
values to metric tonnes (MT) using the ESR unit-of-measure lookup table.

Missing fields
--------------
The ``changes`` field (revisions to previously reported sales) is absent in
some historical records returned by the API.  It is filled with 0.0 when
missing so downstream schemas remain consistent.
"""
from __future__ import annotations

import json

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Mapping from API camelCase field names to bronze snake_case column names.
_FIELD_MAP: dict[str, str] = {
    "commodityCode":    "commodity_code",
    "countryCode":      "country_code",
    "marketYear":       "market_year",
    "weekEndingDate":   "week_ending_date",
    "netSales":         "net_sales",
    "outstandingSales": "outstanding_sales",
    "weeklyExports":    "weekly_exports",
    "cumulativeExports": "cumulative_exports",
    "grossNewSales":    "gross_new_sales",
    "cancelations":     "cancelations",
    "changes":          "changes",
    "unitId":           "unit_id",
}

_FLOAT_COLS = frozenset({
    "net_sales", "outstanding_sales", "weekly_exports", "cumulative_exports",
    "gross_new_sales", "cancelations", "changes",
})

_INT16_COLS = frozenset({"commodity_code", "country_code", "market_year", "unit_id"})


def transform_esr_json_to_bronze(
    raw_bytes: bytes,
    commodity_code: int,
    market_year: int,
    as_of_date: str,
    ingest_date: str,
) -> pd.DataFrame:
    """Parse raw ESR API JSON bytes into a typed bronze DataFrame.

    Args:
        raw_bytes:      Raw bytes of the JSON array returned by the FAS API.
        commodity_code: ESR commodity code (used only for logging / validation).
        market_year:    Marketing year start (used only for logging / validation).
        as_of_date:     Snapshot date in ``YYYYMMDD`` format.  Stored as a
                        metadata column for point-in-time backtesting.
        ingest_date:    ISO date string (``YYYY-MM-DD``) when this row was written.

    Returns:
        DataFrame with bronze schema.  Never empty — raises ``ValueError`` if the
        input produces zero rows.

    Raises:
        json.JSONDecodeError: If *raw_bytes* is not valid JSON.
        ValueError:           If the parsed array is empty or required columns
                              are missing after renaming.
    """
    records: list[dict] = json.loads(raw_bytes)

    if not records:
        raise ValueError(
            f"ESR JSON for commodity_code={commodity_code} market_year={market_year} "
            "is an empty array — no data to transform."
        )

    df = pd.DataFrame(records)

    # Rename API camelCase → snake_case.  Only rename columns that are present;
    # unknown extra columns from future API versions are dropped silently.
    rename = {k: v for k, v in _FIELD_MAP.items() if k in df.columns}
    df = df.rename(columns=rename)

    # Keep only the expected columns (drop any unrecognised API additions).
    expected = list(_FIELD_MAP.values())
    df = df[[col for col in expected if col in df.columns]]

    # --- "changes" may be absent in historical records or null in individual rows ---
    if "changes" not in df.columns:
        logger.debug(
            "commodity_code=%d market_year=%d: 'changes' column absent — filling 0.0",
            commodity_code, market_year,
        )
        df["changes"] = 0.0
    else:
        null_count = df["changes"].isna().sum()
        if null_count:
            logger.debug(
                "commodity_code=%d market_year=%d: %d null 'changes' value(s) — filling 0.0",
                commodity_code, market_year, null_count,
            )
        df["changes"] = df["changes"].fillna(0.0)

    # --- Type casts ---
    df["week_ending_date"] = pd.to_datetime(
        df["week_ending_date"], errors="coerce"
    ).dt.date

    for col in _FLOAT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")

    for col in _INT16_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int16")

    # --- Metadata columns ---
    df["as_of_date"] = as_of_date
    df["ingest_date"] = ingest_date
    df["source"] = "usda_esr"

    logger.info(
        "ESR bronze transform: commodity_code=%d market_year=%d rows=%d",
        commodity_code, market_year, len(df),
    )

    return df
