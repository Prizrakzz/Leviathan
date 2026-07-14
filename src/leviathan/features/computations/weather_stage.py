"""Stage-window weather features: z-scores, anomalies, frost, GDD, drought.

All families here consume long-format silver weather frames
(``date, year, month, day, country, region, commodity, source, variable, value``)
already restricted by the extractor to the relevant source.

Window-completeness rule: an in-season aggregate whose stage window has not yet
fully elapsed (window end after the last available observation date for the
region) is emitted as NaN, never as a partial aggregate — a half-complete
flowering z-score looks like data but means something different.  Exception:
``frost_event_flag`` may emit 1 early (a frost already observed is a fact) but
never an early 0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.features.computations.base import (
    FeatureContext,
    assign_crop_year,
    dry_day_threshold,
    empty_result,
    make_result,
    max_consecutive_true,
    stage_month_set,
    trailing_baseline_z,
)


def _prepare(ctx: FeatureContext, source_key: str, variable: str) -> pd.DataFrame | None:
    """Slice one weather variable, with crop-year assignment. None if unusable."""
    df = ctx.inputs.get(source_key)
    if df is None or df.empty or ctx.calendar is None:
        return None
    df = df.loc[df["variable"] == variable].copy()
    if df.empty:
        return None
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df["date"] = pd.to_datetime(df["date"])
    df["spine_crop_year"] = assign_crop_year(df, ctx.calendar)
    return df.dropna(subset=["spine_crop_year"])


def _window_complete(window_end: pd.Timestamp, last_obs: pd.Timestamp) -> bool:
    return last_obs >= window_end


def _stage_yearly_aggregates(
    region_df: pd.DataFrame,
    ctx: FeatureContext,
    stage: str,
    agg: str,
) -> pd.Series:
    """Per-crop-year stage aggregate for one region; incomplete windows -> NaN."""
    months = stage_month_set(*ctx.calendar.stages[stage])
    in_stage = region_df.loc[region_df["date"].dt.month.isin(months)]
    if in_stage.empty:
        return pd.Series(dtype=float)

    yearly = in_stage.groupby("spine_crop_year")["value"].agg(agg)
    yearly.index = yearly.index.astype(int)

    last_obs = region_df["date"].max()
    out = {}
    for crop_year, value in yearly.items():
        window = ctx.calendar.stage_window(stage, int(crop_year))
        if _window_complete(pd.Timestamp(window.end_date), last_obs):
            out[int(crop_year)] = value
        else:
            out[int(crop_year)] = np.nan
    return pd.Series(out, dtype=float).sort_index()


def _stage_z_family(
    ctx: FeatureContext,
    spec,
    source_key: str,
    variable: str,
    name_prefix: str,
    agg: str,
) -> pd.DataFrame:
    df = _prepare(ctx, source_key, variable)
    if df is None:
        return empty_result()

    baselines = ctx.params.get("baselines", {})
    window_years = int(baselines.get("window_years", 30))
    min_years = int(baselines.get("min_years", 10))

    rows: list[tuple[str, int, str, float]] = []
    for (country, region), region_df in df.groupby(["country", "region"]):
        if country not in ctx.countries:
            continue
        for stage in ctx.calendar.stages:
            yearly = _stage_yearly_aggregates(region_df, ctx, stage, agg)
            if yearly.empty:
                continue
            z = trailing_baseline_z(yearly, window_years, min_years)
            feature = f"{name_prefix}_{region}_{stage}"
            for crop_year in ctx.crop_years:
                rows.append((country, crop_year, feature, z.get(crop_year, np.nan)))
    return make_result(rows)


def compute_stage_precip_z(ctx: FeatureContext, spec) -> pd.DataFrame:
    return _stage_z_family(
        ctx, spec, "weather:chirps", "precipitation_mm", "chirps_precip_z", "mean"
    )


def compute_stage_tmax_anomaly(ctx: FeatureContext, spec) -> pd.DataFrame:
    return _stage_z_family(
        ctx, spec, "weather:nasa_power", "temperature_2m_max_c", "nasa_tmax_anomaly", "mean"
    )


def compute_stage_tmin_anomaly(ctx: FeatureContext, spec) -> pd.DataFrame:
    return _stage_z_family(
        ctx, spec, "weather:nasa_power", "temperature_2m_min_c", "nasa_tmin_anomaly", "mean"
    )


def compute_frost_event_flag(ctx: FeatureContext, spec) -> pd.DataFrame:
    """1 if Tmin < 0°C inside the frost-sensitive window of the crop year.

    Uses the ``frost_risk`` stage when the calendar defines one, otherwise the
    whole crop year.  Early 1 is allowed (frost observed is a fact); an early 0
    for an incomplete window is suppressed to NaN.
    """
    df = _prepare(ctx, "weather:nasa_power", "temperature_2m_min_c")
    if df is None:
        return empty_result()

    has_stage = "frost_risk" in ctx.calendar.stages
    months = (
        stage_month_set(*ctx.calendar.stages["frost_risk"]) if has_stage else set(range(1, 13))
    )

    rows: list[tuple[str, int, str, float]] = []
    for (country, region), region_df in df.groupby(["country", "region"]):
        if country not in ctx.countries:
            continue
        in_window = region_df.loc[region_df["date"].dt.month.isin(months)]
        if in_window.empty:
            continue
        yearly_min = in_window.groupby("spine_crop_year")["value"].min()
        last_obs = region_df["date"].max()
        feature = f"frost_event_flag_{region}"
        for crop_year in ctx.crop_years:
            tmin = yearly_min.get(crop_year, np.nan)
            if pd.isna(tmin):
                value = np.nan
            elif tmin < 0.0:
                value = 1.0
            else:
                window_end = (
                    pd.Timestamp(ctx.calendar.stage_window("frost_risk", crop_year).end_date)
                    if has_stage
                    else pd.Timestamp(ctx.calendar.crop_year_end(crop_year))
                )
                value = 0.0 if _window_complete(window_end, last_obs) else np.nan
            rows.append((country, crop_year, feature, value))
    return make_result(rows)


def compute_gdd_z(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Growing Degree Days accumulated over the GDD window, z-scored vs. trailing baseline.

    Raw GDD totals are cross-commodity and cross-country incomparable (corn ~2700 GDD,
    wheat ~1200 GDD).  The z-score normalises each year against the prior-years
    baseline for that specific (commodity, country, region), making the feature
    dimensionless and comparable.

    ``GDD_day = max(0, (min(Tmax, cap) + max(Tmin, base)) / 2 - base)``
    ``z[Y] = (gdd[Y] - mean(gdd[Y-w..Y-1])) / std(gdd[Y-w..Y-1])``
    Incomplete windows -> NaN.
    """
    if ctx.calendar is None or ctx.calendar.gdd_window is None:
        return empty_result()

    tmax = _prepare(ctx, "weather:nasa_power", "temperature_2m_max_c")
    tmin = _prepare(ctx, "weather:nasa_power", "temperature_2m_min_c")
    if tmax is None or tmin is None:
        return empty_result()

    gdd_params = ctx.params.get("gdd", {})
    crop_cfg = (gdd_params.get("per_commodity") or {}).get(
        ctx.commodity, gdd_params.get("default", {})
    )
    base = float(crop_cfg.get("base_c", 10.0))
    cap = float(crop_cfg.get("cap_c", 30.0))

    baselines = ctx.params.get("baselines", {})
    window_years = int(baselines.get("window_years", 30))
    min_years = int(baselines.get("min_years", 10))

    first_stage, last_stage = ctx.calendar.gdd_window
    start_month = ctx.calendar.stages[first_stage][0]
    end_month = ctx.calendar.stages[last_stage][1]
    months = stage_month_set(start_month, end_month)

    key = ["country", "region", "date", "spine_crop_year"]
    merged = pd.merge(
        tmax[key + ["value"]].rename(columns={"value": "tmax"}),
        tmin[key + ["value"]].rename(columns={"value": "tmin"}),
        on=key,
        how="inner",
    )
    merged = merged.loc[merged["date"].dt.month.isin(months)]
    if merged.empty:
        return empty_result()

    tmax_adj = merged["tmax"].clip(upper=cap)
    tmin_adj = merged["tmin"].clip(lower=base)
    merged["gdd"] = ((tmax_adj + tmin_adj) / 2.0 - base).clip(lower=0.0)

    rows: list[tuple[str, int, str, float]] = []
    for (country, region), region_df in merged.groupby(["country", "region"]):
        if country not in ctx.countries:
            continue
        last_obs = region_df["date"].max()
        yearly_raw = region_df.groupby("spine_crop_year")["gdd"].sum()
        yearly_raw.index = yearly_raw.index.astype(int)

        # Include only complete windows in the baseline series.
        complete: dict[int, float] = {}
        for crop_year, total in yearly_raw.items():
            window = ctx.calendar.gdd_dates(int(crop_year))
            if window and _window_complete(pd.Timestamp(window[1]), last_obs):
                complete[int(crop_year)] = float(total)

        if not complete:
            continue

        z = trailing_baseline_z(
            pd.Series(complete, dtype=float).sort_index(), window_years, min_years
        )
        feature = f"gdd_z_{region}"
        for crop_year in ctx.crop_years:
            rows.append((country, crop_year, feature, z.get(crop_year, np.nan)))
    return make_result(rows)


def compute_heat_stress_z(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Count of days above a crop-specific heat threshold in the GDD window,
    z-scored vs. the trailing baseline.

    Heat during the critical reproductive window is one of the most predictive
    yield signals — corn yield collapses above ~35 °C at silking — and is *not*
    captured by ``gdd_z`` (capped accumulation) or ``nasa_tmax_anomaly`` (stage
    mean).  This counts threshold exceedances over the same window ``gdd_z`` uses,
    then z-scores per (commodity, country, region) so it is comparable across
    regions.  Incomplete windows -> NaN.

    Emits:
      heat_stress_z_<region>
    """
    if ctx.calendar is None or ctx.calendar.gdd_window is None:
        return empty_result()

    tmax = _prepare(ctx, "weather:nasa_power", "temperature_2m_max_c")
    if tmax is None:
        return empty_result()

    hs_params = ctx.params.get("heat_stress", {})
    crop_cfg = (hs_params.get("per_commodity") or {}).get(
        ctx.commodity, hs_params.get("default", {})
    )
    threshold = float(crop_cfg.get("threshold_c", 35.0))

    baselines = ctx.params.get("baselines", {})
    window_years = int(baselines.get("window_years", 30))
    min_years = int(baselines.get("min_years", 10))

    first_stage, last_stage = ctx.calendar.gdd_window
    start_month = ctx.calendar.stages[first_stage][0]
    end_month = ctx.calendar.stages[last_stage][1]
    months = stage_month_set(start_month, end_month)

    df = tmax.loc[tmax["date"].dt.month.isin(months)].copy()
    if df.empty:
        return empty_result()
    df["hot"] = (df["value"] > threshold).astype(float)

    rows: list[tuple[str, int, str, float]] = []
    for (country, region), region_df in df.groupby(["country", "region"]):
        if country not in ctx.countries:
            continue
        last_obs = region_df["date"].max()
        yearly = region_df.groupby("spine_crop_year")["hot"].sum()
        yearly.index = yearly.index.astype(int)

        complete: dict[int, float] = {}
        for crop_year, total in yearly.items():
            window = ctx.calendar.gdd_dates(int(crop_year))
            if window and _window_complete(pd.Timestamp(window[1]), last_obs):
                complete[int(crop_year)] = float(total)
        if not complete:
            continue

        z = trailing_baseline_z(
            pd.Series(complete, dtype=float).sort_index(), window_years, min_years
        )
        feature = f"heat_stress_z_{region}"
        for crop_year in ctx.crop_years:
            rows.append((country, crop_year, feature, z.get(crop_year, np.nan)))
    return make_result(rows)


def compute_cpc_soil_z(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Stage-level soil moisture z-scores from CPC daily soil moisture data.

    Same trailing-baseline-z pattern as stage_precip_z but for soil moisture.
    """
    return _stage_z_family(
        ctx, spec, "weather:cpc_soil", "soil_moisture_mm", "cpc_soil_z", "mean"
    )


def compute_modis_ndvi_z(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Stage-mean NDVI anomaly from MODIS 8-day composites.

    Silver already carries ``ndvi_z_score`` (precomputed vs. the MODIS
    climatological baseline), so we aggregate stage means of that z-score
    rather than running a second trailing-baseline-z on top.
    Mean of z-scores within a stage is a valid anomaly aggregate for a
    gradient-boosting model.
    """
    df = _prepare(ctx, "weather:modis_ndvi", "ndvi_z_score")
    if df is None:
        return empty_result()

    rows: list[tuple[str, int, str, float]] = []
    for (country, region), region_df in df.groupby(["country", "region"]):
        if country not in ctx.countries:
            continue
        last_obs = region_df["date"].max()
        for stage in ctx.calendar.stages:
            months = stage_month_set(*ctx.calendar.stages[stage])
            in_stage = region_df.loc[region_df["date"].dt.month.isin(months)]
            if in_stage.empty:
                continue
            yearly = in_stage.groupby("spine_crop_year")["value"].mean()
            yearly.index = yearly.index.astype(int)
            feature = f"modis_ndvi_z_{region}_{stage}"
            for crop_year in ctx.crop_years:
                window = ctx.calendar.stage_window(stage, crop_year)
                if not _window_complete(pd.Timestamp(window.end_date), last_obs):
                    continue
                val = yearly.get(crop_year, np.nan)
                if not np.isnan(val):
                    rows.append((country, crop_year, feature, float(val)))
    return make_result(rows)


def compute_drought_z(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Z-score of longest consecutive dry-day run per stage, vs. trailing baseline.

    Two normalisation layers:
      1. Dry-day threshold: bottom ``dry_percentile`` of daily precipitation in
         the same stage months over prior ``window_years`` crop years.  This makes
         "dry" relative to the local climatology of each (region, stage).
      2. Run-count z-score: the annual count of consecutive dry days is itself
         z-scored vs. the prior-year baseline, making the output dimensionless
         and comparable across arid and humid regions.

    All prior years are processed first (pass 1) to populate the z-score baseline;
    only ctx.crop_years are emitted (pass 2).  Incomplete windows and years with
    < min_years of baseline yield NaN.
    """
    df = _prepare(ctx, "weather:chirps", "precipitation_mm")
    if df is None:
        return empty_result()

    baselines = ctx.params.get("baselines", {})
    window_years = int(baselines.get("window_years", 30))
    min_years = int(baselines.get("min_years", 10))
    pctile = float(ctx.params.get("drought", {}).get("dry_percentile", 20.0))

    rows: list[tuple[str, int, str, float]] = []
    for (country, region), region_df in df.groupby(["country", "region"]):
        if country not in ctx.countries:
            continue
        last_obs = region_df["date"].max()
        for stage in ctx.calendar.stages:
            months = stage_month_set(*ctx.calendar.stages[stage])
            in_stage = region_df.loc[region_df["date"].dt.month.isin(months)]
            if in_stage.empty:
                continue
            by_year = {
                int(cy): g.sort_values("date")
                for cy, g in in_stage.groupby("spine_crop_year")
            }

            # Pass 1: compute raw run count for every complete year in the data.
            # Iterating all available years (not just ctx.crop_years) ensures the
            # z-score baseline covers the full history.
            yearly_runs: dict[int, float] = {}
            for crop_year in sorted(by_year.keys()):
                current = by_year[crop_year]
                window_end = pd.Timestamp(
                    ctx.calendar.stage_window(stage, crop_year).end_date
                )
                baseline_years = [
                    y for y in by_year if crop_year - window_years <= y < crop_year
                ]
                if (
                    not _window_complete(window_end, last_obs)
                    or len(baseline_years) < min_years
                ):
                    continue
                baseline = np.concatenate(
                    [by_year[y]["value"].to_numpy() for y in baseline_years]
                )
                # floored at DRY_DAY_FLOOR_MM (see computations.base): zero-inflated baselines
                # degenerate the percentile to 0.0 and the strict < makes dry days impossible
                threshold = dry_day_threshold(baseline, pctile)
                run = max_consecutive_true(current["value"].to_numpy() < threshold)
                yearly_runs[crop_year] = float(run)

            if not yearly_runs:
                continue

            # Pass 2: z-score the annual run counts vs. trailing baseline of counts.
            z = trailing_baseline_z(
                pd.Series(yearly_runs, dtype=float).sort_index(), window_years, min_years
            )
            feature = f"drought_z_{region}_{stage}"
            for crop_year in ctx.crop_years:
                rows.append((country, crop_year, feature, z.get(crop_year, np.nan)))
    return make_result(rows)


def _parse_region_stage_feature(
    feature: str,
    *,
    prefix: str,
    stages: list[str],
) -> tuple[str, str] | None:
    base = f"{prefix}_"
    if not feature.startswith(base):
        return None
    body = feature[len(base):]
    for stage in sorted(stages, key=len, reverse=True):
        suffix = f"_{stage}"
        if body.endswith(suffix):
            region = body[:-len(suffix)]
            if region:
                return region, stage
    return None


def _parse_region_feature(
    feature: str,
    *,
    prefix: str,
    stage: str,
) -> tuple[str, str] | None:
    base = f"{prefix}_"
    if not feature.startswith(base):
        return None
    region = feature[len(base):]
    return (region, stage) if region else None


def _dense_metric_rows(
    base_df: pd.DataFrame,
    *,
    ctx: FeatureContext,
    base_prefix: str,
    dense_metric: str,
    stage_aware: bool,
    default_stage: str,
    stats: tuple[str, ...],
    expected_regions: dict[tuple[str, str], set[str]] | None = None,
    share_name: str | None = None,
    share_direction: str = "high",
    share_threshold: float = 1.0,
) -> list[tuple[str, int, str, float]]:
    if base_df.empty or ctx.calendar is None:
        return []

    stages = list(ctx.calendar.stages)
    parsed_rows: list[dict[str, object]] = []
    for row in base_df.itertuples(index=False):
        feature = str(row.feature)
        parsed = (
            _parse_region_stage_feature(feature, prefix=base_prefix, stages=stages)
            if stage_aware else
            _parse_region_feature(feature, prefix=base_prefix, stage=default_stage)
        )
        if parsed is None:
            continue
        region, stage = parsed
        parsed_rows.append({
            "country": str(row.country),
            "crop_year": int(row.crop_year),
            "stage": stage,
            "region": region,
            "value": float(row.value),
        })
    if not parsed_rows:
        return []

    parsed_df = pd.DataFrame(parsed_rows)
    parsed_df = parsed_df.loc[parsed_df["country"].isin(set(ctx.countries))]
    if parsed_df.empty:
        return []

    per_region = (
        parsed_df
        .groupby(["country", "crop_year", "stage", "region"], as_index=False)["value"]
        .mean()
    )
    emitted_regions = (
        parsed_df
        .groupby(["country", "stage"])["region"]
        .apply(lambda values: set(str(value) for value in values))
        .to_dict()
    )
    expected_region_sets: dict[tuple[str, str], set[str]] = {}
    for key, regions in emitted_regions.items():
        expected_region_sets[key] = set(regions)
    for key, regions in (expected_regions or {}).items():
        expected_region_sets[key] = expected_region_sets.get(key, set()) | set(regions)
    per_region = per_region.loc[per_region["crop_year"].isin(set(ctx.crop_years))]
    if per_region.empty:
        return []

    rows: list[tuple[str, int, str, float]] = []
    for (country, crop_year, stage), group in per_region.groupby(
        ["country", "crop_year", "stage"], sort=True
    ):
        values = pd.to_numeric(group["value"], errors="coerce").dropna()
        if values.empty:
            continue
        expected_count = int(len(expected_region_sets.get((country, stage), set())))
        expected_count = expected_count or len(values)
        coverage_share = float(len(values) / expected_count) if expected_count else np.nan
        if "mean" in stats:
            rows.append((country, int(crop_year), f"weather_dense_{dense_metric}_mean_{stage}", float(values.mean())))
        if "min" in stats:
            rows.append((country, int(crop_year), f"weather_dense_{dense_metric}_min_{stage}", float(values.min())))
        if "max" in stats:
            rows.append((country, int(crop_year), f"weather_dense_{dense_metric}_max_{stage}", float(values.max())))
        if share_name:
            if share_direction == "low":
                share = float((values <= -abs(share_threshold)).mean())
            else:
                share = float((values >= abs(share_threshold)).mean())
            rows.append((country, int(crop_year), f"weather_dense_{dense_metric}_{share_name}_{stage}", share))
        if coverage_share < 1.0:
            rows.append((
                country,
                int(crop_year),
                f"weather_dense_{dense_metric}_coverage_share_{stage}",
                coverage_share,
            ))
    return rows


def _expected_regions_from_source(
    ctx: FeatureContext,
    *,
    source_key: str,
    variable: str,
    stage_aware: bool,
    default_stage: str,
) -> dict[tuple[str, str], set[str]]:
    if ctx.calendar is None:
        return {}
    df = ctx.inputs.get(source_key)
    if df is None or df.empty or "variable" not in df.columns:
        return {}
    df = df.loc[df["variable"] == variable].copy()
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    df = df.loc[df["country"].isin(set(ctx.countries))]
    if df.empty:
        return {}

    out: dict[tuple[str, str], set[str]] = {}
    if not stage_aware:
        for country, group in df.groupby("country"):
            out[(str(country), default_stage)] = set(group["region"].astype(str).unique())
        return out

    for stage, months_raw in ctx.calendar.stages.items():
        months = stage_month_set(*months_raw)
        in_stage = df.loc[df["date"].dt.month.isin(months)]
        for country, group in in_stage.groupby("country"):
            out[(str(country), stage)] = set(group["region"].astype(str).unique())
    return out


def _dense_base_context(ctx: FeatureContext) -> FeatureContext:
    if ctx.calendar is None:
        return ctx
    years = set(int(year) for year in ctx.crop_years)
    for source_key in (
        "weather:chirps",
        "weather:nasa_power",
        "weather:cpc_soil",
        "weather:modis_ndvi",
    ):
        df = ctx.inputs.get(source_key)
        if df is None or df.empty or "year" not in df.columns or "month" not in df.columns:
            continue
        assigned = assign_crop_year(df, ctx.calendar).dropna()
        years.update(int(year) for year in assigned.astype(int).unique())
    return FeatureContext(
        commodity=ctx.commodity,
        crop_years=sorted(years),
        countries=ctx.countries,
        calendar=ctx.calendar,
        inputs=ctx.inputs,
        params=ctx.params,
    )


def compute_inseason_weather_dense(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Dense origin-level weather aggregates for annual PSD anomaly models.

    This family intentionally reuses the existing region/stage weather
    computations and aggregates their point-in-time-safe outputs. It keeps the
    same incomplete-window protections while replacing hundreds of sparse
    region columns with a smaller set of interpretable country/stage stress
    summaries.
    """
    if ctx.calendar is None:
        return empty_result()

    base_ctx = _dense_base_context(ctx)
    dense_params = ctx.params.get("weather_dense", {})
    stress_z_threshold = float(dense_params.get("stress_z_threshold", 1.0))
    gdd_stage = "gdd_window" if ctx.calendar.gdd_window else "crop_year"
    frost_stage = "frost_risk" if "frost_risk" in ctx.calendar.stages else "crop_year"

    families = [
        {
            "compute": compute_stage_precip_z,
            "source_key": "weather:chirps",
            "variable": "precipitation_mm",
            "base_prefix": "chirps_precip_z",
            "dense_metric": "precip_z",
            "stage_aware": True,
            "default_stage": "",
            "stats": ("mean", "min"),
            "share_name": "dry_share",
            "share_direction": "low",
            "share_threshold": stress_z_threshold,
        },
        {
            "compute": compute_drought_z,
            "source_key": "weather:chirps",
            "variable": "precipitation_mm",
            "base_prefix": "drought_z",
            "dense_metric": "drought_z",
            "stage_aware": True,
            "default_stage": "",
            "stats": ("mean", "max"),
            "share_name": "stress_share",
            "share_direction": "high",
            "share_threshold": stress_z_threshold,
        },
        {
            "compute": compute_stage_tmax_anomaly,
            "source_key": "weather:nasa_power",
            "variable": "temperature_2m_max_c",
            "base_prefix": "nasa_tmax_anomaly",
            "dense_metric": "tmax_anomaly",
            "stage_aware": True,
            "default_stage": "",
            "stats": ("mean", "max"),
            "share_name": "hot_share",
            "share_direction": "high",
            "share_threshold": stress_z_threshold,
        },
        {
            "compute": compute_stage_tmin_anomaly,
            "source_key": "weather:nasa_power",
            "variable": "temperature_2m_min_c",
            "base_prefix": "nasa_tmin_anomaly",
            "dense_metric": "tmin_anomaly",
            "stage_aware": True,
            "default_stage": "",
            "stats": ("mean", "min"),
            "share_name": "cold_share",
            "share_direction": "low",
            "share_threshold": stress_z_threshold,
        },
        {
            "compute": compute_cpc_soil_z,
            "source_key": "weather:cpc_soil",
            "variable": "soil_moisture_mm",
            "base_prefix": "cpc_soil_z",
            "dense_metric": "soil_z",
            "stage_aware": True,
            "default_stage": "",
            "stats": ("mean", "min"),
            "share_name": "dry_share",
            "share_direction": "low",
            "share_threshold": stress_z_threshold,
        },
        {
            "compute": compute_modis_ndvi_z,
            "source_key": "weather:modis_ndvi",
            "variable": "ndvi_z_score",
            "base_prefix": "modis_ndvi_z",
            "dense_metric": "ndvi_z",
            "stage_aware": True,
            "default_stage": "",
            "stats": ("mean", "min"),
            "share_name": "low_vigor_share",
            "share_direction": "low",
            "share_threshold": stress_z_threshold,
        },
        {
            "compute": compute_gdd_z,
            "source_key": "weather:nasa_power",
            "variable": "temperature_2m_max_c",
            "base_prefix": "gdd_z",
            "dense_metric": "gdd_z",
            "stage_aware": False,
            "default_stage": gdd_stage,
            "stats": ("mean", "min", "max"),
        },
        {
            "compute": compute_heat_stress_z,
            "source_key": "weather:nasa_power",
            "variable": "temperature_2m_max_c",
            "base_prefix": "heat_stress_z",
            "dense_metric": "heat_stress_z",
            "stage_aware": False,
            "default_stage": gdd_stage,
            "stats": ("mean", "max"),
            "share_name": "stress_share",
            "share_direction": "high",
            "share_threshold": stress_z_threshold,
        },
        {
            "compute": compute_frost_event_flag,
            "source_key": "weather:nasa_power",
            "variable": "temperature_2m_min_c",
            "base_prefix": "frost_event_flag",
            "dense_metric": "frost_event_flag",
            "stage_aware": False,
            "default_stage": frost_stage,
            "stats": ("max",),
            "share_name": "event_share",
            "share_direction": "high",
            "share_threshold": 0.5,
        },
    ]

    rows: list[tuple[str, int, str, float]] = []
    for family in families:
        base_df = family["compute"](base_ctx, spec)
        expected_regions = _expected_regions_from_source(
            ctx,
            source_key=str(family["source_key"]),
            variable=str(family["variable"]),
            stage_aware=bool(family["stage_aware"]),
            default_stage=str(family["default_stage"]),
        )
        rows.extend(
            _dense_metric_rows(
                base_df,
                ctx=ctx,
                base_prefix=str(family["base_prefix"]),
                dense_metric=str(family["dense_metric"]),
                stage_aware=bool(family["stage_aware"]),
                default_stage=str(family["default_stage"]),
                stats=tuple(family["stats"]),
                expected_regions=expected_regions,
                share_name=family.get("share_name"),
                share_direction=str(family.get("share_direction", "high")),
                share_threshold=float(family.get("share_threshold", stress_z_threshold)),
            )
        )
    return make_result(rows)
