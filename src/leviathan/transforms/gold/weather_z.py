"""gold_weather_z compute core — monthly, PIT-safe standardized weather-stress anomalies.

Pure ``(long weather frames) -> tall gold frame``: no S3, no AWS, no side effects, fully unit-testable on
synthetic frames (the jobs/batch/gold_weather_z_task.py wrapper does the S3 I/O). This is the
transform-upstream half of Phase D-W4: it decouples the weather z-math from BOTH the deferred MLOps feature
layer (crop-year grain, gold.feature_spine — barred from the cascade by silverleg.py:16-20) AND the
projected silver_nasa_power table (the LIST-storm partition class). The output is a small, tall,
non-projected gold table the numbers registry serves directly.

OUTPUT SHAPE (tall) — one row per ``commodity x country x region x year x month x metric``:
    commodity : Leviathan contract slug (e.g. corn_cbot)
    country   : PSD Title-Case SURFACE FORM ('United States', 'Brazil') -- built here in the silver_psd
                convention (silverleg.py:93-94: snake_case -> ``.replace('_',' ').title()``) so a
                country_rule=region weather leg resolves against it instead of going DARK like the
                France->EU / Cote d'Ivoire PSD legs.
    region    : the silver weather region token (carried through as-is; v1 is not a query filter).
    year, month : the year_month anchor -> the registry entry sets knowledge_semantics=year_month so the
                as-of guard is ``(year*100+month) <= asof_ym`` (query.py year_month machinery, reused
                wholesale from the ONI path; NO partition projection, NO LIST-storm surface).
    metric    : one of {drought_z, heat_stress_z, gdd_z, tmax_anomaly, frost_event_flag}.
    value     : the z-score (dimensionless) or, for frost_event_flag, a 0/1 flag.

MONTHLY BASELINE WINDOWING (the R3 UNKNOWN, settled here) — **rolling prior-year SAME-MONTH baseline**:
each metric is first reduced to ONE scalar per (commodity, country, region, year, month), then z-scored
across YEARS within the same calendar month via ``trailing_baseline_z`` (base.py:62):

    z[Y, m] = (x[Y, m] - mean(x[Y-W .. Y-1, m])) / std(x[Y-W .. Y-1, m])

``trailing_baseline_z`` shifts by one BEFORE rolling, so the baseline for (year Y, month m) is drawn from
the SAME month m of the trailing ``window_years`` PRIOR years and NEVER sees year Y (or any later year) --
the point-in-time property the truncate-at-T test asserts. A same-month baseline (not trailing-months)
holds seasonality fixed so a July anomaly is measured against prior Julys, never against a cool April.

PER-FAMILY MATH — reuses the weather_stage.py doctrine (the crop-year/stage-grain functions
compute_stage_tmax_anomaly / compute_gdd_z / compute_heat_stress_z / compute_drought_z /
compute_frost_event_flag) as the reference; the exact thresholds/formulas are mirrored here at MONTH grain
because those functions are hard-bound to ctx.calendar stages and cannot emit year_month rows. The shared
base.py primitives (``trailing_baseline_z``, ``max_consecutive_true``) are IMPORTED directly -- a gold
transform job is upstream infrastructure, not serving/cascade code, so the silverleg.py:16-20
"never read the feature layer here" doctrine (which targets the cascade reading gold.feature_spine) does
not apply; importing two pure functions from base.py introduces no S3/AWS/feature-spine dependency.

    tmax_anomaly     : monthly MEAN of temperature_2m_max_c (nasa_power)         -> same-month z.
    gdd_z            : monthly SUM of daily GDD (nasa_power tmax+tmin;
                       GDD_day = clip((min(tmax,cap)+max(tmin,base))/2 - base, 0)) -> same-month z.
    heat_stress_z    : monthly COUNT of days tmax > heat_threshold (nasa_power)  -> same-month z.
    drought_z        : monthly LONGEST consecutive dry-day run (chirps precip;
                       "dry" = below the dry_percentile of the SAME (region, month)'s daily precip over the
                       trailing prior years -- a second PIT layer) -> same-month z of the run counts.
    frost_event_flag : 1.0 if the monthly MIN of temperature_2m_min_c < frost_threshold, else 0.0
                       (nasa_power). A flag, not a z -- emitted directly (0.0 is a real observation, kept).

ASSUMPTION (documented): the reduction treats each calendar month as COMPLETE. The transform runs on
historical/backfilled silver where months are whole; a partial trailing month would understate the
sum/count families. The as-of year_month guard withholds the current partial month at serve time for a
typical asof, and a follow-up may add a min-days-in-month completeness gate (weather_stage's stage-window
analogue) if live weekly weather is ever wired.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.features.computations.base import (
    dry_day_threshold,
    max_consecutive_true,
    trailing_baseline_z,
)

# ── output contract ────────────────────────────────────────────────────────────────────────────────
GOLD_COLUMNS = ["commodity", "country", "region", "year", "month", "metric", "value"]

METRIC_TMAX_ANOMALY = "tmax_anomaly"
METRIC_GDD_Z = "gdd_z"
METRIC_HEAT_STRESS_Z = "heat_stress_z"
METRIC_DROUGHT_Z = "drought_z"
METRIC_FROST_FLAG = "frost_event_flag"
Z_METRICS = (METRIC_TMAX_ANOMALY, METRIC_GDD_Z, METRIC_HEAT_STRESS_Z, METRIC_DROUGHT_Z)
ALL_METRICS = Z_METRICS + (METRIC_FROST_FLAG,)

# ── default thresholds — mirror the weather_stage.py defaults (baselines / gdd / heat_stress / drought) ─
BASELINE_WINDOW_YEARS = 30
BASELINE_MIN_YEARS = 10
GDD_BASE_C = 10.0
GDD_CAP_C = 30.0
HEAT_THRESHOLD_C = 35.0
DRY_PERCENTILE = 20.0
FROST_THRESHOLD_C = 0.0

_TMAX = "temperature_2m_max_c"
_TMIN = "temperature_2m_min_c"
_PRECIP = "precipitation_mm"
_KEYS = ["country", "region", "year", "month"]


def to_psd_surface(country: str) -> str:
    """snake_case silver weather country -> PSD Title-Case surface form (silverleg.py:93-94 convention).

    'united_states' -> 'United States', 'brazil' -> 'Brazil', 'european_union' -> 'European Union' — the
    exact strings the region_map resolve block and silver_psd store, so a country_rule=region weather leg
    matches instead of going DARK.
    """
    return str(country).replace("_", " ").title()


def _slice(long_df: pd.DataFrame | None, variable: str) -> pd.DataFrame | None:
    """One weather variable as a clean daily long frame (country, region, year, month, day, value)."""
    if long_df is None or long_df.empty or "variable" not in long_df.columns:
        return None
    df = long_df.loc[long_df["variable"] == variable,
                     ["country", "region", "year", "month", "day", "value"]].copy()
    if df.empty:
        return None
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    for c in ("year", "month", "day"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["value", "year", "month", "day"])
    if df.empty:
        return None
    df[["year", "month", "day"]] = df[["year", "month", "day"]].astype(int)
    return df


def _emit(rows: list[tuple], keep_zero: bool = True) -> pd.DataFrame:
    """Build the tall gold frame from (commodity, country, region, year, month, metric, value) tuples,
    dropping NaN values (absence == missing in long format). 0.0 is a real observation and is kept."""
    if not rows:
        return pd.DataFrame(columns=GOLD_COLUMNS)
    df = pd.DataFrame(rows, columns=GOLD_COLUMNS)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).reset_index(drop=True)
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    return df


def _same_month_z(monthly: pd.DataFrame, *, commodity: str, metric: str,
                  window_years: int, min_years: int) -> list[tuple]:
    """Z-score a per-(country, region, year, month) scalar across YEARS within each calendar month.

    ``monthly`` carries columns [country, region, year, month, scalar]. For each (country, region, month)
    the yearly ``scalar`` series is z-scored by ``trailing_baseline_z`` (prior years only), so the value
    for year Y is standardized against the same month of prior years and never sees Y itself.
    """
    rows: list[tuple] = []
    for (country, region, month), grp in monthly.groupby(["country", "region", "month"], sort=True):
        yearly = grp.set_index("year")["scalar"].astype(float).sort_index()
        z = trailing_baseline_z(yearly, window_years, min_years)
        surface = to_psd_surface(country)
        for year, zval in z.items():
            rows.append((commodity, surface, region, int(year), int(month), metric, zval))
    return rows


def _monthly_scalar(daily: pd.DataFrame, col: str, how: str) -> pd.DataFrame:
    """Reduce a daily frame to one scalar per (country, region, year, month). how in {mean, sum}."""
    agg = daily.groupby(_KEYS, as_index=False)[col].agg(how)
    return agg.rename(columns={col: "scalar"})


def _tmax_anomaly(nasa: pd.DataFrame, *, commodity, window_years, min_years) -> list[tuple]:
    tmax = _slice(nasa, _TMAX)
    if tmax is None:
        return []
    monthly = _monthly_scalar(tmax, "value", "mean")
    return _same_month_z(monthly, commodity=commodity, metric=METRIC_TMAX_ANOMALY,
                         window_years=window_years, min_years=min_years)


def _heat_stress_z(nasa: pd.DataFrame, *, commodity, window_years, min_years, threshold) -> list[tuple]:
    tmax = _slice(nasa, _TMAX)
    if tmax is None:
        return []
    tmax = tmax.copy()
    tmax["hot"] = (tmax["value"] > threshold).astype(float)
    monthly = _monthly_scalar(tmax, "hot", "sum")
    return _same_month_z(monthly, commodity=commodity, metric=METRIC_HEAT_STRESS_Z,
                         window_years=window_years, min_years=min_years)


def _gdd_z(nasa: pd.DataFrame, *, commodity, window_years, min_years, base, cap) -> list[tuple]:
    tmax = _slice(nasa, _TMAX)
    tmin = _slice(nasa, _TMIN)
    if tmax is None or tmin is None:
        return []
    merged = tmax.rename(columns={"value": "tmax"}).merge(
        tmin.rename(columns={"value": "tmin"}),
        on=["country", "region", "year", "month", "day"], how="inner")
    if merged.empty:
        return []
    # GDD_day = clip((min(tmax,cap) + max(tmin,base)) / 2 - base, lower=0)  -- weather_stage.compute_gdd_z
    merged["gdd"] = ((merged["tmax"].clip(upper=cap) + merged["tmin"].clip(lower=base)) / 2.0 - base) \
        .clip(lower=0.0)
    monthly = _monthly_scalar(merged, "gdd", "sum")
    return _same_month_z(monthly, commodity=commodity, metric=METRIC_GDD_Z,
                         window_years=window_years, min_years=min_years)


def _drought_runs(precip: pd.DataFrame, *, window_years, min_years, dry_percentile) -> pd.DataFrame:
    """Monthly longest consecutive dry-day run per (country, region, year, month), two-pass PIT-safe.

    Mirrors weather_stage.compute_drought_z at month grain: the dry-day threshold for (region, month, year
    Y) is the ``dry_percentile`` of the SAME (region, month)'s daily precip over the trailing prior years
    [Y-window, Y-1]; a year with fewer than ``min_years`` prior years yields no run (NaN) so it never
    fabricates a run count from an empty baseline.
    """
    rows: list[tuple] = []
    for (country, region, month), grp in precip.groupby(["country", "region", "month"], sort=True):
        by_year = {int(y): g.sort_values("day") for y, g in grp.groupby("year")}
        for year in sorted(by_year):
            prior = [y for y in by_year if year - window_years <= y < year]
            if len(prior) < min_years:
                continue
            baseline = np.concatenate([by_year[y]["value"].to_numpy() for y in prior])
            # floored at DRY_DAY_FLOOR_MM: a zero-inflated baseline's bottom percentile is 0.0
            # and no day is ever strictly below zero rain (BF-W1: 27/31 commodities degenerate)
            threshold = dry_day_threshold(baseline, dry_percentile)
            run = max_consecutive_true(by_year[year]["value"].to_numpy() < threshold)
            rows.append((country, region, year, month, float(run)))
    return pd.DataFrame(rows, columns=["country", "region", "year", "month", "scalar"])


def _drought_z(chirps: pd.DataFrame, *, commodity, window_years, min_years, dry_percentile) -> list[tuple]:
    precip = _slice(chirps, _PRECIP)
    if precip is None:
        return []
    runs = _drought_runs(precip, window_years=window_years, min_years=min_years,
                         dry_percentile=dry_percentile)
    if runs.empty:
        return []
    return _same_month_z(runs, commodity=commodity, metric=METRIC_DROUGHT_Z,
                         window_years=window_years, min_years=min_years)


def _frost_flag(nasa: pd.DataFrame, *, commodity, threshold) -> list[tuple]:
    tmin = _slice(nasa, _TMIN)
    if tmin is None:
        return []
    monthly_min = tmin.groupby(_KEYS, as_index=False)["value"].min()
    rows: list[tuple] = []
    for r in monthly_min.itertuples(index=False):
        flag = 1.0 if float(r.value) < threshold else 0.0
        rows.append((commodity, to_psd_surface(r.country), r.region, int(r.year), int(r.month),
                     METRIC_FROST_FLAG, flag))
    return rows


def compute_weather_z(
    commodity: str,
    *,
    nasa_power: pd.DataFrame | None = None,
    chirps: pd.DataFrame | None = None,
    window_years: int = BASELINE_WINDOW_YEARS,
    min_years: int = BASELINE_MIN_YEARS,
    gdd_base_c: float = GDD_BASE_C,
    gdd_cap_c: float = GDD_CAP_C,
    heat_threshold_c: float = HEAT_THRESHOLD_C,
    dry_percentile: float = DRY_PERCENTILE,
    frost_threshold_c: float = FROST_THRESHOLD_C,
) -> pd.DataFrame:
    """Compute the tall gold_weather_z frame for ONE commodity from its silver weather long frames.

    ``nasa_power`` supplies temperature_2m_max_c / temperature_2m_min_c (heat/gdd/tmax/frost families);
    ``chirps`` supplies precipitation_mm (drought family). Either may be None/empty -> that family is
    skipped. Returns a frame with columns ``GOLD_COLUMNS``; NaN z-scores (insufficient baseline) are
    dropped, frost 0.0 flags are kept.
    """
    rows: list[tuple] = []
    rows += _tmax_anomaly(nasa_power, commodity=commodity, window_years=window_years, min_years=min_years)
    rows += _heat_stress_z(nasa_power, commodity=commodity, window_years=window_years,
                          min_years=min_years, threshold=heat_threshold_c)
    rows += _gdd_z(nasa_power, commodity=commodity, window_years=window_years, min_years=min_years,
                  base=gdd_base_c, cap=gdd_cap_c)
    rows += _drought_z(chirps, commodity=commodity, window_years=window_years, min_years=min_years,
                      dry_percentile=dry_percentile)
    rows += _frost_flag(nasa_power, commodity=commodity, threshold=frost_threshold_c)
    return _emit(rows)
