"""Silver transform for USDA FAS Export Sales Reporting (ESR) data.

Converts a bronze ESR DataFrame into a silver DataFrame.

Design notes
------------
* **Wide format** — one row per (country_code, week_ending_date).  Quantity
  columns appear side-by-side rather than melted into variable/value pairs.
  This makes feature engineering (pace ratios, z-scores) straightforward
  without a pivot step.

* **1000 MT units** — all quantity columns are divided by 1,000 so that values
  are expressed in *thousands of metric tonnes* (the USDA WASDE standard).
  Column names carry the ``_1000mt`` suffix to make the unit explicit.
  ``unit_id=1`` (raw metric tonnes) is the only unit observed across all ten
  ESR commodity codes.  If a future API update introduces a different unit the
  transform raises ``ValueError`` rather than silently producing wrong values.

* **market_year parameter** — the ESR API response does not include the
  ``marketYear`` field in historical records.  The caller (backfill script or
  Airflow task) passes ``market_year`` directly because it is encoded in the
  bronze S3 partition path.

* **Immutable snapshots** — ``as_of_date`` is preserved from the bronze row so
  the silver layer retains full point-in-time history for backtesting.

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Mapping from ESR commodity_code to the canonical Leviathan commodity slug.
# Codes without a direct futures contract (104, 107, 701) use descriptive
# strings so that Athena queries remain self-documenting.
_COMMODITY_CODE_TO_NAME: dict[int, str] = {
    101: "hard_red_winter_wheat_kcbt",
    102: "soft_red_winter_wheat_cbot",
    103: "hard_red_spring_wheat_mgex",
    104: "white_wheat",
    107: "all_wheat",
    401: "corn_cbot",
    701: "grain_sorghum",
    801: "soybeans_cbot",
    901: "soybean_meal_cbot",
    902: "soybean_oil_cbot",
}

# unit_id → multiplication factor to convert to 1000 MT.
# unit_id=1 is raw metric tonnes (MT); dividing by 1,000 gives 1000 MT.
# All ten ESR commodity codes observed in the backfill use unit_id=1.
_UNIT_TO_1000MT_FACTOR: dict[int, float] = {
    1: 0.001,  # MT → 1000 MT
}

# Quantity columns present in actual bronze ESR data (probe-verified 2026-05-24).
# These are the only fields the FAS API returns for the allCountries endpoint.
_QUANTITY_COLS: list[str] = [
    "outstanding_sales",
    "weekly_exports",
    "gross_new_sales",
    "changes",
]

# Columns that must be present in the bronze DataFrame.
_REQUIRED_COLS: frozenset[str] = frozenset({
    "commodity_code",
    "country_code",
    "week_ending_date",
    "unit_id",
    "as_of_date",
    "ingest_date",
    "source",
})


def transform_esr_bronze_to_silver(
    df: pd.DataFrame,
    market_year: int,
) -> pd.DataFrame:
    """Clean and normalise a single bronze ESR Parquet into silver.

    Args:
        df:          Bronze ESR DataFrame as loaded from Parquet.
        market_year: Marketing year start (e.g. 2024 = Sep 2024 – Aug 2025 for
                     corn).  Passed explicitly because the ESR API does not
                     include ``marketYear`` in its response payload.

    Returns:
        Wide-format silver DataFrame with all quantity columns expressed in
        1000 MT.  Row count is preserved except for rows where
        ``week_ending_date`` is null (dropped with a warning).

    Raises:
        ValueError: If required columns are absent from *df*, or if an
                    unrecognised ``unit_id`` value is encountered (which would
                    produce silently wrong unit conversions).
    """
    # --- Validate required columns ---
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"ESR bronze DataFrame is missing required columns: {missing}. "
            f"Got: {list(df.columns)}"
        )

    # --- Validate unit_ids ---
    unknown_units = set(df["unit_id"].dropna().unique()) - set(_UNIT_TO_1000MT_FACTOR)
    if unknown_units:
        raise ValueError(
            f"ESR bronze contains unrecognised unit_id value(s): {unknown_units}. "
            "Update _UNIT_TO_1000MT_FACTOR before proceeding."
        )

    df = df.copy()

    # --- Drop rows with null week_ending_date ---
    null_dates = df["week_ending_date"].isna().sum()
    if null_dates:
        logger.warning(
            "market_year=%d: dropping %d row(s) with null week_ending_date",
            market_year,
            null_dates,
        )
        df = df.dropna(subset=["week_ending_date"]).reset_index(drop=True)

    # --- Add derived columns ---
    df["commodity_name"] = (
        df["commodity_code"].map(_COMMODITY_CODE_TO_NAME).fillna("unknown")
    )
    df["market_year"] = pd.array([market_year] * len(df), dtype="Int16")

    # --- Unit conversion: MT → 1000 MT ---
    factor_series = df["unit_id"].map(_UNIT_TO_1000MT_FACTOR)

    for col in _QUANTITY_COLS:
        if col in df.columns:
            df[f"{col}_1000mt"] = (df[col] * factor_series).astype("float32")
            df = df.drop(columns=[col])

    # --- Rename unit_id to source_unit_id for audit clarity ---
    df = df.rename(columns={"unit_id": "source_unit_id"})

    # --- Final column order ---
    base_cols = [
        "commodity_code",
        "commodity_name",
        "market_year",
        "country_code",
        "week_ending_date",
    ]
    quantity_cols = [f"{c}_1000mt" for c in _QUANTITY_COLS if f"{c}_1000mt" in df.columns]
    meta_cols = ["source_unit_id", "as_of_date", "ingest_date", "source"]

    ordered = base_cols + quantity_cols + meta_cols
    df = df[[c for c in ordered if c in df.columns]]

    logger.info(
        "ESR silver transform: commodity_code=%s market_year=%d rows=%d",
        df["commodity_code"].iloc[0] if len(df) else "?",
        market_year,
        len(df),
    )

    return df
