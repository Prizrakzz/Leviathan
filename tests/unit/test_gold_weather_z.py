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
    Z_METRICS,
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
    got = compute_weather_z("corn_cbot", nasa_power=nasa, window_years=WIN, min_years=MIN, enforce_month_completeness=False)

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
                                window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    z_full = compute_weather_z("corn_cbot", nasa_power=_var_by_year(7, _TMAX, full),
                               window_years=WIN, min_years=MIN, enforce_month_completeness=False)
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
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    assert not got.empty
    assert set(got["country"].unique()) == {"Brazil"}       # never the raw snake_case 'brazil'


# ── tall-shape schema ──────────────────────────────────────────────────────────────────────────────────

def test_tall_shape_schema_and_metrics() -> None:
    levels = {y: 20.0 + (y % 5) for y in range(2000, 2010)}
    tmin = {y: -3.0 if y == 2005 else 6.0 for y in range(2000, 2010)}
    nasa = pd.concat([_var_by_year(7, _TMAX, levels), _var_by_year(7, _TMIN, tmin)], ignore_index=True)
    got = compute_weather_z("corn_cbot", nasa_power=nasa, window_years=WIN, min_years=MIN, enforce_month_completeness=False)

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
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
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
    got = compute_weather_z("corn_cbot", nasa_power=nasa, window_years=WIN, min_years=MIN, enforce_month_completeness=False)

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
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
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
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    assert METRIC_DROUGHT_Z in set(got["metric"].unique())
    assert (got["country"] == "United States").all()        # chirps country is title-cased too


def test_drought_threshold_floors_on_zero_inflated_baseline() -> None:
    # BF-W1 live find: the corn belt's chirps is ~78% zero-precip days, so the p20 of the
    # baseline is 0.0 and NO day is ever strictly below zero rain -- every run degenerated to 0
    # and the z died on zero variance (drought_z emitted for only 4/31 commodities). The
    # DRY_DAY_FLOOR_MM floor makes sub-1mm days count as dry exactly where the percentile
    # degenerates, without touching wet climatologies (threshold 5.0 test above is unchanged).
    prior = [_daily(y, 7, _PRECIP, [0.0] * 8 + [6.0, 8.0]) for y in (2000, 2001, 2002)]
    # 2003: four consecutive trace days (<1mm) then wet -> run must be 4, not 0.
    y2003 = _daily(2003, 7, _PRECIP, [0.0, 0.2, 0.0, 0.4, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
    precip = pd.concat(prior + [y2003], ignore_index=True)

    runs = _drought_runs(precip, window_years=WIN, min_years=MIN, dry_percentile=20.0)
    got = runs[(runs["year"] == 2003) & (runs["month"] == 7)]
    assert len(got) == 1 and float(got["scalar"].iloc[0]) == 4.0


def test_drought_z_emitted_for_zero_inflated_climate_end_to_end() -> None:
    frames = []
    rng = np.random.default_rng(7)
    for y in range(2000, 2012):
        # zero-inflated: ~70% dry zeros, occasional real rain -- the temperate profile
        vals = [0.0 if rng.random() < 0.7 else float(rng.uniform(2.0, 12.0)) for _ in range(20)]
        frames.append(_daily(y, 7, _PRECIP, vals))
    got = compute_weather_z("corn_cbot", chirps=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    assert METRIC_DROUGHT_Z in set(got["metric"].unique())


# ── month completeness gate + z winsorize (RCA 2026-07-24: the served gdd_z=-13.16) ────────────────────
# The as-of year_month guard is <=, so a mid-month asof SEES the in-progress month; on 2026-07-24 every
# region's partial July cratered (gdd_z median -9.96, min -80) because a ~23-day GDD sum was z-scored
# against full-month baselines. The gate (production default) drops months not covering every calendar
# day; z metrics are winsorized at +/-Z_CAP because beyond |z|~6 the magnitude is baseline-thinness
# noise, not signal (~1,070 historical rows breached 6 this way, mostly heat_stress_z).

def _full_july(year: int, variable: str, daily_value: float) -> pd.DataFrame:
    return _daily(year, 7, variable, [daily_value] * 31)


def test_partial_current_month_dropped_all_families() -> None:
    frames = []
    for y in range(2000, 2005):
        frames.append(_full_july(y, _TMAX, 25.0 + (y % 3)))
        frames.append(_full_july(y, _TMIN, 15.0))
    # the live geometry: the trailing month observed only 20 of July's 31 days
    frames.append(_daily(2005, 7, _TMAX, [25.0] * 20))
    frames.append(_daily(2005, 7, _TMIN, [15.0] * 20))
    got = compute_weather_z("corn_cbot", nasa_power=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN)
    assert not got[got["year"] == 2004].empty     # complete months emit through the gate
    # the partial month emits NOTHING — no z, and no false frost 0.0 over days never observed
    assert got[got["year"] == 2005].empty


def test_drought_family_gated_on_partial_months() -> None:
    # same 20-day shape test_drought_z_emitted_end_to_end passes with the gate OFF -> empty with it ON
    rng = np.random.default_rng(0)
    frames = [_daily(y, 7, _PRECIP, list(rng.uniform(0.0, 10.0, size=20))) for y in range(2000, 2012)]
    got = compute_weather_z("corn_cbot", chirps=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN)
    assert got.empty


def test_z_winsorized_at_cap_positive() -> None:
    # degenerate-variance baseline: prior hot-day counts {0,0,1,0} -> std ~0.5; ten hot days would
    # raw-z to ~+19 -> capped to exactly +Z_CAP
    hot = {2000: 0, 2001: 0, 2002: 1, 2003: 0, 2004: 10}
    frames = []
    for y, n_hot in hot.items():
        frames.append(_daily(y, 7, _TMAX, [40.0] * n_hot + [20.0] * (31 - n_hot)))
    got = compute_weather_z("corn_cbot", nasa_power=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN)
    from leviathan.transforms.gold.weather_z import Z_CAP
    assert _val(got, METRIC_HEAT_STRESS_Z, 2004) == Z_CAP


def test_z_winsorized_at_cap_negative() -> None:
    # tight prior GDD sums (std ~1.8) + a collapsed year: raw z ~ -113 -> capped to exactly -Z_CAP
    tmax = {2000: 25.0, 2001: 25.2, 2002: 25.0, 2003: 25.2, 2004: 12.0}
    frames = [_full_july(y, _TMAX, v) for y, v in tmax.items()]
    frames += [_full_july(y, _TMIN, 15.0) for y in tmax]
    got = compute_weather_z("corn_cbot", nasa_power=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN)
    from leviathan.transforms.gold.weather_z import Z_CAP
    assert _val(got, METRIC_GDD_Z, 2004) == -Z_CAP


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
                             window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    assert not gold.empty, "real-schema melt must yield gold rows (the run-1 failure mode)"
    assert (gold["country"] == "Argentina").all()          # PSD Title-Case surface form
    assert set(gold["metric"]).issubset(set(ALL_METRICS))


def test_task_melt_rejects_unknown_schema() -> None:
    from jobs.batch.gold_weather_z_task import _to_long
    bad = pd.DataFrame({"foo": [1], "bar": [2]})
    assert _to_long(bad) is None


def test_task_passthrough_long_chirps_schema() -> None:
    """CHIRPS silver is ALREADY LONG (variable='precipitation_mm' + value, probed 2026-07-12) -- _to_long
    must pass it through, not demand wide columns (run 2's drought blackout: 34 DARK legs, 0 drought rows)."""
    from jobs.batch.gold_weather_z_task import _to_long

    frames = []
    for year in range(2000, 2012):
        n = 28
        frames.append(pd.DataFrame({
            "date": [f"{year}-01-{d:02d}" for d in range(1, n + 1)],
            "year": year, "month": 1, "day": list(range(1, n + 1)),
            "country": "argentina", "region": "ar_corn_buenos_aires",
            "commodity": "corn_cbot", "source": "chirps", "ingest_date": "2026-05-13",
            "variable": "precipitation_mm",
            # a WET month with one leading dry spell whose LENGTH varies by year: continuous values so
            # the pct-20 threshold sits above the dry days, and year-varying runs so the z has variance
            "value": [0.1 if d <= (3 + year % 5) else 5.0 for d in range(1, n + 1)],
        }))
    chirps_long = pd.concat(frames, ignore_index=True)

    out = _to_long(chirps_long)
    assert out is not None and not out.empty
    assert set(out.columns) == {"country", "region", "year", "month", "day", "variable", "value"}
    assert set(out["variable"].unique()) == {_PRECIP}

    gold = compute_weather_z("corn_cbot", nasa_power=None, chirps=out,
                             window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    assert not gold.empty and (gold["metric"] == METRIC_DROUGHT_Z).all()


# ── basin aggregate rows (GN-2 W1.1): the compound-region-token DECLINES fix ───────────────────────────
# region_map tokens like 'West Africa' can never scope-resolve against a single country row, so the
# cocoa weather legs SKIP_NODE'd without ever reading the data. The transform now emits basin rows
# (mean + tail share) under one resolvable surface; these fences pin the math and the guards.

def _basin_nasa(cell_2003: dict[tuple[str, str], float]) -> pd.DataFrame:
    """Four-cell basin frame: identical 2000-2002 baseline (20/22/21), per-cell 2003 divergence."""
    frames = []
    for (country, region), v2003 in cell_2003.items():
        levels = {2000: 20.0, 2001: 22.0, 2002: 21.0, 2003: v2003}
        frames.append(_var_by_year(7, _TMAX, levels, country=country, region=region))
    return pd.concat(frames, ignore_index=True)


def test_basin_rows_mean_and_tail_share() -> None:
    cells = {("cameroon", "c1"): 24.0, ("cameroon", "c2"): 21.5,
             ("ghana", "g1"): 22.0, ("ghana", "g2"): 20.0}
    got = compute_weather_z("cocoa", nasa_power=_basin_nasa(cells),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)

    basin = got[got["country"] == "West Africa"]
    assert not basin.empty
    assert set(basin["region"].unique()) == {"west_africa_basin"}

    # expected: mean of the four per-cell z's, tail share = fraction at z >= +2.0
    cell_z = [float(trailing_baseline_z(
        pd.Series({2000: 20.0, 2001: 22.0, 2002: 21.0, 2003: v}).sort_index(), WIN, MIN).loc[2003])
        for v in cells.values()]
    mean_row = basin[(basin["metric"] == METRIC_TMAX_ANOMALY) & (basin["year"] == 2003)]
    tail_row = basin[(basin["metric"] == METRIC_TMAX_ANOMALY + "_tail_share") & (basin["year"] == 2003)]
    assert len(mean_row) == 1 and len(tail_row) == 1
    assert np.isclose(float(mean_row["value"].iloc[0]), float(np.mean(cell_z)))
    assert np.isclose(float(tail_row["value"].iloc[0]),
                      float(np.mean([z >= 2.0 for z in cell_z])))
    # per-cell member rows are UNTOUCHED: all four cells still emit under their own countries
    assert set(got["country"].unique()) == {"Cameroon", "Ghana", "West Africa"}


def test_basin_requires_two_member_countries() -> None:
    cells = {("ghana", "g1"): 24.0, ("ghana", "g2"): 21.5}    # one country, two cells
    got = compute_weather_z("cocoa", nasa_power=_basin_nasa(cells),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    assert "West Africa" not in set(got["country"].unique())  # one country alone is not a basin read


def test_basin_min_cells_guard() -> None:
    # cameroon/c1 alone has a 2004 observation -> the 2004 group has 1 cell -> no basin row for 2004
    cells = {("cameroon", "c1"): 24.0, ("ghana", "g1"): 22.0}
    nasa = pd.concat([
        _basin_nasa(cells),
        _var_by_year(7, _TMAX, {2004: 23.0}, country="cameroon", region="c1"),
    ], ignore_index=True)
    got = compute_weather_z("cocoa", nasa_power=nasa,
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    basin = got[got["country"] == "West Africa"]
    assert not basin[basin["year"] == 2003].empty
    assert basin[basin["year"] == 2004].empty


def test_basin_frost_renamed_to_share_and_no_tail() -> None:
    frames = [
        _daily(2001, 7, _TMIN, [5.0, 5.0, -3.0, 5.0], country="cameroon", region="c1"),   # frost
        _daily(2001, 7, _TMIN, [6.0, 6.0, 6.0, 6.0], country="ghana", region="g1"),       # none
    ]
    got = compute_weather_z("cocoa", nasa_power=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    basin = got[got["country"] == "West Africa"]
    # renamed (a flag never wears a share); the W-3 provenance row rides beside it, and NO tail share
    assert set(basin["metric"].unique()) == {"frost_event_share", "frost_event_flag_cells"}
    share = basin[basin["metric"] == "frost_event_share"]
    assert np.isclose(float(share["value"].iloc[0]), 0.5)           # 1 of 2 cells flagged


def test_basin_disabled_with_empty_registry() -> None:
    cells = {("cameroon", "c1"): 24.0, ("ghana", "g1"): 22.0}
    got = compute_weather_z("cocoa", nasa_power=_basin_nasa(cells),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False,
                            basins={})
    assert "West Africa" not in set(got["country"].unique())


# ── W-2: three measured basins, one entry per belt, zero new fetches ───────────────────────────────────
# The member lists were MEASURED off configs/geographies (the tokens the silver frames carry); this
# fence pins the registry shape and the surface tokens, which are load-bearing (a surface that collides
# with a live per-cell country value would merge a belt aggregate into a real country's row pool).

def test_basin_registry_declares_the_four_belts_with_snake_case_members() -> None:
    from leviathan.transforms.gold.weather_z import BASINS
    assert set(BASINS) == {"west_africa", "eu_belt", "sea_palm_belt", "northern_plains_prairies"}
    assert BASINS["eu_belt"]["members"] == [
        "france", "germany", "poland", "romania", "hungary", "italy", "ukraine"]
    assert BASINS["sea_palm_belt"]["members"] == ["indonesia", "malaysia"]
    assert BASINS["northern_plains_prairies"]["members"] == ["united_states", "canada"]
    for spec in BASINS.values():
        for m in spec["members"]:
            assert m == m.lower() and " " not in m, m       # SILVER snake_case, never a surface form


def test_basin_surfaces_never_collide_with_a_live_country_value() -> None:
    """'European Union' is a LIVE per-cell country value (rapeseed_oil_zce carries country
    european_union) -- the eu_belt surface must never be that string, or a belt aggregate would land
    in a real country's row pool. Same rule for every member's own surface."""
    from leviathan.transforms.gold.weather_z import BASINS
    surfaces = {spec["surface"] for spec in BASINS.values()}
    assert "European Union" not in surfaces
    assert surfaces == {"West Africa", "EU Belt", "SE Asia Palm Belt", "Northern Plains"}
    member_surfaces = {to_psd_surface(m) for spec in BASINS.values() for m in spec["members"]}
    assert surfaces.isdisjoint(member_surfaces)


def test_member_tokens_match_the_geography_configs() -> None:
    """Every declared member must be a country token some tracked geography config actually carries --
    a typo'd member is a basin that silently never fires (the class W-2 was written to avoid)."""
    yaml = pytest.importorskip("yaml")
    import glob
    import os
    from leviathan.transforms.gold.weather_z import BASINS
    root = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "geographies")
    paths = sorted(glob.glob(os.path.join(root, "*_regions.yaml")))
    if not paths:
        pytest.skip("configs/geographies absent from this tree")
    live: set[str] = set()
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            for r in (yaml.safe_load(fh) or {}).get("regions", []):
                live.add(r["country"])
    for basin, spec in BASINS.items():
        for m in spec["members"]:
            assert m in live, f"{basin} member {m!r} is in no geography config"


def test_single_country_intersection_is_silently_skipped() -> None:
    """The STRUCK single-country belts (us_midwest_soy_belt, safrinha_belt) would look exactly like
    this: a frame carrying ONE member of a declared basin. The nunique() < BASIN_MIN_COUNTRIES guard
    skips it whole -- no basin row AND no country tier (the tier decomposes a basin read, it is never
    a standalone per-country product)."""
    from leviathan.transforms.gold.weather_z import BASINS
    cells = {("united_states", "ia"): 24.0, ("united_states", "il"): 21.5}   # us only: canada absent
    got = compute_weather_z("soybeans_cbot", nasa_power=_basin_nasa(cells),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    assert BASINS["northern_plains_prairies"]["surface"] not in set(got["country"].unique())
    assert set(got["region"].unique()) == {"ia", "il"}          # no *_basin, no *_country row
    assert set(got["metric"].unique()) <= set(ALL_METRICS)      # only cell-grain metrics survive


# ── W-4: the per-country tail tier ────────────────────────────────────────────────────────────────────
# <metric>_tail_share used to exist at BASIN grain only, so more basins bought more BASIN rows and never
# a per-country one. The tier emits the member's own tail share (and frost share) under the member's own
# surface at region '<member>_country' -- and NEVER the mean, which would collide with the per-cell rows
# already sitting under that country surface (region is not a v1 query filter).

def test_country_tier_emits_shares_never_the_mean() -> None:
    cells = {("cameroon", "c1"): 24.0, ("cameroon", "c2"): 21.5,
             ("ghana", "g1"): 22.0, ("ghana", "g2"): 20.0}
    got = compute_weather_z("cocoa", nasa_power=_basin_nasa(cells),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    tier = got[got["region"].str.endswith("_country")]
    assert set(tier["region"].unique()) == {"cameroon_country", "ghana_country"}
    assert set(tier["country"].unique()) == {"Cameroon", "Ghana"}      # the member's OWN PSD surface
    # exactly the share + provenance vocabulary; the bare metric name NEVER appears at this grain
    assert set(tier["metric"].unique()) == {"tmax_anomaly_tail_share", "tmax_anomaly_cells"}
    assert METRIC_TMAX_ANOMALY not in set(tier["metric"].unique())

    # the value is THAT COUNTRY's share, computed from that country's cells only
    def cell_z(v: float) -> float:
        return float(trailing_baseline_z(
            pd.Series({2000: 20.0, 2001: 22.0, 2002: 21.0, 2003: v}).sort_index(),
            WIN, MIN).loc[2003])
    for country, region, vals in (("Cameroon", "cameroon_country", (24.0, 21.5)),
                                  ("Ghana", "ghana_country", (22.0, 20.0))):
        row = tier[(tier["country"] == country) & (tier["region"] == region)
                   & (tier["metric"] == "tmax_anomaly_tail_share") & (tier["year"] == 2003)]
        assert len(row) == 1
        assert np.isclose(float(row["value"].iloc[0]),
                          float(np.mean([cell_z(v) >= 2.0 for v in vals])))

    # the tall key stays unique even though country-tier rows share a country surface with cell rows
    key = ["commodity", "country", "region", "year", "month", "metric"]
    assert not got.duplicated(subset=key).any()


def test_country_tier_frost_share_and_no_flag_no_tail() -> None:
    frames = [
        _daily(2001, 7, _TMIN, [5.0, 5.0, -3.0, 5.0], country="cameroon", region="c1"),   # frost
        _daily(2001, 7, _TMIN, [-2.0, 6.0, 6.0, 6.0], country="cameroon", region="c2"),   # frost
        _daily(2001, 7, _TMIN, [6.0, 6.0, 6.0, 6.0], country="ghana", region="g1"),       # none
    ]
    got = compute_weather_z("cocoa", nasa_power=pd.concat(frames, ignore_index=True),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    tier = got[got["region"].str.endswith("_country")]
    assert set(tier["metric"].unique()) == {"frost_event_share", "frost_event_flag_cells"}
    cmr = tier[(tier["country"] == "Cameroon") & (tier["metric"] == "frost_event_share")]
    gha = tier[(tier["country"] == "Ghana") & (tier["metric"] == "frost_event_share")]
    assert np.isclose(float(cmr["value"].iloc[0]), 1.0)      # 2 of 2 Cameroon cells flagged
    assert np.isclose(float(gha["value"].iloc[0]), 0.0)      # 0 of 1 -- a real reading, kept
    # the 0/1 FLAG itself never appears at country-tier grain (only on the per-cell rows)
    assert METRIC_FROST_FLAG not in set(tier["metric"].unique())
    assert (got[got["metric"] == METRIC_FROST_FLAG]["region"].isin(["c1", "c2", "g1"])).all()


def test_country_tier_rides_the_basin_min_cells_gate() -> None:
    """A country-tier row ALWAYS has a parent basin row at the same (commodity, metric, year, month):
    a month too thin for a belt read must not reappear decomposed."""
    cells = {("cameroon", "c1"): 24.0, ("ghana", "g1"): 22.0}
    nasa = pd.concat([
        _basin_nasa(cells),
        _var_by_year(7, _TMAX, {2004: 23.0}, country="cameroon", region="c1"),   # 2004: 1 cell only
    ], ignore_index=True)
    got = compute_weather_z("cocoa", nasa_power=nasa,
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    tier = got[got["region"].str.endswith("_country")]
    assert not tier[tier["year"] == 2003].empty
    assert tier[tier["year"] == 2004].empty                  # gated with its parent basin row


# ── W-3: <metric>_cells, the fidelity guard that ships WITH the basins ─────────────────────────────────

def test_cells_metric_at_both_grains_with_correct_counts() -> None:
    cells = {("cameroon", "c1"): 24.0, ("cameroon", "c2"): 21.5,
             ("ghana", "g1"): 22.0, ("ghana", "g2"): 20.0, ("nigeria", "n1"): 23.0}
    got = compute_weather_z("cocoa", nasa_power=_basin_nasa(cells),
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)
    at = lambda region, metric: got[(got["region"] == region) & (got["metric"] == metric)
                                    & (got["year"] == 2003)]["value"]
    basin_cells = at("west_africa_basin", "tmax_anomaly_cells")
    assert len(basin_cells) == 1 and float(basin_cells.iloc[0]) == 5.0     # all five member cells
    for region, n in (("cameroon_country", 2.0), ("ghana_country", 2.0), ("nigeria_country", 1.0)):
        col = at(region, "tmax_anomaly_cells")
        assert len(col) == 1 and float(col.iloc[0]) == n, region
    # counts are integers CARRIED AS FLOATS (the tall value column is numeric, one dtype for all rows)
    assert got["value"].dtype.kind == "f"
    # exactly one cells row per (grain, metric, year, month) -- provenance is never duplicated
    cellrows = got[got["metric"].str.endswith("_cells")]
    assert not cellrows.duplicated(subset=["commodity", "country", "region", "year",
                                           "month", "metric"]).any()


def test_lat50_shape_absent_country_row_and_a_short_basin_count() -> None:
    """THE MEASURED CASE (configs/sources/chirps.yaml: coverage.lat_max = 50). french_rapeseed_matif
    loses ALL 4 German and ALL 3 Polish cells from drought_z while every temperature metric keeps them,
    yet the >= 2-countries test passes on the WHOLE commodity frame -- so an 'EU (France/Germany/Poland)'
    drought leg is answered by a basin holding ZERO German cells. Here: germany has tmax cells and NO
    drought cells. The country tier for germany/drought_z must be ABSENT, and the basin's
    drought_z_cells must count only the cells that exist -- short against tmax_anomaly_cells, which is
    the disclosure."""
    tmax_cells = {("france", "fr1"): 24.0, ("france", "fr2"): 21.0,
                  ("germany", "de1"): 23.0, ("germany", "de2"): 22.0}
    nasa = _basin_nasa(tmax_cells)
    # CHIRPS: france only -- germany is above latitude 50 and simply has no precipitation cells
    rng = np.random.default_rng(3)
    precip = pd.concat(
        [_daily(y, 7, _PRECIP, list(rng.uniform(0.0, 10.0, size=20)), country="france", region=r)
         for r in ("fr1", "fr2") for y in range(2000, 2012)], ignore_index=True)
    got = compute_weather_z("french_rapeseed_matif", nasa_power=nasa, chirps=precip,
                            window_years=WIN, min_years=MIN, enforce_month_completeness=False)

    basin = got[got["region"] == "eu_belt_basin"]
    assert set(basin["country"].unique()) == {"EU Belt"}
    # the basin EXISTS (2 countries on the whole frame) yet its drought leg is France-only ...
    assert float(basin[(basin["metric"] == "tmax_anomaly_cells") & (basin["year"] == 2003)]
                 ["value"].iloc[0]) == 4.0
    drought_counts = basin[basin["metric"] == "drought_z_cells"]["value"].unique()
    assert len(drought_counts) == 1 and float(drought_counts[0]) == 2.0   # 2 of 4: SHORT, and it SAYS so

    # ... and germany has NO drought country-tier row at all, while it does have a tmax one
    tier = got[got["region"].str.endswith("_country")]
    de = set(tier[tier["country"] == "Germany"]["metric"].unique())
    assert "tmax_anomaly_tail_share" in de and "tmax_anomaly_cells" in de
    assert not any(m.startswith("drought_z") for m in de)     # honest absence, never a fabricated share
    fr = set(tier[tier["country"] == "France"]["metric"].unique())
    assert {"drought_z_tail_share", "drought_z_cells"} <= fr


# ── one basin entry, many commodities: the frame intersection does the work ────────────────────────────

def test_one_eu_belt_entry_serves_multiple_commodities_by_frame_intersection() -> None:
    """W-2's whole economy: ONE eu_belt entry covers all three MATIF contracts because _basin_rows
    intersects the member list against each commodity's OWN frame. Pinned on a two-commodity gold
    frame (compute_weather_z is per-commodity, the post-pass is not)."""
    from leviathan.transforms.gold.weather_z import BASINS, _basin_rows

    def cell(commodity, country, region, metric, value):
        return {"commodity": commodity, "country": to_psd_surface(country), "region": region,
                "year": 2003, "month": 7, "metric": metric, "value": value}

    gold = pd.DataFrame([
        # french_wheat_matif: france + germany (+ romania) -- three members
        cell("french_wheat_matif", "france", "fr1", METRIC_TMAX_ANOMALY, 2.5),
        cell("french_wheat_matif", "germany", "de1", METRIC_TMAX_ANOMALY, 0.5),
        cell("french_wheat_matif", "romania", "ro1", METRIC_TMAX_ANOMALY, 1.0),
        # french_maize_matif: france + hungary + italy -- a DIFFERENT member subset, same entry
        cell("french_maize_matif", "france", "fr9", METRIC_TMAX_ANOMALY, 3.0),
        cell("french_maize_matif", "hungary", "hu1", METRIC_TMAX_ANOMALY, 2.2),
        cell("french_maize_matif", "italy", "it1", METRIC_TMAX_ANOMALY, -0.4),
        # corn_cbot: ukraine ALONE of the members -> 1 country -> skipped, correctly
        cell("corn_cbot", "ukraine", "ua1", METRIC_TMAX_ANOMALY, 4.0),
        cell("corn_cbot", "united_states", "ia", METRIC_TMAX_ANOMALY, 4.0),
    ])
    out = _basin_rows(gold, BASINS)
    belts = out[out["region"] == "eu_belt_basin"]
    assert set(belts["commodity"].unique()) == {"french_wheat_matif", "french_maize_matif"}
    # each commodity's basin is built from ITS OWN members only
    for commodity, n, mean in (("french_wheat_matif", 3.0, (2.5 + 0.5 + 1.0) / 3),
                               ("french_maize_matif", 3.0, (3.0 + 2.2 - 0.4) / 3)):
        sub = belts[belts["commodity"] == commodity]
        assert float(sub[sub["metric"] == "tmax_anomaly_cells"]["value"].iloc[0]) == n
        assert np.isclose(float(sub[sub["metric"] == METRIC_TMAX_ANOMALY]["value"].iloc[0]), mean)
    assert out[out["commodity"] == "corn_cbot"].empty          # ukraine alone is not a belt
    # every qualifying member got its own country tier, keyed on the SILVER token
    assert set(out[out["commodity"] == "french_maize_matif"]["region"].unique()) == {
        "eu_belt_basin", "france_country", "hungary_country", "italy_country"}


def test_derived_metric_vocabulary_is_exactly_what_the_post_pass_emits() -> None:
    """DERIVED_METRICS is the card's contract: every name the post-pass can emit that a per-cell row
    never carries. ALL_METRICS stays the CELL-grain contract."""
    from leviathan.transforms.gold.weather_z import BASINS, DERIVED_METRICS, _basin_rows

    rows = []
    for country, region in (("cameroon", "c1"), ("ghana", "g1")):
        for metric in ALL_METRICS:
            rows.append({"commodity": "cocoa", "country": to_psd_surface(country), "region": region,
                         "year": 2003, "month": 7, "metric": metric, "value": 2.5})
    out = _basin_rows(pd.DataFrame(rows), BASINS)
    emitted = set(out["metric"].unique())
    assert emitted == set(DERIVED_METRICS) | set(Z_METRICS)    # z means ride at BASIN grain only
    assert set(DERIVED_METRICS).isdisjoint(set(ALL_METRICS))
    assert len(DERIVED_METRICS) == len(set(DERIVED_METRICS)) == 10
