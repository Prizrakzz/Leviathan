"""PSD monthly-vintage features at the annual feature-spine grain.

PSD rows are annual marketing-year estimates with monthly release vintages.
This module uses those vintages as point-in-time inputs while preserving the
annual PSD target policy: every crop-year feature sees only rows released on or
before the configured snapshot date.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from leviathan.features.computations.base import FeatureContext, empty_result, make_result

_CONFIG_PATH = Path(__file__).resolve().parents[4] / "configs" / "ml" / "psd_vintage_features.yaml"

_REQUIRED_COLUMNS = {"country", "market_year", "release_date"}


def _finite(value: object) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except Exception:  # noqa: BLE001
        return False


def _load_config(path: Path = _CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _allowed_columns(config: dict) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in config.get("feature_columns") or []:
        if item.get("allowed_as_feature", True) is False:
            continue
        attr = str(item.get("psd_attribute") or "")
        prefix = str(item.get("feature_prefix") or "")
        if attr and prefix:
            out.append({"attribute": attr, "prefix": prefix})
    return out


def _snapshot_date(ctx: FeatureContext, crop_year: int) -> pd.Timestamp:
    # Phase 6.5 supports the crop-year-start snapshot first. Additional
    # policies can be added once revision-target datasets exist.
    if ctx.calendar is None:
        return pd.Timestamp(year=int(crop_year), month=1, day=1)
    return pd.Timestamp(ctx.calendar.crop_year_start(int(crop_year)))


def _target_market_year(ctx: FeatureContext, crop_year: int) -> int:
    # Annual PSD targets use market_year == crop_year.  This intentionally
    # differs from legacy prior_marketing_year balance-sheet features.
    return int(crop_year)


def _latest_history_as_of(
    source: pd.DataFrame,
    attribute: str,
    *,
    snapshot: pd.Timestamp,
    market_year: int,
) -> pd.Series:
    """Latest visible historical value per market_year, indexed by market_year."""
    if attribute not in source.columns:
        return pd.Series(dtype=float)
    valid = source.loc[
        (source["market_year"] < int(market_year))
        & (source["release_date"] <= snapshot)
    ].dropna(subset=["market_year", "release_date", attribute]).copy()
    if valid.empty:
        return pd.Series(dtype=float)
    valid = valid.sort_values(["market_year", "release_date"])
    latest = valid.groupby("market_year", sort=True).tail(1)
    values = pd.to_numeric(latest[attribute], errors="coerce")
    years = pd.to_numeric(latest["market_year"], errors="coerce").astype("Int64")
    out = pd.Series(values.to_numpy(dtype=float), index=years.astype(int), dtype=float)
    return out.sort_index()


def _trend_prediction(
    yearly: pd.Series,
    market_year: int,
    *,
    min_history_years: int,
) -> float:
    prior = yearly.loc[yearly.index < int(market_year)].dropna()
    if len(prior) < min_history_years or len(pd.Index(prior.index).unique()) < 2:
        return np.nan
    coeffs = np.polyfit(prior.index.to_numpy(dtype=float), prior.to_numpy(dtype=float), 1)
    return float(np.polyval(coeffs, float(market_year)))


def _current_vs_trend(value: float, trend: float, epsilon: float) -> float:
    if not _finite(value) or not _finite(trend):
        return np.nan
    if abs(float(trend)) <= epsilon:
        return np.nan
    return (float(value) - float(trend)) / abs(float(trend))


def _revision_count(values: pd.Series) -> float:
    diffs = values.diff().dropna()
    diffs = diffs.loc[diffs != 0]
    if diffs.empty:
        return 0.0
    last_sign = math.copysign(1.0, float(diffs.iloc[-1]))
    run = 0
    for value in reversed(diffs.to_list()):
        sign = math.copysign(1.0, float(value))
        if sign != last_sign:
            break
        run += 1
    return float(run * int(last_sign))


def _prepare_psd(df: pd.DataFrame, columns: list[dict[str, str]]) -> pd.DataFrame:
    needed = _REQUIRED_COLUMNS | {item["attribute"] for item in columns}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"PSD vintage feature source missing columns: {sorted(missing)}")
    out = df.copy()
    out["market_year"] = pd.to_numeric(out["market_year"], errors="coerce")
    out["release_date"] = pd.to_datetime(out["release_date"], errors="coerce")
    out = out.dropna(subset=["country", "market_year", "release_date"])
    out["market_year"] = out["market_year"].astype(int)
    return out.sort_values(["country", "market_year", "release_date"]).reset_index(drop=True)


def compute_psd_monthly_vintage_features(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Emit PSD vintage features visible at each crop-year snapshot.

    Feature names are metric-specific, for example:
    ``psd_production_latest_estimate_as_of`` and
    ``psd_su_ratio_mom_revision``.
    """
    raw = ctx.inputs.get("psd")
    if raw is None or raw.empty:
        return empty_result()

    config = _load_config()
    defaults = config.get("defaults") or {}
    columns = [
        item for item in _allowed_columns(config)
        if item["attribute"] in raw.columns
    ]
    if not columns:
        return empty_result()

    source = _prepare_psd(raw, columns)
    min_history_years = int(defaults.get("min_history_years", 5))
    epsilon = float(defaults.get("near_zero_trend_epsilon", 1e-9))

    rows: list[tuple[str, int, str, float]] = []
    for country in ctx.countries:
        country_df = source.loc[source["country"] == country].copy()
        if country_df.empty:
            continue

        for crop_year in ctx.crop_years:
            market_year = _target_market_year(ctx, int(crop_year))
            snapshot = _snapshot_date(ctx, int(crop_year))
            visible = country_df.loc[
                (country_df["market_year"] == market_year)
                & (country_df["release_date"] <= snapshot)
            ].sort_values("release_date")
            if visible.empty:
                continue

            latest = visible.iloc[-1]
            release_count = float(len(visible))
            month_code = float(pd.Timestamp(latest["release_date"]).month)

            for item in columns:
                attr = item["attribute"]
                prefix = item["prefix"]
                values = pd.to_numeric(visible[attr], errors="coerce")
                latest_value = values.iloc[-1] if len(values) else np.nan
                previous_value = values.iloc[-2] if len(values) >= 2 else np.nan
                first_value = values.iloc[0] if len(values) else np.nan
                historical_values = _latest_history_as_of(
                    country_df,
                    attr,
                    snapshot=snapshot,
                    market_year=market_year,
                )
                trend = _trend_prediction(
                    historical_values,
                    market_year,
                    min_history_years=min_history_years,
                )

                rows.extend([
                    (country, int(crop_year), f"{prefix}_latest_estimate_as_of", latest_value),
                    (
                        country,
                        int(crop_year),
                        f"{prefix}_mom_revision",
                        latest_value - previous_value
                        if _finite(latest_value) and _finite(previous_value) else np.nan,
                    ),
                    (
                        country,
                        int(crop_year),
                        f"{prefix}_revision_since_first_forecast",
                        latest_value - first_value
                        if _finite(latest_value) and _finite(first_value) else np.nan,
                    ),
                    (
                        country,
                        int(crop_year),
                        f"{prefix}_consecutive_revision_count",
                        _revision_count(values),
                    ),
                    (
                        country,
                        int(crop_year),
                        f"{prefix}_current_vs_trend",
                        _current_vs_trend(latest_value, trend, epsilon),
                    ),
                    (country, int(crop_year), f"{prefix}_month_code", month_code),
                    (
                        country,
                        int(crop_year),
                        f"{prefix}_release_count_for_market_year",
                        release_count,
                    ),
                ])

    return make_result(rows)
