"""Point-in-time gold_v2 feature spine.

gold_v2 is additive to the legacy annual ``gold/`` layer.  It keeps a stable
long schema while making the as-of snapshot explicit, so training and serving
can agree on the exact data vintage.
"""
from __future__ import annotations

import datetime as dt
import math
import subprocess
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from leviathan.features.availability import normalize_availability
from leviathan.features.computations.base import trailing_baseline_z

SPINE_V2_COLUMNS = [
    "entity_type",
    "entity_id",
    "physical_commodity",
    "contract_slug",
    "origin",
    "crop_year",
    "as_of_date",
    "snapshot_stage",
    "feature",
    "value",
    "feature_available_at",
    "source",
    "source_vintage",
    "is_label",
]

SPINE_V2_NATURAL_KEY = [
    "entity_id",
    "origin",
    "crop_year",
    "as_of_date",
    "snapshot_stage",
    "feature",
]

DEFAULT_V2_COMMODITIES = [
    "corn_cbot",
    "soybean_oil_cbot",
    "malaysian_crude_palm_oil_cme",
    "raw_sugar",
]

V2_SOURCE_KEYS_BY_COMMODITY = {
    "corn_cbot": {
        "nass_crop_progress",
        "esr",
        "fgis",
        "wap_revisions",
        "pink_sheet",
    },
    "soybean_oil_cbot": {
        "esr",
        "futures_prices",
        "pink_sheet",
    },
    "malaysian_crude_palm_oil_cme": {
        "mpob",
        "futures_prices",
        "pink_sheet",
    },
    "raw_sugar": {
        "pink_sheet",
        "unica",
    },
}

SOURCE_DATASET_IDS = {
    "nass_crop_progress": "silver_nass_crop_progress",
    "esr": "silver_esr",
    "fgis": "silver_fgis",
    "wap_revisions": "silver_wap_table01_revisions",
    "wasde": "silver_wasde",
    "pink_sheet": "silver_pink_sheet",
    "futures_prices": "silver_futures_prices",
    "mpob": "silver_mpob",
    "unica": "silver_unica_biweekly_release_series",
}

_PHYSICAL_COMMODITY = {
    "corn_cbot": "corn",
    "soybean_oil_cbot": "soybean_oil",
    "malaysian_crude_palm_oil_cme": "palm_oil",
    "raw_sugar": "sugar",
}

_DEFAULT_ORIGIN = {
    "corn_cbot": "united_states",
    "soybean_oil_cbot": "united_states",
    "malaysian_crude_palm_oil_cme": "malaysia",
    "raw_sugar": "brazil_center_south",
}

_SOY_CRUSH_LEGS = {
    "beans": "soybeans_cbot",
    "meal": "soybean_meal_cbot",
    "oil": "soybean_oil_cbot",
}


class SpineV2Error(ValueError):
    """gold_v2 spine validation failed."""


@dataclass(frozen=True)
class SpineV2BuildResult:
    commodity: str
    df: pd.DataFrame
    report: dict
    passed: bool


def git_short_sha() -> str:
    try:
        full = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        return full[:8]
    except Exception:  # noqa: BLE001
        return "unknown"


def default_dataset_version(
    *,
    now: dt.datetime | None = None,
    short_git_sha: str | None = None,
) -> str:
    stamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    return f"{stamp.strftime('%Y%m%dT%H%M%SZ')}_{short_git_sha or git_short_sha()}"


def default_as_of_dates(crop_years: Iterable[int]) -> dict[int, pd.Timestamp]:
    return {
        int(year): pd.Timestamp(dt.date(int(year), 12, 31))
        for year in crop_years
    }


def snapshot_stage_for(as_of_date: pd.Timestamp, crop_year: int, policy: str) -> str:
    if policy == "default_v1":
        if as_of_date == pd.Timestamp(dt.date(int(crop_year), 12, 31)):
            return "crop_year_end"
        return "custom_as_of"
    return policy


def _contract_context(commodity: str) -> dict[str, str]:
    origin = _DEFAULT_ORIGIN.get(commodity, "global")
    return {
        "entity_type": "contract_origin",
        "entity_id": f"{commodity}:{origin}",
        "physical_commodity": _PHYSICAL_COMMODITY.get(commodity, commodity),
        "contract_slug": commodity,
        "origin": origin,
    }


def _num(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    out = float(value)
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _date(value: object) -> pd.Timestamp:
    return pd.to_datetime(value, errors="coerce").normalize()


def _eligible(df: pd.DataFrame, as_of_date: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df
    return df.loc[pd.to_datetime(df["feature_available_at"], errors="coerce") <= as_of_date].copy()


def _latest(df: pd.DataFrame, date_col: str = "observation_date") -> pd.Series | None:
    if df.empty or date_col not in df.columns:
        return None
    ordered = df.dropna(subset=[date_col]).sort_values(date_col)
    if ordered.empty:
        return None
    return ordered.iloc[-1]


def _emit(
    rows: list[dict],
    *,
    ctx: dict[str, str],
    crop_year: int,
    as_of_date: pd.Timestamp,
    snapshot_stage: str,
    feature: str,
    value: float | None,
    available_at: object,
    source: str,
    source_vintage: object,
    is_label: bool = False,
) -> None:
    numeric = _num(value)
    if numeric is None:
        return
    rows.append({
        **ctx,
        "crop_year": int(crop_year),
        "as_of_date": _date(as_of_date),
        "snapshot_stage": snapshot_stage,
        "feature": feature,
        "value": numeric,
        "feature_available_at": _date(available_at),
        "source": source,
        "source_vintage": "" if pd.isna(source_vintage) else str(source_vintage),
        "is_label": bool(is_label),
    })


def _normalize_inputs(inputs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for source, df in inputs.items():
        if df is None:
            continue
        out[source] = normalize_availability(source, df)
    return out


def _feature_nass_crop_progress(
    rows: list[dict],
    inputs: dict[str, pd.DataFrame],
    ctx: dict[str, str],
    crop_year: int,
    as_of_date: pd.Timestamp,
    snapshot_stage: str,
) -> None:
    df = inputs.get("nass_crop_progress")
    if df is None or df.empty:
        return
    work = _eligible(df, as_of_date)
    if "year" in work.columns:
        work = work.loc[pd.to_numeric(work["year"], errors="coerce") == int(crop_year)]
    if "state" in work.columns and (work["state"].astype(str) == "US").any():
        work = work.loc[work["state"].astype(str) == "US"]
    latest = _latest(work)
    if latest is None:
        return
    for column, feature in [
        ("pct_good_excellent", "nass_ge_pct_latest"),
        ("pct_planted", "nass_planted_pct_latest"),
        ("pct_harvested", "nass_harvested_pct_latest"),
    ]:
        if column in latest:
            _emit(
                rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
                snapshot_stage=snapshot_stage, feature=feature, value=latest[column],
                available_at=latest["feature_available_at"], source="nass_crop_progress",
                source_vintage=latest["source_vintage"],
            )
    if "pct_good_excellent" in work.columns:
        latest_date = pd.Timestamp(latest["observation_date"])
        prior = _latest(work.loc[work["observation_date"] <= latest_date - pd.Timedelta(days=28)])
        if prior is not None:
            _emit(
                rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
                snapshot_stage=snapshot_stage, feature="nass_ge_pct_change_4w",
                value=_num(latest["pct_good_excellent"]) - _num(prior["pct_good_excellent"])
                if _num(latest["pct_good_excellent"]) is not None
                and _num(prior["pct_good_excellent"]) is not None
                else None,
                available_at=latest["feature_available_at"],
                source="nass_crop_progress",
                source_vintage=latest["source_vintage"],
            )


def _feature_esr(
    rows: list[dict],
    inputs: dict[str, pd.DataFrame],
    ctx: dict[str, str],
    crop_year: int,
    as_of_date: pd.Timestamp,
    snapshot_stage: str,
) -> None:
    df = inputs.get("esr")
    if df is None or df.empty or "market_year" not in df.columns:
        return
    work = _eligible(df, as_of_date)
    if "weekly_exports_1000mt" not in work.columns:
        return
    annual = (
        work.assign(market_year=pd.to_numeric(work["market_year"], errors="coerce"))
        .dropna(subset=["market_year"])
        .groupby("market_year")["weekly_exports_1000mt"]
        .sum()
        .sort_index()
    )
    if annual.empty:
        return
    z = trailing_baseline_z(annual.astype(float), window_years=5, min_years=3)
    value = z.get(float(crop_year), np.nan)
    vintage_rows = work.loc[pd.to_numeric(work["market_year"], errors="coerce") == int(crop_year)]
    vintage = _latest(vintage_rows) if not vintage_rows.empty else _latest(work)
    if vintage is None:
        return
    _emit(
        rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
        snapshot_stage=snapshot_stage, feature="esr_export_pace_z", value=value,
        available_at=vintage["feature_available_at"], source="esr",
        source_vintage=vintage["source_vintage"],
    )


def _feature_fgis(
    rows: list[dict],
    inputs: dict[str, pd.DataFrame],
    ctx: dict[str, str],
    crop_year: int,
    as_of_date: pd.Timestamp,
    snapshot_stage: str,
) -> None:
    df = inputs.get("fgis")
    if df is None or df.empty or "marketing_year" not in df.columns:
        return
    work = _eligible(df, as_of_date)
    value_col = "exports_mt_ctd" if "exports_mt_ctd" in work.columns else "exports_mt_weekly"
    if value_col not in work.columns:
        return
    annual = (
        work.assign(marketing_year=pd.to_numeric(work["marketing_year"], errors="coerce"))
        .dropna(subset=["marketing_year"])
        .groupby("marketing_year")[value_col]
        .sum()
        .sort_index()
    )
    if int(crop_year) not in annual.index or int(crop_year) - 1 not in annual.index:
        return
    prev = float(annual.loc[int(crop_year) - 1])
    if prev == 0:
        return
    value = (float(annual.loc[int(crop_year)]) - prev) / prev
    vintage_rows = work.loc[pd.to_numeric(work["marketing_year"], errors="coerce") == int(crop_year)]
    vintage = _latest(vintage_rows) if not vintage_rows.empty else _latest(work)
    if vintage is None:
        return
    _emit(
        rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
        snapshot_stage=snapshot_stage, feature="fgis_export_pace_yoy", value=value,
        available_at=vintage["feature_available_at"], source="fgis",
        source_vintage=vintage["source_vintage"],
    )


def _revision_source(inputs: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame | None]:
    if "wasde" in inputs and not inputs["wasde"].empty:
        return "wasde", inputs["wasde"]
    if "wap_revisions" in inputs and not inputs["wap_revisions"].empty:
        return "wap_revisions", inputs["wap_revisions"]
    return "wasde", None


def _feature_wasde_revisions(
    rows: list[dict],
    inputs: dict[str, pd.DataFrame],
    ctx: dict[str, str],
    crop_year: int,
    as_of_date: pd.Timestamp,
    snapshot_stage: str,
) -> None:
    source, df = _revision_source(inputs)
    if df is None or df.empty:
        return
    work = _eligible(df, as_of_date)
    revision_col = "revision" if "revision" in work.columns else "revision_mmt"
    if revision_col not in work.columns:
        return
    year_col = "marketing_year" if "marketing_year" in work.columns else None
    if year_col:
        years = pd.to_numeric(work[year_col].astype(str).str.extract(r"(\d{4})")[0], errors="coerce")
        scoped = work.loc[years == int(crop_year)].copy()
    else:
        scoped = work.copy()
    if scoped.empty:
        return
    scoped = scoped.sort_values("feature_available_at")
    latest_release = scoped["feature_available_at"].max()
    latest_rows = scoped.loc[scoped["feature_available_at"] == latest_release]
    latest_revision = pd.to_numeric(latest_rows[revision_col], errors="coerce").sum(min_count=1)
    nonzero = (
        pd.to_numeric(scoped[revision_col], errors="coerce")
        .fillna(0.0)
        .loc[lambda s: s != 0]
    )
    consecutive = 0
    last_sign: float | None = None
    for value in reversed(nonzero.tolist()):
        sign = math.copysign(1.0, value)
        if last_sign is None:
            last_sign = sign
        if sign != last_sign:
            break
        consecutive += 1
    vintage = _latest(latest_rows, "feature_available_at")
    if vintage is None:
        return
    _emit(
        rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
        snapshot_stage=snapshot_stage, feature="wasde_latest_revision",
        value=latest_revision, available_at=vintage["feature_available_at"],
        source=source, source_vintage=vintage["source_vintage"],
    )
    _emit(
        rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
        snapshot_stage=snapshot_stage, feature="wasde_consecutive_revision_count",
        value=consecutive, available_at=vintage["feature_available_at"],
        source=source, source_vintage=vintage["source_vintage"],
    )


def _rolling_latest_z(series: pd.Series, window: int = 60, min_periods: int = 12) -> pd.Series:
    prior = series.shift(1)
    mean = prior.rolling(window, min_periods=min_periods).mean()
    std = prior.rolling(window, min_periods=min_periods).std()
    return ((series - mean) / std).replace([np.inf, -np.inf], np.nan)


def _feature_pink_sheet(
    rows: list[dict],
    inputs: dict[str, pd.DataFrame],
    ctx: dict[str, str],
    crop_year: int,
    as_of_date: pd.Timestamp,
    snapshot_stage: str,
) -> None:
    df = inputs.get("pink_sheet")
    if df is None or df.empty:
        return
    work = _eligible(df, as_of_date).sort_values("observation_date").copy()
    if work.empty:
        return
    latest = _latest(work)
    if latest is None:
        return
    if "brent_crude_usd_bbl_zscore_5yr" in latest:
        _emit(
            rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
            snapshot_stage=snapshot_stage, feature="pink_sheet_energy_z",
            value=latest["brent_crude_usd_bbl_zscore_5yr"],
            available_at=latest["feature_available_at"], source="pink_sheet",
            source_vintage=latest["source_vintage"],
        )
    if {"soybean_oil_usd_t", "palm_oil_cpo_usd_t"} <= set(work.columns):
        premium = (
            pd.to_numeric(work["soybean_oil_usd_t"], errors="coerce")
            - pd.to_numeric(work["palm_oil_cpo_usd_t"], errors="coerce")
        )
        ratio = (
            pd.to_numeric(work["soybean_oil_usd_t"], errors="coerce")
            / pd.to_numeric(work["palm_oil_cpo_usd_t"], errors="coerce")
        )
        premium_z = _rolling_latest_z(premium)
        ratio_z = _rolling_latest_z(ratio)
        _emit(
            rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
            snapshot_stage=snapshot_stage, feature="veg_oil_soy_palm_premium_z",
            value=premium_z.iloc[-1], available_at=latest["feature_available_at"],
            source="pink_sheet", source_vintage=latest["source_vintage"],
        )
        _emit(
            rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
            snapshot_stage=snapshot_stage, feature="veg_oil_soy_palm_ratio_z",
            value=ratio_z.iloc[-1], available_at=latest["feature_available_at"],
            source="pink_sheet", source_vintage=latest["source_vintage"],
        )


def _feature_crush(
    rows: list[dict],
    inputs: dict[str, pd.DataFrame],
    ctx: dict[str, str],
    crop_year: int,
    as_of_date: pd.Timestamp,
    snapshot_stage: str,
) -> None:
    if ctx["contract_slug"] not in {
        "soybeans_cbot",
        "soybean_meal_cbot",
        "soybean_oil_cbot",
        "soybeans_no_1_dce",
        "soybeans_no_2_dce",
        "soybean_meal_dce",
        "soybean_oil_dce",
    }:
        return
    df = inputs.get("futures_prices")
    if df is None or df.empty:
        return
    work = _eligible(df, as_of_date)
    if not {"leviathan_slug", "close"} <= set(work.columns):
        return
    legs = work.loc[work["leviathan_slug"].isin(_SOY_CRUSH_LEGS.values())].copy()
    if legs.empty:
        return
    wide = legs.pivot_table(
        index="observation_date", columns="leviathan_slug", values="close", aggfunc="last"
    ).dropna(subset=list(_SOY_CRUSH_LEGS.values()))
    if wide.empty:
        return
    crush = (
        0.022 * wide[_SOY_CRUSH_LEGS["meal"]]
        + 0.11 * wide[_SOY_CRUSH_LEGS["oil"]]
        - 0.01 * wide[_SOY_CRUSH_LEGS["beans"]]
    ).sort_index()
    z = _rolling_latest_z(crush, window=252 * 5, min_periods=252)
    latest_date = z.dropna().index.max() if not z.dropna().empty else None
    if latest_date is None:
        return
    latest_rows = legs.loc[legs["observation_date"] == latest_date]
    latest = _latest(latest_rows)
    if latest is None:
        latest = _latest(legs)
    if latest is None:
        return
    _emit(
        rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
        snapshot_stage=snapshot_stage, feature="crush_margin_z", value=z.loc[latest_date],
        available_at=latest["feature_available_at"], source="futures_prices",
        source_vintage=latest["source_vintage"],
    )


def _feature_mpob(
    rows: list[dict],
    inputs: dict[str, pd.DataFrame],
    ctx: dict[str, str],
    crop_year: int,
    as_of_date: pd.Timestamp,
    snapshot_stage: str,
) -> None:
    if ctx["contract_slug"] not in {"malaysian_crude_palm_oil_cme", "palm_olein_dce"}:
        return
    df = inputs.get("mpob")
    if df is None or df.empty:
        return
    work = _eligible(df, as_of_date).sort_values("observation_date").copy()
    if work.empty:
        return
    latest = _latest(work)
    if latest is None:
        return
    for column, feature in [
        ("exports_palm_oil_mt", "mpob_exports_z"),
        ("su_ratio", "mpob_su_ratio_z"),
    ]:
        if column not in work.columns:
            continue
        z = _rolling_latest_z(pd.to_numeric(work[column], errors="coerce"))
        _emit(
            rows, ctx=ctx, crop_year=crop_year, as_of_date=as_of_date,
            snapshot_stage=snapshot_stage, feature=feature, value=z.iloc[-1],
            available_at=latest["feature_available_at"], source="mpob",
            source_vintage=latest["source_vintage"],
        )


def build_spine_v2(
    *,
    commodity: str,
    crop_years: Iterable[int],
    inputs: dict[str, pd.DataFrame],
    as_of_dates: dict[int, object] | None = None,
    snapshot_policy: str = "default_v1",
) -> SpineV2BuildResult:
    """Build the Phase 4 thin gold_v2 spine for one contract slug."""
    crop_years = [int(year) for year in crop_years]
    as_of_dates = as_of_dates or default_as_of_dates(crop_years)
    normalized_inputs = _normalize_inputs(inputs)
    ctx = _contract_context(commodity)
    rows: list[dict] = []

    for crop_year in crop_years:
        as_of = _date(as_of_dates[int(crop_year)])
        snapshot_stage = snapshot_stage_for(as_of, crop_year, snapshot_policy)
        _feature_nass_crop_progress(rows, normalized_inputs, ctx, crop_year, as_of, snapshot_stage)
        _feature_esr(rows, normalized_inputs, ctx, crop_year, as_of, snapshot_stage)
        _feature_fgis(rows, normalized_inputs, ctx, crop_year, as_of, snapshot_stage)
        _feature_wasde_revisions(rows, normalized_inputs, ctx, crop_year, as_of, snapshot_stage)
        _feature_pink_sheet(rows, normalized_inputs, ctx, crop_year, as_of, snapshot_stage)
        _feature_crush(rows, normalized_inputs, ctx, crop_year, as_of, snapshot_stage)
        _feature_mpob(rows, normalized_inputs, ctx, crop_year, as_of, snapshot_stage)

    df = pd.DataFrame(rows, columns=SPINE_V2_COLUMNS)
    report = validate_spine_v2(df, commodity=commodity)
    return SpineV2BuildResult(
        commodity=commodity,
        df=df.sort_values(SPINE_V2_NATURAL_KEY).reset_index(drop=True)
        if not df.empty else df,
        report=report,
        passed=report["passed"],
    )


def validate_spine_v2(df: pd.DataFrame, *, commodity: str) -> dict:
    hard: dict[str, object] = {}
    if df.empty:
        return {
            "commodity": commodity,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "row_count": 0,
            "feature_count": 0,
            "passed": True,
            "hard_failures": {},
        }
    missing = set(SPINE_V2_COLUMNS) - set(df.columns)
    if missing:
        hard["missing_columns"] = sorted(missing)
    null_keys = {
        column: int(df[column].isna().sum())
        for column in SPINE_V2_NATURAL_KEY
        if column in df.columns and int(df[column].isna().sum())
    }
    if null_keys:
        hard["null_key_values"] = null_keys
    dupes = int(df.duplicated(subset=SPINE_V2_NATURAL_KEY).sum())
    if dupes:
        hard["duplicate_natural_keys"] = dupes
    available = pd.to_datetime(df["feature_available_at"], errors="coerce")
    as_of = pd.to_datetime(df["as_of_date"], errors="coerce")
    future = int((available > as_of).sum())
    if future:
        hard["future_available_features"] = future
    return {
        "commodity": commodity,
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "row_count": int(len(df)),
        "feature_count": int(df["feature"].nunique()),
        "passed": not hard,
        "hard_failures": hard,
    }
