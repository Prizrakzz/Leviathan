"""FIX ROUND 2 (09-24 re-smoke) -- THE FIXER PASS. One pin per review item the fixer closed that no lane
deck already pins, each on the review's OWN probe shape (REVIEW_VC / REVIEW_RA / REVIEW_WT, fix_round_0924).

  WT MAJOR-1  a later non-guidance document on a policy node supersedes the regime claim of an older action
  WT MAJOR-2  a document dated to a month / year FLOOR is an interval: an event inside it is a report
  WT MAJOR-3  the distance-0 test on EVERY seat; the horizon reads a chain on the question's own market
  WT MAJOR-5  O-5's single-market test counts the question's OWN markets, never the planner's seeds
  WT lexical  a far tape is READ when it carries a move (never a typed status subset)
  RA M2       the terminal standing prints only the reading the verdict read, at THAT row's handle
  RA M3       an FX row is named by its own series ("IDR/USD exchange rate"), and a global series is never
              prefixed by a market; the market rides ", on <board>" (no article test)
  RA M5       a horizon asked and not answered on the question's markets prints its decline line
  RA lexical  the append-only law is graded at CLAUSE grain; `_identifying_names` replaces the 8-char floor
  VC M2 / RA M7  the numbers seat's served calls reach the K23 store-period pass and re-take the rank
  VC M5       the K23 scope join keys on the query layer's own country canonicalisation
  WT lexical  rice's all-class milled words come from the card's family rule (the one-off line is retired)
  VC F1       an EvidenceLedger ISSUES only the addresses the block printed
  T  (RA M10) the cascade verdict / preamble / lag-gate lines speak the register table under the key and are
              HEAD's bytes off it
"""
from __future__ import annotations

import types

from leviathan.graphrag import citations as cit
from leviathan.graphrag.numbers import cascade as CQ
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import rows as RW
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.board import Anchor
from leviathan.graphrag.state.walk import parse_lag


# ── WT MAJOR-1 / MAJOR-2: the regime ladder ────────────────────────────────────────────────────────────────
def _rc(event_date, precision, doc, *, kind=None, text="x"):
    r = {"event_date": event_date, "event_date_precision": precision, "date": doc, "source": "s",
         "text": text, "source_key": "k" + event_date + doc}
    if kind is not None:
        r["date_kind"] = kind
    return r


_BAND = parse_lag("0-4 quarters")
IMPOSE_2018 = _rc("2018-07-06", "day", "2021-02-04")          # MPOC's dated report of the 2018 duty (realised)
EXCL_2020_UNPLACED = _rc("2020-03-02", "", "2022-03-17")       # the 2020 exclusion, no stored precision
EXCL_2020_STRADDLE = _rc("2020-03-01", "month", "2020-03-20")  # "in March 2020", reported inside March


def test_fixer_WT_MAJOR1_an_older_action_is_never_the_regime_over_a_later_unplaced_document():
    got = W.hop_event([IMPOSE_2018, EXCL_2020_UNPLACED], asof="2026-09-24", band=_BAND,
                      node_type="policy_event")
    assert got["kind"] in ("report_in_reach", "report_outside"), got["kind"]
    assert got["event_date"] == "2020-03-02" and got["interval"] == ()     # unplaced: no day printed
    alone = W.hop_event([IMPOSE_2018], asof="2026-09-24", band=_BAND, node_type="policy_event")
    assert alone["kind"] == "regime_in_force" and alone["event_date"] == "2018-07-06"


def test_fixer_WT_MAJOR1_a_straddle_report_supersedes_the_older_regime_too():
    got = W.hop_event([IMPOSE_2018, EXCL_2020_STRADDLE], asof="2026-09-24", band=_BAND,
                      node_type="policy_event")
    assert got["kind"] in ("report_in_reach", "report_outside") and got["event_date"] == "2020-03-01"


def test_fixer_WT_MAJOR1_guidance_never_supersedes_a_realised_action():
    """O-6 holds: a scheduled / conditional statement (wholly after its own document) is not a later
    event, so the realised action keeps the regime."""
    cond = _rc("2027-04-01", "month", "2026-03-28")
    got = W.hop_event([IMPOSE_2018, cond], asof="2027-09-24", band=_BAND, node_type="policy_event")
    assert got["kind"] == "regime_in_force" and got["event_date"] == "2018-07-06"


def test_fixer_WT_MAJOR2_a_month_floored_document_reporting_a_day_inside_its_month_is_a_report():
    """probes/p2_floored_doc: a CMO outlook keyed release=2022-04 (date 2022-04-01, date_kind key_month)
    reporting "Indonesia banned exports ... from 28 April 2022" -- a report, never a forecast, and an older
    realised DMO action cannot take the regime past it."""
    cmo = _rc("2022-04-28", "day", "2022-04-01", kind="key_month")
    assert not W.realised(cmo) and not W.is_guidance(cmo)
    assert W.document_interval(cmo) == ("2022-04-01", "2022-04-30")
    dmo = _rc("2022-01-27", "day", "2022-02-03", kind="key")
    got = W.hop_event([dmo, cmo], asof="2022-09-01", band=_BAND, node_type="policy_event")
    assert got["kind"] in ("report_in_reach", "report_outside") and got["event_date"] == "2022-04-28"
    # a document with NO declared kind is read at face value, as a day -- HEAD's reading
    assert W.document_interval({"date": "2022-04-01"}) == ("2022-04-01", "2022-04-01")
    # a year floor: an event ending before the year's first day is realised; one inside it is a report
    assert W.realised(_rc("2021-06-01", "month", "2022-01-01", kind="year_floor"))
    assert not W.realised(_rc("2022-06-01", "month", "2022-01-01", kind="year_floor"))
    assert not W.is_guidance(_rc("2022-06-01", "month", "2022-01-01", kind="year_floor"))
    # an epoch floor dates nothing: never an action
    assert not W.realised(_rc("2021-06-01", "day", "1970-01-01", kind="epoch_floor"))


# ── WT MAJOR-3: every seat on the question's own markets ────────────────────────────────────────────────────
def _chain(score, contract, terminal, ids, *, band="0-1 quarters"):
    hops = tuple(W.ChainHop(contract=contract, driver_id=h, seat=j, lag_band=parse_lag(band),
                            series_key="s_%s_%s" % (contract, h)) for j, h in enumerate(ids))
    ch = W.Chain(contract=contract, hops=hops, depth=len(hops) - 1, terminal=terminal)
    ch.score = score
    return ch


def test_fixer_WT_MAJOR3_an_off_question_chain_is_counted_never_seated():
    corn = _chain(95.0, "corn_cbot", "sorghum", ("China_state_reserves", "b1"))       # driver board's own
    into = _chain(80.0, "corn_cbot", "soybeans_cbot", ("planted_area", "b2"))         # runs INTO the question
    own = _chain(70.0, "soybeans_cbot", "soybeans_cbot", ("crush", "b3"))
    got = W.chain_render_set([corn, into, own], k=3, print_line=0.0,
                             question_markets=frozenset({"soybeans_cbot"}))
    seated = {(c.contract, c.terminal) for c in got["rendered"]}
    assert ("corn_cbot", "sorghum") not in seated and len(got["rendered"]) == 2
    assert got["counts"]["off_question"] == 1
    head = W.chain_render_set([corn, into, own], k=3, print_line=0.0)             # no reach: HEAD's reading
    assert len(head["rendered"]) == 3 and "off_question" not in head["counts"]


def test_fixer_WT_MAJOR3_the_horizon_is_answered_on_the_question_markets_own_tape():
    """`_outcome_for` reads `bd.tape[ch.contract]`, so the chain that answers the horizon must sit ON a
    question market -- a corn chain INTO soybeans would print corn's price history as the soybean answer."""
    into = _chain(90.0, "corn_cbot", "soybeans_cbot", ("planted_area", "b2"), band="1-2 quarters")
    got = W.chain_render_set([into], k=2, print_line=0.0, horizon_months=4,
                             question_markets=frozenset({"soybeans_cbot"}))
    assert got["counts"]["slot_state"]["horizon"] == "no_candidate"
    assert not any(getattr(c, "answers_horizon", False) for c in got["rendered"])
    own = _chain(60.0, "soybeans_cbot", "soybeans_cbot", ("crush", "b3"), band="1-2 quarters")
    got2 = W.chain_render_set([into, own], k=2, print_line=0.0, horizon_months=4,
                              question_markets=frozenset({"soybeans_cbot"}))
    assert [c.contract for c in got2["rendered"] if c.answers_horizon] == ["soybeans_cbot"]
    # and a question-market chain that LANDS on another board (the 2024 / deep "China import tariff into BMF
    # corn") never answers the question market's horizon
    out = _chain(95.0, "soybeans_cbot", "campinas_corn_reference_bmf", ("China_import_tariff", "b4"),
                 band="1-2 quarters")
    got3 = W.chain_render_set([out, own], k=2, print_line=0.0, horizon_months=4,
                              question_markets=frozenset({"soybeans_cbot"}))
    assert [(c.contract, c.terminal) for c in got3["rendered"] if c.answers_horizon] ==         [("soybeans_cbot", "soybeans_cbot")]


# ── WT MAJOR-5: single-market counts the question's own words ────────────────────────────────────────────────
def test_fixer_WT_MAJOR5_single_market_counts_named_anchors_never_planner_seeds():
    bd = types.SimpleNamespace(
        subject={"picked": ["brazil_soybean_supply"], "hints": {"exact": [], "alias": []}},
        question_reach=(("soybeans_cbot", 0), ("soybean_oil_cbot", 0), ("corn_cbot", 1)),
        anchors=[Anchor(contract="soybeans_cbot", source="named", named=True),
                 Anchor(contract="soybean_oil_cbot", source="planner_inferred")])
    graph = types.SimpleNamespace(contracts={})
    got = W.subject_standing(bd, graph)
    assert got["single_market"] is True                   # the question named ONE market
    bd.anchors.append(Anchor(contract="soybean_oil_cbot", source="named", named=True))
    assert W.subject_standing(bd, graph)["single_market"] is False


# ── WT lexical: the far tape is read when it carries a move ─────────────────────────────────────────────────
def test_fixer_WT_lexical_a_tape_is_read_by_its_move_never_by_a_status_word():
    moved = types.SimpleNamespace(status="weird_new_word", changes=[{"declined": False, "delta": 3.5}])
    none = types.SimpleNamespace(status="ok", changes=[{"declined": True}])
    assert W._has_move(moved) is True and W._has_move(none) is False


# ── RA M3 / lexical 9: the FX identity and the market's place ───────────────────────────────────────────────
def test_fixer_RA_M3_an_fx_row_is_named_by_its_own_series():
    assert R.series_name_words("silver_fred_fx", "idr_usd", "", "IDR/USD exchange rate") == \
        "IDR/USD exchange rate"
    assert R.series_name_words("silver_fred_fx", "myr_usd", "", "MYR/USD exchange rate") == \
        "MYR/USD exchange rate"
    # a label that carries a digit never becomes a name (the reading-words law): the card-wide words stand
    assert "90" not in R.series_name_words("silver_fred_fx", "idr_usd_pct_change_90d", "",
                                           "IDR/USD 90-day % change")
    # a metric the book declares exactly keeps its own words
    assert R.series_name_words("silver_psd", "su_ratio", "", "stocks-to-use ratio") == "the stocks-to-use ratio"


def test_fixer_RA_M3_a_global_series_is_never_named_on_a_market_and_a_market_needs_no_article_test():
    hop_fx = types.SimpleNamespace(contract="corn_cbot", series_key="fred_fx_macro|_global||brl_usd")
    assert R._market_prefixed("BRL/USD exchange rate", hop_fx, None, ("soybeans_cbot",)) == \
        "BRL/USD exchange rate"
    hop_rs = types.SimpleNamespace(contract="rapeseed_matif",
                                   series_key="psd_ending_stock_su_ratio|rapeseed_matif|European Union|")
    got = R._market_prefixed("the stocks-to-use ratio, for European Union", hop_rs, None, ("palm",))
    assert got == "the stocks-to-use ratio, for European Union, on %s" % R.board_label("rapeseed_matif")
    assert RW._with_commodity("production", "sunflower oil") == "production of sunflower oil"
    assert RW._with_commodity("the stocks-to-use ratio", "rapeseed") == "the stocks-to-use ratio of rapeseed"
    assert RW._with_commodity("sunflower oil production", "sunflower oil") == "sunflower oil production"


# ── WT lexical (B-R3): rice's class words come from the family rule ────────────────────────────────────────
def test_fixer_WT_lexical_rice_class_words_are_the_family_rules_and_the_one_off_is_retired():
    from leviathan.graphrag.state import lint as L
    assert "silver_psd.ending_stocks_mt@rough_rice_cbot" not in (L.load_conventions() or {}).get(
        "reading_words", {})
    assert R.family_class_words("silver_psd", "rough_rice_cbot") == "all classes, milled basis"
    assert R.family_class_words("silver_psd", "soft_red_winter_wheat_cbot") == "all classes"
    assert R.family_class_words("silver_psd", "corn_cbot") == ""
    ident = RW.RowIdentity(row_id="r", contract="rough_rice_cbot", driver_id="d", series_key="k",
                           table="silver_psd", metric="ending_stocks_mt", name="ending stocks",
                           scope="United States", class_words="all classes, milled basis")
    assert ident.series_words() == "ending stocks, all classes, milled basis, for United States"


# ── RA M5: the horizon's decline line ───────────────────────────────────────────────────────────────────────
def test_fixer_RA_M5_a_horizon_no_on_question_chain_answers_prints_its_decline():
    bd = types.SimpleNamespace(horizon_months=3, chain_counts={"slot_state": {"horizon": "no_candidate"}})
    line = R.sb_ask_horizon_decline(bd)
    assert line.startswith("ASKED HORIZON three months: no chain on this question's own markets")
    assert R.ROW_CLASSES["SB-ASK"].match(line)
    for ss in ({"horizon": "seated"}, {"horizon": "not_asked"}, {}):
        assert R.sb_ask_horizon_decline(types.SimpleNamespace(horizon_months=3,
                                                              chain_counts={"slot_state": ss})) == ""
    assert R.sb_ask_horizon_decline(types.SimpleNamespace(horizon_months=None, chain_counts={})) == ""


# ── RA M2: the terminal standing ─────────────────────────────────────────────────────────────────────────────
def test_fixer_RA_M2_the_terminal_standing_is_the_verdicts_own_reading_or_nothing():
    last = W.ChainHop(contract="cotton", driver_id="El_Nino", series_key="oni")
    ch = W.Chain(contract="cotton", hops=(last,), depth=0, terminal="corn_cbot")
    ch.cross = {"other": "corn_cbot", "sign": "+"}
    ch.terminal_percentile = 82.0                        # the EARNED cross's far reading (the ONI)
    ch.edge_signs = ("+",)
    no = R.sb_chain_hop(ch, 0, terminal_handle=16)
    assert "whose own reading" not in no                  # no reading handed -> no standing clause
    yes = R.sb_chain_hop(ch, 0, terminal_handle=16, terminal_percentile=40.0)
    assert "whose own reading sits at the fortieth percentile" in yes


# ── RA lexical 10: identifying names by uniqueness ──────────────────────────────────────────────────────────
def test_fixer_RA_lexical10_a_name_identifies_a_link_by_uniqueness_never_by_length():
    got = R._identifying_names([("crush", "the crush margin"), ("crush", "soybean oil"), ("the", "yield")])
    assert got[0] == ("the crush margin",)                # "crush" names two links: it names neither
    assert got[1] == ("soybean oil",) or got[1] == ()     # content words by the verifier's own reader
    assert "the" not in got[2]


# ── RA lexical 11: the append-only law at clause grain ──────────────────────────────────────────────────────
def test_fixer_RA_lexical11_the_append_only_law_grades_clauses_not_sentences():
    from leviathan.graphrag.state import lint as L

    def clause_end(box):
        box["mechanism"] = box["mechanism"].replace("set the EU balance,",
                                                    "set the EU balance -- the ratio reads 9.42 % [N60],")
    probe = {"mechanism": "The seed's stocks-to-use ratio and supply set the EU balance, and the seed "
                          "carries the oil share."}
    rep = L.chain_append_only_report(clause_end, probe=probe)
    assert rep["errors"] == [], rep["errors"]

    def deleter(box):
        box["mechanism"] = box["mechanism"].replace(" and supply", "")
    assert L.chain_append_only_report(deleter, probe=probe)["errors"]


# ── VC M2 / RA M7: the seat's calls reach the K23 pass at stage 2 ──────────────────────────────────────────
def test_fixer_VC_M2_the_seat_calls_stamp_and_re_rank_the_behind_row():
    from leviathan.graphrag.state.rows import SeriesKey, StateRow
    st = StateRow(key=SeriesKey(ref="psd_ending_stock_su_ratio", commodity="soybeans_cbot",
                                country="United States"), status="ok", reads=1)
    st.table, st.metric, st.level_date, st.knowledge_date = "silver_psd", "su_ratio", "2020", "2021-01-12"
    row = types.SimpleNamespace(state=st, rank=(0,), coverage_tier="series", contract="soybeans_cbot",
                                driver_id="d")
    wasde = {"query": {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "soybeans",
                       "country": "United States"},
             "rows": [{"value": 315, "unit": "Million Bushels", "period": "2023/24",
                       "knowledge_date": "2024-02-08"}], "status": "ok"}
    calls = {"n": 0}
    bd = types.SimpleNamespace(rows=[row], asof="2024-03-01", rank_rule=False, notes=[])
    orig_key, orig_order = W.rank_key_for, W.board_order
    try:
        W.rank_key_for = lambda rule: (lambda r: ("re-taken",))
        W.board_order = lambda b: calls.__setitem__("n", calls["n"] + 1)
        n = W.restamp_store_period(bd, [wasde])
    finally:
        W.rank_key_for, W.board_order = orig_key, orig_order
    # the 2024 page's shape: PSD US soybeans MY2020 beside the seat's WASDE US soybeans 2023/24 -- the ONE
    # newer period the store held -- is stamped behind at stage 2 and its rank is re-taken
    assert dict(st.period_behind) == {"held": "2020/21", "newer_on": "USDA WASDE", "newer": "2023/24"}
    assert n == 1 and row.rank == ("re-taken",) and calls["n"] == 1
    assert bd.notes and bd.notes[-1]["kind"] == "period_behind_seat"
    # a WASDE sheet known AFTER the as-of is no evidence, and a second run moves nothing (idempotent)
    assert W.restamp_store_period(bd, [wasde]) == 0


# ── VC M5: the scope join keys on the store's own partition value ───────────────────────────────────────────
def test_fixer_VC_M5_the_scope_join_is_the_query_layers_country_canonicalisation():
    from leviathan.graphrag.state.feeders import _scope_norm
    assert _scope_norm("United States") == _scope_norm("united_states") == _scope_norm("US") == "united_states"
    assert _scope_norm("Brazil") != _scope_norm("United States")


# ── VC F1: the ledger issues only what the block printed ────────────────────────────────────────────────────
def test_fixer_VC_F1_the_ledger_issues_only_the_addresses_the_block_printed():
    menu = [{"source": "a", "date": "2020-01-01", "text": "t1", "source_key": "k1"},
            {"source": "b", "date": "2021-01-01", "text": "t2", "source_key": "k2"}]
    led = cit.EvidenceLedger(menu)
    assert led.issued() == {}
    k = led.address({"source": "b", "date": "2021-01-01", "text": "t2 other chunk", "source_key": "k2"})
    k3 = led.address({"source": "c", "date": "2022-01-01", "text": "t3", "source_key": "k3"})
    iss = led.issued()
    assert (k, k3) == (2, 3) and sorted(iss) == [2, 3]
    assert [r["text"] for r in iss[2]] == ["t2", "t2 other chunk"]
    assert 1 not in iss                                   # a menu index the block never printed
    assert set(led.chunks()) <= set(iss)


# ── T (RA M10): the cascade print sites under the display key ───────────────────────────────────────────────
def test_fixer_RA_M10_the_cascade_verdict_preamble_and_lag_gate_speak_the_register_under_the_key():
    on = [CQ._cw_verdict_line("A", "B", v, display="analyst") for v in ("aligned", "at_odds", "x")]
    on.append(CQ._cw_verdict_line("A", "B", "x", reason="fx_flips_sign", xccy=("USD", "EUR"), display="analyst"))
    on.append(CQ._cw_marker("third", context=True, fx=True, display="analyst"))
    on.append(CQ._cw_absence("A", "lag_gate", display="analyst"))
    on.append(CQ._cw_hop_header("A", "B", ["x"], "", "heat", display="analyst"))
    for ln in on:
        assert "firing" not in ln.lower(), ln
    off = CQ._cw_verdict_line("A", "B", "aligned")
    assert off.endswith("held on this firing; the moves above are the record, in-sample on the named "
                        "window only, never extended beyond it.")
    assert "same dated firing window" in CQ._cw_marker("first")
    from leviathan.graphrag import register as RG
    assert RG.desk_phrase("firing", 1) in on[0]           # the words are the TABLE's, read, never typed


# ── RA M4: the ask head names the SERIES a calculator row was computed over (the real producers, end to end) ──
def test_fixer_RA_M4_the_ask_head_names_the_source_series_through_the_real_agent_row():
    """The 09-24 palm/rape head printed the rapeseed-side row of the question's own comparison as "ending stocks
    (change over the window) for china" -- no commodity. Lane T's `_stat_calls` now stamps, under the board
    kwarg only, the lookup's OWN query on the change row (`source_query`), and the head names the row through
    lane C's one identity reader over that source call. Board off: HEAD's row, with no `source_query`."""
    from leviathan.graphrag.numbers import agent as A
    res = {"stat": "window_change", "declined": False, "value": 170000.0, "n": 3, "pct_change": 70.25,
           "t1": 0, "t2": -1}
    src = {"table": "silver_mpoc_stock_comparison", "metric": "ending_stocks_mt",
           "commodity": "french_rapeseed_matif", "country": "china"}
    obs = ["2026-01", "2026-03", "2026-06"]
    off = A._stat_calls("window_change", dict(res), {}, "MT", "2026-09-11", {"country": "china"},
                        "silver_mpoc_stock_comparison", "ending_stocks_mt")
    assert "source_query" not in off[0]["rows"][0]
    on = A._stat_calls("window_change", dict(res), {}, "MT", "2026-09-11", {"country": "china"},
                       "silver_mpoc_stock_comparison", "ending_stocks_mt", board=True, obs=obs, src_query=src)
    assert on[0]["rows"][0]["source_query"] == src
    name, period, _unit = R.ask_row_words(on[0])
    commodity = R.commodity_node("french_rapeseed_matif")
    assert commodity and commodity in name and name.endswith(" change"), name
    assert "(change over the window)" not in name and period.startswith("from "), (name, period)
    line = R.sb_ask_row(12, on[0])
    assert line.startswith("ASKED ROW [N12] %s" % name) and "+170,000" in line, line
    # the head without the stamp keeps the seat row's own identity (HEAD's words)
    assert "(change over the window)" in R.ask_row_words(off[0])[0]
