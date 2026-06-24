"""USDA WASDE bronze -> revision-aware silver transform.

WASDE is useful for ML only if releases remain separate.  This transform keeps
one row per accepted estimate per release and computes the adjacent-release
revision without looking forward from any individual release.
"""
from __future__ import annotations

import re

import pandas as pd

OUTPUT_COLUMNS = [
    "release_date",
    "commodity",
    "table_type",
    "region",
    "marketing_year",
    "attribute",
    "unit",
    "estimate",
    "prior_release_date",
    "prior_estimate",
    "revision",
    "revision_direction",
    "months_to_marketing_year_end",
    "is_first_estimate",
    "is_final_or_latest",
    "raw_table_name",
    "raw_region",
    "raw_attribute",
    "raw_status",
    "raw_projection_month",
    "source",
]

_SUPPORTED_ATTRIBUTES = {
    "beginning_stocks",
    "production",
    "imports",
    "total_supply",
    "feed",
    "food_use",
    "seed_use",
    "feed_residual",
    "domestic_total",
    "total_use",
    "exports",
    "ending_stocks",
    "crush",
    "residual",
    "planted_area",
    "harvested_area",
    "yield",
    "avg_farm_price",
    "loss",
}
_SUPPORTED_UNITS = {
    "",
    "million metric tons",
    "million bushels",
    "million 480-lb. bales",
    "million 480-lb bales",
    "million pounds",
    "million acres",
    "bushels per acre",
    "pounds per acre",
    "dollars per bushel",
    "cents per pound",
    "milled basis",
    "domestic measure",
}
_MONTH_ARTIFACTS = {
    "jan",
    "january",
    "feb",
    "february",
    "mar",
    "march",
    "apr",
    "april",
    "may",
    "jun",
    "june",
    "jul",
    "july",
    "aug",
    "august",
    "sep",
    "sept",
    "september",
    "oct",
    "october",
    "nov",
    "november",
    "dec",
    "december",
}


def _clean(value: object) -> str:
    value = "" if value is None or pd.isna(value) else str(value)
    return re.sub(r"\s+", " ", value).strip()


def _snake(value: object) -> str:
    text = _clean(value).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _commodity_from_table(table_name: str) -> str | None:
    low = table_name.lower()
    if "soybean oil" in low or "soybean oil" in low.replace("-", " "):
        return "soybean_oil"
    if "soybean meal" in low or "soybean meal" in low.replace("-", " "):
        return "soybean_meal"
    if "soybean" in low or "oilseed" in low:
        return "soybeans"
    if "wheat" in low:
        return "wheat"
    if "corn" in low:
        return "corn"
    if "rice" in low:
        return "rice"
    if "cotton" in low:
        return "cotton"
    if "sugar" in low:
        return "sugar"
    return None


def _table_type(table_name: str) -> str:
    low = table_name.lower()
    if "u.s." in low or "united states" in low:
        return "us"
    if "world" in low:
        return "world"
    return "regional"


def _market_year_start(marketing_year: str) -> int | None:
    match = re.match(r"^(\d{4})/(\d{2,4})$", _clean(marketing_year))
    if not match:
        return None
    return int(match.group(1))


def _market_year_end(marketing_year: str) -> pd.Timestamp | None:
    start = _market_year_start(marketing_year)
    if start is None:
        return None
    return pd.Timestamp(year=start + 1, month=6, day=30)


def _months_to_marketing_year_end(marketing_year: str, release_date: pd.Timestamp) -> int | None:
    end = _market_year_end(marketing_year)
    if end is None or pd.isna(release_date):
        return None
    return int((end.year - release_date.year) * 12 + (end.month - release_date.month))


def _revision_direction(value: object) -> str:
    if pd.isna(value):
        return "none"
    value = float(value)
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def _resolve_duplicate_conflicts(df: pd.DataFrame, *, on_conflict: str = "raise") -> pd.DataFrame:
    key = [
        "release_date",
        "commodity",
        "table_type",
        "region",
        "marketing_year",
        "attribute",
        "unit",
    ]
    conflict_rows: list[dict[str, object]] = []
    for _, group in df.groupby(key, dropna=False):
        values = group["estimate"].dropna().unique()
        if len(values) > 1:
            conflict_rows.append(group.iloc[0][key].to_dict())
    if conflict_rows:
        if on_conflict == "drop":
            conflict_key = pd.MultiIndex.from_frame(pd.DataFrame(conflict_rows)[key])
            row_key = pd.MultiIndex.from_frame(df[key])
            return (
                df.loc[~row_key.isin(conflict_key)]
                .drop_duplicates(subset=key, keep="last")
                .reset_index(drop=True)
            )
        preview = conflict_rows[:5]
        raise ValueError(f"WASDE duplicate estimate conflicts on natural key: {preview}")
    return df.drop_duplicates(subset=key, keep="last").reset_index(drop=True)


def transform_wasde_bronze_to_silver(
    bronze: pd.DataFrame,
    *,
    on_conflict: str = "raise",
) -> pd.DataFrame:
    """Normalize accepted WASDE bronze rows and compute adjacent revisions."""
    required = {
        "release_date",
        "table_name",
        "region",
        "market_year",
        "attribute",
        "value",
        "unit",
    }
    missing = required - set(bronze.columns)
    if missing:
        raise ValueError(f"WASDE bronze missing required columns: {sorted(missing)}")
    if bronze.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = bronze.copy()
    df["raw_table_name"] = df["table_name"].map(_clean)
    df["raw_region"] = df["region"].map(_clean)
    df["raw_attribute"] = df["attribute"].map(_clean)
    df["raw_status"] = df.get("status", "").map(_clean) if "status" in df.columns else ""
    df["raw_projection_month"] = (
        df.get("projection_month", "").map(_clean)
        if "projection_month" in df.columns
        else ""
    )
    df["commodity"] = df["raw_table_name"].map(_commodity_from_table)
    df["table_type"] = df["raw_table_name"].map(_table_type)
    df["region"] = df["raw_region"].map(_snake)
    df["marketing_year"] = df["market_year"].map(_clean)
    df["attribute"] = df["raw_attribute"].map(_snake)
    df["unit"] = df["unit"].map(lambda value: _clean(value).lower())
    df["estimate"] = pd.to_numeric(df["value"], errors="coerce")
    df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce").dt.date.astype(str)

    accepted = df[
        df["commodity"].notna()
        & df["attribute"].isin(_SUPPORTED_ATTRIBUTES)
        & df["unit"].isin(_SUPPORTED_UNITS)
        & df["estimate"].notna()
        & ~df["attribute"].str.startswith("col_")
        & ~df["region"].isin(_MONTH_ARTIFACTS)
        & ~df["raw_table_name"].str.contains(
            r"\s-\s(?:Jan\.?|January|Feb\.?|February|Mar\.?|March|Apr\.?|April|"
            r"May|Jun\.?|June|Jul\.?|July|Aug\.?|August|Sep\.?|Sept\.?|September|"
            r"Oct\.?|October|Nov\.?|November|Dec\.?|December)\b",
            case=False,
            regex=True,
            na=False,
        )
        & (df["region"] != "")
        & (df["marketing_year"] != "")
    ].copy()
    if accepted.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    accepted = _resolve_duplicate_conflicts(accepted, on_conflict=on_conflict)
    accepted["_release_ts"] = pd.to_datetime(accepted["release_date"], errors="coerce")
    accepted = accepted.sort_values([
        "commodity",
        "table_type",
        "region",
        "marketing_year",
        "attribute",
        "unit",
        "_release_ts",
    ]).reset_index(drop=True)

    group_cols = [
        "commodity",
        "table_type",
        "region",
        "marketing_year",
        "attribute",
        "unit",
    ]
    grouped = accepted.groupby(group_cols, dropna=False)
    accepted["prior_release_date"] = grouped["release_date"].shift(1)
    accepted["prior_estimate"] = grouped["estimate"].shift(1)
    accepted["revision"] = accepted["estimate"] - accepted["prior_estimate"]
    accepted["revision_direction"] = accepted["revision"].map(_revision_direction)
    accepted["is_first_estimate"] = accepted["prior_estimate"].isna()
    accepted["is_final_or_latest"] = accepted["_release_ts"].eq(grouped["_release_ts"].transform("max"))
    accepted["months_to_marketing_year_end"] = [
        _months_to_marketing_year_end(my, rd)
        for my, rd in zip(accepted["marketing_year"], accepted["_release_ts"])
    ]
    accepted["source"] = "usda_wasde"

    return accepted[OUTPUT_COLUMNS].reset_index(drop=True)
