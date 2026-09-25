"""THE 09-24 RE-SMOKE FIX ROUND, LANE R -- the row identity reaches the SENTENCE, one ledger addresses every
[E], the head answers what the question asked, and the words a producer prints never misread its own numbers.

Each pin names the CONTRACT item it holds (fix_round_0924/CONTRACT.md K1, K2, K3, K5, K8, K11, K12, K14, K15,
K21, K26; items 9, 28b, 30; OWNER DECISIONS O-5, O-7). Every pin is offline and $0: hand-built rows in the
shapes the producers emit, the shipped card registry and the shipped causal cards -- no read, no model call.
"""
from __future__ import annotations

import inspect
import types

import pytest

from leviathan.graphrag import verify as V
from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import lint as L
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import rows as ROWS
from leviathan.graphrag.state import seam as S
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.lagbands import parse_lag

ASOF = "2026-09-24"


def _st(**kw):
    base = dict(key=ROWS.SeriesKey(ref="psd_ending_stock_su_ratio", commodity="soybeans_cbot",
                                   country="United States"),
                status="ok", table="silver_psd", metric="su_ratio", cadence="annual", unit="ratio",
                narrate_unit="%", scale=100.0, level=0.1072, level_date="2026", knowledge_date="2026-09-11",
                asof=ASOF)
    base.update(kw)
    return ROWS.StateRow(**base)


def _row(st, contract="soybeans_cbot", driver_id="psd_ending_stock_su_ratio", sign="-"):
    return B.NodeRow(contract=contract, driver_id=driver_id, state=st, sign=sign,
                     lag_band=parse_lag("0-2 quarters"))


# ── the leaf's new vocabulary, appended at the TAIL (other lanes read it defensively) ──────────────────────
def test_K2_K3_K5_the_leaf_vocabularies_grow_only_at_their_tails():
    assert ROWS.STAT_KINDS[:5] == ("level", "sigma", "percentile", "window_peak_percentile", "current_level")
    assert "window_change" in ROWS.STAT_KINDS and "pair_level_spread" in ROWS.STAT_KINDS
    assert ROWS.SCALAR_KINDS[:12] == ("level", "sigma", "percentile", "window_peak_percentile",
                                      "current_level", "window_length", "run_length", "lag_band_quarters",
                                      "firings_count", "firings_aligned", "card_threshold", "outcome_move")
    for k in ("window_change", "pair_level_spread", "ask_row"):
        assert k in ROWS.SCALAR_KINDS
    assert ROWS.CELL_RULES == ("single_cell", "mean_of_cells", "one_of_cells", "sum", "")
    f = ROWS.RowIdentity.__dataclass_fields__
    # the fixer pass appends `class_words` (the family rule's words) AT THE TAIL -- every earlier field keeps
    # its position
    # 09-25 (RT-2): `cell_rank` / `cell_extreme` are appended AFTER class_words -- every earlier field keeps
    # its position, and the round-2 tail is read one step further from the end
    assert list(f)[-7:-2] == ["commodity_words", "cell_n", "stat_kind", "period_role", "class_words"]
    assert list(f)[-2:] == ["cell_rank", "cell_extreme"]
    assert "period_behind" in ROWS.StateRow.__dataclass_fields__
    assert ROWS.StateRow(key=ROWS.SeriesKey(ref="x")).period_behind == {}


# ── K2: THE FIGURE TOKEN ─────────────────────────────────────────────────────────────────────────────────────
def test_K2_the_figure_token_puts_basis_and_period_ON_the_figure_and_omits_what_is_empty():
    assert ROWS.figure_token("10.72 %", figure_basis="of domestic use", period_words="2026/27") == \
        "10.72 % of domestic use, 2026/27"
    assert ROWS.figure_token("0", unit="thousand MT", figure_basis="shipped in the week",
                             period_words="week to 3 September 2026",
                             period_role="the last week of the closed 2025/26 year") == \
        "0 thousand MT shipped in the week, week to 3 September 2026, the last week of the closed 2025/26 year"
    assert ROWS.figure_token("2.6 USD/bu") == "2.6 USD/bu"          # nothing declared -> HEAD's figure
    assert ROWS.figure_token("") == ""


def test_K2_R1_a_token_sentence_passes_the_verifier_and_the_extractor_reads_only_the_figure():
    """R-1 (measured on the 09-24 artefacts in BUILD_R): "<name> is <token> [Nk]." draws no charge, and the
    claim extractor reads the value plus only the period's own year tokens."""
    su = {"query": {"table": "silver_psd", "metric": "su_ratio", "commodity": "soybeans_cbot",
                    "country": "United States", "period": "2026"},
          "rows": [{"value": 10.72, "unit": "%", "knowledge_date": "2026-09-11"}], "status": "ok"}
    tok = ROWS.figure_token("10.72 %", figure_basis="of domestic use", period_words="2026/27")
    sent = "The stocks-to-use ratio for United States is %s [N1]." % tok
    st = {"tldr": sent, "mechanism": "", "sources": []}
    rep = V.verify_citations(st, [], [su])
    assert not rep.get("by_rule") and st["tldr"] == sent, rep
    assert V._claim_numbers_with_decimals(tok)[0] == [10.72]


def test_K2_the_SB1_value_slot_is_the_token_and_the_head_names_the_series_once():
    line, calls = R.sb_state(1, _row(_st()), asof=ASOF)
    head, rest = line.split(": ", 1)
    assert head.endswith("read here for psd ending stock su ratio"), head
    assert "2026/27" not in head, "the period rides the figure, not the head"
    assert rest.split("; ")[0].startswith("10.72 %") and "2026/27" in rest.split("; ")[0], rest
    assert calls[0]["rows"][0]["routing"] == "psd ending stock su ratio"          # K4 reads it


# ── K3: THE ROW IDENTITY ─────────────────────────────────────────────────────────────────────────────────────
def test_K3_the_cell_rule_is_the_served_rows_grain_never_the_axis_enum():
    surf = R.basin_surfaces()
    assert "West Africa" in surf and "EU Belt" in surf, surf
    f = ROWS.cell_rule_for
    assert f(axis="region_cell", collapse="mean", scope="United States") == ("mean_of_cells", 0)
    assert f(axis="destination", collapse="sum") == ("sum", 0)
    assert f(axis="region_cell", collapse="", scope="West Africa", basin_surfaces=surf) == ("mean_of_cells", 0)
    assert f(axis="region_cell", collapse="", scope="United States", basin_surfaces=surf,
             rows_at_period=10) == ("one_of_cells", 10)
    assert f(axis="region_cell", collapse="", scope="United States", basin_surfaces=surf) == ("", 0)
    assert f(axis="national", collapse="", scope="West Africa", basin_surfaces=surf) == ("", 0)


def test_K3_R2_cocoas_West_Africa_BASIN_MEAN_is_never_one_growing_cell():
    st = _st(key=ROWS.SeriesKey(ref="drought_z", commodity="cocoa", country="West Africa"),
             table="gold_weather_z", metric="drought_z", cadence="monthly", unit="z", narrate_unit="z",
             scale=1.0, level=0.00089, level_date="2026-07", collapse=None)
    ident = R.row_identity_for(_row(st, contract="cocoa", driver_id="drought", sign="+"))
    assert ident.cell_rule == "mean_of_cells", ident
    assert "one West Africa" not in ident.words() and "cell" in ident.words(), ident.words()


def test_K3_R3_commodity_words_name_the_series_commodity_only_where_it_is_not_the_boards():
    assert R.series_commodity_words("sunflower_oil", "soybean_oil_cbot") == "sunflower oil"
    assert R.series_commodity_words("corn_cbot", "corn") == ""          # one commodity, two slugs
    assert R.series_commodity_words("_global", "cocoa") == ""
    st = _st(key=ROWS.SeriesKey(ref="sunflower_oil_supply", commodity="sunflower_oil", country="Russia"),
             table="silver_psd", metric="production_mt", unit="MT", narrate_unit="MMT", scale=1e-6,
             level=7.81e6)
    ident = R.row_identity_for(_row(st, contract="soybean_oil_cbot", driver_id="russia_sunoil_supply",
                                    sign="-"))
    assert ident.commodity_words == "sunflower oil"
    # FIXER PASS (REVIEW_RA lexical 9): the series' commodity names what the series is OF, after the name --
    # one composition, so no test of the name's first word ("the ") decides where it goes
    assert ident.series_words().startswith("production of sunflower oil"), ident.series_words()
    assert ident.short_words().startswith("production of sunflower oil") and "Russia" in ident.short_words()
    herd = ROWS.RowIdentity(row_id="x", contract="corn_cbot", driver_id="cattle_herd", series_key="k",
                            table="silver_nass", metric="head", name="the head count of live animals",
                            commodity_words="cattle beef", scope="United States")
    assert herd.series_words().startswith("the head count of live animals of cattle beef"), herd.series_words()
    assert herd.short_words() == "the head count of live animals of cattle beef for United States"


def test_K3_one_of_cells_words_state_only_what_the_rows_prove():
    ident = ROWS.RowIdentity(row_id="x", contract="soybeans_cbot", driver_id="flash_drought", series_key="k",
                             table="gold_weather_z", metric="drought_z", name="the longest dry-day run",
                             axis="region_cell", scope="United States", cell_rule="one_of_cells",
                             cell_noun=("growing cell", "growing cells"), cell_n=10)
    assert ident.series_words() == "the longest dry-day run, for one of the ten United States growing cells"


def test_K23_the_store_period_words_ride_the_identity_and_the_token():
    w = ROWS.period_behind_words({"held": "2020/21", "newer_on": "USDA WASDE", "newer": "2023/24"},
                                 asof_words="1 March 2024")
    assert w == "the newest this series holds as known on 1 March 2024; USDA WASDE held 2023/24 by then"
    assert ROWS.period_behind_words({}) == ""
    st = _st(level_date="2020", asof="2024-03-01",
             period_behind={"held": "2020/21", "newer_on": "USDA WASDE", "newer": "2023/24"})
    line, _ = R.sb_state(1, _row(st), asof="2024-03-01")
    assert "the newest this series holds as known on 1 March 2024" in line, line
    assert "2026" not in line and "September" not in line          # C11: nothing later than the as-of


# ── K5 / K15: THE LIKE-STATE STANZA ──────────────────────────────────────────────────────────────────────────
def test_K5_an_analog_outcome_is_a_CHANGE_row_with_its_window_and_its_ends_known_date():
    o = {"label": "the longest dry-day run on ICE cocoa", "unit": "z", "table": "gold_weather_z",
         "metric": "drought_z", "commodity": "cocoa", "country": "West Africa", "band": parse_lag("1-3 quarters"),
         "t": "2025-10-31", "declined": None, "near_value": -0.2327, "far_value": 0.1528,
         "near_date": "2026-01", "far_date": "2026-07", "from_date": "2025-10",
         "near_known": "2026-02-25", "far_known": "2026-08-25"}
    line, calls = R.sb_analog_outcome(181, o, asof=ASOF)
    assert "moved -0.23 z" in line and "moved +0.15 z" in line, line
    for c, end, kd in zip(calls, ("2026-01", "2026-07"), ("2026-02-25", "2026-08-25")):
        assert c["rows"][0]["stat"] == "window_change"
        assert c["rows"][0]["window"] == {"from": "2025-10", "to": end}
        assert c["rows"][0]["knowledge_date"] == kd
    assert A.known_date_after("2026-07", 25) == "2026-08-25"
    assert A.known_date_after("2026", 25) == ""                   # a bare year carries no known date
    assert A.known_date_after("2026-09-04", 0) == "2026-09-04"


def test_K5_both_ends_on_ONE_print_decline_by_name_and_the_word_has_a_sentence():
    # the 09-24 max / tariff shape: an ANNUAL series (bare-year periods) read over the ENSO seed's one-to-two
    # quarter band from an October 2025 like state -- both ends land on the 2026 print.
    band = parse_lag("1-2 quarters")
    o = A.outcome_over_band(label="production for Argentina", values=[48.2, 50.9, 51.4],
                            dates=["2024", "2025", "2026"], t="2025-10-31", band=band, asof=ASOF)
    assert o["declined"] == "band_inside_one_print", o
    assert "band_inside_one_print" in A.OUTCOME_DECLINES
    assert R.absence_why("band_inside_one_print") != R.ABSENCE_FALLBACK
    assert not any("band_inside_one_print" in e for e in L._check_absence_vocabulary())


def test_K15_the_seeds_fold_on_the_series_key_and_the_header_word_is_the_pole_in_force():
    st = _st(key=ROWS.SeriesKey(ref="oni_climate", commodity="_global", country=""), table="silver_noaa_oni",
             metric="oni_anom", cadence="monthly", unit="degC", narrate_unit="degC", scale=1.0, level=1.8,
             level_date="2026-07")
    assert R.analog_header_name({"driver_id": "La_Nina"}, st) == "El Nino"
    cool = _st(key=st.key, table="silver_noaa_oni", metric="oni_anom", cadence="monthly", unit="degC",
               narrate_unit="degC", scale=1.0, level=0.2, level_date="2026-07")
    assert R.analog_header_name({"driver_id": "La_Nina"}, cool) not in ("El Nino", "La Nina")
    # THE FOLD, DRIVEN: two loud poles on ONE ONI series and one distinct series -> TWO seeds, the loudest
    # member's id kept; a board with no duplicate series seeds exactly its loud-numeric rows (B12 / R-10).
    oni = _st(key=st.key, table="silver_noaa_oni", metric="oni_anom", cadence="monthly", unit="degC",
              narrate_unit="degC", scale=1.0, level=1.8, level_date="2026-07",
              inputs={st.key.label(): {"values": [1.8], "dates": ["2026-07"]}})
    su = _st(inputs={_st().key.label(): {"values": [0.1], "dates": ["2026"]}})
    rows = [_row(oni, driver_id="El_Nino", sign="+"), _row(oni, driver_id="La_Nina", sign="-"), _row(su)]
    for r in rows:
        r.legs["loud"] = True
    bd = types.SimpleNamespace(rows=rows, order=[r.key for r in rows],
                               knobs=types.SimpleNamespace(analog_dims=3))
    got = A.seed_rows(bd, bd.knobs)
    assert [r.driver_id for r in got] == ["El_Nino", "psd_ending_stock_su_ratio"], [r.driver_id for r in got]
    bd.rows, bd.order = [rows[0], rows[2]], [rows[0].key, rows[2].key]
    assert [r.driver_id for r in A.seed_rows(bd, bd.knobs)] == ["El_Nino", "psd_ending_stock_su_ratio"]
    # ONE PUBLISHED RULE, TWO READERS: the selection and the seam's declared-dimension lookup.
    assert "seed_rows(bd, knobs)" in inspect.getsource(A.analog_rows)
    assert "seed_rows" in inspect.getsource(S._analog_dims)
    bd.rows, bd.order = rows, [r.key for r in rows]
    assert S._analog_dims(bd) == frozenset({"El_Nino", "psd_ending_stock_su_ratio"})


def test_K15_O7_a_pick_that_agrees_on_NO_dimension_is_withheld_with_its_absence_line():
    a = {"contract": "cocoa", "driver_id": "El_Nino", "date": "2025-10-31", "dims_declared": 3,
         "per_dim": ({"id": "El_Nino", "sign_agree": False}, {"id": "drought", "sign_agree": False},
                     {"id": "heat_stress", "sign_agree": False})}
    assert R.analog_agree_n(a) == 0
    line = R.sb_analog_nearest(a, name="El Nino", agree_n=0)
    assert line.startswith("LIKE STATE El Nino on ICE cocoa: the nearest reading the record holds is "
                           "October 2025"), line
    assert "sat like this" not in line and "zero of the three dimensions" in line
    assert R.classify(line) == ("SB-A",) and R.register_hits(line) == []
    assert R.analog_agree_n({"driver_id": "x"}) is None           # a hand-built row keeps HEAD's stanza


# ── K11: THE RECORD LINE NAMES ITS READING ───────────────────────────────────────────────────────────────────
def _hop(**kw):
    base = dict(contract="soybeans_cbot", driver_id="crude_oil", sign="+", lag="0-2 quarters",
                lag_band=parse_lag("0-2 quarters"), confidence="high", measured=True,
                series_key="brent_crude_z|_global|", percentile=88.0, z=1.9, run_direction="up",
                run_since="2026-04-30", knowledge_date="2026-09-04", tail=0.76, move=1.0)
    base.update(kw)
    return W.ChainHop(**base)


def _chain(hops, **kw):
    return W.Chain(contract=kw.pop("contract", "soybeans_cbot"), hops=tuple(hops), depth=len(hops) - 1,
                   terminal=kw.pop("terminal", "soybeans_cbot"),
                   agreements=kw.pop("agreements", tuple(["aligned"] * len(hops))),
                   edge_signs=kw.pop("edge_signs", tuple(["+"] * len(hops))), **kw)


def test_K11_R6_the_record_line_names_the_RECEIPT_hop_and_the_link_below_it():
    crude = _hop()
    crush = _hop(driver_id="soybean_crush_margin", series_key="cbot_board_crush_margin|_global|")
    ch = _chain([crude, crush], terminal="soybean_oil_dce")
    ch.receipt_index = 0
    ch.history = {"n_firings": 8, "aligned": 5, "at_odds": 3, "undetermined": 0, "unmeasured": 8}
    reading, nxt = R.chain_record_reading_names(ch)
    assert reading == R.chain_hop_name(crude) and nxt == R.chain_hop_name(crush)
    line = R.sb_chain_record(ch)
    assert ("of the past times %s sat this far out, eight had a reading of %s to measure"
            % (reading, nxt)) in line, line
    assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
    ch.receipt_index = 1                                  # the last hop: the next link is the terminal
    assert R.chain_record_reading_names(ch) == (R.chain_hop_name(crush), R.board_label("soybean_oil_dce"))
    assert "this reading sat" in R.chain_record_words({"n_firings": 8, "aligned": 5, "at_odds": 3,
                                                       "unmeasured": 0})     # no names -> HEAD's words


# ── K12: THE HOP NAME CARRIES ITS MARKET ─────────────────────────────────────────────────────────────────────
def test_K12_R7_an_off_question_hop_names_its_board_and_a_page_market_hop_is_unchanged():
    coffee = _hop(contract="brazilian_arabica_coffee", driver_id="biennial_on_year",
                  series_key="production|brazilian_arabica_coffee|Brazil")
    soy = _hop()
    # FIXER PASS (REVIEW_RA M3 / lexical 9): the hop's own market is named the way the SB-1 head names it
    # (", on <board>"), never prefixed into the noun phrase
    assert R.chain_hop_name(coffee, page_markets=("cocoa",)).endswith(", on BMF arabica coffee"), \
        R.chain_hop_name(coffee, page_markets=("cocoa",))
    assert R.chain_hop_name(soy, page_markets=("soybeans_cbot",)) == R.chain_hop_name(soy)
    assert R.chain_hop_name(coffee) == R.chain_hop_name(coffee, page_markets=())   # no markets -> HEAD
    ch = _chain([coffee], contract="brazilian_arabica_coffee", terminal="robusta_coffee")
    head = R.sb_chain_head(ch, i=1, n=2, page_markets=("cocoa",))
    assert "on BMF arabica coffee, from production, for Brazil to ICE robusta coffee" in head, head
    names = R.chain_hop_reader_names(coffee, page_markets=("cocoa",))
    assert R.chain_hop_name(coffee) in names and R.chain_hop_name(coffee, page_markets=("cocoa",)) in names


def test_O5_the_subject_seat_label_follows_the_tier_the_pick_came_from():
    sem = {"hints": {"exact": [], "alias": []}, "picked": ["brazil_soybean_supply"],
           "groups": {"brazil_soybean_supply": ["brazil_soybean_supply", "safrinha"]}}
    named = {"hints": {"exact": ["import_tariff"], "alias": ["China_import_tariff"]},
             "picked": ["China_import_tariff"], "groups": {"China_import_tariff": ["China_import_tariff"]}}
    assert R.subject_named_tier(sem) is False and R.subject_named_tier(named) is True
    assert R.subject_named_tier({}) is True
    ch = types.SimpleNamespace(slot="subject")
    assert R.chain_slot_words(ch, subject_named=False) == "the driver this question was resolved to"
    assert R.chain_slot_words(ch) == "the chain this question names"


# ── K1: EVERY BLOCK [E] IS THE LEDGER'S ──────────────────────────────────────────────────────────────────────
def test_K1_every_chain_document_kind_is_addressed_by_the_ledger_and_an_unaddressed_record_says_so():
    book = {"sk-regime": 46, "sk-menu": 7}
    addr = lambda rec: book.get(str((rec or {}).get("source_key") or ""))       # noqa: E731
    blk = R.Block(start=1)
    for kind in ("open", "closed", "mechanism", "none"):
        rp = {"kind": kind, "prop": {"source_key": "sk-regime", "text": "t"}}
        assert R.chain_document_cite(rp, None, None, evidence_address=addr, block=blk) == " [E46]"
    rp = {"kind": "closed", "prop": {"text": "an object receipt with no durable identity"}}
    assert R.chain_document_cite(rp, None, None, evidence_address=addr, block=blk) == ""
    assert blk.counters.get("receipt_unaddressed") == 1
    # the harness (no ledger) keeps HEAD's two rules byte for byte
    assert R.chain_document_cite({"kind": "closed", "prop": {"source_key": "sk-menu"}}, None,
                                 {"sk-menu": 7}) == ""
    assert R.chain_document_cite({"kind": "none", "prop": {"source_key": "sk-menu"}}, None,
                                 {"sk-menu": 7}) == " [E7]"


def test_K1_an_unaddressed_receipt_and_event_still_render_in_their_own_classes():
    r = {"source": "a wire", "date": "2025-03-19", "text": "the tariff took effect"}
    line = R.sb_receipt(None, 2, r, driver_id="China_import_tariff")
    assert line.startswith("- [T2] (a wire, reported 2025-03-19)") and R.classify(line) == ("SB-R",)
    assert R.classify(R.sb_receipt(46, 2, r, driver_id="China_import_tariff")) == ("SB-R",)
    row = B.NodeRow(contract="soybeans_cbot", driver_id="China_import_tariff", state=None, sign="-",
                    lag_band=parse_lag("0-2 quarters"), event_date="2025-03-10")
    ev = R.sb_event(row, receipt_handle=None, published="2025-03-19", board="CBOT soybeans",
                    window={"opens": None, "declined": "lag_unparsed"}, asof=ASOF)
    assert "by a document this page carries no address for" in ev and R.classify(ev) == ("SB-D",)
    sig = inspect.signature(R.render_board)
    for k in ("evidence_address", "ask_rows", "page_markets"):
        assert k in sig.parameters and sig.parameters[k].default is None
    ssig = inspect.signature(S.fill_stage2)
    for k in ("evidence_address", "ask_rows", "extra_kd", "page_markets"):
        assert k in ssig.parameters and ssig.parameters[k].default is None


# ── K6 (R words): A DATE WITH NO PRECISION IS NEVER PRINTED AS A DAY ───────────────────────────────────────
def test_K6_I4_an_event_with_no_precision_prints_the_documents_date_only():
    w = R._event_words("report_in_reach", event_date="2025-02-01", precision="", published="2025-03-19")
    assert w == "a dated report, published 19 March 2025" and "February" not in w
    w = R._event_words("regime_in_force", event_date="2025-03-01", precision="month",
                       published="2025-03-19")
    assert "is March 2025, reported 19 March 2025;" in w, w
    w = R._event_words("regime_in_force", event_date="2025-02-01", precision="", published="2025-03-19")
    assert "1 February 2025" not in w and "reported 19 March 2025" in w, w


# ── K8 / K21: THE HEAD ───────────────────────────────────────────────────────────────────────────────────────
def _seat(metric, value, unit, **row):
    return {"query": {"table": "compute_stat", "metric": metric, **row.pop("_q", {})},
            "rows": [{"value": value, "unit": unit, **row}], "status": "ok",
            "stat_provenance": row.pop("_prov", {"stat": metric})}


def test_K8_R4_the_ask_head_prints_the_pair_first_cites_the_seats_handle_and_counts_the_rest():
    blk = R.Block(start=100)
    pair = _seat("pair_spread", -357.0, "USD/mt", leg_a="a", leg_b="b",
                 _q={"commodity": "world crude palm oil minus world rapeseed oil", "period": "2026-08-01"})
    pair["stat_provenance"] = {"stat": "pair_level_spread", "input_legs": ["a", "b"]}
    assert R.ask_row_is_pair(pair)
    line = R.sb_ask_row(14, pair, block=blk)
    assert line.startswith("ASKED ROW [N14] ") and ": -357" in line and R.classify(line) == ("SB-ASK",), line
    ch = _seat("window_change", 10289.0, "MT", window={"from": "2026-01-01", "to": "2026-08-01"})
    line = R.sb_ask_row(11, ch, block=blk)
    assert "+10289" in line and "January 2026" in line and "August 2026" in line, line
    blk.add("ASKED ROW [N11] x: +1", ())
    kinds = {(s["kind"], s["handle"]) for s in blk.served_scalars()}
    assert ("ask_row", 11) in kinds or ("ask_row", 14) in kinds
    assert R.render_caps("quick")["ask_rows"] == 3 and R.render_caps("max")["ask_rows"] == 5
    # the contract's handle arrives as 14 or as lane A's printed spelling "N14"
    assert R._handle_int("N14") == 14 and R._handle_int(14) == 14 and R._handle_int("[N7]") == 7
    assert R._handle_int(None) == 0 and R._handle_int("x") == 0


def test_K8_R5_the_tape_spread_is_the_calculators_and_a_unit_mismatch_is_refused_verbatim():
    def _tape(slug, unit, cur, vals, cm="2026-12"):
        dates = ["2026-09-18", "2026-09-21", "2026-09-22"]
        return ROWS.TapeState(slug=slug, status="ok", unit=unit, currency=cur, contract_month=cm,
                              level=vals[-1], level_date=dates[-1],
                              inputs={"%s|%s" % (slug, cm): {"values": vals, "dates": dates, "unit": unit}})
    anchors = (B.Anchor(contract="corn_cbot", source="named"),
               B.Anchor(contract="soft_red_winter_wheat_cbot", source="named"))
    bd = types.SimpleNamespace(anchors=anchors, asof=ASOF,
                               tape={"corn_cbot": _tape("corn_cbot", "US cents/bushel", None,
                                                        [530.0, 533.0, 536.75]),
                                     "soft_red_winter_wheat_cbot": _tape("soft_red_winter_wheat_cbot",
                                                                         "US cents/bushel", None,
                                                                         [710.0, 715.0, 717.25])})
    sp = R.tape_pair_spread(bd)
    assert not sp.get("declined") and abs(sp["value"] - (536.75 - 717.25)) < 1e-9, sp
    line, calls = R.sb_tape_spread(200, sp, bd)
    assert line.startswith("ASKED SPREAD [N200] CBOT corn December 2026 minus CBOT srw wheat") and \
        "-180.5 US cents/bushel" in line, line
    assert calls[0]["rows"][0]["stat"] == "pair_level_spread"
    assert calls[0]["rows"][0]["legs"] == ["corn_cbot", "soft_red_winter_wheat_cbot"]
    bd.tape["soft_red_winter_wheat_cbot"] = _tape("soft_red_winter_wheat_cbot", "USD/metric ton", None,
                                                  [210.0, 211.0, 212.0])
    sp = R.tape_pair_spread(bd)
    assert sp.get("declined"), sp
    line, calls = R.sb_tape_spread(200, sp, bd)
    assert "the spread calculator refused it" in line and calls == []
    bd.anchors = anchors[:1]
    assert R.tape_pair_spread(bd) is None                  # one named market sets no pair


def test_K21_the_horizon_row_is_the_answering_chains_outcome_or_its_decline():
    ch = _chain([_hop()], terminal="soybeans_cbot")
    ch.rendered, ch.slot, ch.slot_fits = True, "top", ("horizon",)
    ch.outcome = {"n": 2, "n_in": 8, "median_move": None, "unit": "percent"}
    bd = types.SimpleNamespace(horizon_months=3, asof=ASOF, chains=[ch],
                               chain_counts={"slot_state": {"horizon": "answered_by_rank"}})
    assert R.horizon_chain(bd) is ch
    line, calls, hh = R.sb_ask_horizon(300, ch, bd)
    assert line.startswith("ASKED HORIZON three months: the chain from ") and "too thin" in line
    assert calls == [] and hh == () and R.classify(line) == ("SB-ASK",)
    ch.outcome = {"n": 6, "n_in": 8, "median_move": 2.1, "low": -3.0, "high": 5.5, "unit": "percent",
                  "window_from": "2025-06-16", "window_to": "2026-09-04"}
    line, calls, hh = R.sb_ask_horizon(300, ch, bd)
    assert hh == (300, 301, 302) and len(calls) == 3 and "history, not a forecast" in line, line
    oline, ocalls = R.sb_chain_outcome(400, ch, asof=ASOF, cite=hh)
    assert ocalls == [] and "[N300]" in oline and "[N400]" not in oline
    bd.chain_counts = {"slot_state": {"horizon": "not_asked"}}
    assert R.horizon_chain(bd) is None


# ── item 30: THE TAPE REGISTERS ITS SERVED SCALARS ───────────────────────────────────────────────────────────
def test_item30_R12_the_tariff_tape_sentence_is_backed_and_a_wrong_unit_is_still_charged():
    tape = ROWS.TapeState(slug="soybeans_cbot", status="ok", unit="US cents/bushel", contract_month="2026-11",
                          level=1325.5, level_date="2026-09-22",
                          changes=[{"window": "21 sessions", "n_periods": 21, "delta": 86.0, "declined": None},
                                   {"window": "63 sessions", "n_periods": 63, "delta": 176.25,
                                    "declined": None}],
                          percentile={"value": 99.0}, coverage={"n_obs": 325},
                          window_note="325 sessions on 2026-11, 2025-06-10 to 2026-09-22")
    blk = R.Block(start=212)
    line, calls = R.sb_tape(212, tape, asof=ASOF, block=blk)
    blk.add(line, calls)
    pool = blk.served_scalars()
    assert {(s["kind"], s["value"]) for s in pool} >= {("level", 1325.5), ("window_change", 86.0),
                                                        ("window_change", 176.25), ("percentile", 99.0),
                                                        ("window_length", 325.0)}
    assert all(c.get("_row_id") == R.tape_row_id(tape) for c in calls)
    number_calls = [{"query": {"table": "x", "metric": "y"}, "rows": [{"value": 0.0}], "status": "ok"}] * 211
    number_calls = number_calls + calls
    sent = ("at the 99th percentile of the 325 sessions this read covers [N215], 1325.5 US cents/bushel [N212], "
            "up 86 over twenty-one sessions [N213].")
    st = {"tldr": sent, "mechanism": "", "sources": []}
    rep = V.verify_citations(st, [], number_calls, served_scalars=pool)
    assert "number_unbacked" not in (rep.get("by_rule") or {}), rep.get("by_rule")
    bad = {"tldr": "the level sits at 325 % of its range [N215].", "mechanism": "", "sources": []}
    rep = V.verify_citations(bad, [], number_calls, served_scalars=pool)
    assert rep.get("by_rule"), "a session count never backs a percent"


# ── K14: A FALSIFIER IS A READING THAT TURNS ─────────────────────────────────────────────────────────────────
def test_K14_R8_every_falsifier_names_a_series_the_row_prints_and_none_is_about_the_model():
    for k, f in WA.NONOBVIOUS_FALSIFIERS.items():
        assert "{series}" in f, k
        assert "counted twice" not in f and "cluster in one episode" not in f, k
    assert not [e for e in L._check_nonobvious_watch() if "FALSIFIERS" in e]
    row = _row(_st())
    c = WA._cand("upstream_convergence", row, what="x", dates="", floor=("two_upstream_paths",))
    assert R.row_identity_for(row).short_words() in c["falsifier"], c["falsifier"]
    assert "{series}" not in c["what"]


# ── K26: THE SAME READING IS ONE SERIES ─────────────────────────────────────────────────────────────────────
def test_K26_the_spillover_counts_same_series_far_rows_only_and_the_rest_by_name():
    far = [{"contract": "barley", "sign": "-", "same_series": False, "lag_band": parse_lag("0-2 quarters"),
            "confidence": "high"},
           {"contract": "canola_ice", "sign": "-", "same_series": False, "lag_band": parse_lag("0-2 quarters"),
            "confidence": "high"}]
    bd = types.SimpleNamespace(fan=[{"contract": "french_rapeseed_matif", "driver_id": "ending_stocks_su_ratio",
                                     "far": far}])
    row = types.SimpleNamespace(contract="french_rapeseed_matif", driver_id="ending_stocks_su_ratio", sign="-")
    fa = WA._fan_facts(bd, row)
    assert fa["n"] == 0 and fa["other_series"] == 2, fa
    for f in far:
        f.pop("same_series")
    assert WA._fan_facts(bd, row)["n"] == 2                  # an unstamped fan keeps HEAD's count


def test_K26_on_a_declared_phase_pair_both_sides_are_the_pole_in_force():
    oni = _st(key=ROWS.SeriesKey(ref="oni_climate", commodity="_global", country=""), table="silver_noaa_oni",
              metric="oni_anom", cadence="monthly", unit="degC", narrate_unit="degC", scale=1.0, level=1.8,
              level_date="2026-07")
    la = _row(oni, driver_id="La_Nina", sign="+")
    el = _row(oni, driver_id="El_Nino", sign="-")
    far_el = [{"contract": "corn_cbot", "sign": "-"}, {"contract": "malaysian_crude_palm_oil_cme", "sign": "+"}]
    far_la = [{"contract": "corn_cbot", "sign": "+"}, {"contract": "malaysian_crude_palm_oil_cme", "sign": "-"}]
    bd = types.SimpleNamespace(fan=[{"contract": "soybeans_cbot", "driver_id": "El_Nino", "far": far_el},
                                    {"contract": "soybeans_cbot", "driver_id": "La_Nina", "far": far_la}],
                               row=lambda c, d: {"El_Nino": el, "La_Nina": la}.get(d))
    fa = WA._fan_facts(bd, la)
    assert fa["driver_read"] == "El_Nino" and fa["same"] == 1 and fa["opposite"] == 1, fa


# ── item 9: THE LINE IS ON THE SIDE THE READING SITS, MEASURED ON THE FIGURE THE ROW CITES ─────────────────
def test_item9_a_negative_reading_takes_the_cards_low_label_and_the_row_cites_its_sigma():
    st = _st(key=ROWS.SeriesKey(ref="urea_z", commodity="_global", country=""), table="silver_pink_sheet",
             metric="urea_usd_t_zscore_5yr", cadence="monthly", unit="z", narrate_unit="z", scale=1.0,
             level=-0.53, level_date="2026-08", z={"value": -0.78},
             convention={"kind": "z_bands", "reading": -0.78, "matched": False})
    row = _row(st, contract="corn_cbot", driver_id="fertilizer_cost", sign="-")
    conv = {"urea_z": {"kind": "z_bands", "bands": [1.5], "labels": ["elevated"], "labels_low": ["depressed"]}}
    cd = WA.convention_distance(row, conventions=conv)
    assert cd["label"] == "depressed" and cd["low_side"] and cd["band_words"].startswith("-1.5"), cd
    assert cd["stat_key"] == "sigma" and "sigma" in cd["stat_words"]
    conv["urea_z"].pop("labels_low")
    assert WA.convention_distance(row, conventions=conv)["label"] == "elevated"   # two-sided words stand


# ── item 28b: A CHAIN TOLD AS A CHAIN ───────────────────────────────────────────────────────────────────────
def test_item28b_two_ADJACENT_links_in_the_chains_own_order_make_a_told_chain():
    crude = _hop()
    crush = _hop(driver_id="soybean_crush_margin", series_key="cbot_board_crush_margin|_global|")
    ch = _chain([crude, crush], terminal="soybeans_cbot")
    n0, n1 = R.chain_hop_name(crude), R.chain_hop_name(crush)
    assert R.chain_referenced_adjacent_in(ch, ["Firm %s pushes %s higher." % (n0, n1)])
    assert not R.chain_referenced_adjacent_in(ch, ["%s held while %s rose." % (n1, n0)])
    assert "chain_referenced_adjacent" in inspect.getsource(R._chain_coverage)


# ── K15 / seam: THE ANALOG ROWS RIDE THE TRACE ───────────────────────────────────────────────────────────────
def test_K15_the_TRADED_CONTRACTS_tape_leads_the_monthly_benchmark_in_the_calls_units():
    """K15: "where the page market's own tape is an admitted price dimension its outcome row leads (the call's
    own units)". The monthly benchmark is this market's price too (call_units), but not the contract the call
    is on -- the BOCO max re-render printed the benchmark first until the producer marked its tape row."""
    dates = ["2026-0%d-15" % m for m in range(1, 10)]
    tape = ROWS.TapeState(slug="soybeans_cbot", status="ok", level=1040.0, level_date=dates[-1],
                          contract_month="2026-11", unit="USc/bu")
    tape.inputs = {"soybeans_cbot|2026-11": {"values": [1000.0 + i for i in range(9)], "dates": dates}}
    bd = types.SimpleNamespace(tape={"soybeans_cbot": tape}, asof=ASOF, rows=[], row=lambda c, d: None,
                               ledger=types.SimpleNamespace(benchmark_reads=0), fan=[], series={})
    seed = _row(_st(), driver_id="El_Nino")
    seed.lag_band = parse_lag("0-1 quarters")
    bm = {"values": [300.0 + i for i in range(9)], "dates": dates, "unit": "USD/t",
          "label": "the soybean monthly benchmark", "table": "silver_pink_sheet", "metric": "soybeans_usd_t"}
    outs = A._outcomes_for(bd, seed, "2026-01-15", benchmark_fn=lambda c: bm)
    tp = [o for o in outs if o.get("tape")]
    assert tp and tp[0]["call_units"] and not tp[0].get("declined"), outs[:1]
    bench = [o for o in outs if "benchmark" in str(o.get("label") or "")]
    assert bench and bench[0]["call_units"] and not bench[0].get("tape")
    # THE RENDER'S ORDER READS THAT FLAG right after the call's units, before any label tie-break.
    src = inspect.getsource(R.render_board)
    i_cu, i_tp = src.index('0 if o.get("call_units") else 1'), src.index('0 if o.get("tape") else 1')
    assert i_cu < i_tp < src.index('0 if "benchmark" in str(o.get("label") or "") else 1')


def test_K15_the_analog_rows_ride_the_board_and_the_seam_puts_them_on_the_trace():
    bd = types.SimpleNamespace(analogs=[], legs={})
    bd.stamp = lambda leg, outcome, **kw: {"outcome": outcome}
    rows = [{"contract": "cocoa", "driver_id": "El_Nino", "date": "2025-10-31", "dims_seen": 3,
             "dims_declared": 3, "declined": None, "series_key": "oni_climate|_global|",
             "per_dim": ({"id": "El_Nino", "sign_agree": False},), "outcomes": ()}]
    A.analog_leg(bd, rows)
    assert bd.analogs and bd.analogs[0]["agree_n"] == 0 and bd.analogs[0]["series_key"] == "oni_climate|_global|"
    assert 'tr["analogs"]' in inspect.getsource(S.fill_stage2)
