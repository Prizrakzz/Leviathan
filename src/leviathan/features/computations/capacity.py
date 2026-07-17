"""Tree-crop capacity recovery index (post-frost productive wood decay model).

Per desiredstate.md Layer 1: frost severity is classified from each prior crop
year's Tmin minimum, and remaining capacity loss decays exponentially with a
configurable half-life.  Only severity >= ``min_carryforward_severity`` events
carry across years (lighter frosts are one-season cherry damage captured by
``frost_event_flag``).

Point-in-time: only frost events in crop years STRICTLY BEFORE the observation
year are visible (visibility class ``prior_history``) — the observation year's
own frost is in-season information carried by ``frost_event_flag``.
"""
from __future__ import annotations

import pandas as pd

from leviathan.features.computations.base import (
    FeatureContext,
    assign_crop_year,
    empty_result,
    make_result,
)


def _severity(tmin_min: float, thresholds: list[float]) -> int:
    """0-3 severity tier from the annual Tmin minimum (thresholds descending)."""
    t1, t2, t3 = thresholds
    if tmin_min >= t1:
        return 0
    if tmin_min >= t2:
        return 1
    if tmin_min >= t3:
        return 2
    return 3


def compute_capacity_recovery_index(ctx: FeatureContext, spec) -> pd.DataFrame:
    params = ctx.params.get("capacity_recovery", {})
    if ctx.commodity not in set(params.get("tree_crops", [])):
        return empty_result()

    df = ctx.inputs.get("weather:nasa_power")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    df = df.loc[df["variable"] == "temperature_2m_min_c"].copy()
    if df.empty:
        return empty_result()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df["date"] = pd.to_datetime(df["date"])
    df["spine_crop_year"] = assign_crop_year(df, ctx.calendar)
    df = df.dropna(subset=["spine_crop_year"])

    thresholds = [float(t) for t in ctx.params.get("frost", {}).get(
        "severity_thresholds_c", [-2.0, -4.0, -6.0]
    )]
    half_life = float(params.get("half_life_years", 3.0))
    min_sev = int(params.get("min_carryforward_severity", 2))
    lookback_needed = int(round(half_life * 2))

    rows: list[tuple[str, int, str, float]] = []
    for (country, region), region_df in df.groupby(["country", "region"]):
        if country not in ctx.countries:
            continue
        yearly_min = region_df.groupby("spine_crop_year")["value"].min()
        yearly_min.index = yearly_min.index.astype(int)
        severities = {
            int(y): _severity(float(v), thresholds) for y, v in yearly_min.items()
        }
        series_start = min(severities) if severities else None
        feature = f"capacity_recovery_index_{region}"
        flag_feature = f"capacity_lookback_truncated_{region}"

        for crop_year in ctx.crop_years:
            if series_start is None or crop_year <= series_start:
                continue
            # Worst remaining loss across ALL prior carry-forward events —
            # overlapping events constrain capacity jointly, latest-only would
            # understate damage from an older, more severe frost.
            worst_loss = 0.0
            for event_year, sev in severities.items():
                if event_year >= crop_year or sev < min_sev:
                    continue
                years_since = crop_year - event_year
                loss = (sev / 3.0) * (0.5 ** (years_since / half_life))
                worst_loss = max(worst_loss, loss)
            capacity = 1.0 - worst_loss

            truncated = float(crop_year - series_start < lookback_needed)
            rows.append((country, crop_year, feature, capacity))
            rows.append((country, crop_year, flag_feature, truncated))
    return make_result(rows)
