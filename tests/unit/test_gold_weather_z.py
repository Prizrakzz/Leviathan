"""Unit tests for the gold_weather_z transform (Phase D-W4) — synthetic frames only, no S3/AWS.

Covers: z-math correctness (compute == trailing_baseline_z on the same-month yearly series), PIT safety
(year Y's baseline never includes Y or any later year), the PSD Title-Case surface-form lock, the tall-shape
schema, the per-family reductions (gdd cap, heat-count, drought two-pass), and the registry/build_sql
year_month wiring (sargable guard, no CAST-on-projection, leakage boundary).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leviathan.features.computations.base import trailing_baseline_z
from leviathan.transforms.gold.weather_z import (
    ALL_METRICS,
    GOLD_COLUMNS,
    METRIC_DROUGHT_Z,
    METRIC_FROST_FLAG,
    METRIC_GDD_Z,
    METRIC_HEAT_STRESS_Z,
    METRIC_TMAX_ANOMALY,
    _drought_runs,
    compute_weather_z,
    to_psd_surface,
)

_TMAX = "temperature_2m_max_c"
_TMIN = "temperature_2m_min_c"
_PRECIP = "precipitation_mm"
WIN, MIN = 30, 3          # small min_years so a handful of synthetic years suffices (mirrors the weather test)


def _daily(year: int, month: int, variable: str, values: list[float], *,
           country: str = "united_states", region: str = "belt") -> pd.DataFrame:
    """One (year, month) block: len(values) consecutive days of `variable`."""
    n = len(values)
    return pd.DataFrame({
        "year": year, "month": month, "day": list(range(1, n + 1)),
        "country": country, "region": region, "source": "syn",
        "variable": variable, "value": values,
    })


def _var_by_year(month: int, variable: str, per_year_value: dict[int, float], *, n_days: int = 28,
                 country: str = "united_states", region: str = "belt") -> pd.DataFrame:
    """Constant daily `variable` per year (monthly mean/each-day == that constant)."""
    return pd.concat(
        [_daily(y, month, variable, [v] * n_days, country=country, region=region)
         for y, v in per_year_value.items()],
        ignore_index=True,
    )


def _val(df: pd.DataFrame, metric: str, year: int, month: int = 7) -> float:
    sub = df[(df["metric"] == metric) & (df["year"] == year) & (df["month"] == month)]
    assert len(sub) == 1, f"expected exactly one {metric} row for {year}-{month}, got {len(sub)}"
    return float(sub["value"].iloc[0])


# ── z-math correctness ───────────────────────────────────────────────────────────────────────────────

def test_tmax_anomaly_equals_trailing_baseline_z() -> None:
    levels = {2000: 20.0, 2001: 22.0, 2002: 21.0, 2003: 25.0, 2004: 19.0, 2005: 30.0}
    nasa = _var_by_year(7, _TMAX, levels)
    got = compute_weather_z("corn_cbot", nasa_power=nasa, window_years=WIN, min_years=MIN)

    expected = trailing_baseline_z(pd.Series(levels).sort_index(), WIN, MIN)
    # 2000-2002 have < MIN prior years -> NaN -> dropped; 2003-2005 emit.
    for y in (2003, 2004, 2005):
        assert np.isclose(_val(got, METRIC_TMAX_ANOMALY, y), float(expected.loc[y]))
    assert got[(got["metric"] == METRIC_TMAX_ANOMALY) & (got["year"] < 2003)].empty


# ── PIT safety: year Y's baseline never includes Y or any later year ───────────────────────────────────

def test_pit_year_Y_baseline_excludes_Y_and_later() -> None:
    base = {2000: 20.0, 2001: 22.0, 2002: 21.0, 2003: 25.0}
    full = {**base, 2004: 19.0, 2005: 999.0}             # later years, one extreme
    z_trunc = compute_weather_z("corn_cbot", nasa_power=_var_by_year(7, _TMAX, base),
                                window_years=WIN, min_years=MIN)
    z_full = compute_weather_z("corn_cbot", nasa_power=_var_by_year(7, _TMAX, full),
                               window_years=WIN, min_years=MIN)
    # 2003's z is identical whether or not 2004/2005 (incl. a 999 outlier) exist downstream.
    assert np.isclose(_val(z_trunc, METRIC_TMAX_ANOMALY, 2003), _val(z_full, METRIC_TMAX_ANOMALY, 2003))


# ── PSD Title-Case surface-form lock ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("snake, surface", [
    ("united_states", "United States"), ("brazil", "Brazil"), ("european_union", "European Union"),
    ("south_africa", "South Africa"),
])
def test_to_psd_surface(snake: str, surface: str) -> None:
    assert to_psd_surface(snake) == surface


def test_output_country_is_title_case() -> None:
    levels = {2000: 20.0, 2001: 22.0, 2002: 21.0, 2003: 25.0}
    got = compute_weather_z("soybeans_cbot",
                            nasa_power=_var_by_year(7, _TMAX, levels, country="brazil"),
                            window_years=WIN, min_years=MIN)
    assert not got.empty
    assert set(got["country"].unique()) == {"Brazil"}       # never the raw snake_case 'brazil'


# ── tall-shape schema ──────────────────────────────────────────────────────────────────────────────────

def test_tall_shape_schema_and_metrics() -> None:
    levels = {y: 20.0 + (y % 5) for y in range(2000, 2010)}
    tmin = {y: -3.0 if y == 2005 else 6.0 for y in range(2000, 2010)}
    nasa = pd.concat([_var_by_year(7, _TMAX, levels), _var_by_year(7, _TMIN, tmin)], ignore_index=True)
    got = compute_weather_z("corn_cbot", nasa_power=nasa, window_years=WIN, min_years=MIN)

    assert list(got.columns) == GOLD_COLUMNS
    assert set(got["metric"].unique()) <= set(ALL_METRICS)
    # tall identity is unique per (commodity, country, region, year, month, metric)
    key = ["commodity", "country", "region", "year", "month", "metric"]
    assert not got.duplicated(subset=key).any()
    assert (got["commodity"] == "corn_cbot").all()


# ── frost_event_flag: a flag (0/1), 0.0 kept, not a z ─────────────────────────────────────────────────

def test_frost_event_flag_keeps_zero_and_flags_subzero() -> None:
    # 2001 has one sub-zero day in July -> monthly min < 0 -> flag 1.0; 2002 all positive -> 0.0.
    frames = [
        _daily(2001, 7, _TMIN, [5.0, 5.0, -3.0, 5.0, 5.0]),
        _daily(2002, 7, _TMIN, [5.0, 6.0, 7.0, 5.0, 5.0]),
    ]
    got = compute_weather_z("corn_cbot", nasa_power=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN)
    assert _val(got, METRIC_FROST_FLAG, 2001) == 1.0
    assert _val(got, METRIC_FROST_FLAG, 2002) == 0.0       # 0.0 is a real observation, NOT dropped


# ── gdd_z: daily GDD formula with cap/base, monthly SUM, then same-month z ─────────────────────────────

def test_gdd_z_respects_cap_and_sums_monthly() -> None:
    # tmin fixed at 15 (>= base 10). daily GDD = (min(tmax,30) + 15)/2 - 10.
    tmax_by_year = {2000: 25.0, 2001: 27.0, 2002: 23.0, 2003: 29.0, 2004: 21.0, 2005: 31.0}
    n_days = 28
    nasa = pd.concat([
        _var_by_year(7, _TMAX, tmax_by_year, n_days=n_days),
        _var_by_year(7, _TMIN, {y: 15.0 for y in tmax_by_year}, n_days=n_days),
    ], ignore_index=True)
    got = compute_weather_z("corn_cbot", nasa_power=nasa, window_years=WIN, min_years=MIN)

    def daily_gdd(tmax: float) -> float:
        return (min(tmax, 30.0) + max(15.0, 10.0)) / 2.0 - 10.0
    monthly_sum = pd.Series({y: daily_gdd(t) * n_days for y, t in tmax_by_year.items()}).sort_index()
    expected = trailing_baseline_z(monthly_sum, WIN, MIN)
    # 2005 tmax=31 is CAPPED to 30 -> daily 12.5, sum 350 (not 364): the cap is honored.
    assert np.isclose(monthly_sum.loc[2005], 350.0)
    for y in (2003, 2004, 2005):
        assert np.isclose(_val(got, METRIC_GDD_Z, y), float(expected.loc[y]))


# ── heat_stress_z: monthly COUNT of days over the threshold, then same-month z ─────────────────────────

def test_heat_stress_counts_days_over_threshold() -> None:
    hot_days = {2000: 2, 2001: 4, 2002: 1, 2003: 8, 2004: 0, 2005: 10}   # days > 35 C
    frames = []
    for y, n_hot in hot_days.items():
        vals = [40.0] * n_hot + [20.0] * (28 - n_hot)                     # 40 > 35 (hot), 20 not
        frames.append(_daily(y, 7, _TMAX, vals))
    got = compute_weather_z("corn_cbot", nasa_power=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN)
    expected = trailing_baseline_z(pd.Series({y: float(n) for y, n in hot_days.items()}).sort_index(),
                                   WIN, MIN)
    for y in (2003, 2004, 2005):
        assert np.isclose(_val(got, METRIC_HEAT_STRESS_Z, y), float(expected.loc[y]))


# ── drought two-pass: prior-year same-month percentile threshold + longest dry run, PIT-safe ────────────

def test_drought_runs_prior_year_threshold_and_pit() -> None:
    # 2000-2002 constant precip 5.0 -> the p20 threshold for 2003 is 5.0.
    prior = [_daily(y, 7, _PRECIP, [5.0] * 10) for y in (2000, 2001, 2002)]
    # 2003: three days at 4.0 (< 5.0 -> dry) then wet -> longest dry run = 3.
    y2003 = _daily(2003, 7, _PRECIP, [4.0, 4.0, 4.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    # a later, extreme year must NOT change 2003's run (threshold uses ONLY prior years).
    y2004 = _daily(2004, 7, _PRECIP, [0.0] * 10)
    precip = pd.concat(prior + [y2003, y2004], ignore_index=True)

    runs = _drought_runs(precip, window_years=WIN, min_years=MIN, dry_percentile=20.0)
    got_2003 = runs[(runs["year"] == 2003) & (runs["month"] == 7)]
    assert len(got_2003) == 1 and float(got_2003["scalar"].iloc[0]) == 3.0
    # 2000-2002 have < MIN prior same-month years -> no run emitted (never a fabricated count).
    assert runs[runs["year"].isin([2000, 2001, 2002])].empty


def test_drought_z_emitted_end_to_end() -> None:
    # Enough same-month history for BOTH the run-count baseline and the run-count z-score.
    frames = []
    rng = np.random.default_rng(0)
    for y in range(2000, 2012):
        # vary daily precip so prior-year percentiles and run counts differ across years
        vals = list(rng.uniform(0.0, 10.0, size=20))
        frames.append(_daily(y, 7, _PRECIP, vals))
    got = compute_weather_z("corn_cbot", chirps=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN)
    assert METRIC_DROUGHT_Z in set(got["metric"].unique())
    assert (got["country"] == "United States").all()        # chirps country is title-cased too


# ── registry + build_sql: the year_month wiring is sargable & leakage-safe ──────────────────────────────

def test_registry_parses_gold_weather_z() -> None:
    from leviathan.graphrag.numbers.registry import load_registry
    ts = load_registry().get("gold_weather_z")
    assert ts.shape == "tall"
    assert ts.metric_col == "metric" and ts.value_col == "value"
    assert ts.knowledge_semantics == "year_month"
    assert ts.year_col == "year" and ts.month_col == "month"
    assert ts.commodity_col == "commodity" and ts.country_col == "country"
    assert set(ALL_METRICS) <= set(ts.metrics)
    assert ts.partition_cols == []                          # non-projected: no LIST-storm / clobber surface


def test_build_sql_year_month_guard_is_sargable() -> None:
    from leviathan.graphrag.numbers.query import NumberQuery, build_sql
    sql = build_sql(NumberQuery(
        table="gold_weather_z", metric="drought_z", asof="2012-06-15", commodity="corn_cbot",
        country="United States", period_start="2011-01-01", period_end="2012-05-31", agg="mean"))
    assert "(year * 100 + month) <= 201206" in sql        # the leakage guard
    assert "metric = 'drought_z'" in sql
    assert "commodity = 'corn_cbot'" in sql
    assert "country = 'United States'" in sql              # Title-Case surface-form scope
    assert "avg(value)" in sql
    assert "gold_weather_z" in sql
    assert "CAST(" not in sql                              # no projected-column CAST -> no enumeration


def test_apply_pit_filter_excludes_future_month() -> None:
    from leviathan.graphrag.numbers.query import NumberQuery, apply_pit_filter
    from leviathan.graphrag.numbers.registry import load_registry
    ts = load_registry().get("gold_weather_z")
    spec = NumberQuery(table="gold_weather_z", metric="drought_z", asof="2012-06-15",
                       commodity="corn_cbot", country="United States")
    rows = [
        {"commodity": "corn_cbot", "country": "United States", "region": "belt",
         "year": 2012, "month": 5, "metric": "drought_z", "value": 1.2},   # 201205 <= 201206 -> KEEP
        {"commodity": "corn_cbot", "country": "United States", "region": "belt",
         "year": 2012, "month": 8, "metric": "drought_z", "value": 9.9},   # 201208 > 201206 -> DROP
    ]
    kept = apply_pit_filter(rows, spec, ts)
    assert [r["month"] for r in kept] == [5]


# ── the wide->long task seam (locks the 2026-07-12 run-1 silent no-op) ──────────────────────────────────

def test_task_melt_real_wide_schema_produces_gold_rows() -> None:
    """The Batch task's _to_long melts the REAL silver wide schema (one row per day; the exact column
    names probed from silver/weather on 2026-07-12) into the core's long shape, and compute_weather_z
    then emits rows -- the integration seam whose absence made run 1 a 31/31-commodity silent no-op."""
    from jobs.batch.gold_weather_z_task import _to_long

    frames = []
    for year in range(2000, 2012):
        for month in (1, 7):
            n = 28
            frames.append(pd.DataFrame({
                "date": [f"{year}-{month:02d}-{d:02d}" for d in range(1, n + 1)],
                "year": year, "month": month, "day": list(range(1, n + 1)),
                "country": "argentina", "region": "ar_corn_buenos_aires",
                "source": "nasa_power", "ingest_date": "2026-05-13",
                "source_file_name": "syn.json",
                "temperature_2m_mean_c": 22.0,
                "temperature_2m_max_c": [30.0 + (d % 5) + year % 3 for d in range(1, n + 1)],
                "temperature_2m_min_c": [12.0 + (d % 4) for d in range(1, n + 1)],
                "precipitation_mm": [0.0 if d % 6 else 4.0 for d in range(1, n + 1)],
                "relative_humidity_2m_pct": 50.0, "wind_speed_2m_m_s": 2.0,
            }))
    wide = pd.concat(frames, ignore_index=True)

    long_df = _to_long(wide)
    assert long_df is not None and not long_df.empty
    assert set(long_df.columns) == {"country", "region", "year", "month", "day", "variable", "value"}
    assert set(long_df["variable"].unique()) == {_TMAX, _TMIN, _PRECIP}

    gold = compute_weather_z("corn_cbot", nasa_power=long_df, chirps=long_df,
                             window_years=WIN, min_years=MIN)
    assert not gold.empty, "real-schema melt must yield gold rows (the run-1 failure mode)"
    assert (gold["country"] == "Argentina").all()          # PSD Title-Case surface form
    assert set(gold["metric"]).issubset(set(ALL_METRICS))


def test_task_melt_rejects_unknown_schema() -> None:
    from jobs.batch.gold_weather_z_task import _to_long
    bad = pd.DataFrame({"foo": [1], "bar": [2]})
    assert _to_long(bad) is None
