"""THE 09-26 FIX SITTING 2, LANE P -- state/feeders.py and numbers/registry.py.

  P-1  THE PSD LAST-REVISION CLOCK: the retention producer (``vintage_retention``), the last-revised label, the
       card-to-WASDE line map (``registry.WASDE_LINE_OF``) and the then-current WASDE line, folded into the
       row's ``period_behind`` with ``why: last_revised`` (CONTRACT Y5 / Y6);
  P-2  a DERIVED row's knowledge stamp is the MAX of its inputs' stamps (CONTRACT Y7);
  P-3  the POPULATION a percentile was taken over (CONTRACT Y8);
  P-4  the known stamp's ONE derivation on the seat's own row shapes (CONTRACT Y9, the producer half);
  m7   the action ledger's ``unanchored`` word.

Every test runs OFFLINE: the store facts below are TRANSCRIBED from the read-only pull of ``silver_psd`` (09-22,
251,475 rows) and ``silver_wasde`` (09-24, all 473 releases) that the lane's drives run on -- the vintages of US
soybeans MY2016-2026 and the WASDE rows of Argentina's soybean exports -- never invented shapes.
"""
import pytest
from leviathan.graphrag.numbers import registry as R
from leviathan.graphrag.numbers.registry import load_registry
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state.rows import SeriesKey, StateRow

ASOF_2024 = "2024-03-01"

#: US soybeans, silver_psd: (market_year, release_date) -- the MEASURED vintage history (09-22 pull).
US_SOY_VINTAGES = [(2012, "2018-05-10"), (2013, "2019-02-08"), (2014, "2019-02-08"), (2015, "2019-07-11"),
                   (2016, "2023-04-11"), (2017, "2023-04-11"), (2018, "2024-01-12"), (2019, "2024-01-12"),
                   (2020, "2024-01-12"), (2021, "2026-04-09"), (2022, "2026-04-09"), (2023, "2026-04-09"),
                   (2023, "2026-07-10"), (2024, "2026-04-09"), (2024, "2026-07-10"), (2025, "2026-05-12"),
                   (2025, "2026-09-11"), (2026, "2026-05-12"), (2026, "2026-09-11")]


class _Node:
    __slots__ = ("contract", "id", "prior", "evidence", "anchor_row")

    def __init__(self, contract, driver_id, ref, region=None):
        self.contract, self.id = contract, driver_id
        self.prior = {"silver_ref": ref, "region": region}
        self.evidence = []
        self.anchor_row = True


def _probe_reader(vintages, calls=None):
    """A reader for the PROBE's SQL shape: one row per DISTINCT (period, knowledge date), inside the band the
    compiled SQL states -- the band is read back off the statement so the fake cannot answer a question the
    SQL did not ask."""
    import re

    def _run(sql):
        if calls is not None:
            calls.append(sql)
        lo = int(re.search(r"market_year >= (\d+)", sql).group(1))
        hi = int(re.search(r"market_year <= (\d+)", sql).group(1))
        return [{"period": str(y), "knowledge_date": d} for y, d in sorted(set(vintages)) if lo <= y <= hi]
    return _run


def _psd():
    return load_registry().get("silver_psd")


# ── P-1: the retention producer ──────────────────────────────────────────────────────────────────────
def test_P1_the_2024_US_soybean_row_is_HELD_ONLY_AS_LAST_REVISED_by_the_stores_own_vintages():
    calls = []
    rt = F.vintage_retention(_psd(), "silver_psd", commodity="soybeans_cbot", scope="United States",
                             served_period="2020", asof=ASOF_2024, reader=_probe_reader(US_SOY_VINTAGES, calls),
                             metric="su_ratio")
    assert rt["state"] == "held_as_last_revised" and rt["read"] is True
    assert rt["served"] == 2020 and rt["current"] == 2023, "soybeans' calendar: Sep start -> MY2023 at 2024-03"
    assert rt["newer"] == [2021, 2022], "the evidence is the years STRICTLY older than the current one"
    assert rt["n_on_or_before"] == 1 and rt["first_after"] == "2026-04-09"
    assert len(calls) == 1, "ONE bounded statement per served series"


def test_P1_the_probe_is_compiled_from_the_query_layers_own_scope_with_NO_asof_guard():
    sql = F.retention_sql(_psd(), "silver_psd", metric="su_ratio", commodity="soybeans_cbot",
                          scope="United States", asof=ASOF_2024, lo=2020, hi=2023)
    assert "leviathan_slug = 'soybeans_cbot'" in sql and "country = 'United States'" in sql
    assert "market_year >= 2020" in sql and "market_year <= 2023" in sql and "su_ratio IS NOT NULL" in sql
    assert "<= '2024-03-01'" not in sql, "the probe asks which vintages exist AFTER the as-of"
    assert sql.rstrip().endswith("LIMIT %d" % F.RETENTION_ROW_LIMIT)


@pytest.mark.parametrize("served, asof", [("2026", "2026-09-26"), ("2025", "2026-09-26"), ("2022", ASOF_2024)])
def test_P1a_a_row_AT_or_ONE_BEHIND_the_current_year_is_vintaged_at_ZERO_reads(served, asof):
    calls = []
    rt = F.vintage_retention(_psd(), "silver_psd", commodity="soybeans_cbot", scope="United States",
                             served_period=served, asof=asof, reader=_probe_reader(US_SOY_VINTAGES, calls),
                             metric="su_ratio")
    assert rt["state"] == "vintaged" and rt["why"] == "within_slack" and calls == []


def test_P1a_a_newer_year_FIRST_PRINTED_after_the_asof_is_no_evidence_of_revision():
    """The late printer's case (FCOJ first prints MY Y on 31 January of Y+1, the 09-23 ruling F1): the only
    newer key is the CURRENT year and it exists only after the as-of -- it may never have been printed by
    then, so it proves no lost vintage. Two years behind, with the year between HELD as known, is not held."""
    vint = [(2021, "2022-01-31"), (2022, "2023-01-31"), (2023, "2024-01-31"), (2024, "2025-01-31")]
    rt = F.vintage_retention(_psd(), "silver_psd", commodity="frozen_orange_juice", scope="United States",
                             served_period="2022", asof="2024-11-15", reader=_probe_reader(vint),
                             metric="production_mt", current=2024)
    assert rt["state"] == "vintaged" and rt["newer"] == [], rt


def test_P1_a_newer_year_holding_ANY_vintage_on_or_before_the_asof_is_not_evidence():
    vint = [(2020, "2024-01-12"), (2021, "2024-02-08"), (2021, "2026-04-09"), (2022, "2026-04-09")]
    rt = F.vintage_retention(_psd(), "silver_psd", commodity="soybeans_cbot", scope="United States",
                             served_period="2020", asof=ASOF_2024, reader=_probe_reader(vint), metric="su_ratio")
    assert rt["newer"] == [2022] and rt["state"] == "held_as_last_revised"
    vint2 = [(2020, "2024-01-12"), (2021, "2024-02-08"), (2022, "2024-02-08")]
    rt2 = F.vintage_retention(_psd(), "silver_psd", commodity="soybeans_cbot", scope="United States",
                              served_period="2020", asof=ASOF_2024, reader=_probe_reader(vint2), metric="su_ratio")
    assert rt2["state"] == "vintaged" and rt2["newer"] == []


def test_P1_no_mirror_no_read_no_raise_and_the_gates_answer_by_name(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_NUMBERS_BACKEND", raising=False)
    rt = F.vintage_retention(_psd(), "silver_psd", commodity="soybeans_cbot", scope="United States",
                             served_period="2020", asof=ASOF_2024, metric="su_ratio")
    assert rt == {"read": False, "why": "no_pool", "served": 2020, "current": 2023}
    oni = load_registry().get("silver_noaa_oni")
    assert F.vintage_retention(oni, "silver_noaa_oni", commodity="", scope="", served_period="2020",
                               asof=ASOF_2024)["why"] == "not_vintage_card"
    esr = load_registry().get("silver_esr")
    assert F.vintage_retention(esr, "silver_esr", commodity="soybeans", scope="", served_period="2024-02-22",
                               asof=ASOF_2024)["why"] == "not_marketing_year"

    def _boom(sql):
        raise RuntimeError("pool exhausted")
    assert F.vintage_retention(_psd(), "silver_psd", commodity="soybeans_cbot", scope="United States",
                               served_period="2020", asof=ASOF_2024, reader=_boom,
                               metric="su_ratio")["why"] == "read_error"


def test_P1_a_commodity_the_calendar_declares_no_start_for_DECLINES_never_defaults(monkeypatch):
    """S2-9: the calendar's undeclared default (September) is never read as a fact."""
    from leviathan.graphrag.numbers import query as Q
    monkeypatch.delattr(Q, "current_marketing_year", raising=False)
    assert F._current_my("silver_psd", "palm_olein_dce", ASOF_2024) is None
    assert F._current_my("silver_psd", "soybeans_cbot", ASOF_2024) == 2023
    assert F._current_my("silver_psd", "rough_rice_cbot", "2024-07-31") == 2023    # rice opens in August
    assert F._current_my("silver_psd", "rough_rice_cbot", "2024-08-01") == 2024


def test_P1_Q_s_current_marketing_year_producer_wins_where_it_has_landed(monkeypatch):
    from leviathan.graphrag.numbers import query as Q
    monkeypatch.setattr(Q, "current_marketing_year", lambda t, c, a: (2019, "calendar"), raising=False)
    assert F._current_my("silver_psd", "soybeans_cbot", ASOF_2024) == 2019
    monkeypatch.setattr(Q, "current_marketing_year", lambda t, c, a: (None, "no_declared_start"), raising=False)
    assert F._current_my("silver_psd", "soybeans_cbot", ASOF_2024) is None


def test_P1f_the_last_revised_label_is_register_clean_and_carries_no_later_date():
    from leviathan.graphrag import register
    note = F.vintage_note_last_revised(ASOF_2024, {"served": 2020})
    assert note == ("the newest marketing year this store shows as known on 1 March 2024 is 2020/21; newer "
                    "years were revised after that date and are held only as last revised")
    assert "not recoverable" not in note, "K18's ONI words are false for a row whose as-known value IS served"
    assert register.desk_register_hits(note) == [] and register.internal_leaks(note) == []
    assert not any(str(y) in note for y in range(2024 + 1, 2031))


# ── P-1: the series state, the stamp and the fold ────────────────────────────────────────────────────
def _psd_rows_2024():
    """The board read's rows at 2024-03-01 for US soybeans S/U (the as-known series, one per year)."""
    vals = {2016: 0.0892, 2017: 0.1082, 2018: 0.2358, 2019: 0.2372, 2020: 0.1141}
    return [{"value": str(v), "period": str(y), "knowledge_date": "2024-01-12" if y >= 2018 else "2023-04-11",
             "country": "United States"} for y, v in sorted(vals.items())] + \
        [{"value": str(0.10 + 0.01 * (i % 5)), "period": str(1990 + i), "knowledge_date": "2019-02-08",
          "country": "United States"} for i in range(26)]


def _row(asof=ASOF_2024, reader=None, rows=None):
    rows = sorted(rows if rows is not None else _psd_rows_2024(), key=lambda r: int(r["period"]))
    return F.series_state("psd_ending_stock_su_ratio",
                          _Node("soybeans_cbot", "psd_ending_stock_su_ratio", "psd_ending_stock_su_ratio"),
                          asof, qfn=F.fixture_query_fn({"silver_psd": rows}), windows={"annual": 10},
                          silver_status="available", retention_reader=reader)


def test_P1_the_served_row_KEEPS_its_figure_and_carries_the_last_revised_stamp_and_note():
    st = _row(reader=_probe_reader(US_SOY_VINTAGES))
    assert st.status == "ok" and st.level_date == "2020" and abs(st.level - 0.1141) < 1e-9
    assert st.knowledge_date == "2024-01-12", "the row's own as-known print, unchanged"
    assert F.held_as_last_revised(st)
    assert st.recency[F.RETENTION_KEY]["newer"] == [2021, 2022]
    assert st.vintage_note.startswith("the newest marketing year this store shows as known on 1 March 2024 is "
                                      "2020/21")


def test_P1_a_row_nothing_measured_keeps_HEADs_recency_and_note_byte_for_byte(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_NUMBERS_BACKEND", raising=False)
    offline = _row()                                          # 2024 as-of, no mirror
    assert offline.recency[F.RETENTION_KEY] == {"read": False, "why": "no_pool", "served": 2020,
                                                "current": 2023}
    assert offline.vintage_note is None and not F.held_as_last_revised(offline)
    # a served year ONE behind the current one: zero reads, no key, no note -- HEAD's row
    one_behind = _psd_rows_2024() + [{"value": "0.08", "period": "2021", "knowledge_date": "2024-02-01",
                                      "country": "United States"},
                                     {"value": "0.07", "period": "2022", "knowledge_date": "2024-02-01",
                                      "country": "United States"}]
    calls = []
    live = _row(reader=_probe_reader(US_SOY_VINTAGES, calls), rows=one_behind)
    assert live.level_date == "2022" and calls == []
    assert F.RETENTION_KEY not in live.recency and live.vintage_note is None


def test_P1_the_fold_survives_every_restamp_and_a_K23_newer_year_is_KEPT():
    st = _row(reader=_probe_reader(US_SOY_VINTAGES))
    F.stamp_period_behind([st], ASOF_2024)
    assert st.period_behind == {"held": "2020/21", "why": "last_revised"}
    seat = {"status": "ok", "query": {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "soybeans",
                                      "country": "united_states", "asof": ASOF_2024},
            "rows": [{"value": "315", "period": "2023/24", "knowledge_date": "2024-02-08",
                      "country": "united_states", "revision_stamp": "projection", "unit": "Million Bushels"}]}
    F.stamp_period_behind([st], ASOF_2024, extra_periods=(seat,))
    assert st.period_behind == {"held": "2020/21", "newer_on": "USDA WASDE", "newer": "2023/24",
                                "why": "last_revised"}
    F.stamp_period_behind([st], ASOF_2024, extra_periods=(seat,))       # idempotent
    assert st.period_behind["why"] == "last_revised"


def test_P1g_the_board_level_retention_stamp_sums_the_rows_own_stamps_and_is_EMPTY_when_nothing_measured():
    held = _row(reader=_probe_reader(US_SOY_VINTAGES))
    rows = _psd_rows_2024() + [{"value": "0.07", "period": "2022", "knowledge_date": "2024-02-01",
                                "country": "United States"}]
    slack = _row(reader=_probe_reader(US_SOY_VINTAGES), rows=rows)
    c = F.retention_census([held, slack, held])
    assert c["keys"] == 1 and c["stamped"] == 1 and c["read"] is True and c["why"] == {}
    assert F.retention_census([slack]) == {}, "a live turn writes no retention stamp"


def test_P1_a_row_the_probe_did_not_stamp_gets_exactly_K23():
    rows = _psd_rows_2024() + [{"value": "0.07", "period": "2022", "knowledge_date": "2024-02-01",
                                "country": "United States"}]
    st = _row(reader=_probe_reader(US_SOY_VINTAGES), rows=rows)
    F.stamp_period_behind([st], ASOF_2024)
    assert st.period_behind == {}


def test_P1_at_an_earlier_asof_the_SAME_store_holds_the_row_as_last_revised_by_the_same_rule():
    """At 2021-06-30 the as-known US series ends at MY2015 (every later year is held only under 2023-2024
    vintages); the current year is MY2020 and the years between are the evidence -- measured, not dated."""
    st = _row(asof="2021-06-30", reader=_probe_reader(US_SOY_VINTAGES))
    assert st.level_date == "2015" and F.held_as_last_revised(st)
    assert st.recency[F.RETENTION_KEY]["newer"] == [2016, 2017, 2018, 2019]


WASDE_ARG_EXPORTS = [  # silver_wasde, soybeans / argentina / exports, world sheet (the 09-24 pull)
    {"value": "2.86", "period": "2021/22", "knowledge_date": "2024-02-08", "revision_stamp": "actual",
     "country": "argentina", "table_type": "world", "unit": "MMT"},
    {"value": "4.19", "period": "2022/23", "knowledge_date": "2024-02-08", "revision_stamp": "estimate",
     "country": "argentina", "table_type": "world", "unit": "MMT"},
    {"value": "9.9", "period": "2023/24", "knowledge_date": "2024-05-10", "revision_stamp": "estimate",
     "country": "argentina", "table_type": "world", "unit": "MMT"},       # post-as-of: the belt drops it
]


def test_P1_i_the_WASDE_line_is_read_at_the_asof_as_ITS_OWN_row_never_the_PSD_figure():
    tc = F.then_current_line("silver_psd", "exports_mt", commodity="soybeans_cbot", scope="Argentina",
                             asof=ASOF_2024, reader=lambda sql: [dict(r) for r in WASDE_ARG_EXPORTS])
    assert tc["newer"] == "2022/23" and tc["newer_on"] == "USDA WASDE" and tc["ordinal"] == 2022
    assert tc["table"] == "silver_wasde" and tc["metric"] == "exports" and tc["country"] == "argentina"
    assert tc["knowledge_date"] == "2024-02-08" and tc["role"] == "estimate"
    assert F.then_current_line("silver_psd", "su_ratio", commodity="soybeans_cbot", scope="United States",
                               asof=ASOF_2024, reader=lambda sql: []) == {}, "an unmapped series reads nothing"


def test_P1_i_a_WASDE_line_that_is_ITSELF_stale_names_no_newer_year():
    """MEASURED on the WASDE pull: China's corn imports line stops at 2011/12 (last released 2011-08-11), so at
    2024-03-01 "USDA WASDE held 2011/12 by then" would be true and misleading -- the line is not the then-current
    one by the same one-period slack, and it names nothing."""
    rows = [{"value": "4.0", "period": "2011/12", "knowledge_date": "2011-08-11", "revision_stamp": "projection",
             "country": "china", "table_type": "world", "unit": "MMT"}]
    tc = F.then_current_line("silver_psd", "imports_mt", commodity="corn_cbot", scope="China", asof=ASOF_2024,
                             reader=lambda sql: [dict(r) for r in rows])
    assert tc == {"read": True, "why": "stale_line", "period": "2011/12", "ordinal": 2011}
    st = StateRow(key=SeriesKey(ref="import", commodity="corn_cbot", country="China"), asof=ASOF_2024,
                  table="silver_psd", metric="imports_mt", cadence="annual", level=1.6e4, level_date="2006",
                  knowledge_date="2018-11-08")
    st.recency = {F.RETENTION_KEY: {"read": True, "state": "held_as_last_revised", "served": 2006,
                                    "then_current": tc}}
    F.stamp_period_behind([st], ASOF_2024)
    assert st.period_behind == {"held": "2006/07", "why": "last_revised"}


def test_P1_i_the_then_current_line_names_the_newer_year_where_no_other_card_did():
    st = StateRow(key=SeriesKey(ref="export", commodity="soybeans_cbot", country="Argentina"), asof=ASOF_2024,
                  table="silver_psd", metric="exports_mt", cadence="annual", level=2.132e6, level_date="2017",
                  knowledge_date="2023-06-09")
    st.recency = {F.RETENTION_KEY: {"read": True, "state": "held_as_last_revised", "served": 2017,
                                    "then_current": {"ordinal": 2022, "newer": "2022/23",
                                                     "newer_on": "USDA WASDE"}}}
    F.stamp_period_behind([st], ASOF_2024)
    assert st.period_behind == {"held": "2017/18", "newer_on": "USDA WASDE", "newer": "2022/23",
                                "why": "last_revised"}


# ── P-1 (i): the declared map ─────────────────────────────────────────────────────────────────────────
def test_P1c_the_WASDE_line_map_is_clean_and_every_target_is_a_quantity_line():
    assert R.check_wasde_line_map() == []
    assert R.wasde_line_for("silver_psd", "su_ratio", "United States") is None, "a ratio is not a WASDE line"
    assert R.wasde_line_for("silver_psd", "area_harvested_1000ha", "United States") is None
    line = R.wasde_line_for("silver_psd", "beginning_stocks_mt", "China", commodity="corn_cbot")
    assert line == {"table": "silver_wasde", "metric": "beginning_stocks", "country": "china",
                    "scope": "reporter", "commodity": "corn"}
    assert R.wasde_line_for("silver_psd", "production_mt", "Malaysia",
                            commodity="malaysian_crude_palm_oil_cme") is None, "WASDE prints no palm sheet"


def test_P1c_the_lint_BITES_on_a_ratio_mapped_as_a_quantity(monkeypatch):
    bad = dict(R.WASDE_LINE_OF)
    bad[("silver_psd", "su_ratio")] = {"table": "silver_wasde", "metric": "ending_stocks", "scope": "reporter"}
    monkeypatch.setattr(R, "WASDE_LINE_OF", bad)
    errs = R.check_wasde_line_map()
    assert any("declare 2 units" in e for e in errs), errs
    bad2 = dict(R.WASDE_LINE_OF)
    bad2[("silver_psd", "exports_mt")] = {"table": "silver_wasde", "metric": "avg_farm_price", "scope": "reporter"}
    monkeypatch.setattr(R, "WASDE_LINE_OF", bad2)
    assert any("not a balance-sheet quantity line" in e for e in R.check_wasde_line_map())


# ── P-2: derived stamps ───────────────────────────────────────────────────────────────────────────────
def test_P2_derived_knowledge_is_the_MAX_of_its_inputs_and_unread_when_any_is_missing():
    assert F.derived_knowledge(["2026-09-24", "2026-09-25", "2026-09-01"]) == "2026-09-25"
    assert F.derived_knowledge(["2026-09-24", None]) is None
    assert F.derived_knowledge([]) is None
    assert F.derived_knowledge(["20260924"]) == "2026-09-24"


def _sessions(n, last="2026-09-24"):
    import datetime as _dt
    end = _dt.date.fromisoformat(last)
    return [(end - _dt.timedelta(days=k)).isoformat() for k in range(n)][::-1]


def test_P2_the_tapes_change_and_percentile_are_known_WHEN_THE_SETTLE_IS():
    """MEASURED on arm A: settle [N89] known 2026-09-25, change [N93] / percentile [N94] known 2026-09-24."""
    rows = [{"value": str(500 + i), "knowledge_date": d, "contract_month": "2026-12", "settle_kind": "official",
             "currency": "EUR", "unit": "EUR/t"} for i, d in enumerate(_sessions(120))]
    t = F.tape_state("french_wheat_matif", "2026-09-26", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    settle_known = F.tape_known_date(t)
    assert settle_known > t.level_date, "the settle carries the card's publication lag"
    assert all(c["knowledge_date"] == settle_known for c in t.changes if not c["declined"])
    assert t.percentile["knowledge_date"] == settle_known
    assert all(c["to_date"] == t.level_date for c in t.changes), "the window's END SESSION does not move"
    assert F.TR.re_execute_all(t.derivation, t.inputs) == [], "the stats results are never mutated"


def test_P2_a_series_rows_derived_measures_carry_their_OWN_inputs_max_and_reexecute_clean():
    st = _row(reader=_probe_reader(US_SOY_VINTAGES))
    assert st.z["knowledge_date"] == "2024-01-12" and st.percentile["knowledge_date"] == "2024-01-12"
    assert all(c["knowledge_date"] == "2024-01-12" for c in st.changes if not c["declined"])
    assert F.re_execute_row(st) == []
    assert F.DERIVED_UNREAD_KEY not in st.recency


def test_P2a_an_input_with_NO_stamp_leaves_HEADs_stamp_and_is_COUNTED():
    st = StateRow(key=SeriesKey(ref="x"), z={"stat": "zscore", "declined": False, "value": 1.0, "window": 3},
                  percentile={"stat": "percentile", "declined": False, "value": 50.0, "n": 3},
                  changes=[{"window": "1 month", "n_periods": 1, "declined": False, "to_date": "2026-03"}])
    n = F.stamp_derived_known(st, {"2026-01": "2026-02-10", "2026-02": None, "2026-03": "2026-04-10"},
                              ["2026-01", "2026-02", "2026-03"])
    assert n == 3 and "knowledge_date" not in st.z and "knowledge_date" not in st.percentile
    assert "knowledge_date" not in st.changes[0]


# ── P-3: the population ───────────────────────────────────────────────────────────────────────────────
def test_P3_a_bounded_read_is_a_WINDOW_with_its_start_and_a_whole_history_read_is_the_RECORD():
    months = ["2015-%02d" % m for m in range(8, 13)] + ["20%02d-%02d" % (y, m) for y in range(16, 27)
                                                        for m in range(1, 13)]
    w = F.population_of(months, n=len(months), span=("months", 132), truncated=False, first_obs=None)
    assert w["whole"] is False and w["basis"] == "window" and w["first"] == "2015-08"
    whole = F.population_of(["1964", "2020"], n=57, span=None, truncated=False)
    assert whole == {"first": "1964", "last": "2020", "n": 57, "whole": True, "basis": "series"}
    assert F.population_of(["1964", "2020"], n=57, span=None, truncated=True)["whole"] is False
    reached = F.population_of(["2006-06-13", "2026-09-15"], n=900, span=("weeks", 164), truncated=False,
                              first_obs="2006-06-13")
    assert reached["whole"] is True
    cot = F.population_of(["2023-08-01", "2026-09-15"], n=164, span=("weeks", 164), truncated=False,
                          first_obs="2006-06-13")
    assert cot["whole"] is False and cot["first"] == "2023-08-01"


def test_P3_the_row_carries_the_population_ITS_percentile_used():
    st = _row(reader=_probe_reader(US_SOY_VINTAGES))
    pop = getattr(st, "population")
    assert pop["n"] == st.percentile["n"] == 31 and pop["whole"] is True and pop["last"] == "2020"


# ── P-4: the one derivation, on the seat's own row shapes ─────────────────────────────────────────────
def test_P4_the_seats_year_month_rows_derive_the_SAME_known_date_the_board_prints():
    """The control page's "[known 2026-07]" on a July ONI value: the ONE derivation gives 2026-09-05 from the
    seat row's own (year, month) aliases -- strings on the served path -- and the metric's own lag on a card
    that declares per-metric lags. H's ``citations._known_date`` reads this producer (PC-9)."""
    reg = load_registry()
    assert F.derive_knowledge_date(reg.get("silver_noaa_oni"), {"year": "2026", "month": "7"})[0] == "2026-09-05"
    gw = reg.get("gold_weather_z")
    assert F.derive_knowledge_date(gw, {"year": "2026", "month": "8", "metric": "drought_z"})[0] == "2026-09-25"
    assert F.derive_knowledge_date(gw, {"year": "2026", "month": "8", "metric": "heat_stress_z"})[0] == \
        "2026-09-05"


# ── m7: the action ledger's word ──────────────────────────────────────────────────────────────────────
def test_m7_every_regime_node_unanchored_says_UNANCHORED_and_the_count_stands():
    nodes = {("soybeans_cbot", "US_section301_tariffs"): ("drivers/tariff",)}
    led, stamp = F.action_ledger(nodes, asof=ASOF_2024, anchors={}, reader=lambda *a, **k: {})
    assert led == {} and stamp["why"] == "unanchored" and stamp["nodes"] == 1 and stamp["read"] is False
    assert F.action_ledger({}, asof=ASOF_2024)[1]["why"] == "no_nodes"
    assert F.ACTION_LEDGER_WHY[:4] == ("no_nodes", "no_asof", "no_pool", "read_error"), "append-never-sort"
    assert "unanchored" in F.ACTION_LEDGER_WHY
