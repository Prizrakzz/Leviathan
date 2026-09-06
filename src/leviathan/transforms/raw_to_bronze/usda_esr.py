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

The five NET-COMMITMENT fields (SILVER-F030 BF-W2 additive set)
--------------------------------------------------------------
``accumulatedExports`` / ``currentMYNetSales`` / ``currentMYTotalCommitment`` /
``nextMYOutstandingSales`` / ``nextMYNetSales`` arrive on the SAME
``allCountries`` payload this adapter already fetches, which is why the
schema-drift WARN below has been naming exactly these five on every partition.
They are promoted into ``_FIELD_MAP`` here, which is what stops the WARN naming
them -- the contract for any FUTURE unknown field is untouched.

WHEN did they start arriving?  MEASURED, not inferred (2026-09-04,
``jobs/utils/esr_netcommitment_raw_census.py`` over ALL 446 dated raw objects
in ``s3://leviathan-dev-shahem-001``): every one of the 12 as_of vintages held
in raw -- 20260712 through 20260904 -- carries all five keys, 446/446, with no
per-commodity tail; a sample of the undated backfill payloads carries them too.
So raw holds NO pre-publication vintage, and the earlier reading ("the API
started publishing them in August 2026", evidenced by bronze as_of
20260813..20260903 carrying 0 non-null ``changes``) was circular: that window
establishes when ``changes`` went dead, not when the five appeared.  A bound
derived from it would have excluded six vintages whose raw does carry the
fields.  The bronze columns are null for a vintage only when that vintage's
BRONZE predates this promotion -- never because the source withheld them.

They obey the SAME INV-4 law as ``changes`` (absent -> the column EXISTS and is
all-NULL, never 0.0), and they are cast to **float64**, not the incumbent
float32: the frozen ADR declares their silver counterparts ``double``, and a
parquet FLOAT under a Glue ``double`` is the ``HIVE_BAD_DATA: Malformed Parquet
file ... type DOUBLE ... incompatible with type real`` class the estate already
ate on ``silver_food_cpi``.  The incumbent four stay float32; widening THEM is
the separate SILVER-F031 data rewrite already recorded in both contracts'
``drift_summary``.

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
    # --- SILVER-F030 BF-W2 additive set (2026-09-04): the five net-commitment
    # fields, appended at the TAIL so the map diff is a pure append. See the
    # module docstring for why they are float64 and not float32.
    "accumulatedExports":       "accumulated_exports",
    "currentMYNetSales":        "current_my_net_sales",
    "currentMYTotalCommitment": "current_my_total_commitment",
    "nextMYOutstandingSales":   "next_my_outstanding_sales",
    "nextMYNetSales":           "next_my_net_sales",
}

_FLOAT_COLS = frozenset({
    "net_sales", "outstanding_sales", "weekly_exports", "cumulative_exports",
    "gross_new_sales", "cancelations", "changes",
})

# The BF-W2 additive five are born at the INV-2 TARGET width (float64 == Glue
# `double`), kept SEPARATE from _FLOAT_COLS so the incumbent float32 columns are
# not silently re-typed by this lane.
_FLOAT64_COLS = frozenset({
    "accumulated_exports", "current_my_net_sales", "current_my_total_commitment",
    "next_my_outstanding_sales", "next_my_net_sales",
})

# Every nullable measure INV-4 governs: absent -> created as NaN, never 0.0.
_NULLABLE_MEASURE_COLS: tuple[str, ...] = (
    "changes",
    "accumulated_exports",
    "current_my_net_sales",
    "current_my_total_commitment",
    "next_my_outstanding_sales",
    "next_my_net_sales",
)

_INT16_COLS = frozenset({"commodity_code", "country_code", "market_year", "unit_id"})


def _ensure_nullable(
    df: pd.DataFrame, col: str, commodity_code: int, market_year: int
) -> None:
    """INV-4 for one measure column, in place.

    An ABSENT column is created all-NaN; a PRESENT column's nulls are counted and
    left NULL.  Neither branch ever writes 0.0 -- a synthesized zero is
    indistinguishable from a real zero revision / a real zero commitment.  One
    implementation, six call sites, so the law cannot drift between them.
    """
    if col not in df.columns:
        logger.debug(
            "commodity_code=%d market_year=%d: %r column absent -- left NULL (INV-4)",
            commodity_code, market_year, col,
        )
        df[col] = float("nan")
        return
    null_count = int(df[col].isna().sum())
    if null_count:
        logger.debug(
            "commodity_code=%d market_year=%d: %d null %r value(s) -- left NULL (INV-4)",
            commodity_code, market_year, null_count, col,
        )


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

    # --- Nullable measures may be absent in historical records or null in individual rows. ---
    # INV-4: an absent source measure stays NULL -- it is NEVER synthesized as 0.0 (a real zero
    # revision would be indistinguishable from "not reported" if we filled). ``changes`` is a
    # DEPRECATED nullable column (SILVER-F030 ADR); the five BF-W2 net-commitment fields are
    # absent only from a payload the source had not yet extended -- and MEASURED 2026-09-04, raw
    # holds no such vintage: 446 of 446 dated objects across 20260712..20260904 carry all five,
    # and sampled UNDATED backfill payloads (down to market_year 1993) carry them too. So in
    # practice they are absent only from a frame whose BRONZE predates this promotion, never
    # because the source withheld them. Both cases: NaN stays NaN, and the column EXISTS
    # either way so the silver schema does not depend on which vintage produced the frame.
    for _col in _NULLABLE_MEASURE_COLS:
        _ensure_nullable(df, _col, commodity_code, market_year)

    # --- Type casts ---
    df["week_ending_date"] = pd.to_datetime(
        df["week_ending_date"], errors="coerce"
    ).dt.date

    for col in _FLOAT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")

    for col in _FLOAT64_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

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
