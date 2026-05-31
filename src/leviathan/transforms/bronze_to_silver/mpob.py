"""Silver transform for MPOB (Malaysian Palm Oil Board) annual statistics.

Converts the EAV bronze Parquets into a wide monthly time-series with one row
per (year, month) and key supply/demand metrics pre-computed.

Design notes
------------
* **Source**: annual_summary bronze only.  monthly_release bronze is sparse
  (single month in S3) and uses a different schema; it is excluded from this
  transform.

* **Variable mapping** — the bronze EAV variable column uses the pattern
  ``{section}__{commodity}`` after the bronze-transform fix.  This transform
  selects five canonical variables:

      production__crude_palm_oil   → production_cpo_mt
      closing_stocks__palm_oil     → closing_stocks_palm_oil_mt
      exports__palm_oil            → exports_palm_oil_mt
      imports__palm_oil            → imports_palm_oil_mt
      ffb_price__ffb               → ffb_price_myr_per_mt

  ``imports__palm_oil`` corresponds to the "Palm Oil (CPO+PPO)" row in the
  MPOB HTML table (total palm oil imports, not just CPO).

* **Deduplication across files** — each annual_summary file includes one
  overlap month (December of the prior year for context).  After concatenating
  all years, rows are deduplicated on (year, month, variable) — keeping the
  first occurrence — before pivoting.

* **S/U ratio** — ``su_ratio`` is closing-stocks ÷ that-month's exports
  (a "months of supply" metric at current export pace).  Null when either
  component is missing or exports are zero.

* **Date column** — ``date`` is the first day of the month as a string in
  ISO format (``YYYY-MM-01``) for Athena/Parquet compatibility.

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Maps the bronze EAV variable names to silver column names.
_VAR_TO_COL: dict[str, str] = {
    "production__crude_palm_oil": "production_cpo_mt",
    "closing_stocks__palm_oil":   "closing_stocks_palm_oil_mt",
    "exports__palm_oil":          "exports_palm_oil_mt",
    "imports__palm_oil":          "imports_palm_oil_mt",
    "ffb_price__ffb":             "ffb_price_myr_per_mt",
}

# Canonical silver column order.
OUTPUT_COLUMNS: list[str] = [
    "date",
    "production_cpo_mt",
    "closing_stocks_palm_oil_mt",
    "exports_palm_oil_mt",
    "imports_palm_oil_mt",
    "ffb_price_myr_per_mt",
    "su_ratio",
    "source",
    "commodity",
]


def transform_mpob_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Transform concatenated MPOB annual_summary bronze rows to silver.

    Args:
        df: Concatenation of all annual_summary bronze Parquets.  Must
            contain columns ``(year, month, variable, value, source)``.

    Returns:
        Wide monthly DataFrame with columns defined by ``OUTPUT_COLUMNS``.
        Rows are sorted by ``date`` ascending.

    Raises:
        ValueError: If required columns are missing from ``df``.
    """
    required = {"year", "month", "variable", "value", "source"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"MPOB bronze missing columns: {sorted(missing)}")

    # Keep only the five variables needed for silver.
    wanted = set(_VAR_TO_COL.keys())
    df = df[df["variable"].isin(wanted)].copy()
    if df.empty:
        logger.warning("MPOB silver: no matching variables found in bronze input")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Deduplicate cross-year overlap (e.g. Dec 2023 appears in both the 2023
    # and 2024 annual files).  Keep the first occurrence per (year, month, var).
    df = df.drop_duplicates(subset=["year", "month", "variable"], keep="first")

    # Rename the variable values to silver column names before pivoting.
    df["variable"] = df["variable"].map(_VAR_TO_COL)

    # Preserve source — will be constant "mpob" but keep it for the pivot.
    source_val = df["source"].iloc[0] if not df.empty else "mpob"

    # Pivot EAV → wide.
    wide = df.pivot_table(
        index=["year", "month"],
        columns="variable",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # Ensure all expected metric columns exist (may be absent in sparse years).
    for col in _VAR_TO_COL.values():
        if col not in wide.columns:
            wide[col] = float("nan")

    # Derive date as first-of-month ISO string.
    wide["date"] = (
        pd.to_datetime(wide[["year", "month"]].assign(day=1))
        .dt.strftime("%Y-%m-%d")
    )

    # Compute stocks-to-exports ratio (months of supply at current export pace).
    wide["su_ratio"] = wide.apply(
        lambda r: (
            r["closing_stocks_palm_oil_mt"] / r["exports_palm_oil_mt"]
            if pd.notna(r["closing_stocks_palm_oil_mt"])
            and pd.notna(r["exports_palm_oil_mt"])
            and r["exports_palm_oil_mt"] > 0
            else float("nan")
        ),
        axis=1,
    )

    wide["source"] = source_val
    wide["commodity"] = "malaysian_crude_palm_oil_cme"

    # Sort by date and return canonical columns.
    wide = wide.sort_values("date").reset_index(drop=True)
    return wide[OUTPUT_COLUMNS]
