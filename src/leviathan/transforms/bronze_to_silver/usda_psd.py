"""Silver transform for USDA PSD (Production, Supply and Distribution) data.

Converts a list of bronze PSD DataFrames (one per release date) into a single
silver DataFrame suitable for Tier 2 S/D balance-sheet feature engineering.

Design notes
------------
* **Wide format** — one row per (leviathan_slug, country, market_year,
  wasde_release_month, release_date).  The eight core attributes (6 S/D + area
  + yield) are pivoted to columns so that su_ratio, revision diffs, and
  area-based ratios can be computed without extra joins.

* **Contract slug fan-out** — each PSD commodity_code maps to a list of
  Leviathan contract slugs (e.g. wheat → 4 slugs covering KCBT, CBOT, MGEX,
  MATIF).  The global PSD S/D row is duplicated once per slug so that
  ``leviathan_slug`` is a universal join key consistent with ESR, FGIS, and
  other silver tables.  Downstream consumers filter to the slug(s) relevant to
  their model.

* **MT units** — all mass columns are converted to metric tonnes (MT).  Unit
  conversion happens before the pivot.  ``area_harvested_1000ha`` keeps the
  USDA native "1000 HA" unit (column name is explicit).  ``yield_mt_ha`` is
  the per-hectare yield in MT/HA; USDA reports some commodities in KG/HA which
  is divided by 1 000 before storage.

* **Consumption attribute normalisation** — sugar uses "Total Disappearance"
  (attr 126) and cotton uses "Domestic Use" (attr 142) instead of the standard
  "Domestic Consumption" (attr 125).  Both are remapped before the pivot so
  ``consumption_mt`` is uniformly named across all commodities.

* **su_ratio** — ending_stocks_mt / consumption_mt.  Zero consumption → NaN.

* **su_ratio_yoy_delta** — within each (leviathan_slug, country, release_date),
  year-over-year diff of su_ratio across market_year.  Available from the first
  release because the PSD snapshot spans ~65 marketing years.

* **revision columns** — value from this release minus the prior release for the
  same (leviathan_slug, country, market_year, wasde_release_month).  All NaN
  with a single release; populate as monthly downloads accumulate.

* **month_code = 0** — pre-WASDE-tracking historical estimates (MY ~1960–2004
  for older series).  Passed through as wasde_release_month = 0.

* **calendar_year / country_code** — dropped.  calendar_year is a batch-import
  artefact; country_code is 100% NULL in the PSD bulk CSV.

* **Sorghum excluded** — no Leviathan contract YAML exists; dropped at the
  commodity-filter step.

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Commodity fan-out: PSD 6-digit code → list of Leviathan contract slugs
# ---------------------------------------------------------------------------
# Each global S/D row is emitted once per slug in this list.  Slugs match
# the ``commodity`` field in configs/commodities/*.yaml files exactly.

_PSD_COMMODITY_TO_SLUGS: dict[int, list[str]] = {
    410000: [                              # all-class wheat aggregate
        "hard_red_winter_wheat_kcbt",
        "soft_red_winter_wheat_cbot",
        "hard_red_spring_wheat_mgex",
        "french_wheat_matif",
    ],
    440000: [                              # corn / maize aggregate
        "corn_cbot",
        "campinas_corn_reference_bmf",
        "french_maize_matif",
    ],
    422110: ["rough_rice_cbot"],           # milled rice
    2222000: [                             # soybeans aggregate
        "soybeans_cbot",
        "soybeans_no_1_dce",
        "soybeans_no_2_dce",
    ],
    813100:  ["soybean_meal_cbot", "soybean_meal_dce"],
    4232000: ["soybean_oil_cbot", "soybean_oil_dce"],
    2226000: ["canola_ice", "french_rapeseed_matif"],
    4239100: ["rapeseed_oil_zce"],
    813600:  ["rapeseed_meal_zce"],
    4243000: ["palm_olein_dce", "malaysian_crude_palm_oil_cme"],
    612000:  ["raw_sugar", "white_sugar"],
    711100:  ["arabica_coffee", "robusta_coffee"],
    2631000: ["cotton"],
}

# ---------------------------------------------------------------------------
# Unit conversion: native PSD unit_desc → factor applied to raw value
# ---------------------------------------------------------------------------
# Result is MT for mass columns, 1000 HA for area, MT/HA for yield.

_UNIT_FACTOR: dict[str, float] = {
    "(1000 MT)":          1_000.0,    # grains, oilseeds, oils, sugar, etc.
    "(MT)":               1.0,        # specialty nuts (not in scope but safe)
    "1000 480 lb. Bales": 217.724,    # cotton: 1 bale = 480 lb; 1000 bales → MT
    "(1000 60 KG BAGS)":  60.0,       # coffee: 1000 bags × 60 kg → MT
    "(1000 HA)":          1.0,        # area harvested (keep 1000 HA, col name says so)
    "(MT/HA)":            1.0,        # yield already in MT/HA
    "(KG/HA)":            0.001,      # yield in KG/HA → divide by 1000 → MT/HA
}

# ---------------------------------------------------------------------------
# Attribute normalisation
# ---------------------------------------------------------------------------

# The eight attributes we pivot to columns.
_TARGET_ATTRS: frozenset[str] = frozenset({
    "Beginning Stocks",
    "Production",
    "Imports",
    "Exports",
    "Ending Stocks",
    "Domestic Consumption",
    "Area Harvested",
    "Yield",
})

# Silver column names for each attribute_desc after pivot.
_ATTR_TO_COL: dict[str, str] = {
    "Beginning Stocks":   "beginning_stocks_mt",
    "Production":         "production_mt",
    "Imports":            "imports_mt",
    "Exports":            "exports_mt",
    "Ending Stocks":      "ending_stocks_mt",
    "Domestic Consumption": "consumption_mt",
    "Area Harvested":     "area_harvested_1000ha",
    "Yield":              "yield_mt_ha",
}

# Consumption attribute_desc in bronze for slugs that deviate from the default.
_SUGAR_CONSUMPTION_ATTR  = "Total Disappearance"   # attr_id 126
_COTTON_CONSUMPTION_ATTR = "Domestic Use"           # attr_id 142

_SUGAR_SLUGS:  frozenset[str] = frozenset({"raw_sugar", "white_sugar"})
_COTTON_SLUGS: frozenset[str] = frozenset({"cotton"})

# ---------------------------------------------------------------------------
# Required columns in bronze DataFrames
# ---------------------------------------------------------------------------

_REQUIRED_COLS: frozenset[str] = frozenset({
    "commodity_code",
    "commodity_desc",
    "country_name",
    "market_year",
    "month_code",
    "attribute_desc",
    "unit_desc",
    "value",
    "release_date",
})

# ---------------------------------------------------------------------------
# Final column order for silver output (18 columns)
# ---------------------------------------------------------------------------

_SILVER_COLS: list[str] = [
    "leviathan_slug",
    "country",
    "market_year",
    "wasde_release_month",
    "release_date",
    "beginning_stocks_mt",
    "production_mt",
    "imports_mt",
    "exports_mt",
    "ending_stocks_mt",
    "consumption_mt",
    "area_harvested_1000ha",
    "yield_mt_ha",
    "su_ratio",
    "su_ratio_yoy_delta",
    "production_mt_revision",
    "ending_stocks_mt_revision",
    "consumption_mt_revision",
]

# ---------------------------------------------------------------------------
# Public transform
# ---------------------------------------------------------------------------


def transform_psd_bronze_to_silver(
    dfs: list[pd.DataFrame],
) -> pd.DataFrame:
    """Convert one or more bronze PSD DataFrames into a single silver DataFrame.

    Each element of *dfs* is one ``release_date`` partition read from S3
    (``bronze/production/source=usda_psd/release_date=.../part-000.parquet``).
    Passing multiple DataFrames enables revision-diff computation across
    sequential WASDE releases.

    Args:
        dfs: List of bronze DataFrames.  Must be non-empty.

    Returns:
        Wide-format silver DataFrame with :data:`_SILVER_COLS` columns.

    Raises:
        ValueError: If *dfs* is empty, required columns are missing, or an
                    unrecognised ``unit_desc`` appears for an in-scope row.
    """
    if not dfs:
        raise ValueError("dfs must contain at least one DataFrame")

    # -----------------------------------------------------------------------
    # 1. Validate required columns
    # -----------------------------------------------------------------------
    for i, df in enumerate(dfs):
        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(
                f"PSD bronze DataFrame[{i}] missing required columns: {missing}. "
                f"Got: {list(df.columns)}"
            )

    # -----------------------------------------------------------------------
    # 2. Concatenate all release snapshots
    # -----------------------------------------------------------------------
    combined = pd.concat(dfs, ignore_index=True)

    # -----------------------------------------------------------------------
    # 3. Filter to in-scope commodity codes
    # -----------------------------------------------------------------------
    in_scope_mask = combined["commodity_code"].isin(_PSD_COMMODITY_TO_SLUGS)
    n_dropped = int((~in_scope_mask).sum())
    if n_dropped:
        logger.info("PSD transform: dropping %d out-of-scope rows", n_dropped)
    combined = combined[in_scope_mask].copy()

    if combined.empty:
        logger.warning("PSD transform: no in-scope rows remain after commodity filter")
        return _empty_silver()

    # -----------------------------------------------------------------------
    # 4. Fan-out: explode each commodity row to one row per contract slug
    # -----------------------------------------------------------------------
    combined["leviathan_slug"] = combined["commodity_code"].map(_PSD_COMMODITY_TO_SLUGS)
    combined = combined.explode("leviathan_slug").reset_index(drop=True)

    # -----------------------------------------------------------------------
    # 5. Remap non-standard consumption attribute labels → "Domestic Consumption"
    # -----------------------------------------------------------------------
    sugar_mask = (
        combined["leviathan_slug"].isin(_SUGAR_SLUGS)
        & (combined["attribute_desc"] == _SUGAR_CONSUMPTION_ATTR)
    )
    combined.loc[sugar_mask, "attribute_desc"] = "Domestic Consumption"

    cotton_mask = (
        combined["leviathan_slug"].isin(_COTTON_SLUGS)
        & (combined["attribute_desc"] == _COTTON_CONSUMPTION_ATTR)
    )
    combined.loc[cotton_mask, "attribute_desc"] = "Domestic Consumption"

    # -----------------------------------------------------------------------
    # 6. Filter to the eight target attributes
    # -----------------------------------------------------------------------
    combined = combined[combined["attribute_desc"].isin(_TARGET_ATTRS)].copy()

    if combined.empty:
        logger.warning("PSD transform: no rows remain after attribute filter")
        return _empty_silver()

    # -----------------------------------------------------------------------
    # 7. Validate unit_desc (only in-scope rows, so limited to known units)
    # -----------------------------------------------------------------------
    unknown_units = set(combined["unit_desc"].unique()) - set(_UNIT_FACTOR)
    if unknown_units:
        raise ValueError(
            f"PSD bronze contains unrecognised unit_desc for in-scope rows: "
            f"{unknown_units}. Update _UNIT_FACTOR to avoid wrong conversions."
        )

    # -----------------------------------------------------------------------
    # 8. Convert values using unit_desc factor
    # -----------------------------------------------------------------------
    factor_series = combined["unit_desc"].map(_UNIT_FACTOR)
    combined["value_mt"] = combined["value"] * factor_series

    # -----------------------------------------------------------------------
    # 9. Rename index columns
    # -----------------------------------------------------------------------
    combined = combined.rename(columns={
        "country_name": "country",
        "month_code":   "wasde_release_month",
    })

    # -----------------------------------------------------------------------
    # 10. Dedup before pivot (keep first occurrence per key)
    # -----------------------------------------------------------------------
    pivot_index = [
        "leviathan_slug",
        "country",
        "market_year",
        "wasde_release_month",
        "release_date",
    ]
    dedup_key = pivot_index + ["attribute_desc"]
    n_dupes = int(combined.duplicated(subset=dedup_key).sum())
    if n_dupes:
        logger.warning(
            "PSD transform: %d duplicate (index + attribute_desc) rows; keeping first",
            n_dupes,
        )
        combined = combined.drop_duplicates(subset=dedup_key, keep="first")

    # -----------------------------------------------------------------------
    # 11. Pivot attribute_desc → wide columns
    # -----------------------------------------------------------------------
    wide = combined.pivot_table(
        index=pivot_index,
        columns="attribute_desc",
        values="value_mt",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # Rename attribute columns to silver names
    wide = wide.rename(columns=_ATTR_TO_COL)

    # Guarantee all eight pivot columns exist even if absent in this snapshot
    for col in _ATTR_TO_COL.values():
        if col not in wide.columns:
            wide[col] = np.nan

    # -----------------------------------------------------------------------
    # 12. Compute su_ratio
    # -----------------------------------------------------------------------
    with np.errstate(divide="ignore", invalid="ignore"):
        wide["su_ratio"] = wide["ending_stocks_mt"] / wide["consumption_mt"]
    wide["su_ratio"] = wide["su_ratio"].replace([np.inf, -np.inf], np.nan)

    # -----------------------------------------------------------------------
    # 13. Compute su_ratio_yoy_delta
    # Within each (leviathan_slug, country, release_date), diff su_ratio by
    # market_year ascending.
    # -----------------------------------------------------------------------
    wide = wide.sort_values(
        ["leviathan_slug", "country", "release_date", "market_year"]
    ).copy()
    wide["su_ratio_yoy_delta"] = wide.groupby(
        ["leviathan_slug", "country", "release_date"]
    )["su_ratio"].diff(1)

    # -----------------------------------------------------------------------
    # 14. Compute revision columns
    # Within each (leviathan_slug, country, market_year, wasde_release_month),
    # diff value columns by release_date ascending.
    # -----------------------------------------------------------------------
    wide = wide.sort_values(
        ["leviathan_slug", "country", "market_year", "wasde_release_month", "release_date"]
    ).copy()
    revision_group_key = [
        "leviathan_slug", "country", "market_year", "wasde_release_month",
    ]
    for col in ("production_mt", "ending_stocks_mt", "consumption_mt"):
        wide[f"{col}_revision"] = wide.groupby(revision_group_key)[col].diff(1)

    # -----------------------------------------------------------------------
    # 15. Cast types
    # -----------------------------------------------------------------------
    wide["market_year"] = wide["market_year"].astype("Int16")
    wide["wasde_release_month"] = wide["wasde_release_month"].astype("Int8")

    # -----------------------------------------------------------------------
    # 16. Final column order
    # -----------------------------------------------------------------------
    wide = wide[_SILVER_COLS]

    logger.info(
        "PSD silver transform complete: rows=%d slugs=%d releases=%d",
        len(wide),
        wide["leviathan_slug"].nunique(),
        wide["release_date"].nunique(),
    )

    return wide


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _empty_silver() -> pd.DataFrame:
    """Return an empty DataFrame matching the silver schema."""
    schema: dict[str, pd.Series] = {
        "leviathan_slug":            pd.Series([], dtype="object"),
        "country":                   pd.Series([], dtype="object"),
        "market_year":               pd.Series([], dtype="Int16"),
        "wasde_release_month":       pd.Series([], dtype="Int8"),
        "release_date":              pd.Series([], dtype="object"),
        "beginning_stocks_mt":       pd.Series([], dtype="float64"),
        "production_mt":             pd.Series([], dtype="float64"),
        "imports_mt":                pd.Series([], dtype="float64"),
        "exports_mt":                pd.Series([], dtype="float64"),
        "ending_stocks_mt":          pd.Series([], dtype="float64"),
        "consumption_mt":            pd.Series([], dtype="float64"),
        "area_harvested_1000ha":     pd.Series([], dtype="float64"),
        "yield_mt_ha":               pd.Series([], dtype="float64"),
        "su_ratio":                  pd.Series([], dtype="float64"),
        "su_ratio_yoy_delta":        pd.Series([], dtype="float64"),
        "production_mt_revision":    pd.Series([], dtype="float64"),
        "ending_stocks_mt_revision": pd.Series([], dtype="float64"),
        "consumption_mt_revision":   pd.Series([], dtype="float64"),
    }
    return pd.DataFrame(schema)
