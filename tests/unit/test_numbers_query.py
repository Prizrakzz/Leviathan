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
        assert f"CAST({ts.knowledge_col()} AS varchar) <= '2024-03-01'" in sql   # leakage guard, type-agnostic


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
    assert "sum(value)" in sql and "CAST(date AS varchar) >= '2024-01-01'" in sql and "precipitation_mm AS value" in sql


def test_date_guard_is_type_agnostic_no_raw_date_compare():
    # regression: silver_nasa_power.date is a true DATE type; a raw `date <= 'YYYY-MM-DD'` guard threw Athena
    # TYPE_MISMATCH ("Cannot apply operator: date <= varchar"). The guard/window must compare AS TEXT.
    sql = build_sql(NumberQuery(table="silver_nasa_power", metric="temperature_2m_max_c", asof="2012-08-01",
                                commodity="corn_cbot", country="United States", agg="latest"), _weather())
    assert "CAST(date AS varchar) <= '2012-08-01'" in sql             # guard casts -> works on a DATE column
    assert " date <= '2012-08-01'" not in sql                          # never the bare (TYPE_MISMATCH) form


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
    assert "as_of_date DESC" in sql and "CAST(as_of_date AS varchar) <= '2024-03-25'" in sql


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
    assert "brl_usd AS value" in sql and "CAST(date AS varchar) <= '2024-06-01'" in sql
    # native chrono col DESC first, then the deterministic total-order tiebreak (engine-parity, 2026-07-05)
    assert "ORDER BY date DESC, " in sql and sql.strip().endswith("LIMIT 1")


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


def _weather_part() -> TableSpec:                          # wide + data_date + REQUIRED injected partition
    return TableSpec(id="silver_nasa_power", description="", shape="wide", commodity_col="commodity",
                     country_col="country", period_type="date", date_col="date", knowledge_semantics="data_date",
                     partition_cols=["commodity", "country", "region"])


def test_partition_required_emits_static_equality():
    # regression: silver_nasa_power uses injected partition projection on `region` — Athena rejects any query
    # without a static `region = '...'` (CONSTRAINT_VIOLATION). Explicit region wins; else the commodity default.
    sql = build_sql(NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2012-08-01",
                                commodity="corn_cbot", region="us_corn_illinois", agg="latest"), _weather_part())
    assert "region = 'us_corn_illinois'" in sql


def test_partition_default_region_from_geographies():
    from leviathan.graphrag.numbers.query import default_region
    assert default_region("corn_cbot") == "us_corn_iowa"        # first primary-country station in the config
    sql = build_sql(NumberQuery(table="silver_nasa_power", metric="temperature_2m_max_c", asof="2012-08-01",
                                commodity="corn_cbot", agg="latest"), _weather_part())
    assert "region = 'us_corn_iowa'" in sql                     # default resolved when region omitted
    assert "country = 'united_states'" in sql                  # country derived from the region block (snake)


def test_partition_required_without_resolvable_region_raises():
    import pytest
    with pytest.raises(ValueError, match="requires commodity"):      # commodity is itself a partition column
        build_sql(NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2012-08-01"),
                  _weather_part())
    with pytest.raises(ValueError, match="static region equality"):  # commodity without a geographies config
        build_sql(NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2012-08-01",
                              commodity="no_such_commodity", country="united_states"), _weather_part())


def test_partition_country_normalized_to_snake():
    # the S3 layout stores country as snake_case ('united_states'); the agent says 'United States' — 0 rows
    # unless normalized. Confirmed live: united_states -> 16071 rows, 'United States' -> 0.
    sql = build_sql(NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2012-08-01",
                                commodity="corn_cbot", country="United States", agg="latest"), _weather_part())
    assert "country = 'united_states'" in sql and "country = 'United States'" not in sql


def test_partition_country_derived_from_region_overrides_model_string():
    # July-3 b_weather_2012: the model emitted country='us'; the partition value is 'united_states'.
    # When the region is in the geographies map, the map's country is authoritative.
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    ts = reg.get("silver_nasa_power")
    spec = Q.NumberQuery(table="silver_nasa_power", metric="precipitation_mm", commodity="corn_cbot",
                         country="us", region="us_corn_iowa", asof="2012-08-01")
    filters = Q._partition_filters(spec, ts)
    joined = " AND ".join(filters)
    assert "country = 'united_states'" in joined                    # region-derived, model's 'us' ignored
    assert "'us'" not in joined.replace("'united_states'", "").replace("'us_corn_iowa'", "")


def test_country_alias_canonicalization_when_region_unmapped():
    from leviathan.graphrag.numbers import query as Q
    assert Q._canon_country("us") == "united_states"
    assert Q._canon_country("USA") == "united_states"
    assert Q._canon_country("United States") == "united_states"
    assert Q._canon_country("Brazil") == "brazil"                   # pass-through for normal names
    assert Q._canon_country(None) is None


# ── projection-enumeration guards (Jul-2026 S3 LIST storm: $134 of ListBucket in 2 days) ──────────────
def _esr_projected() -> TableSpec:
    """The production silver_esr shape: as_of_date is a PROJECTED string partition (yyyyMMdd) spanning
    1990->NOW; commodity_code is a projected int partition. Without sargable bounds, one query = ~130-600K
    S3 LISTs (measured 26-31s Athena planning time)."""
    return TableSpec(id="silver_esr", description="", shape="wide", commodity_col="commodity_name",
                     period_col="market_year", period_type="marketing_year", period_sql_type="int",
                     period_offset=1, date_col="week_ending_date", knowledge_date_col="as_of_date",
                     knowledge_semantics="data_date",
                     grain_cols=["commodity_name", "country_code", "week_ending_date"],
                     vintage_partition_col="as_of_date", vintage_partition_format="yyyyMMdd",
                     commodity_code_col="commodity_code", commodity_codes={"corn_cbot": 401})


def _esr_compact() -> TableSpec:
    """The PRODUCTION serving shape post-fix: the agent-facing id stays silver_esr but SQL targets
    silver_esr_compact (registered Glue partitions, one file per commodity, no projection anywhere)."""
    return TableSpec(id="silver_esr", description="", athena_table="silver_esr_compact", shape="wide",
                     commodity_col="commodity_name", period_col="market_year",
                     period_type="marketing_year", period_sql_type="int", period_offset=1,
                     date_col="week_ending_date", knowledge_date_col="as_of_date",
                     knowledge_semantics="data_date", partition_cols=["commodity"],
                     grain_cols=["commodity_name", "country_code", "week_ending_date"])


def test_esr_serves_from_compact_table_with_partition_pruning():
    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2013-03-01",
                                commodity="corn_cbot", period="2012", agg="sum"), _esr_compact())
    assert "FROM leviathan_dev.silver_esr_compact" in sql           # physical table swapped in
    assert "commodity = 'corn_cbot'" in sql                         # registered-partition equality (1 file)
    assert "commodity_name = 'corn_cbot'" in sql                    # identity filter rides along
    assert "market_year = 2013" in sql                              # END-label equality (offset +1)
    assert "CAST(week_ending_date AS varchar) <= '2013-03-01'" in sql   # PIT guard unchanged
    assert "as_of_date >=" not in sql and "as_of_date <=" not in sql    # no vintage-axis bounds


def test_projected_table_machinery_bands_market_year_only():
    """If a spec ever points at a PROJECTED table again, the machinery bands the MY axis for
    latest/window queries and NEVER emits (or casts) as_of_date bounds — the 2026-07-04 canary
    proved date windows are semantically wrong for latest-snapshot-per-MY storage (the whole
    backfilled history sits under the snapshot WRITE date)."""
    ts = _esr_projected()
    latest = build_sql(NumberQuery(table="silver_esr", metric="outstanding_sales_1000mt",
                                   asof="2024-05-31", commodity="corn_cbot", agg="latest"), ts)
    assert "market_year BETWEEN 2023 AND 2025" in latest            # MY axis collapsed 46 -> 3
    assert "commodity_code = 401" in latest                         # projected code pruned
    assert "as_of_date >=" not in latest and "as_of_date <=" not in latest
    assert "CAST(as_of_date" not in latest                          # never cast a projected partition col
    window = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2013-03-01",
                                   commodity="corn_cbot", period_start="2012-06-01",
                                   period_end="2012-09-01", agg="series"), ts)
    assert "market_year BETWEEN 2012 AND 2014" in window


def test_esr_unmapped_slug_skips_code_pruning_but_scopes_rows():
    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2013-03-01",
                                commodity="all_wheat", period="2012", agg="sum"), _esr_projected())
    assert "commodity_code" not in sql                              # unmapped -> no code pruning ...
    assert "commodity_name = 'all_wheat'" in sql                    # ... but rows still scoped by name


def test_unprojected_tables_are_unchanged():
    sql = build_sql(NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof="2024-02-15",
                                commodity="corn", period="2023"), _psd())
    assert "as_of_date" not in sql and "commodity_code" not in sql  # no bounds injected where none belong


def test_pit_oracle_ignores_cost_bounds():
    """The SQL snapshot-locator bounds are COST caps, not semantics: the oracle keeps rows the window
    would skip (bounded-staleness is documented), and the week_ending guard still rules."""
    ts = _esr_projected()
    rows = [{"commodity_name": "corn_cbot", "country_code": "1", "week_ending_date": "2012-08-30",
             "as_of_date": "20120906", "weekly_exports_1000mt": 500.0},
            {"commodity_name": "corn_cbot", "country_code": "1", "week_ending_date": "2013-06-06",
             "as_of_date": "20130613", "weekly_exports_1000mt": 700.0}]
    kept = apply_pit_filter(rows, NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                              asof="2013-03-01", commodity="corn_cbot"), ts)
    assert [r["week_ending_date"] for r in kept] == ["2012-08-30"]  # future week dropped, old snapshot kept


def test_athena_stats_summary_and_reset():
    from leviathan.graphrag.numbers import query as Q
    Q.reset_stats()
    assert Q.stats_summary() == {"n": 0}
    Q.STATS.extend([{"planning_ms": 100, "total_ms": 900, "scanned_bytes": 1_000_000},
                    {"planning_ms": 30_000, "total_ms": 200_000, "scanned_bytes": 500}])
    s = Q.stats_summary()
    assert s["n"] == 2 and s["planning_max_ms"] == 30_000 and s["planning_p50_ms"] == 100
    assert s["scanned_mb"] == 1.0
    Q.reset_stats()
    assert Q.stats_summary() == {"n": 0}


def test_athena_timeout_cancels_the_query(monkeypatch):
    """An enumeration-class query must be CANCELLED at the deadline, not left billing S3 LISTs."""
    from types import SimpleNamespace

    from leviathan.graphrag.numbers import query as Q
    monkeypatch.setenv("ATHENA_QUERY_TIMEOUT_S", "0")
    stopped = []
    client = SimpleNamespace(
        start_query_execution=lambda **kw: {"QueryExecutionId": "qid-1"},
        get_query_execution=lambda **kw: {"QueryExecution": {"Status": {"State": "RUNNING"}}},
        stop_query_execution=lambda **kw: stopped.append(kw["QueryExecutionId"]),
    )
    import pytest
    with pytest.raises(RuntimeError, match="cancelled"):
        Q._athena(client, "SELECT 1", "db")
    assert stopped == ["qid-1"]


def _wasde_projected() -> TableSpec:
    """silver_wasde: release_date is a PROJECTED string partition holding REAL monthly publication
    dates (461 real vs 19.5K daily candidates) — native guard + period lower bound are the pruning."""
    return TableSpec(id="silver_wasde", description="", shape="tall", commodity_col="commodity",
                     period_col="marketing_year", period_type="marketing_year", period_sql_type="string",
                     knowledge_date_col="release_date", knowledge_semantics="vintage",
                     metric_col="attribute", value_col="estimate", unit_col="unit",
                     vintage_partition_col="release_date", vintage_partition_format="iso",
                     vintage_dates_real=True)


def test_wasde_guard_is_native_and_period_bounds_the_grid():
    sql = build_sql(NumberQuery(table="silver_wasde", metric="Ending Stocks", asof="2024-05-31",
                                commodity="corn", period="2023/24"), _wasde_projected())
    assert "release_date <= '2024-05-31'" in sql                 # NATIVE sargable guard ...
    assert "CAST(release_date" not in sql                        # ... never the pruning-poison CAST
    assert "release_date >= '2023-01-01'" in sql                 # period-derived lower bound
    assert "marketing_year = '2023/24'" in sql


def test_wasde_no_period_keeps_native_guard_without_lower_bound():
    sql = build_sql(NumberQuery(table="silver_wasde", metric="Ending Stocks", asof="2013-06-01",
                                commodity="corn", agg="latest"), _wasde_projected())
    assert "release_date <= '2013-06-01'" in sql and "CAST(release_date" not in sql
    assert "release_date >=" not in sql                          # no period -> no date lower bound


def test_esr_write_date_vintages_never_get_date_bounds():
    """vintage_dates_real=False (ESR write-date snapshots): date bounds stay canary-banned."""
    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2013-03-01",
                                commodity="corn_cbot", period="2012", agg="sum"), _esr_projected())
    assert "as_of_date >=" not in sql and "as_of_date <=" not in sql


def test_registry_projection_lint_flags_unguarded_axes():
    from types import SimpleNamespace

    from leviathan.graphrag.numbers import lint as L

    def fake_get_table(DatabaseName, Name):
        params = {"projection.enabled": "true", "projection.release_date.type": "date",
                  "projection.release_date.range": "1973-01-01,NOW"} if Name == "silver_wasde" else {}
        return {"Table": {"Parameters": params}}

    glue = SimpleNamespace(get_table=fake_get_table)
    problems = L.lint_registry(glue)                             # live registry: wasde declares the col
    assert not [p for p in problems if "silver_wasde" in p]
    # now break the discipline: same projection, spec without coverage
    monkey_reg = L.load_registry()
    monkey_reg.tables["silver_wasde"].vintage_partition_col = None
    try:
        problems = L.lint_registry(glue)
        assert any("silver_wasde" in p and "release_date" in p for p in problems)
    finally:
        monkey_reg.tables["silver_wasde"].vintage_partition_col = "release_date"
