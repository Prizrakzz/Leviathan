"""World Bank Pink Sheet bronze -> silver transforms (SILVER-F023: all 36 columns).

Reads the long-format bronze Parquet produced by ``pink_sheet_task.py`` and produces a single
wide-format silver table:

``silver/pink_sheet/part-000.parquet``
    One row per calendar month (1960-01 onward). Contains the exact 36-column contract pinned by
    the SILVER-F010 registry (``configs/silver/tables/silver_pink_sheet.yaml``):

    * 15 governed price series (6 fertilizer/energy + 9 commodity-price), each mapped from an
      explicit bronze ``series_name`` alias and carried in its governed unit (see
      :data:`_SERIES_UNIT_SCALE`);
    * ``blended_npk_index`` -- equal-weight average of urea, DAP, and potassium fertilizer prices
      (NaN when any component is unavailable, i.e. pre-1967);
    * a rolling 5-year (60-month, min 3 years) z-score for each of the 15 price series and the
      blended index -- 16 z-score columns;
    * ``date`` / ``year`` / ``month`` and ``latest_release_ym`` (which monthly release last set each
      row's values; tracks WB retroactive revisions).

SILVER-F023 (OP-3 close): the pre-F023 producer emitted only 18 columns (the 6 fertilizer/energy
series + derived), which is an exact SUBSET of the live 36-column physical/Glue table. Regenerating
with that narrowed code would have silently DROPPED the 9 commodity-price series + their z-scores
(a feature-visible schema regression, INV-2). This module restores the full 36-column contract; the
governed bronze aliases + unit rules below make a forced replay from the existing raw workbook
reproduce every live column rather than remove one.

Multi-release deduplication
---------------------------
The Pink Sheet is cumulative: every monthly release contains the full history back to 1960. When
multiple releases are present in bronze, we keep the latest release's value for each
(date, series_name) pair before pivoting.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Governed bronze series_name -> silver column name (all 15 price series).
# The first 6 are the original fertilizer/energy series; the 9 below them are the commodity-price
# series that OP-3 showed the live table carries and the narrowed producer had dropped. Each bronze
# name is produced by the raw->bronze header aliases in ``raw_to_bronze/world_bank_pink_sheet.py``.
# ---------------------------------------------------------------------------
_SERIES_RENAME: dict[str, str] = {
    # fertilizer + energy
    "urea_e_europe_bulk_spot_usd_mt":   "urea_usd_mt",
    "dap_spot_usd_mt":                  "dap_usd_mt",
    "potassium_chloride_std_usd_mt":    "potassium_usd_mt",
    "natural_gas_us_usd_mmbtu":         "natural_gas_us_usd_mmbtu",
    "natural_gas_europe_usd_mmbtu":     "natural_gas_eu_usd_mmbtu",
    "phosphate_rock_usd_mt":            "phosphate_rock_usd_mt",
    # commodity prices (SILVER-F023 restoration)
    "crude_oil_brent_usd_bbl":          "brent_crude_usd_bbl",
    "soybeans_usd_mt":                  "soybeans_usd_t",
    "soybean_oil_usd_mt":               "soybean_oil_usd_t",
    "soybean_meal_usd_mt":              "soybean_meal_usd_t",
    "palm_oil_usd_mt":                  "palm_oil_cpo_usd_t",
    "sugar_world_usd_kg":               "raw_sugar_world_usd_t",
    "wheat_us_hrw_usd_mt":              "wheat_us_hrw_usd_t",
    "wheat_us_srw_usd_mt":              "wheat_us_srw_usd_t",
    "rapeseed_oil_usd_mt":              "rapeseed_oil_usd_t",
}

# Explicit governed unit rule per silver column: multiply the bronze value by this scale to reach
# the column's contract unit. The World Bank "Monthly Prices" nominal sheet reports sugar in USD/kg;
# the contract column is ``raw_sugar_world_usd_t`` (USD/tonne), so sugar is scaled x1000. Every other
# governed series is already reported in its contract unit (USD/mt or USD/bbl or USD/mmbtu) -> 1.0.
# (An explicit, tested rule -- never an implicit conversion -- per the F023 "units/ambiguity" step.)
_SERIES_UNIT_SCALE: dict[str, float] = {
    "raw_sugar_world_usd_t": 1000.0,
}

# The three fertilizer components that make up the blended NPK index.
_NPK_COLS: list[str] = ["urea_usd_mt", "dap_usd_mt", "potassium_usd_mt"]

# Rolling z-score parameters.
_ZSCORE_WINDOW: int = 60        # 5 years
_ZSCORE_MIN_PERIODS: int = 36   # 3 years minimum

# Floor year per series: z-scores before this year are nulled. Rationale: WB repeated annual
# averages 12x before monthly data existed (both gas series flat until ~1985/91); rolling z-scores
# on flat data produce near-zero std -> unstable z-scores. Commodity-price series carry reliable
# monthly history from 1960, so they default to no masking (1960).
_ZSCORE_VALID_FROM: dict[str, int] = {
    "urea_usd_mt":                  1992,
    "dap_usd_mt":                   1967,
    "potassium_usd_mt":             1980,
    "natural_gas_us_usd_mmbtu":     1979,
    "natural_gas_eu_usd_mmbtu":     1991,
    "phosphate_rock_usd_mt":        1960,
    "blended_npk_index":            1967,   # depends on DAP
    "brent_crude_usd_bbl":          1960,
    "soybeans_usd_t":               1960,
    "soybean_oil_usd_t":            1960,
    "soybean_meal_usd_t":           1960,
    "palm_oil_cpo_usd_t":           1960,
    "raw_sugar_world_usd_t":        1960,
    "wheat_us_hrw_usd_t":           1960,
    "wheat_us_srw_usd_t":           1960,
    "rapeseed_oil_usd_t":           1960,
}

# Ordered column list for the final silver table -- EXACTLY the 36-column registry contract order
# (configs/silver/tables/silver_pink_sheet.yaml). The order is load-bearing (INV-2 writer schema).
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
    "brent_crude_usd_bbl",
    "blended_npk_index",
    "soybeans_usd_t",
    "soybean_oil_usd_t",
    "soybean_meal_usd_t",
    "palm_oil_cpo_usd_t",
    "raw_sugar_world_usd_t",
    "wheat_us_hrw_usd_t",
    "wheat_us_srw_usd_t",
    "rapeseed_oil_usd_t",
    "urea_usd_mt_zscore_5yr",
    "dap_usd_mt_zscore_5yr",
    "potassium_usd_mt_zscore_5yr",
    "natural_gas_us_usd_mmbtu_zscore_5yr",
    "natural_gas_eu_usd_mmbtu_zscore_5yr",
    "phosphate_rock_usd_mt_zscore_5yr",
    "brent_crude_usd_bbl_zscore_5yr",
    "blended_npk_index_zscore_5yr",
    "soybeans_usd_t_zscore_5yr",
    "soybean_oil_usd_t_zscore_5yr",
    "soybean_meal_usd_t_zscore_5yr",
    "palm_oil_cpo_usd_t_zscore_5yr",
    "raw_sugar_world_usd_t_zscore_5yr",
    "wheat_us_hrw_usd_t_zscore_5yr",
    "wheat_us_srw_usd_t_zscore_5yr",
    "rapeseed_oil_usd_t_zscore_5yr",
    "latest_release_ym",
]

# The 15 renamed price columns (after pivot + rename).
_VALUE_COLS: list[str] = list(_SERIES_RENAME.values())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_silver(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Transform a list of Pink Sheet bronze DataFrames into the 36-column silver table.

    Args:
        dfs: List of bronze DataFrames, one per release. Each must have columns
             ``(date, series_name, value_usd, release_ym, source)``. May be a single-element list.

    Returns:
        A DataFrame with columns matching :data:`SILVER_COLUMNS` (exact order), sorted by ``date``
        ascending. Returns an empty DataFrame with those columns if ``dfs`` is empty/all-empty.
    """
    if not dfs:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    combined = pd.concat(dfs, ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    # ------------------------------------------------------------------
    # Step 1 -- deduplicate: keep latest release per (date, series_name)
    # release_ym is "YYYYMmm" (e.g. "2026M05"); sortable as int after stripping "M".
    # ------------------------------------------------------------------
    combined["_release_sort"] = (
        combined["release_ym"].str.replace("M", "", regex=False).astype(int)
    )
    combined_sorted = combined.sort_values("_release_sort", ascending=False)
    deduped = combined_sorted.drop_duplicates(
        subset=["date", "series_name"], keep="first"
    ).copy()

    # ------------------------------------------------------------------
    # Step 2 -- capture latest_release_ym per date (fixed-width YYYYMmm => lexicographic == numeric)
    # ------------------------------------------------------------------
    latest_ym = (
        deduped.groupby("date")["release_ym"]
        .max()
        .reset_index()
        .rename(columns={"release_ym": "latest_release_ym"})
    )

    # ------------------------------------------------------------------
    # Step 3 -- pivot long -> wide, rename bronze series to silver columns
    # ------------------------------------------------------------------
    wide = deduped.pivot(index="date", columns="series_name", values="value_usd")
    wide.columns.name = None
    wide = wide.reset_index()
    wide = wide.rename(columns=_SERIES_RENAME)

    # Ensure all 15 value columns are present even if a series was absent from this bronze slice.
    for col in _VALUE_COLS:
        if col not in wide.columns:
            wide[col] = float("nan")

    # ------------------------------------------------------------------
    # Step 3b -- apply governed unit scales (explicit, per-series; default 1.0)
    # ------------------------------------------------------------------
    for col, scale in _SERIES_UNIT_SCALE.items():
        if col in wide.columns and scale != 1.0:
            wide[col] = wide[col] * scale

    # ------------------------------------------------------------------
    # Step 4 -- cast date; derive year and month
    # ------------------------------------------------------------------
    wide["date"] = pd.to_datetime(wide["date"])
    wide = wide.sort_values("date").reset_index(drop=True)
    wide["year"] = wide["date"].dt.year.astype(int)
    wide["month"] = wide["date"].dt.month.astype(int)

    # ------------------------------------------------------------------
    # Step 5 -- blended NPK index (equal-weight; NaN if any component NaN)
    # ------------------------------------------------------------------
    wide["blended_npk_index"] = wide[_NPK_COLS].mean(axis=1, skipna=False)

    # ------------------------------------------------------------------
    # Step 6 -- rolling 5-year z-scores for every price series + the blended index
    # ------------------------------------------------------------------
    for col in _VALUE_COLS + ["blended_npk_index"]:
        z_col = f"{col}_zscore_5yr"
        roll = wide[col].rolling(_ZSCORE_WINDOW, min_periods=_ZSCORE_MIN_PERIODS)
        wide[z_col] = (wide[col] - roll.mean()) / roll.std()

    # ------------------------------------------------------------------
    # Step 7 -- null z-scores before each series' reliable history start
    # ------------------------------------------------------------------
    for col, floor_year in _ZSCORE_VALID_FROM.items():
        z_col = f"{col}_zscore_5yr"
        if z_col in wide.columns:
            wide.loc[wide["year"] < floor_year, z_col] = None

    # ------------------------------------------------------------------
    # Step 8 -- join latest_release_ym back on date
    # ------------------------------------------------------------------
    latest_ym["date"] = pd.to_datetime(latest_ym["date"])
    wide = wide.merge(latest_ym, on="date", how="left")

    return wide[SILVER_COLUMNS].reset_index(drop=True)
