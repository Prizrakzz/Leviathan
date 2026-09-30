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

MONTH COMPLETENESS (RCA 2026-07-24, the served gdd_z=-13.16): live daily weather IS wired (A1-A2
schedules), and the as-of year_month guard does NOT withhold the current month — the guard is
``(year*100+month) <= asof_ym``, so a mid-month asof sees the in-progress month. A partial month's
SUM/COUNT reductions (gdd, heat, drought runs) crater against full-month baselines: on 2026-07-24 every
region's July gdd_z was -2..-80 (median -9.96) from ~12-23 observed days. The fix is transform-side:
``_complete_months_only`` drops any (country, region, year, month) whose observed distinct days do not
cover the FULL calendar month, for EVERY family (a partial month's mean/min/flag is a short sample too).
Historic silver is gapless (probed 2012/2019: 0 incomplete region-months), so the gate binds only on the
live trailing month — the honest serve is the latest COMPLETE month.

Z WINSORIZE (same RCA, the historical tail): ~1,070 pre-2026 rows breached |z|>6 (mostly heat_stress_z)
from thin same-month baselines — prior-year counts like {0,0,1,0,...} give a tiny nonzero std and one hot
week explodes the z to +/-40..80. Beyond |z|~6 the magnitude asserts absurd probabilities and carries no
statistical meaning REGARDLESS of whether the month was genuinely extreme, so z metrics are clipped to
+/-``Z_CAP`` (=6.0). Exact-zero variance already yields NaN in ``trailing_baseline_z`` and is dropped.

BASIN AGGREGATE ROWS (GN-2 W1.1, 2026-08-22) — the cocoa DECLINES fix. Multi-country producing belts
("West Africa") appear in region_map as COMPOUND tokens that scope resolution cannot match against any
single country row, so the cascade SKIP_NODEs the leg and the engine NEVER READS the station values
(the mis-diagnosed "declines-honestly" class: scope-resolution failure, not below-threshold calm). The
fix is transform-side: after the per-cell rows are computed, ``_basin_rows`` emits one aggregate row set
per basin under a SINGLE resolvable country surface (e.g. 'West Africa'):

    <metric>            : the basin MEAN of member-cell values for each z metric (same metric name, so
                          an existing-shape leg reads it at the basin surface with zero map machinery).
    <metric>_tail_share : share of member cells at z >= +TAIL_SIGMA (=2.0) — W2.1's tail statistic
                          pulled forward as the enabler; share-of-cells is robust to one duplicated or
                          extreme grid cell dominating a mean, and distinguishes a one-cell artifact
                          from "a quarter of the belt is cooking".
    frost_event_share   : basin mean of the 0/1 frost flags — renamed (never ``frost_event_flag``) so a
                          fractional share is never misread as a flag.

Guards: a basin only emits for a commodity when >= ``BASIN_MIN_COUNTRIES`` member countries are present
in that commodity's frame (one country alone is not a basin read), and each (metric, year, month) group
needs >= ``BASIN_MIN_CELLS`` member cells (a 1-cell mean/share is just that cell). Members are declared
in SILVER snake_case and matched on the PSD surface the gold rows already carry. Basin rows ride the
same parquet/pg path as cell rows; region_map basin tokens then resolve the compound-token legs to the
basin surface, and the calm/tail narration renders from these real reads.

PER-COUNTRY TAIL TIER (W-4, 2026-08-25) — the basin decomposed by member. Until now ``_tail_share`` was
emitted at BASIN grain ONLY and ``n_cells`` was computed and thrown away, so adding basins bought more
BASIN rows and never a per-country one: "how much of Ghana is in the tail" had no row to read. The same
post-pass now also emits, per member country present in the commodity's frame, at
region ``<member>_country`` under that member's own PSD surface (region is not a query filter in v1):

    <metric>_tail_share : share of THAT COUNTRY's member cells at z >= +TAIL_SIGMA.
    frost_event_share   : mean of THAT COUNTRY's 0/1 frost flags (again never ``frost_event_flag``).

The country tier deliberately carries NO ``<metric>`` mean. The per-cell rows already sit under the same
country surface, and region is not a filter, so a country-scoped ``agg=mean`` over ``drought_z`` reads
the cells; a country-tier mean under the SAME metric name would silently join that pool and double-count
the country against itself. ``_tail_share`` / ``frost_event_share`` / ``_cells`` are names that exist at
NO other grain under a country surface, so they can only ever be read as what they are.

CELL-COUNT PROVENANCE (W-3, the fidelity guard that must ship WITH the basins) — ``<metric>_cells``,
emitted at BOTH grains for every metric, integer counts carried as floats. The ``>= BASIN_MIN_COUNTRIES``
test runs on the WHOLE commodity frame across ALL metrics, but the sources do not cover the members
equally: CHIRPS stops at latitude 50 (configs/sources/chirps.yaml, coverage.lat_max), and MEASURED from
configs/geographies on 2026-08-25 that costs french_rapeseed_matif ALL 4 German and ALL 3 Polish cells
(and 1 of 5 French), french_wheat_matif 3 of 4 German, ALL 3 Polish and 1 of 6 French, and
hard_red_spring_wheat_mgex 2 of 3 CANADIAN cells. So an "EU (France/Germany/Poland)" drought leg would be
answered by a basin holding ZERO German or Polish drought cells, and a "Northern Plains" drought leg by
one that is 4/5 US -- while the temperature metrics on the SAME basin surface carry every member. Nothing
in the emitted rows said so. ``<metric>_cells`` says it: ``tmax_anomaly_cells``=16 beside
``drought_z_cells``=8 IS the disclosure, per metric, per month, at both grains, and a member whose
metric has no cells at all simply has NO country-tier row for that metric -- absence that a present
sibling metric makes legible instead of silent.

THE ORIGIN TIER (WX-1, data repairs 2026-09-29) -- see the block of that name below
``compute_weather_z``. BY ORIGIN COUNTRY, PRODUCTION-WEIGHTED, AND RAINFALL AS A SHARE OF NORMAL, as
NEW ROWS UNDER NEW METRIC NAMES produced by a SEPARATE pure function (``compute_origin_rows``) that
reads the finished frame of ``compute_weather_z`` and never edits it: every row this module emitted
before stays byte-identical because the function that emits it is not touched at all.

THE KNOWN DATE (WX-2, same repair) -- ``METRIC_SOURCES`` / ``known_date`` below: a row's (year, month)
is the DATA month; the date it became known is the month's last day plus the declared publication lag
of the source product behind the metric.
"""
from __future__ import annotations

import calendar
from collections import Counter
from datetime import date, timedelta

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
METRIC_FROST_SHARE = "frost_event_share"   # basin grain only — a share must never wear the flag's name

# THE PRELIMINARY STAMP (2026-09-15, the CHIRPS prelim lane) -- an OBSERVATION, not a prediction.
# ``drought_z`` may now be computed from CHIRPS v2.0 PRELIM days, about eighteen days before the
# authoritative FINAL block lands, and when that block lands the month is RECOMPUTED and the served z
# CHANGES after it has been served. Nothing in the estate recorded that a row was preliminary when it
# was read, so ``state/analogs.state_history``'s knowledge axis and ``state/feeders._recency``'s stamp
# had no way to say so and a banked analog ranking was not reproducible from today's bytes.
#
# It is a TALL METRIC ROW and not an eighth gold column, and the difference is the blast radius:
# ``GOLD_COLUMNS`` is a fixed 7-column contract mirrored into pg (``load_pg_numbers.P1_TABLES``) behind
# a Branch-A parity stage, with a generated Glue contract and a hand DDL. A column touches five files
# this lane may not open; a metric row touches none of them -- no DDL, no Glue, no pg schema, no parity.
#
# TWO NAMES, NOT ONE, and the reason is the estate's own ``frost_event_share`` precedent: at CELL grain
# this is a 0/1 flag (that cell-month was fed by prelim bytes, or it was not), but ``_basin_rows``
# averages every metric it finds, so at BASIN and COUNTRY grain the same number is a SHARE OF CELLS.
# A fraction wearing a flag's name is exactly the misreading ``frost_event_share`` was renamed to
# prevent, so the aggregate grains rename it here too.
METRIC_DROUGHT_PRELIM = "drought_z_is_preliminary"        # CELL grain: 1.0 = built from prelim bytes
METRIC_DROUGHT_PRELIM_SHARE = "drought_z_preliminary_share"   # aggregate grain: share of member cells

Z_METRICS = (METRIC_TMAX_ANOMALY, METRIC_GDD_Z, METRIC_HEAT_STRESS_Z, METRIC_DROUGHT_Z)
# The stamp is a CELL-grain metric (it is emitted beside each drought_z cell row), so it belongs here
# and not in DERIVED_METRICS -- but it is NOT a z, so it gets no ``_tail_share`` and is never winsorized.
ALL_METRICS = Z_METRICS + (METRIC_FROST_FLAG, METRIC_DROUGHT_PRELIM)
TAIL_SHARE_SUFFIX = "_tail_share"
CELLS_SUFFIX = "_cells"                    # W-3 provenance: how many member cells this row was built from
COUNTRY_TIER_SUFFIX = "_country"           # region token for the per-member tier (cf. ``_basin``)

# Metrics whose aggregate-grain row is a SHARE and must therefore be RENAMED, so a fraction can never
# be read as the flag it averages. One map, read at BOTH aggregate grains.
AGGREGATE_RENAMES: dict[str, str] = {
    METRIC_FROST_FLAG: METRIC_FROST_SHARE,
    METRIC_DROUGHT_PRELIM: METRIC_DROUGHT_PRELIM_SHARE,
}

# Everything the aggregate post-pass can emit that a per-cell row never carries -- the vocabulary the
# numbers card must declare and the only names legal at a basin OR country-tier surface. ALL_METRICS
# stays the CELL-grain contract (the registry fence asserts it is a subset of the card's metrics).
DERIVED_METRICS: tuple[str, ...] = (
    tuple(f"{m}{TAIL_SHARE_SUFFIX}" for m in Z_METRICS)
    + (METRIC_FROST_SHARE, METRIC_DROUGHT_PRELIM_SHARE)
    + tuple(f"{m}{CELLS_SUFFIX}" for m in ALL_METRICS)
)

# ── basin registry (W1.1; W-2 2026-08-25) — members in SILVER snake_case (the exact ``country:`` token
# configs/geographies/<commodity>_regions.yaml carries into the silver weather frames); surface = the
# resolvable country token the region_map basin entry points at. ONE entry per belt serves every
# commodity: ``_basin_rows`` intersects the member list against each commodity's OWN frame, so a
# contract that carries two members gets a basin and one that carries a single member is silently
# skipped by the nunique() < BASIN_MIN_COUNTRIES guard. Add basins here ONLY with a measured member list.
#
# MEASURED member lists (configs/geographies, 2026-08-25; the same instrument reproduces west_africa's
# live-frame cell counts exactly, which is why it is trusted for the three new belts):
#   west_africa               cocoa {cote_divoire 4, ghana 3, cameroon 2, nigeria 2} = 11 cells.
#                             (Ecuador is South America and stays a per-cell read.)
#   eu_belt                   french_wheat_matif   {france 6, germany 4, poland 3, romania 3} = 16
#                             french_rapeseed_matif{france 5, germany 4, poland 3, ukraine 4} = 16
#                             french_maize_matif   {france 5, romania 3, hungary 2, italy 3}  = 13
#                             corn_cbot intersects at ukraine ALONE -> 1 country -> skipped, correctly.
#   sea_palm_belt             malaysian_crude_palm_oil_cme {malaysia 6, indonesia 6} = 12
#                             palm_olein_dce               {indonesia 6, malaysia 5} = 11
#                             robusta_coffee intersects at indonesia alone -> skipped, correctly.
#   northern_plains_prairies  hard_red_spring_wheat_mgex {united_states 4, canada 3} = 7. Every other
#                             US or Canadian contract (soybeans_cbot, canola_ice, rapeseed_*_zce, ...)
#                             carries exactly ONE of the two and is skipped.
#
# SURFACE TOKENS ARE LOAD-BEARING: eu_belt is "EU Belt" and NEVER "European Union" -- that string is a
# LIVE per-cell country value (rapeseed_oil_zce carries country european_union), and reusing it would
# merge a belt aggregate into a real country's row pool.
#
# STRUCK, do not add: us_midwest_soy_belt and safrinha_belt are SINGLE-COUNTRY -- the nunique guard
# would skip them silently forever, and a single country already has per-cell rows plus (since W-4) a
# country tier wherever it rides a real belt. black_sea_wheat_belt is NOT CONSTRUCTIBLE from the live
# geographies (no commodity frame carries two of its would-be members).
BASINS: dict[str, dict] = {
    "west_africa": {
        "surface": "West Africa",
        "members": ["cameroon", "cote_divoire", "ghana", "nigeria"],
    },
    "eu_belt": {
        "surface": "EU Belt",
        "members": ["france", "germany", "poland", "romania", "hungary", "italy", "ukraine"],
    },
    "sea_palm_belt": {
        "surface": "SE Asia Palm Belt",
        "members": ["indonesia", "malaysia"],
    },
    "northern_plains_prairies": {
        "surface": "Northern Plains",
        "members": ["united_states", "canada"],
    },
}
TAIL_SIGMA = 2.0
BASIN_MIN_COUNTRIES = 2
BASIN_MIN_CELLS = 2
# The country tier needs only ONE cell. A 1-cell tail share is 0.0 or 1.0 -- a legitimate reading of
# "that country's only cell is / is not in the tail" -- and the ``<metric>_cells`` row emitted beside it
# states the thinness outright. Disclosure beats a floor here: a floor would DELETE the very rows W-3
# exists to make visible (the lat-50 members are exactly the thin ones).
COUNTRY_MIN_CELLS = 1

# ── default thresholds — mirror the weather_stage.py defaults (baselines / gdd / heat_stress / drought) ─
BASELINE_WINDOW_YEARS = 30
BASELINE_MIN_YEARS = 10
# Winsorize bound for all z metrics: beyond |z|~6 the magnitude is statistical noise from a thin
# same-month baseline (prior-year counts like {0,0,1,0} -> tiny std), never a meaningful reading.
Z_CAP = 6.0
GDD_BASE_C = 10.0
GDD_CAP_C = 30.0
HEAT_THRESHOLD_C = 35.0
DRY_PERCENTILE = 20.0
FROST_THRESHOLD_C = 0.0

_TMAX = "temperature_2m_max_c"
_TMIN = "temperature_2m_min_c"
_PRECIP = "precipitation_mm"
_KEYS = ["country", "region", "year", "month"]
# The silver_chirps provenance column, carried as a '0'/'1' STRING (the gold_board_crush
# is_roll_boundary precedent) and coerced to a 0.0/1.0 float here. ABSENT is a real and permanent case:
# every silver object written before 2026-09-15 lacks the column and is never rewritten, so a concat of
# legacy and current objects yields NaN for the legacy rows. Absent and NaN both mean FINAL, and that is
# a statement about those bytes -- the prelim product was unreachable when they were written.
_PRELIM_COL = "is_preliminary"


def to_psd_surface(country: str) -> str:
    """snake_case silver weather country -> PSD Title-Case surface form (silverleg.py:93-94 convention).

    'united_states' -> 'United States', 'brazil' -> 'Brazil', 'european_union' -> 'European Union' — the
    exact strings the region_map resolve block and silver_psd store, so a country_rule=region weather leg
    matches instead of going DARK.
    """
    return str(country).replace("_", " ").title()


def _slice(long_df: pd.DataFrame | None, variable: str) -> pd.DataFrame | None:
    """One weather variable as a clean daily long frame (country, region, year, month, day, value).

    ``is_preliminary`` rides along WHEN THE FRAME CARRIES IT, coerced to 0.0/1.0. When it does not --
    every pre-2026-09-15 silver object, and every nasa_power frame -- the projection is the pre-lane
    one, column for column, which is what makes the whole historical corpus byte-identical through this
    seam. Nothing downstream keys on it except :func:`_month_prelim_flags`."""
    if long_df is None or long_df.empty or "variable" not in long_df.columns:
        return None
    cols = ["country", "region", "year", "month", "day", "value"]
    if _PRELIM_COL in long_df.columns:
        cols.append(_PRELIM_COL)
    df = long_df.loc[long_df["variable"] == variable, cols].copy()
    if df.empty:
        return None
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    for c in ("year", "month", "day"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["value", "year", "month", "day"])
    if df.empty:
        return None
    df[["year", "month", "day"]] = df[["year", "month", "day"]].astype(int)
    if _PRELIM_COL in df.columns:
        # A row the merge could not match, or a legacy object concatenated beside a current one, is
        # NaN here -- and NaN is FINAL, for the same reason the column's absence is.
        df[_PRELIM_COL] = pd.to_numeric(df[_PRELIM_COL], errors="coerce").fillna(0.0).astype(float)
    return df


def _complete_months_only(daily: pd.DataFrame | None) -> pd.DataFrame | None:
    """Drop (country, region, year, month) groups whose observed distinct days do not cover the FULL
    calendar month. A partial month's SUM/COUNT reductions crater against full-month baselines (the
    served gdd_z=-13.16), and its mean/min/flag reductions are short samples; no family may see one.
    Historic silver is gapless (probed 2012/2019), so this binds only on the live trailing month."""
    if daily is None or daily.empty:
        return daily
    key = ["country", "region", "year", "month"]
    obs = daily.groupby(key)["day"].nunique().reset_index(name="observed_days")
    cal = obs.apply(lambda r: pd.Timestamp(int(r["year"]), int(r["month"]), 1).days_in_month, axis=1)
    keep = obs.loc[obs["observed_days"] >= cal, key]
    if keep.empty:
        return None
    return daily.merge(keep, on=key, how="inner")


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
        z = trailing_baseline_z(yearly, window_years, min_years).clip(lower=-Z_CAP, upper=Z_CAP)
        surface = to_psd_surface(country)
        for year, zval in z.items():
            rows.append((commodity, surface, region, int(year), int(month), metric, zval))
    return rows


def _monthly_scalar(daily: pd.DataFrame, col: str, how: str) -> pd.DataFrame:
    """Reduce a daily frame to one scalar per (country, region, year, month). how in {mean, sum}."""
    agg = daily.groupby(_KEYS, as_index=False)[col].agg(how)
    return agg.rename(columns={col: "scalar"})


def _tmax_anomaly(nasa: pd.DataFrame, *, commodity, window_years, min_years,
                  complete_months) -> list[tuple]:
    tmax = _slice(nasa, _TMAX)
    if complete_months:
        tmax = _complete_months_only(tmax)
    if tmax is None:
        return []
    monthly = _monthly_scalar(tmax, "value", "mean")
    return _same_month_z(monthly, commodity=commodity, metric=METRIC_TMAX_ANOMALY,
                         window_years=window_years, min_years=min_years)


def _heat_stress_z(nasa: pd.DataFrame, *, commodity, window_years, min_years, threshold,
                   complete_months) -> list[tuple]:
    tmax = _slice(nasa, _TMAX)
    if complete_months:
        tmax = _complete_months_only(tmax)
    if tmax is None:
        return []
    tmax = tmax.copy()
    tmax["hot"] = (tmax["value"] > threshold).astype(float)
    monthly = _monthly_scalar(tmax, "hot", "sum")
    return _same_month_z(monthly, commodity=commodity, metric=METRIC_HEAT_STRESS_Z,
                         window_years=window_years, min_years=min_years)


def _gdd_z(nasa: pd.DataFrame, *, commodity, window_years, min_years, base, cap,
           complete_months) -> list[tuple]:
    tmax = _slice(nasa, _TMAX)
    tmin = _slice(nasa, _TMIN)
    if tmax is None or tmin is None:
        return []
    merged = tmax.rename(columns={"value": "tmax"}).merge(
        tmin.rename(columns={"value": "tmin"}),
        on=["country", "region", "year", "month", "day"], how="inner")
    if complete_months:
        # gate the MERGED frame: a day missing from EITHER variable leaves the month's GDD sum short
        merged = _complete_months_only(merged)
    if merged is None or merged.empty:
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


def _month_prelim_flags(precip: pd.DataFrame) -> dict[tuple, float]:
    """``(psd_country, region, year, month) -> 1.0 if ANY day of that month came from PRELIM bytes``.

    THE ASYMMETRY, the same one bronze states: ANY preliminary day makes the month preliminary; only
    ALL final days make it final. Hence ``max`` over the month's days and never a mean -- a month that
    is 20 days final and 11 days prelim is a PRELIMINARY month, because the figure the board prints was
    built from bytes that will be revised.

    Empty when the frame carries no provenance column at all, which is the signal :func:`_drought_z`
    uses to emit NO stamp rows whatsoever and stay byte-identical to the pre-lane transform."""
    if precip is None or precip.empty or _PRELIM_COL not in precip.columns:
        return {}
    grouped = precip.groupby(_KEYS)[_PRELIM_COL].max()
    return {(to_psd_surface(country), region, int(year), int(month)): float(flag)
            for (country, region, year, month), flag in grouped.items()}


def _drought_z(chirps: pd.DataFrame, *, commodity, window_years, min_years, dry_percentile,
               complete_months) -> list[tuple]:
    precip = _slice(chirps, _PRECIP)
    if complete_months:
        precip = _complete_months_only(precip)
    if precip is None:
        return []
    runs = _drought_runs(precip, window_years=window_years, min_years=min_years,
                         dry_percentile=dry_percentile)
    if runs.empty:
        return []
    rows = _same_month_z(runs, commodity=commodity, metric=METRIC_DROUGHT_Z,
                         window_years=window_years, min_years=min_years)
    flags = _month_prelim_flags(precip)
    if not flags:
        return rows
    # ONE STAMP PER EMITTED drought_z ROW, keyed off the z rows themselves rather than off the precip
    # frame, so the two can never be emitted for different (country, region, year, month) sets: a stamp
    # with no z would be a provenance claim about a figure that was never served, and a z with no stamp
    # is the silence this metric exists to end. A NaN z is dropped by ``_emit`` (thin baseline), so its
    # stamp is skipped here for the same reason.
    stamps: list[tuple] = []
    for commodity_, surface, region, year, month, _metric, zval in rows:
        if zval is None or zval != zval:      # NaN -- the z row will be dropped, so no stamp either
            continue
        flag = flags.get((surface, region, int(year), int(month)))
        if flag is None:
            continue
        stamps.append((commodity_, surface, region, int(year), int(month),
                       METRIC_DROUGHT_PRELIM, float(flag)))
    return rows + stamps


def _frost_flag(nasa: pd.DataFrame, *, commodity, threshold, complete_months) -> list[tuple]:
    tmin = _slice(nasa, _TMIN)
    if complete_months:
        # a partial month's 0.0 flag would be a false "no frost" claim over days never observed
        tmin = _complete_months_only(tmin)
    if tmin is None:
        return []
    monthly_min = tmin.groupby(_KEYS, as_index=False)["value"].min()
    rows: list[tuple] = []
    for r in monthly_min.itertuples(index=False):
        flag = 1.0 if float(r.value) < threshold else 0.0
        rows.append((commodity, to_psd_surface(r.country), r.region, int(r.year), int(r.month),
                     METRIC_FROST_FLAG, flag))
    return rows


def _tail_share(values) -> float:
    """Share of member cells at or beyond +TAIL_SIGMA. One definition, both grains."""
    return float((values >= TAIL_SIGMA).mean())


def _basin_rows(gold: pd.DataFrame, basins: dict[str, dict]) -> pd.DataFrame:
    """Aggregate per-cell gold rows into basin rows (W1.1) and per-member country-tier rows (W-4).
    Pure post-pass over the tall frame.

    A basin is considered for a commodity only when >= BASIN_MIN_COUNTRIES of its member countries
    appear in that commodity's frame; otherwise NOTHING is emitted for it at EITHER grain -- the
    country tier is a decomposition OF a basin read, never a standalone per-country product (a lone
    country already has its own per-cell rows). Per (commodity, metric, year, month):

      BASIN grain   (country = spec['surface'], region = ``<basin>_basin``), gated on
                    >= BASIN_MIN_CELLS member cells in the group:
                      ``<metric>``            basin MEAN (frost renamed ``frost_event_share``)
                      ``<metric>_tail_share`` z metrics only -- share of cells at >= +TAIL_SIGMA
                      ``<metric>_cells``      how many member cells the two rows above were built from

      COUNTRY grain (country = the member's own PSD surface, region = ``<member>_country``), gated on
                    the SAME group clearing BASIN_MIN_CELLS at basin grain, plus >= COUNTRY_MIN_CELLS
                    cells for that member -- so a country-tier row ALWAYS has a parent basin row at the
                    same (commodity, metric, year, month), and a month too thin for a belt read never
                    reappears decomposed:
                      ``<metric>_tail_share`` z metrics only -- share of THAT country's cells in the tail
                      ``frost_event_share``   frost only -- mean of THAT country's 0/1 flags
                      ``<metric>_cells``      that country's contributing cell count
                    NO ``<metric>`` mean: the per-cell rows already sit under this country surface and
                    region is not a v1 query filter, so a same-named mean would double-count.

    A member appearing in two basins is emitted ONCE at country grain (first basin in registry order):
    the row is basin-independent by construction, so a second copy would only duplicate the tall key.
    """
    if gold.empty:
        return pd.DataFrame(columns=GOLD_COLUMNS)
    rows: list[tuple] = []
    seen_country: set[tuple] = set()
    for basin, spec in basins.items():
        member_by_surface = {to_psd_surface(m): m for m in spec["members"]}
        sub = gold[gold["country"].isin(set(member_by_surface))]
        if sub.empty or sub["country"].nunique() < BASIN_MIN_COUNTRIES:
            continue
        surface = spec["surface"]
        region = f"{basin}_basin"
        agg = sub.groupby(["commodity", "metric", "year", "month"])["value"].agg(
            basin_mean="mean", n_cells="count", tail_share=_tail_share).reset_index()
        # the basin-grain cell count IS the country tier's gate -- one guard, one meaning
        basin_cells = {(r.commodity, r.metric, int(r.year), int(r.month)): int(r.n_cells)
                       for r in agg.itertuples(index=False)}
        for r in agg.itertuples(index=False):
            if int(r.n_cells) < BASIN_MIN_CELLS:
                continue
            key = (r.commodity, surface, region, int(r.year), int(r.month))
            # A MEAN OF FLAGS IS A SHARE, and a share may never wear the flag's name: frost_event_flag
            # -> frost_event_share, drought_z_is_preliminary -> drought_z_preliminary_share. One map,
            # read at this grain and at the country grain below.
            out_metric = AGGREGATE_RENAMES.get(r.metric, r.metric)
            rows.append((*key, out_metric, float(r.basin_mean)))
            if r.metric in Z_METRICS:
                rows.append((*key, f"{r.metric}{TAIL_SHARE_SUFFIX}", float(r.tail_share)))
            rows.append((*key, f"{r.metric}{CELLS_SUFFIX}", float(r.n_cells)))

        cagg = sub.groupby(["commodity", "country", "metric", "year", "month"])["value"].agg(
            country_mean="mean", n_cells="count", tail_share=_tail_share).reset_index()
        for r in cagg.itertuples(index=False):
            group = (r.commodity, r.metric, int(r.year), int(r.month))
            if basin_cells.get(group, 0) < BASIN_MIN_CELLS or int(r.n_cells) < COUNTRY_MIN_CELLS:
                continue
            creg = f"{member_by_surface[r.country]}{COUNTRY_TIER_SUFFIX}"
            key = (r.commodity, r.country, creg, int(r.year), int(r.month))
            if (key, r.metric) in seen_country:
                continue
            seen_country.add((key, r.metric))
            if r.metric in Z_METRICS:
                rows.append((*key, f"{r.metric}{TAIL_SHARE_SUFFIX}", float(r.tail_share)))
            elif r.metric in AGGREGATE_RENAMES:
                # The flag families carry their SHARE at this grain (never a ``<metric>`` mean, which
                # would double-count the country against its own per-cell rows).
                rows.append((*key, AGGREGATE_RENAMES[r.metric], float(r.country_mean)))
            rows.append((*key, f"{r.metric}{CELLS_SUFFIX}", float(r.n_cells)))
    return _emit(rows)


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
    enforce_month_completeness: bool = True,
    basins: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """Compute the tall gold_weather_z frame for ONE commodity from its silver weather long frames.

    ``nasa_power`` supplies temperature_2m_max_c / temperature_2m_min_c (heat/gdd/tmax/frost families);
    ``chirps`` supplies precipitation_mm (drought family). Either may be None/empty -> that family is
    skipped. Returns a frame with columns ``GOLD_COLUMNS``; NaN z-scores (insufficient baseline) are
    dropped, frost 0.0 flags are kept. ``enforce_month_completeness`` (production default True) drops
    months not covering every calendar day — the -13.16 partial-month guard; z metrics are winsorized
    at +/-``Z_CAP`` either way. Tests exercising synthetic short months pass False explicitly.

    ``basins`` (default: the module ``BASINS`` registry) appends the aggregate post-pass for basins with
    enough member countries present in THIS commodity's frame: basin rows (mean + ``_tail_share`` per z
    metric + ``frost_event_share``) and the per-member country tier (``_tail_share`` /
    ``frost_event_share`` only, never a mean), with ``<metric>_cells`` provenance at both grains — see
    the module docstring's BASIN AGGREGATE ROWS / PER-COUNTRY TAIL TIER / CELL-COUNT PROVENANCE blocks.
    Pass ``{}`` to disable.
    """
    cm = enforce_month_completeness
    rows: list[tuple] = []
    rows += _tmax_anomaly(nasa_power, commodity=commodity, window_years=window_years,
                         min_years=min_years, complete_months=cm)
    rows += _heat_stress_z(nasa_power, commodity=commodity, window_years=window_years,
                          min_years=min_years, threshold=heat_threshold_c, complete_months=cm)
    rows += _gdd_z(nasa_power, commodity=commodity, window_years=window_years, min_years=min_years,
                  base=gdd_base_c, cap=gdd_cap_c, complete_months=cm)
    rows += _drought_z(chirps, commodity=commodity, window_years=window_years, min_years=min_years,
                      dry_percentile=dry_percentile, complete_months=cm)
    rows += _frost_flag(nasa_power, commodity=commodity, threshold=frost_threshold_c, complete_months=cm)
    gold = _emit(rows)
    basin_extra = _basin_rows(gold, BASINS if basins is None else basins)
    if not basin_extra.empty:
        gold = pd.concat([gold, basin_extra], ignore_index=True)
    return gold


# ── THE ORIGIN TIER (WX-1, data repairs 2026-09-29) ────────────────────────────────────────────────
# WHAT WAS WRONG, MEASURED (data_repairs_0929/checks/chk_wx.py). The cocoa page read "wetter than
# usual" off the West Africa basin's August-2026 drought_z of -0.92: the EQUAL-WEIGHT mean of 11 cells
# (4 of them in Cameroon and Nigeria) of a dry-spell LENGTH z. In our own CHIRPS silver, Cote d'Ivoire
# -- the origin that sets the main crop -- had 50.0 % of its 1991-2020 July rainfall and 75.5 % of
# August's, while Ghana had 136.0 % of August's. The two largest origins moved opposite ways and the
# mean hid both, and the store held no per-country mean, no rainfall metric and no production weight.
#
# WHAT IS ADDED -- ROWS UNDER NEW METRIC NAMES; the 7-column shape, the grain and every existing row
# are unchanged (compute_weather_z above is not edited; this block reads its finished frame):
#   CELL tier    (region = the cell token; EVERY CHIRPS cell of EVERY commodity, complete months only)
#     precip_total_mm        the month's rainfall total
#     precip_normal_mm       the mean total of that calendar month over the NORMAL PERIOD (below)
#     precip_pct_normal      100 x precip_total_mm / precip_normal_mm (only where the normal is > 0)
#     precip_is_preliminary  1.0 if ANY day of the month came from CHIRPS PRELIM bytes -- the drought
#                            stamp's asymmetry, emitted only when the frame carries the provenance column
#   COUNTRY tier (region = <member>_country, under the member's own PSD surface; basin members only)
#     <z>_country_mean       the equal-weight mean of THAT country's cells, for each of the four z metrics
#     precip_pct_normal_country  100 x the country's summed cell rainfall / its summed cell normals
#     precip_pct_normal_cells    the cells behind that ratio
#     precip_preliminary_share   the share of those cells whose month is preliminary
#     production_share       the member's share of the basin members' FAOSTAT production (0-1)
#     production_share_year  the FAOSTAT year that share was taken from
#   BASIN tier   (region = <basin>_basin, under the basin surface)
#     <z>_prod_weighted      sum over members of production_share x <z>_country_mean
#     precip_pct_normal_prod_weighted  sum over members of production_share x precip_pct_normal_country
#     precip_pct_normal_basin  100 x the basin's summed cell rainfall / summed cell normals
#     precip_pct_normal_cells, precip_preliminary_share   as at the country tier
#
# THE NAME RULE (T-WX-1 / T-WX-2). The serving leg aggregates a commodity's rows by COUNTRY with no
# region filter, so (a) no country-tier name may be a name a cell row carries -- a per-country
# ``tmax_anomaly`` under "Ghana" would be averaged with Ghana's own three cells -- and (b) no new basin
# name may be an existing basin name -- a weighted ``drought_z`` under "West Africa" would be averaged
# with the equal-weight one. Every new aggregate therefore carries a suffix no other grain carries
# (``_country_mean``, ``_prod_weighted``, ``_country``, ``_basin``). The deck asserts the name sets.
#
# NOT IN ALL_METRICS / DERIVED_METRICS, ON PURPOSE. Those two tuples are the CARD'S contract:
# tests/unit/test_contract_check.py binds them to the gold_weather_z card in BOTH directions, and the
# card is the serving side's to edit. These names are emitted into the store and stay invisible to
# serving -- the pg loader mirrors a TALL table's DECLARED metrics only -- until the card declares them
# (with their lags) and the binding folds ``ORIGIN_METRICS`` into its roster in the same edit.
#
# THE WEIGHTS (T-WX-3..5). FAOSTAT QCL ``production_quantity`` for the gold row's OWN commodity slug
# (silver_production, read by the task), members joined on the SAME snake token the geographies file
# carries (``country_key``). That join is a string identity, so it is a TRIPWIRE, never a guess: a
# member that resolves to no FAOSTAT row, or to two areas, fails the whole basin's weights closed and
# the reason is returned. The shares are over the members PRESENT in the commodity's frame and sum to
# one; a weighted row is emitted only when EVERY present member has a value that month -- never
# renormalised over the members that happen to have one (a drought mean over two of four EU members is
# not the EU). The weight year (O-4) is the latest FAOSTAT year whose DECLARED publication lag has
# elapsed by the month's last day, so a weight is always known before the weather row it weights; no
# declared lag -> no weight year can be dated -> no weights at all, and the reason says so.
#
# THE NORMAL (O-5 default, T-WX-6). The WMO 30-year period IN FORCE at the month: the latest 30-year
# period ending in a year divisible by ten and strictly before the month's year -- 1991-2020 for months
# from 2021, 1981-2010 for 2011-2020, and for earlier months the CHIRPS-truncated 1981-2000 / 1981-1990.
# At least ``NORMAL_MIN_YEARS`` years of complete months are required, else the month has no normal.
# PIT-safe by construction (the period ends before the month's year) and it reproduces the measured
# 50.0 / 75.5 / 136.0. The country ratio is a RATIO OF SUMS (the mean of cell ratios reads 51 / 71 / 140
# on the same bytes, and differs by up to 30 points elsewhere): a country's rainfall against its normal,
# not the average of its cells' percentages.
METRIC_PRECIP_TOTAL = "precip_total_mm"
METRIC_PRECIP_NORMAL = "precip_normal_mm"
METRIC_PRECIP_PCT = "precip_pct_normal"
METRIC_PRECIP_PRELIM = "precip_is_preliminary"
METRIC_PRECIP_PCT_COUNTRY = "precip_pct_normal_country"
METRIC_PRECIP_PCT_BASIN = "precip_pct_normal_basin"
METRIC_PRECIP_PRELIM_SHARE = "precip_preliminary_share"
METRIC_PRODUCTION_SHARE = "production_share"
METRIC_PRODUCTION_SHARE_YEAR = "production_share_year"
COUNTRY_MEAN_SUFFIX = "_country_mean"
PROD_WEIGHTED_SUFFIX = "_prod_weighted"
METRIC_PRECIP_PCT_CELLS = f"{METRIC_PRECIP_PCT}{CELLS_SUFFIX}"
METRIC_PRECIP_PCT_WEIGHTED = f"{METRIC_PRECIP_PCT}{PROD_WEIGHTED_SUFFIX}"

ORIGIN_CELL_METRICS: tuple[str, ...] = (
    METRIC_PRECIP_TOTAL, METRIC_PRECIP_NORMAL, METRIC_PRECIP_PCT, METRIC_PRECIP_PRELIM)
ORIGIN_COUNTRY_METRICS: tuple[str, ...] = (
    tuple(f"{m}{COUNTRY_MEAN_SUFFIX}" for m in Z_METRICS)
    + (METRIC_PRECIP_PCT_COUNTRY, METRIC_PRECIP_PCT_CELLS, METRIC_PRECIP_PRELIM_SHARE,
       METRIC_PRODUCTION_SHARE, METRIC_PRODUCTION_SHARE_YEAR)
)
ORIGIN_BASIN_METRICS: tuple[str, ...] = (
    tuple(f"{m}{PROD_WEIGHTED_SUFFIX}" for m in Z_METRICS)
    + (METRIC_PRECIP_PCT_WEIGHTED, METRIC_PRECIP_PCT_BASIN, METRIC_PRECIP_PCT_CELLS,
       METRIC_PRECIP_PRELIM_SHARE)
)
ORIGIN_METRICS: tuple[str, ...] = tuple(dict.fromkeys(
    ORIGIN_CELL_METRICS + ORIGIN_COUNTRY_METRICS + ORIGIN_BASIN_METRICS))

# The WMO standard-normal convention: 30-year periods, re-based every 10 years (1961-1990 ... 1991-2020).
NORMAL_PERIOD_YEARS = 30
NORMAL_PERIOD_STEP_YEARS = 10
NORMAL_MIN_YEARS = BASELINE_MIN_YEARS
# The ONE FAOSTAT element the weights read -- the physical metric name silver_production carries
# (the numbers card's `production_quantity`, unit t).
FAOSTAT_PRODUCTION_METRIC = "production_quantity"


def normal_period(year: int) -> tuple[int, int]:
    """The WMO 30-year normal period in force for a month of ``year``: ``(first, last)`` year.

    The latest period of ``NORMAL_PERIOD_YEARS`` ending in a multiple of ``NORMAL_PERIOD_STEP_YEARS``
    and strictly before ``year`` -- 2026 -> (1991, 2020), 2021 -> (1991, 2020), 2020 -> (1981, 2010).
    The caller intersects it with the years it holds (CHIRPS starts 1981)."""
    last = ((int(year) - 1) // NORMAL_PERIOD_STEP_YEARS) * NORMAL_PERIOD_STEP_YEARS
    return last - NORMAL_PERIOD_YEARS + 1, last


def _month_end(year: int, month: int) -> date:
    return date(int(year), int(month), calendar.monthrange(int(year), int(month))[1])


def _precip_cells(chirps: pd.DataFrame | None, *, complete_months: bool,
                  normal_min_years: int) -> pd.DataFrame:
    """One row per COMPLETE cell-month: [country, region, year, month, total, normal, prelim].

    ``normal`` is NaN where the normal period holds fewer than ``normal_min_years`` complete months of
    that calendar month; ``prelim`` is NaN for every row when the frame carries no provenance column
    (and then no stamp is emitted), else the month's max over its days (ANY prelim day -> 1.0)."""
    cols = ["country", "region", "year", "month", "total", "normal", "prelim"]
    precip = _slice(chirps, _PRECIP)
    if complete_months:
        precip = _complete_months_only(precip)
    if precip is None or precip.empty:
        return pd.DataFrame(columns=cols)
    monthly = (precip.groupby(_KEYS, as_index=False)["value"].sum()
               .rename(columns={"value": "total"}))
    if _PRELIM_COL in precip.columns:
        flags = (precip.groupby(_KEYS, as_index=False)[_PRELIM_COL].max()
                 .rename(columns={_PRELIM_COL: "prelim"}))
        monthly = monthly.merge(flags, on=_KEYS, how="left")
    else:
        monthly["prelim"] = np.nan
    normal = pd.Series(np.nan, index=monthly.index, dtype=float)
    for _key, grp in monthly.groupby(["country", "region", "month"], sort=False):
        by_year = grp.set_index("year")["total"].astype(float)
        for idx, year in zip(grp.index, grp["year"]):
            lo, hi = normal_period(int(year))
            base = by_year[(by_year.index >= lo) & (by_year.index <= hi)]
            if len(base) >= normal_min_years:
                normal.loc[idx] = float(base.mean())
    monthly["normal"] = normal
    return monthly[cols].reset_index(drop=True)


def _member_production(production: pd.DataFrame | None,
                       members: list[str]) -> tuple[dict | None, list[int], str]:
    """``({member: {year: tonnes}}, held_years, "")`` or ``(None, [], reason)``.

    Each member (the geographies file's snake token) must resolve to EXACTLY ONE FAOSTAT area through
    ``country_key`` and carry at most one production row per year; anything else fails the basin's
    weights closed with the reason, never a partial basin (T-WX-4)."""
    if production is None or len(production) == 0:
        return None, [], "no silver_production (FAOSTAT) rows were read for this commodity"
    need = {"country", "country_key", "metric", "value", "year"}
    if not need <= set(production.columns):
        return None, [], f"the silver_production frame lacks {sorted(need - set(production.columns))}"
    prod = production[production["metric"] == FAOSTAT_PRODUCTION_METRIC]
    years = sorted({int(y) for y in pd.to_numeric(prod["year"], errors="coerce").dropna()})
    table: dict[str, dict[int, float]] = {}
    problems: list[str] = []
    for member in members:
        rows = prod[prod["country_key"] == member]
        if rows.empty:
            problems.append(f"'{member}' matches no FAOSTAT country_key")
            continue
        areas = sorted({str(a) for a in rows["country"].dropna()})
        if len(areas) != 1:
            problems.append(f"'{member}' matches {len(areas)} FAOSTAT areas {areas}")
            continue
        yr = pd.to_numeric(rows["year"], errors="coerce").astype(int)
        if yr.duplicated().any():
            problems.append(f"'{member}' carries more than one production row for a year")
            continue
        table[member] = {int(y): float(v) for y, v in
                         zip(yr, pd.to_numeric(rows["value"], errors="coerce"))}
    if problems:
        return None, [], "member resolution failed: " + "; ".join(problems)
    return table, years, ""


def _weights_for_month(year: int, month: int, table: dict, held_years: list[int],
                       lag_days: int) -> tuple[int, dict[str, float]] | str:
    """``(weight_year, {member: share})`` for a data month, or the reason there is none.

    weight_year = the latest held FAOSTAT year Y whose declared release (Dec 31 of Y + ``lag_days``)
    falls on or before the month's last day, so the weight is known before any weather row of that
    month (O-4). Every member must carry a finite, non-negative value for that year and the total must
    be positive; the shares then sum to one (asserted, 1e-9)."""
    horizon = _month_end(year, month)
    known = [y for y in held_years if date(y, 12, 31) + timedelta(days=int(lag_days)) <= horizon]
    if not known:
        return f"no FAOSTAT year is released by {horizon.isoformat()} at the declared lag {lag_days} d"
    wy = max(known)
    vals = {m: table[m].get(wy, float("nan")) for m in table}
    bad = sorted(m for m, v in vals.items() if not (np.isfinite(v) and v >= 0.0))
    if bad:
        return f"FAOSTAT {wy} carries no production value for {bad}"
    total = float(sum(vals.values()))
    if not total > 0.0:
        return f"FAOSTAT {wy} production over the members sums to {total}"
    shares = {m: v / total for m, v in vals.items()}
    if abs(sum(shares.values()) - 1.0) > 1e-9:          # arithmetic guard, never expected to fire
        return f"FAOSTAT {wy} shares sum to {sum(shares.values())!r}, not 1"
    return wy, shares


def _origin_aggregate_rows(commodity: str, gold: pd.DataFrame, cells: pd.DataFrame,
                           basins: dict[str, dict], production: pd.DataFrame | None,
                           production_lag_days: int | None, absent: Counter) -> list[tuple]:
    """The COUNTRY and BASIN tiers of the origin block. The basin membership test and the cell gates
    are the ones ``_basin_rows`` applies, read off the same cell rows, so an origin aggregate exists
    for exactly the (commodity, basin) pairs the legacy basin exists for."""
    rows: list[tuple] = []
    seen: set[tuple] = set()
    weight_owner: dict[str, str] = {}           # member surface -> the basin that printed its weights
    # CELL rows only: the cell-grain vocabulary under a member surface. Basin rows carry a basin
    # surface (never a member surface -- deck-pinned) and country-tier rows carry DERIVED names.
    cell_gold = gold[gold["metric"].isin(ALL_METRICS)] if not gold.empty else gold
    if not cells.empty:
        cells = cells.assign(surface=cells["country"].map(to_psd_surface))

    def _country_row(surface: str, member: str, year: int, month: int, metric: str, value: float):
        key = (commodity, surface, f"{member}{COUNTRY_TIER_SUFFIX}", int(year), int(month))
        if (key, metric) in seen:               # a member in two basins is emitted once (legacy rule)
            return
        seen.add((key, metric))
        rows.append((*key, metric, float(value)))

    for basin, spec in basins.items():
        member_by_surface = {to_psd_surface(m): m for m in spec["members"]}
        sub = cell_gold[cell_gold["country"].isin(set(member_by_surface))] if not cell_gold.empty \
            else cell_gold
        if sub.empty or sub["country"].nunique() < BASIN_MIN_COUNTRIES:
            continue
        present = sorted(sub["country"].unique())
        bkey = (commodity, spec["surface"], f"{basin}_basin")

        # (a) the per-country z means, on the legacy country tier's exact gate
        zsub = sub[sub["metric"].isin(Z_METRICS)]
        bcount = {(m, int(y), int(mo)): int(n) for (m, y, mo), n in
                  zsub.groupby(["metric", "year", "month"])["value"].count().items()}
        means: dict[tuple[str, int, int], dict[str, float]] = {}
        cagg = zsub.groupby(["country", "metric", "year", "month"])["value"].agg(["mean", "count"])
        for (surface, metric, y, mo), r in cagg.iterrows():
            if bcount.get((metric, int(y), int(mo)), 0) < BASIN_MIN_CELLS or int(r["count"]) < COUNTRY_MIN_CELLS:
                continue
            means.setdefault((metric, int(y), int(mo)), {})[surface] = float(r["mean"])
            _country_row(surface, member_by_surface[surface], y, mo,
                         f"{metric}{COUNTRY_MEAN_SUFFIX}", float(r["mean"]))

        # (b) rainfall against its normal: ratio of sums, basin and country, on the same cell gates
        pct_by_month: dict[tuple[int, int], dict[str, float]] = {}
        psub = cells[cells["surface"].isin(set(member_by_surface)) & cells["normal"].notna()] \
            if not cells.empty else cells
        for (y, mo), grp in (psub.groupby(["year", "month"]) if not psub.empty else ()):
            if len(grp) < BASIN_MIN_CELLS:
                continue
            stamped = bool(grp["prelim"].notna().all())
            normal_sum = float(grp["normal"].sum())
            if normal_sum > 0.0:
                rows.append((*bkey, int(y), int(mo), METRIC_PRECIP_PCT_BASIN,
                             100.0 * float(grp["total"].sum()) / normal_sum))
            rows.append((*bkey, int(y), int(mo), METRIC_PRECIP_PCT_CELLS, float(len(grp))))
            if stamped:
                rows.append((*bkey, int(y), int(mo), METRIC_PRECIP_PRELIM_SHARE,
                             float(grp["prelim"].astype(float).mean())))
            for surface, cg in grp.groupby("surface"):
                if len(cg) < COUNTRY_MIN_CELLS:
                    continue
                member = member_by_surface[surface]
                c_normal = float(cg["normal"].sum())
                if c_normal > 0.0:
                    pct = 100.0 * float(cg["total"].sum()) / c_normal
                    pct_by_month.setdefault((int(y), int(mo)), {})[surface] = pct
                    _country_row(surface, member, y, mo, METRIC_PRECIP_PCT_COUNTRY, pct)
                _country_row(surface, member, y, mo, METRIC_PRECIP_PCT_CELLS, float(len(cg)))
                if stamped:
                    _country_row(surface, member, y, mo, METRIC_PRECIP_PRELIM_SHARE,
                                 float(cg["prelim"].astype(float).mean()))

        # (c) + (d) the production weights and the weighted basin rows
        families: list[tuple[str, str, dict]] = [
            (f"{z}{PROD_WEIGHTED_SUFFIX}", f"{z}{COUNTRY_MEAN_SUFFIX}",
             {(y, mo): v for (m, y, mo), v in means.items() if m == z}) for z in Z_METRICS]
        families.append((METRIC_PRECIP_PCT_WEIGHTED, METRIC_PRECIP_PCT_COUNTRY, pct_by_month))
        reason = ""
        table: dict | None = None
        held: list[int] = []
        if production_lag_days is None:
            reason = ("the FAOSTAT publication lag is UNDECLARED (configs/datasets/source_contracts.yaml "
                      "production:faostat carries no publication_lag_days), so no weight year can be dated")
        else:
            table, held, reason = _member_production(production, [member_by_surface[s] for s in present])
        owner = sorted({weight_owner[s] for s in present if s in weight_owner})
        if not reason and owner:
            reason = f"a member already carries production_share from basin(s) {owner}"
        if reason:
            for out_metric, _stem, by_month in families:
                if by_month:
                    absent[(commodity, basin, out_metric, reason)] += len(by_month)
            continue
        cache: dict[tuple[int, int], tuple[int, dict[str, float]] | str] = {}
        used: dict[tuple[int, int], tuple[int, dict[str, float]]] = {}
        for out_metric, stem, by_month in families:
            for (y, mo), vals in sorted(by_month.items()):
                if (y, mo) not in cache:
                    cache[(y, mo)] = _weights_for_month(y, mo, table, held, int(production_lag_days))
                w = cache[(y, mo)]
                if isinstance(w, str):
                    absent[(commodity, basin, out_metric, w)] += 1
                    continue
                missing = [s for s in present if s not in vals]
                if missing:
                    absent[(commodity, basin, out_metric,
                            f"member(s) {missing} carry no {stem} that month")] += 1
                    continue
                wy, shares = w
                value = sum(shares[member_by_surface[s]] * vals[s] for s in present)
                rows.append((*bkey, int(y), int(mo), out_metric, float(value)))
                used[(y, mo)] = w
        for (y, mo), (wy, shares) in sorted(used.items()):
            for s in present:
                _country_row(s, member_by_surface[s], y, mo, METRIC_PRODUCTION_SHARE,
                             shares[member_by_surface[s]])
                _country_row(s, member_by_surface[s], y, mo, METRIC_PRODUCTION_SHARE_YEAR, float(wy))
        if used:
            for s in present:
                weight_owner[s] = basin
    return rows


def compute_origin_rows(
    commodity: str,
    *,
    gold: pd.DataFrame,
    chirps: pd.DataFrame | None = None,
    production: pd.DataFrame | None = None,
    production_lag_days: int | None = None,
    basins: dict[str, dict] | None = None,
    enforce_month_completeness: bool = True,
    normal_min_years: int = NORMAL_MIN_YEARS,
) -> tuple[pd.DataFrame, list[dict]]:
    """The origin tier (WX-1) for ONE commodity: ``(rows, absences)``.

    ``gold`` is the FINISHED frame of :func:`compute_weather_z` for the same commodity and is only
    read; ``chirps`` is the same long CHIRPS frame it was given; ``production`` is that commodity's
    silver_production (FAOSTAT) frame with a ``year`` column; ``production_lag_days`` is the DECLARED
    FAOSTAT publication lag (``None`` = undeclared -> no weights). Returns ONLY the new rows, in
    ``GOLD_COLUMNS``, every metric in :data:`ORIGIN_METRICS`; the caller appends them to ``gold``.

    ``absences`` lists every weighted series that could NOT be emitted, one dict per
    (basin, metric, reason) with the count of months -- a missing figure is never silent."""
    absent: Counter = Counter()
    cells = _precip_cells(chirps, complete_months=enforce_month_completeness,
                          normal_min_years=normal_min_years)
    rows: list[tuple] = []
    for r in cells.itertuples(index=False):
        key = (commodity, to_psd_surface(r.country), r.region, int(r.year), int(r.month))
        rows.append((*key, METRIC_PRECIP_TOTAL, float(r.total)))
        if np.isfinite(r.normal):
            rows.append((*key, METRIC_PRECIP_NORMAL, float(r.normal)))
            if r.normal > 0.0:
                rows.append((*key, METRIC_PRECIP_PCT, 100.0 * float(r.total) / float(r.normal)))
        if np.isfinite(r.prelim):
            rows.append((*key, METRIC_PRECIP_PRELIM, float(r.prelim)))
    rows += _origin_aggregate_rows(commodity, gold, cells, BASINS if basins is None else basins,
                                   production, production_lag_days, absent)
    absences = [{"commodity": c, "basin": b, "metric": m, "reason": why, "months": n}
                for (c, b, m, why), n in sorted(absent.items())]
    return _emit(rows), absences


# ── THE KNOWN DATE (WX-2, data repairs 2026-09-29) ─────────────────────────────────────────────────
# WHAT WAS WRONG. gold_weather_z declares ``knowledge_semantics: year_month`` with no knowledge column
# and no lag, and its notes said nothing about when a month becomes known -- so an as-of-2026-04-15
# page printed APRIL 2026's basin max-temperature tail share (0.0909), a figure that could not exist
# until the month had ended and NASA POWER had published it. The (year, month) of a row is the DATA
# month; the store must say when that month became known.
#
# THE RULE: known date = the last day of (year, month) + the publication lag of the SOURCE PRODUCT
# behind the metric, as DECLARED per source in configs/datasets/source_contracts.yaml (the task reads
# it; nothing is typed here). An aggregate takes the MAX over its weather inputs. The FAOSTAT weight
# never moves a row later: its year is chosen released by the month's last day. A metric fed by
# FAOSTAT alone (the weight rows) is therefore known at the month's last day. The map is built from
# the SAME expressions that build the names, so a new family cannot arrive without a source: the deck
# asserts it covers every name this module emits.
#
# CHIRPS PRELIM, stated rather than hidden: a month whose ``*_is_preliminary`` stamp is 1 was stored
# earlier (the prelim month completes ~+2 d past month-end, worst +4, documented in
# source_contracts.yaml but NOT declared as a field) and is RECOMPUTED when the FINAL block lands
# (+11..+16 observed). The declared ``weather:chirps`` lag (25) is the final's horizon, so a read that
# bounds on it is late, never early, and by then the stored value is the final.
SOURCE_NASA_POWER = "weather:nasa_power"
SOURCE_CHIRPS = "weather:chirps"
SOURCE_FAOSTAT = "production:faostat"

_CELL_METRIC_SOURCES: dict[str, tuple[str, ...]] = {
    METRIC_TMAX_ANOMALY: (SOURCE_NASA_POWER,),
    METRIC_GDD_Z: (SOURCE_NASA_POWER,),
    METRIC_HEAT_STRESS_Z: (SOURCE_NASA_POWER,),
    METRIC_FROST_FLAG: (SOURCE_NASA_POWER,),
    METRIC_DROUGHT_Z: (SOURCE_CHIRPS,),
    METRIC_DROUGHT_PRELIM: (SOURCE_CHIRPS,),
    METRIC_PRECIP_TOTAL: (SOURCE_CHIRPS,),
    METRIC_PRECIP_NORMAL: (SOURCE_CHIRPS,),
    METRIC_PRECIP_PCT: (SOURCE_CHIRPS,),
    METRIC_PRECIP_PRELIM: (SOURCE_CHIRPS,),
}


def _build_metric_sources() -> dict[str, tuple[str, ...]]:
    src = dict(_CELL_METRIC_SOURCES)
    for stem in Z_METRICS:
        src[f"{stem}{TAIL_SHARE_SUFFIX}"] = src[stem]
        src[f"{stem}{COUNTRY_MEAN_SUFFIX}"] = src[stem]
        src[f"{stem}{PROD_WEIGHTED_SUFFIX}"] = src[stem] + (SOURCE_FAOSTAT,)
    for stem in ALL_METRICS:
        src[f"{stem}{CELLS_SUFFIX}"] = src[stem]
    for stem, renamed in AGGREGATE_RENAMES.items():
        src[renamed] = src[stem]
    for name in (METRIC_PRECIP_PCT_COUNTRY, METRIC_PRECIP_PCT_BASIN, METRIC_PRECIP_PCT_CELLS,
                 METRIC_PRECIP_PRELIM_SHARE):
        src[name] = src[METRIC_PRECIP_PCT]
    src[METRIC_PRECIP_PCT_WEIGHTED] = src[METRIC_PRECIP_PCT] + (SOURCE_FAOSTAT,)
    src[METRIC_PRODUCTION_SHARE] = (SOURCE_FAOSTAT,)
    src[METRIC_PRODUCTION_SHARE_YEAR] = (SOURCE_FAOSTAT,)
    return src


METRIC_SOURCES: dict[str, tuple[str, ...]] = _build_metric_sources()


def known_date(metric: str, year: int, month: int, lag_days_by_source: dict) -> date | None:
    """The date the row ``(metric, year, month)`` became known: the month's last day plus the max
    DECLARED lag over the metric's weather sources (``lag_days_by_source``: source_key -> days).

    ``None`` when any of those lags is undeclared -- unknown, never zero. RAISES ``KeyError`` for a
    metric with no declared source: a name without an entry has no known date, and that is a defect
    of this map, not a row to guess about."""
    sources = METRIC_SOURCES[metric]
    horizon = _month_end(year, month)
    weather = [s for s in sources if s != SOURCE_FAOSTAT]
    if not weather:
        return horizon
    lags = [lag_days_by_source.get(s) for s in weather]
    if any(lag is None for lag in lags):
        return None
    return horizon + timedelta(days=max(int(lag) for lag in lags))


# ── freshness tripwire (2026-09-11) ─────────────────────────────────────────────────────────────────
# A MEASUREMENT, NOT A GATE. Nothing in this block is called from compute_weather_z or from any
# function it calls; it consumes a FINISHED gold frame and returns numbers. The z arithmetic above is
# untouched by construction, which is the whole of the lane's "tripwire only, never a behaviour
# change" mandate discharged structurally rather than by promise.
#
# WHY PER-METRIC AND NOT PER-TABLE. gold_weather_z is ONE parquet per commodity carrying five metrics
# fed by TWO independent sources: nasa_power (tmax_anomaly / gdd_z / heat_stress_z / frost_event_flag)
# and chirps (drought_z). MEASURED 2026-09-11: both halves were frozen at 202607, but the nasa half
# can be moved forward today and the chirps half cannot -- the source has published nothing after
# 2026-07-31. The moment the nasa half advances, four metrics tip at 202608 and drought_z at 202607
# inside one object under one table-level lag declaration; a table-grain counter would read the max,
# report "0 behind", and hide the drought hole exactly when it opens.

def metric_tip_ym(gold: "pd.DataFrame | None") -> dict:
    """The newest DATA MONTH present per metric, as ``year * 100 + month``.

    ``{metric: tip_ym}`` over whatever the frame actually holds -- an empty frame, a None, or a frame
    missing any of ``metric`` / ``year`` / ``month`` returns ``{}`` rather than raising, because this is
    telemetry and telemetry may not be the thing that fails a producer run. Rows whose year or month
    will not coerce to an integer are dropped from the measurement (they cannot be a tip of anything).

    MEASURED on the live object 2026-09-11 (gold/weather_z/corn_cbot.parquet, 45,002 rows): every one
    of the five metrics returned 202607, while the served card's own ``_ym_lagged_asof_ym(today, 7)``
    admitted 202608 -- the newest month the card PROMISES did not exist in the bytes, silently."""
    if gold is None or len(gold) == 0:
        return {}
    for col in ("metric", "year", "month"):
        if col not in gold.columns:
            return {}
    df = gold[["metric", "year", "month"]].copy()
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["month"] = pd.to_numeric(df["month"], errors="coerce")
    df = df.dropna(subset=["year", "month"])
    if df.empty:
        return {}
    df["ym"] = df["year"].astype(int) * 100 + df["month"].astype(int)
    return {str(m): int(v) for m, v in df.groupby("metric")["ym"].max().items()}


def months_behind(claimed_ym: "int | None", actual_ym: "int | None") -> "int | None":
    """How many MONTHS the bytes lag the newest month their own card says is knowable.

    ``claimed_ym`` comes from the card's shipped arithmetic (``numbers.query._ym_lagged_asof_ym`` over
    ``ym_publication_lag_days``) -- this function invents no threshold and holds no calendar opinion of
    its own; it only differences two ``YYYYMM`` integers in month units, so 202609 against 202512 is 9,
    not 97. Either side ``None`` (nothing measured, or the card declares no lag) returns None: an
    unmeasured thing must read as absent, never as zero."""
    if claimed_ym is None or actual_ym is None:
        return None
    cy, cm = divmod(int(claimed_ym), 100)
    ay, am = divmod(int(actual_ym), 100)
    return (cy - ay) * 12 + (cm - am)
