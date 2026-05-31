"""Silver transform for MPOB Overview-PDF annual statistics (2010–2016).

Converts annual EAV bronze rows (extracted from overview PDFs) into a wide
yearly time-series with one row per calendar year and key supply/demand metrics.

Design notes
------------
* **Source**: overview_pdf bronze only.  This transform is separate from the
  monthly HTML-based silver (silver/mpob/) which covers 2017–present.

* **Variable mapping** — identical to the monthly transform (_VAR_TO_COL is
  the same five variables):

      production__crude_palm_oil   → production_cpo_mt
      closing_stocks__palm_oil     → closing_stocks_palm_oil_mt
      exports__palm_oil            → exports_palm_oil_mt
      imports__palm_oil            → imports_palm_oil_mt
      ffb_price__ffb               → ffb_price_myr_per_mt

* **Granularity** — annual totals only; no ``date`` column.  ``year`` (INT)
  is the primary key.  The overview PDFs report calendar-year national figures
  (not monthly disaggregated).

* **S/U ratio** — ``su_ratio`` is closing-stocks ÷ annual exports (a rough
  "years of supply" metric at that year's export pace).  Null when either
  component is missing or exports are zero.

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Maps bronze EAV variable names to silver column names.
# Intentionally identical to the monthly mpob silver (_VAR_TO_COL in mpob.py)
# so both layers share the same column vocabulary.
_VAR_TO_COL: dict[str, str] = {
    "production__crude_palm_oil": "production_cpo_mt",
    "closing_stocks__palm_oil":   "closing_stocks_palm_oil_mt",
    "exports__palm_oil":          "exports_palm_oil_mt",
    "imports__palm_oil":          "imports_palm_oil_mt",
    "ffb_price__ffb":             "ffb_price_myr_per_mt",
}

# Canonical silver column order (no ``date`` — annual granularity only).
OUTPUT_COLUMNS: list[str] = [
    "year",
    "production_cpo_mt",
    "closing_stocks_palm_oil_mt",
    "exports_palm_oil_mt",
    "imports_palm_oil_mt",
    "ffb_price_myr_per_mt",
    "su_ratio",
    "source",
    "commodity",
]


def transform_mpob_annual_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Transform MPOB overview-PDF annual bronze rows to silver.

    Args:
        df: Concatenation of all overview_pdf bronze Parquets.  Must
            contain columns ``(year, variable, value, source)``.

    Returns:
        Wide yearly DataFrame with columns defined by ``OUTPUT_COLUMNS``,
        sorted by ``year`` ascending.  One row per calendar year.

    Raises:
        ValueError: If required columns are missing from ``df``.
    """
    required = {"year", "variable", "value", "source"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"MPOB annual bronze missing columns: {sorted(missing)}")

    wanted = set(_VAR_TO_COL.keys())
    df = df[df["variable"].isin(wanted)].copy()
    if df.empty:
        logger.warning("MPOB annual silver: no matching variables found in bronze input")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Deduplicate — should not normally occur but guard against duplicate runs.
    df = df.drop_duplicates(subset=["year", "variable"], keep="first")

    df["variable"] = df["variable"].map(_VAR_TO_COL)

    source_val = df["source"].iloc[0] if not df.empty else "mpob"

    # Pivot EAV → wide (one row per year).
    wide = df.pivot_table(
        index="year",
        columns="variable",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # Ensure all expected metric columns are present (sparse years may be missing some).
    for col in _VAR_TO_COL.values():
        if col not in wide.columns:
            wide[col] = float("nan")

    # Stocks-to-exports ratio (years of supply at that year's export pace).
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

    wide = wide.sort_values("year").reset_index(drop=True)
    return wide[OUTPUT_COLUMNS]
