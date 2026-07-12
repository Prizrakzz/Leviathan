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

Missing fields (SILVER-F030 semantic ADR, INV-4)
------------------------------------------------
The ``changes`` field (revisions to previously reported sales) is absent in
some historical records returned by the API.  It is kept **NULL** when absent
or null -- it is NEVER synthesized as 0.0 (INV-4: an absent source measure
stays null; a real zero revision is otherwise indistinguishable from "not
reported").  ``changes`` / ``changes_1000mt`` is a DEPRECATED, nullable column.

Unknown API fields (SILVER-F030 schema-drift reporting, INV-1)
--------------------------------------------------------------
Raw JSON is immutable in S3, so every field the FAS API returns is already
preserved there.  A camelCase key the current ``_FIELD_MAP`` does not know is
NOT silently dropped: it is surfaced as a WARN (schema-drift alert) before the
typed bronze projection, so a future API addition is caught and can be promoted
to ``_FIELD_MAP`` deliberately rather than lost unnoticed.
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

    # --- Schema-drift alert (SILVER-F030 / INV-1): DO NOT silently drop unknown API fields. ---
    # Raw JSON is immutable in S3 (every field is already preserved there); surface any camelCase
    # key the current _FIELD_MAP does not know as a WARN so a future FAS API addition is caught and
    # promoted deliberately, never lost unnoticed.
    unknown_api_fields = sorted(set(df.columns) - set(_FIELD_MAP))
    if unknown_api_fields:
        logger.warning(
            "ESR schema drift commodity_code=%d market_year=%d: %d unrecognised API field(s) %s "
            "— retained in immutable Raw, dropped from the typed bronze schema (add to _FIELD_MAP "
            "to promote them).",
            commodity_code, market_year, len(unknown_api_fields), unknown_api_fields,
        )

    # Rename API camelCase → snake_case.  Only rename columns that are present.
    rename = {k: v for k, v in _FIELD_MAP.items() if k in df.columns}
    df = df.rename(columns=rename)

    # Keep only the expected (known) columns for the typed bronze schema.
    expected = list(_FIELD_MAP.values())
    df = df[[col for col in expected if col in df.columns]]

    # --- "changes" (revisions) may be absent in historical records or null in individual rows. ---
    # INV-4: an absent source measure stays NULL -- it is NEVER synthesized as 0.0 (a real zero
    # revision would be indistinguishable from "not reported" if we filled). ``changes`` is a
    # DEPRECATED nullable column (SILVER-F030 ADR); NaN stays NaN.
    if "changes" not in df.columns:
        logger.debug(
            "commodity_code=%d market_year=%d: 'changes' column absent — left NULL (INV-4)",
            commodity_code, market_year,
        )
        df["changes"] = float("nan")
    else:
        null_count = int(df["changes"].isna().sum())
        if null_count:
            logger.debug(
                "commodity_code=%d market_year=%d: %d null 'changes' value(s) — left NULL (INV-4)",
                commodity_code, market_year, null_count,
            )

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
