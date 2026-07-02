"""Numbers SQL agent — deterministic leakage-safe query layer (pure; no AWS).

The anti-leakage property test is load-bearing: it proves the point-in-time filter can NEVER surface a value
published after `asof` — the single correctness property the whole numbers layer rests on.
"""
from __future__ import annotations

import random

from leviathan.graphrag.numbers.query import NumberQuery, apply_pit_filter, build_sql
from leviathan.graphrag.numbers.registry import Metric, TableSpec, load_registry


def _psd() -> TableSpec:                                   # wide + vintage
    return TableSpec(id="silver_psd", description="", shape="wide", commodity_col="leviathan_slug",
                     country_col="country", period_col="market_year", period_type="marketing_year",
                     period_sql_type="int", knowledge_date_col="release_date", knowledge_semantics="vintage",
                     metrics={"ending_stocks_mt": Metric(unit="1000 MT")})


def _prod() -> TableSpec:                                  # tall + ingest
    return TableSpec(id="silver_production", description="", shape="tall", commodity_col="commodity",
                     country_col="country", period_col="year", period_type="year", period_sql_type="int",
                     knowledge_date_col="ingest_date", knowledge_semantics="ingest", metric_col="metric",
                     value_col="value", unit_col="unit")


def _weather() -> TableSpec:                               # wide + data_date
    return TableSpec(id="silver_nasa_power", description="", shape="wide", commodity_col="commodity",
                     country_col="country", period_type="date", date_col="date", knowledge_semantics="data_date")


def _esr() -> TableSpec:                                   # wide + vintage, keyed on the WEEK
    return TableSpec(id="silver_esr", description="", shape="wide", commodity_col="commodity_name",
                     period_col="market_year", period_type="marketing_year", period_sql_type="int",
                     date_col="week_ending_date", knowledge_date_col="as_of_date", knowledge_semantics="vintage",
                     grain_cols=["commodity_name", "country_code", "week_ending_date"])


def _fx() -> TableSpec:                                    # wide + data_date, macro (no commodity)
    return TableSpec(id="silver_fred_fx", description="", shape="wide", period_type="date", date_col="date",
                     knowledge_semantics="data_date")


def _oni() -> TableSpec:                                   # wide + year_month (no date column)
    return TableSpec(id="silver_noaa_oni", description="", shape="wide", period_type="date",
                     year_col="year", month_col="month", knowledge_semantics="year_month")


def test_guard_always_present_every_semantics():
    for ts, metric, extra in ((_psd(), "ending_stocks_mt", {"period": "2023"}),
                              (_prod(), "production", {"period": "2023"}),
                              (_weather(), "precipitation_mm", {"period_start": "2024-01-01", "period_end": "2024-03-01"})):
        sql = build_sql(NumberQuery(table=ts.id, metric=metric, asof="2024-03-01", commodity="corn", **extra), ts)
        assert f"{ts.knowledge_col()} <= '2024-03-01'" in sql          # the leakage guard, always injected


def test_vintage_sql_collapses_to_latest_known():
    sql = build_sql(NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof="2024-02-15",
                                commodity="corn", country="Brazil", period="2023"), _psd())
    assert "ROW_NUMBER() OVER" in sql and "release_date DESC" in sql and "_rn = 1" in sql


def test_wide_vs_tall_value_expr():
    wide = build_sql(NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof="2024-03-01"), _psd())
    tall = build_sql(NumberQuery(table="silver_production", metric="production", asof="2024-03-01"), _prod())
    assert "ending_stocks_mt AS value" in wide                          # wide: metric IS the column
    assert "value AS value" in tall and "metric = 'production'" in tall  # tall: metric is a row value


def test_weather_window_aggregate():
    sql = build_sql(NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2024-03-01",
                                commodity="soybeans", country="Brazil", period_start="2024-01-01",
                                period_end="2024-02-29", agg="sum"), _weather())
    assert "sum(value)" in sql and "date >= '2024-01-01'" in sql and "precipitation_mm AS value" in sql


def test_pit_vintage_returns_the_then_current_estimate():
    ts = _psd()
    rows = [{"leviathan_slug": "corn", "country": "Brazil", "market_year": 2023, "release_date": d, "ending_stocks_mt": v}
            for d, v in (("2024-01-10", 10.0), ("2024-02-08", 11.0), ("2024-03-08", 9.0))]
    q = dict(table="silver_psd", metric="ending_stocks_mt", commodity="corn", country="Brazil", period="2023")
    mid = apply_pit_filter(rows, NumberQuery(asof="2024-02-15", **q), ts)
    late = apply_pit_filter(rows, NumberQuery(asof="2024-03-20", **q), ts)
    assert len(mid) == 1 and mid[0]["release_date"] == "2024-02-08"     # the Feb vintage, not the (future) Mar one
    assert len(late) == 1 and late[0]["release_date"] == "2024-03-08"   # rolls forward as vintages publish


def test_pit_no_leakage_property():
    ts = _prod()
    rng = random.Random(7)
    rows = [{"commodity": "corn", "country": "US", "year": 2023, "metric": "production", "value": float(i),
             "ingest_date": f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"} for i in range(400)]
    for _ in range(50):
        asof = f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        spec = NumberQuery(table="silver_production", metric="production", asof=asof, commodity="corn",
                           country="US", period="2023")
        kept = apply_pit_filter(rows, spec, ts)
        assert all(r["ingest_date"] <= asof for r in kept)             # NEVER a value not yet known at asof
        assert all(r["ingest_date"] > asof for r in rows if r not in kept)  # ...and nothing valid was dropped


def test_esr_vintage_keys_on_week_not_marketing_year():
    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2024-03-25",
                                commodity="corn_cbot", period="2023"), _esr())
    assert "PARTITION BY commodity_name, country_code, week_ending_date" in sql   # grain = the WEEK, not the MY
    assert "as_of_date DESC" in sql and "as_of_date <= '2024-03-25'" in sql


def test_esr_pit_latest_report_per_week_no_leakage():
    ts = _esr()
    rows = [{"commodity_name": "corn_cbot", "country_code": 9, "week_ending_date": "2024-03-14",
             "as_of_date": d, "weekly_exports_1000mt": v}
            for d, v in (("2024-03-15", 790.0), ("2024-03-22", 800.0), ("2024-03-29", 810.0))]
    kept = apply_pit_filter(rows, NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                              asof="2024-03-25", commodity="corn_cbot"), ts)
    assert len(kept) == 1 and kept[0]["as_of_date"] == "2024-03-22"   # newest report KNOWN at asof (Mar-29 is future)
    assert kept[0]["weekly_exports_1000mt"] == 800.0


def test_fx_latest_is_single_most_recent():
    sql = build_sql(NumberQuery(table="silver_fred_fx", metric="brl_usd", asof="2024-06-01", agg="latest"), _fx())
    assert "brl_usd AS value" in sql and "date <= '2024-06-01'" in sql
    assert sql.strip().endswith("ORDER BY date DESC LIMIT 1")


def test_oni_year_month_guard_no_leakage():
    ts = _oni()
    sql = build_sql(NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2024-03-15", agg="latest"), ts)
    assert "(year * 100 + month) <= 202403" in sql
    rows = [{"year": 2024, "month": m, "oni_anom": 0.1 * m} for m in range(1, 13)]
    kept = apply_pit_filter(rows, NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2024-03-15"), ts)
    assert {r["month"] for r in kept} == {1, 2, 3}                    # Apr+ not yet known at mid-March


def test_rows_are_self_identifying():
    psd = build_sql(NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof="2024-06-01",
                                commodity="corn_cbot", country="Argentina", period="2023"), _psd())
    assert "market_year AS period" in psd                        # PSD row carries its marketing year
    oni = build_sql(NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2016-06-01",
                                period_start="2016-01", period_end="2016-03", agg="series"), _oni())
    assert "year AS year" in oni and "month AS month" in oni      # ONI row carries its year+month (was the 0.0 misread)


def test_oni_month_window():
    ts = _oni()
    sql = build_sql(NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2016-06-01",
                                period_start="2016-01", period_end="2016-03", agg="series"), ts)
    assert "(year * 100 + month) >= 201601" in sql and "(year * 100 + month) <= 201603" in sql
    rows = [{"year": 2016, "month": m, "oni_anom": 2.5 - 0.1 * m} for m in range(1, 13)]
    kept = apply_pit_filter(rows, NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2016-06-01",
                                              period_start="2016-01", period_end="2016-03"), ts)
    assert {r["month"] for r in kept} == {1, 2, 3}               # windowed to the requested months


def test_registry_yaml_loads():
    reg = load_registry()
    assert {"silver_psd", "silver_wasde", "silver_production", "silver_nasa_power",
            "silver_esr", "silver_fred_fx", "silver_noaa_oni"} <= set(reg.tables)
    assert reg.get("silver_psd").shape == "wide" and reg.get("silver_psd").knowledge_semantics == "vintage"
    assert reg.get("silver_wasde").shape == "tall" and reg.get("silver_wasde").metric_col == "attribute"
    assert reg.get("silver_esr").grain_cols == ["commodity_name", "country_code", "week_ending_date"]
    assert reg.get("silver_noaa_oni").knowledge_semantics == "year_month"
    assert reg.get("silver_psd").metrics["ending_stocks_mt"].unit == "MT"   # unit corrected from '1000 MT'
