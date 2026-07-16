"""Numbers SQL agent — deterministic leakage-safe query layer (pure; no AWS).

The anti-leakage property test is load-bearing: it proves the point-in-time filter can NEVER surface a value
published after `asof` — the single correctness property the whole numbers layer rests on.
"""
from __future__ import annotations

import random

from leviathan.graphrag.numbers.query import NumberQuery, apply_pit_filter, build_sql
from leviathan.graphrag.numbers.registry import Metric, TableSpec, VintageTiebreakTerm, load_registry


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
    # BF-W2 R3: market_year is IN the grain — the same week rides under BOTH current and next MY in
    # every weekly vintage; without it the latest-vintage ROW_NUMBER collapse merges the two MYs.
    assert reg.get("silver_esr").grain_cols == ["commodity_name", "market_year",
                                                "country_code", "week_ending_date"]
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


# ── D-W0.1: the query.py country-clobber fix (a caller-resolved country on a country-PARTITION table used to
#    be discarded for geo's snake_case default for the DEFAULTED primary region — DARK legs) ────────────────
def _country_part() -> TableSpec:
    """A country-PARTITION table (the D-W0.1 clobber class): country is an injected-projection partition, so
    its value goes through _partition_filters — where a caller-resolved country used to be clobbered by the
    geo default. commodity=corn_cbot has a geographies config (primary us_corn_iowa -> united_states), so the
    geo default (united_states) is DISTINCT from an explicit non-US country and the clobber is observable."""
    return TableSpec(id="silver_nasa_power", description="", shape="wide", commodity_col="commodity",
                     country_col="country", period_type="date", date_col="date",
                     knowledge_semantics="data_date", partition_cols=["commodity", "country"])


def test_partition_country_explicit_country_wins_over_geo_default():
    # (a) explicit country + NO region: the caller's country must survive, canonicalised to the snake
    # partition form — the clobber emitted geo's default (corn_cbot -> 'united_states') instead.
    sql = build_sql(NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2024-06-01",
                                commodity="corn_cbot", country="Brazil"), _country_part())
    assert "country = 'brazil'" in sql                          # honored (snake), not clobbered
    assert "country = 'united_states'" not in sql               # the geo default no longer wins unconditionally


def test_partition_country_explicit_region_wins_over_country():
    # (b) explicit region is the finer key: its geography country wins over a model country string (the July
    # 'us' numbers-agent fix must NOT regress).
    sql = build_sql(NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2024-06-01",
                                commodity="corn_cbot", region="us_corn_iowa", country="Brazil"), _country_part())
    assert "country = 'united_states'" in sql                   # region-derived; model's 'Brazil' ignored
    assert "country = 'brazil'" not in sql


def test_partition_country_geo_default_when_neither_pinned():
    # (c) neither region nor country -> geo's country for the primary region (unchanged behavior).
    sql = build_sql(NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2024-06-01",
                                commodity="corn_cbot"), _country_part())
    assert "country = 'united_states'" in sql


def test_partition_country_build_sql_pit_filter_parity():
    # (d) build_sql's emitted country predicate and apply_pit_filter must select the SAME row for all three
    # preference cases — the anti-leakage oracle stays in lockstep with the fix (shared _resolved_country).
    ts = _country_part()
    rows = [{"commodity": "corn_cbot", "country": "brazil", "date": "2024-05-01", "precipitation_mm": 5.0},
            {"commodity": "corn_cbot", "country": "united_states", "date": "2024-05-01", "precipitation_mm": 9.0}]
    base = dict(table="silver_nasa_power", metric="precipitation_mm", asof="2024-06-01", commodity="corn_cbot")
    cases = ((NumberQuery(country="Brazil", **base), "brazil"),                            # (a)
             (NumberQuery(region="us_corn_iowa", country="Brazil", **base), "united_states"),  # (b)
             (NumberQuery(**base), "united_states"))                                        # (c)
    for spec, want in cases:
        sql = build_sql(spec, ts)
        assert f"country = '{want}'" in sql                     # build_sql selects it ...
        kept = apply_pit_filter(rows, spec, ts)
        assert [r["country"] for r in kept] == [want]           # ... and the oracle keeps exactly that row


# ── D-W0.3: ESR publication-lag PIT offset (a week is citable only once week_ending_date + 7d <= asof —
#    USDA publishes ~7 days after the reporting week; C3/adversarial finding) ────────────────────────────────
def _esr_compact_lag() -> TableSpec:
    """The compact serving shape WITH the D-W0.3 publication-lag guard (publication_lag_days=7)."""
    return TableSpec(id="silver_esr", description="", athena_table="silver_esr_compact", shape="wide",
                     commodity_col="commodity_name", period_col="market_year", period_type="marketing_year",
                     period_sql_type="int", period_offset=1, date_col="week_ending_date",
                     knowledge_date_col="as_of_date", knowledge_semantics="data_date",
                     partition_cols=["commodity"], publication_lag_days=7,
                     grain_cols=["commodity_name", "country_code", "week_ending_date"])


def test_esr_publication_lag_shifts_guard_and_stays_sargable():
    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2024-03-25",
                                commodity="corn_cbot", agg="latest"), _esr_compact_lag())
    # the cutoff is shifted back 7 days (2024-03-25 -> 2024-03-18): a week is citable only once it was
    # PUBLISHED (week_ending_date + 7d <= asof), bound as the equivalent week_ending_date <= asof-7d.
    assert "CAST(week_ending_date AS varchar) <= '2024-03-18'" in sql
    assert "'2024-03-25'" not in sql                            # the raw (pre-publication) cutoff never appears
    assert "commodity = 'corn_cbot'" in sql                     # partition equality intact ...
    assert "CAST(commodity " not in sql and "INTERVAL" not in sql   # ... never wrapped: sargable, no date-math on
    #                                                                 the column, so no LIST-storm surface


def test_esr_publication_lag_boundary_excludes_unpublished_week():
    """D-W0.3 / D-W3.5.6: a week whose data date passed but which USDA has NOT yet published
    (week_ending_date <= asof < week_ending_date + 7d) is EXCLUDED; it becomes citable exactly at
    week_ending_date + 7d; a plainly-future week stays excluded."""
    ts = _esr_compact_lag()
    q = dict(table="silver_esr", metric="weekly_exports_1000mt", commodity="corn_cbot")
    row = [{"commodity_name": "corn_cbot", "country_code": 9, "week_ending_date": "2024-03-16",
            "as_of_date": "20240323", "weekly_exports_1000mt": 800.0}]           # published ~2024-03-23
    assert apply_pit_filter(row, NumberQuery(asof="2024-03-20", **q), ts) == []  # data date passed, NOT yet public
    assert apply_pit_filter(row, NumberQuery(asof="2024-03-22", **q), ts) == []  # still one day before publication
    kept = apply_pit_filter(row, NumberQuery(asof="2024-03-23", **q), ts)        # publication date reached
    assert len(kept) == 1 and kept[0]["week_ending_date"] == "2024-03-16"
    future = [{"commodity_name": "corn_cbot", "country_code": 9, "week_ending_date": "2024-04-06",
               "as_of_date": "20240413", "weekly_exports_1000mt": 810.0}]
    assert apply_pit_filter(future, NumberQuery(asof="2024-03-23", **q), ts) == []   # plain future week excluded


def test_publication_lag_zero_is_identity_for_other_tables():
    # every non-ESR table defaults publication_lag_days=0 -> the guard cutoff is the raw asof (no regression).
    sql = build_sql(NumberQuery(table="silver_fred_fx", metric="brl_usd", asof="2024-06-01", agg="latest"), _fx())
    assert "CAST(date AS varchar) <= '2024-06-01'" in sql       # unshifted; _fx() has no publication_lag_days


# ── BF-W2 SILVER-F031 option-b: the ESR vintage semantics flip (laneA R2/R3/R4). silver_esr_compact
#    retains one object per (slug, as_of_date) weekly vintage; as-of truth = latest vintage <= asof. ────────
def _esr_vintage() -> TableSpec:
    """The post-flip serving shape (mirrors the live tables.yaml silver_esr entry)."""
    return TableSpec(id="silver_esr", description="", athena_table="silver_esr_compact", shape="wide",
                     commodity_col="commodity_name", period_col="market_year", period_type="marketing_year",
                     period_sql_type="int", period_offset=1, date_col="week_ending_date",
                     knowledge_date_col="as_of_date", knowledge_semantics="vintage",
                     vintage_partition_col="as_of_date", vintage_partition_format="yyyyMMdd",
                     partition_cols=["commodity"],
                     grain_cols=["commodity_name", "market_year", "country_code", "week_ending_date"])


def test_esr_registry_declares_vintage_semantics_lag_zero():
    # the LIVE registry entry carries the BF-W2 flip: per-week vintage, YYYYMMDD-format guard, no +7d
    # data_date lag (R4: under vintage semantics the as_of stamp IS the publication event — a retained
    # lag would DOUBLE-withhold the freshest published week).
    ts = load_registry().get("silver_esr")
    assert ts.knowledge_semantics == "vintage"
    assert ts.publication_lag_days == 0
    assert ts.vintage_partition_col == "as_of_date" and ts.vintage_partition_format == "yyyyMMdd"
    assert ts.vintage_dates_real is False        # write-date backfill vintage: date bounds stay canary-banned
    assert "market_year" in ts.grain_cols        # R3


def test_esr_vintage_guard_is_sargable_and_format_correct():
    """R2 lexical-format trap: as_of_date values are YYYYMMDD but asof is ISO. The guard MUST compile
    natively in the partition's own value format — the naive `as_of_date <= '2026-07-14'` is lexically
    FALSE against every '2026xxxx' vintage (zero rows), and a CAST would defeat partition pruning once
    as_of_date becomes a registered partition key."""
    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-07-14",
                                commodity="corn_cbot", period="2025", agg="sum"), _esr_vintage())
    assert "as_of_date <= '20260714'" in sql                    # native YYYYMMDD compare
    assert "as_of_date <= '2026-07-14'" not in sql              # the lexically-false ISO form never appears
    assert "CAST(as_of_date" not in sql                         # never wrapped: sargable on the partition col
    assert "ROW_NUMBER() OVER" in sql and "as_of_date DESC" in sql   # as-known latest-vintage collapse


def test_esr_vintage_rownumber_partitions_on_market_year():
    # R3 in SQL: the dedup identity group carries market_year, so the same week under two MYs
    # yields TWO surviving rows, not one arbitrary winner.
    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-07-14",
                                commodity="corn_cbot"), _esr_vintage())
    assert "PARTITION BY commodity_name, market_year, country_code, week_ending_date" in sql


def test_esr_same_week_two_marketing_years_survive_dedup():
    """R3 fixture: a weekly vintage carries the SAME week under the current and the next MY.
    Both rows must survive the latest-vintage collapse (the pre-fix grain merged them)."""
    ts = _esr_vintage()
    rows = [{"commodity_name": "corn_cbot", "market_year": 2026, "country_code": 9,
             "week_ending_date": "2026-07-03", "as_of_date": "20260712", "weekly_exports_1000mt": 700.0},
            {"commodity_name": "corn_cbot", "market_year": 2027, "country_code": 9,
             "week_ending_date": "2026-07-03", "as_of_date": "20260712", "weekly_exports_1000mt": 55.0}]
    kept = apply_pit_filter(rows, NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                              asof="2026-07-14", commodity="corn_cbot"), ts)
    assert sorted(r["market_year"] for r in kept) == [2026, 2027]   # BOTH MYs kept
    # and the vintage collapse itself still works per (week, MY): a newer vintage supersedes.
    rows.append({"commodity_name": "corn_cbot", "market_year": 2026, "country_code": 9,
                 "week_ending_date": "2026-07-03", "as_of_date": "20260719", "weekly_exports_1000mt": 710.0})
    kept = apply_pit_filter(rows, NumberQuery(table="silver_esr", metric="weekly_exports_1000mt",
                                              asof="2026-07-20", commodity="corn_cbot"), ts)
    by_my = {r["market_year"]: r for r in kept}
    assert by_my[2026]["as_of_date"] == "20260719" and by_my[2027]["as_of_date"] == "20260712"


def test_esr_lag_zero_freshest_vintage_citable_at_publication():
    """R4: with lag=0 under vintage semantics, a week published in the as_of=20260712 vintage is
    citable the moment asof reaches the vintage date — the old data_date+7d guard would have hidden
    it until week_ending + 7d (the double-withhold)."""
    ts = _esr_vintage()
    row = [{"commodity_name": "corn_cbot", "market_year": 2026, "country_code": 9,
            "week_ending_date": "2026-07-03", "as_of_date": "20260712", "weekly_exports_1000mt": 742.5}]
    q = dict(table="silver_esr", metric="weekly_exports_1000mt", commodity="corn_cbot")
    assert apply_pit_filter(row, NumberQuery(asof="2026-07-11", **q), ts) == []     # vintage not yet out
    kept = apply_pit_filter(row, NumberQuery(asof="2026-07-12", **q), ts)           # publication day
    assert len(kept) == 1 and kept[0]["weekly_exports_1000mt"] == 742.5
    sql = build_sql(NumberQuery(asof="2026-07-13", **q), ts)
    assert "as_of_date <= '20260713'" in sql                    # unshifted cutoff (no -7d)
    assert "'20260706'" not in sql and "'2026-07-06'" not in sql   # the double-withheld cutoff never appears


def test_esr_vintage_agg_latest_keeps_freshest_week_lock():
    """agg=latest on the vintage branch keeps the single-freshest-observation contract (the D-W3.1
    pace leg's C2 stale-week lock): ORDER BY the data axis DESC ... LIMIT 1 AFTER the vintage
    dedup. The outer query exposes ALIASES only, so the ordering MUST use the alias (data_date) --
    the raw column name is COLUMN_NOT_FOUND on both Athena and Postgres (live-caught at the BF-W2
    step-11 serving smoke gate; the pre-fix assertion here pinned the buggy raw-column form)."""
    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-07-14",
                                commodity="corn_cbot", period_start="2025-07-14",
                                period_end="2026-07-14", agg="latest"), _esr_vintage())
    assert "ORDER BY data_date DESC" in sql and sql.strip().endswith("LIMIT 1")
    outer = sql.rsplit(") AS _v", 1)[1]                         # everything after the dedup subquery
    assert "week_ending_date" not in outer                      # raw column never leaks into outer scope
    assert "ROW_NUMBER() OVER" in sql                           # dedup still applied first
    assert "CAST(week_ending_date AS varchar) <= '2026-07-14'" in sql   # window guard on the data axis intact


def test_esr_vintage_agg_latest_sql_executes_end_to_end():
    """EXECUTE the generated vintage+latest SQL on a real engine (stdlib sqlite3: window functions +
    alias scoping rules match Athena/PG here). A string assertion cannot catch outer-scope alias bugs
    -- this is the regression net for the step-11 live failure. Two vintages x two weeks: the query
    must return exactly the freshest week of the LATEST vintage visible at asof."""
    import sqlite3

    sql = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-07-14",
                                commodity="corn_cbot", agg="latest"), _esr_vintage())
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH ':memory:' AS leviathan_dev")
    con.execute("""CREATE TABLE leviathan_dev.silver_esr_compact (
        commodity_name TEXT, market_year INT, country_code INT, week_ending_date TEXT,
        weekly_exports_1000mt REAL, as_of_date TEXT, commodity TEXT)""")
    rows = [
        ("corn_cbot", 2026, 9, "2026-05-15", 500.0, "20260524", "corn_cbot"),
        ("corn_cbot", 2026, 9, "2026-05-22", 510.0, "20260524", "corn_cbot"),
        ("corn_cbot", 2026, 9, "2026-05-15", 501.0, "20260712", "corn_cbot"),  # revised by the newer vintage
        ("corn_cbot", 2026, 9, "2026-07-02", 640.0, "20260712", "corn_cbot"),  # the freshest week
    ]
    con.executemany("INSERT INTO leviathan_dev.silver_esr_compact VALUES (?,?,?,?,?,?,?)", rows)
    got = con.execute(sql).fetchall()                           # raises on any outer-scope column bug
    assert len(got) == 1
    assert got[0][0] == 640.0                                   # value = freshest week, latest vintage
    # and at an asof BEFORE the second vintage, the first vintage's freshest week wins
    sql_pit = build_sql(NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-06-01",
                                    commodity="corn_cbot", agg="latest"), _esr_vintage())
    got = con.execute(sql_pit).fetchall()
    assert len(got) == 1 and got[0][0] == 510.0


def test_vintage_agg_latest_without_order_col_unchanged():
    # PSD/WASDE (vintage, no date_col) keep the plain deduped-set shape under agg=latest — the
    # freshest-week lock applies only where a chronological data axis exists.
    sql = build_sql(NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof="2024-02-15",
                                commodity="corn", country="Brazil", period="2023", agg="latest"), _psd())
    assert not sql.strip().endswith("LIMIT 1")
    assert "ROW_NUMBER() OVER" in sql and "_rn = 1" in sql


# ── F2 (silver_rebuild_gate Branch-A parity): the WASDE role-priority vintage tiebreak. The F2 rebuild put
#    the F036 columns (estimate_role/projection_month/source_table_id, all silver `string`) physically into
#    every silver_wasde partition. Early-era releases (1985-1999) carry MULTIPLE estimate_role rows per numbers
#    grain at ONE release_date, so the release_date-only latest-vintage ROW_NUMBER TIES and pg-vs-Athena break
#    the tie by engine order (value flip-flops). A deterministic role-priority tiebreak restores parity. ──────
def _wasde_tiebreak() -> TableSpec:
    """silver_wasde WITH the F2 role-priority vintage tiebreak (mirrors the live tables.yaml entry): within a
    grain the pick is release_date DESC, then role rank (actual < estimate < projection), then projection_month
    DESC NULLS LAST, then source_table_id ASC — a total order identical on Athena and the pg mirror."""
    return TableSpec(id="silver_wasde", description="", shape="tall", commodity_col="commodity",
                     country_col="region", period_col="marketing_year", period_type="marketing_year",
                     period_sql_type="string", knowledge_date_col="release_date",
                     knowledge_semantics="vintage", metric_col="attribute", value_col="estimate",
                     unit_col="unit", vintage_partition_col="release_date", vintage_partition_format="iso",
                     vintage_dates_real=True,
                     grain_cols=["commodity", "table_type", "region", "marketing_year", "attribute"],
                     vintage_tiebreak=[
                         VintageTiebreakTerm(col="estimate_role",
                                             role_order=["actual", "estimate", "projection"]),
                         VintageTiebreakTerm(col="projection_month", dir="desc", nulls="last"),
                         VintageTiebreakTerm(col="source_table_id", dir="asc")])


def _wasde_multirole_rows() -> list[dict]:
    """ONE grain (corn / balance_sheet / united_states / 1986/87 / ending_stocks), ONE release_date, three
    rows differing ONLY by estimate_role — the early-era multi-role shape that ties the release_date-only pick."""
    grain = dict(commodity="corn", table_type="balance_sheet", region="united_states",
                 marketing_year="1986/87", attribute="ending_stocks", release_date="1986-05-09", unit="1000 MT")
    return [
        {**grain, "estimate_role": "projection", "estimate": 300.0, "projection_month": "05", "source_table_id": "ws_p"},
        {**grain, "estimate_role": "estimate", "estimate": 200.0, "projection_month": "", "source_table_id": "ws_e"},
        {**grain, "estimate_role": "actual", "estimate": 100.0, "projection_month": "", "source_table_id": "ws_a"},
    ]


def test_wasde_registry_declares_role_tiebreak():
    ts = load_registry().get("silver_wasde")
    tb = ts.vintage_tiebreak
    assert [t.col for t in tb] == ["estimate_role", "projection_month", "source_table_id"]
    assert tb[0].role_order == ["actual", "estimate", "projection"]   # actual (rank 0) wins the tie
    assert tb[1].dir == "desc" and tb[1].nulls == "last"             # projection_month DESC NULLS LAST
    assert tb[2].dir == "asc" and tb[2].role_order == []             # source_table_id ASC (final total order)
    # every OTHER vintage table carries NO tiebreak -> its generated SQL stays byte-identical (zero change).
    for tid in ("silver_psd", "silver_esr", "silver_production", "silver_fred_fx",
                "silver_noaa_oni", "gold_weather_z"):
        assert load_registry().get(tid).vintage_tiebreak == []


def test_wasde_role_tiebreak_in_generated_sql_both_engines():
    # build_sql is BACKEND-AGNOSTIC: the ONE string it returns runs on BOTH pg and Athena (run() only picks the
    # executor), so this single assertion covers both engines' ordering. Role rank + explicit dirs/NULLS force
    # a deterministic total order; the tiebreak cols are silver `string` == pg TEXT COLLATE "C" == Presto order.
    sql = build_sql(NumberQuery(table="silver_wasde", metric="ending_stocks", asof="1986-12-31",
                                commodity="corn", country="united_states", period="1986/87"), _wasde_tiebreak())
    assert ("ORDER BY release_date DESC, CASE estimate_role WHEN 'actual' THEN 0 WHEN 'estimate' THEN 1 "
            "WHEN 'projection' THEN 2 ELSE 3 END ASC, projection_month DESC NULLS LAST, "
            "source_table_id ASC") in sql
    assert "ROW_NUMBER() OVER (PARTITION BY commodity, table_type, region, marketing_year, attribute" in sql


def test_tiebreak_absent_spec_is_byte_identical_window():
    # a wasde-shaped spec WITHOUT vintage_tiebreak must emit the PRE-FIX window verbatim (release_date DESC
    # only) — the byte-identical guarantee for every table that does not set the key.
    q = NumberQuery(table="silver_wasde", metric="ending_stocks", asof="2024-05-31", commodity="corn",
                    period="2023/24")
    no_tb = build_sql(q, _wasde_projected())                          # existing helper: no vintage_tiebreak
    window = no_tb.split("ORDER BY", 1)[1].split(") AS _rn")[0].strip()
    assert window == "release_date DESC"                              # exactly the old ordering, no CASE/terms
    assert "CASE" not in no_tb
    # and PSD (no tiebreak in the live registry) never grows a CASE rank either.
    psd = build_sql(NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof="2024-02-15",
                                commodity="corn", country="Brazil", period="2023"),
                    load_registry().get("silver_psd"))
    assert "CASE" not in psd and "ROW_NUMBER() OVER (PARTITION BY" in psd


def test_wasde_multirole_tiebreak_picks_actual_oracle():
    # (pg-mirror semantics reference) apply_pit_filter must pick the 'actual' row from the tied multi-role grain.
    ts = _wasde_tiebreak()
    q = NumberQuery(table="silver_wasde", metric="ending_stocks", asof="1986-12-31", commodity="corn",
                    country="united_states", period="1986/87")
    kept = apply_pit_filter(_wasde_multirole_rows(), q, ts)
    assert len(kept) == 1
    assert kept[0]["estimate_role"] == "actual" and kept[0]["estimate"] == 100.0


def test_wasde_multirole_tiebreak_picks_actual_sql_executes():
    # EXECUTE the generated SQL on a real engine (stdlib sqlite3: CASE + window ORDER BY + NULLS LAST match
    # Athena/PG here) — a string assertion cannot prove the tie actually resolves to 'actual'. Rows inserted
    # projection-first to prove the pick is order-independent.
    import sqlite3
    sql = build_sql(NumberQuery(table="silver_wasde", metric="ending_stocks", asof="1986-12-31",
                                commodity="corn", country="united_states", period="1986/87"), _wasde_tiebreak())
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH ':memory:' AS leviathan_dev")
    con.execute("""CREATE TABLE leviathan_dev.silver_wasde (
        commodity TEXT, table_type TEXT, region TEXT, marketing_year TEXT, attribute TEXT,
        estimate REAL, release_date TEXT, estimate_role TEXT, projection_month TEXT,
        source_table_id TEXT, unit TEXT)""")
    order = ["commodity", "table_type", "region", "marketing_year", "attribute", "estimate",
             "release_date", "estimate_role", "projection_month", "source_table_id", "unit"]
    con.executemany("INSERT INTO leviathan_dev.silver_wasde VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r[c] for c in order) for r in _wasde_multirole_rows()])
    got = con.execute(sql).fetchall()
    assert len(got) == 1
    assert got[0][0] == 100.0                                         # value column = actual's estimate


def test_wasde_modern_single_role_unaffected():
    # REGRESSION: a modern grain carries ONE estimate_role ('actual') per release across TWO release_dates.
    # Recency still dominates (latest release_date wins) and the role tiebreak is a no-op — exactly the
    # pre-F036 behavior. Checked on BOTH the SQL engine and the oracle.
    import sqlite3
    ts = _wasde_tiebreak()
    q = NumberQuery(table="silver_wasde", metric="ending_stocks", asof="2024-06-30", commodity="corn",
                    country="united_states", period="2023/24")
    base = dict(commodity="corn", table_type="balance_sheet", region="united_states",
                marketing_year="2023/24", attribute="ending_stocks", unit="1000 MT",
                estimate_role="actual", projection_month="", source_table_id="ws1")
    rows = [{**base, "release_date": "2024-05-10", "estimate": 50.0},
            {**base, "release_date": "2024-06-12", "estimate": 55.0}]   # newest vintage -> wins
    sql = build_sql(q, ts)
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH ':memory:' AS leviathan_dev")
    con.execute("""CREATE TABLE leviathan_dev.silver_wasde (
        commodity TEXT, table_type TEXT, region TEXT, marketing_year TEXT, attribute TEXT,
        estimate REAL, release_date TEXT, estimate_role TEXT, projection_month TEXT,
        source_table_id TEXT, unit TEXT)""")
    order = ["commodity", "table_type", "region", "marketing_year", "attribute", "estimate",
             "release_date", "estimate_role", "projection_month", "source_table_id", "unit"]
    con.executemany("INSERT INTO leviathan_dev.silver_wasde VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r[c] for c in order) for r in rows])
    got = con.execute(sql).fetchall()
    assert len(got) == 1 and got[0][0] == 55.0                       # latest release_date, unchanged by tiebreak
    kept = apply_pit_filter(rows, q, ts)                             # oracle agrees
    assert len(kept) == 1 and kept[0]["estimate"] == 55.0
