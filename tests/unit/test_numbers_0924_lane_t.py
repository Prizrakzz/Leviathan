"""THE 09-24 FIX ROUND 2, LANE T -- the numbers cards, query, agent, stats and the cascade print sites.

Every pin below is held against the SHAPE the 09-24 re-smoke served (fix_round_0924/BRIEF_T.md, the ten pages
and traces under resmoke_0924/answers): the WASDE rows are the store's own rows for the 2024-02-08 and
2026-09-11 releases (read-only, P-2), the ESR rows are the store's soybean destination weeks (P-3), the pair
legs are the Pink Sheet's 2026-08 prints, the change rows are palm/rape's N11-N13.

  T-1 / B9  the numbers seat prompt and both tool schemas do not move by a byte
  T-2 / K22 a lookup of a commodity serves ITS sheet; the sheet names the unit; `table_type` rides the row
  T-3 / K24 a closed marketing year's last week says so, and the year's total is the query layer's own sum
  T-4 / O-9 the cascade print sites print HEAD's `{:+g}` flag-off and the ONE precision producer under the key,
            and `_shown` binds exactly the printed magnitude
  T-5 / K5  a window_change row carries its stat, its two observations and the calculator's own percent
  T-6       a directional z label names the side the reading sits on (labels_low)
  K8        the pair row names its leg order and its period; the record says which producer minted it
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import types

import pytest

from leviathan.graphrag import config_check as CC
from leviathan.graphrag import reasoning_modes as RM
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import cascade as CQ
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R
from leviathan.graphrag.numbers import stats as ST

# B9 -- the SAME constants round 1 banked (test_numbers_card_fields.py), re-measured this sitting on the
# head0a76 shadow and on the tree: identical (fix_round_0924/t_work/b9/B9full_{head,tree}.out).
B9_NUMBERS_PROMPT_SHA256 = "3caa2d83e7752c7baa6f72cd3c07ee663632623889dc4c9e780bd02ffd95adc5"
B9_NUMBERS_PROMPT_CHARS = 255421
B9_TOOL_SCHEMA_SHA256 = "fea04e3d23c49344b4ce4e19e9ff61f73b93703fcada017442106bfbbb60bab8"
B9_STATS_TOOL_SCHEMA_SHA256 = "f11a75a605db17f8f8c2ac7801dae55d475924f6df7b90d3d8b55412588699c7"


@pytest.fixture()
def clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("GRAPHRAG_"):
            monkeypatch.delenv(k, raising=False)
    R.load_registry.cache_clear()
    yield
    R.load_registry.cache_clear()


# ══ T-1 / B9 ════════════════════════════════════════════════════════════════════════════════════════
def test_T1_the_numbers_prompt_and_both_tool_schemas_are_byte_identical(clean_env):
    reg = R.load_registry()
    sp = A.system_prompt(reg)
    assert len(sp) == B9_NUMBERS_PROMPT_CHARS
    assert hashlib.sha256(sp.encode("utf-8")).hexdigest() == B9_NUMBERS_PROMPT_SHA256
    ts = json.dumps(A.tool_schema(reg), sort_keys=True, default=str)
    ss = json.dumps(A.stats_tool_schema(), sort_keys=True, default=str)
    assert hashlib.sha256(ts.encode("utf-8")).hexdigest() == B9_TOOL_SCHEMA_SHA256
    assert hashlib.sha256(ss.encode("utf-8")).hexdigest() == B9_STATS_TOOL_SCHEMA_SHA256


def test_T1_the_card_unit_phrase_set_the_verifier_reads_on_every_cell_is_HEADs(clean_env):
    """`registry.card_unit_phrases` feeds the verifier's unit vocabulary on BOTH cells; this round's display
    declarations reuse "%" (already declared on the PSD ratio), so the set is HEAD's to the member --
    measured on the head0a76 shadow (fix_round_0924/t_work/drives/cup_{head,tree}.json): 0 added, 0 removed."""
    R._card_unit_phrases_cached.cache_clear()
    got = R.card_unit_phrases()
    assert "percentage points" not in got and "%" in got
    assert "million hundredweight" not in got                             # sheet units ride the ROW, not the card


def test_T1_no_round2_field_name_or_sheet_id_reaches_the_prompt(clean_env):
    sp = A.system_prompt(R.load_registry())
    for name in ("figure_basis", "definition_phrases", "period_sum", "unit_from_sheet", "sheet_col",
                 "table_type_col", "commodity_families", "class_scope", "labels_low",
                 "u_s_total_rice_supply_and_use", "u_s_soybeans_and_products_supply_and_use",
                 "MMT, milled basis", "medium- and short-grain rice"):
        assert name not in sp, name
    # the figure_basis VALUES are the descs' own words by design ("new sales booked in the week"), so the
    # prompt already carries them -- the pin is that the prompt is unchanged (above), not that they are absent


# ══ T-2 / K22 -- THE SHEET A ROW WAS PRINTED ON ══════════════════════════════════════════════════════
_WASDE_COLS = ("commodity", "table_type", "region", "marketing_year", "attribute", "estimate", "release_date",
               "estimate_role", "projection_month", "source_table_id", "unit")


def _wasde_db(rows):
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH ':memory:' AS leviathan_dev")
    con.execute("CREATE TABLE leviathan_dev.silver_wasde (commodity TEXT, table_type TEXT, region TEXT, "
                "marketing_year TEXT, attribute TEXT, estimate REAL, release_date TEXT, estimate_role TEXT, "
                "projection_month TEXT, source_table_id TEXT, unit TEXT)")
    con.executemany("INSERT INTO leviathan_dev.silver_wasde VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r.get(c) for c in _WASDE_COLS) for r in rows])

    def qfn(sql):
        cur = con.execute(sql)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]
    return qfn


def _w(sheet, value, unit, *, com="soybeans", tt="us", region="united_states", my="2023/24",
       attr="production", rd="2024-02-08", role="projection", pm="February"):
    return {"commodity": com, "table_type": tt, "region": region, "marketing_year": my, "attribute": attr,
            "estimate": value, "release_date": rd, "estimate_role": role, "projection_month": pm,
            "source_table_id": sheet, "unit": unit}


# The store's own rows (P-2, release 2024-02-08, US soybeans 2023/24 production; both projection months).
_SOY_2024 = [_w("u_s_soybeans_and_products_supply_and_use", 54154.0, "1 Thousand Short2 Tons 3 4", pm="January"),
             _w("u_s_soybeans_and_products_supply_and_use", 54154.0, "1 Thousand Short2 Tons 3 4"),
             _w("u_s_soybeans_supply_and_use", 4165.0, "Million Bushels", pm="January"),
             _w("u_s_soybeans_supply_and_use", 4165.0, "Million Bushels")]
# The store's own rows (P-2, release 2026-09-11, US rice 2026/27 production).
_RICE_2026 = [_w("u_s_long_grain_rice_supply_and_use", 103.5, None, com="rice", my="2026/27",
                 rd="2026-09-11", pm="September"),
              _w("u_s_medium_short_grain_rice_supply_and_use", 54.6, None, com="rice", my="2026/27",
                 rd="2026-09-11", pm="September"),
              _w("u_s_total_rice_supply_and_use", 158.2, "Million Hundredweight", com="rice", my="2026/27",
                 rd="2026-09-11", pm="September")]


def _spec(com, asof, period, metric="production", country="united_states"):
    return Q.NumberQuery(table="silver_wasde", metric=metric, asof=asof, commodity=com, country=country,
                         period=period)


def test_K22_the_precedence_is_DERIVED_from_the_one_sheets_declaration(clean_env):
    ts = R.load_registry().get("silver_wasde")
    own = [sid for sid, sp in ts.sheets.items() if sp.serves == "all_classes"]
    term = ts.vintage_tiebreak[2]
    assert term.col == ts.sheet_col == "source_table_id" and term.role_order == own
    assert ts.vintage_tiebreak[3].col == "source_table_id" and ts.vintage_tiebreak[3].role_order == []
    # idempotent: re-validating the spec never ranks twice
    again = R.TableSpec.model_validate(ts.model_dump())
    assert [t.col for t in again.vintage_tiebreak] == [t.col for t in ts.vintage_tiebreak]
    # a card declaring no sheets gains nothing (every other card's SQL is byte-identical)
    assert R.load_registry().get("silver_psd").vintage_tiebreak == []
    bare = R.TableSpec(id="x", description="d", shape="tall", vintage_tiebreak=[{"col": "sid", "dir": "asc"}])
    assert [t.col for t in bare.vintage_tiebreak] == ["sid"]


def test_K22_the_2024_soybean_lookup_serves_the_BEANS_sheet_never_the_meal_sheet(clean_env):
    """THE FATAL 2024 ROW: 'US soybean production projected at 54,154 1 Thousand Short2 Tons 3 4 [N4]' --
    the MEAL sub-table of the 'Soybeans and Products' page won the grain BY ALPHABET."""
    qfn = _wasde_db(_SOY_2024)
    rows = Q.run(_spec("soybeans", "2024-03-01", "2023/24"), query_fn=qfn)
    assert [(r["value"], r["unit"], r["table_type"]) for r in rows] == [(4165.0, "Million Bushels", "us")]
    assert all(Q.SHEET_ALIAS not in r for r in rows)                  # the internal sheet id never ships


def test_K22_the_2026_rice_lookup_serves_the_ALL_CLASS_total_never_a_class_sheet(clean_env):
    """'production 103.5 [N1]' with no unit and no class was the LONG-GRAIN class (the total is 158.2)."""
    qfn = _wasde_db(_RICE_2026)
    rows = Q.run(_spec("rice", "2026-09-24", "2026/27"), query_fn=qfn)
    assert [(r["value"], r["unit"], r["table_type"]) for r in rows] == [(158.2, "Million Hundredweight", "us")]


def test_K22_the_python_oracle_picks_the_same_sheet_as_the_sql(clean_env):
    ts = R.load_registry().get("silver_wasde")
    raw = [{**r, "release_date": r["release_date"]} for r in _RICE_2026]
    kept = Q.apply_pit_filter(raw, _spec("rice", "2026-09-24", "2026/27"), ts)
    assert [r["source_table_id"] for r in kept] == ["u_s_total_rice_supply_and_use"]


def test_K22_the_sheet_names_the_unit_blank_beats_a_false_one_and_an_undeclared_sheet_keeps_its_own(clean_env):
    # a world-table row: the source prints no unit (or "Milled Basis"); the card's sheet names it
    world = [_w("world_soybean_supply_and_use", 8.85, None, tt="world", my="2025/26", attr="ending_stocks",
                rd="2026-09-11", role="estimate", pm=None),
             _w("u_s_soybeans_supply_and_use", 325.0, "Million Bushels", my="2025/26", attr="ending_stocks",
                rd="2026-09-11", role="estimate", pm=None)]
    rows = Q.run(_spec("soybeans", "2026-09-24", "2025/26", metric="ending_stocks"), query_fn=_wasde_db(world))
    assert sorted((r["value"], r["unit"], r["table_type"]) for r in rows) == [
        (8.85, "MMT", "world"), (325.0, "Million Bushels", "us")]
    # the products page when it is the ONLY US sheet (2010): the pick is HEAD's, the junk unit is blanked
    only = [_w("u_s_soybeans_and_products_supply_and_use", 39533.0, "Domestic Measure", my="2010/11",
               rd="2010-12-10", pm="December")]
    rows = Q.run(_spec("soybeans", "2010-12-31", "2010/11"), query_fn=_wasde_db(only))
    assert [(r["value"], r["unit"]) for r in rows] == [(39533.0, "")]
    # an OCR-fragment sheet the card never declared keeps its raw unit and HEAD's rank
    ocr = [_w("world_corn_supply_and_use_united_states_102_61_209_56_0_05_119_74", 7.1, "Cont'd.", com="corn",
              my="1988/89", rd="1989-03-09", role="estimate", pm=None)]
    rows = Q.run(_spec("corn", "1989-03-31", "1988/89"), query_fn=_wasde_db(ocr))
    assert [(r["value"], r["unit"]) for r in rows] == [(7.1, "Cont'd.")]


def test_K22_a_metric_that_does_not_declare_unit_from_sheet_keeps_the_governing_override(clean_env):
    price = [_w("u_s_total_rice_supply_and_use", 14.9, "$/cwt", com="rice", my="2026/27", attr="avg_farm_price",
                rd="2026-09-11", pm="September"),
             _w("u_s_long_grain_rice_supply_and_use", 14.3, "$/cwt", com="rice", my="2026/27",
                attr="avg_farm_price", rd="2026-09-11", pm="September")]
    rows = Q.run(_spec("rice", "2026-09-24", "2026/27", metric="avg_farm_price"), query_fn=_wasde_db(price))
    assert [(r["value"], r["unit"]) for r in rows] == [(14.9, "$/cwt")]   # all-class price; unit_overrides


def test_K22_every_other_card_compiles_byte_identical_sql(clean_env):
    spec = Q.NumberQuery(table="silver_psd", metric="su_ratio", asof="2026-09-24", commodity="corn_cbot",
                         country="United States")
    sql = Q.build_sql(spec)
    assert "table_type" not in sql and "_sheet" not in sql


def test_K22_the_family_rule_says_all_classes_on_every_class_slug(clean_env):
    for slug in ("soft_red_winter_wheat_cbot", "hard_red_winter_wheat_kcbt", "hard_red_spring_wheat_mgex",
                 "french_wheat_matif"):
        cs = R.class_scope("silver_psd", slug)
        assert cs["family"] == "wheat" and cs["class_scope"] == "all_classes", slug
    assert R.class_scope("silver_psd", "rough_rice_cbot")["basis"] == "milled basis"
    assert R.class_scope("silver_psd_attributes", "corn_cbot")["class_scope"] == "all_classes"
    assert R.class_scope("silver_psd", "soybeans_cbot")["class_scope"] == ""       # one sheet, no class
    assert R.class_scope("silver_psd", "cocoa") == {} and R.class_scope("no_such_card", "x") == {}


def test_K22_the_readers_never_raise_and_never_default(clean_env):
    assert R.sheet_spec("silver_wasde", "u_s_rice_supply_and_use")["serves"] == "medium- and short-grain rice"
    assert R.sheet_spec("silver_wasde", "nope") == {} and R.sheet_spec("no_card", "x") == {}
    assert R.figure_basis("silver_psd", "su_ratio") == "of domestic use"
    assert R.figure_basis("silver_esr", "weekly_exports_1000mt") == "shipped in the week"
    assert R.figure_basis("silver_esr", "gross_new_sales_1000mt") == "booked in the week"
    assert R.figure_basis("silver_esr", "outstanding_sales_1000mt") == "" == R.figure_basis("nope", "x")
    ph = R.definition_phrases("gold_weather_z", "tmax_anomaly_tail_share")
    assert ph == ("at or beyond +2 sigma",) and R.definition_phrases("nope", "x") == ()
    assert ("gold_weather_z", "heat_stress_z_tail_share") in R.definition_phrases()


def test_K7_the_su_ratio_family_answers_its_display_spec(clean_env):
    assert R.display_spec("silver_psd", "su_ratio") == (100.0, "%", 2)
    assert R.display_spec("silver_icco_cocoa", "su_ratio") == (100.0, "%", 2)
    # su_ratio_yoy_delta is DELIBERATELY undeclared: a "percentage points" display unit would join
    # `card_unit_phrases` and move the verifier's card-vs-spelling split on the CONTROL cell (flag-off law)
    assert R.display_spec("silver_psd", "su_ratio_yoy_delta") == (None, None, None)
    assert R.display_spec("silver_mpob", "su_ratio") == (1.0, "months of export cover", 2)
    # undeclared metrics answer nothing: the precision producer's own rule (round-1 C5) is the default
    assert R.display_spec("silver_pink_sheet", "palm_oil_cpo_usd_t_zscore_5yr") == (None, None, None)


# ══ T-3 / K24 -- THE CLOSED MARKETING YEAR ═══════════════════════════════════════════════════════════
_ESR_COLS = ("commodity", "commodity_name", "market_year", "country_code", "week_ending_date",
             "weekly_exports_1000mt", "outstanding_sales_1000mt", "gross_new_sales_1000mt", "changes_1000mt",
             "as_of_date")


def _esr_db(rows):
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH ':memory:' AS leviathan_dev")
    con.execute("CREATE TABLE leviathan_dev.silver_esr_compact (commodity TEXT, commodity_name TEXT, "
                "market_year INTEGER, country_code TEXT, week_ending_date TEXT, weekly_exports_1000mt REAL, "
                "outstanding_sales_1000mt REAL, gross_new_sales_1000mt REAL, changes_1000mt REAL, "
                "as_of_date TEXT)")
    con.executemany("INSERT INTO leviathan_dev.silver_esr_compact VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r.get(c) for c in _ESR_COLS) for r in rows])

    def qfn(sql):
        cur = con.execute(sql)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]
    return qfn


def _e(my, week, exports, outstanding, gross, *, code="5700", asof="20260917"):
    return {"commodity": "soybeans_cbot", "commodity_name": "soybeans_cbot", "market_year": my,
            "country_code": code, "week_ending_date": week, "weekly_exports_1000mt": exports,
            "outstanding_sales_1000mt": outstanding, "gross_new_sales_1000mt": gross, "changes_1000mt": 0.0,
            "as_of_date": asof}


# The P-3 shape (the store's soybean China weeks): MY2025/26 (physical label 2026) through the carry week to
# 2026-09-03, and MY2026/27 (label 2027) opening that same week in the 09-17 vintage.
_ESR_CLOSED = [_e(2026, "2026-07-02", 268.117, 68.0, 1.688), _e(2026, "2026-08-06", 65.936, 141.0, 0.0),
               _e(2026, "2026-08-27", 0.0, 141.0, 0.0), _e(2026, "2026-09-03", 0.0, 5.0, 0.0),
               _e(2027, "2026-09-03", 0.0, 8983.0, 1222.0), _e(2027, "2026-09-10", 328.25, 9530.0, 879.05)]


def _esr_call(metric, period, asof, qfn):
    spec = A._forced_spec(asof, {"table": "silver_esr", "metric": metric, "commodity": "soybeans_cbot",
                                 "country": "China", "period": period, "agg": "series"})
    rows = [r for r in Q.run(spec, query_fn=qfn) if r.get("value") not in (None, "")]
    return {"query": spec.model_dump(exclude_none=True), "rows": rows, "status": "ok", "handle": "L1"}


def test_T3_a_closed_years_last_week_says_so_and_the_year_total_is_the_query_layers_sum(clean_env):
    qfn = _esr_db(_ESR_CLOSED)
    call = _esr_call("weekly_exports_1000mt", "2025", "2026-09-24", qfn)
    legs, rec = A.esr_closed_year_legs([call], "2026-09-24", qfn)
    newest = max(call["rows"], key=lambda r: r["data_date"])
    assert newest["data_date"] == "2026-09-03"
    assert newest["period_role"] == "the last week of the closed 2025/26 year"
    assert len(legs) == 1 and legs[0]["query"]["agg"] == "sum" and legs[0]["query"]["period"] == "2025"
    assert legs[0]["query"]["country"] == "China" and legs[0]["closed_year_of"] == "L1"
    assert legs[0]["rows"][0]["value"] == pytest.approx(268.117 + 65.936)
    assert rec == {"stamped": [{"handle": "L1", "metric": "weekly_exports_1000mt", "year": "2025/26"}],
                   "companions": 1, "declined": []}


def test_T3_an_open_year_and_a_year_the_store_has_not_yet_succeeded_mint_nothing(clean_env):
    qfn = _esr_db(_ESR_CLOSED)
    open_call = _esr_call("weekly_exports_1000mt", "2026", "2026-09-24", qfn)      # MY2026/27 itself
    legs, rec = A.esr_closed_year_legs([open_call], "2026-09-24", qfn)
    assert legs == [] and all("period_role" not in r for r in open_call["rows"])
    assert rec["declined"][0]["reason"] == "next_year_not_in_store"
    # the year ENDED on 08-31 but the store's vintage holds no successor yet: a store fact, never a calendar
    gap = _esr_db([dict(r, as_of_date="20260904") for r in _ESR_CLOSED if r["market_year"] == 2026
                   and r["week_ending_date"] <= "2026-08-27"])
    call = _esr_call("weekly_exports_1000mt", "2025", "2026-09-09", gap)
    legs, rec = A.esr_closed_year_legs([call], "2026-09-09", gap)
    assert legs == [] and all("period_role" not in r for r in call["rows"])


def test_T3_a_BALANCE_is_stamped_and_never_summed_and_a_national_read_is_left_alone(clean_env):
    qfn = _esr_db(_ESR_CLOSED)
    bal = _esr_call("outstanding_sales_1000mt", "2025", "2026-09-24", qfn)
    legs, rec = A.esr_closed_year_legs([bal], "2026-09-24", qfn)
    assert legs == [] and rec["companions"] == 0
    assert max(bal["rows"], key=lambda r: r["data_date"])["period_role"].startswith("the last week of the closed")
    national = dict(bal, query={k: v for k, v in bal["query"].items() if k != "country"})
    assert A.esr_closed_year_legs([national], "2026-09-24", qfn) == ([], {})


def test_T3_the_kwarg_is_absent_by_default_and_arms_the_leg_only_when_threaded(clean_env):
    import inspect
    p = inspect.signature(A.answer_numbers).parameters
    assert p["closed_year"].default is False and list(p)[-1] == "closed_year"
    assert A.ESR_CLOSED_YEAR_KEY == "esr_closed_year"


# ══ T-5 / K5 -- THE WINDOW ON THE CHANGE ROW ══════════════════════════════════════════════════════════
_WC_RES = {"stat": "window_change", "declined": False, "value": 10289.0, "n": 8, "start_val": 2814199.0,
           "end_val": 2824488.0, "pct_change": 100.0 * 10289.0 / 2814199.0, "t1": 0, "t2": -1}


def test_T5_board_off_the_change_row_is_HEADs_to_the_byte(clean_env):
    head = A._stat_calls("window_change", dict(_WC_RES), {"stat": "window_change"}, "MT", "2026-08-01",
                         dates=["2026-%02d-01" % m for m in range(1, 9)])
    assert set(head[0]["rows"][0]) == {"value", "unit", "knowledge_date"} and "shown" not in head[0]


def test_T5_board_on_the_change_row_carries_its_stat_window_and_the_calculators_own_percent(clean_env):
    obs = ["2026-%02d-01" % m for m in range(1, 9)]
    out = A._stat_calls("window_change", dict(_WC_RES), {"stat": "window_change"}, "MT", "2026-08-01",
                        dates=obs, board=True, obs=obs)
    row = out[0]["rows"][0]
    assert row["stat"] == "window_change"
    assert row["window"] == {"from": "2026-01-01", "to": "2026-08-01"}
    assert row["pct_change"] == pytest.approx(0.3656, abs=1e-4)              # +0.37 %, never re-divided
    assert out[0]["shown"] == [10289.0, row["pct_change"]]
    assert out[0]["query"] == {"table": A.STATS_TOOL_NAME, "metric": "window_change"}   # no period moves


def test_T5_a_year_month_card_states_its_window_in_its_own_months(clean_env):
    """palm/rape N12 (MPOC China: year/month rows, no date alias) -- the window the page could not state."""
    rows = [{"value": v, "year": 2026, "month": m} for m, v in ((1, 242000.0), (3, 300000.0), (6, 412000.0))]
    rows.insert(1, {"value": None, "year": 2026, "month": 2})                  # dropped by `_cell_float`
    assert A._obs_axis(rows) == ["2026-01", "2026-03", "2026-06"]
    assert A._date_axis(rows) == ["", "", ""]                                  # the RV/window axis is untouched
    res = {"stat": "window_change", "declined": False, "value": 170000.0, "n": 3, "pct_change": 70.25,
           "t1": 0, "t2": -1}
    out = A._stat_calls("window_change", res, {}, "MT", None, board=True, obs=A._obs_axis(rows))
    assert out[0]["rows"][0]["window"] == {"from": "2026-01", "to": "2026-06"}
    # a misaligned or part-dated axis states NO window -- silence, never a guessed span
    assert A._change_window(res, ["2026-01", ""]) is None and A._change_window(res, []) is None


# ══ K8 -- THE PAIR ROW NAMES ITS ORDER AND ITS PERIOD ═════════════════════════════════════════════════
def _pink_leg(metric, value, date="2026-08-01"):
    return {"query": {"table": "silver_pink_sheet", "metric": metric},
            "rows": [{"value": value, "unit": "", "data_date": date, "knowledge_date": date}], "status": "ok"}


_SCOPE = ("malaysian_crude_palm_oil_cme", "soybean_oil_cbot")


def test_K8_board_on_the_minted_pair_row_says_which_way_round_and_when(clean_env):
    palm, soy = _pink_leg("palm_oil_cpo_usd_t", 1117.0), _pink_leg("soybean_oil_usd_t", 1638.0)
    rows, why = A.rv_pair_spread_legs(_SCOPE, [palm, soy], level_only=True, board=True)
    row = rows[0]["rows"][0]
    assert why is None and row["value"] == -521.0
    assert row["leg_order"] == "world crude palm oil minus world soybean oil" == rows[0]["query"]["commodity"]
    assert row["period_words"] == "August 2026"


def test_K8_board_off_the_pair_row_is_HEADs(clean_env):
    palm, soy = _pink_leg("palm_oil_cpo_usd_t", 1117.0), _pink_leg("soybean_oil_usd_t", 1638.0)
    rows, _ = A.rv_pair_spread_legs(_SCOPE, [palm, soy], level_only=True)
    assert "leg_order" not in rows[0]["rows"][0] and "period_words" not in rows[0]["rows"][0]


def test_K8_the_period_phrase_is_the_cards_own_precision(clean_env):
    assert A.period_phrase("silver_pink_sheet", "2026-08-01") == "August 2026"
    assert A.period_phrase("silver_futures_eod", "2026-09-22") == "22 September 2026"
    assert A.period_phrase("silver_esr", "2026-09-03") == "the week to 3 September 2026"
    assert A.period_phrase("silver_psd", "2025") == "2025"                    # a marketing year stays itself
    assert A.period_phrase("no_card", "2026-08-01") == "2026-08-01" and A.period_phrase("x", "") == ""


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.sent.append(kw)
        return self.outer.queue.pop(0)


class _Client:
    def __init__(self, queue):
        self.queue, self.sent = list(queue), []
        self.messages = _Msgs(self)


def _resp(content, stop):
    return types.SimpleNamespace(content=content, stop_reason=stop, usage=None)


def _tool(inp, tid):
    return types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, input=inp, id=tid)


def test_K8_the_record_keeps_legs_at_its_head_and_names_rows_minted_and_source_at_its_tail(clean_env):
    q = ("Palm oil's supply picture has been shifting. How does that reach soybean oil, and where does the "
         "balance between the two sheets stand this marketing year?")
    client = _Client([_resp([_tool({"table": "silver_pink_sheet", "metric": "palm_oil_cpo_usd_t"}, "a"),
                             _tool({"table": "silver_pink_sheet", "metric": "soybean_oil_usd_t"}, "b")],
                            "tool_use"),
                      _resp([types.SimpleNamespace(type="text", text="read both.")], "end_turn")])

    def qf(sql):
        v = 1117.0 if "palm_oil_cpo_usd_t" in sql else 1638.0
        return [{"value": str(v), "unit": "USD/mt", "data_date": "2026-08-01", "knowledge_date": "2026-08-01"}]
    out = A.answer_numbers(q, asof="2026-09-24", client=client, query_fn=qf, pair_spread=True)
    assert list(out["rv_pair_spread"]) == ["legs", "markets", "rows_minted", "source"]
    assert out["rv_pair_spread"]["legs"] == 1 == out["rv_pair_spread"]["rows_minted"]
    assert out["rv_pair_spread"]["source"] == "seat"
    minted = out["calls"][-1]["rows"][0]
    assert minted["leg_order"] == "world crude palm oil minus world soybean oil"
    assert minted["period_words"] == "August 2026"


def test_K8_the_ask_heads_row_cap_is_a_tier_fact_covering_every_board_tier():
    assert (RM.board_ask_rows("quick"), RM.board_ask_rows("deep"), RM.board_ask_rows("max")) == (3, 4, 5)
    assert RM.board_ask_rows("standard") is None and RM.board_ask_rows("deep_hp") == 4
    assert set(RM.BOARD_ASK_ROWS) == set(RM.BOARD_PRESETS)


# ══ T-6 -- A DIRECTIONAL LABEL NAMES THE SIDE ════════════════════════════════════════════════════════
def test_T6_the_low_side_takes_its_own_word_and_the_band_rule_is_otherwise_HEADs():
    head = ST.regime_flag(-1.6, [1.5], ["elevated"], kind="z_bands")
    assert head["value"] == "elevated"                                         # HEAD: |z| alone
    assert ST.regime_flag(-1.6, [1.5], ["elevated"], kind="z_bands", labels_low=["depressed"])["value"] \
        == "depressed"
    assert ST.regime_flag(1.6, [1.5], ["elevated"], kind="z_bands", labels_low=["depressed"])["value"] \
        == "elevated"
    inside = ST.regime_flag(-0.53, [1.5], ["elevated"], kind="z_bands", labels_low=["depressed"])
    assert inside["matched"] is False and inside["value"] is None             # -0.53: inside the band
    assert ST.regime_flag(-1.6, [1.5], ["elevated"], kind="z_bands", labels_low=[])["declined"]
    # an abs_bands row reads a magnitude: labels_low never applies
    assert ST.regime_flag(-0.6, [0.5], ["elevated"], kind="abs_bands", labels_low=["x"])["value"] == "elevated"


def test_T6_the_eight_directional_price_z_rows_declare_their_low_word():
    from leviathan.graphrag.state import lint as SL
    convs = SL.load_conventions()["conventions"]
    for ref in ("brent_crude_z", "urea_z", "natural_gas_us_z", "natural_gas_eu_z", "npk_fertilizer_z",
                "dap_z", "potash_z", "fishmeal_price_z"):
        assert convs[ref]["labels"] == ["elevated"] and convs[ref]["labels_low"] == ["depressed"], ref
    for ref in ("drought_z", "heat_stress_z", "fred_fx_macro"):                # magnitude words: no low side
        assert "labels_low" not in convs[ref], ref
    assert SL._check_conventions() == []


# ══ T-4 / O-9 -- THE CASCADE PRINT SITES ══════════════════════════════════════════════════════════════
def test_T4_the_display_word_is_lane_As_stamp():
    from leviathan.graphrag import answer as AN
    assert CQ.CW_DISPLAY_ANALYST == getattr(AN, "_DISPLAY_ANALYST", "analyst")


@pytest.mark.parametrize("v", [38.98436, -4.78330, 17.63521, 0.0, 0.05671, -0.0, 1234.5678, 15.0])
def test_T4_pct_print_is_HEADs_pair_off_and_the_one_producer_on(v):
    assert CQ._pct_print(v) == (f"{float(v):+g}", float(v))
    from leviathan.graphrag.state import rows as SR
    txt = SR.figure_text(float(v), two_sided=True)
    assert CQ._pct_print(v, "analyst") == (txt, float(txt))


def test_T4_each_print_site_is_HEADs_bytes_off_and_the_producers_figure_on():
    row = {"metric": "closing_stocks_palm_oil_mt", "narrate_unit": "MMT"}
    rec = {"span": "2020-08..2021-01", "move_pct": 38.98436, "contract_month": "2021-02", "label": "palm",
           "first_month": "2020-08", "last_month": "2021-01", "revision_stamp": "2026M09",
           "first_date": "2020-08-10", "last_date": "2020-12-31"}
    res = {"move_pct": 38.98436, "contract_month_used": "2021-02"}
    cells = [
        (lambda **k: CQ._fmt_pct(row, 38.98436, 7, era=1, **k), "+38.9844 %", "+38.98 %"),
        (lambda **k: CQ._chain_fmt_pct(row, 38.98436, 7, label="hop", **k), "+38.9844 %", "+38.98 %"),
        (lambda **k: CQ._episode_outcome_line(7, "malaysian_crude_palm_oil_cme", res, rec["span"],
                                              "2026-09-24", **k), "+38.9844 %", "+38.98 %"),
        (lambda **k: CQ._cw_cell_line(7, "malaysian_crude_palm_oil_cme", rec, "2026-09-24", **k),
         "+38.9844 %", "+38.98 %"),
        (lambda **k: CQ._cw_context_line(7, rec, **k), "+38.9844 %", "+38.98 %"),
        (lambda **k: CQ._cw_fx_line(7, rec, **k), "+38.9844 %", "+38.98 %"),
        (lambda **k: CQ.cot_outcome_line(7, "soybeans_cbot", event_date="2026-01-06", horizon_days=90,
                                         value=38.98436, **k), "+38.9844 %", "+38.98 %"),
    ]
    for fn, head, on in cells:
        off_line, on_line = fn(), fn(display="analyst")
        assert head in off_line and on not in off_line
        assert on in on_line and head not in on_line
        assert off_line.replace(head, on) == on_line                      # ONLY the figure moves


def test_T4_the_hop_header_speaks_the_register_under_the_key_and_is_HEADs_off():
    from leviathan.graphrag import register as RG
    off = CQ._cw_hop_header("CBOT corn", "CBOT srw wheat", ["compete for the same demand"], "b", "heat")
    on = CQ._cw_hop_header("CBOT corn", "CBOT srw wheat", ["compete for the same demand"], "b", "heat",
                           display="analyst")
    assert off == ("CONSEQUENCE HOP CBOT corn and CBOT srw wheat: the graph records these markets compete "
                   "for the same demand -- b; measured over the heat firing window, whose dated span rides "
                   "the rows for this hop.")
    assert on.startswith("CONSEQUENCE HOP CBOT corn and CBOT srw wheat:") and "firing" not in on
    masked = on.replace("CONSEQUENCE HOP", "")                          # the producer's line marker stays
    assert RG.count_desk_register(masked) == 0 and RG.count_desk_register(off.replace("CONSEQUENCE HOP", "")) > 0
    assert CQ._cw_register_fence([on])


# The walk end to end on the test_cascade_walk fixture shape (a hermetic tape; the REAL slice resolver):
# the printed figure and the `shown` binding are ONE magnitude, and the flag-off run is HEAD's.
import datetime as _dt  # noqa: E402

_ASOF = "2026-07-31"
_ROOT, _CHILD = "corn_cbot", "soft_red_winter_wheat_cbot"
_WS, _WE, _SPAN = "2021-03-05", "2021-06-25", "2021-03..2021-06"
_LIFE = {"2021-05": ("2021-02-15", "2021-05-10"), "2021-07": ("2021-02-15", "2021-07-12"),
         "2021-09": ("2021-02-15", "2021-08-15"), "2021-12": ("2021-02-15", "2021-08-15")}


def _tape(px0, px1):
    d, end, out = _dt.date.fromisoformat("2021-02-15"), _dt.date.fromisoformat("2021-08-15"), []
    while d <= end:
        iso = d.isoformat()
        for cm, (first, last) in _LIFE.items():
            if first <= iso <= last:
                settle = (px0 if iso <= _WS else px1) if cm == "2021-07" else 400.0
                out.append({"value": settle, "knowledge_date": iso, "contract_month": cm,
                            "unit": "US cents/bushel", "currency": "USD", "settle_kind": "settlement"})
        d += _dt.timedelta(days=1)
    return out


def _walk(display=None, via_request=False):
    rows_by = {_ROOT: _tape(500.0, 577.7777), _CHILD: _tape(500.0, 577.7777)}

    def qfn(sql):
        for slug, rows in rows_by.items():
            if slug in (sql or ""):
                return list(rows)
        return []
    nodes = {_ROOT: "corn", _CHILD: "srw_wheat"}
    edge = {"seed": _ROOT, "contract": _CHILD, "relation": "competes_with", "sign": "+",
            "lag": "0-1 quarters", "blurb": "one board's demand spills into the other", "mechanism": "m"}
    graph = types.SimpleNamespace(
        contracts={_ROOT: types.SimpleNamespace(drivers=[types.SimpleNamespace(id="heat")])},
        rev_cross_links=lambda c: [dict(edge)] if nodes.get(c, c) == "corn" else [],
        contract_node=lambda c: nodes.get(c, c))
    sg = types.SimpleNamespace(nodes=[], fired_regimes=[], trace={
        "episodes_injected": [{"node": "heat", "line": "DATED EPISODES for heat ...", "spans": [_SPAN],
                               "windows": [{"start": _WS, "end": _WE, "span": _SPAN, "n": 7}]}],
        "quantify_wave_reads": 0})
    calls: list = []
    req = {"focus_contract": _ROOT}
    kw: dict = {}
    if display and via_request:
        req["display"] = display                    # the contract's first site: the key ON the request
    elif display:
        kw["display"] = display                     # the threaded kwarg quantify passes (board payload route)
    lines, payload = CQ._cascade_walk_leg_or_nothing(sg, graph, req, qfn, _ASOF, calls, **kw)
    return lines, payload, calls


def test_T4_the_walk_prints_and_binds_ONE_magnitude_under_the_key_and_HEADs_bytes_off():
    off_lines, off_payload, off_calls = _walk()
    on_lines, on_payload, on_calls = _walk("analyst")
    assert off_payload["outcome"] == on_payload["outcome"] == "fired"
    off_row1 = [ln for ln in off_lines if ln.startswith("- [N")]
    on_row1 = [ln for ln in on_lines if ln.startswith("- [N")]
    assert len(off_row1) == len(on_row1) == 2
    assert all("+15.5555 %" in ln for ln in off_row1)                     # HEAD: six significant digits
    assert all("+15.56 %" in ln for ln in on_row1)                        # the one precision producer
    assert [c["shown"] for c in off_calls] == [[15.5555]] * 2                # HEAD: the cell's own move_pct
    assert [c["shown"] for c in on_calls] == [[15.56]] * 2                # bound = printed, one variable
    # the ROW VALUES do not move (B5): only the printed digits and the bound magnitude
    assert [c["rows"] for c in off_calls] == [c["rows"] for c in on_calls]
    # FIX ROUND 2, fixer pass (REVIEW_WT lexical / RA M10): the header's words are COMPOSED from the register
    # table (`register.desk_phrase`), never a typed second copy
    from leviathan.graphrag import register as RG
    assert any("dated window of heat, one of the %s" % RG.desk_phrase("firing", 1) in ln for ln in on_lines)
    assert not any("firing" in ln.lower() for ln in on_lines)
    assert any("heat firing window" in ln for ln in off_lines)
    assert CQ._cw_register_fence(on_lines)


def test_T4_a_request_dict_carrying_the_key_is_honoured_too():
    lines, payload, calls = _walk("analyst", via_request=True)          # the key rides the request dict
    assert [c["shown"] for c in calls] == [[15.56]] * 2
    assert all("+15.56 %" in ln for ln in lines if ln.startswith("- [N"))


def test_T4_quantify_reads_the_key_off_the_board_payload_and_its_signature_does_not_move():
    import inspect
    src = inspect.getsource(CQ.quantify)
    assert 'board.get("display")' in src and "_dq" in src
    assert "display" not in inspect.signature(CQ.quantify).parameters            # the g1x census pins it


# ══ config_check -- THE ROUND'S FIELDS ARE GRADED ═════════════════════════════════════════════════════
def test_the_card_fields_lint_is_green_at_the_tree():
    assert CC.check_numbers_card_fields() == []


def test_the_card_fields_lint_fires_on_each_malformed_declaration(clean_env):
    reg = R.load_registry()
    bad = reg.model_copy(deep=True)
    m = bad.tables["silver_psd"].metrics["su_ratio"]
    m.figure_basis = "of 2026 domestic use"
    t = bad.tables["gold_weather_z"].metrics["tmax_anomaly_tail_share"]
    t.definition_phrases = ["beyond +3 sigma"]
    bad.tables["silver_psd"].commodity_families["wheat"].members.append("not_a_slug")
    errs = CC.check_numbers_card_fields(reg=bad)
    assert any("figure_basis" in e and "digit" in e for e in errs)
    assert any("not a substring" in e for e in errs)
    assert any("not_a_slug" in e for e in errs)
    conv = {"conventions": {"x": {"kind": "abs_bands", "bands": [1.0], "labels": ["a"], "labels_low": ["b"]},
                            "y": {"kind": "z_bands", "bands": [1.0, 2.0], "labels": ["a", "b"],
                                  "labels_low": ["c"]}}}
    errs = CC.check_numbers_card_fields(reg=reg, conventions=conv)
    assert any("'x'" in e and "z_bands" in e for e in errs) and any("'y'" in e and "parallel" in e for e in errs)
