"""Silver transform for USDA NASS QuickStats annual crop data.

The bronze NASS layer intentionally keeps a broad annual slice from the bulk
QuickStats crops file, including county rows and a few proxy commodity mappings.
This transform narrows that data into production-forecasting features:
national/state only, standard metric units, and one wide row per
(leviathan_slug, state, year).

D-LD pre-step D-LD-9a (2026-08-18) ADDITIVELY appends one column, ``release_date``
-- the DERIVED vintage knowledge anchor. The measured physical table carried NO
date, vintage, ingest or month column of any kind (14 body columns over 593
canonical objects / 14,631 rows), so a numbers card had nothing to anchor its
point-in-time as-of guard on: ``knowledge_col()`` returned ``None`` and
``query.build_sql`` raised "no knowledge/date column to anchor the as-of guard".
``year`` is the CROP year, not a knowledge date. This is the same shape
WIRING_WAVE1 met on ``silver_conab_coffee`` (``survey_release_date``) and
``silver_sagis_weekly_exports`` (``week_ending_date``), and it is solved the same
way: one producer-derived, conservative, never-leak timing column. See
``_ANNUAL_SUMMARY_RELEASE`` below. The column NEVER touches a measured value.
"""
from __future__ import annotations

import math

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

ACRE_TO_HA = 0.40468564224
LB_TO_MT = 0.00045359237
LB_PER_ACRE_TO_T_HA = LB_TO_MT / ACRE_TO_HA
SHORT_TON_TO_MT = 0.90718474

STAT_TO_VALUE_COL = {
    "AREA PLANTED": "area_planted_ha",
    "AREA HARVESTED": "area_harvested_ha",
    "YIELD": "yield_t_ha",
    "PRODUCTION": "production_mt",
}

STAT_TO_CV_COL = {
    "AREA PLANTED": "area_planted_cv_pct",
    "AREA HARVESTED": "area_harvested_cv_pct",
    "YIELD": "yield_cv_pct",
    "PRODUCTION": "production_cv_pct",
}

OUTPUT_COLUMNS = [
    "leviathan_slug",
    "country",
    "state",
    "year",
    "marketing_year",
    "area_planted_ha",
    "area_harvested_ha",
    "yield_t_ha",
    "production_mt",
    "area_planted_cv_pct",
    "area_harvested_cv_pct",
    "yield_cv_pct",
    "production_cv_pct",
    "source",
    # D-LD pre-step D-LD-9a additive tail (kept LAST to mirror the Glue ADD COLUMNS append and the
    # hand DDL's appended column -- the conab survey_release_date discipline, column for column).
    "release_date",
]

# The 14 columns the producer emitted BEFORE the D-LD pre-step, in order. Frozen here so a future
# edit that reorders or drops a pre-existing column is a test failure rather than a silent silver
# rewrite of 593 canonical objects.
PRE_DLD_OUTPUT_COLUMNS = OUTPUT_COLUMNS[:-1]

_REQUIRED_COLS = frozenset({
    "commodity_desc",
    "statisticcat_desc",
    "unit_desc",
    "agg_level_desc",
    "state_alpha",
    "year",
    "value",
    "cv_pct",
    "source",
})

_BUSHEL_WEIGHTS_LB = {
    "corn_cbot": 56.0,
    "soybeans_cbot": 60.0,
    "soft_red_winter_wheat_cbot": 60.0,
    "hard_red_winter_wheat_kcbt": 60.0,
    "hard_red_spring_wheat_mgex": 60.0,
}

_SECONDARY_UTILIZATION = frozenset({
    "FORAGE",
    "GREENCHOP",
    "HAY",
    "HAYLAGE",
    "SEED",
    "SILAGE",
    "STOVER",
})

_NON_FEATURE_UNITS = frozenset({
    "$",
    "PCT BY SIZE GROUP",
    "PCT BY TYPE",
})


# ---------------------------------------------------------------------------
# release_date -- the derived, conservative, never-leak vintage anchor (D-LD pre-step D-LD-9a).
# ---------------------------------------------------------------------------
# USDA NASS publishes the Crop Production ANNUAL SUMMARY for crop year Y in the SECOND WEEK OF
# JANUARY of Y+1 (the settled acreage/yield/production this table carries). We stamp the FIRST DAY
# OF THE MONTH STRICTLY AFTER that window -- Feb 1 of Y+1 -- so the derived date is ALWAYS on/after
# the real release: the point-in-time as-of guard can never LEAK a crop year before its summary was
# actually published. It withholds by at most ~3 weeks, which is the SAFE direction.
#
# WHAT THIS VINTAGE DELIBERATELY DOES NOT SERVE: the IN-SEASON prints. NASS also publishes
# Prospective Plantings (Mar 31) and Acreage (Jun 30) for the CURRENT crop year, and those numbers
# land in this row the moment the weekly job re-reads QuickStats (a 2026 row with planted/harvested
# acreage and NULL yield/production exists today). ONE row carries ONE knowledge date, and the row
# is OVERWRITTEN each January with the settled production -- so stamping it June would leak the
# settled figure on every historical replay. In-season US acreage/pace is silver_nass_crop_progress.
#
# The stamp is a pure function of the crop year, so it is stable across re-runs and byte-identical
# for an unchanged partition. (year offset, month, day) is the single knob.
_ANNUAL_SUMMARY_RELEASE = (1, 2, 1)


def _release_date(crop_year: object) -> str:
    """Conservative ISO ``YYYY-MM-DD`` annual-summary release stamp for one NASS crop year.

    Raises on a missing/unparseable crop year -- fail-loud, because a null PIT anchor would silently
    drop the row from the leakage-safe as-of guard (``null <= asof`` is UNKNOWN in SQL, and the
    Python oracle looks the column up on the row dict)."""
    if crop_year is None or (isinstance(crop_year, float) and math.isnan(crop_year)):
        raise ValueError(
            "NASS annual silver cannot derive a leakage-safe release_date from a null crop year"
        )
    try:
        year = int(crop_year)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"NASS annual crop year {crop_year!r} is not an integer; cannot derive release_date"
        ) from exc
    yr_off, month, day = _ANNUAL_SUMMARY_RELEASE
    return f"{year + yr_off:04d}-{month:02d}-{day:02d}"


def _is_all_class(class_name: str) -> bool:
    return class_name in {"", "ALL CLASSES"}


def _empty_output() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return " ".join(text.upper().split())


def _canonical_slug(commodity_desc: object, class_desc: object) -> str | None:
    commodity = _clean_text(commodity_desc)
    class_name = _clean_text(class_desc)

    if commodity == "CORN":
        return "corn_cbot" if _is_all_class(class_name) else None
    if commodity == "SOYBEANS":
        return "soybeans_cbot" if _is_all_class(class_name) else None
    if commodity == "COTTON":
        return "cotton" if _is_all_class(class_name) else None
    if commodity == "RICE":
        return "rough_rice_cbot" if _is_all_class(class_name) else None
    if commodity == "CANOLA":
        return "canola_ice" if _is_all_class(class_name) else None

    if commodity == "WHEAT, SPRING":
        if class_name in {"", "ALL CLASSES", "HARD RED SPRING"}:
            return "hard_red_spring_wheat_mgex"
        return None

    if commodity == "WHEAT, WINTER":
        if "SOFT RED WINTER" in class_name:
            return "soft_red_winter_wheat_cbot"
        if "HARD RED WINTER" in class_name:
            return "hard_red_winter_wheat_kcbt"
        return None

    # Aggregate WHEAT, durum, coarse-grain proxies, sunflower, and sugar crops
    # are intentionally excluded from this contract-targeted annual table.
    return None


def _filter_primary_rows(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    if "source_desc" in result.columns:
        source_desc = result["source_desc"].map(_clean_text)
        if (source_desc == "SURVEY").any():
            result = result.loc[source_desc == "SURVEY"].copy()

    if "domain_desc" in result.columns:
        domain = result["domain_desc"].map(_clean_text)
        if (domain == "TOTAL").any():
            result = result.loc[domain == "TOTAL"].copy()

    if "domaincat_desc" in result.columns:
        domaincat = result["domaincat_desc"].map(_clean_text)
        if (domaincat == "NOT SPECIFIED").any():
            result = result.loc[domaincat == "NOT SPECIFIED"].copy()

    if "reference_period_desc" in result.columns:
        reference_period = result["reference_period_desc"].map(_clean_text)
        if (reference_period == "YEAR").any():
            result = result.loc[reference_period == "YEAR"].copy()

    if "prodn_practice_desc" in result.columns:
        prodn = result["prodn_practice_desc"].map(_clean_text)
        result = result.loc[prodn.isin({"", "ALL PRODUCTION PRACTICES"})].copy()

    if "util_practice_desc" in result.columns:
        util = result["util_practice_desc"].map(_clean_text)
        result = result.loc[~util.isin(_SECONDARY_UTILIZATION)].copy()

    return result


def _bushel_weight(slug: str, unit_desc: str) -> float:
    try:
        return _BUSHEL_WEIGHTS_LB[slug]
    except KeyError as exc:
        raise ValueError(
            f"NASS annual unit {unit_desc!r} requires a bushel weight for {slug!r}"
        ) from exc


def _convert_value(row: pd.Series) -> float:
    value = row["value"]
    if pd.isna(value):
        return float("nan")

    stat = row["statisticcat_desc_norm"]
    unit = row["unit_desc_norm"]
    slug = row["leviathan_slug"]
    numeric = float(value)

    if stat in {"AREA PLANTED", "AREA HARVESTED"}:
        if unit == "ACRES":
            return numeric * ACRE_TO_HA
        if unit in {"HECTARES", "HA"}:
            return numeric
        raise ValueError(f"Unsupported NASS area unit {unit!r} for {slug!r}")

    if stat == "YIELD":
        if unit in {"BU / ACRE", "BU / NET PLANTED ACRE"}:
            return numeric * _bushel_weight(slug, unit) * LB_PER_ACRE_TO_T_HA
        if unit in {"LB / ACRE", "LB / NET PLANTED ACRE"}:
            return numeric * LB_PER_ACRE_TO_T_HA
        if unit == "CWT / ACRE":
            return numeric * 100.0 * LB_PER_ACRE_TO_T_HA
        if unit in {"TONS / ACRE", "TON / ACRE"}:
            return numeric * 2000.0 * LB_PER_ACRE_TO_T_HA
        raise ValueError(f"Unsupported NASS yield unit {unit!r} for {slug!r}")

    if stat == "PRODUCTION":
        if unit == "BU":
            return numeric * _bushel_weight(slug, unit) * LB_TO_MT
        if unit == "LB":
            return numeric * LB_TO_MT
        if unit == "CWT":
            return numeric * 100.0 * LB_TO_MT
        if unit in {"TONS", "TON"}:
            return numeric * SHORT_TON_TO_MT
        if unit == "480 LB BALES":
            return numeric * 480.0 * LB_TO_MT
        if unit in {"METRIC TONS", "METRIC TONNES", "MT"}:
            return numeric
        raise ValueError(f"Unsupported NASS production unit {unit!r} for {slug!r}")

    raise ValueError(f"Unsupported NASS statistic category {stat!r}")


def _metric_preference_rank(row: pd.Series) -> int:
    stat = row["statisticcat_desc_norm"]
    unit = row["unit_desc_norm"]
    if stat == "YIELD" and unit in {"BU / NET PLANTED ACRE", "LB / NET PLANTED ACRE"}:
        return 1
    return 0


def _prefer_metric_rows(df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["leviathan_slug", "state", "year", "statisticcat_desc_norm"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if not duplicate_mask.any():
        return df

    work = df.copy()
    work["_metric_preference_rank"] = work.apply(_metric_preference_rank, axis=1)
    best_rank = work.groupby(key_cols, dropna=False)["_metric_preference_rank"].transform("min")
    work = work.loc[work["_metric_preference_rank"] == best_rank].copy()
    return work.drop(columns=["_metric_preference_rank"])


def _validate_metric_uniqueness(df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["leviathan_slug", "state", "year", "statisticcat_desc_norm"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if not duplicate_mask.any():
        return df

    duplicates = df.loc[duplicate_mask].copy()
    conflicts: list[tuple[object, ...]] = []
    for key, group in duplicates.groupby(key_cols, dropna=False):
        value_count = group["converted_value"].dropna().nunique()
        cv_count = group["cv_pct"].dropna().nunique()
        if value_count > 1 or cv_count > 1:
            conflicts.append(key)

    if conflicts:
        preview = ", ".join(str(c) for c in conflicts[:5])
        raise ValueError(
            "NASS annual silver found conflicting duplicate metric rows for "
            f"{preview}. Tighten source/class/practice filters before pivoting."
        )

    return df.drop_duplicates(subset=key_cols, keep="last").copy()


def transform_nass_annual_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Convert bronze USDA NASS annual rows into wide silver production features."""
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"NASS annual bronze DataFrame is missing required columns: {missing}. "
            f"Got: {list(df.columns)}"
        )
    if df.empty:
        return _empty_output()

    work = df.copy()
    work["agg_level_desc_norm"] = work["agg_level_desc"].map(_clean_text)
    work["statisticcat_desc_norm"] = work["statisticcat_desc"].map(_clean_text)
    work["unit_desc_norm"] = work["unit_desc"].map(_clean_text)

    work = work.loc[
        work["agg_level_desc_norm"].isin({"NATIONAL", "STATE"})
        & work["statisticcat_desc_norm"].isin(STAT_TO_VALUE_COL)
    ].copy()
    work = work.loc[~work["unit_desc_norm"].isin(_NON_FEATURE_UNITS)].copy()
    if work.empty:
        return _empty_output()

    work = _filter_primary_rows(work)
    if work.empty:
        return _empty_output()

    class_series = (
        work["class_desc"]
        if "class_desc" in work.columns
        else pd.Series([""] * len(work), index=work.index)
    )
    work["leviathan_slug"] = [
        _canonical_slug(commodity, class_name)
        for commodity, class_name in zip(work["commodity_desc"], class_series)
    ]
    work = work.dropna(subset=["leviathan_slug"]).copy()
    if work.empty:
        return _empty_output()

    work["value"] = pd.to_numeric(
        work["value"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    work["cv_pct"] = pd.to_numeric(
        work["cv_pct"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work = work.dropna(subset=["year"]).copy()
    work["year"] = work["year"].astype(int)
    work["marketing_year"] = work["year"]
    work["country"] = "united_states"
    work["state"] = work["state_alpha"].where(
        work["agg_level_desc_norm"] != "NATIONAL",
        other="US",
    )
    work["state"] = work["state"].fillna("").astype(str).str.strip().str.upper()
    work = work[work["state"] != ""].copy()
    work["source"] = "usda_nass"

    work["converted_value"] = work.apply(_convert_value, axis=1)
    work = _prefer_metric_rows(work)
    work = _validate_metric_uniqueness(work)

    index_cols = [
        "leviathan_slug",
        "country",
        "state",
        "year",
        "marketing_year",
        "source",
    ]

    values = work.pivot(
        index=index_cols,
        columns="statisticcat_desc_norm",
        values="converted_value",
    ).rename(columns=STAT_TO_VALUE_COL)

    cvs = work.pivot(
        index=index_cols,
        columns="statisticcat_desc_norm",
        values="cv_pct",
    ).rename(columns=STAT_TO_CV_COL)

    silver = pd.concat([values, cvs], axis=1).reset_index()

    # D-LD pre-step D-LD-9a: the derived vintage anchor. Stamped from the CROP YEAR (an int by
    # construction above) BEFORE the OUTPUT_COLUMNS backfill below, so it is never NA-filled --
    # a null here would drop the row from the as-of guard instead of failing loudly.
    silver["release_date"] = [_release_date(y) for y in silver["year"]]

    for col in OUTPUT_COLUMNS:
        if col not in silver.columns:
            silver[col] = pd.NA

    silver = silver[OUTPUT_COLUMNS].sort_values(
        ["leviathan_slug", "state", "year"],
        kind="stable",
    )
    logger.info("NASS annual silver transform produced %d rows", len(silver))
    return silver.reset_index(drop=True)
