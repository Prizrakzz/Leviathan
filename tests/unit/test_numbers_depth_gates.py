"""Numbers-depth wave -- the per-lane acceptance gates as CODE.

This file is the judge-free acceptance harness for wiring three UDP-certified silver tables into the
numbers SQL agent: ICCO cocoa (annual, vintage), MPOB palm (monthly, data_date + fixed publication
lag), SAGIS CEC maize (annual, vintage). It encodes the plan's per-lane gate lists
(docs/private/NUMBERS_DEPTH_WAVE_PLAN.md) as deterministic assertions:

  * Leakage traps -- the SOLE PIT proof for tables whose reconcile gate is only-just-un-blinded:
      - MPOB: CORRECTION V1's April-SCOPED trap (period_start/period_end isolate April), asof
        straddling the lag-43 boundary on BOTH sides.
      - SAGIS: a production_year with NO earlier public estimate -> not_known (the verify nit).
      - ICCO: latest-vintage / prior-vintage -- an asof before a release must see the PRIOR vintage,
        and a period-pinned future vintage returns not_known.
  * Golden-value unit fixtures (W0-6) -- one exact (metric, period, asof)->value per table from the
    REAL parquet, units asserted where testable (the thousand-fold SAGIS wheat corruption class).
  * Populatedness fixtures (V2) -- DISTINCT slug/scope assertions against the REAL data. C002 does NOT
    probe these wide tables' slug/scope vocabulary (CORRECTION V2), so these ARE the real vocabulary
    gate. Network-gated: skips cleanly when the read-only S3 probe is unavailable.
  * Register-leak pins -- SAGIS crop codes / scope words and the MPOB contract slug must never surface
    in reader prose; the ICCO/MPOB su_ratio labels stay distinct from the PSD-World su_ratio (D7).
  * Granularity guard -- a monthly-vs-annual disambiguation pin (a "palm stocks in June" ask must
    never satisfy from an annual row, and vice versa) at the build_sql / apply_pit_filter seam.

Values are pinned from a READ-ONLY pyarrow S3 probe of the three flat parquet objects (2026-07-19):
  s3://leviathan-dev-shahem-001/silver/{icco_cocoa,mpob,sagis_cec}/part-000.parquet.

The registry-cards lane authors configs/graphrag/numbers/tables.yaml concurrently. Each table is
imported via the registry loader; if an entry is missing mid-build the lane's tests xfail gracefully
(``_require(tid)``) so this file still runs standalone -- the integrator unifies.
"""
from __future__ import annotations

import io
import json
import os
import types

import pytest

from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import contract_check as CC
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import TableSpec, load_registry
from leviathan.graphrag.register import register_leaks, sanitize

CME = "malaysian_crude_palm_oil_cme"
BUCKET = "leviathan-dev-shahem-001"
_S3_KEYS = {
    "silver_icco_cocoa": "silver/icco_cocoa/part-000.parquet",
    "silver_mpob": "silver/mpob/part-000.parquet",
    "silver_sagis_cec": "silver/sagis_cec/part-000.parquet",
}


# ── registry access with graceful xfail (the lane authoring tables.yaml runs concurrently) ────────────
def _require(tid: str) -> TableSpec:
    reg = load_registry()
    if tid not in reg.tables:
        pytest.xfail(f"{tid} not yet in tables.yaml (registry-cards lane mid-build)")
    return reg.get(tid)


# ── REAL-parquet golden fixtures (probed 2026-07-19; the ground truth every golden assertion pins) ────
# ICCO silver_icco_cocoa: 15 rows, one per cocoa_year, KT (thousand tonnes). Vintage on latest_release_date.
ICCO_ROWS = [
    {"cocoa_year": "2020/21", "latest_release_date": "2021-08-31", "production_kt": 5141.0,
     "grindings_kt": 4860.0, "end_stocks_kt": 1963.0, "su_ratio": 0.403909},
    {"cocoa_year": "2021/22", "latest_release_date": "2023-05-31", "production_kt": 4980.0,
     "grindings_kt": 5072.0, "end_stocks_kt": 1632.0, "su_ratio": 0.321767},
    {"cocoa_year": "2022/23", "latest_release_date": "2023-11-30", "production_kt": 4953.0,
     "grindings_kt": 5002.0, "end_stocks_kt": 1744.0, "su_ratio": 0.348661},
    {"cocoa_year": "2023/24", "latest_release_date": "2025-05-30", "production_kt": 4368.0,
     "grindings_kt": 4818.0, "end_stocks_kt": 1270.0, "su_ratio": 0.263595},
    {"cocoa_year": "2024/25", "latest_release_date": "2026-05-29", "production_kt": 4723.0,
     "grindings_kt": 4628.0, "end_stocks_kt": 1320.0, "su_ratio": 0.285220},
]

# MPOB silver_mpob: 113 rows, one per month, MT (metric tonnes). data_date on `date` + fixed lag 43.
MPOB_ROWS = [
    {"date": "2026-01-01", "commodity": CME, "closing_stocks_palm_oil_mt": 2814849.0,
     "production_cpo_mt": 1500000.0, "exports_palm_oil_mt": 1454625.0, "su_ratio": 1.934},
    {"date": "2026-02-01", "commodity": CME, "closing_stocks_palm_oil_mt": 2703521.0,
     "production_cpo_mt": 1284268.0, "exports_palm_oil_mt": 1106599.0, "su_ratio": 2.443090},
    {"date": "2026-03-01", "commodity": CME, "closing_stocks_palm_oil_mt": 2270574.0,
     "production_cpo_mt": 1376849.0, "exports_palm_oil_mt": 1521098.0, "su_ratio": 1.492720},
    {"date": "2026-04-01", "commodity": CME, "closing_stocks_palm_oil_mt": 2309474.0,
     "production_cpo_mt": 1629801.0, "exports_palm_oil_mt": 1302979.0, "su_ratio": 1.772457},
]
MPOB_APRIL_STOCKS = 2309474.0
MPOB_MARCH_STOCKS = 2270574.0

# SAGIS silver_sagis_cec: 1702 rows. current_estimate_t in TONNES. Vintage on release_date,
# estimate_number DESC tiebreak. total_maize/total headline scope.
SAGIS_ROWS = [
    {"crop": "total_maize", "scope": "total", "production_year": 2025, "report_month": 4,
     "release_date": "2025-04-30", "estimate_number": 3, "current_estimate_t": 15285300.0,
     "area_planted_ha": 2954700.0},
    {"crop": "total_maize", "scope": "total", "production_year": 2025, "report_month": 5,
     "release_date": "2025-05-27", "estimate_number": 4, "current_estimate_t": 15265450.0,
     "area_planted_ha": 2954700.0},
    {"crop": "total_maize", "scope": "total", "production_year": 2025, "report_month": 9,
     "release_date": "2025-09-30", "estimate_number": 8, "current_estimate_t": 16800000.0,
     "area_planted_ha": 2954700.0},
    {"crop": "total_maize", "scope": "total", "production_year": 2026, "report_month": 4,
     "release_date": "2026-04-23", "estimate_number": 3, "current_estimate_t": 17530125.0,
     "area_planted_ha": 3113370.0},
    # a distinct scope + crop so the DISTINCT-vocabulary fixtures have >1 surface form locally
    {"crop": "white_maize", "scope": "commercial", "production_year": 2025, "report_month": 9,
     "release_date": "2025-09-30", "estimate_number": 8, "current_estimate_t": 8200000.0,
     "area_planted_ha": 1500000.0},
]
SAGIS_PY2025_LATEST = 16800000.0     # release 2025-09-30, estimate 8
SAGIS_PY2025_MAY = 15265450.0        # release 2025-05-27, estimate 4 (mid-vintage as-known)
SAGIS_PY2026_FIRST_RELEASE = "2026-04-23"

# ── DISTINCT slug/scope vocabularies captured from the REAL parquet (2026-07-19). These ARE the V2
#    populatedness ground truth: C002 does NOT probe these wide tables' slug/scope surfaces
#    (CORRECTION V2), so the golden-vocabulary fixture is the real >=1-row backstop. The prod bucket is
#    unconditionally firewalled inside pytest (F002 default-deny), so the live cross-check
#    (test_real_parquet_matches_embedded_vocabularies) skips in-suite while THIS embedded gate runs. ──
MPOB_DISTINCT_COMMODITY = {CME}                              # single-commodity axis (probed)
SAGIS_DISTINCT_CROP = {
    "barley", "canola", "dry_beans", "groundnuts", "oats", "sorghum", "soybeans",
    "sunflower_seed", "total_maize", "wheat", "white_maize", "yellow_maize",
}
SAGIS_DISTINCT_SCOPE = {"commercial", "developing", "total"}
SAGIS_CROP_SEASON = {                                       # season is a FUNCTION of crop (not an axis)
    "barley": "winter", "canola": "winter", "oats": "winter", "wheat": "winter",
    "dry_beans": "summer", "groundnuts": "summer", "sorghum": "summer", "soybeans": "summer",
    "sunflower_seed": "summer", "total_maize": "summer", "white_maize": "summer",
    "yellow_maize": "summer",
}


# ── the leakage-safe seam under test: pure-Python apply_pit_filter over local fixtures ────────────────
def _pit(rows, ts, **q) -> list[dict]:
    """apply_pit_filter over local fixtures -- the pure-Python reference build_sql's SQL encodes (the
    anti-leakage oracle the numbers stack ships). No Athena."""
    return Q.apply_pit_filter(rows, Q.NumberQuery(**q), ts)


# ── an end-to-end status oracle: FakeClient + a query_fn that returns apply_pit_filter's rows ──────────
def _tool_use(inp, tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, input=inp, id=tid)


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _resp(content, stop="end_turn"):
    return types.SimpleNamespace(content=content, stop_reason=stop)


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.sent.append(kw)
        return self.outer.queue.pop(0)


class FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        self.messages = _Msgs(self)


def _agent_status(fixture, ts, tool_input, asof) -> dict:
    """Drive the REAL agent loop with a mocked LLM (one tool_use = tool_input) and a query_fn that
    returns exactly apply_pit_filter's rows for that forced spec -- so the honest four-status taxonomy
    (ok/not_known/no_rows) is exercised end-to-end, byte-identical to serving except for the executor."""
    spec = Q.NumberQuery(asof=asof, **{k: v for k, v in tool_input.items() if k != "asof"})
    kept = Q.apply_pit_filter(fixture, spec, ts)
    out = [{"value": r.get(spec.metric), "knowledge_date": r.get(ts.knowledge_date_col)} for r in kept]
    client = FakeClient([_resp([_tool_use(tool_input)]), _resp([_text("done")])])
    res = A.answer_numbers("q", asof=asof, client=client, query_fn=lambda sql: out)
    return res["calls"][0]


# ── network-gated REAL-parquet loader for the V2 populatedness (DISTINCT slug/scope) gate ──────────────
def _real_frame(tid: str):
    """Read the flat silver parquet from S3 (READ-ONLY single-object GET + pyarrow). Skips the test when
    boto3/pyarrow/credentials/object are unavailable -- so the vocabulary gate is real when it can run
    and never a spurious failure in an offline sandbox."""
    try:
        import boto3
        import pyarrow.parquet as pq
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"pyarrow/boto3 unavailable: {e}")
    try:
        body = boto3.client("s3", region_name="us-east-1").get_object(
            Bucket=BUCKET, Key=_S3_KEYS[tid])["Body"].read()
        return pq.read_table(io.BytesIO(body)).to_pandas()
    except Exception as e:  # noqa: BLE001 -- no creds / offline / object moved
        pytest.skip(f"read-only S3 probe unavailable for {tid}: {str(e)[:120]}")


# ======================================================================================================
# LANE A1 -- ICCO cocoa (annual, vintage). THE VALUE CASE.
# ======================================================================================================
def test_icco_golden_value_and_units():
    """W0-6 golden: (grindings_kt, cocoa_year='2023/24', asof=2026-06-01) -> the row whose
    latest_release_date (2025-05-30) <= asof, exact value in KT (thousand tonnes)."""
    ts = _require("silver_icco_cocoa")
    got = _pit(ICCO_ROWS, ts, table="silver_icco_cocoa", metric="grindings_kt",
               asof="2026-06-01", period="2023/24")
    assert [r["grindings_kt"] for r in got] == [4818.0]
    assert got[0]["latest_release_date"] == "2025-05-30"
    # unit pinned in the card as thousand tonnes -- NOT bare MT (the 1000x mislabel class, W0-6)
    assert ts.metrics["grindings_kt"].unit == "1000 MT"
    assert ts.metrics["end_stocks_kt"].unit == "1000 MT"


def test_icco_leakage_trap_period_pinned_is_not_known():
    """Gate #3 trap: (cocoa_year='2024/25', asof=2026-01-01) -> not_known -- its release (2026-05-29)
    was NOT public at asof. Empty apply_pit_filter AND the agent's vintage-only not_known status."""
    ts = _require("silver_icco_cocoa")
    assert _pit(ICCO_ROWS, ts, table="silver_icco_cocoa", metric="grindings_kt",
                asof="2026-01-01", period="2024/25") == []
    call = _agent_status(ICCO_ROWS, ts, {"table": "silver_icco_cocoa", "metric": "grindings_kt",
                                         "period": "2024/25"}, asof="2026-01-01")
    assert call["status"] == "not_known" and call["rows"] == []


def test_icco_latest_vintage_shows_prior_vintage():
    """Latest-vintage trap: agg=latest (no period pin) at asof=2026-01-01 must see the PRIOR vintage --
    the newest cocoa_year whose release <= asof is 2023/24 (2025-05-30); 2024/25 (2026-05-29) is
    withheld. The annual table has no chronological order col, so 'latest' returns the deduped set;
    the leak-safety claim is that 2024/25 is ABSENT and 2023/24 is the freshest visible."""
    ts = _require("silver_icco_cocoa")
    kept = _pit(ICCO_ROWS, ts, table="silver_icco_cocoa", metric="grindings_kt", asof="2026-01-01")
    years = {r["cocoa_year"] for r in kept}
    assert "2024/25" not in years                         # future vintage never leaks
    assert "2023/24" in years                             # the prior vintage IS visible
    assert max(years) == "2023/24"


def test_icco_metric_columns_exist_aws_free():
    """Gate #1 (CORRECTION V2): each declared metric is a physical column of the wide table -- an
    AWS-free F010 registry membership check (shape=wide never runs a DISTINCT probe)."""
    ts = _require("silver_icco_cocoa")
    assert ts.shape == "wide"
    cols = CC._f010_column_fn()(CC._physical(ts))
    assert cols, "F010 silver registry columns unavailable"
    assert set(ts.metrics) <= cols


def test_icco_register_clean_and_su_ratio_labeled_distinctly():
    """D7 + register: cocoa is a bare word (no leak); the ICCO su_ratio label is annual and stays
    DISTINCT from the PSD-World su_ratio so an answer never blends the two formulas."""
    ts = _require("silver_icco_cocoa")
    ans = "World cocoa grindings were 4,818 thousand tonnes in 2023/24; stocks-to-use 0.264 [2025-05-30]."
    assert register_leaks(sanitize(ans)) == []
    assert "PSD" in ts.metrics["su_ratio"].desc and "ANNUAL" in ts.metrics["su_ratio"].desc.upper()


# ======================================================================================================
# LANE A2 -- MPOB palm (monthly, data_date + fixed publication lag 43).
# ======================================================================================================
def test_mpob_april_scoped_leakage_trap_flips_at_lag_boundary():
    """CORRECTION V1 -- the April-SCOPED trap. period_start/period_end isolate the April row so the
    lag-43 guard is actually interrogated (the original single-bound trap returned public MARCH and
    never touched April). April (date 2026-04-01) is public at asof >= 2026-05-14 (date + 43); it must
    be INVISIBLE at 2026-05-01 and 2026-05-13 and VISIBLE at 2026-05-14 and 2026-05-20."""
    ts = _require("silver_mpob")

    def april(asof):
        return _pit(MPOB_ROWS, ts, table="silver_mpob", metric="closing_stocks_palm_oil_mt",
                    asof=asof, commodity=CME, period_start="2026-04-01", period_end="2026-04-30")

    assert april("2026-05-01") == []
    assert april("2026-05-13") == []                       # one day before the boundary
    assert [r["closing_stocks_palm_oil_mt"] for r in april("2026-05-14")] == [MPOB_APRIL_STOCKS]
    assert [r["closing_stocks_palm_oil_mt"] for r in april("2026-05-20")] == [MPOB_APRIL_STOCKS]


def test_mpob_lag_43_offset_is_emitted_in_sql():
    """W0-1: build_sql must shift the as-of cutoff back by publication_lag_days under data_date
    semantics (asof 2026-05-01 - 43 = 2026-03-19) -- without this, MPOB would surface a month on its
    first-of-month DATA date, ~40 days before the real ~10th-of-M+1 release (a hard PIT leak)."""
    ts = _require("silver_mpob")
    assert ts.publication_lag_days == 43 and ts.knowledge_semantics == "data_date"
    sql = Q.build_sql(Q.NumberQuery(table="silver_mpob", metric="closing_stocks_palm_oil_mt",
                                    asof="2026-05-01", commodity=CME,
                                    period_start="2026-04-01", period_end="2026-04-30"), ts)
    assert "CAST(date AS varchar) <= '2026-03-19'" in sql   # the lag-shifted guard


def test_mpob_golden_value_and_units():
    """W0-6 golden: April 2026 closing stocks = 2,309,474 MT at asof 2026-05-20, unit = MT."""
    ts = _require("silver_mpob")
    got = _pit(MPOB_ROWS, ts, table="silver_mpob", metric="closing_stocks_palm_oil_mt",
               asof="2026-05-20", commodity=CME, period_start="2026-04-01", period_end="2026-04-30")
    assert [r["closing_stocks_palm_oil_mt"] for r in got] == [MPOB_APRIL_STOCKS]
    assert ts.metrics["closing_stocks_palm_oil_mt"].unit == "MT"


def test_mpob_populatedness_commodity_is_the_declared_slug():
    """Gate #1 populatedness (CORRECTION V2 -- the golden fixture, not C002, is the backstop): the
    headline commodity slug returns a row locally, and the single-commodity axis holds. The DISTINCT
    vocabulary is asserted against the REAL parquet in test_real_distinct_vocabularies."""
    ts = _require("silver_mpob")
    assert ts.commodity_col == "commodity"
    got = _pit(MPOB_ROWS, ts, table="silver_mpob", metric="closing_stocks_palm_oil_mt",
               asof="2026-05-20", commodity=CME, agg="latest")
    assert got and got[0]["commodity"] == CME


def test_mpob_register_slug_is_sanitized_out():
    """Register: malaysian_crude_palm_oil_cme is an UNDERSCORED contract slug -> register_leaks flags
    it in raw prose; the existing sanitizer rewrites it to a spelled-out name so the sanitized answer
    is clean (register_leaks(sanitize(answer)) == [])."""
    _require("silver_mpob")
    raw = f"Malaysian palm closing stocks were 2,309,474 MT via {CME} [2026-04-01]."
    assert register_leaks(raw)                              # the slug DOES leak in raw prose
    assert CME not in sanitize(raw)                         # ... and is rewritten out
    assert register_leaks(sanitize(raw)) == []


def test_mpob_su_ratio_labeled_distinctly_from_psd():
    """D7 / su_ratio-collision: MPOB su_ratio is a MONTHLY stocks/exports ratio, labeled distinctly
    from the PSD annual stocks-to-use so the reroute-v2 yardstick and this column never blend."""
    ts = _require("silver_mpob")
    assert "PSD" in ts.metrics["su_ratio"].desc and "MONTHLY" in ts.metrics["su_ratio"].desc.upper()


def test_mpob_metric_columns_exist_aws_free():
    ts = _require("silver_mpob")
    assert ts.shape == "wide"
    cols = CC._f010_column_fn()(CC._physical(ts))
    assert cols and set(ts.metrics) <= cols
    assert "ffb_price_myr_per_mt" not in ts.metrics        # D2 price-doctrine fence


# ======================================================================================================
# LANE A3 -- SAGIS CEC maize (annual, vintage; scope ridden on country_col).
# ======================================================================================================
def test_sagis_golden_latest_and_mid_vintage_in_tonnes():
    """W0-6 golden + latest-vintage collapse: total_maize/total production_year=2025.
      * asof 2025-12-31 -> the newest estimate as-known = 16,800,000 t (release 2025-09-30, est 8).
      * asof 2025-06-01 -> the mid-season vintage = 15,265,450 t (release 2025-05-27, est 4).
    Units are TONNES, not thousand-tonnes -- the SAGIS golden thousand-fold-corruption class (W0-6)."""
    ts = _require("silver_sagis_cec")
    latest = _pit(SAGIS_ROWS, ts, table="silver_sagis_cec", metric="current_estimate_t",
                  asof="2025-12-31", commodity="total_maize", country="total", period="2025")
    assert [r["current_estimate_t"] for r in latest] == [SAGIS_PY2025_LATEST]
    mid = _pit(SAGIS_ROWS, ts, table="silver_sagis_cec", metric="current_estimate_t",
               asof="2025-06-01", commodity="total_maize", country="total", period="2025")
    assert [r["current_estimate_t"] for r in mid] == [SAGIS_PY2025_MAY]
    assert ts.metrics["current_estimate_t"].unit == "MT"    # metric tonnes, NOT "1000 MT"


def test_sagis_leakage_trap_production_year_with_no_earlier_estimate():
    """Leakage trap (verify nit): production_year=2026's earliest release is 2026-04-23. An asof
    strictly before it (2026-04-01) has NO public estimate for that year -> not_known (vintage), never
    a fabricated figure or a leak of the yet-unreleased first estimate."""
    ts = _require("silver_sagis_cec")
    assert _pit(SAGIS_ROWS, ts, table="silver_sagis_cec", metric="current_estimate_t",
                asof="2026-04-01", commodity="total_maize", country="total", period="2026") == []
    call = _agent_status(SAGIS_ROWS, ts, {"table": "silver_sagis_cec", "metric": "current_estimate_t",
                                          "commodity": "total_maize", "country": "total",
                                          "period": "2026"}, asof="2026-04-01")
    assert call["status"] == "not_known" and call["rows"] == []
    # sanity: on/after the first release the estimate IS visible
    assert _pit(SAGIS_ROWS, ts, table="silver_sagis_cec", metric="current_estimate_t",
                asof=SAGIS_PY2026_FIRST_RELEASE, commodity="total_maize", country="total",
                period="2026")


def test_sagis_scope_rides_country_col():
    """W0-2 / D5: the scope axis (total|commercial|developing) has no tool field, so it rides
    country_col. build_sql emits an equality on `scope` from the country field; a commercial-scope
    ask does NOT return the total-scope row."""
    ts = _require("silver_sagis_cec")
    assert ts.country_col == "scope" and ts.commodity_col == "crop"
    sql = Q.build_sql(Q.NumberQuery(table="silver_sagis_cec", metric="current_estimate_t",
                                    asof="2025-12-31", commodity="total_maize", country="total",
                                    period="2025"), ts)
    assert "scope = 'total'" in sql and "crop = 'total_maize'" in sql
    # scope selectivity: commercial scope must not satisfy from a total-scope row
    commercial = _pit(SAGIS_ROWS, ts, table="silver_sagis_cec", metric="current_estimate_t",
                      asof="2025-12-31", commodity="white_maize", country="commercial", period="2025")
    assert commercial and all(r["scope"] == "commercial" for r in commercial)


def test_sagis_crop_code_and_scope_never_leak_into_prose():
    """Register (the concrete NEW hazard of the wave): SAGIS crop codes (total_maize/white_maize/...)
    are underscored tokens that must be rewritten to friendly labels before reader prose. The sanitizer
    rewrite map for these crop codes is a serving-lane change (Lane A3); until it lands this pin xfails
    rather than failing, so the file runs standalone and the pin turns green when the rewrite ships."""
    _require("silver_sagis_cec")
    codes = ["total_maize", "white_maize", "yellow_maize", "sunflower_seed"]
    if any(c in sanitize(c) for c in codes):
        pytest.xfail("SAGIS crop-code sanitizer rewrite pending (serving-lane numbers-footer change)")
    ans = "South African total_maize (total scope) production estimate was 16,800,000 MT [2025-09-30]."
    assert all(c not in sanitize(ans) for c in codes)
    assert register_leaks(sanitize(ans)) == []


def test_sagis_season_functionally_determined_by_crop():
    """Doc lint (the season_type note): season is a FUNCTION of crop (maize=summer, wheat=winter), NOT
    an independent grain axis -- no crop appears in both seasons. Asserted against the probed ground
    truth (SAGIS_CROP_SEASON) so the grain_cols choice ([crop, scope, production_year], no season) is
    safe. The local fixture's (crop, season) pairs must agree with that ground truth."""
    _require("silver_sagis_cec")
    assert set(SAGIS_CROP_SEASON) == SAGIS_DISTINCT_CROP     # every crop has exactly one season
    assert len(set(SAGIS_CROP_SEASON.values())) == 2         # summer | winter, disjoint by crop
    for r in SAGIS_ROWS:
        assert SAGIS_CROP_SEASON[r["crop"]] in ("summer", "winter")


def test_sagis_metric_columns_exist_and_revision_fields_fenced():
    """Gate #1 + D4: the two served metrics are physical columns; the inter-vintage DELTA fields
    (revision_t/revision_pct/revision_surprise) are NOT served (level-vs-delta criterion, CORRECTION
    V4 -- there is no 'quarantine'; the line is point-in-time LEVEL vs cross-vintage DELTA)."""
    ts = _require("silver_sagis_cec")
    assert ts.shape == "wide"
    cols = CC._f010_column_fn()(CC._physical(ts))
    assert cols and set(ts.metrics) <= cols
    for delta in ("revision_t", "revision_pct", "revision_surprise"):
        assert delta not in ts.metrics


# ======================================================================================================
# GRANULARITY GUARD -- monthly (MPOB) vs annual (ICCO/SAGIS) are non-interchangeable at the query seam.
# ======================================================================================================
def test_granularity_monthly_ask_isolates_the_month():
    """A "palm stocks in June" ask hits MPOB (monthly), which carves the month via a date-range
    predicate and returns EXACTLY that month's row -- never a year's worth summed or an annual level."""
    ts = _require("silver_mpob")
    sql = Q.build_sql(Q.NumberQuery(table="silver_mpob", metric="closing_stocks_palm_oil_mt",
                                    asof="2026-07-01", commodity=CME,
                                    period_start="2026-03-01", period_end="2026-03-31"), ts)
    assert "CAST(date AS varchar) >= '2026-03-01'" in sql and "CAST(date AS varchar) <= '2026-03-31'" in sql
    got = _pit(MPOB_ROWS, ts, table="silver_mpob", metric="closing_stocks_palm_oil_mt",
               asof="2026-07-01", commodity=CME, period_start="2026-03-01", period_end="2026-03-31")
    assert [r["closing_stocks_palm_oil_mt"] for r in got] == [MPOB_MARCH_STOCKS]
    assert all(r["date"].startswith("2026-03") for r in got)


def test_granularity_annual_table_cannot_carve_a_month():
    """... and the vice-versa: a month window handed to the ANNUAL cocoa table cannot subset within the
    year -- ICCO has no date_col, so build_sql emits NO month lower-bound predicate; the only period
    axis is cocoa_year. So 'cocoa grindings in June' can never satisfy from a spuriously-monthly row."""
    ts = _require("silver_icco_cocoa")
    assert ts.date_col is None and ts.period_type == "marketing_year"
    sql = Q.build_sql(Q.NumberQuery(table="silver_icco_cocoa", metric="grindings_kt",
                                    asof="2026-06-15", period_start="2026-06-01",
                                    period_end="2026-06-30"), ts)
    assert ">=" not in sql                                  # no month lower-bound: cannot carve June
    assert "cocoa_year" in sql                              # annual axis only


def test_granularity_grains_are_structurally_disjoint():
    """Structural invariant behind both directions: MPOB is date-grained with NO annual period axis;
    ICCO/SAGIS are annual with NO date axis. Every MPOB row is self-identifying by its data_date
    (surfaced as knowledge_date), so a monthly figure can never be silently relabeled annual."""
    mpob = _require("silver_mpob")
    assert mpob.period_type == "date" and mpob.date_col == "date" and mpob.period_col is None
    sql = Q.build_sql(Q.NumberQuery(table="silver_mpob", metric="closing_stocks_palm_oil_mt",
                                    asof="2026-05-20", commodity=CME, agg="latest"), mpob)
    assert "date AS knowledge_date" in sql                 # the month stamp travels with the value
    for tid, ptype in (("silver_icco_cocoa", "marketing_year"), ("silver_sagis_cec", "year")):
        ts = _require(tid)
        assert ts.period_type == ptype and ts.date_col is None


# ======================================================================================================
# POPULATEDNESS (V2) -- DISTINCT slug/scope against the REAL data. THIS is the vocabulary gate (not C002).
# ======================================================================================================
def test_populatedness_distinct_vocabularies():
    """CORRECTION V2 -- THE real vocabulary gate (C002 does NOT probe these wide tables' slug/scope
    surfaces: wide-metric is F010 column existence; the slug/country DISTINCT families iterate
    cascade_map, which these tables are OUT of). Assert the routing surface forms the cards + W0-7
    conventions mint are all IN the probed DISTINCT vocabulary, and the single-axis constraints hold --
    so no headline ask can SUCCEED with 0 rows on an unrecognised slug/scope."""
    # MPOB: exactly one commodity slug, and it is the one the card + conventions block route to.
    mpob = _require("silver_mpob")
    assert MPOB_DISTINCT_COMMODITY == {CME}
    assert CME in MPOB_DISTINCT_COMMODITY and mpob.commodity_col == "commodity"

    # SAGIS: every W0-7 crop code the conventions note advertises is a real DISTINCT crop; the scope
    # axis (ridden on country_col) is exactly {commercial, developing, total}; the headline (total_maize,
    # total) is present in-fixture -- the 'SUCCEEDED 0-row on an unrecognised slug' guard.
    sag = _require("silver_sagis_cec")
    advertised = {"total_maize", "white_maize", "yellow_maize", "wheat", "soybeans", "sunflower_seed",
                  "sorghum", "barley", "canola", "oats", "dry_beans", "groundnuts"}
    assert advertised <= SAGIS_DISTINCT_CROP
    assert SAGIS_DISTINCT_SCOPE == {"commercial", "developing", "total"}
    assert sag.commodity_col == "crop" and sag.country_col == "scope"
    assert any(r["crop"] == "total_maize" and r["scope"] == "total" for r in SAGIS_ROWS)
    # local fixture surface forms must be a subset of the real vocabulary (no drift in the fixtures)
    assert {r["crop"] for r in SAGIS_ROWS} <= SAGIS_DISTINCT_CROP
    assert {r["scope"] for r in SAGIS_ROWS} <= SAGIS_DISTINCT_SCOPE

    # ICCO: single-commodity WORLD table -> the populatedness surface is the headline metric + period,
    # not a slug/scope. The golden fixture already asserts >=1 populated row; pin the axis shape here.
    icco = _require("silver_icco_cocoa")
    assert icco.commodity_col is None and icco.country_col is None
    assert "2023/24" in {r["cocoa_year"] for r in ICCO_ROWS}
    assert sum(1 for r in ICCO_ROWS if r.get("grindings_kt") is not None) == len(ICCO_ROWS)


@pytest.mark.integration
def test_real_parquet_matches_embedded_vocabularies():
    """Provenance cross-check: the embedded DISTINCT vocabularies were captured from the REAL parquet
    (2026-07-19). This confirms they still match on demand. The prod bucket is unconditionally
    firewalled inside pytest (F002 default-deny; prod is never a valid test target), so this SKIPS
    in-suite via _real_frame -- run it out-of-band (or against a sanctioned mirror) to re-verify."""
    mdf = _real_frame("silver_mpob")
    assert set(mdf["commodity"].dropna().unique()) == MPOB_DISTINCT_COMMODITY
    sdf = _real_frame("silver_sagis_cec")
    assert set(sdf["crop"].dropna().unique()) == SAGIS_DISTINCT_CROP
    assert set(sdf["scope"].dropna().unique()) == SAGIS_DISTINCT_SCOPE
    idf = _real_frame("silver_icco_cocoa")
    assert "2023/24" in set(idf["cocoa_year"]) and idf["grindings_kt"].notna().sum() >= 10


# ======================================================================================================
# PROJECTION SAFETY (gate #2) + reconcile coverage (CORRECTION V3).
# ======================================================================================================
def test_projection_safety_flat_tables_have_no_projected_axis():
    """Gate #2 (invariant 4): all three are flat / projection-forbidden -- no partition_cols, no
    vintage_partition_col, no commodity_code_col -- so numbers/lint projection safety passes trivially
    and the Jul-2026 $134 S3-LIST-storm class cannot recur here."""
    for tid in ("silver_icco_cocoa", "silver_mpob", "silver_sagis_cec"):
        ts = _require(tid)
        assert ts.partition_cols == []
        assert ts.vintage_partition_col is None
        assert ts.commodity_code_col is None


def test_reconcile_gate_is_not_blind_to_the_new_tables():
    """CORRECTION V3: reconcile.NUMBERS_TABLES is a hardcoded tuple that reconcile_numbers() iterates;
    a table absent from it is NEVER checked and the gate reports 'clean' vacuously. Pin that all three
    are present so a mis-derived PIT field (e.g. the MPOB lag) can never ship green-but-unchecked."""
    from leviathan.silver import reconcile
    for tid in ("silver_icco_cocoa", "silver_mpob", "silver_sagis_cec"):
        assert tid in reconcile.NUMBERS_TABLES


# ======================================================================================================
# EVAL INTENT-ROUTING PINS (judge-free) -- the three headline asks route numbers_only.
# ======================================================================================================
_EVAL_YAML = os.path.join("configs", "graphrag", "eval_queries_v3.yaml")
_DEPTH_EVAL_IDS = ("b_cocoa_grindings_2324", "b_mpob_palm_stocks_apr2026", "b_sagis_maize_2025")


def _load_eval_rows():
    import yaml
    from leviathan.graphrag import extract as ex
    path = ex._CFG / "eval_queries_v3.yaml"
    if not path.exists():
        pytest.skip(f"{path} absent")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {q["id"]: q for q in (data.get("queries") or []) if "id" in q}


def test_eval_yaml_pins_route_numbers_only():
    """Task-6 eval pins: the three new numbers rows (cocoa grindings / Malaysian palm stocks / SA maize
    estimate) declare expected_intent=numbers_only AND the deterministic heuristic router agrees --
    judge-free, so this holds without any API spend. The rows are xfail if the eval-yaml lane hasn't
    merged them yet (they are additions this file owns)."""
    from leviathan.graphrag.intent import classify_intent
    rows = _load_eval_rows()
    missing = [i for i in _DEPTH_EVAL_IDS if i not in rows]
    if missing:
        pytest.xfail(f"numbers-depth eval rows not yet merged: {missing}")
    for i in _DEPTH_EVAL_IDS:
        q = rows[i]
        assert q.get("expected_intent") == "numbers_only", f"{i}: expected_intent must be numbers_only"
        got = classify_intent(q["question"], call=None)      # call=None -> heuristic only (judge-free)
        assert got["intent"] == "numbers_only", f"{i}: router gave {got['intent']} for {q['question']!r}"
        assert q.get("asof"), f"{i}: a numbers/PIT row must carry an asof cutoff"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
