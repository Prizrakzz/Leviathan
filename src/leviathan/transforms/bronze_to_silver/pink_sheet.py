"""World Bank Pink Sheet bronze -> silver transforms (SILVER-F063: all 80 columns).

Reads the long-format bronze Parquet produced by ``pink_sheet_task.py`` and produces a single
wide-format silver table:

``silver/pink_sheet/part-000.parquet``
    One row per calendar month (1960-01 onward). Contains the 80-column contract pinned by the
    SILVER-F010 registry (``configs/silver/tables/silver_pink_sheet.yaml``):

    * 37 governed price series (6 fertilizer/energy + 9 SILVER-F023 commodity-price + 22 added by
      SILVER-F063), each mapped from an explicit bronze ``series_name`` alias and carried in its
      governed unit (see :data:`_SERIES_UNIT_SCALE`);
    * ``blended_npk_index`` -- equal-weight average of urea, DAP, and potassium fertilizer prices
      (NaN when any component is unavailable, i.e. pre-1967);
    * a rolling 5-year (60-month, min 3 years) z-score for each of the 37 price series and the
      blended index -- 38 z-score columns;
    * ``date`` / ``year`` / ``month`` and ``latest_release_ym`` (which monthly release last set each
      row's values; tracks WB retroactive revisions).

SILVER-F063 -- THE SERIES WIDENING (2026-08-20)
-----------------------------------------------
The workbook carries 71 monthly series; the producer carried 15 of them. That is the same
projection-failure class as the PSD 13-of-63 census. F063 raises the kept set to 37 and, in the
raw->bronze module beside this one, makes the other 34 an explicit written REFUSAL with a
header-drift warning behind it.

The 22 new legs are the PRICE HALF of quantifying the D15 context nodes: nine price
``context_commodities`` that had narrative coverage and no price at all (coconut, peanut x2,
palm_kernel, fish_meal, sunflower_oil, barley, sorghum, fresh_citrus); eleven are world benchmarks
for contract nodes the table previously declined on (cotton, rubber, arabica, robusta, cocoa, rice,
maize, EU/US sugar, beef, chicken); two complete the phosphate-fertilizer chain and give the
``metals`` macro_context slice a single leg (TSP, copper).

COLUMN ORDER IS APPEND-ONLY. The 36 pre-F063 columns keep their exact ordinals -- including
``latest_release_ym`` at position 36 -- and all 44 new columns follow it. That is deliberate and
load-bearing: an ADDITIVE Glue migration can only ``ADD COLUMNS`` at the end, so any logical
regrouping (values together, z-scores together) would have forced a REPLACE COLUMNS and put all 36
existing ordinals at risk for cosmetics. The contract order must equal the catalog order or
``tests/unit/silver/test_ddl_generation.py`` reports drift.

BYTE-IDENTITY OF THE PRE-F063 16. Every existing value column keeps its name, its unit rule and --
critically -- its hand-set ``_ZSCORE_VALID_FROM`` floor. Those six fertilizer/energy floors were set
by hand and do NOT match the flat-history rule used to derive the new ones (urea is floored at 1992
where the flat prefix ends in 1976). Re-deriving them would silently move published z-scores, so
they are frozen as-is and the new floors are derived and documented separately.

Multi-release deduplication
---------------------------
The Pink Sheet is cumulative: every monthly release contains the full history back to 1960. When
multiple releases are present in bronze, we first normalize each row's ``series_name`` to its
governed silver name, then keep the latest release's value for each (date, series_name) pair before
pivoting. Normalizing BEFORE the dedup collapses releases written under different naming conventions
(pre-F023 governed names vs raw World Bank names) onto a single key -- otherwise both survive the
dedup and pivot into two columns that then rename to the same governed name (a hard ValueError in the
downstream z-score loop).

This also makes the F063 rollout safe across a MIXED bronze estate: a bronze release written by the
pre-F063 extractor carries only 15 series, and the "ensure all value columns present" step fills the
other 22 with NaN rather than failing. Because every WB release restates 1960-onward in full, ONE
re-extracted release backfills all 798 months of every new column.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Governed bronze series_name -> silver column name (all 37 price series).
#
# Naming convention (measured from the pre-F063 table, followed exactly):
#   <commodity>_usd_<unit>, where the unit is the CONTRACT unit, not the source unit.
#   * fertilizer / energy / mineral legs use  _usd_mt / _usd_mmbtu / _usd_bbl
#   * agricultural commodity legs use         _usd_t
# The mt/t split between fertilizer and ag columns is a pre-existing inconsistency in the shipped
# contract (both mean tonnes). It is PRESERVED, not corrected -- renaming a live column is a
# feature-visible schema regression, and this wave adds columns, it does not rewrite them.
#
# Every WB series reported in $/kg is scaled to $/tonne and named _usd_t, following the ONE existing
# precedent (sugar_world_usd_kg -> raw_sugar_world_usd_t). That gives the table a SINGLE agricultural
# unit, so any two ag columns can be differenced directly. It matters most for sugar: the world/EU/US
# policy wedge is a subtraction, and a table that quoted world in $/t and EU in $/kg would invite a
# 1000x error on the one comparison those columns exist to support.
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
    # SILVER-F063 (a) -- pricing legs for D15 context_commodity nodes
    "coconut_oil_usd_mt":               "coconut_oil_usd_t",
    "groundnuts_usd_mt":                "groundnuts_usd_t",
    "groundnut_oil_usd_mt":             "groundnut_oil_usd_t",
    "palm_kernel_oil_usd_mt":           "palm_kernel_oil_usd_t",
    "fish_meal_usd_mt":                 "fish_meal_usd_t",
    "sunflower_oil_usd_mt":             "sunflower_oil_usd_t",
    "barley_usd_mt":                    "barley_usd_t",
    "sorghum_usd_mt":                   "sorghum_usd_t",
    "orange_usd_kg":                    "orange_usd_t",
    # SILVER-F063 (b) -- benchmarks quantifying existing contract nodes
    "cotton_a_index_usd_kg":            "cotton_a_index_usd_t",
    "rubber_rss3_usd_kg":               "rubber_rss3_usd_t",
    "coffee_arabica_usd_kg":            "coffee_arabica_usd_t",
    "coffee_robusta_usd_kg":            "coffee_robusta_usd_t",
    "cocoa_usd_kg":                     "cocoa_usd_t",
    "rice_thai_5pct_usd_mt":            "rice_thai_5pct_usd_t",
    "maize_usd_mt":                     "maize_usd_t",
    "sugar_eu_usd_kg":                  "raw_sugar_eu_usd_t",
    "sugar_us_usd_kg":                  "raw_sugar_us_usd_t",
    "beef_usd_kg":                      "beef_usd_t",
    "chicken_usd_kg":                   "chicken_usd_t",
    # SILVER-F063 (c) -- fertilizer chain completion + macro context
    "tsp_usd_mt":                       "tsp_usd_mt",
    "copper_usd_mt":                    "copper_usd_mt",
}

# Explicit governed unit rule per silver column: multiply the bronze value by this scale to reach the
# column's contract unit. The World Bank "Monthly Prices" nominal sheet reports 11 of the governed
# series in USD/kg; every one is scaled x1000 into the table's single agricultural unit, USD/tonne.
# Every other governed series is already reported in its contract unit (USD/mt, USD/bbl, USD/mmbtu)
# -> 1.0. (An explicit, tested rule -- never an implicit conversion.)
#
# MEASURED source units, release 2026M07 row 6: the eleven ($/kg) headers are Sugar world/EU/US,
# Cocoa, Coffee Arabica/Robusta, Orange, Beef, Chicken, Cotton A Index, Rubber RSS3.
_SERIES_UNIT_SCALE: dict[str, float] = {
    "raw_sugar_world_usd_t":  1000.0,
    "raw_sugar_eu_usd_t":     1000.0,
    "raw_sugar_us_usd_t":     1000.0,
    "cocoa_usd_t":            1000.0,
    "coffee_arabica_usd_t":   1000.0,
    "coffee_robusta_usd_t":   1000.0,
    "orange_usd_t":           1000.0,
    "beef_usd_t":             1000.0,
    "chicken_usd_t":          1000.0,
    "cotton_a_index_usd_t":   1000.0,
    "rubber_rss3_usd_t":      1000.0,
}

# The three fertilizer components that make up the blended NPK index. TSP is deliberately NOT a
# component: changing the index would rewrite a live published column.
_NPK_COLS: list[str] = ["urea_usd_mt", "dap_usd_mt", "potassium_usd_mt"]

# Rolling z-score parameters.
_ZSCORE_WINDOW: int = 60        # 5 years
_ZSCORE_MIN_PERIODS: int = 36   # 3 years minimum

# Floor year per series: z-scores before this year are nulled. Rationale: WB repeated annual
# averages 12x before monthly data existed; rolling z-scores on flat data produce near-zero std ->
# unstable z-scores.
#
# THE PRE-F063 SIXTEEN ARE FROZEN AS SHIPPED. They were hand-set and do not follow a single derivable
# rule (urea 1992 vs a flat prefix ending 1976; phosphate_rock 1960 vs a flat prefix ending 1973).
# Re-deriving them would move already-published z-scores, so they are left exactly as they were.
#
# THE 22 F063 FLOORS ARE MEASURED, NOT INFERRED -- the OP-8 inferred-floor lesson. Rule: the floor is
# the first calendar year after the CONTIGUOUS LEADING RUN of years in which all 12 monthly values are
# identical (i.e. the first year the WB published genuine monthly data); series with no such run floor
# at their first populated year. Measured 2026-08-20 against release 2026M07 (798 months,
# 1960-01..2026-06); only three of the 22 have a flat prefix at all:
#   raw_sugar_eu_usd_t  flat 1960-1963 -> 1964
#   chicken_usd_t       flat 1960      -> 1961
#   tsp_usd_mt          flat 1960-1966 -> 1967
# Also measured: the longest INTERIOR run of identical consecutive values across all 22 is 44 months
# (raw_sugar_eu), shorter than the 60-month window, so no window has zero std -- 0 infinities and 0
# zero-std divisions in the whole widened table.
_ZSCORE_VALID_FROM: dict[str, int] = {
    # --- frozen, pre-F063 -------------------------------------------------
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
    # --- SILVER-F063, measured (first-populated month in the comment) ------
    "coconut_oil_usd_t":            1960,   # first 1960-01, no flat prefix
    "groundnuts_usd_t":             1980,   # first 1980-01, no flat prefix
    "groundnut_oil_usd_t":          1960,   # first 1960-01, no flat prefix
    "palm_kernel_oil_usd_t":        1996,   # first 1996-01, no flat prefix
    "fish_meal_usd_t":              1979,   # first 1979-01, no flat prefix
    "sunflower_oil_usd_t":          2002,   # first 2002-02, no flat prefix
    "barley_usd_t":                 1960,   # first 1960-01, DISCONTINUED after 2020-08
    "sorghum_usd_t":                1960,   # first 1960-01, DISCONTINUED after 2020-08
    "orange_usd_t":                 1960,   # first 1960-01, no flat prefix
    "cotton_a_index_usd_t":         1960,   # first 1960-01, no flat prefix
    "rubber_rss3_usd_t":            1960,   # first 1960-01, no flat prefix
    "coffee_arabica_usd_t":         1960,   # first 1960-01, no flat prefix
    "coffee_robusta_usd_t":         1960,   # first 1960-01, no flat prefix
    "cocoa_usd_t":                  1960,   # first 1960-01, no flat prefix
    "rice_thai_5pct_usd_t":         1960,   # first 1960-01, no flat prefix
    "maize_usd_t":                  1960,   # first 1960-01, no flat prefix
    "raw_sugar_eu_usd_t":           1964,   # first 1960-01, MEASURED flat prefix 1960-1963
    "raw_sugar_us_usd_t":           1960,   # first 1960-01, no flat prefix
    "beef_usd_t":                   1960,   # first 1960-01, no flat prefix
    "chicken_usd_t":                1961,   # first 1960-01, MEASURED flat prefix 1960
    "tsp_usd_mt":                   1967,   # first 1960-01, MEASURED flat prefix 1960-1966
    "copper_usd_mt":                1960,   # first 1960-01, no flat prefix
}

# Ordered column list for the final silver table -- EXACTLY the 80-column registry contract order
# (configs/silver/tables/silver_pink_sheet.yaml). The order is load-bearing (INV-2 writer schema)
# and APPEND-ONLY: entries 1..36 are the pre-F063 contract verbatim; entries 37..80 are the F063
# additions, values then z-scores, in _SERIES_RENAME order.
_PRE_F063_COLUMNS: list[str] = [
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

# The 22 SILVER-F063 additions, in _SERIES_RENAME order.
_F063_VALUE_COLUMNS: list[str] = [
    "coconut_oil_usd_t",
    "groundnuts_usd_t",
    "groundnut_oil_usd_t",
    "palm_kernel_oil_usd_t",
    "fish_meal_usd_t",
    "sunflower_oil_usd_t",
    "barley_usd_t",
    "sorghum_usd_t",
    "orange_usd_t",
    "cotton_a_index_usd_t",
    "rubber_rss3_usd_t",
    "coffee_arabica_usd_t",
    "coffee_robusta_usd_t",
    "cocoa_usd_t",
    "rice_thai_5pct_usd_t",
    "maize_usd_t",
    "raw_sugar_eu_usd_t",
    "raw_sugar_us_usd_t",
    "beef_usd_t",
    "chicken_usd_t",
    "tsp_usd_mt",
    "copper_usd_mt",
]

SILVER_COLUMNS: list[str] = (
    _PRE_F063_COLUMNS
    + _F063_VALUE_COLUMNS
    + [f"{c}_zscore_5yr" for c in _F063_VALUE_COLUMNS]
)

# The 37 renamed price columns (after pivot + rename).
_VALUE_COLS: list[str] = list(_SERIES_RENAME.values())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_silver(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Transform a list of Pink Sheet bronze DataFrames into the 80-column silver table.

    Args:
        dfs: List of bronze DataFrames, one per release. Each must have columns
             ``(date, series_name, value_usd, release_ym, source)``. May be a single-element list.
             Releases written by the pre-F063 extractor carry only 15 series; the missing 22 are
             filled with NaN rather than failing.

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
    # Step 0 -- normalize series_name to the governed silver names in the LONG
    # frame, BEFORE the dedup. Releases predating the F023 rewrite already carry
    # governed names (e.g. soybeans_usd_t) while newer releases carry the raw
    # World Bank names (e.g. soybeans_usd_mt) that _SERIES_RENAME maps to the same
    # governed column. Renaming here makes both conventions share one dedup key so
    # the (date, series_name) dedup below collapses the cross-convention duplicate;
    # otherwise both survive and pivot into two columns that rename to the same
    # name. ``replace`` leaves any non-mapped series_name untouched.
    # ------------------------------------------------------------------
    combined["series_name"] = combined["series_name"].replace(_SERIES_RENAME)

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
    # Step 3 -- pivot long -> wide. series_name was already normalized to the
    # governed silver column names in Step 0, so no post-pivot rename is needed.
    # ------------------------------------------------------------------
    wide = deduped.pivot(index="date", columns="series_name", values="value_usd")
    wide.columns.name = None
    wide = wide.reset_index()

    # Defensive: after Step 0 normalization the pivot columns must be unique. A
    # duplicate here would mean an un-normalized cross-convention alias slipped
    # past the dedup and would otherwise crash the z-score loop below with an
    # opaque "multiple columns to the single column" ValueError.
    if wide.columns.duplicated().any():
        dupes = sorted(set(wide.columns[wide.columns.duplicated()]))
        raise ValueError(
            f"pink_sheet pivot produced duplicate columns {dupes}; series_name "
            "normalization (Step 0) did not collapse a cross-convention alias."
        )

    # Ensure all 37 value columns are present even if a series was absent from this bronze slice
    # (a pre-F063 bronze release carries only 15).
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
        std = roll.std()
        # OPTION A (owner-ratified 2026-08-20): a window with NO dispersion has no z-score. WB
        # pinned phosphate rock at 44.0 for 102 consecutive months (1999-03..2007-08) and potash
        # for 138 -- both longer than the 60-month window, so those windows divide 0/0 and the
        # published value depended on the numpy BUILD (live parquet held 0.0, a recompute NaN).
        # A z of 0.0 asserts "exactly at the 5-year mean", a claim constant data cannot support:
        # the honest value is NULL. The epsilon also future-proofs urea + US natgas, both at
        # 48-month flat runs today, 12 months from tipping. Census: the flat-run table in the
        # D-EC plan, 2026-08-20.
        std = std.where(std > 1e-9)
        wide[z_col] = (wide[col] - roll.mean()) / std

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
