"""THE ORIGIN TIER (WX-1) AND THE KNOWN DATE (WX-2) of gold_weather_z -- data repairs 2026-09-29.

WHAT WAS WRONG, MEASURED (data_repairs_0929/checks/chk_wx.py on the store's own copy). The cocoa page read
"wetter than usual" off the West Africa basin's drought_z of -0.92 for August 2026 -- the EQUAL-WEIGHT mean
of 11 cells (4 in Cameroon and Nigeria) of a dry-spell LENGTH z -- while Cote d'Ivoire, the origin that
sets the main crop, had 50.0 % of its 1991-2020 July rain and 75.5 % of August's, and Ghana 136.0 % of
August's. The store held no per-country mean, no rainfall metric and no production weight; and no
declaration said when a weather month becomes known (an as-of-2026-04-15 page printed April's value).

WHAT THIS DECK PINS. (1) The name rule: no new aggregate name is a name another grain carries at the
same surface (T-WX-1 / T-WX-2). (2) The served rows are untouched: ``compute_weather_z`` is compared
element-wise against the module at 7ba6803f (the tree the repair started from). (3) The arithmetic of
every new metric on synthetic frames -- the WMO normal period, the ratio of sums, the country means on
the legacy tier's own gate, the production weights and the weight year, and every FAIL-CLOSED path
(an unresolved member, an undeclared lag, a member with no value that month). (4) The known-date map
covers every name the module emits. (5) The task seams: the origin tier can never cost the served rows,
the production read is all-or-nothing, and the declared lags are read from the source contracts.
"""
from __future__ import annotations

import calendar
import importlib.util
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from leviathan.transforms.gold import weather_z as wz

_REPO = Path(__file__).resolve().parents[2]
_BASE_REF = "7ba6803f:src/leviathan/transforms/gold/weather_z.py"   # the tree WX-1 started from
_WA = {"west_africa": wz.BASINS["west_africa"]}


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────
def _chirps_month(country: str, region: str, year: int, month: int, daily_mm: float,
                  prelim: str | None = None, days: int | None = None) -> pd.DataFrame:
    n = calendar.monthrange(year, month)[1] if days is None else days
    df = pd.DataFrame({"country": country, "region": region, "year": year, "month": month,
                       "day": list(range(1, n + 1)), "variable": wz._PRECIP, "value": float(daily_mm)})
    if prelim is not None:
        df[wz._PRELIM_COL] = prelim
    return df


def _chirps_history(country: str, region: str, month: int, per_year_daily: dict[int, float],
                    prelim: str | None = None) -> pd.DataFrame:
    return pd.concat([_chirps_month(country, region, y, month, d, prelim=prelim)
                      for y, d in per_year_daily.items()], ignore_index=True)


def _cell(commodity: str, country: str, region: str, year: int, month: int, metric: str,
          value: float) -> tuple:
    return (commodity, wz.to_psd_surface(country), region, year, month, metric, value)


def _gold_with_basins(cell_rows: list[tuple], basins=None) -> pd.DataFrame:
    """A frame shaped like compute_weather_z's output: the cell rows, then the legacy aggregate rows."""
    cells = pd.DataFrame(cell_rows, columns=wz.GOLD_COLUMNS)
    extra = wz._basin_rows(cells, _WA if basins is None else basins)
    return pd.concat([cells, extra], ignore_index=True)


def _production(values: dict[tuple[str, int], float], areas: dict[str, str] | None = None) -> pd.DataFrame:
    areas = areas or {}
    rows = [{"country": areas.get(k, k.replace("_", " ").title()), "country_key": k,
             "metric": wz.FAOSTAT_PRODUCTION_METRIC, "unit": "t", "value": v, "year": y}
            for (k, y), v in values.items()]
    return pd.DataFrame(rows)


def _val(frame: pd.DataFrame, metric: str, country: str, year: int, month: int,
         region: str | None = None) -> float:
    sub = frame[(frame.metric == metric) & (frame.country == country) & (frame.year == year)
                & (frame.month == month)]
    if region is not None:
        sub = sub[sub.region == region]
    assert len(sub) == 1, f"expected one {metric} row for {country} {year}-{month}, got {len(sub)}"
    return float(sub.value.iloc[0])


# ── (1) THE NAME RULE ────────────────────────────────────────────────────────────────────────────────
class TestTheNameRule:
    def test_no_origin_name_is_a_card_bound_name(self):
        """ALL_METRICS | DERIVED_METRICS is the card's contract (test_contract_check binds it both ways);
        the origin names must stay outside it until the card declares them."""
        assert set(wz.ORIGIN_METRICS).isdisjoint(set(wz.ALL_METRICS) | set(wz.DERIVED_METRICS))
        assert len(wz.ORIGIN_METRICS) == len(set(wz.ORIGIN_METRICS))

    def test_no_country_tier_name_is_a_cell_name(self):
        """T-WX-1: region is not a query filter, so a country-tier name shared with a cell name would be
        averaged into the country's own cells."""
        cell_names = set(wz.ALL_METRICS) | set(wz.ORIGIN_CELL_METRICS)
        assert set(wz.ORIGIN_COUNTRY_METRICS).isdisjoint(cell_names)

    def test_no_new_basin_name_is_a_legacy_basin_name(self):
        """T-WX-2: a weighted mean under an existing basin name would be averaged with the equal-weight
        one by a leg on the basin surface."""
        legacy_basin = set(wz.Z_METRICS) | set(wz.DERIVED_METRICS)
        assert set(wz.ORIGIN_BASIN_METRICS).isdisjoint(legacy_basin)

    def test_the_EMITTED_tiers_obey_the_rule_too(self):
        gold, _chirps, prod = _two_member_basin()
        origin, _ = wz.compute_origin_rows("cocoa", gold=gold, chirps=_chirps, production=prod,
                                           production_lag_days=0, basins=_WA,
                                           enforce_month_completeness=True, normal_min_years=3)
        out = pd.concat([gold, origin], ignore_index=True)
        is_country = out.region.str.endswith(wz.COUNTRY_TIER_SUFFIX)
        is_basin = out.region.str.endswith("_basin")
        cell = ~(is_country | is_basin)
        assert set(out[is_country].metric).isdisjoint(set(out[cell].metric))
        new_basin = set(origin[origin.region.str.endswith("_basin")].metric)
        assert new_basin and new_basin.isdisjoint(set(gold[gold.region.str.endswith("_basin")].metric))
        assert set(origin.metric) <= set(wz.ORIGIN_METRICS)
        key = ["commodity", "country", "region", "year", "month", "metric"]
        assert not out.duplicated(subset=key).any()


# ── (2) THE SERVED ROWS ARE UNTOUCHED ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def base_weather_z(tmp_path_factory):
    """weather_z.py at 7ba6803f, imported beside the tree's module."""
    try:
        src = subprocess.run(["git", "show", _BASE_REF], cwd=_REPO, capture_output=True, text=True,
                             check=True).stdout
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"git show {_BASE_REF} unavailable: {exc}")
    path = tmp_path_factory.mktemp("wx_base") / "weather_z_base_7ba6803f.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("weather_z_base_7ba6803f", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["weather_z_base_7ba6803f"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _synthetic_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(7)
    nasa, chirps = [], []
    for country, region in (("cameroon", "c1"), ("cameroon", "c2"), ("ghana", "g1"),
                            ("cote_divoire", "i1"), ("ecuador", "e1")):
        for year in range(1990, 2027):
            for month in (7, 8):
                n = calendar.monthrange(year, month)[1]
                days = list(range(1, n + 1))
                tmax = 28 + rng.normal(0, 2, n)
                tmin = 18 + rng.normal(0, 2, n)
                rain = np.clip(rng.gamma(0.8, 6.0, n) - 2.0, 0, None)
                nasa.append(pd.DataFrame({"country": country, "region": region, "year": year,
                                          "month": month, "day": days * 2,
                                          "variable": [wz._TMAX] * n + [wz._TMIN] * n,
                                          "value": np.concatenate([tmax, tmin])}))
                chirps.append(pd.DataFrame({"country": country, "region": region, "year": year,
                                            "month": month, "day": days, "variable": wz._PRECIP,
                                            "value": rain}))
    return pd.concat(nasa, ignore_index=True), pd.concat(chirps, ignore_index=True)


class TestTheServedRowsAreUntouched:
    def test_compute_weather_z_is_ELEMENT_WISE_the_7ba6803f_transform(self, base_weather_z):
        nasa, chirps = _synthetic_inputs()
        now = wz.compute_weather_z("cocoa", nasa_power=nasa, chirps=chirps)
        then = base_weather_z.compute_weather_z("cocoa", nasa_power=nasa, chirps=chirps)
        pd.testing.assert_frame_equal(now, then, check_exact=True)
        assert len(now) > 0 and "West Africa" in set(now.country)

    def test_the_origin_tier_APPENDS_and_never_edits(self):
        nasa, chirps = _synthetic_inputs()
        gold = wz.compute_weather_z("cocoa", nasa_power=nasa, chirps=chirps)
        snapshot = gold.copy(deep=True)
        prod = _production({(k, y): v for k, v in (("cameroon", 3.0), ("ghana", 5.0),
                                                    ("cote_divoire", 12.0)) for y in range(1980, 2026)})
        origin, _ = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                           production_lag_days=365)
        pd.testing.assert_frame_equal(gold, snapshot, check_exact=True)   # the input is only read
        assert list(origin.columns) == wz.GOLD_COLUMNS and len(origin) > 0
        key = ["commodity", "country", "region", "year", "month", "metric"]
        both = pd.concat([gold, origin], ignore_index=True)
        assert not both.duplicated(subset=key).any()


# ── (3) THE ARITHMETIC ───────────────────────────────────────────────────────────────────────────────
class TestTheNormalPeriod:
    @pytest.mark.parametrize("year, period", [
        (2026, (1991, 2020)), (2021, (1991, 2020)), (2020, (1981, 2010)), (2011, (1981, 2010)),
        (2010, (1971, 2000)), (2001, (1971, 2000)), (2000, (1961, 1990)), (1991, (1961, 1990)),
    ])
    def test_the_WMO_period_in_force(self, year, period):
        assert wz.normal_period(year) == period

    def test_the_period_always_ends_BEFORE_the_month_year(self):
        for year in range(1950, 2100):
            lo, hi = wz.normal_period(year)
            assert hi < year and hi - lo + 1 == wz.NORMAL_PERIOD_YEARS


class TestTheCellTier:
    def test_total_normal_and_share_of_normal(self):
        # July 1991-2020: daily 2.0 mm in even years, 4.0 in odd -> totals 62 / 124 -> normal 93.
        hist = {y: (2.0 if y % 2 == 0 else 4.0) for y in range(1991, 2021)}
        hist[2026] = 1.5                                            # 46.5 mm -> 50 % of 93
        chirps = _chirps_history("cote_divoire", "soubre", 7, hist)
        out, _ = wz.compute_origin_rows("cocoa", gold=pd.DataFrame(columns=wz.GOLD_COLUMNS),
                                        chirps=chirps, basins={})
        assert _val(out, wz.METRIC_PRECIP_TOTAL, "Cote Divoire", 2026, 7) == pytest.approx(46.5)
        assert _val(out, wz.METRIC_PRECIP_NORMAL, "Cote Divoire", 2026, 7) == pytest.approx(93.0)
        assert _val(out, wz.METRIC_PRECIP_PCT, "Cote Divoire", 2026, 7) == pytest.approx(50.0)

    def test_a_month_before_enough_normal_years_has_a_total_and_NO_share(self):
        chirps = _chirps_history("ghana", "g1", 7, {y: 3.0 for y in range(1981, 1995)})
        out, _ = wz.compute_origin_rows("cocoa", gold=pd.DataFrame(columns=wz.GOLD_COLUMNS),
                                        chirps=chirps, basins={})
        # 1990: the period in force is 1951-1980 and CHIRPS holds none of it -> no normal.
        # 1991: the period is 1961-1990, of which 1981-1990 is held = 10 years -> a normal.
        assert set(out[out.year == 1990].metric) == {wz.METRIC_PRECIP_TOTAL}
        assert _val(out, wz.METRIC_PRECIP_PCT, "Ghana", 1991, 7) == pytest.approx(100.0)

    def test_a_partial_month_is_never_a_monthly_metric(self):
        """'September so far' is not stored: the table's complete-months rule binds the new metric."""
        hist = pd.concat([_chirps_history("ghana", "g1", 9, {y: 3.0 for y in range(1991, 2021)}),
                          _chirps_month("ghana", "g1", 2026, 9, 0.5, days=25)], ignore_index=True)
        out, _ = wz.compute_origin_rows("cocoa", gold=pd.DataFrame(columns=wz.GOLD_COLUMNS),
                                        chirps=hist, basins={})
        assert out[(out.year == 2026)].empty

    def test_the_prelim_stamp_rides_only_when_the_column_does(self):
        base = {y: 3.0 for y in range(1991, 2021)}
        with_col = pd.concat([_chirps_history("ghana", "g1", 8, base, prelim="0"),
                              _chirps_month("ghana", "g1", 2026, 8, 3.0, prelim="1")], ignore_index=True)
        out, _ = wz.compute_origin_rows("cocoa", gold=pd.DataFrame(columns=wz.GOLD_COLUMNS),
                                        chirps=with_col, basins={})
        assert _val(out, wz.METRIC_PRECIP_PRELIM, "Ghana", 2026, 8) == 1.0
        assert _val(out, wz.METRIC_PRECIP_PRELIM, "Ghana", 2020, 8) == 0.0
        without = _chirps_history("ghana", "g1", 8, {**base, 2026: 3.0})
        out2, _ = wz.compute_origin_rows("cocoa", gold=pd.DataFrame(columns=wz.GOLD_COLUMNS),
                                         chirps=without, basins={})
        assert wz.METRIC_PRECIP_PRELIM not in set(out2.metric)

    def test_NASA_precipitation_never_feeds_the_rain_metrics(self):
        """nasa_power's wide frame melts precipitation_mm too; the rain metrics read CHIRPS only."""
        out, _ = wz.compute_origin_rows("cocoa", gold=pd.DataFrame(columns=wz.GOLD_COLUMNS),
                                        chirps=None, basins={})
        assert out.empty


def _two_member_basin(*, ghana_cells: int = 1, cam_cells: int = 2):
    """Cameroon (2 cells) + Ghana (1 cell) on West Africa, a z metric per cell at 2026-08 and a July
    rainfall history 1991-2026 per cell; production for both, 1990-2025."""
    rows = []
    cam = [("cameroon", f"c{i}") for i in range(1, cam_cells + 1)]
    gha = [("ghana", f"g{i}") for i in range(1, ghana_cells + 1)]
    zvals = {"c1": 1.0, "c2": 3.0, "c3": 5.0, "g1": -1.0, "g2": 0.0}
    for country, region in cam + gha:
        rows.append(_cell("cocoa", country, region, 2026, 8, wz.METRIC_TMAX_ANOMALY, zvals[region]))
    gold = _gold_with_basins(rows)
    daily = {"c1": 2.0, "c2": 6.0, "c3": 4.0, "g1": 3.0, "g2": 3.0}
    frames = []
    for country, region in cam + gha:
        hist = {y: daily[region] for y in range(1991, 2021)}
        frames.append(_chirps_history(country, region, 8, hist))
        frames.append(_chirps_month(country, region, 2026, 8, daily[region] * (0.5 if country == "cameroon" else 1.5)))
    chirps = pd.concat(frames, ignore_index=True)
    prod = _production({(k, y): v for k, v in (("cameroon", 1.0), ("ghana", 3.0)) for y in range(1990, 2026)})
    return gold, chirps, prod


class TestTheCountryAndBasinTiers:
    def test_the_country_mean_sits_EXACTLY_where_the_legacy_tail_share_does(self):
        gold, chirps, prod = _two_member_basin()
        origin, _ = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                           production_lag_days=0, basins=_WA)
        key = ["commodity", "country", "region", "year", "month"]
        tail = gold[gold.metric == "tmax_anomaly_tail_share"]
        tail = tail[tail.region.str.endswith(wz.COUNTRY_TIER_SUFFIX)][key]
        mean = origin[origin.metric == "tmax_anomaly_country_mean"][key]
        assert sorted(map(tuple, tail.values)) == sorted(map(tuple, mean.values))
        assert _val(origin, "tmax_anomaly_country_mean", "Cameroon", 2026, 8) == pytest.approx(2.0)
        assert _val(origin, "tmax_anomaly_country_mean", "Ghana", 2026, 8) == pytest.approx(-1.0)

    def test_the_country_share_of_normal_is_a_RATIO_OF_SUMS(self):
        gold, chirps, prod = _two_member_basin()
        origin, _ = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                           production_lag_days=0, basins=_WA)
        # Cameroon: c1 normal 62, 2026 = 31; c2 normal 186, 2026 = 93 -> (31+93)/(62+186) = 50 %
        # (the mean of the cell ratios is also 50 here: pin a case where they DIFFER below)
        assert _val(origin, wz.METRIC_PRECIP_PCT_COUNTRY, "Cameroon", 2026, 8) == pytest.approx(50.0)
        assert _val(origin, wz.METRIC_PRECIP_PCT_CELLS, "Cameroon", 2026, 8) == 2.0
        # basin: (31 + 93 + 139.5) / (62 + 186 + 93) = 263.5 / 341
        assert _val(origin, wz.METRIC_PRECIP_PCT_BASIN, "West Africa", 2026, 8) == \
            pytest.approx(100.0 * 263.5 / 341.0)

    def test_ratio_of_sums_and_mean_of_ratios_DIFFER_and_the_sum_is_the_one_stored(self):
        cam = pd.concat([
            _chirps_history("cameroon", "c1", 8, {**{y: 1.0 for y in range(1991, 2021)}, 2026: 2.0}),
            _chirps_history("cameroon", "c2", 8, {**{y: 9.0 for y in range(1991, 2021)}, 2026: 4.5}),
            _chirps_history("ghana", "g1", 8, {**{y: 3.0 for y in range(1991, 2021)}, 2026: 3.0}),
        ], ignore_index=True)
        gold = _gold_with_basins([_cell("cocoa", c, r, 2026, 8, wz.METRIC_TMAX_ANOMALY, 0.1)
                                  for c, r in (("cameroon", "c1"), ("cameroon", "c2"), ("ghana", "g1"))])
        origin, _ = wz.compute_origin_rows("cocoa", gold=gold, chirps=cam, basins=_WA)
        # cells 200 % and 50 %: the mean of ratios is 125; the ratio of sums is (62+139.5)/(31+279) = 65
        got = _val(origin, wz.METRIC_PRECIP_PCT_COUNTRY, "Cameroon", 2026, 8)
        assert got == pytest.approx(100.0 * (62.0 + 139.5) / (31.0 + 279.0))
        assert got != pytest.approx(125.0)

    def test_the_weights_sum_to_one_and_the_weighted_row_is_their_dot_product(self):
        gold, chirps, prod = _two_member_basin()
        origin, absences = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                                  production_lag_days=0, basins=_WA)
        w_cam = _val(origin, wz.METRIC_PRODUCTION_SHARE, "Cameroon", 2026, 8)
        w_gha = _val(origin, wz.METRIC_PRODUCTION_SHARE, "Ghana", 2026, 8)
        assert w_cam + w_gha == pytest.approx(1.0, abs=1e-12)
        assert (w_cam, w_gha) == pytest.approx((0.25, 0.75))
        assert _val(origin, wz.METRIC_PRODUCTION_SHARE_YEAR, "Ghana", 2026, 8) == 2025.0
        assert _val(origin, "tmax_anomaly_prod_weighted", "West Africa", 2026, 8) == \
            pytest.approx(0.25 * 2.0 + 0.75 * -1.0)
        assert _val(origin, wz.METRIC_PRECIP_PCT_WEIGHTED, "West Africa", 2026, 8) == \
            pytest.approx(0.25 * 50.0 + 0.75 * 150.0)
        # the equal-weight basin row is still what it was, beside the weighted one
        assert _val(gold, wz.METRIC_TMAX_ANOMALY, "West Africa", 2026, 8) == pytest.approx(1.0)
        assert absences == []

    def test_the_weight_year_is_the_latest_RELEASED_by_the_month_end(self):
        gold, chirps, prod = _two_member_basin()
        # lag 365 d: FAOSTAT 2025 is released 2026-12-31 (after 2026-08-31) -> 2024 is used;
        # 2024-12-31 + 365 = 2025-12-31 <= 2026-08-31.
        origin, _ = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                           production_lag_days=365, basins=_WA)
        assert _val(origin, wz.METRIC_PRODUCTION_SHARE_YEAR, "Cameroon", 2026, 8) == 2024.0
        w = wz._weights_for_month(2026, 8, {"a": {2025: 1.0, 2024: 1.0}}, [2024, 2025], 608)
        assert w[0] == 2024                         # 2025-12-31 + 608 d = 2027-08-31 > 2026-08-31
        w = wz._weights_for_month(2026, 8, {"a": {2025: 1.0, 2024: 1.0}}, [2024, 2025], 243)
        assert w[0] == 2025                         # 2025-12-31 + 243 d = 2026-08-31, ON the horizon


class TestEveryFailClosedPath:
    def test_an_UNDECLARED_lag_means_no_weights_and_says_so(self):
        gold, chirps, prod = _two_member_basin()
        origin, absences = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                                  production_lag_days=None, basins=_WA)
        assert not {wz.METRIC_PRODUCTION_SHARE, "tmax_anomaly_prod_weighted",
                    wz.METRIC_PRECIP_PCT_WEIGHTED} & set(origin.metric)
        assert absences and all("UNDECLARED" in a["reason"] for a in absences)
        # the unweighted tiers do not depend on the weights
        assert "tmax_anomaly_country_mean" in set(origin.metric)
        assert wz.METRIC_PRECIP_PCT_COUNTRY in set(origin.metric)

    def test_a_member_that_resolves_to_NO_FAOSTAT_row_fails_the_basin_closed(self):
        gold, chirps, _ = _two_member_basin()
        prod = _production({("cameroon", 2025): 1.0, ("ghana_republic_of", 2025): 3.0})
        origin, absences = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                                  production_lag_days=0, basins=_WA)
        assert wz.METRIC_PRODUCTION_SHARE not in set(origin.metric)
        assert any("'ghana' matches no FAOSTAT country_key" in a["reason"] for a in absences)

    def test_a_member_key_naming_TWO_areas_fails_closed(self):
        gold, chirps, _ = _two_member_basin()
        prod = pd.concat([
            _production({("cameroon", 2025): 1.0, ("ghana", 2025): 3.0}),
            _production({("ghana", 2024): 3.0}, areas={"ghana": "Ghana (former)"}),
        ], ignore_index=True)
        _o, absences = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                              production_lag_days=0, basins=_WA)
        assert any("matches 2 FAOSTAT areas" in a["reason"] for a in absences)

    def test_a_member_with_no_value_in_the_weight_year_is_NEVER_renormalised_away(self):
        gold, chirps, _ = _two_member_basin()
        prod = _production({("cameroon", 2025): 1.0, ("ghana", 2025): float("nan"),
                            ("ghana", 2024): 3.0, ("cameroon", 2024): 1.0})
        origin, absences = wz.compute_origin_rows("cocoa", gold=gold, chirps=chirps, production=prod,
                                                  production_lag_days=0, basins=_WA)
        assert "tmax_anomaly_prod_weighted" not in set(origin.metric)
        assert any("FAOSTAT 2025 carries no production value for ['ghana']" in a["reason"]
                   for a in absences)

    def test_a_member_with_no_cells_for_a_metric_that_month_leaves_the_weighted_row_ABSENT(self):
        """The lat-50 shape: a member present on the basin with no cells for ONE metric. The weighted
        row is absent -- a mean over the members that happen to have cells is not the basin."""
        rows = [_cell("cocoa", c, r, 2026, 8, wz.METRIC_TMAX_ANOMALY, 1.0)
                for c, r in (("cameroon", "c1"), ("cameroon", "c2"), ("ghana", "g1"))]
        rows += [_cell("cocoa", "cameroon", r, 2026, 8, wz.METRIC_DROUGHT_Z, 0.5) for r in ("c1", "c2")]
        gold = _gold_with_basins(rows)
        prod = _production({("cameroon", 2025): 1.0, ("ghana", 2025): 3.0})
        origin, absences = wz.compute_origin_rows("cocoa", gold=gold, production=prod,
                                                  production_lag_days=0, basins=_WA)
        assert "tmax_anomaly_prod_weighted" in set(origin.metric)
        assert "drought_z_prod_weighted" not in set(origin.metric)
        assert any(a["metric"] == "drought_z_prod_weighted" and "['Ghana']" in a["reason"]
                   for a in absences)

    def test_a_single_member_commodity_gets_no_aggregate_origin_rows(self):
        rows = [_cell("cocoa", "ghana", r, 2026, 8, wz.METRIC_TMAX_ANOMALY, 1.0) for r in ("g1", "g2")]
        gold = _gold_with_basins(rows)
        origin, _ = wz.compute_origin_rows("cocoa", gold=gold, basins=_WA,
                                           production=_production({("ghana", 2025): 1.0}),
                                           production_lag_days=0)
        assert origin.empty

    def test_the_live_basins_share_no_member_so_the_weight_owner_rule_never_fires(self):
        seen: dict[str, str] = {}
        for basin, spec in wz.BASINS.items():
            for m in spec["members"]:
                assert m not in seen, f"{m} is in {seen.get(m)} and {basin}"
                seen[m] = basin


# ── (4) THE KNOWN DATE (WX-2) ────────────────────────────────────────────────────────────────────────
def _declared_lags() -> dict[str, int | None]:
    doc = yaml.safe_load((_REPO / "configs" / "datasets" / "source_contracts.yaml").read_text(encoding="utf-8"))
    return {s["source_key"]: s.get("publication_lag_days") for s in doc["sources"]}


class TestTheKnownDate:
    def test_the_source_map_covers_EXACTLY_every_name_the_module_emits(self):
        emitted = set(wz.ALL_METRICS) | set(wz.DERIVED_METRICS) | set(wz.ORIGIN_METRICS)
        assert set(wz.METRIC_SOURCES) == emitted

    def test_every_source_named_is_a_declared_source_contract(self):
        declared = _declared_lags()
        for sources in wz.METRIC_SOURCES.values():
            for s in sources:
                assert s in declared, s

    def test_the_D6a_case_April_is_NOT_known_on_April_15(self):
        """The as-of-2026-04-15 page printed April 2026's basin tail share. Under the declared rule
        April's NASA-fed rows are known on 2026-05-03 (month end + the declared 3 days)."""
        lags = _declared_lags()
        kd = wz.known_date("tmax_anomaly_tail_share", 2026, 4, lags)
        assert kd == date(2026, 4, 30) + timedelta(days=int(lags[wz.SOURCE_NASA_POWER]))
        assert kd > date(2026, 4, 15)
        assert wz.known_date("tmax_anomaly_tail_share", 2026, 3, lags) <= date(2026, 4, 15)

    def test_each_source_carries_its_own_lag_and_an_aggregate_the_max(self):
        lags = {wz.SOURCE_NASA_POWER: 3, wz.SOURCE_CHIRPS: 25, wz.SOURCE_FAOSTAT: 400}
        assert wz.known_date("drought_z", 2026, 8, lags) == date(2026, 9, 25)
        assert wz.known_date("precip_pct_normal_country", 2026, 8, lags) == date(2026, 9, 25)
        assert wz.known_date("gdd_z_country_mean", 2026, 8, lags) == date(2026, 9, 3)
        # the weight never moves a row later (its year is released by the month's end)
        assert wz.known_date("drought_z_prod_weighted", 2026, 8, lags) == date(2026, 9, 25)
        assert wz.known_date("production_share", 2026, 8, lags) == date(2026, 8, 31)

    def test_an_undeclared_lag_is_UNKNOWN_never_zero_and_an_unmapped_name_raises(self):
        assert wz.known_date("drought_z", 2026, 8, {wz.SOURCE_NASA_POWER: 3}) is None
        with pytest.raises(KeyError):
            wz.known_date("some_future_metric", 2026, 8, {})


# ── (5) THE TASK SEAMS ───────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def task():
    from jobs.batch import gold_weather_z_task as mod
    return mod


class TestTheTaskSeams:
    def test_an_origin_failure_costs_nothing_of_the_served_rows(self, task, monkeypatch):
        gold = pd.DataFrame([_cell("cocoa", "ghana", "g1", 2026, 8, "tmax_anomaly", 1.0)],
                            columns=wz.GOLD_COLUMNS)

        def _boom(*a, **k):
            raise RuntimeError("origin tier bug")
        monkeypatch.setattr(task, "compute_origin_rows", _boom)
        out = task._with_origin_tier("cocoa", gold, None, None, {})
        pd.testing.assert_frame_equal(out, gold)

    def test_the_origin_rows_ride_AFTER_the_served_rows(self, task):
        gold, chirps, prod = _two_member_basin()
        out = task._with_origin_tier("cocoa", gold, chirps, prod, {wz.SOURCE_FAOSTAT: 0})
        pd.testing.assert_frame_equal(out.iloc[:len(gold)].reset_index(drop=True), gold)
        assert set(out.iloc[len(gold):].metric) <= set(wz.ORIGIN_METRICS)

    def test_the_declared_lags_are_READ_not_typed(self, task, tmp_path):
        got = task._declared_source_lags()
        declared = _declared_lags()
        assert set(got) == {s for v in wz.METRIC_SOURCES.values() for s in v}
        for key, lag in got.items():
            assert lag == declared.get(key), key
        p = tmp_path / "sc.yaml"
        p.write_text("sources:\n  - source_key: weather:chirps\n    publication_lag_days: 9\n",
                     encoding="utf-8")
        assert task._declared_source_lags(p) == {wz.SOURCE_CHIRPS: 9, wz.SOURCE_NASA_POWER: None,
                                                 wz.SOURCE_FAOSTAT: None}
        assert set(task._declared_source_lags(tmp_path / "missing.yaml").values()) == {None}

    def test_the_production_read_is_ALL_OR_NOTHING(self, task, monkeypatch):
        keys = [f"silver/production/commodity=cocoa/year={y}/part-000.parquet" for y in (2023, 2024)]
        monkeypatch.setattr(task, "list_s3_keys", lambda *a, **k: keys)
        monkeypatch.setattr(task, "get_thread_local_s3_client", lambda region: object())
        buf = __import__("io").BytesIO()
        _production({("ghana", 0): 1.0}).drop(columns=["year"]).to_parquet(buf, index=False)

        def _get(bucket, key, s3):
            if "2024" in key:
                raise IOError("transient")
            return buf.getvalue()
        monkeypatch.setattr(task, "s3_download_with_retry", _get)
        assert task._read_production("B", "cocoa", "us-east-1") is None
        monkeypatch.setattr(task, "s3_download_with_retry", lambda b, k, s: buf.getvalue())
        frame = task._read_production("B", "cocoa", "us-east-1")
        assert sorted(frame.year.unique()) == [2023, 2024]

    def test_the_production_prefix_carries_its_trailing_slash(self, task):
        assert task._production_prefix("cocoa") == "silver/production/commodity=cocoa/"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
