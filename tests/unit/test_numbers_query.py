"""Numbers SQL agent — deterministic leakage-safe query layer (pure; no AWS).

The anti-leakage property test is load-bearing: it proves the point-in-time filter can NEVER surface a value
published after `asof` — the single correctness property the whole numbers layer rests on.
"""
from __future__ import annotations

import random

import pytest

from leviathan.graphrag.numbers import query as _Q
from leviathan.graphrag.numbers.query import NumberQuery, apply_pit_filter, build_sql
from leviathan.graphrag.numbers.registry import Metric, TableSpec, VintageTiebreakTerm, load_registry


@pytest.fixture(autouse=True)
def _clean_athena_stats():
    """Q.STATS is a MODULE GLOBAL the census banner counts (cascade_census `athena_calls`), so a test
    here that runs a query and leaves its stat behind fails test_cascade_census's `athena_calls == 0`
    assertion IN ANOTHER FILE, only when the suites share a process and this one runs first (verified
    on clean HEAD 4570ec35: the pairing fails, each file alone passes). Reset on both sides of every
    test so suite order never matters."""
    _Q.reset_stats()
    yield
    _Q.reset_stats()


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


# ---------------------------------------------------------------------------------------------
# S0 (D-FR-12) -- Athena NextToken pagination on the numbers executor.
#
# Before S0 the executor made ONE GetQueryResults call at MaxResults=1000 and dropped the rest.
# Page 1 spends one of those 1000 slots on the header row, so every read capped at 999 rows
# (MEASURED 2026-08-04: corn_cbot trade_year 2025 is 2,760 rows and _athena returned 999,
# stopping at 2025-05-09 with no error). These pins clone the coverage the house idiom at
# jobs/utils/athena_utils.py:70-103 earns: three pages, header on page 1 ONLY, token exhaustion.
# ---------------------------------------------------------------------------------------------

_PAGE_COLS = ("trade_date", "settle")


def _fake_athena(pages, *, fail_on_call=None):
    """An Athena stub that SUCCEEDS immediately and serves `pages` from get_query_results.

    `pages` is [(rows, next_token), ...] where rows are (trade_date, settle) tuples. Page 1 MUST
    carry the header row at index 0, exactly as the service returns it; later pages must NOT --
    that asymmetry is the whole defect surface. A NextToken of "tok-<i>" selects pages[i].

    `fail_on_call=(n, exc)` raises `exc` on the n-th get_query_results call so per-page _retry
    semantics can be pinned (a throttle on page 2 must replay page 2 ONLY).
    """
    from types import SimpleNamespace
    calls: list[dict] = []

    def get_query_results(**kw):
        calls.append(dict(kw))
        if fail_on_call and len(calls) == fail_on_call[0]:
            raise fail_on_call[1]
        idx = int(kw["NextToken"].split("-")[1]) if "NextToken" in kw else 0
        rows, nxt = pages[idx]
        out = {"ResultSet": {
            "ResultSetMetadata": {"ColumnInfo": [{"Name": c} for c in _PAGE_COLS]},
            "Rows": [{"Data": [{"VarCharValue": v} for v in r]} for r in rows]}}
        if nxt:
            out["NextToken"] = nxt
        return out

    client = SimpleNamespace(
        start_query_execution=lambda **kw: {"QueryExecutionId": "qid-1"},
        get_query_execution=lambda **kw: {"QueryExecution": {
            "Status": {"State": "SUCCEEDED"},
            "Statistics": {"QueryPlanningTimeInMillis": 11, "TotalExecutionTimeInMillis": 22,
                           "DataScannedInBytes": 33}}},
        get_query_results=get_query_results,
    )
    return client, calls


def _three_pages():
    """Page 1: header + 2 rows. Page 2: 2 rows, NO header. Page 3: 1 row, NO header, no token."""
    return [([_PAGE_COLS, ("2025-01-02", "459.5"), ("2025-01-03", "460.0")], "tok-1"),
            ([("2025-01-06", "461.0"), ("2025-01-07", "462.0")], "tok-2"),
            ([("2025-01-08", "463.0")], None)]


def test_athena_paginates_three_pages_and_skips_the_header_on_page_1_only():
    """Every real row from every page, in order, exactly once -- and the header never leaks.

    The bug a fresh implementation gets wrong is skipping row 0 of EVERY page, which silently eats
    one real row per page. Page 2 opens on 2025-01-06 and page 3 on 2025-01-08; both must survive.
    """
    from leviathan.graphrag.numbers import query as Q
    client, calls = _fake_athena(_three_pages())
    rows = Q._athena(client, "SELECT trade_date, settle FROM t", "db")
    assert [r["trade_date"] for r in rows] == ["2025-01-02", "2025-01-03", "2025-01-06",
                                               "2025-01-07", "2025-01-08"]
    assert [r["settle"] for r in rows] == ["459.5", "460.0", "461.0", "462.0", "463.0"]
    # the header row is DATA on the wire; if it leaked it would appear as a row of column names
    assert not any(r["trade_date"] == "trade_date" for r in rows)
    assert len(rows) == 5                                    # 5 real rows, not 3 (pre-S0) and not 6
    assert len(calls) == 3


def test_athena_pagination_token_exhaustion_stops_the_loop():
    """The loop ends when a page carries NO NextToken -- and pages 2..N carry the PREVIOUS page's."""
    from leviathan.graphrag.numbers import query as Q
    client, calls = _fake_athena(_three_pages())
    Q._athena(client, "SELECT 1", "db")
    assert len(calls) == 3                                   # exactly one call per page, no extra
    assert "NextToken" not in calls[0]                       # page 1 asks without a token
    assert [c.get("NextToken") for c in calls[1:]] == ["tok-1", "tok-2"]
    assert all(c["MaxResults"] == 1000 for c in calls)        # the API ceiling is still requested
    assert all(c["QueryExecutionId"] == "qid-1" for c in calls)


def test_athena_single_page_is_unchanged_by_pagination():
    """A one-page result is byte-identical to the pre-S0 behaviour: header dropped, one call."""
    from leviathan.graphrag.numbers import query as Q
    client, calls = _fake_athena([([_PAGE_COLS, ("2025-01-02", "459.5")], None)])
    rows = Q._athena(client, "SELECT 1", "db")
    assert rows == [{"trade_date": "2025-01-02", "settle": "459.5"}]
    assert len(calls) == 1


def test_athena_empty_result_set_returns_no_rows():
    """A header-only page yields [], not a row of column names."""
    from leviathan.graphrag.numbers import query as Q
    client, _ = _fake_athena([([_PAGE_COLS], None)])
    assert Q._athena(client, "SELECT 1", "db") == []


def test_athena_pagination_retries_the_FAILING_PAGE_ONLY(monkeypatch):
    """_retry wraps each page, not the loop: a throttle on page 2 must not replay page 1.

    Replaying the loop would duplicate page 1's rows; replaying the page returns them once.
    """
    import time as _time

    from botocore.exceptions import ClientError
    from leviathan.graphrag.numbers import query as Q
    monkeypatch.setattr(_time, "sleep", lambda *_a, **_k: None)
    throttle = ClientError({"Error": {"Code": "ThrottlingException"}}, "GetQueryResults")
    client, calls = _fake_athena(_three_pages(), fail_on_call=(2, throttle))
    rows = Q._athena(client, "SELECT 1", "db")
    assert [r["trade_date"] for r in rows] == ["2025-01-02", "2025-01-03", "2025-01-06",
                                               "2025-01-07", "2025-01-08"]
    assert len(calls) == 4                                   # 3 pages + 1 replay of page 2
    # the replay carried page 2's token, i.e. page 1 was NOT re-fetched
    assert calls[1].get("NextToken") == "tok-1" and calls[2].get("NextToken") == "tok-1"


def test_athena_pagination_preserves_stats_telemetry():
    """STATS is the S3-LIST-storm tripwire; it is stamped ONCE per query, not once per page."""
    from leviathan.graphrag.numbers import query as Q
    Q.reset_stats()
    client, _ = _fake_athena(_three_pages())
    Q._athena(client, "SELECT 1", "db")
    assert len(Q.STATS) == 1
    assert Q.STATS[0] == {"planning_ms": 11, "total_ms": 22, "scanned_bytes": 33}
    assert Q.stats_summary()["n"] == 1
    Q.reset_stats()


def test_athena_pagination_lifts_the_row_cap_past_999():
    """The regression pin for the defect itself: 1,500 rows across two pages must ALL return.

    Pre-S0 this returned 999 (page 1 minus the header) and the engine's `_trunc` sentinel
    (`len(rows) >= 5000`, agent.py:1929) was structurally unreachable on the Athena lane.
    """
    from leviathan.graphrag.numbers import query as Q
    p1 = [_PAGE_COLS] + [(f"d{i}", str(i)) for i in range(999)]
    p2 = [(f"d{i}", str(i)) for i in range(999, 1500)]
    client, calls = _fake_athena([(p1, "tok-1"), (p2, None)])
    rows = Q._athena(client, "SELECT 1", "db")
    assert len(rows) == 1500                                 # was 999
    assert rows[998]["trade_date"] == "d998" and rows[999]["trade_date"] == "d999"
    assert len(calls) == 2


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


# ── W0-1 (numbers-depth wave, MPOB): publication_lag_days MUST shift the as-of cutoff back under
#    data_date semantics, not only vintage/ESR. VERIFIED a NO-OP fix: _pub_lagged_asof is applied in
#    _guard/apply_pit_filter for EVERY non-year_month semantics (query.py), so the lag branch already
#    covers data_date. These tests PROVE it (an MPOB-shaped spec) so a future regression is caught. ──────
def _mpob() -> TableSpec:                                  # wide + data_date + publication lag (MPOB shape)
    return TableSpec(id="silver_mpob", description="", shape="wide", commodity_col="commodity",
                     period_type="date", date_col="date", knowledge_date_col="date",
                     knowledge_semantics="data_date", publication_lag_days=43,
                     metrics={"closing_stocks_palm_oil_mt": Metric(unit="MT")})


def test_data_date_publication_lag_shifts_guard_w0_1():
    ts = _mpob()
    sql = build_sql(NumberQuery(table="silver_mpob", metric="closing_stocks_palm_oil_mt",
                                asof="2026-05-01", commodity="malaysian_crude_palm_oil_cme",
                                agg="latest"), ts)
    # asof 2026-05-01 minus the 43-day publication lag = 2026-03-19: a data month is citable only once
    # published (date + 43 <= asof), bound as the sargable equivalent date <= asof-43.
    assert "CAST(date AS varchar) <= '2026-03-19'" in sql       # lag applied under data_date semantics
    assert "'2026-05-01'" not in sql                            # the raw (pre-publication) cutoff never appears


def test_data_date_lag_boundary_oracle_april_scoped_w0_1():
    """The April-scoped leakage trap (CORRECTION V1): with lag 43 the April data month (date 2026-04-01)
    is invisible until 2026-05-14 (2026-04-01 + 43) and visible from then -- proves the lag shift in the
    pure-Python oracle too, not just build_sql."""
    ts = _mpob()
    row = [{"commodity": "malaysian_crude_palm_oil_cme", "date": "2026-04-01",
            "closing_stocks_palm_oil_mt": 1900000.0}]
    q = dict(table="silver_mpob", metric="closing_stocks_palm_oil_mt",
             commodity="malaysian_crude_palm_oil_cme", period_start="2026-04-01", period_end="2026-04-30")
    assert apply_pit_filter(row, NumberQuery(asof="2026-05-01", **q), ts) == []   # data date passed, not public
    assert apply_pit_filter(row, NumberQuery(asof="2026-05-13", **q), ts) == []   # still before publication
    kept = apply_pit_filter(row, NumberQuery(asof="2026-05-14", **q), ts)         # 2026-04-01 + 43d exactly
    assert len(kept) == 1 and kept[0]["closing_stocks_palm_oil_mt"] == 1900000.0


# ── HARDENING (numbers-depth wave): a NULL/empty knowledge date must FAIL CLOSED (not-yet-visible),
#    never always-visible. The SQL guard already drops NULLs (col <= asof is NULL => excluded); the
#    Python oracle previously compared str(None or '')='' <= asof == TRUE and leaked every unstamped row. ──
def test_pit_null_knowledge_date_fails_closed():
    # data_date table (knowledge col = date): NULL and empty-string dates are dropped, stamped row survives.
    wx = _weather()
    rows = [{"commodity": "corn", "country": "US", "date": None, "precipitation_mm": 5.0},
            {"commodity": "corn", "country": "US", "date": "", "precipitation_mm": 6.0},
            {"commodity": "corn", "country": "US", "date": "2024-01-15", "precipitation_mm": 7.0}]
    q = NumberQuery(table="silver_nasa_power", metric="precipitation_mm", asof="2024-06-01",
                    commodity="corn", country="US")
    kept = apply_pit_filter(rows, q, wx)
    assert [r["precipitation_mm"] for r in kept] == [7.0]        # only the knowledge-stamped row survives
    # vintage table (knowledge col = release_date): a NULL-release row must NOT become the vintage winner.
    psd = _psd()
    vrows = [{"leviathan_slug": "corn", "country": "Brazil", "market_year": 2023,
              "release_date": None, "ending_stocks_mt": 999.0},
             {"leviathan_slug": "corn", "country": "Brazil", "market_year": 2023,
              "release_date": "2024-02-08", "ending_stocks_mt": 11.0}]
    vq = NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof="2024-03-01",
                     commodity="corn", country="Brazil", period="2023")
    vkept = apply_pit_filter(vrows, vq, psd)
    assert len(vkept) == 1 and vkept[0]["ending_stocks_mt"] == 11.0   # NULL-release row excluded, not the winner


# ── KILL-SWITCH (numbers-depth wave): env GRAPHRAG_NUMBERS_DISABLE (comma-sep table ids) drops those
#    tables from the loaded registry -> they vanish from the agent tool enum too; fail-open on junk. ────────
def test_numbers_disable_kill_switch(monkeypatch):
    from leviathan.graphrag.numbers import agent as A
    from leviathan.graphrag.numbers.registry import _disabled_tables, load_registry

    # the parser accepts each NEW table id and trims surrounding whitespace (real ids never hit fail-open).
    monkeypatch.setenv("GRAPHRAG_NUMBERS_DISABLE", "silver_icco_cocoa, silver_mpob ,silver_sagis_cec")
    assert _disabled_tables() == frozenset({"silver_icco_cocoa", "silver_mpob", "silver_sagis_cec"})

    # the drop actually happens at load: disable an EXISTING table and confirm it (and its tool-enum entry)
    # vanish while peers stay -- proves the mechanism on a table guaranteed present in the live tables.yaml.
    load_registry.cache_clear()
    monkeypatch.setenv("GRAPHRAG_NUMBERS_DISABLE", "silver_psd,silver_mpob")
    reg = load_registry()
    assert "silver_psd" not in reg.tables and "silver_wasde" in reg.tables
    enum = A.tool_schema(reg)["input_schema"]["properties"]["table"]["enum"]
    assert "silver_psd" not in enum                             # dropped from the tool enum by construction

    # fail-OPEN on junk: a whitespace/empty env disables nothing (never silently kill the whole stack).
    load_registry.cache_clear()
    monkeypatch.setenv("GRAPHRAG_NUMBERS_DISABLE", "   ,  , ")
    assert _disabled_tables() == frozenset()
    assert "silver_psd" in load_registry().tables

    # absent env -> identity.
    load_registry.cache_clear()
    monkeypatch.delenv("GRAPHRAG_NUMBERS_DISABLE", raising=False)
    assert "silver_psd" in load_registry().tables
    load_registry.cache_clear()                                 # leave the cache clean for other tests


# ── numbers-depth wave acceptance (integrator): the tool enum gains EXACTLY the three wired ids, and the
#    kill-switch reverts the enum to the pre-wave 8 -- a total, config-only rollback of the whole wave. ──────
_NEW_DEPTH_IDS = ("silver_icco_cocoa", "silver_mpob", "silver_sagis_cec")
_PRE_WAVE_8 = frozenset({
    "silver_psd", "silver_wasde", "silver_production", "silver_nasa_power",
    "silver_esr", "silver_fred_fx", "silver_noaa_oni", "gold_weather_z",
})
# D-LD TRACK 2 #5 (2026-08-18): `silver_nasa_power` is `quarantined: true` (SILVER-F047 -- weather serves
# from gold_weather_z) and `registry.visible_tables` now STRIPS quarantined cards, so it is no longer in
# the tool enum. It stays NAMED in the pre-wave 8 above -- that set is a historical roster, not a live
# expectation -- and is subtracted here, so the day the quarantine lifts this line is the one-word edit
# and the roster above still says which wave the card came from. The card is still LOADED
# (`load_registry`), so this is a VISIBILITY subtraction and not a registry one; the kill-switch arithmetic
# below is untouched because a stripped card cannot appear on either side of it.
_QUARANTINE_STRIPPED = frozenset({"silver_nasa_power"})
# PRICE_OBSERVABILITY W2 wired silver_pink_sheet, and W4 wired silver_cot, as LATER waves; SEAM C
# whitelisted silver_futures_prices (2026-07-23) as a still-later one. All are present regardless of the
# depth-wave kill-switch, so the depth-wave enum baseline is the pre-wave 8 PLUS the price + positioning
# tables PLUS the SEAM-C futures card.
_PRICE_IDS = ("silver_pink_sheet", "silver_cot")
_SEAM_C_IDS = ("silver_futures_prices",)
# WIRING WAVE-1 wired Card A (IOD) + Card B (CONAB) on 2026-07-23; Card C (SAGIS weekly exports) followed on
# 2026-07-24 once the catalog ALTER registered the derived week_ending_date DATE. All three are present
# regardless of the depth-wave kill-switch, so they belong in the depth-wave enum baseline alongside
# price + futures (they are NOT part of the _NEW_DEPTH_IDS the kill-switch reverts).
_WIRING_W1_IDS = ("silver_noaa_iod", "silver_conab_coffee", "silver_sagis_weekly_exports")
# PRICE_AND_PLAYBOOKS W3 whitelisted silver_futures_eod (2026-07-30) -- the per-delivery-month EOD table,
# registered ahead of its producers at W1.0 and fenced out of serving until the producers, their gates and
# the coverage guard were all live. Same standing as the SEAM-C card: present regardless of the depth-wave
# kill-switch, so it belongs in the BASELINE and is NOT one of the three ids that switch reverts.
_W3_IDS = ("silver_futures_eod",)
# D-CW-2a (2026-08-07) landed the weekly NASS crop-progress card (DARK CAPABILITY CENSUS item 6 -- a
# shipped eval already graded its citation key while the registry had no card for it). Same standing as
# every other later wave listed above: present regardless of the DEPTH-wave kill-switch, so it belongs in
# the BASELINE and is NOT one of the three ids that switch reverts.
_D_CW_IDS = ("silver_nass_crop_progress",)
# D-PQ tranche 1a (2026-08-07) landed the MPOC importer-country vegetable-oil ending-stocks card, the
# ONE table of the dark-table matrix's six tranche-1a candidates that survived a data-shape check (the
# other five are recorded in the D-PQ execution record: three carry NO knowledge/date column at all, so
# every build_sql read RAISES, and two are content-dead behind a fresh S3 object). Same standing as
# every later wave above: present regardless of the DEPTH-wave kill-switch, so it belongs in the
# BASELINE and is NOT one of the three ids that switch reverts.
_D_PQ_IDS = ("silver_mpoc_stock_comparison",)
# D-LD TRACK 1 (2026-08-18, LIGHT THE DARK) landed six more cards on tables that were already built,
# scheduled and firing and had no numbers_ref -- FGIS export inspections, the WAP Table 01 revision
# ledger (which DISCHARGES the D-PQ 'free_axis' refusal), the two FNC Colombia coffee tables, the NASS
# citrus forecast and the MPOC Malaysian palm export archive (which discharges the D-PQ 'stale' verdict
# by re-measurement: a CLOSED archive, not a stale one). Same standing as every wave above: present
# regardless of the DEPTH-wave kill-switch, so they belong in the BASELINE and are NOT among the three
# ids that switch reverts. Enumerated by NAME rather than folded in as a count so that a card leaving
# the registry fails here with the id in the message.
_D_LD_IDS = ("silver_fgis", "silver_wap_table01_revisions", "silver_fnc_colombia_monthly",
             "silver_fnc_colombia_exports_port_type", "silver_nass_citrus",
             "silver_mpoc_trade_stats_monthly")
# D-LD TRANCHE 2 (2026-08-18) landed the six tables Track 1 could NOT reach, and the reason is one
# sentence: none of them had a date column of any kind, so `query._guard` had nothing to anchor on and
# every build_sql read RAISED before compiling -- exactly the "three carry NO knowledge/date column at
# all" note on _D_PQ_IDS above, now discharged. Each gained ONE producer-derived column (the WIRING
# WAVE-1 pre-step idiom) and then a card. A SEPARATE tuple rather than an extension of _D_LD_IDS
# because the two tranches are different landings with different preconditions, and a reader tracing
# why a given id is in the baseline should land on the right paragraph. Same standing as every wave
# above: present regardless of the DEPTH-wave kill-switch, so they belong in the BASELINE and are NOT
# among the three ids that switch reverts. Enumerated by NAME so a card leaving the registry fails
# here with the id in the message.
_D_LD_T2_IDS = ("silver_sagis_weekly_deliveries", "silver_ams_cotton_quality", "silver_nass_annual",
                "silver_food_cpi", "silver_fnc_colombia_area_department",
                "silver_mpoc_exports_by_country")
# D-LD TRANCHE 3 (2026-08-19) landed the UNICA Brazil sugar/ethanol family, and its precondition is
# the OPPOSITE of Tranche 2's: these three needed NO producer pre-step at all. `fortnight_date` has
# been a real Glue DATE and `month_date` a clean ISO string since the tables landed, so the guard could
# always have anchored on them -- what kept them dark was a SERVING judgement about ceilings (each
# stops months in the past, and the hazard is a correctly-guarded old number narrated as current),
# ratified by the owner on 2026-08-18. A SEPARATE tuple for the same reason Tranche 2 got one: a reader
# tracing why an id is in the baseline should land on the paragraph that actually explains it.
# Same standing as every wave above: present regardless of the DEPTH-wave kill-switch, so they belong
# in the BASELINE and are NOT among the three ids that switch reverts.
# NOTE the fourth table of that tranche's scope, silver_unica_biweekly_release_series, is deliberately
# ABSENT: it was REFUSED a card because its only temporal column is free-text 'DD/MM/YYYY' on which the
# guard degenerates to a lexicographic compare (measured: 119/122 rows admitted at EVERY as-of,
# including a Feb-2026 stamp at asof 2015-01-01). That refusal is pinned in
# tests/unit/test_capability_wiring.py::test_the_refused_unica_table_is_carded_nowhere.
_D_LD_T3_IDS = ("silver_unica_biweekly_season_history", "silver_unica_corn_ethanol",
                "silver_unica_monthly_ethanol_sales")
# D-EC DK-13 (2026-08-20) landed ONE card, and its precondition is unlike every wave above: the
# table did not exist. gold_board_crush is the first table DERIVED from a published silver table
# (silver_futures_eod), so nothing had to be un-darkened -- the number had to be COMPUTED. It
# quantifies a driver the causal graph models in sixteen places and the corpus can never feed
# (the phrase "board crush" appears in 0 of 449 sampled documents), which is why it could only ever
# be numbers-bound. Same standing as every wave above: present regardless of the DEPTH-wave
# kill-switch, so it belongs in the BASELINE and is NOT among the three ids that switch reverts.
_D_EC_IDS = ("gold_board_crush",)
# LIGHT THE CARD / MINAGRO (2026-08-20) landed ONE card, and like gold_board_crush directly above the
# table did not exist before this wave -- but for the opposite reason. board_crush had to be COMPUTED
# from our own published silver; this one had to be CAPTURED, from a Ukrainian ministry page behind a
# Cloudflare managed challenge that refuses Fargate, which is why its weekly leg is the estate's one
# laptop-side scheduled command (dag_catalog family `minagro`). It is a marketing-year-cumulative
# export table in thousand tonnes, wide, one row per as_of_date x crop_slug, and its knowledge column
# is that same as_of_date -- the F010 contract already carried the full PIT trio before the card
# existed (the silver_nass_citrus case; see the enumeration note in silver/reconcile.py NUMBERS_TABLES,
# which is the drift check that forces the card and that list to land together).
# Same standing as every wave above: present regardless of the DEPTH-wave kill-switch, so it belongs
# in the BASELINE and is NOT among the three ids that switch reverts.
# THE OTHER THREE TABLES OF THE 2026-08-20 WAVE ARE DELIBERATELY ABSENT, and that is a measurement
# rather than an omission: silver_ams_gtr, silver_eex_freight and silver_moex_agro_indices are all
# registered ahead of their producers with `consumers: none`, so the four-checkmark law forbids a card
# until a cloud run proves rows and there is nothing to put in this enum. They join it the day their
# cards land, exactly as this one did.
_MINAGRO_IDS = ("silver_minagro_grain_exports",)
_GN2_IDS = ("gold_futures_spreads",)      # GN-2 W2.3: the spread pairs (kc_chi / white_yellow)
# PROJECTION WAVE Lane 3 (flipped 2026-08-26): silver_psd_attributes, the LONG PSD companion. It
# joins the BASELINE and not _NEW_DEPTH_IDS for the same reason gold_futures_spreads did -- the
# depth-wave kill-switch reverts ITS OWN three tables and nothing else, and a later card riding
# that switch would make a rollback of the numbers-depth wave silently un-serve an unrelated one.
# Its own config-only rollback is GRAPHRAG_NUMBERS_DISABLE=silver_psd_attributes, which the enum
# machinery already gives every card for free.
_LANE3_IDS = ("silver_psd_attributes",)
# PROJECTION WAVE Lane 5 (flipped 2026-08-26, 4ec0ee69): silver_production_livestock, the SECOND
# card on the silver_production physical table (herd/flock size, the milking herd, per-animal
# yield). Joins the BASELINE and not _NEW_DEPTH_IDS for the _LANE3_IDS reason verbatim: the
# depth-wave kill-switch reverts its own three tables and nothing else. This card's config-only
# rollback is GRAPHRAG_NUMBERS_DISABLE=silver_production_livestock. (This line was owed BY the
# flip commit and landed a sitting late -- the keying-knob review caught the red.)
_LANE5_IDS = ("silver_production_livestock",)
_DEPTH_BASELINE = ((_PRE_WAVE_8 | set(_PRICE_IDS) | set(_SEAM_C_IDS) | set(_WIRING_W1_IDS)
                    | set(_W3_IDS) | set(_D_CW_IDS) | set(_D_PQ_IDS) | set(_D_LD_IDS)
                    | set(_D_LD_T2_IDS) | set(_D_LD_T3_IDS) | set(_D_EC_IDS) | set(_MINAGRO_IDS)
                    | set(_GN2_IDS) | set(_LANE3_IDS) | set(_LANE5_IDS))
                   - _QUARANTINE_STRIPPED)          # D-LD Track 2 #5, see above


def _tool_enum():
    from leviathan.graphrag.numbers import agent as A
    from leviathan.graphrag.numbers.registry import load_registry
    return set(A.tool_schema(load_registry())["input_schema"]["properties"]["table"]["enum"])


def test_depth_wave_enum_gains_three_and_kill_switch_reverts_to_pre_wave_8(monkeypatch):
    from leviathan.graphrag.numbers.registry import load_registry

    # (1) env UNSET -> the three freshly wired tables ARE in the agent's tool enum.
    load_registry.cache_clear()
    monkeypatch.delenv("GRAPHRAG_NUMBERS_DISABLE", raising=False)
    live = _tool_enum()
    assert set(_NEW_DEPTH_IDS) <= live, live
    assert live == _DEPTH_BASELINE | set(_NEW_DEPTH_IDS)       # exactly (8 + price + futures) + 3, nothing else

    # (2) disable all three -> the enum reverts to the depth-wave baseline (pre-wave 8 + pink_sheet); a
    #     total, config-only rollback of the depth wave that leaves the separately-wired price table intact.
    load_registry.cache_clear()
    monkeypatch.setenv("GRAPHRAG_NUMBERS_DISABLE", ",".join(_NEW_DEPTH_IDS))
    reverted = _tool_enum()
    assert reverted == _DEPTH_BASELINE, reverted
    assert not (set(_NEW_DEPTH_IDS) & reverted)                 # none of the three survive
    load_registry.cache_clear()                                 # leave the cache clean for other tests


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
    """silver_wasde WITH the WASDE-restoration W2 vintage tiebreak (mirrors the live tables.yaml entry): within
    a grain the pick is release_date DESC, then role rank (actual < estimate < projection), then the
    RELEASE-RELATIVE projection_month rank (the current-month projection == the release month wins), then
    source_table_id ASC — a total order identical on Athena and the pg mirror by construction."""
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
                         VintageTiebreakTerm(col="projection_month", match_release_month="release_date"),
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
    # WASDE-restoration W2: projection_month is RELEASE-RELATIVE (current-month == release month wins), NOT a
    # lexical DESC (which picked the stale prior-month value at ~half of releases + the wrong Dec/Jan wrap row).
    assert tb[1].match_release_month == "release_date"
    assert tb[1].dir == "asc" and tb[1].role_order == [] and tb[1].nulls is None  # default ASC, no dir -> engines agree
    assert tb[2].dir == "asc" and tb[2].role_order == []             # source_table_id ASC (final total order)
    # every OTHER vintage table carries NO tiebreak -> its generated SQL stays byte-identical (zero change).
    for tid in ("silver_psd", "silver_esr", "silver_production", "silver_fred_fx",
                "silver_noaa_oni", "gold_weather_z"):
        assert load_registry().get(tid).vintage_tiebreak == []


def test_wasde_role_tiebreak_in_generated_sql_both_engines():
    # build_sql is BACKEND-AGNOSTIC: the ONE string it returns runs on BOTH pg and Athena (run() only picks the
    # executor), so this single assertion covers both engines' ordering. Role rank + the release-relative
    # projection_month CASE (substr on the ISO release_date, engine-portable, default ASC) force a
    # deterministic total order; the tiebreak cols are silver `string` == pg TEXT COLLATE "C" == Presto order.
    sql = build_sql(NumberQuery(table="silver_wasde", metric="ending_stocks", asof="1986-12-31",
                                commodity="corn", country="united_states", period="1986/87"), _wasde_tiebreak())
    assert ("ORDER BY release_date DESC, CASE estimate_role WHEN 'actual' THEN 0 WHEN 'estimate' THEN 1 "
            "WHEN 'projection' THEN 2 ELSE 3 END ASC, CASE WHEN projection_month = CASE "
            "substr(release_date, 6, 2) WHEN '01' THEN 'January' WHEN '02' THEN 'February' "
            "WHEN '03' THEN 'March' WHEN '04' THEN 'April' WHEN '05' THEN 'May' WHEN '06' THEN 'June' "
            "WHEN '07' THEN 'July' WHEN '08' THEN 'August' WHEN '09' THEN 'September' "
            "WHEN '10' THEN 'October' WHEN '11' THEN 'November' WHEN '12' THEN 'December' ELSE '' END "
            "THEN 0 ELSE 1 END ASC, source_table_id ASC") in sql
    assert "ROW_NUMBER() OVER (PARTITION BY commodity, table_type, region, marketing_year, attribute" in sql
    assert "CAST(release_date" not in sql                            # substr, not CAST -> partition-safe


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


# ── WASDE-restoration W2: CHRONOLOGICAL projection_month tiebreak. The modern US two-vintage shape carries a
#    current-month + a prior-month projection row per grain at ONE release; the CURRENT (== release month) must
#    win. The old lexical `projection_month DESC` picked the STALE prior month at ~half of releases and the
#    wrong row at the Dec/Jan wrap (Athena-probed present: 1549 grains, all January releases). The rank is
#    RELEASE-RELATIVE (match_release_month), so SQL + oracle agree by construction (no dir to diverge). ─────────
_WASDE_SQLITE_COLS = ("commodity", "table_type", "region", "marketing_year", "attribute", "estimate",
                      "release_date", "estimate_role", "projection_month", "source_table_id", "unit")


def _wasde_sqlite(rows):
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH ':memory:' AS leviathan_dev")
    con.execute("""CREATE TABLE leviathan_dev.silver_wasde (
        commodity TEXT, table_type TEXT, region TEXT, marketing_year TEXT, attribute TEXT,
        estimate REAL, release_date TEXT, estimate_role TEXT, projection_month TEXT,
        source_table_id TEXT, unit TEXT)""")
    con.executemany("INSERT INTO leviathan_dev.silver_wasde VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r.get(c) for c in _WASDE_SQLITE_COLS) for r in rows])
    return con


_MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]


def _two_vintage_projection_grain(rel_month: int, rel_year: int = 2015):
    """The modern US shape: ONE grain at ONE release, with the CURRENT-month projection column (projection_month
    == the release month) carrying the operative value, and the PRIOR-month column carrying the stale value.
    Returns (rows, release_date, current_value, prior_value). Prior month wraps Dec of the previous year."""
    cur_name = _MONTH_NAMES[rel_month - 1]
    prior_month = 12 if rel_month == 1 else rel_month - 1
    prior_name = _MONTH_NAMES[prior_month - 1]
    release_date = f"{rel_year}-{rel_month:02d}-10"
    grain = dict(commodity="corn", table_type="us", region="united_states",
                 marketing_year=f"{rel_year}/{(rel_year + 1) % 100:02d}", attribute="ending_stocks",
                 unit="1000 MT", estimate_role="projection")
    cur, prior = 1500.0 + rel_month, 1400.0 + rel_month
    rows = [
        {**grain, "release_date": release_date, "projection_month": prior_name,
         "estimate": prior, "source_table_id": "ws_prior"},
        {**grain, "release_date": release_date, "projection_month": cur_name,
         "estimate": cur, "source_table_id": "ws_cur"},
    ]
    return rows, release_date, cur, prior


def test_wasde_projection_month_release_relative_era_matrix():
    """Era matrix: for EVERY release month (including the Dec→Jan wrap), the modern both-populated projection
    pair must pick the CURRENT (release-month) value — on BOTH the SQL engine and the oracle — at every as-of
    on/after the release. The lexical-DESC bug would pick the prior month for Nov (Oct>Nov), Sep, Jun, Mar,
    and December at the January wrap."""
    ts = _wasde_tiebreak()
    for rel_month in range(1, 13):
        rows, release_date, cur, prior = _two_vintage_projection_grain(rel_month)
        for asof in (release_date, "2015-12-31", "2020-01-01"):       # every as-of on/after the release
            q = NumberQuery(table="silver_wasde", metric="ending_stocks", asof=asof, commodity="corn",
                            country="united_states", period=rows[0]["marketing_year"])
            kept = apply_pit_filter(rows, q, ts)
            assert len(kept) == 1 and kept[0]["estimate"] == cur, (rel_month, asof, "oracle")
            got = _wasde_sqlite(rows).execute(build_sql(q, ts)).fetchall()
            assert len(got) == 1 and got[0][0] == cur, (rel_month, asof, "sql")
            assert cur != prior


def test_wasde_projection_month_january_wrap_picks_january_not_december():
    """The specific Dec/Jan wrap (probed PRESENT, 1549 grains): a January release carries a December (prior)
    and a January (current) projection column. A static winner-first calendar list would wrongly pick
    December; the release-relative rank picks January. Mirrors the live carry-forward series
    (Jan'02 corn US ending_stocks = 1546, not the stale Dec = 1574)."""
    ts = _wasde_tiebreak()
    grain = dict(commodity="corn", table_type="us", region="united_states", marketing_year="2001/02",
                 attribute="ending_stocks", unit="1000 MT", estimate_role="projection")
    rows = [{**grain, "release_date": "2002-01-11", "projection_month": "December",
             "estimate": 1574.0, "source_table_id": "ws_dec"},
            {**grain, "release_date": "2002-01-11", "projection_month": "January",
             "estimate": 1546.0, "source_table_id": "ws_jan"}]
    q = NumberQuery(table="silver_wasde", metric="ending_stocks", asof="2002-06-30", commodity="corn",
                    country="united_states", period="2001/02")
    kept = apply_pit_filter(rows, q, ts)
    assert len(kept) == 1 and kept[0]["projection_month"] == "January" and kept[0]["estimate"] == 1546.0
    got = _wasde_sqlite(rows).execute(build_sql(q, ts)).fetchall()
    assert len(got) == 1 and got[0][0] == 1546.0                     # SQL engine agrees


def test_wasde_tiebreak_oracle_sql_run_parity():
    """MANDATED oracle-run parity: build a mixed frame and run the SQL engine (sqlite) AND the pure-Python
    oracle over the SAME rows, asserting they pick the IDENTICAL winner per grain. A byte-compare of the SQL
    string alone cannot catch a divergence between the emitter and the oracle (the ORACLE-DIR trap); executing
    both is the only proof. The frame mixes: a modern two-vintage projection pair (release-relative), a
    January-wrap pair, and an early-era multi-role tie (actual < estimate < projection)."""
    ts = _wasde_tiebreak()
    modern, _, modern_cur, _ = _two_vintage_projection_grain(9, rel_year=2016)         # Sep: current=September
    wrapg = dict(commodity="corn", table_type="us", region="united_states", marketing_year="2001/02",
                 attribute="ending_stocks", unit="1000 MT", estimate_role="projection")
    wrap = [{**wrapg, "release_date": "2002-01-11", "projection_month": "December", "estimate": 1574.0,
             "source_table_id": "d"},
            {**wrapg, "release_date": "2002-01-11", "projection_month": "January", "estimate": 1546.0,
             "source_table_id": "j"}]
    legacy = _wasde_multirole_rows()                                  # actual must win (rank 0)
    frame = modern + wrap + legacy
    con = _wasde_sqlite(frame)
    grains = {("corn", "us", "united_states", "2016/17", "ending_stocks"): modern_cur,
              ("corn", "us", "united_states", "2001/02", "ending_stocks"): 1546.0,
              ("corn", "balance_sheet", "united_states", "1986/87", "ending_stocks"): 100.0}
    for (co, tt, rg, my, at), want in grains.items():
        q = NumberQuery(table="silver_wasde", metric="ending_stocks", asof="2020-01-01", commodity=co,
                        country=rg, period=my)
        # oracle over the rows of THIS grain
        grain_rows = [r for r in frame if (r["commodity"], r["table_type"], r["region"],
                                           r["marketing_year"], r["attribute"]) == (co, tt, rg, my, at)]
        kept = apply_pit_filter(grain_rows, q, ts)
        sql = build_sql(q, ts)
        got = [g for g in con.execute(sql).fetchall()]
        # a single grain's build_sql filters commodity+region+period+attribute, so exactly one winner each
        assert len(kept) == 1 and kept[0]["estimate"] == want, (my, "oracle")
        assert len(got) == 1 and got[0][0] == want, (my, "sql")
        assert kept[0]["estimate"] == got[0][0]                       # oracle == SQL, by row-run not string
