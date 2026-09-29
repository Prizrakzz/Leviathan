"""FIX SITTING 2 (09-26) -- LANE Q: THE NUMBERS SEAT READS WHAT THE CARD DECLARES.

MEASURED on the fifty banked traces (resmoke_0923/0924/0925 + arm A both cells) and READ-ONLY Athena:
  Q-1 (N-1, LIVE IN PROD, PC-1)  a no-destination agg=latest silver_esr read compiled `... LIMIT 1` over one row per
       BUYER and kept the SMALLEST -- 33 of 33 such served rows are exactly 0.0, five pages printed one as the
       nation ("Weekly export shipments read 0 1000 MT [N16]" beside a national week of 775.39 kMT). The card's
       `axis_national: sum` is now COMPILED (`query.national_fold`, one marketing year, the buyer count on the row);
       on the ten board weeks the traces carry the tree's fold equals the board's own fold, 10 of 10 (Athena).
       A BALANCE is never summed across observations (`query.BalanceSumRefused`): the treatment deep-soy seat
       served 58,884.71 kMT of "national outstanding sales" -- three weeks and two marketing years summed.
  Q-2 (VC-5, PC-2)  the card note told the seat "the current MY at a mid-2026 as-of is 2025" (false on 2026-09-26
       for soybeans, corn, wheat, cotton, rice): the note now carries the RULE, every marketing-year result names
       the turn's current year from ONE producer (`query.current_marketing_year`, the estate calendar), and on a
       board turn (`closed_year`) the current year is served beside a stale one.
  Q-3 (PC-3)  the cotton pace ask: silver_esr carries no cotton series, and the seat's CommodityOffCard "error" was
       printed as "returned no rows" -- now DECLINED BY NAME (`absence_reason: no_series`).
  Q-4 (PC-4)  `_exec` called every empty vintage read "not yet published at this as-of"; the reason is now MEASURED
       (`agent.empty_read_reason`, ABSENCE_REASONS).
  Q-L (m9 R4)  the rung ladder's record rides the census row of the pass it describes.
REJECTED (named so no later edit reaches for them): filtering zero rows; a destination blacklist; a prompt line
telling the agent to pass agg=sum; re-adding `country` to the tiebreak; keying the fold on a table name; editing the
year in the note; a per-commodity year table; letting the model derive the year from the as-of; special-casing
cotton; mapping cotton to cottonseed; reading "error" as "no rows" in the writer's prompt.
"""
from __future__ import annotations

import hashlib
import sqlite3
import types

import pytest
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import cascade as CQ
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import TableSpec, load_registry


def _esr() -> TableSpec:
    return load_registry().get("silver_esr")


def _spec(**kw) -> Q.NumberQuery:
    base = {"table": "silver_esr", "metric": "weekly_exports_1000mt", "asof": "2026-09-26",
            "commodity": "soybeans_cbot"}
    base.update(kw)
    return Q.NumberQuery(**base)


# ── the store fixture: ONE sqlite engine executes the compiled SQL (window functions + GROUP BY + NULLS LAST) ──
_COLS = ("commodity", "commodity_name", "market_year", "country_code", "week_ending_date",
         "weekly_exports_1000mt", "outstanding_sales_1000mt", "gross_new_sales_1000mt", "changes_1000mt",
         "as_of_date")


def _r(slug, my, code, week, ex, os_, asof):
    return (slug, slug, my, code, week, ex, os_, ex, 0.0, asof)


# soybeans_cbot (MY Sep 1): the CARRY week to 3 Sep holds the closing MY (end label 2026) and the new one (2027),
# every week holds a zero buyer, and the week to 10 Sep has one buyer revised by a later vintage (mixed vintages).
_ROWS = [
    _r("soybeans_cbot", 2026, "2230", "2026-09-03", 100.0, 600.0, "20260910"),
    _r("soybeans_cbot", 2026, "2110", "2026-09-03", 0.0, 70.0, "20260910"),
    _r("soybeans_cbot", 2027, "2230", "2026-09-03", 50.0, 9000.0, "20260910"),
    _r("soybeans_cbot", 2027, "5700", "2026-09-03", 30.0, 9700.0, "20260910"),
    _r("soybeans_cbot", 2027, "2230", "2026-09-10", 200.0, 9100.0, "20260917"),
    _r("soybeans_cbot", 2027, "2110", "2026-09-10", 0.0, 0.0, "20260917"),
    _r("soybeans_cbot", 2027, "5700", "2026-09-10", 5.0, 9800.0, "20260917"),
    _r("soybeans_cbot", 2027, "2230", "2026-09-10", 210.0, 9150.0, "20260924"),   # the revision
    # all_rice (the calendar declares no start for it): a carry week holding two marketing years
    _r("all_rice", 2026, "2230", "2026-08-06", 3.0, 30.0, "20260813"),
    _r("all_rice", 2027, "2230", "2026-08-06", 4.0, 40.0, "20260813"),
]


@pytest.fixture()
def qfn():
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH ':memory:' AS leviathan_dev")
    con.execute("CREATE TABLE leviathan_dev.silver_esr_compact (commodity TEXT, commodity_name TEXT, "
                "market_year INTEGER, country_code TEXT, week_ending_date TEXT, weekly_exports_1000mt REAL, "
                "outstanding_sales_1000mt REAL, gross_new_sales_1000mt REAL, changes_1000mt REAL, "
                "as_of_date TEXT)")
    con.executemany("INSERT INTO leviathan_dev.silver_esr_compact VALUES (?,?,?,?,?,?,?,?,?,?)", _ROWS)
    seen: list = []

    def _q(sql):
        seen.append(sql)
        cur = con.execute(sql)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]
    _q.seen = seen
    return _q


# ════════════════════════════════════ Q-1: THE NATIONAL FOLD (Y1) ════════════════════════════════════════
def test_Q1_the_fold_reads_the_CARDS_declaration_never_a_table_name():
    ts = _esr()
    assert ts.axis_national == "sum" and Q.FOLD_RULES == ("sum",)
    assert Q.national_fold(ts, _spec(agg="latest")) == "sum"
    assert Q.national_fold(ts, _spec(agg="latest", country="China")) is None          # a named buyer: HEAD
    assert Q.national_fold(ts, _spec(agg="sum")) is None                              # an aggregate: HEAD
    assert Q.national_fold(ts, _spec(agg="series")) is None
    undeclared = ts.model_copy(update={"axis_national": None})
    assert Q.national_fold(undeclared, _spec(agg="latest")) is None                   # no declaration: HEAD
    cell = ts.model_copy(update={"axis_national": "none"})
    assert Q.national_fold(cell, _spec(agg="latest")) is None                         # a CELL axis: HEAD
    # the lexical form is REJECTED: the board's table-name set is never the trigger
    import inspect
    assert "DESTINATION_GRAIN_TABLES" not in inspect.getsource(Q.national_fold)
    assert "silver_esr" not in inspect.getsource(Q.national_fold)


def test_Q1_a_declared_national_relation_the_compiler_does_not_fold_DECLINES_by_name():
    means = _esr().model_copy(update={"axis_national": "mean_of_cells"})
    with pytest.raises(Q.NationalFoldDeclined) as e:
        Q.build_sql(_spec(agg="latest"), means)
    assert e.value.reason == "undeclared_rule" and "undeclared_rule" in str(e.value)
    assert e.value.reason in Q.NATIONAL_FOLD_DECLINES


def test_Q1_the_fold_SQL_groups_every_axis_but_the_buyer_and_prefers_the_calendars_current_year():
    sql = Q.build_sql(_spec(agg="latest"), _esr())
    assert sql.startswith("SELECT sum(value) AS value, max(knowledge_date) AS knowledge_date, data_date, period, "
                          "count(value) AS _fold_n, count(*) OVER (PARTITION BY data_date) AS _fold_years FROM (")
    assert " GROUP BY data_date, period ORDER BY data_date DESC NULLS LAST, " in sql
    # soybeans at 2026-09-26: the calendar's current MY is 2026 (start year) -> the card's END-year label 2027
    assert "CASE WHEN period = 2027 THEN 0 ELSE 1 END, data_date, period LIMIT 1" in sql
    outer = sql.rsplit(") AS _v", 1)[1]
    assert "country" not in outer and "week_ending_date" not in outer          # no buyer, no raw column outside
    assert "ROW_NUMBER() OVER" in sql and "as_of_date <= '20260926'" in sql     # the dedup + PIT guard unchanged
    # a pinned period needs no preference: the MY filter already holds one year
    pinned = Q.build_sql(_spec(agg="latest", period="2026"), _esr())
    assert "CASE WHEN" not in pinned and "market_year = 2027" in pinned


# HEAD's SQL, banked from the 511631c5 shadow (fix_sitting_2_0926/lane_q/head_sql_pins.json): a destination-named
# read, a flow aggregate and a series compile BYTE FOR BYTE as they did (Q1-f); only the balance sum moves (Y2).
_HEAD_SQL = [
    ({"agg": "latest", "country": "China"},
     "SELECT value, knowledge_date, data_date, period, country FROM (SELECT weekly_exports_1000mt AS value, as_of_date AS knowledge_date, week_ending_date AS data_date, market_year AS period, country_code AS country, ROW_NUMBER() OVER (PARTITION BY commodity_name, market_year, country_code, week_ending_date ORDER BY as_of_date DESC) AS _rn FROM leviathan_dev.silver_esr_compact WHERE commodity = 'soybeans_cbot' AND market_year BETWEEN 2025 AND 2027 AND commodity_name = 'soybeans_cbot' AND CAST(country_code AS varchar) IN ('5700') AND as_of_date <= '20260926') AS _v WHERE _rn = 1 ORDER BY data_date DESC, data_date, period, country, knowledge_date, value LIMIT 1"),  # noqa: E501
    ({"metric": "outstanding_sales_1000mt", "agg": "latest", "country": "China", "period": "2026"},
     "SELECT value, knowledge_date, data_date, period, country FROM (SELECT outstanding_sales_1000mt AS value, as_of_date AS knowledge_date, week_ending_date AS data_date, market_year AS period, country_code AS country, ROW_NUMBER() OVER (PARTITION BY commodity_name, market_year, country_code, week_ending_date ORDER BY as_of_date DESC) AS _rn FROM leviathan_dev.silver_esr_compact WHERE commodity = 'soybeans_cbot' AND commodity_name = 'soybeans_cbot' AND CAST(country_code AS varchar) IN ('5700') AND market_year = 2027 AND as_of_date <= '20260926') AS _v WHERE _rn = 1 ORDER BY data_date DESC, data_date, period, country, knowledge_date, value LIMIT 1"),  # noqa: E501
    ({"agg": "sum", "country": "China", "period": "2025"},
     "SELECT sum(value) AS value FROM (SELECT value, knowledge_date, data_date, period, country FROM (SELECT weekly_exports_1000mt AS value, as_of_date AS knowledge_date, week_ending_date AS data_date, market_year AS period, country_code AS country, ROW_NUMBER() OVER (PARTITION BY commodity_name, market_year, country_code, week_ending_date ORDER BY as_of_date DESC) AS _rn FROM leviathan_dev.silver_esr_compact WHERE commodity = 'soybeans_cbot' AND commodity_name = 'soybeans_cbot' AND CAST(country_code AS varchar) IN ('5700') AND market_year = 2026 AND as_of_date <= '20260926') AS _v WHERE _rn = 1) AS _v LIMIT 5000"),  # noqa: E501
    ({"agg": "sum", "period": "2025"},
     "SELECT sum(value) AS value FROM (SELECT value, knowledge_date, data_date, period, country FROM (SELECT weekly_exports_1000mt AS value, as_of_date AS knowledge_date, week_ending_date AS data_date, market_year AS period, country_code AS country, ROW_NUMBER() OVER (PARTITION BY commodity_name, market_year, country_code, week_ending_date ORDER BY as_of_date DESC) AS _rn FROM leviathan_dev.silver_esr_compact WHERE commodity = 'soybeans_cbot' AND commodity_name = 'soybeans_cbot' AND market_year = 2026 AND as_of_date <= '20260926') AS _v WHERE _rn = 1) AS _v LIMIT 5000"),  # noqa: E501
    ({"metric": "gross_new_sales_1000mt", "commodity": "corn_cbot", "agg": "series", "period_start": "2026-06-01"},
     "SELECT value, knowledge_date, data_date, period, country FROM (SELECT gross_new_sales_1000mt AS value, as_of_date AS knowledge_date, week_ending_date AS data_date, market_year AS period, country_code AS country, ROW_NUMBER() OVER (PARTITION BY commodity_name, market_year, country_code, week_ending_date ORDER BY as_of_date DESC) AS _rn FROM leviathan_dev.silver_esr_compact WHERE commodity = 'corn_cbot' AND commodity_name = 'corn_cbot' AND CAST(week_ending_date AS varchar) >= '2026-06-01' AND as_of_date <= '20260926') AS _v WHERE _rn = 1 ORDER BY data_date, period, knowledge_date, value LIMIT 5000"),  # noqa: E501
]


@pytest.mark.parametrize("kw,head", _HEAD_SQL)
def test_Q1_every_read_the_fold_does_not_cover_compiles_byte_for_byte_as_HEAD(kw, head):
    assert Q.build_sql(_spec(**kw), _esr()) == head


def test_Q1_the_fold_EXECUTES_the_national_week_never_the_smallest_buyer(qfn):
    """The week to 10 Sep at the 17 Sep vintage: 200 + 0 + 5 -- HEAD's LIMIT 1 kept the 0.0 buyer."""
    rows = Q.run(_spec(agg="latest", asof="2026-09-20"), query_fn=qfn)
    assert len(rows) == 1
    r = rows[0]
    assert float(r["value"]) == 205.0 and r["data_date"] == "2026-09-10" and int(r["period"]) == 2027
    assert r[Q.FOLD_MARKER] == {"axis": "destination", "rule": "sum", "n": 3}
    assert "country" not in r and "_fold_n" not in r and "_fold_years" not in r
    assert r["knowledge_date"] == "20260917"


def test_Q1_a_week_whose_buyers_sit_on_two_vintages_is_ONE_national_week_known_at_its_newest(qfn):
    rows = Q.run(_spec(agg="latest", asof="2026-09-26"), query_fn=qfn)
    r = rows[0]
    assert float(r["value"]) == 215.0                        # 210 (revised, 24 Sep) + 0 + 5 (17 Sep): one week
    assert r["knowledge_date"] == "20260924" and r[Q.FOLD_MARKER]["n"] == 3


def test_Q1_the_carry_week_is_summed_for_the_calendars_CURRENT_year_never_across_both(qfn):
    """Q1-a: the week to 3 Sep carries the closing MY (100 + 0) and the new one (50 + 30); at 12 Sep the calendar's
    current soybean MY is 2026/27, so the national week is 80 -- never 180, never 100."""
    r = Q.run(_spec(agg="latest", asof="2026-09-12"), query_fn=qfn)[0]
    assert float(r["value"]) == 80.0 and int(r["period"]) == 2027 and r[Q.FOLD_MARKER]["n"] == 2
    old = Q.run(_spec(agg="latest", asof="2026-09-12", period="2025"), query_fn=qfn)[0]
    assert float(old["value"]) == 100.0 and int(old["period"]) == 2026        # a pinned year reads that year


def test_Q1_a_two_year_week_the_calendar_cannot_resolve_DECLINES_by_name(qfn):
    with pytest.raises(Q.NationalFoldDeclined) as e:
        Q.run(_spec(agg="latest", commodity="all_rice", asof="2026-08-15"), query_fn=qfn)
    assert e.value.reason == "two_marketing_years"
    assert "declares no marketing-year start" in str(e.value) and "pass period=" in str(e.value)
    pinned = Q.run(_spec(agg="latest", commodity="all_rice", asof="2026-08-15", period="2026"), query_fn=qfn)
    assert float(pinned[0]["value"]) == 4.0                                 # a pinned year serves


def test_Q1_the_fold_never_mutates_the_executors_rows_and_leaves_a_non_fold_executor_untouched():
    """A session cache hands the SAME row objects back; an executor that ignored the SQL is not the fold's."""
    raw = [{"value": "7", "knowledge_date": "20260924", "data_date": "2026-09-17", "period": "2027",
            "_fold_n": "3", "_fold_years": "1"}]
    snap = [dict(x) for x in raw]
    out = Q._apply_national_fold(raw, _spec(agg="latest"), _esr())
    assert raw == snap and out[0] is not raw[0] and out[0][Q.FOLD_MARKER]["n"] == 3
    legacy = [{"value": "0.0", "country": "Costa Rica"}]
    assert Q._apply_national_fold(legacy, _spec(agg="latest"), _esr()) is legacy


def test_Q1_the_zero_aggregate_caveat_rides_the_folded_row_exactly_as_it_rides_agg_sum():
    folded = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "latest"},
              "rows": [{"value": 0.0, Q.FOLD_MARKER: {"axis": "destination", "rule": "sum", "n": 12}}]}
    assert A._is_zero_esr_aggregate(folded) is True
    one_buyer = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "latest"},
                 "rows": [{"value": 0.0, "country": "Costa Rica"}]}
    assert A._is_zero_esr_aggregate(one_buyer) is False                    # HEAD's reading of a non-fold row
    signed = {"query": {"table": "silver_esr", "metric": "changes_1000mt", "agg": "latest"},
              "rows": [{"value": 0.0, Q.FOLD_MARKER: {"axis": "destination", "rule": "sum", "n": 12}}]}
    assert A._is_zero_esr_aggregate(signed) is False                       # a signed net of zero is a reading


# ════════════════════════════════ Q-1 (Y2): A BALANCE IS NEVER SUMMED ════════════════════════════════════
def test_Y2_a_balance_summed_across_weeks_and_years_is_REFUSED_with_its_measured_span(qfn):
    """The arm-A treatment deep-soy seat's 58,884.71 kMT: agg=sum from 1 Sep over three weeks and two MYs."""
    with pytest.raises(Q.BalanceSumRefused) as e:
        Q.run(_spec(metric="outstanding_sales_1000mt", agg="sum", period_start="2026-09-01"), query_fn=qfn)
    assert e.value.axes == {"period": 2, "data_date": 2}
    assert "BALANCE" in str(e.value) and "2 marketing years" in str(e.value) and "2 weeks" in str(e.value)
    assert "agg=latest" in str(e.value)
    with pytest.raises(Q.BalanceSumRefused):
        Q.run(_spec(metric="outstanding_sales_1000mt", agg="mean", period="2026"), query_fn=qfn)


def test_Y2_one_week_of_one_year_still_serves_the_fold_over_buyers_and_a_flow_sum_is_HEAD(qfn):
    one = Q.run(_spec(metric="outstanding_sales_1000mt", agg="sum", period="2026", period_start="2026-09-10",
                      period_end="2026-09-10", asof="2026-09-20"), query_fn=qfn)
    assert len(one) == 1 and float(one[0]["value"]) == 18900.0 and list(one[0]) == ["value"]
    flow = Q.build_sql(_spec(metric="weekly_exports_1000mt", agg="sum", period_start="2026-09-01"), _esr())
    assert "_bal_" not in flow and "count(DISTINCT" not in flow            # period_sum: true -> HEAD's aggregate
    assert float(Q.run(_spec(agg="sum", period_start="2026-09-01", asof="2026-09-20"), query_fn=qfn)[0]["value"]) \
        == 385.0                                                          # a FLOW over weeks and years still sums


# ═════════════════════════════════ Q-2: THE CURRENT MARKETING YEAR (Y3) ══════════════════════════════════
@pytest.mark.parametrize("slug,asof,want", [
    ("soybeans_cbot", "2026-09-26", (2026, "calendar")),        # hierarchy node 'soybeans' -> Sep
    ("soybeans_cbot", "2026-08-15", (2025, "calendar")),
    ("soybeans_cbot", "2024-03-01", (2023, "calendar")),        # the as-of turn: MY 2023/24
    ("soybean_oil_cbot", "2026-09-26", (2025, "calendar")),     # Oct start, read on the value
    ("corn_cbot", "2026-09-26", (2026, "calendar")),
    ("soft_red_winter_wheat_cbot", "2026-09-26", (2026, "calendar")),   # node srw_wheat -> the wheat family
    ("rough_rice_cbot", "2026-09-26", (2026, "calendar")),      # Aug start on the value, never the Sep default
    ("all_rice", "2026-09-26", (None, "no_declared_start")),    # S2-9: the rice class slugs DECLINE, never default
    ("long_grain_milled_rice", "2026-09-26", (None, "no_declared_start")),
    ("grain_sorghum", "2026-09-26", (None, "no_declared_start")),
])
def test_Q2_the_one_producer_reads_the_estate_calendar_and_never_its_default(slug, asof, want):
    assert Q.current_marketing_year("silver_esr", slug, asof) == want


def test_Q2_non_marketing_year_cards_carry_no_year_and_the_label_is_the_split_spelling():
    assert Q.current_marketing_year("silver_cot", "corn_cbot", "2026-09-26") == (None, "not_marketing_year")
    assert Q.current_marketing_year("no_such_card", "corn_cbot", "2026-09-26") == (None, "not_marketing_year")
    assert Q.current_marketing_year("silver_wasde", "soybeans", "2026-09-26") == (2026, "calendar")
    assert Q.marketing_year_label(2026) == "2026/27" and Q.marketing_year_label(2099) == "2099/00"


@pytest.mark.parametrize("key", sorted({*CQ.MY_START_MONTH, "soybeans_cbot", "rough_rice_cbot", "all_rice",
                                        "kc_wheat_kcbt", "grain_sorghum", "cottonseed", "barley", "hogs"}))
def test_Q2_the_default_detector_agrees_with_the_calendars_own_lookup_key_by_key(key, monkeypatch):
    """ONE calendar: `_calendar_start` returns `_my_start`'s own month, and None exactly where `_my_start` falls
    to its undeclared default (proved with a sentinel default -- a second calendar would disagree here)."""
    monkeypatch.setattr(CQ, "_MY_DEFAULT_START", 99)
    got = Q._calendar_start(key)
    if CQ._my_start(key) == 99:
        assert got is None
    else:
        assert got == CQ._my_start(key)


def test_Q2_the_note_carries_the_RULE_and_no_year_so_the_seat_prompt_is_one_sha_across_as_ofs():
    notes = " ".join(_esr().notes.split())
    assert "mid-2026" not in notes and "is 2025" not in notes
    assert "current_marketing_year" in notes and "start month most recently passed" in notes
    assert "OMIT country for the national figure: agg=latest reads the newest week summed over every " \
           "destination" in notes
    assert "Outstanding sales is a BALANCE" in notes
    sp = A.system_prompt(load_registry())
    assert "mid-2026 as-of is 2025" not in sp
    # the prompt takes no as-of at all: one string for every turn (B9), whatever the year
    assert hashlib.sha256(sp.encode("utf-8")).hexdigest() == hashlib.sha256(
        A.system_prompt(load_registry()).encode("utf-8")).hexdigest()


# ── the seat, end to end: a scripted client and the sqlite store ─────────────────────────────────────────
def _tu(inp, tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, input=dict(inp), id=tid)


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


class _Client:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        self.messages = _Msgs(self)


@pytest.fixture()
def quiet(monkeypatch):
    for k in ("GRAPHRAG_NUMBERS_THINKING", "GRAPHRAG_COST_CENSUS", "GRAPHRAG_STATE_BOARD",
              "GRAPHRAG_NUMBERS_BUDGET_NOTE", "GRAPHRAG_NUMBERS_MODE_BUDGET"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _seat(inp, qfn, *, asof="2026-09-26", q="How are US soybean export sales pacing?", **kw):
    c = _Client([_resp([_tu(inp)], "tool_use"), _resp([_text("read.")])])
    return A.answer_numbers(q, asof=asof, client=c, query_fn=qfn, **kw)


def test_Q2_every_marketing_year_result_names_the_turns_current_year_BEFORE_its_rows(quiet, qfn):
    out = _seat({"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "soybeans_cbot"}, qfn)
    call = out["calls"][0]
    assert call["current_marketing_year"] == 2026 and call["current_marketing_year_label"] == "2026/27"
    assert list(call)[:3] == ["query", "current_marketing_year", "current_marketing_year_label"]
    assert call["rows"][0][Q.FOLD_MARKER]["rule"] == "sum"                  # the seat served the fold
    rice = _seat({"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "all_rice",
                  "period": "2026"}, qfn, asof="2026-08-15")["calls"][0]
    assert "current_marketing_year" not in rice                             # no declared start: no year, named


def test_Q2b_on_a_board_turn_the_current_year_is_served_BESIDE_a_stale_one_and_never_flag_off(quiet):
    """The control cotton turn read 2025/26 vs 2024/25 as "this year"; with `closed_year` (the board kwarg) the
    same series is read at the current 2026/27 as a real companion read. Flag-off: nothing is added."""
    asked: list = []

    def wasde(sql):
        asked.append(sql)
        for my in ("2025/26", "2026/27"):
            if f"marketing_year = '{my}'" in sql:
                return [{"value": "4.15" if my == "2025/26" else "3.6", "period": my, "knowledge_date": "2026-09-11",
                         "unit": "Million 480 Pound Bales"}]
        return []
    inp = {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "cotton", "country": "united_states",
           "period": "2025/26"}
    on = _seat(inp, wasde, q="Where does cotton stand?", closed_year=True)
    comp = [c for c in on["calls"] if c.get("current_year_of")]
    assert len(comp) == 1 and comp[0]["query"]["period"] == "2026/27" and comp[0]["rows"][0]["value"] == "3.6"
    assert on[A.ESR_CLOSED_YEAR_KEY]["current_year"]["served"][0]["year"] == "2026/27"
    off = _seat(inp, wasde, q="Where does cotton stand?")
    assert not [c for c in off["calls"] if c.get("current_year_of")] and A.ESR_CLOSED_YEAR_KEY not in off
    cur = _seat({**inp, "period": "2026/27"}, wasde, q="Where does cotton stand?", closed_year=True)
    assert not [c for c in cur["calls"] if c.get("current_year_of")]      # already current: nothing added


def test_Q2b_an_empty_companion_is_dropped_and_NAMED_never_fabricated():
    calls = [{"handle": "L1", "status": "ok", "rows": [{"value": "1"}],
              "query": {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "cotton",
                        "country": "united_states", "period": "2025/26", "asof": "2026-09-26"}}]
    legs, rec = A.current_year_companion_legs(calls, "2026-09-26", lambda sql: [])
    assert legs == [] and rec["declined"][0]["reason"] == "companion_no_rows"
    rice = [{"handle": "L2", "status": "ok", "rows": [{"value": "1"}],
             "query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "all_rice",
                       "period": "2025", "asof": "2026-09-26"}}]
    legs, rec = A.current_year_companion_legs(rice, "2026-09-26", lambda sql: [{"value": "9"}])
    assert legs == [] and rec["declined"][0]["reason"] == "no_declared_start"


# ═══════════════════════════════════ Q-3: THE NO-SERIES DECLINE (Y4) ═════════════════════════════════════
def test_Q3_cotton_on_the_export_sales_card_is_DECLINED_BY_NAME_and_nothing_is_queried(quiet):
    seen: list = []
    out = _seat({"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "cotton"},
                lambda sql: seen.append(sql) or [], q="What does the pace of cotton export sales say?")
    call = out["calls"][0]
    assert call["status"] == "declined" and call["absence_reason"] == "no_series"
    assert call["numbers_decline"] == {"reason": "no_series", "table": "silver_esr", "commodity": "cotton"}
    assert "the USDA FAS Export Sales (ESR) store carries no ICE cotton series" in call["scope_note"]
    assert "error" not in call and seen == []


@pytest.mark.parametrize("asked", ["soybeans", "sorghum", "upland_cotton", "corn"])
def test_Q3_a_spelling_miss_an_aliased_member_or_an_unknown_name_keeps_HEADs_refusal(quiet, asked):
    """Q3-a: 'soybeans' shares the node of the declared soybeans_cbot; 'sorghum' has the card's own candidate
    grain_sorghum; 'upland_cotton' is a name the hierarchy does not know -- none of them is a no_series fact."""
    out = _seat({"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": asked}, lambda sql: [])
    call = out["calls"][0]
    assert call["status"] == "error" and call["absence_reason"] == "error"
    assert "does not serve commodity" in call["error"] and "numbers_decline" not in call


def test_Q3_cotton_never_resolves_to_cottonseed_and_the_universe_is_read_at_call_time():
    vals = list(_esr().commodity_values)
    assert "cottonseed" in vals and A._no_series_for("cotton", vals) is True
    assert A._no_series_for("cotton", vals + ["cotton"]) is False          # the pipeline lands it: the decline stops


# ════════════════════════════════════ Q-4: THE MEASURED EMPTY READ (Y4) ══════════════════════════════════
@pytest.mark.parametrize("kw,status,want", [
    ({"table": "silver_esr", "metric": "outstanding_sales_1000mt", "commodity": "soybeans_cbot",
      "asof": "2024-03-01"}, "not_known", "store_gap"),            # the 2024 turns: write-date vintages
    ({"table": "silver_psd", "metric": "su_ratio", "commodity": "soybean_oil_cbot", "country": "World",
      "asof": "2026-09-26"}, "not_known", "store_gap"),            # revision-dated vintages: no timing claim
    ({"table": "silver_wasde", "metric": "ending_stocks", "commodity": "soybeans", "country": "united_states",
      "period": "2027/28", "asof": "2026-09-26"}, "not_known", "not_yet_published"),   # Q4-a: TRUE timing kept
    ({"table": "silver_wasde", "metric": "domestic_total", "commodity": "rice", "country": "united_states",
      "period": "2026/27", "asof": "2026-09-26"}, "not_known", "no_rows"),    # a scope miss on real vintages
    ({"table": "silver_cot", "metric": "mm_net", "commodity": "corn_cbot", "period_start": "2026-10-01",
      "asof": "2026-09-26"}, "no_rows", "not_yet_published"),      # the window opens after the as-of
    ({"table": "silver_cot", "metric": "mm_net", "commodity": "corn_cbot", "asof": "2026-09-26"},
     "no_rows", "no_rows"),
    ({"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "cotton", "asof": "2026-09-26"},
     "not_known", "no_series"),
])
def test_Q4_the_reason_is_measured_off_the_spec_and_the_card(kw, status, want):
    spec = types.SimpleNamespace(**{"country": None, "period": None, "period_start": None, "commodity": None, **kw})
    assert A.empty_read_reason(spec, status, reg=load_registry(), asof=kw["asof"]) == want


def test_Q4_every_reason_has_its_words_and_only_a_measured_timing_says_not_yet_published():
    for w in A.ABSENCE_REASONS:
        assert w in A._NO_ROWS_WHY
    timed = {k for k, v in A._NO_ROWS_WHY.items() if "not yet published" in v}
    assert timed == {"not_yet_published", "future_unpublished"}
    assert "not a timing claim" in A._NO_ROWS_WHY["not_known"]
    assert A.empty_read_reason(None, "error", reg=load_registry(), asof="2026-09-26") == "error"
    assert A.empty_read_reason(types.SimpleNamespace(table="nope"), "no_rows", reg=load_registry(),
                               asof="2026-09-26") == "no_card"


def test_Q4_the_seats_empty_read_carries_its_reason_and_the_marker_says_it(quiet):
    out = _seat({"table": "silver_esr", "metric": "outstanding_sales_1000mt", "commodity": "soybeans_cbot",
                 "period": "2023"}, lambda sql: [], asof="2024-03-01")
    call = out["calls"][0]
    assert call["status"] == "not_known" and call["absence_reason"] == "store_gap"
    assert call["scope_note"].startswith(A._no_rows_note("store_gap"))
    assert "not yet published" not in call["scope_note"]


def test_Q1_the_seat_declines_a_balance_sum_and_an_unresolvable_two_year_week_by_name(quiet, qfn):
    bal = _seat({"table": "silver_esr", "metric": "outstanding_sales_1000mt", "commodity": "soybeans_cbot",
                 "agg": "sum", "period_start": "2026-09-01"}, qfn)["calls"][0]
    assert bal["status"] == "declined" and bal["absence_reason"] == "declined"
    assert bal["numbers_decline"]["reason"] == "balance_over_periods" and "BALANCE" in bal["scope_note"]
    rice = _seat({"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "all_rice"}, qfn,
                 asof="2026-08-15")["calls"][0]
    assert rice["status"] == "declined" and rice["numbers_decline"]["reason"] == "two_marketing_years"


# ═══════════════════════════════ Q-L (m9 R4): THE RUNG RIDES ITS USAGE ROW ═══════════════════════════════
def _usage(o):
    return types.SimpleNamespace(input_tokens=10, output_tokens=o, cache_read_input_tokens=0,
                                 cache_creation_input_tokens=0)


@pytest.fixture()
def armed(monkeypatch):
    from leviathan.graphrag import providers as pv
    for k in ("GRAPHRAG_STATE_BOARD", "GRAPHRAG_NUMBERS_MODE_BUDGET", "GRAPHRAG_NUMBERS_BUDGET_NOTE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GRAPHRAG_NUMBERS_THINKING", "adaptive")
    monkeypatch.setenv("GRAPHRAG_NUMBERS_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(pv, "provider", lambda: "anthropic")
    monkeypatch.setattr(pv, "supports_adaptive", lambda m: True)
    return monkeypatch


def _ladder_client():
    tu = _tu({"table": "silver_cot", "metric": "mm_net", "commodity": "corn_cbot"})
    return _Client([types.SimpleNamespace(content=[], stop_reason="max_tokens", usage=_usage(6000)),
                    types.SimpleNamespace(content=[tu], stop_reason="tool_use", usage=_usage(7000)),
                    types.SimpleNamespace(content=[_text("read.")], stop_reason="end_turn", usage=_usage(50))])


def test_QL_a_ladder_that_fired_rides_the_census_rows_of_its_two_passes(armed):
    armed.setenv("GRAPHRAG_COST_CENSUS", "on")
    sink: list = []
    out = A.answer_numbers("corn positioning?", "2026-09-26", client=_ladder_client(), query_fn=lambda s: [],
                           usage_sink=sink, rung_ladder=True)
    rows = out["numbers_usage"]
    assert rows[0]["rung"] == {"max_tokens": 6000, "stop": "max_tokens", "out": 6000}
    assert rows[1]["rung"] == {"max_tokens": 12000, "stop": "tool_use", "out": 7000}
    assert "rung" not in rows[2] and sink == rows                          # a pass the ladder never touched


def test_QL_ladder_off_or_census_off_carries_no_rung_anywhere(armed):
    armed.setenv("GRAPHRAG_COST_CENSUS", "on")
    c = _Client([types.SimpleNamespace(content=[_text("read.")], stop_reason="end_turn", usage=_usage(40))])
    out = A.answer_numbers("corn positioning?", "2026-09-26", client=c, query_fn=lambda s: [], rung_ladder=True)
    assert all("rung" not in r for r in out["numbers_usage"])
    armed.delenv("GRAPHRAG_COST_CENSUS")
    out = A.answer_numbers("corn positioning?", "2026-09-26", client=_ladder_client(), query_fn=lambda s: [],
                           rung_ladder=True)
    assert "numbers_usage" not in out and out["numbers_budget"]["rungs"][0]["stop"] == "max_tokens"
