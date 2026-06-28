"""Point-in-time WASDE revision features for PSD snapshot model-ready rows."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

SNAPSHOT_ID_COLUMNS = ["country", "crop_year", "snapshot_stage", "as_of_date"]
SNAPSHOT_CONTEXT_COLUMNS = SNAPSHOT_ID_COLUMNS + ["target_market_year"]

SLUG_TO_WASDE_COMMODITY: dict[str, str] = {
    "corn_cbot": "corn",
    "campinas_corn_reference_bmf": "corn",
    "french_maize_matif": "corn",
    "soft_red_winter_wheat_cbot": "wheat",
    "hard_red_winter_wheat_kcbt": "wheat",
    "hard_red_spring_wheat_mgex": "wheat",
    "french_wheat_matif": "wheat",
    "soybeans_cbot": "soybeans",
    "soybeans_no_1_dce": "soybeans",
    "soybeans_no_2_dce": "soybeans",
    "soybean_meal_cbot": "soybean_meal",
    "soybean_meal_dce": "soybean_meal",
    "soybean_oil_cbot": "soybean_oil",
    "soybean_oil_dce": "soybean_oil",
    "rough_rice_cbot": "rice",
    "cotton": "cotton",
    "raw_sugar": "sugar",
    "white_sugar": "sugar",
}

WASDE_COMPONENT_FEATURES: dict[str, str] = {
    "production": "wasde_production_revision_z",
    "ending_stocks": "wasde_ending_stocks_revision_z",
    "exports": "wasde_exports_revision_z",
    "total_use": "wasde_total_use_revision_z",
    "domestic_total": "wasde_domestic_use_revision_z",
}

WASDE_SNAPSHOT_FEATURES = tuple(
    sorted({
        "wasde_latest_revision",
        "wasde_consecutive_revision_count",
        *WASDE_COMPONENT_FEATURES.values(),
    })
)

_REQUIRED_COLUMNS = {
    "release_date",
    "commodity",
    "region",
    "marketing_year",
    "attribute",
    "revision",
}


def _marketing_year_start(value: object) -> int | None:
    match = re.search(r"\d{4}", str(value))
    if not match:
        return None
    return int(match.group(0))


def _prepare_snapshot_context(
    snapshots: pd.DataFrame,
    countries: list[str] | tuple[str, ...] | set[str],
) -> pd.DataFrame:
    required = {"crop_year", "snapshot_stage", "as_of_date"}
    missing = required - set(snapshots.columns)
    if missing:
        raise ValueError(f"snapshot frame missing columns: {sorted(missing)}")

    base = snapshots.copy()
    base["crop_year"] = pd.to_numeric(base["crop_year"], errors="coerce")
    base["as_of_date"] = pd.to_datetime(base["as_of_date"], errors="coerce")
    base = base.dropna(subset=["crop_year", "as_of_date"])
    base["crop_year"] = base["crop_year"].astype(int)
    base["snapshot_stage"] = base["snapshot_stage"].astype(str)
    if "target_market_year" not in base.columns:
        base["target_market_year"] = base["crop_year"]
    base["target_market_year"] = pd.to_numeric(
        base["target_market_year"], errors="coerce"
    ).fillna(base["crop_year"]).astype(int)

    country_values = sorted({str(country) for country in countries})
    if "country" in base.columns:
        base["country"] = base["country"].astype(str)
        base = base.loc[base["country"].isin(country_values)].copy()
    else:
        base = pd.DataFrame({"country": country_values}).merge(base, how="cross")

    out = base[SNAPSHOT_CONTEXT_COLUMNS].copy()
    duplicates = out.duplicated(SNAPSHOT_ID_COLUMNS, keep=False)
    if duplicates.any():
        keys = (
            out.loc[duplicates, SNAPSHOT_ID_COLUMNS]
            .drop_duplicates()
            .sort_values(SNAPSHOT_ID_COLUMNS)
            .to_dict("records")
        )
        raise ValueError(f"duplicate WASDE snapshot context keys {keys[:5]}")
    return out.sort_values(SNAPSHOT_ID_COLUMNS).reset_index(drop=True)


def _prepare_wasde(wasde_df: pd.DataFrame, commodity: str) -> pd.DataFrame:
    missing = _REQUIRED_COLUMNS - set(wasde_df.columns)
    if missing:
        raise ValueError(f"WASDE snapshot source missing columns: {sorted(missing)}")

    wasde_commodity = SLUG_TO_WASDE_COMMODITY.get(commodity)
    if wasde_commodity is None:
        return pd.DataFrame(columns=list(wasde_df.columns) + ["marketing_year_start"])

    source = wasde_df.copy()
    source["commodity"] = source["commodity"].astype(str).str.strip().str.lower()
    source["region"] = source["region"].astype(str).str.strip().str.lower()
    source["attribute"] = source["attribute"].astype(str).str.strip().str.lower()
    out = source.loc[source["commodity"] == wasde_commodity].copy()
    if out.empty:
        return pd.DataFrame(columns=list(wasde_df.columns) + ["marketing_year_start"])

    out["release_date"] = pd.to_datetime(out["release_date"], errors="coerce")
    out["marketing_year_start"] = out["marketing_year"].map(_marketing_year_start)
    out["revision"] = pd.to_numeric(out["revision"], errors="coerce")
    out = out.dropna(subset=["release_date", "marketing_year_start"])
    out["marketing_year_start"] = out["marketing_year_start"].astype(int)
    return out.sort_values(["region", "marketing_year_start", "release_date"]).reset_index(drop=True)


def _country_rows(source: pd.DataFrame, country: str) -> pd.DataFrame:
    rows = source.loc[source["region"].astype(str) == country].copy()
    if rows.empty and country == "united_states":
        rows = source.loc[source["region"].astype(str).isin({"united_states", "us"})].copy()
    return rows


def _latest_visible_revision(
    rows: pd.DataFrame,
    *,
    attribute: str,
    market_year: int,
    as_of_date: pd.Timestamp,
) -> tuple[float, pd.DataFrame]:
    attr_rows = rows.loc[
        (rows["attribute"] == attribute)
        & (rows["marketing_year_start"] == int(market_year))
        & (rows["release_date"] <= as_of_date)
    ].dropna(subset=["revision"]).sort_values("release_date")
    if attr_rows.empty:
        return np.nan, attr_rows
    return float(attr_rows.iloc[-1]["revision"]), attr_rows


def _historical_latest_revisions(
    rows: pd.DataFrame,
    *,
    attribute: str,
    market_year: int,
    as_of_date: pd.Timestamp,
) -> pd.Series:
    attr_rows = rows.loc[
        (rows["attribute"] == attribute)
        & (rows["marketing_year_start"] < int(market_year))
        & (rows["release_date"] <= as_of_date)
    ].dropna(subset=["revision", "marketing_year_start", "release_date"]).copy()
    if attr_rows.empty:
        return pd.Series(dtype=float)
    latest = (
        attr_rows.sort_values(["marketing_year_start", "release_date"])
        .groupby("marketing_year_start", sort=True)
        .tail(1)
    )
    return pd.Series(
        latest["revision"].to_numpy(dtype=float),
        index=latest["marketing_year_start"].astype(int),
        dtype=float,
    ).sort_index()


def _current_zscore(
    value: float,
    history: pd.Series,
    *,
    window_years: int,
    min_history_years: int,
) -> float:
    if not np.isfinite(value):
        return np.nan
    prior = history.dropna().sort_index().tail(window_years)
    if len(prior) < min_history_years:
        return np.nan
    std = float(prior.std(ddof=0))
    if not np.isfinite(std) or std == 0.0:
        return np.nan
    return float((value - float(prior.mean())) / std)


def _revision_streak(rows: pd.DataFrame) -> float:
    if rows.empty:
        return np.nan
    signs = np.sign(pd.to_numeric(rows["revision"], errors="coerce").dropna().to_numpy(dtype=float))
    if signs.size == 0:
        return np.nan
    last = signs[-1]
    if last == 0:
        return 0.0
    count = 0
    for sign in signs[::-1]:
        if sign == 0 or sign != last:
            break
        count += 1
    return float(count * last)


def build_wasde_snapshot_feature_matrix(
    wasde_df: pd.DataFrame | None,
    *,
    commodity: str,
    countries: list[str] | tuple[str, ...] | set[str],
    snapshots: pd.DataFrame,
    window_years: int = 30,
    min_history_years: int = 5,
) -> pd.DataFrame:
    """Return WASDE revision features visible at explicit snapshot dates."""
    snapshot_context = _prepare_snapshot_context(snapshots, countries)
    id_rows = snapshot_context[SNAPSHOT_ID_COLUMNS].copy()
    if wasde_df is None or wasde_df.empty:
        return id_rows

    source = _prepare_wasde(wasde_df, commodity)
    if source.empty:
        return id_rows

    rows: list[dict[str, object]] = []
    for snap in snapshot_context.itertuples(index=False):
        country = str(snap.country)
        as_of_date = pd.Timestamp(snap.as_of_date)
        market_year = int(snap.target_market_year)
        country_df = _country_rows(source, country)
        out: dict[str, object] = {
            "country": country,
            "crop_year": int(snap.crop_year),
            "snapshot_stage": str(snap.snapshot_stage),
            "as_of_date": as_of_date.date(),
        }
        if country_df.empty:
            rows.append(out)
            continue

        production_revision, production_rows = _latest_visible_revision(
            country_df,
            attribute="production",
            market_year=market_year,
            as_of_date=as_of_date,
        )
        if np.isfinite(production_revision):
            out["wasde_latest_revision"] = production_revision
            streak = _revision_streak(production_rows)
            if np.isfinite(streak):
                out["wasde_consecutive_revision_count"] = streak

        for attribute, feature in WASDE_COMPONENT_FEATURES.items():
            revision, _ = _latest_visible_revision(
                country_df,
                attribute=attribute,
                market_year=market_year,
                as_of_date=as_of_date,
            )
            history = _historical_latest_revisions(
                country_df,
                attribute=attribute,
                market_year=market_year,
                as_of_date=as_of_date,
            )
            z = _current_zscore(
                revision,
                history,
                window_years=window_years,
                min_history_years=min_history_years,
            )
            if np.isfinite(z):
                out[feature] = z
        rows.append(out)

    if not rows:
        return id_rows
    return pd.DataFrame(rows).sort_values(SNAPSHOT_ID_COLUMNS).reset_index(drop=True)
