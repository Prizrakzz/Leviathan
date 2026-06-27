"""Silver transform for USDA NASS QuickStats weekly crop progress data.

The crop-progress bronze layer keeps weekly progress and condition rows from
QuickStats. This transform narrows those rows into contract-aligned weekly
features with one row per (leviathan_slug, state, year, date).
"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

OUTPUT_COLUMNS = [
    "leviathan_slug",
    "state",
    "year",
    "date",
    "week_of_year",
    "pct_planted",
    "pct_emerged",
    "pct_good_excellent",
    "pct_poor_very_poor",
    "pct_harvested",
    "source",
]

_REQUIRED_COLS = frozenset({
    "commodity_desc",
    "class_desc",
    "statisticcat_desc",
    "unit_desc",
    "agg_level_desc",
    "state_alpha",
    "year",
    "week_ending",
    "value",
    "source",
})

_PROGRESS_UNIT_TO_COL = {
    "PCT PLANTED": "pct_planted",
    "PCT EMERGED": "pct_emerged",
    "PCT HARVESTED": "pct_harvested",
}

_CONDITION_UNIT_TO_COMPONENT = {
    "PCT GOOD": "good",
    "PCT EXCELLENT": "excellent",
    "PCT POOR": "poor",
    "PCT VERY POOR": "very_poor",
}

_HARVESTED_UTIL_EXCLUSIONS = frozenset({
    "SILAGE",
    "FORAGE",
    "GREENCHOP",
    "HAY",
    "HAYLAGE",
    "STOVER",
})


def _empty_output() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return " ".join(text.upper().split())


def _is_all_class(class_name: str) -> bool:
    return class_name in {"", "ALL CLASSES"}


def _canonical_slug(commodity_desc: object, class_desc: object) -> str | None:
    commodity = _clean_text(commodity_desc)
    class_name = _clean_text(class_desc)

    if commodity == "CORN":
        return "corn_cbot" if _is_all_class(class_name) else None
    if commodity == "SOYBEANS":
        return "soybeans_cbot" if _is_all_class(class_name) else None
    if commodity == "RICE":
        return "rough_rice_cbot" if _is_all_class(class_name) else None
    if commodity == "COTTON":
        return "cotton" if class_name == "UPLAND" else None
    if commodity == "WHEAT":
        if class_name == "WINTER":
            return "soft_red_winter_wheat_cbot"
        if class_name == "SPRING, (EXCL DURUM)":
            return "hard_red_spring_wheat_mgex"
        return None

    # Coarse-grain proxies, aggregate wheat, durum wheat, and other NASS crops
    # are excluded from this contract-targeted weekly feature table.
    return None


def _metric_name(statisticcat_desc: object, unit_desc: object) -> str | None:
    stat = _clean_text(statisticcat_desc)
    unit = _clean_text(unit_desc)

    if stat == "PROGRESS":
        return _PROGRESS_UNIT_TO_COL.get(unit)
    if stat == "CONDITION":
        return _CONDITION_UNIT_TO_COMPONENT.get(unit)
    return None


def _filter_primary_rows(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    result["agg_level_desc_norm"] = result["agg_level_desc"].map(_clean_text)
    result = result.loc[result["agg_level_desc_norm"].isin({"NATIONAL", "STATE"})].copy()

    result["statisticcat_desc_norm"] = result["statisticcat_desc"].map(_clean_text)
    result = result.loc[result["statisticcat_desc_norm"].isin({"PROGRESS", "CONDITION"})].copy()

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

    if "prodn_practice_desc" in result.columns:
        prodn = result["prodn_practice_desc"].map(_clean_text)
        if (prodn == "ALL PRODUCTION PRACTICES").any():
            result = result.loc[prodn.isin({"", "ALL PRODUCTION PRACTICES"})].copy()

    return result


def _filter_progress_metric_rows(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["metric"] = [
        _metric_name(stat, unit)
        for stat, unit in zip(result["statisticcat_desc"], result["unit_desc"])
    ]
    result = result.dropna(subset=["metric"]).copy()
    if result.empty:
        return result

    if "util_practice_desc" in result.columns:
        util = result["util_practice_desc"].map(_clean_text)
    else:
        util = pd.Series([""] * len(result), index=result.index)

    harvested_mask = result["metric"] == "pct_harvested"
    if harvested_mask.any():
        grain_harvest = harvested_mask & (util == "GRAIN")
        if grain_harvest.any():
            allowed_harvest = grain_harvest | (harvested_mask & (util == ""))
        else:
            allowed_harvest = harvested_mask & ~util.isin(_HARVESTED_UTIL_EXCLUSIONS)
        result = result.loc[~harvested_mask | allowed_harvest].copy()

    return result


def _validate_metric_uniqueness(df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["leviathan_slug", "state", "year", "date", "metric"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if not duplicate_mask.any():
        return df

    duplicates = df.loc[duplicate_mask].copy()
    conflicts: list[tuple[object, ...]] = []
    for key, group in duplicates.groupby(key_cols, dropna=False):
        if group["value"].dropna().nunique() > 1:
            conflicts.append(key)

    if conflicts:
        preview = ", ".join(str(c) for c in conflicts[:5])
        raise ValueError(
            "NASS crop progress silver found conflicting duplicate metric rows for "
            f"{preview}. Tighten source/class/practice filters before pivoting."
        )

    return df.drop_duplicates(subset=key_cols, keep="last").copy()


def _date_or_na(value: pd.Timestamp) -> date:
    return value.date()


def transform_nass_crop_progress_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Convert bronze USDA NASS crop-progress rows into wide weekly features."""
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"NASS crop progress bronze DataFrame is missing required columns: {missing}. "
            f"Got: {list(df.columns)}"
        )
    if df.empty:
        return _empty_output()

    work = _filter_primary_rows(df)
    if work.empty:
        return _empty_output()

    work["leviathan_slug"] = [
        _canonical_slug(commodity, class_name)
        for commodity, class_name in zip(work["commodity_desc"], work["class_desc"])
    ]
    work = work.dropna(subset=["leviathan_slug"]).copy()
    if work.empty:
        return _empty_output()

    work = _filter_progress_metric_rows(work)
    if work.empty:
        return _empty_output()

    work["value"] = pd.to_numeric(
        work["value"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work["date_ts"] = pd.to_datetime(work["week_ending"], errors="coerce")
    work = work.dropna(subset=["year", "date_ts"]).copy()
    if work.empty:
        return _empty_output()

    work["year"] = work["year"].astype(int)
    work["date"] = work["date_ts"].map(_date_or_na)
    work["week_of_year"] = work["date_ts"].dt.isocalendar().week.astype(int)
    work["state"] = work["state_alpha"].where(
        work["agg_level_desc_norm"] != "NATIONAL",
        other="US",
    )
    work["state"] = work["state"].fillna("").astype(str).str.strip().str.upper()
    work = work[work["state"] != ""].copy()
    work["source"] = "usda_nass"

    work = _validate_metric_uniqueness(work)

    index_cols = ["leviathan_slug", "state", "year", "date", "week_of_year", "source"]
    pivot = work.pivot(index=index_cols, columns="metric", values="value")

    silver = pivot.reset_index()
    for component in ("good", "excellent", "poor", "very_poor"):
        if component not in silver.columns:
            silver[component] = pd.NA

    silver["pct_good_excellent"] = silver["good"] + silver["excellent"]
    silver["pct_poor_very_poor"] = silver["poor"] + silver["very_poor"]

    for col in OUTPUT_COLUMNS:
        if col not in silver.columns:
            silver[col] = pd.NA

    for col in [
        "pct_planted",
        "pct_emerged",
        "pct_good_excellent",
        "pct_poor_very_poor",
        "pct_harvested",
    ]:
        silver[col] = pd.to_numeric(silver[col], errors="coerce").astype("Float64")

    silver = silver[OUTPUT_COLUMNS].sort_values(
        ["leviathan_slug", "state", "year", "date"],
        kind="stable",
    )
    logger.info("NASS crop progress silver transform produced %d rows", len(silver))
    return silver.reset_index(drop=True)
