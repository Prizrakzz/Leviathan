"""PRICE_OBSERVABILITY W2.6 -- v1b silver_pink_sheet acceptance gates (SYNTHETIC fixtures only).

The register-fence detector (W0), the registry schema knobs (W1: date_col_type / provenance_col), and
the pink_sheet card + F010 wiring + R5 decline guard (W2) are all local code/config. This file is the
judge-free, AWS-free acceptance harness. Golden real-parquet snapshots are added as W3.1 riders (S3.F7);
here the fixtures are hand-authored -- and TIMESTAMP-TYPED, because a plain-date fixture would pass while
live behavior differs (S2.F1 / DP-5): Athena stringifies the physical timestamp column as
'2026-06-01 00:00:00.000' and the pg mirror as '2026-06-01 00:00:00', so only the substr-normalized SQL
predicate includes the boundary month and keeps parity.

Covers: registry shape + DP-5 knob; metric-column existence vs the F010 card (the brent_crude_usd_bbl
naming trap); the wide-parity first-four ordering; DP-5 substr normalization in extras AND predicates;
the lag-40 offset literal; boundary-month INCLUSION; the forced-asof lag-boundary trap; zscore-as-sigma;
revision_stamp in rows + citation meta; the R5 decline guard battery (each NONE-tier fires, covered names
never fire, prefaces register-clean with zero raw counters, the trace key survives run_numbers_only, and
the ESR-guard trace copy does not regress); reconcile + contract-check coupling.
"""
from __future__ import annotations

import types

import pytest

from leviathan.graphrag import config_check as CC_LINT
from leviathan.graphrag import register as REG
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import contract_check as CC
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import load_registry

TID = "silver_pink_sheet"


def _ts() -> "object":
    return load_registry().get(TID)


# -- TIMESTAMP-TYPED synthetic fixture (S2.F1): the physical `date` renders WITH a time-of-day suffix, so a
#    naive text compare would exclude the boundary month; the DP-5 substr path collapses it to 'YYYY-MM-DD'.
#    Values are illustrative (golden real-parquet rows arrive as W3.1 riders). --------------------------------
PS_ROWS = [
    {"date": "2026-03-01 00:00:00.000", "palm_oil_cpo_usd_t": 1000.0, "soybean_oil_usd_t": 1100.0,
     "urea_usd_mt": 400.0, "palm_oil_cpo_usd_t_zscore_5yr": 0.5, "latest_release_ym": "2026M07"},
    {"date": "2026-04-01 00:00:00.000", "palm_oil_cpo_usd_t": 1010.0, "soybean_oil_usd_t": 1120.0,
     "urea_usd_mt": 405.0, "palm_oil_cpo_usd_t_zscore_5yr": 0.6, "latest_release_ym": "2026M07"},
    {"date": "2026-05-01 00:00:00.000", "palm_oil_cpo_usd_t": 1020.0, "soybean_oil_usd_t": 1140.0,
     "urea_usd_mt": 410.0, "palm_oil_cpo_usd_t_zscore_5yr": 0.7, "latest_release_ym": "2026M07"},
    {"date": "2026-06-01 00:00:00.000", "palm_oil_cpo_usd_t": 1030.0, "soybean_oil_usd_t": 1160.0,
     "urea_usd_mt": 415.0, "palm_oil_cpo_usd_t_zscore_5yr": 0.8, "latest_release_ym": "2026M07"},
]


def _pit(rows, ts, **q) -> list[dict]:
    return Q.apply_pit_filter(rows, Q.NumberQuery(**q), ts)


# -- FakeClient plumbing (clone of the depth-gate harness) so the REAL agent loop runs offline ---------------
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


# ======================================================================================================
# Registry shape + DP-5 knob.
# ======================================================================================================
def test_pink_sheet_registered_shape_and_knobs():
    ts = _ts()
    assert ts.shape == "wide"
    assert ts.commodity_col is None and ts.country_col is None      # the metric name IS the series
    assert ts.period_type == "date" and ts.date_col == "date"
    assert ts.date_col_type == "timestamp"                          # DP-5 knob (physical column is a timestamp)
    assert ts.knowledge_semantics == "data_date" and ts.knowledge_date_col == "date"
    assert ts.publication_lag_days == 40                            # DP-3
    assert ts.provenance_col == "latest_release_ym"                 # DP-2


def test_pink_sheet_metric_order_first_four_for_wide_parity():
    """The wide pg-parity sampler takes only the FIRST FOUR metrics (numbers_parity.py:93). They must span
    one commodity price / one fertilizer / one energy / one z-score so the panel is representative."""
    ts = _ts()
    assert list(ts.metrics)[:4] == [
        "soybean_oil_usd_t", "urea_usd_mt", "brent_crude_usd_bbl", "palm_oil_cpo_usd_t_zscore_5yr"]
    assert len(ts.metrics) == 32


def test_pink_sheet_metric_columns_exist_aws_free():
    """The brent-naming trap: every declared metric must be a PHYSICAL column of the F010 card (a shape=wide
    registry-membership check, no DISTINCT probe). The physical energy column is brent_crude_usd_bbl."""
    ts = _ts()
    cols = CC._f010_column_fn()(CC._physical(ts))
    assert cols, "F010 silver registry columns unavailable"
    missing = set(ts.metrics) - cols
    assert missing == set(), f"declared metrics absent from F010 physical columns: {sorted(missing)}"
    assert "brent_crude_usd_bbl" in ts.metrics and "brent_usd_bbl" not in ts.metrics


def test_pink_sheet_zscore_metric_served_as_sigma():
    ts = _ts()
    assert ts.metrics["palm_oil_cpo_usd_t_zscore_5yr"].unit == "sigma vs 5-yr mean"
    assert ts.metrics["soybean_oil_usd_t"].unit == "USD/mt"
    assert ts.metrics["brent_crude_usd_bbl"].unit == "USD/bbl"


# ======================================================================================================
# DP-5 timestamp normalization + DP-3 lag + boundary inclusion (SQL-text proofs -- the mpob :280 pattern).
# ======================================================================================================
def test_pink_sheet_dp5_substr_normalization_in_extras_and_predicates():
    ts = _ts()
    sql = Q.build_sql(Q.NumberQuery(table=TID, metric="palm_oil_cpo_usd_t", asof="2026-07-05",
                                    period_start="2026-04-01", period_end="2026-06-01"), ts)
    norm = "substr(CAST(date AS varchar), 1, 10)"
    assert f"{norm} AS knowledge_date" in sql                       # SELECT extra normalized (no raw timestamp)
    assert f"{norm} >= '2026-04-01'" in sql                         # window start predicate normalized
    assert f"{norm} <= '2026-06-01'" in sql                         # window end (boundary month) normalized
    # revision_stamp (DP-2) surfaced as an alias so citation meta can render "as published, WB release ...".
    assert "latest_release_ym AS revision_stamp" in sql


def test_pink_sheet_lag_40_offset_emitted_in_guard():
    """The as-of guard shifts back by publication_lag_days (asof 2026-07-05 - 40 = 2026-05-26), so a month
    on its first-of-month DATA date is not citable ~40 days early -- a hard PIT leak without it."""
    ts = _ts()
    sql = Q.build_sql(Q.NumberQuery(table=TID, metric="palm_oil_cpo_usd_t", asof="2026-07-05"), ts)
    assert "substr(CAST(date AS varchar), 1, 10) <= '2026-05-26'" in sql


def test_pink_sheet_boundary_month_inclusion_is_normalized():
    """DP-5: a window ending on the boundary month must NOT be excluded. A naive predicate compares the raw
    timestamp render ('2026-06-01 00:00:00.000' > '2026-06-01') and drops June; the substr predicate keeps
    it ('2026-06-01' <= '2026-06-01'). Prove the emitted predicate is the substr-normalized form, and that a
    row rendered with the timestamp suffix truncates INTO the window under substr(...,1,10)."""
    ts = _ts()
    sql = Q.build_sql(Q.NumberQuery(table=TID, metric="palm_oil_cpo_usd_t", asof="2027-01-01",
                                    period_start="2026-04-01", period_end="2026-06-01"), ts)
    assert "substr(CAST(date AS varchar), 1, 10) <= '2026-06-01'" in sql
    assert " date <= '2026-06-01'" not in sql                       # never a NAKED bare-column boundary predicate
    # the substr semantics on the boundary row: the timestamp render truncates to the date, which IS <= end.
    boundary_render = "2026-06-01 00:00:00.000"
    assert boundary_render[:10] == "2026-06-01" and boundary_render[:10] <= "2026-06-01"


# ======================================================================================================
# Forced-asof lag-boundary trap (the mpob :263 pattern, at the guard level on the timestamp-typed fixture).
# ======================================================================================================
def test_pink_sheet_lag_boundary_trap_latest_knowable_is_prior_month():
    """asof early in month M+1, before the 40d lag elapses, must serve the latest knowable month M-1. With
    M=June: at asof 2026-07-05 (guard cutoff 2026-05-26) the June row (data 2026-06-01, public ~2026-07-11)
    is INVISIBLE and the newest visible month is May. At asof 2026-07-12 (cutoff 2026-06-02) June appears."""
    ts = _ts()
    early = _pit(PS_ROWS, ts, table=TID, metric="palm_oil_cpo_usd_t", asof="2026-07-05")
    months_early = {r["date"][:7] for r in early}
    assert "2026-06" not in months_early                           # June not yet public -> never leaks
    assert "2026-05" in months_early and max(months_early) == "2026-05"   # latest knowable is M-1 = May
    later = _pit(PS_ROWS, ts, table=TID, metric="palm_oil_cpo_usd_t", asof="2026-07-12")
    assert "2026-06" in {r["date"][:7] for r in later}             # ...and becomes visible once the lag elapses


# ======================================================================================================
# DP-5 oracle parity: apply_pit_filter (the pure-Python PIT reference build_sql is verified against, and the
# query_fn W3.1's golden uses) must normalize the TIMESTAMP date EXACTLY as the substr SQL predicate does.
# These RUN apply_pit_filter (not just assert on SQL text) at the two boundaries the DP-5 knob exists to
# guarantee -- the window edge and the exact publication-lag day -- locking the oracle to build_sql (W2-PIT-01).
# ======================================================================================================
def test_apply_pit_window_boundary_month_included_normalizes_timestamp():
    """A window ending on the boundary month keeps June: the raw render '2026-06-01 00:00:00.000' truncates to
    '2026-06-01' <= period_end, exactly as build_sql's `substr(...) <= '2026-06-01'`. asof is far-future so
    only the window (not the lag) gates. Pre-fix apply_pit_filter compared the raw timestamp
    ('2026-06-01 00:00:00.000' > '2026-06-01') and silently DROPPED the boundary month."""
    ts = _ts()
    kept = _pit(PS_ROWS, ts, table=TID, metric="palm_oil_cpo_usd_t",
                period_start="2026-04-01", period_end="2026-06-01", asof="2027-01-01")
    months = {r["date"][:7] for r in kept}
    assert months == {"2026-04", "2026-05", "2026-06"}             # boundary month June INCLUDED (was dropped)


def test_apply_pit_exact_lag_boundary_month_included_matches_build_sql():
    """The EXACT publication-lag boundary: asof 2026-07-11 -> guard cutoff 2026-06-01 (June's first knowable
    day). build_sql serves June via `substr(...) <= '2026-06-01'`; the oracle must agree. Pre-fix the raw
    '2026-06-01 00:00:00.000' <= '2026-06-01' was False and June was hidden -- the oracle/SQL divergence at the
    very boundary this wave exists to guarantee. Lock the two engines together on the shared cutoff literal."""
    ts = _ts()
    kept = _pit(PS_ROWS, ts, table=TID, metric="palm_oil_cpo_usd_t", asof="2026-07-11")
    months = {r["date"][:7] for r in kept}
    assert "2026-06" in months and max(months) == "2026-06"        # June knowable at its exact lag boundary
    sql = Q.build_sql(Q.NumberQuery(table=TID, metric="palm_oil_cpo_usd_t", asof="2026-07-11"), ts)
    assert "substr(CAST(date AS varchar), 1, 10) <= '2026-06-01'" in sql   # same cutoff the oracle used


# ======================================================================================================
# revision_stamp in rows + citation meta.
# ======================================================================================================
def test_pink_sheet_revision_stamp_surfaces_in_citation_meta():
    call = {"query": {"table": TID, "metric": "palm_oil_cpo_usd_t", "asof": "2026-07-12"},
            "rows": [{"value": 1030.0, "knowledge_date": "2026-06-01", "revision_stamp": "2026M07"}]}
    cits = A.to_citations([call])
    assert cits and cits[0].kind == "number"
    row0 = cits[0].payload["rows"][0]
    assert row0["revision_stamp"] == "2026M07"                     # the WB release stamp rides the citation


# ======================================================================================================
# R5 decline guard battery.
# ======================================================================================================
def test_decline_templates_keys_match_lint_census_set():
    assert set(A.DECLINE_TEMPLATES) == set(CC_LINT._NONE_TIER_DECLINE)


def test_decline_templates_and_prefaces_register_clean_zero_counters():
    for name in CC_LINT._NONE_TIER_DECLINE:
        tmpl = A.DECLINE_TEMPLATES[name]
        pre = A._price_decline_preface(name)
        assert REG.register_leaks(tmpl) == [], (name, REG.register_leaks(tmpl))
        assert REG.register_leaks(pre) == [], (name, REG.register_leaks(pre))
        assert REG.count_valuation_words(pre) == 0 and REG.count_flow_words(pre) == 0, name
    # the robusta template wording is fixed by the plan (false-scarcity ban): governed-column, not missing data.
    assert "no robusta series is in our governed price columns" in A.DECLINE_TEMPLATES["robusta"]
    assert "arabica (KC) is not a substitute" in A.DECLINE_TEMPLATES["robusta"]


@pytest.mark.parametrize("q,name", [
    ("what is robusta trading at today", "robusta"),
    ("white sugar price per tonne", "white_sugar"),
    ("MATIF milling wheat price", "french_wheat_matif"),
    ("price of Euronext maize", "french_maize_matif"),
    ("JSE white maize quote", "jse_white_maize"),
    ("SAFEX yellow maize price", "jse_yellow_maize"),
    ("rapeseed meal price", "rapeseed_meal_zce"),
])
def test_price_coverage_scope_fires_on_none_tier_price_asks(q, name):
    assert A.price_coverage_scope(q) == name


@pytest.mark.parametrize("q", [
    "is palm cheap versus soyoil right now",     # covered (palm/soy oil) -- never fire
    "soybean oil price today",                   # covered
    "US HRW wheat price",                         # covered (wheat_us_hrw)
    "raw sugar price",                            # covered (raw_sugar_world) -- not 'white sugar'
    "rapeseed oil price per tonne",               # covered (rapeseed_oil) -- not 'rapeseed meal'
    "any robusta news today?",                    # a NONE-tier NAME but NO price intent -> fail toward None
    "white maize planting progress in South Africa",   # NONE-tier crop, no price intent
    # F1: "milling wheat" is ALSO a global quality grade (milling vs feed); a bare/US-qualified milling-wheat
    # PRICE ask is a COVERED wheat_us_hrw/srw series and must NOT degrade to the MATIF decline (no EU/MATIF
    # qualifier present) -- the code's own "require an EXCHANGE/origin qualifier" invariant.
    "us milling wheat price",                     # covered US wheat, price intent, no MATIF qualifier
    "hard red winter milling wheat price",        # covered HRW, quality-grade phrasing
    "us milling wheat cost",                       # covered, 'cost' intent
    "milling wheat premium over feed wheat",       # grade spread, both covered; no EU qualifier
    "feed wheat vs milling wheat basis",           # grade basis, covered; no EU qualifier
    # F2: broad quantity/logistics vocabulary must NOT read as price intent on a NONE-tier name (ambiguity
    # fails toward None). Volume ("how much ... produce/export", "production/inventory/stock levels"),
    # merchants ("trading houses"), and operational "basis risk" are not valuation asks.
    "how much robusta did vietnam produce",
    "how much robusta was exported",
    "robusta production levels this year",
    "robusta inventory levels",
    "robusta stock levels in warehouses",
    "robusta trading houses in vietnam",
    "robusta basis risk in the supply chain",
])
def test_price_coverage_scope_never_fires_on_covered_or_nonprice(q):
    assert A.price_coverage_scope(q) is None


def test_decline_preface_prepended_and_guard_key_returned():
    """The reader-facing caveat is PREPENDED deterministically (prompt-independent) and answer_numbers
    returns the price_decline_guard key with the NONE-tier name."""
    client = FakeClient([_resp([_text("I can't find a robusta figure.")])])
    out = A.answer_numbers("what is robusta trading at today", asof="2026-07-12",
                           client=client, query_fn=lambda sql: [])
    assert out["price_decline_guard"] == "robusta"
    assert out["answer"].startswith("One limitation to flag before the numbers:")
    assert REG.register_leaks(REG.sanitize(out["answer"])) == []


def test_covered_price_ask_is_byte_identical_no_guard():
    """A covered ask never fires the guard -- no preface, no key (byte-identical path)."""
    client = FakeClient([_resp([_text("Palm CPO was 1,030 USD/mt in June 2026 [2026-06-01].")])])
    out = A.answer_numbers("what was the palm oil price in June", asof="2026-07-12",
                           client=client, query_fn=lambda sql: [])
    assert "price_decline_guard" not in out
    assert out["answer"].startswith("Palm CPO was")


# ======================================================================================================
# W2.5 trace plumbing (run_numbers_only copies the guard keys) -- and the ESR copy does not regress.
# ======================================================================================================
def _orch():
    from leviathan.graphrag import orchestrator as orch
    return orch


def test_run_numbers_only_copies_price_decline_guard_into_trace(monkeypatch):
    orch = _orch()
    from leviathan.graphrag.numbers import agent as na
    monkeypatch.setattr(na, "answer_numbers", lambda *a, **k: {
        "answer": "One limitation to flag before the numbers: no robusta series...\n\nUnavailable.",
        "calls": [], "price_decline_guard": "robusta"})
    out = orch.run_numbers_only("robusta price?", "2026-07-12")
    assert out["trace"]["price_decline_guard"] == "robusta"
    assert "numbers_verifier" in out["trace"]                       # pre-existing keys still ride
    assert "banned_valuation_words" in out["trace"] and "banned_flow_words" in out["trace"]


def test_run_numbers_only_copies_esr_destination_guard_into_trace(monkeypatch):
    """The existing ESR guard key was DROPPED at the orchestrator boundary before W2.5; the copy loop now
    surfaces it too (S3.F2) without disturbing the ESR-only tests, which read answer_numbers' return dict."""
    orch = _orch()
    from leviathan.graphrag.numbers import agent as na
    monkeypatch.setattr(na, "answer_numbers", lambda *a, **k: {
        "answer": "One limitation to flag...\n\nNational total.", "calls": [],
        "esr_destination_guard": "China"})
    out = orch.run_numbers_only("corn sales to China?", "2026-07-12")
    assert out["trace"]["esr_destination_guard"] == "China"
    assert "price_decline_guard" not in out["trace"]               # absent guard -> key not added


def test_run_numbers_only_no_guard_trace_is_unchanged(monkeypatch):
    orch = _orch()
    from leviathan.graphrag.numbers import agent as na
    monkeypatch.setattr(na, "answer_numbers", lambda *a, **k: {"answer": "Corn stocks were 1,234.", "calls": []})
    out = orch.run_numbers_only("corn ending stocks?", "2026-07-12")
    assert set(out["trace"]) == {"numbers_verifier", "banned_valuation_words", "banned_flow_words"}


# ======================================================================================================
# Reconcile + contract-check coupling.
# ======================================================================================================
def test_pink_sheet_in_numbers_tables_tuple_and_reconciles_clean():
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    assert TID in RC.NUMBERS_TABLES
    reg = SR.load_registry()
    divs = [d for d in RC.reconcile_numbers(reg) if d.table == TID]
    assert divs == [], [d.detail for d in divs]
    c = reg.table(TID)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert c["knowledge_semantics"] == "data_date" and c["publication_lag_days"] == 40


def test_pink_sheet_now_in_numbers_scope_for_contract_check():
    """Dropped from the feature-only set: silver_pink_sheet is now a numbers table, so contract_check sees
    it in scope (the FR-001 feature-only footer path no longer owns it)."""
    reg = load_registry()
    assert TID in CC._numbers_table_ids(reg)


# ======================================================================================================
# W3.1 GOLDEN RIDER -- REAL rows snapshotted from Athena by the W3.0 probe battery (2026-07-21, WB
# release 2026M07). These are hand-copied fixtures, not live queries: they pin the ENGINE's behavior
# against genuine production values (the table is latest-only and WB revises retroactively, so the
# live values may drift -- the fixture does not). Feb-2011 is the food-crisis spike (palm z ~ +1.95);
# Jun-2020 is the COVID trough (Brent 39.9).
# ======================================================================================================
GOLDEN_ROWS = [
    {"date": "2011-02-01 00:00:00.000", "palm_oil_cpo_usd_t": 1327.0, "soybean_oil_usd_t": 1360.0,
     "urea_usd_mt": 297.5, "brent_crude_usd_bbl": 104.0, "raw_sugar_world_usd_t": 650.0,
     "wheat_us_hrw_usd_t": 348.1, "palm_oil_cpo_usd_t_zscore_5yr": 1.9520930348498196,
     "latest_release_ym": "2026M07"},
    {"date": "2020-06-01 00:00:00.000", "palm_oil_cpo_usd_t": 656.0, "soybean_oil_usd_t": 756.0,
     "urea_usd_mt": 202.0, "brent_crude_usd_bbl": 39.9, "raw_sugar_world_usd_t": 270.0,
     "wheat_us_hrw_usd_t": 198.4, "palm_oil_cpo_usd_t_zscore_5yr": -0.22522786001448222,
     "latest_release_ym": "2026M07"},
    {"date": "2026-04-01 00:00:00.000", "palm_oil_cpo_usd_t": 1146.0, "soybean_oil_usd_t": 1643.0,
     "urea_usd_mt": 856.9, "brent_crude_usd_bbl": 120.4, "raw_sugar_world_usd_t": 320.0,
     "wheat_us_hrw_usd_t": 282.0, "palm_oil_cpo_usd_t_zscore_5yr": 0.40872766660060955,
     "latest_release_ym": "2026M07"},
    {"date": "2026-05-01 00:00:00.000", "palm_oil_cpo_usd_t": 1136.0, "soybean_oil_usd_t": 1781.0,
     "urea_usd_mt": 770.5, "brent_crude_usd_bbl": 107.5, "raw_sugar_world_usd_t": 340.0,
     "wheat_us_hrw_usd_t": 303.0, "palm_oil_cpo_usd_t_zscore_5yr": 0.3634810614418705,
     "latest_release_ym": "2026M07"},
    {"date": "2026-06-01 00:00:00.000", "palm_oil_cpo_usd_t": 1105.0, "soybean_oil_usd_t": 1765.0,
     "urea_usd_mt": 453.1, "brent_crude_usd_bbl": 85.4, "raw_sugar_world_usd_t": 320.0,
     "wheat_us_hrw_usd_t": 286.0, "palm_oil_cpo_usd_t_zscore_5yr": 0.21561525009156313,
     "latest_release_ym": "2026M07"},
]


def test_golden_lag_makes_june_knowable_from_jul21_but_not_jul05():
    """Real-row PIT: on 2026-07-21 (lag-40 guard 2026-06-11) the June observation IS knowable and is the
    latest month; on 2026-07-05 (guard 2026-05-26) June is hidden and May's 1136.0 serves -- the exact
    DP-3 semantics the probe validated against the live release calendar (2026M07 carries June data)."""
    ts = _ts()
    late = _pit(GOLDEN_ROWS, ts, table=TID, metric="palm_oil_cpo_usd_t", asof="2026-07-21")
    assert [r["date"][:10] for r in late][-1] == "2026-06-01"
    early = _pit(GOLDEN_ROWS, ts, table=TID, metric="palm_oil_cpo_usd_t", asof="2026-07-05")
    assert [r["date"][:10] for r in early][-1] == "2026-05-01"
    assert early[-1]["palm_oil_cpo_usd_t"] == 1136.0


def test_golden_food_crisis_and_covid_rows_survive_pit_with_stamp():
    """Historical asks serve the real values with the release stamp: a 2011-06-30 asof sees the Feb-2011
    spike row (palm 1327.0, z ~ +1.95); a 2020-08-31 asof window catches the COVID trough (Brent 39.9)."""
    ts = _ts()
    crisis = _pit(GOLDEN_ROWS, ts, table=TID, metric="palm_oil_cpo_usd_t", asof="2011-06-30")
    assert crisis and crisis[-1]["palm_oil_cpo_usd_t"] == 1327.0
    assert abs(crisis[-1]["palm_oil_cpo_usd_t_zscore_5yr"] - 1.952) < 0.01
    covid = _pit(GOLDEN_ROWS, ts, table=TID, metric="brent_crude_usd_bbl", asof="2020-08-31",
                 period_start="2020-06-01", period_end="2020-06-30")
    assert [r["brent_crude_usd_bbl"] for r in covid] == [39.9]
    assert covid[0]["latest_release_ym"] == "2026M07"
