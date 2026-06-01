"""World Bank Pink Sheet bronze → silver transforms.

Reads the long-format bronze Parquet produced by ``pink_sheet_task.py`` and
produces a single wide-format silver table:

``silver/pink_sheet/part-000.parquet``
    One row per calendar month (1960-01 onward).  Contains:

    * Six business-friendly price columns (USD/mt or USD/mmbtu).
    * ``blended_npk_index`` — equal-weight average of urea, DAP, and potassium
      fertilizer prices (NaN when any component is unavailable, i.e. pre-1967).
    * Rolling 5-year (60-month, min 3 years) z-score for each price series and
      the blended index.  Z-scores are nulled before each series' reliable
      monthly history start to avoid artefacts from the pre-1991 annual-fill era
      (WB repeated a single annual estimate across all 12 months pre-1985/91).
    * ``latest_release_ym`` — which monthly Pink Sheet release last set each
      row's values; tracks WB retroactive revisions.

Multi-release deduplication
---------------------------
The Pink Sheet is cumulative: every monthly release contains the full history
back to 1960.  When multiple releases are present in bronze, we keep the latest
release's value for each (date, series_name) pair before pivoting.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map bronze series_name → silver column name.
_SERIES_RENAME: dict[str, str] = {
    "urea_e_europe_bulk_spot_usd_mt":   "urea_usd_mt",
    "dap_spot_usd_mt":                  "dap_usd_mt",
    "potassium_chloride_std_usd_mt":    "potassium_usd_mt",
    "natural_gas_us_usd_mmbtu":         "natural_gas_us_usd_mmbtu",
    "natural_gas_europe_usd_mmbtu":     "natural_gas_eu_usd_mmbtu",
    "phosphate_rock_usd_mt":            "phosphate_rock_usd_mt",
}

# The three fertilizer components that make up the blended NPK index.
_NPK_COLS: list[str] = ["urea_usd_mt", "dap_usd_mt", "potassium_usd_mt"]

# Rolling z-score parameters.
_ZSCORE_WINDOW: int = 60        # 5 years
_ZSCORE_MIN_PERIODS: int = 36   # 3 years minimum

# Floor year per series: z-scores before this year are nulled.
# Rationale: WB repeated annual averages 12× before monthly data existed
# (both gas series flat until ~1985/91).  Rolling z-scores on flat data
# produce near-zero std → unstable or infinite z-scores.
_ZSCORE_VALID_FROM: dict[str, int] = {
    "urea_usd_mt":                  1992,
    "dap_usd_mt":                   1967,
    "potassium_usd_mt":             1980,
    "natural_gas_us_usd_mmbtu":     1979,
    "natural_gas_eu_usd_mmbtu":     1991,
    "phosphate_rock_usd_mt":        1960,
    "blended_npk_index":            1967,   # depends on DAP
}

# Ordered column list for the final silver table (18 columns).
SILVER_COLUMNS: list[str] = [
    "date",
    "year",
    "month",
    "urea_usd_mt",
    "dap_usd_mt",
    "potassium_usd_mt",
    "natural_gas_us_usd_mmbtu",
    "natural_gas_eu_usd_mmbtu",
    "phosphate_rock_usd_mt",
    "blended_npk_index",
    "urea_usd_mt_zscore_5yr",
    "dap_usd_mt_zscore_5yr",
    "potassium_usd_mt_zscore_5yr",
    "natural_gas_us_usd_mmbtu_zscore_5yr",
    "natural_gas_eu_usd_mmbtu_zscore_5yr",
    "phosphate_rock_usd_mt_zscore_5yr",
    "blended_npk_index_zscore_5yr",
    "latest_release_ym",
]

# The six renamed price columns (after pivot + rename).
_VALUE_COLS: list[str] = list(_SERIES_RENAME.values())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_silver(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Transform a list of Pink Sheet bronze DataFrames into the silver table.

    Args:
        dfs: List of bronze DataFrames, one per release.  Each must have
             columns ``(date, series_name, value_usd, release_ym, source)``.
             May be a single-element list (only one release ingested so far).

    Returns:
        A DataFrame with columns matching :data:`SILVER_COLUMNS`, sorted by
        ``date`` ascending.  Returns an empty DataFrame with those columns if
        ``dfs`` is empty or all inputs are empty.
    """
    if not dfs:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    combined = pd.concat(dfs, ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    # ------------------------------------------------------------------
    # Step 1 — deduplicate: keep latest release per (date, series_name)
    # ------------------------------------------------------------------
    # release_ym is "YYYYMmm" (e.g. "2026M05"); sortable as int after
    # stripping "M".
    combined["_release_sort"] = (
        combined["release_ym"].str.replace("M", "", regex=False).astype(int)
    )
    combined_sorted = combined.sort_values("_release_sort", ascending=False)
    deduped = combined_sorted.drop_duplicates(
        subset=["date", "series_name"], keep="first"
    ).copy()

    # ------------------------------------------------------------------
    # Step 2 — capture latest_release_ym per date (after dedup, groupby
    # date and take the maximum release_ym string — lexicographic order
    # matches numeric order because format is fixed-width YYYYMmm).
    # ------------------------------------------------------------------
    latest_ym = (
        deduped.groupby("date")["release_ym"]
        .max()
        .reset_index()
        .rename(columns={"release_ym": "latest_release_ym"})
    )

    # ------------------------------------------------------------------
    # Step 3 — pivot long → wide
    # ------------------------------------------------------------------
    wide = deduped.pivot(index="date", columns="series_name", values="value_usd")
    wide.columns.name = None
    wide = wide.reset_index()

    # Rename bronze series names to silver column names.
    wide = wide.rename(columns=_SERIES_RENAME)

    # Ensure all six value columns are present even if a series was absent
    # (defensive; should not happen with a well-formed bronze layer).
    for col in _VALUE_COLS:
        if col not in wide.columns:
            wide[col] = float("nan")

    # ------------------------------------------------------------------
    # Step 4 — cast date; derive year and month
    # ------------------------------------------------------------------
    wide["date"] = pd.to_datetime(wide["date"])
    wide = wide.sort_values("date").reset_index(drop=True)
    wide["year"] = wide["date"].dt.year.astype(int)
    wide["month"] = wide["date"].dt.month.astype(int)

    # ------------------------------------------------------------------
    # Step 5 — blended NPK index (equal-weight; NaN if any component NaN)
    # ------------------------------------------------------------------
    wide["blended_npk_index"] = wide[_NPK_COLS].mean(axis=1, skipna=False)

    # ------------------------------------------------------------------
    # Step 6 — rolling 5-year z-scores
    # ------------------------------------------------------------------
    for col in _VALUE_COLS + ["blended_npk_index"]:
        z_col = f"{col}_zscore_5yr"
        roll = wide[col].rolling(_ZSCORE_WINDOW, min_periods=_ZSCORE_MIN_PERIODS)
        wide[z_col] = (wide[col] - roll.mean()) / roll.std()

    # ------------------------------------------------------------------
    # Step 7 — null z-scores before each series' reliable history start
    # ------------------------------------------------------------------
    for col, floor_year in _ZSCORE_VALID_FROM.items():
        z_col = f"{col}_zscore_5yr"
        if z_col in wide.columns:
            wide.loc[wide["year"] < floor_year, z_col] = None

    # ------------------------------------------------------------------
    # Step 8 — join latest_release_ym back on date
    # ------------------------------------------------------------------
    latest_ym["date"] = pd.to_datetime(latest_ym["date"])
    wide = wide.merge(latest_ym, on="date", how="left")

    return wide[SILVER_COLUMNS].reset_index(drop=True)
