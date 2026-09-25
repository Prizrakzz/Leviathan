"""THE 09-25 RE-SMOKE FIX ROUND, LANE RT -- the then/now lane informs a call in its own units, a cell is a cell,
a reading's side speaks the series' own words, the marketing year rides the figure, a chain's peak has an
address at every tier, the watch list watches the call, a publisher's two releases are vintages, and the count
line is a plain count.

Each pin names its item (fix_round_0925 brief: RT-1 .. RT-8; the 09-25 chain read N3 / N11 / N13; the fact and
PM grades' D11, the cocoa FATAL, F-W1). Every pin is offline and $0: hand-built rows in the shapes the producers
emit, the shipped cards and conventions, and the harness fixture boards through the serving seam -- no read, no
model call.
"""
from __future__ import annotations

import dataclasses
import types

import pytest

from leviathan.graphrag import graph as G
from leviathan.graphrag import register as REG
from leviathan.graphrag.numbers import registry as REGY
from leviathan.graphrag.state import __main__ as M
from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import lint as L
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import rows as ROWS
from leviathan.graphrag.state import seam as S
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.lagbands import parse_lag

ASOF = "2026-09-25"


def _wz(metric="drought_z", level=-0.9183, pct=3.4, z=-1.49, country="West Africa", contract="cocoa"):
    ref = {"drought_z": "drought_z", "tmax_anomaly": "stage_tmax_anomaly"}.get(metric, metric)
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref=ref, commodity=contract, country=country), status="ok",
                       table="gold_weather_z", metric=metric, cadence="monthly", unit="z", narrate_unit="z",
                       scale=1.0, level=level, level_date="2026-08", knowledge_date="2026-09-25", asof=ASOF)
    st.z = {"value": z, "window_n": 120}
    st.percentile = {"value": pct}
    return st


def _row(st, contract="cocoa", driver_id="drought", sign="+"):
    return B.NodeRow(contract=contract, driver_id=driver_id, state=st, sign=sign,
                     lag_band=parse_lag("0-2 quarters"))


def _build_soy_deep():
    """The harness soybeans board at deep, chain lit, through the serving seam -- the fixture every render deck
    already renders; one build per module."""
    g = G.CausalGraph(G.load_contracts(), silver=set(), version="harness")
    sg = types.SimpleNamespace(seeds=["soybeans_cbot"], nodes=[], trace={})
    q = "what is the situation on soybeans now? how is it looking 3 months from now?"
    bd = S.fill_stage1(graph=g, sg=sg, asof=M.ASOF, mode="deep", query=q,
                       state_fn=M.fixture_state_fn(M.ASOF), named=("soybeans_cbot",))
    got = S.fill_stage2(bd, graph=g, sg=sg, state_fn=M.fixture_state_fn(M.ASOF), state_chain=True,
                        watch_nonobvious=True)
    return bd, got


@pytest.fixture(scope="module")
def soy_deep():
    return _build_soy_deep()


# ── RT-1: THE LIKE-STATE OUTCOME IN ITS OWN UNITS ─────────────────────────────────────────────────────────────
def _seed(values, dates, band="1-2 quarters"):
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="oni_climate", commodity="_global", country=""), status="ok",
                       table="silver_noaa_oni", metric="oni_anom", cadence="monthly", unit="degC",
                       narrate_unit="degC", scale=1.0, level=values[-1], level_date=dates[-1], asof=ASOF)
    st.inputs = {st.key.label(): {"values": values, "dates": dates}}
    return B.NodeRow(contract="soybeans_cbot", driver_id="El_Nino", state=st, sign="-",
                     lag_band=parse_lag(band))


def _months(y0, m0, n):
    out = []
    y, m = y0, m0
    for _ in range(n):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def test_RT1_the_own_units_outcome_is_the_seeds_own_series_over_its_band_and_is_not_a_price_move():
    dates = _months(2024, 1, 30)
    vals = [round(0.1 * i - 1.0, 2) for i in range(30)]
    o = A.own_units_outcome(_seed(vals, dates), "2025-02", asof=ASOF, lag_days=36)
    assert o["own_series"] is True and o["call_units"] is False and not o["declined"]
    assert o["label"] == R.reading_words("silver_noaa_oni", "oni_anom")      # the series' own reader words
    assert o["from_date"] == "2025-02" and o["near_date"] == "2025-05" and o["far_date"] == "2025-08"
    assert o["near_value"] == pytest.approx(0.3) and o["far_value"] == pytest.approx(0.6)
    assert o["unit"] == "degC"


def test_RT1_a_tape_that_starts_after_the_like_date_declines_by_name_and_the_own_series_reads_instead():
    dates = _months(2020, 1, 80)
    vals = [0.5 + 0.01 * i for i in range(80)]
    seed = _seed(vals, dates)
    tape = types.SimpleNamespace(status="ok", slug="soybeans_cbot", contract_month="2026-11", unit="US cents/bushel",
                                 inputs={"soybeans_cbot|2026-11": {
                                     "values": [1100.0 + i for i in range(56)],
                                     "dates": (["2025-06-%02d" % (d + 1) for d in range(28)]
                                               + ["2025-07-%02d" % (d + 1) for d in range(28)])}})
    bd = types.SimpleNamespace(tape={"soybeans_cbot": tape}, asof=ASOF, fan=[], row=lambda c, d: None,
                               ledger=types.SimpleNamespace(benchmark_reads=0))
    seed.children = ()
    outs = A._outcomes_for(bd, seed, "2025-02")
    price = [o for o in outs if o.get("call_units")]
    assert price and price[0]["declined"] == "tape_after_like_date"
    assert price[0]["record_from"] == "2025-06-01"
    own = [o for o in outs if o.get("own_series")]
    assert len(own) == 1 and not own[0]["declined"]
    # the word is a closed vocabulary entry with its own reader sentence (lint clause 9)
    assert "tape_after_like_date" in A.OUTCOME_DECLINES and "tape_after_like_date" in R.ABSENCE_WHY
    assert not [e for e in L.check_state_board() if "tape_after_like_date" in e]


def test_RT1_a_stanza_with_a_price_outcome_mints_no_own_units_row():
    dates = _months(2020, 1, 80)
    seed = _seed([0.1] * 80, dates)
    tape = types.SimpleNamespace(status="ok", slug="soybeans_cbot", contract_month="2026-11", unit="c",
                                 inputs={"soybeans_cbot|2026-11": {"values": [1000.0 + i for i in range(80)],
                                                                   "dates": dates}})
    bd = types.SimpleNamespace(tape={"soybeans_cbot": tape}, asof=ASOF, fan=[], row=lambda c, d: None,
                               ledger=types.SimpleNamespace(benchmark_reads=0))
    seed.children = ()
    outs = A._outcomes_for(bd, seed, "2024-02")
    assert [o for o in outs if o.get("call_units") and not o.get("declined")]
    assert not [o for o in outs if o.get("own_series")], "HEAD's outcome set on a stanza that has a price"


def test_RT1_the_stanza_fate_is_withheld_only_with_no_outcome_of_any_kind():
    per = ({"sign_agree": True},)
    price_no = {"label": "the CBOT soybeans November 2026 delivery", "call_units": True,
                "declined": "tape_after_like_date", "record_from": "2025-06-04"}
    own = {"label": "the tropical Pacific sea-surface temperature anomaly", "own_series": True,
           "call_units": False, "declined": None}
    assert R.analog_stanza_fate({"per_dim": per, "outcomes": [price_no, own]}) == ("own_units", "")
    assert R.analog_stanza_fate({"per_dim": per, "outcomes": [price_no]}) == ("withheld", "tape_after_like_date")
    assert R.analog_stanza_fate({"per_dim": ({"sign_agree": False},), "outcomes": [price_no, own]}) == \
        ("withheld", "no_like_state")
    assert R.analog_stanza_fate({"per_dim": per, "outcomes": [dict(price_no, declined=None), own]})[0] == "price"
    assert R.analog_stanza_fate({"outcomes": [price_no]})[0] == "price"        # a hand-built deck row: HEAD's


def test_RT1_the_not_a_price_line_says_what_it_cannot_say_in_desk_words():
    a = {"contract": "soybeans_cbot", "driver_id": "El_Nino", "date": "2020-01"}
    price = {"label": "the CBOT soybeans May 2024 delivery", "call_units": True,
             "declined": "tape_after_like_date", "record_from": "2022-11-10"}
    own = {"label": "the tropical Pacific sea-surface temperature anomaly", "own_series": True}
    line = R.sb_analog_not_price(a, name="El Nino", price=price, others=[own])
    assert line.startswith("LIKE STATE El Nino on CBOT soybeans: the CBOT soybeans May 2024 delivery carries no "
                           "price move over the band from January 2020")
    assert "its record here starts in November 2022, after that date" in line
    assert "the path of the tropical Pacific sea-surface temperature anomaly itself" in line
    assert line.endswith("not a price outcome")
    assert R.classify(line) == ("SB-A",) and R.register_hits(line) == [] and REG.count_desk_register(line) == 0
    # a decline whose closed sentence the desk table charges ("this row") is said as the plain fact
    other = R.sb_analog_not_price(a, name="El Nino", price=dict(price, declined="read_error"), others=[own])
    assert "row" not in other and REG.count_desk_register(other) == 0


def test_RT1_the_harness_stanza_prints_in_own_units_where_HEAD_withheld_it(soy_deep):
    bd, got = soy_deep
    block = got["block"]
    lines = [ln for ln in block.splitlines() if ln.startswith("LIKE STATE El Nino on CBOT soybeans")]
    assert any("not a price outcome" in ln for ln in lines), lines
    assert "BOARD ABSENCE a price outcome of CBOT soybeans over the band from its like state" not in block
    assert any(ln.startswith("- [N") and "the tropical Pacific sea-surface temperature anomaly over the band" in ln
               for ln in block.splitlines())
    tr = [a for a in bd.analogs if a.get("driver_id") == "El_Nino" and "rendered" in a]
    assert tr and tr[0]["rendered"] is True and tr[0].get("outcome_units") == "own"
    assert any(o.get("own_series") for o in tr[0]["outcomes"])


# ── RT-2: A CELL IS A CELL, AND SAYS WHICH ONE ────────────────────────────────────────────────────────────────
N164_APRIL_2011 = [0.9003603729220594, 0.22360679774997883, -0.9909931939970745, -1.1052358582314172,
                   -1.136394423597312, -1.3431102193668325, -1.519297358258059, -1.6199559950018934,
                   -1.7140790708552462, -1.910543822789871]


def test_RT2_the_cell_standing_is_the_served_rows_own_order_statistic():
    assert ROWS.cell_standing(N164_APRIL_2011, N164_APRIL_2011[0]) == (1, 10, 10)
    assert ROWS.cell_standing(N164_APRIL_2011, N164_APRIL_2011[-1]) == (10, 1, 10)
    assert ROWS.cell_standing([1.0], 1.0) == (0, 0, 0)                  # one row is no standing
    assert ROWS.cell_standing([], "x") == (0, 0, 0)
    assert ROWS.cell_standing_words(1, 10, "driest") == "the driest of ten"
    assert ROWS.cell_standing_words(3, 10, "driest") == "the third driest of ten"
    assert ROWS.cell_standing_words(1, 10, "") == ""                    # no declared superlative, no standing


def test_RT2_the_deep_soy_N164_cell_reads_as_one_cell_the_driest_of_ten_ON_THE_FIGURE():
    w = R.cell_grain_words("gold_weather_z", "drought_z", scope="United States",
                           values_at_period=N164_APRIL_2011, headline=N164_APRIL_2011[0])
    assert w == "for one United States growing cell (the driest of ten)"
    tok = ROWS.figure_token("0.9 z", period_words="April 2011", grain_words=w)
    assert tok == "0.9 z for one United States growing cell (the driest of ten), April 2011"
    # the wettest end is named by the card's other superlative; a card on no cell axis gets nothing
    assert "(the wettest of ten)" in R.cell_grain_words("gold_weather_z", "drought_z", scope="United States",
                                                        values_at_period=N164_APRIL_2011,
                                                        headline=N164_APRIL_2011[-1])
    assert R.cell_grain_words("silver_psd", "su_ratio", scope="United States",
                              values_at_period=N164_APRIL_2011, headline=0.9) == ""


def test_RT2_a_ranked_cell_identity_says_which_cell_and_every_other_identity_is_HEADs():
    ident = ROWS.RowIdentity(row_id="x", contract="soybeans_cbot", driver_id="flash_drought", series_key="k",
                             table="gold_weather_z", metric="drought_z", name="the longest dry-day run",
                             axis="region_cell", scope="United States", cell_rule="one_of_cells",
                             cell_noun=("growing cell", "growing cells"), cell_n=10, cell_rank=1,
                             cell_extreme="driest")
    assert ident.scope_words() == " for one United States growing cell (the driest of ten)"
    assert ident.grain_words() == "for one United States growing cell (the driest of ten)"
    unranked = dataclasses.replace(ident, cell_rank=0, cell_extreme="")
    assert unranked.scope_words() == " for one of the ten United States growing cells"     # HEAD's words
    assert unranked.grain_words() == ""
    mean = dataclasses.replace(ident, cell_rule="mean_of_cells")
    assert mean.grain_words() == "" and "mean over the United States growing cells" in mean.scope_words()
    f = list(ROWS.RowIdentity.__dataclass_fields__)
    assert f[-2:] == ["cell_rank", "cell_extreme"], "appended at the TAIL; readers read defensively"


# ── RT-3: THE SIDE A READING SITS ON, IN THE SERIES' OWN WORDS ────────────────────────────────────────────────
def test_RT3_the_cocoa_N14_N20_rows_say_they_are_the_WET_and_COOL_side():
    drought, tmax = _wz(), _wz("tmax_anomaly", level=-0.668, pct=6.44, z=-1.23)
    assert R.tail_side_words(drought) == ("low", "shorter dry spells than usual, so wetter")
    assert R.tail_side_words(tmax) == ("low", "cooler than usual")
    line, _calls = R.sb_state(14, _row(drought), asof=ASOF, block=R.Block(start=14))
    assert "on the low side for this series: shorter dry spells than usual, so wetter" in line
    line2, _ = R.sb_state(20, _row(tmax, driver_id="harmattan"), asof=ASOF, block=R.Block(start=20))
    assert "on the low side for this series: cooler than usual" in line2
    assert R.register_hits(line) == [] and R.classify(line) == ("SB-1",)
    # the high side speaks its own words, and a series the book declares nothing for prints none
    dry = _wz(level=1.25, pct=96.6, z=1.9, country="SE Asia Palm Belt", contract="malaysian_crude_palm_oil_cme")
    assert R.tail_side_words(dry) == ("high", "longer dry spells than usual, so drier")
    psd = ROWS.StateRow(key=ROWS.SeriesKey(ref="export", commodity="x", country="India"), status="ok",
                        table="silver_psd", metric="exports_mt", level=25.0)
    psd.percentile = {"value": 99.0}
    assert R.tail_side_words(psd) is None


def test_RT3_the_watch_side_word_and_the_quorum_names_carry_the_same_words():
    assert WA._side_word(_wz()) == "on the low side, shorter dry spells than usual, so wetter"
    psd = ROWS.StateRow(key=ROWS.SeriesKey(ref="export", commodity="x", country="India"), status="ok",
                        table="silver_psd", metric="exports_mt", level=25.0)
    psd.percentile = {"value": 99.0}
    assert WA._side_word(psd) == "on the high side"                        # HEAD's words, no book entry


def test_RT3_the_tail_word_book_is_graded_by_lint_clause_18(monkeypatch):
    assert L._check_tail_words() == []
    book = dict(L.load_conventions())
    bad = dict(book)
    bad["tail_words"] = {"gold_weather_z.drought_z": {"low": {"side": "drier by 2 points"},
                                                      "high": {"side": "drier by 2 points"}},
                         "no_such.metric": {"low": {"side": "a"}, "high": {"side": "b"}}}
    monkeypatch.setattr(L, "load_conventions", lambda: bad)
    errs = L._check_tail_words()
    assert any("digit" in e for e in errs) and any("same words" in e for e in errs)
    assert any("no_such.metric" in e for e in errs)


# ── RT-4: THE MARKETING YEAR RIDES THE FIGURE ────────────────────────────────────────────────────────────────
def test_RT4_a_marketing_year_joins_its_figure_and_every_caller_naming_no_kind_keeps_HEADs_comma():
    assert ROWS.figure_token("325", unit="Million Bushels", period_words="2025/26",
                             period_kind="marketing_year") == "325 Million Bushels for 2025/26"
    assert ROWS.figure_token("325", unit="Million Bushels", period_words="2025/26") == \
        "325 Million Bushels, 2025/26"                                       # lane C's call today: HEAD's bytes
    # RE-BANKED 09-25 (the N8 restore, VERIFY MINOR-B): a crop season's label is a noun and its join carries
    # the article (`rows.PERIOD_TOKEN_JOINS`); a marketing year keeps the bare preposition (above)
    assert ROWS.figure_token("0.28 ratio", period_words="2024/25 season", period_kind="crop_season",
                             period_role="the ICCO release of 29 May 2026") == \
        "0.28 ratio for the 2024/25 season, the ICCO release of 29 May 2026"
    assert ROWS.figure_token("775.39 1000 MT", figure_basis="shipped in the week",
                             period_words="week to 17 September 2026", period_kind="week") == \
        "775.39 1000 MT shipped in the week, week to 17 September 2026"       # a phrase period keeps its comma


def test_RT4_the_board_row_prints_its_marketing_year_on_the_figure(soy_deep):
    _bd, got = soy_deep
    su = [ln for ln in got["block"].splitlines() if "stocks-to-use ratio" in ln and ln.startswith("- [N")]
    assert su and "% of domestic use for 2025/26" in su[0], su[:1]


# ── RT-5: THE PEAK HANDLE RIDES AN SB-1 ROW AT EVERY TIER ────────────────────────────────────────────────────
def test_RT5_a_chain_hop_whose_series_the_loud_cut_did_not_print_gets_its_row_and_both_handles():
    bd, _got = _build_soy_deep()                                    # its own board: this pin mutates it
    chains = [c for c in bd.chains if getattr(c, "rendered", False) and getattr(c, "full", False)]
    assert chains
    target = None
    for c in chains:
        for i, h in enumerate(c.hops):
            row = bd.row(h.contract, h.driver_id)
            if (h.measured and row is not None and row.state is not None and row.legs.get("loud")
                    and sum(1 for r in bd.rows if r.legs.get("loud") and r.state is not None
                            and r.state.key.label() == row.state.key.label()) == 1):
                target = (c, i, h, row)
                break
        if target:
            break
    assert target, "the harness board carries a measured hop on a loud row"
    c, i, h, row = target
    row.legs["loud"] = False                                        # the loud cut no longer prints it
    row.state.percentile = {"value": 33.0}
    hops = list(c.hops)
    hops[i] = dataclasses.replace(h, percentile=33.0, tail_peak_percentile=99.0, tail_peak_date="2026-06")
    c.hops = type(c.hops)(hops) if isinstance(c.hops, tuple) else hops
    blk = R.render_board(bd)
    metas = [m for m in blk.rows_meta if m.get("role") == "cited_state"]
    assert len(metas) >= 1 and metas[0]["line"].startswith("- [N"), metas
    line = metas[0]["line"]
    assert "peaked at the 99th percentile in June 2026" in line and "33rd percentile of its own record" in line
    rh = blk.row_handles[(h.contract, h.driver_id)]
    assert rh["peak"] and rh["percentile"]
    hop_lines = [ln for ln in blk.lines if "ninety-ninth percentile [N%d]" % rh["peak"] in ln]
    assert hop_lines and "thirty-third [N%d]" % rh["percentile"] in hop_lines[0]
    # it is NOT a loud row: it rides its own role with no rank, so no loud-cut denominator counts it
    assert metas[0].get("rank") is None
    assert not [m for m in blk.rows_meta if m.get("role") == "state" and m.get("line") == line]


# ── RT-6: THE WATCH LIST WATCHES THE CALL, AND EVERY FALSIFIER IS MINTED FROM ITS ROW ─────────────────────────
def test_RT6_the_call_rows_are_the_lead_readings_and_the_question_seat_links(soy_deep):
    bd, _got = soy_deep
    calls = WA.call_rows(bd)
    order = {k: i for i, k in enumerate(bd.order)}
    loud = sorted((r for r in bd.rows if r.legs.get("loud") and r.state is not None), key=lambda r: order.get(r.key))
    assert loud[0].key in calls, "the page's loudest reading is a call row"
    for c in bd.chains:
        if getattr(c, "rendered", False) and str(getattr(c, "slot", "")) in ("subject", "pair", "horizon"):
            assert all(h.key in calls for h in c.hops if h.measured)


def test_RT6_the_draw_seats_the_call_rows_first_inside_the_ceiling(soy_deep):
    bd, _got = soy_deep
    rows = WA.nonobvious_rows(bd)
    core = [r for r in rows if r.get("slot") == "ceiling"]
    calls = WA.call_rows(bd)
    cands = WA.nonobvious_candidates(bd)
    call_cands = {c["row"] for c in cands if c["row"] in calls}
    assert core and all(r.get("call_row") for r in core[:1])
    seated = {r["row"] for r in core}
    # every call row with a candidate is in the core, or the core is full of call rows under the caps
    assert call_cands <= seated or len(core) == int(core[0]["ceiling"])


def test_RT6_a_state_return_falsifier_names_its_direction_in_the_series_own_words():
    row = _row(_wz())
    c = WA._cand("tail_reading", row, what="x", dates="", floor=("record_tail",))
    assert c["falsifier"].endswith("-- a move up from its low side, away from shorter dry spells than usual, "
                                   "so wetter")
    hi = _row(_wz(level=1.25, pct=96.6, z=1.9, country="SE Asia Palm Belt"), contract="malaysian_crude_palm_oil_cme")
    c2 = WA._cand("tail_reading", hi, what="x", dates="", floor=("record_tail",))
    assert "a move down from its high side, away from longer dry spells than usual, so drier" in c2["falsifier"]


def test_RT6_a_crossed_line_is_named_at_its_value_in_words():
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="esr_exports", commodity="soybeans_cbot", country=""), status="ok",
                       table="silver_esr", metric="weekly_exports_1000mt", cadence="weekly", level=775.39)
    st.convention = {"label": "ahead", "band": 10.0, "matched": True, "kind": "pace_vs_prior_year",
                     "reading": 25.0}
    c = WA._cand("past_the_line", _row(st, contract="soybeans_cbot", driver_id="export_pace_lag"), what="x",
                 dates="", floor=("past_a_declared_line",))
    assert c["falsifier"].endswith("(the line called ahead sits at ten percent ahead of the same point of the "
                                   "prior year)")
    assert WA._line_value_words("z_bands", 1.5, low_side=True) == "minus one and a half sigma"
    assert WA._line_value_words("percentile_bands", 90.0) == "the ninetieth percentile"
    assert not any(ch.isdigit() for ch in c["falsifier"]), "SB-W is a letters-only class"
    assert not [e for e in L._check_nonobvious_watch() if "FALSIFIER" in e or "CLAUSES" in e]


# ── RT-7: A PUBLISHER'S TWO RELEASES ARE VINTAGES ─────────────────────────────────────────────────────────────
def test_RT7_a_vintage_row_names_the_release_it_is():
    assert REGY.publisher_words("silver_icco_cocoa") == "the ICCO"
    assert REGY.publisher_words("gold_weather_z") == ""                 # not a vintage card
    assert ROWS.release_words("the ICCO", "2026-05-29") == "the ICCO release of 29 May 2026"
    assert ROWS.release_words("", "2026-05-29") == "" and ROWS.release_words("the ICCO", "") == ""
    assert R.release_role_words("silver_icco_cocoa", "2026-05-29") == "the ICCO release of 29 May 2026"
    assert R.release_role_words("silver_psd", "2026-09-11") == ""        # declares no publisher: HEAD's identity


def test_RT7_the_menus_tier_word_is_charged_and_its_replacements_are_clean():
    from leviathan.graphrag import answer as _an
    served = ("The two readings of the same season's cushion differ by trust tier: the ICCO's published 2024/25 "
              "stocks-to-grindings is 29.2%, while the series read here gives 28.52%.")
    assert [h[0] for h in REG.desk_register_hits(served)] == ["trust tier"]
    for k in range(3):
        ph = REG.desk_phrase("trust tier", k)
        assert REG.desk_register_hits(ph) == [] and not _an._DESK_CLAIM_RX.search(ph), ph


# ── RT-8: THE COUNT LINE IS A PLAIN COUNT ────────────────────────────────────────────────────────────────────
def test_RT8_the_count_line_counts_the_rest_and_carries_no_pool_census():
    counts = {"distinct_sequences": 100, "total": 513, "state_two_hops": 271, "with_document": 0,
              "distinct_unnamed_markets": 3, "cross_market_event": 0, "cross_market_event_rendered": 0}
    line = R.sb_chain_count(counts, k=2, anchor_label="CME palm oil", slots=("top", "pair"))
    assert line.startswith("CHAIN COUNT into CME palm oil: one hundred chains of cause, two of them carried "
                           "above, one here for a reason other than rank; the rest are counted here, not followed "
                           + REG.desk_phrase("hop", 0) + " by " + REG.desk_phrase("hop", 0))
    for census in ("sequence", "ways in all", "past one link", "five hundred thirteen", "two hundred seventy-one"):
        assert census not in line, census
    assert R.classify(line) == ("SB-P",) and R.register_hits(line) == [] and REG.count_desk_register(line) == 0


def test_RT8_the_render_verb_row_is_DOCKETED_because_the_chain_mandate_teaches_it():
    """"renders in full" is NOT a register row this round: ``narration.MANDATE_CHAIN_MOVEMENT`` (lane A) teaches
    that phrase and ``narration.check_literals`` holds the literal at zero charges, so the row would red the
    build on a literal this lane does not own. When lane A's mandate speaks the count line's words, the row
    lands and this pin is re-banked."""
    from leviathan.graphrag.state import narration as N
    assert "renders in full" not in [n for n, _p, _r in REG.DESK_REGISTER_TOKENS]
    assert not [e for e in N.check_literals() if "desk-register" in e]
