"""THE 09-26 FIX SITTING (post-arm-A), LANE R -- render / rows / lint / the row-word books.

R-1 (D3)  a chain link is named by its own [N] / [E] address or a WHOLE reader name unique to it on the BOARD; the
          single identity words are no longer a naming route (cotton's "Indian monsoon" read as the Indian Ocean
          dipole and withheld the backstop). The coverage reads each chain's OWN hop addresses (the rank join).
R-2       the chain positioning row's case words are owner ruling 1 (S-1), and an SB-1 positioning row at its own
          record's end carries its causal card's mechanism, whole, behind the declared lead (P9).
R-3 (D15) every standing a rendered chain hop prints has an address: the hop's row is printed as a cited row.
R-4       the backstop sentence keeps the hop the prose cites (P11); the subject slot answered by its own row (P13).
R-5       every row word this sitting adds is declared once in state_conventions.yaml and graded by lint clause 18.
P5 / P6 / P8 / P14  the producer halves other lanes read: the fan counts and the run's words on the served-scalars
          pool, the ledger regime words, the window-anchor words, the global-scope clause and its row field.

Every pin is offline and $0: hand-built walk objects in the shapes the producers emit, the shipped cards and
conventions, the arm-A served sentences quoted verbatim, and the harness fixture board through the serving seam.
"""
from __future__ import annotations

import dataclasses
import inspect
import types

import pytest

from leviathan.graphrag import graph as G
from leviathan.graphrag import register as REG
from leviathan.graphrag import verify as VF
from leviathan.graphrag.state import __main__ as M
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import lint as L
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import rows as ROWS
from leviathan.graphrag.state import seam as S
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.lagbands import parse_lag

ASOF = "2026-09-26"


def _hop(contract, driver_id, series_key="", **kw):
    return W.ChainHop(contract=contract, driver_id=driver_id, measured=bool(series_key), series_key=series_key, **kw)


def _chain(contract, hops, terminal, agreements=None, signs=None):
    ch = W.Chain(contract=contract, hops=tuple(hops), terminal=terminal,
                 agreements=tuple(agreements or ("undetermined",) * len(hops)),
                 edge_signs=tuple(signs or ("+",) * len(hops)))
    ch.rendered = ch.full = True
    return ch


def _cotton_chains():
    """The 09-26 cotton board's two rendered chains, as the trace carries them (state_board.chains)."""
    c0 = _chain("cotton", [_hop("cotton", "El_Nino", "oni_climate|_global|", percentile=92.7),
                           _hop("cotton", "IOD_positive", "iod_climate|_global|", percentile=37.4),
                           _hop("cotton", "drought"), _hop("cotton", "ending_stocks_su_ratio"),
                           _hop("cotton", "speculative_positioning", "cot_mm_positioning|cotton|", percentile=96.6)],
                "rough_rice_cbot", signs=("-", "+", "-", "-", "0"))
    c1 = _chain("corn_cbot", [_hop("corn_cbot", "China_state_reserves", "beginning_stock_region|corn_cbot|China"),
                              _hop("corn_cbot", "china_import_demand", "import|corn_cbot|China"),
                              _hop("corn_cbot", "export_pace", "esr_exports|corn_cbot|"),
                              _hop("corn_cbot", "ending_stocks_su_ratio",
                                   "psd_ending_stock_su_ratio|corn_cbot|United States")], "cotton")
    return c0, c1


# THE SERVED COTTON SENTENCE (arm_a_0926 treatment cotton:14), verbatim, ASCII-folded as the producers fold it
COTTON_14 = ("A USDA attache report of 3 April 2026 frames the other tail: if warm-phase conditions emerge during 2026 "
             "they could weaken the Indian monsoon and raise drought and heat risk [E36] -- an expectation as of "
             "that report, not a realised outcome.")


# ── R-1 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_R1_the_cotton_D3_sentence_no_longer_tells_the_dipole_to_drought_link():
    c0, c1 = _cotton_chains()
    sents = VF.sentences(COTTON_14)
    # the receipt [E36] sits on the chain's event hop (El Nino, hop 0); the dipole is named by no address or name
    hr = [(36,), (), (), (), ()]
    assert not R.chain_referenced_adjacent_in(c0, sents, hop_handles=[(18, 20), (), (), (), (48, 50, 51)],
                                              page_markets=("cotton",), hop_receipts=hr, peer_chains=(c0, c1))
    # the dipole's WHOLE name in order before drought IS a told link -- identity by the whole name
    told = VF.sentences("The Indian Ocean dipole index is expected to raise drought, and the readings do not settle it.")
    assert R.chain_referenced_adjacent_in(c0, told, page_markets=("cotton",), peer_chains=(c0, c1))


def test_R1_a_name_sharing_a_token_with_ANOTHER_reading_on_the_BOARD_names_neither():
    c0, c1 = _cotton_chains()
    names0 = R.chain_link_names(c0, peer_chains=(c0, c1))
    names1 = R.chain_link_names(c1, peer_chains=(c0, c1))
    # the cotton chain's unmeasured S/U node and the corn chain's measured S/U series share "stocks": neither names
    assert names0[3] == () and not any("stocks-to-use" in n for n in names1[3])
    # "drought" names the drought node; the dipole's names are all whole names of the dipole
    assert "drought" in names0[2] and all("dipole" in n.lower() or "iod" in n.lower() for n in names0[1])
    # UNIQUENESS IS OVER THE BOARD, never the chain: two different stocks-to-use SERIES on two chains name neither
    # on the board, and each names its own link on a board of one; ONE series on two boards is ONE reading
    us = _hop("soybeans_cbot", "psd_ending_stock_su_ratio", "psd_ending_stock_su_ratio|soybeans_cbot|United States")
    eu = _hop("french_rapeseed_matif", "ending_stocks_su_ratio",
              "psd_ending_stock_su_ratio|french_rapeseed_matif|European Union")
    x = _chain("soybeans_cbot", [_hop("soybeans_cbot", "crude_oil", "brent_crude_z|_global|"), us], "soybeans_cbot")
    y = _chain("french_rapeseed_matif", [_hop("french_rapeseed_matif", "crude_oil", "brent_crude_z|_global|"), eu],
               "malaysian_crude_palm_oil_cme")
    assert any("stocks-to-use ratio" in n for n in R.chain_link_names(x)[1])
    assert not any("stocks-to-use" in n for n in R.chain_link_names(x, peer_chains=(x, y))[1])
    assert any("Brent crude" in n for n in R.chain_link_names(x, peer_chains=(x, y))[0]), "one series, one reading"
    # the single identity words stay a function for their other readers, and are no naming route
    assert "indian" in R.chain_hop_identity_words(c0)[1]
    for fn in (R.chain_referenced_in, R.chain_referenced_adjacent_in, R._link_positions, R.chain_link_names):
        assert "chain_hop_identity_words" not in fn.__code__.co_names, fn.__name__


def test_R1_a_link_is_named_by_its_own_E_address_and_by_its_own_N_address():
    c0, c1 = _cotton_chains()
    s = VF.sentences("The warm Pacific reading [N18] and the report behind the drought link [E7] both lean one way.")
    # [N18] names hop 0 and "drought" names hop 2 -> two links in one sentence
    assert R.chain_referenced_in(c0, s, hop_handles=[(18,), (), (), (), ()], peer_chains=(c0, c1))
    # an [E] address the block printed on hop 1's document row names hop 1: [N18] -> [E7] in order is adjacent
    s2 = VF.sentences("The warm Pacific reading [N18] feeds the dipole, per the report [E7].")
    assert R.chain_referenced_adjacent_in(c0, s2, hop_handles=[(18,), (), (), (), ()],
                                          hop_receipts=[(), (7,), (), (), ()], peer_chains=(c0, c1))
    assert not R.chain_referenced_adjacent_in(c0, s2, hop_handles=[(18,), (), (), (), ()], peer_chains=(c0, c1))


def test_R1_a_link_told_across_the_blocks_own_semicolon_is_one_sentence():
    """The block prints every link as "<hop>: <reading>; the model expects it to move <next> ..." -- the writer's
    copy of that shape (deep 09-26:12) splits at the estate splitter's semicolon, and is ONE sentence."""
    hops = [_hop("soybeans_cbot", "crude_oil", "brent_crude_z|_global|"),
            _hop("soybeans_cbot", "soybean_crush_margin", "cbot_board_crush_margin|_global|"),
            _hop("soybeans_cbot", "psd_ending_stock_su_ratio", "psd_ending_stock_su_ratio|soybeans_cbot|United States")]
    ch = _chain("soybeans_cbot", hops, "soybeans_no_1_dce")
    served = ("**The crush demand-pull leg.** the Brent crude price against its own five-year record against its "
              "own five-year record reads 0.51 z, August 2026 [N119]; the model expects it to lift the board crush "
              "margin -- the board crush margin reads 2.43 USD/bu, 23 September 2026 [N115], and the readings agree.")
    sents = VF.sentences(served)
    assert any(s.rstrip().endswith(";") for s in sents), "the estate splitter cuts at the semicolon"
    assert R.chain_referenced_adjacent_in(ch, sents, hop_handles=[(119,), (115,), ()], peer_chains=(ch,))
    assert R._chain_sentences(["a;", "b;", "c.", "d."]) == ["a; b; c.", "d."]
    assert R._chain_sentences(["a.", "b"]) == ["a.", "b"]


def test_R1_the_coverage_reads_each_chains_OWN_hop_addresses_at_its_rank():
    """HEAD handed every chain the PREVIOUS chain's hop addresses (the render stamps rank 1-based, the loop
    counted from 0) -- the first chain had none."""
    c0, c1 = _cotton_chains()
    c0.score, c1.score = 90.0, 80.0
    rows = [{"role": "chain", "rank": 1, "line": "CHAIN one", "handles": ()},
            {"role": "chain_hop", "rank": 1, "hop_handles": (18, 20), "line": "h"},
            {"role": "chain_hop", "rank": 1, "hop_handles": (), "line": "h"},
            {"role": "chain_hop", "rank": 1, "hop_handles": (), "line": "h"},
            {"role": "chain_hop", "rank": 1, "hop_handles": (), "line": "h"},
            {"role": "chain_hop", "rank": 1, "hop_handles": (48,), "line": "h"},
            {"role": "chain", "rank": 2, "line": "CHAIN two", "handles": ()}]
    bd = types.SimpleNamespace(chains=[c0, c1], chain_counts={}, anchor_slugs=("cotton",), rows=[],
                               row=lambda *a: None)

    def bucket(pred):
        return 0, 0, 0, sum(1 for i, m in enumerate(rows) if pred(i, m)), []
    # ADDRESSES ONLY -- no reader name in the sentence, so only the rank join can name the two links
    sents = VF.sentences("Those two readings [N18] and [N48] lean opposite ways.")
    cov = R._chain_coverage(bd, rows, bucket, sents)
    assert cov["chain_referenced"] == 1 and len(cov["missed_chains"]) == 1


# ── R-2 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_R2a_the_chain_positioning_case_words_are_owner_ruling_one_from_the_book():
    ch = _chain("soybeans_cbot", [_hop("soybeans_cbot", "El_Nino", "oni_climate|_global|")], "soybeans_cbot")
    ch.positioning = {"percentile": 0.31, "against": False, "key": ("soybeans_cbot", "cot_mm_positioning")}
    same = R.sb_chain_positioning(ch, handle=53)
    assert same.endswith("the same way as this sequence, %s." % L.load_conventions()["positioning_words"]["same_way"])
    assert "reversal abrupt" in same and "amplifies" not in same and "[N53]" in same
    ch.positioning = dict(ch.positioning, against=True)
    other = R.sb_chain_positioning(ch)
    assert "cushions" in other and "abrupt" not in other
    # the walk's own note on the SAME fact says the same thing (THREAT S-1): one case vocabulary on one block
    assert "reversal abrupt" in inspect.getsource(W._positioning_note)
    for ln in (same, other):
        assert R.register_hits(ln) == [] and REG.count_desk_register(ln) == 0 and R.classify(ln) == ("SB-P",)


def _cot_row(pct, *, context_only=True, mechanism=None, contract="soybeans_cbot", driver="cot_mm_positioning"):
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="cot_mm_positioning", commodity=contract, country=""), status="ok",
                       table="silver_cot", metric="mm_net", cadence="weekly", unit="contracts",
                       narrate_unit="contracts", scale=1.0, level=-126674.0, level_date="2024-02-20",
                       knowledge_date="2024-02-26", asof="2024-03-01")
    st.z = {"value": -3.4, "window_n": 156}
    st.percentile = {"value": pct}
    g = G.CausalGraph(G.load_contracts(), silver=set(), version="deck")
    mech = g.driver(contract, driver).mechanism if mechanism is None else mechanism
    return B.NodeRow(contract=contract, driver_id=driver, state=st, sign="+", context_only=context_only,
                     mechanism=mech, lag_band=parse_lag("0-1 quarters"))


def test_R2b_a_positioning_row_at_its_records_end_carries_the_cards_own_mechanism_whole():
    row = _cot_row(0.3067484662576687)                                 # the 2024 record short: prints "0th"
    clause = R.positioning_asymmetry_clause(row, row.state)
    card = " ".join(str(row.mechanism).split()).rstrip(".")
    assert clause == "%s %s" % (R.POSITIONING_ASYMMETRY_LEAD, card)
    assert "while extreme positioning flags reversal risk" in clause, "the field WHOLE, never split on 'while'"
    assert R.POSITIONING_ASYMMETRY_LEAD == L.load_conventions()["positioning_words"]["record_extreme_lead"]
    blk = R.Block(start=14)
    line, calls = R.sb_state(14, row, asof="2024-03-01", block=blk)
    assert R.POSITIONING_ASYMMETRY_LEAD in line and "historical context only" in line
    assert blk.counters.get("positioning_asymmetry") == 1
    # a non-extreme reading (the 97th), a row that is not positioning, and a card with no mechanism: nothing
    for r in (_cot_row(97.0), _cot_row(0.31, context_only=False), _cot_row(0.31, mechanism="")):
        assert R.positioning_asymmetry_clause(r, r.state) == ""
    top = _cot_row(99.69)                                              # prints "100th": the record's other end
    assert R.positioning_asymmetry_clause(top, top.state)


def test_R2b_a_card_whose_text_a_detector_charges_prints_nothing_and_is_counted():
    row = _cot_row(0.31, mechanism="Managed-money net length amplifies rallies and forced liquidation/margin "
                                   "spirals exaggerates moves in thin cocoa liquidity.")     # the cocoa card
    assert R.register_hits(R.positioning_asymmetry_clause(row, row.state))
    blk = R.Block(start=1)
    line, _calls = R.sb_state(1, row, asof="2024-03-01", block=blk)
    assert R.POSITIONING_ASYMMETRY_LEAD not in line
    assert blk.counters.get("positioning_asymmetry_withheld") == 1 and "positioning_asymmetry" not in blk.counters


# ── R-3 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _build_soy_deep():
    g = G.CausalGraph(G.load_contracts(), silver=set(), version="harness")
    sg = types.SimpleNamespace(seeds=["soybeans_cbot"], nodes=[], trace={})
    q = "what is the situation on soybeans now? how is it looking 3 months from now?"
    bd = S.fill_stage1(graph=g, sg=sg, asof=M.ASOF, mode="deep", query=q,
                       state_fn=M.fixture_state_fn(M.ASOF), named=("soybeans_cbot",))
    S.fill_stage2(bd, graph=g, sg=sg, state_fn=M.fixture_state_fn(M.ASOF), state_chain=True, watch_nonobvious=True)
    return bd


def _unique_loud_hop(bd):
    for c in bd.chains:
        if not (getattr(c, "rendered", False) and getattr(c, "full", False)):
            continue
        for i, h in enumerate(c.hops):
            row = bd.row(h.contract, h.driver_id)
            if (h.measured and row is not None and row.state is not None and row.legs.get("loud")
                    and sum(1 for r in bd.rows if r.legs.get("loud") and r.state is not None
                            and r.state.key.label() == row.state.key.label()) == 1):
                return c, i, h, row
    return None


def test_R3_a_standing_the_hop_line_prints_is_addressed_when_the_loud_cut_did_not_print_its_row():
    bd = _build_soy_deep()
    target = _unique_loud_hop(bd)
    assert target, "the harness board carries a measured hop on a loud row"
    c, i, h, row = target
    row.legs["loud"] = False                                            # the loud cut no longer prints it
    row.state.percentile = {"value": 70.0}
    hops = list(c.hops)
    hops[i] = dataclasses.replace(h, percentile=70.0, tail_peak_percentile=70.0, tail_peak_date="")  # no transit
    c.hops = tuple(hops)
    blk = R.render_board(bd)
    assert "chain_hop_unaddressed" not in blk.counters, blk.counters
    rh = blk.row_handles[(h.contract, h.driver_id)]
    metas = [m for m in blk.rows_meta if m.get("role") == "cited_state" and m["handles"]
             and rh["level"] in m["handles"]]
    assert len(metas) == 1 and metas[0].get("rank") is None
    assert "70th percentile of its own record" in metas[0]["line"]
    assert [ln for ln in blk.lines if "seventieth percentile of its own record [N%d]" % rh["percentile"] in ln]


# ── R-4 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _soyoil_chain():
    return _chain("soybean_oil_cbot", [_hop("soybean_oil_cbot", "drought"),
                                       _hop("soybean_oil_cbot", "psd_ending_stock_su_ratio",
                                            "psd_ending_stock_su_ratio|soybean_oil_cbot|United States"),
                                       _hop("soybean_oil_cbot", "cot_mm_positioning", "cot_mm_positioning|soybean_oil_cbot|")],
                  "soybean_meal_cbot", agreements=("undetermined", "aligned", "undetermined"))


def test_R4b_the_backstop_sentence_keeps_the_hop_the_prose_cites_under_the_same_caps():
    ch = _soyoil_chain()
    rh = {("soybean_oil_cbot", "psd_ending_stock_su_ratio"): {"level": 46},
          ("soybean_oil_cbot", "cot_mm_positioning"): {"level": 36}}
    head = R.chain_page_sentence(ch, rh)
    assert "managed-money net position [N36]" in head and "[N46]" not in head      # HEAD's, byte for byte
    assert R.chain_page_sentence(ch, rh, cited=()) == head
    got = R.chain_page_sentence(ch, rh, cited=(23, 46, 48))                  # the TL;DR cites the S/U [N46]
    assert "stocks-to-use ratio" in got and "[N46]" in got and "[N36]" not in got
    assert len(got.split()) <= R.CHAIN_PAGE_SENTENCE_MAX_WORDS and R.CHAIN_PAGE_SENTENCE_MAX_NODES == 3
    # the prose already cites the last hop: HEAD's sentence names it and nothing moves
    assert R.chain_page_sentence(ch, rh, cited=(36, 46)) == head


def test_R4a_the_subject_answered_by_its_own_row_carries_the_slot_words():
    bd = _build_soy_deep()
    loud = [r for r in bd.rows if r.legs.get("loud") and r.state is not None and r.contract == "soybeans_cbot"
            and not r.context_only and ROWS.status_word(r.state.status) == "ok"]
    target = loud[-1]
    bd.chain_counts = dict(bd.chain_counts or {})
    bd.chain_counts["slot_state"] = dict(bd.chain_counts.get("slot_state") or {}, subject="answered_by_row")
    bd.subject = dict(getattr(bd, "subject", None) or {}, picked=[target.driver_id])
    words = L.load_conventions()["slot_words"]["answered_by_row"]
    blk = R.render_board(bd, page_markets=("soybeans_cbot",))
    hit = [ln for ln in blk.lines if words in ln]
    assert len(hit) == 1 and hit[0].startswith("- [N")
    # W not stamping the word (HEAD's walk) -> no line carries it
    bd.chain_counts["slot_state"]["subject"] = "answered_by_rank"
    assert not [ln for ln in R.render_board(bd, page_markets=("soybeans_cbot",)).lines if words in ln]


# ── P5 / P6 / P8 / P14 ───────────────────────────────────────────────────────────────────────────────────────
def test_P5_a_scalar_keeps_HEADs_shape_and_carries_the_new_keys_only_when_given():
    blk = R.Block()
    blk.scalar(3, unit="months", kind="run_length", text="three")
    blk.scalar(28, unit="markets", kind="fan_count", text="twenty-eight", words="in the opposite direction",
               fan_id="canola_ice|El_Nino|oni_climate|_global|")
    blk.add("- a line", label="x")
    a, b = blk.served_scalars()
    assert set(a) == {"value", "unit", "kind", "row_id", "handle", "text", "cls"}
    assert b["words"] == "in the opposite direction" and b["fan_id"].startswith("canola_ice|") and "direction" not in b
    assert ROWS.SCALAR_KINDS[-1] == "fan_count" and ROWS.SCALAR_KINDS[:15] == (
        "level", "sigma", "percentile", "window_peak_percentile", "current_level", "window_length", "run_length",
        "lag_band_quarters", "firings_count", "firings_aligned", "card_threshold", "outcome_move", "window_change",
        "pair_level_spread", "ask_row")


def test_P5_the_fan_registers_its_three_counts_and_prints_HEADs_line():
    g = G.CausalGraph(G.load_contracts(), silver=set(), version="deck")
    far = W.far_rows(W.fan_index(g), "canola_ice", "El_Nino")
    e = {"contract": "canola_ice", "driver_id": "El_Nino", "loud": True, "far": far, "series_key": "oni_climate|_global|"}
    blk = R.Block()
    line = R.sb_fan(e, block=blk)
    assert line == R.sb_fan(e), "the printed line is HEAD's"
    blk.add(line, label="fan")
    fan = [s for s in blk.served_scalars() if s["kind"] == "fan_count"]
    assert [s["value"] for s in fan][0] == float(len(far))
    assert {s["fan_id"] for s in fan} == {"canola_ice|El_Nino|oni_climate|_global|"}
    arms = [s for s in fan if s.get("words")]
    assert sum(s["value"] for s in arms) == float(len(far))
    assert all(s["words"] in (R.sign_words("+"), R.sign_words("-"), R.sign_words("0")) for s in arms)
    assert all(s["text"] == R.words_for_int(int(s["value"])) and s["unit"] == "markets" for s in fan)


def test_P5_the_run_scalar_carries_its_words_its_direction_and_the_rows_declared_vocabulary():
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="psd_ending_stock_su_ratio", commodity="french_rapeseed_matif",
                                          country="European Union"), status="ok", table="silver_psd",
                       metric="ending_stocks_su_ratio", cadence="annual", unit="%", narrate_unit="%", level=9.42,
                       level_date="2026", asof=ASOF)
    st.run = {"direction": "down", "length": 2, "since_date": "2025"}
    voc = R.run_direction_vocabulary(st)
    assert voc == {"up": ("rising", "loosening"), "down": ("falling", "tightening")}
    row = B.NodeRow(contract="french_rapeseed_matif", driver_id="ending_stocks_su_ratio", state=st, sign="-")
    blk = R.Block()
    line, calls = R.sb_state(1, row, asof=ASOF, block=blk)
    blk.add(line, calls, label="x")
    run = [s for s in blk.served_scalars() if s["kind"] == "run_length"]
    assert run and run[0]["words"] == "falling" and run[0]["direction"] == "down"
    assert run[0]["direction_words"]["down"] == ("falling", "tightening")
    other = ROWS.StateRow(key=ROWS.SeriesKey(ref="oni_climate", commodity="_global", country=""))
    assert R.run_direction_vocabulary(other) == {"up": ("rising",), "down": ("falling",)}


def test_P6_a_ledger_read_regime_prints_the_records_words_and_a_drawn_one_keeps_HEADs(monkeypatch):
    head = R._event_words("regime_in_force", event_date="2025-03-10", precision="month", published="2025-03-19")
    assert "that this turn retrieved" in head
    monkeypatch.setattr(R, "_ledger_origin", lambda: "action_ledger")
    assert R._event_words("regime_in_force", event_date="2025-03-10", precision="month", published="2025-03-19",
                          origin="other") == head
    led = R._event_words("regime_in_force", event_date="2025-03-10", precision="month", published="2025-03-19",
                         origin="action_ledger")
    assert "retrieved" not in led and led == R.REGIME_LEDGER_WORDS % "March 2025, reported 19 March 2025"
    assert R.REGIME_LEDGER_WORDS.count("%s") == 1 and R.REGIME_LEDGER_WORDS == L.load_conventions()["regime_words"]["ledger"]


def test_P8_one_book_names_every_windows_anchor_and_the_SB_J_words_are_HEADs_bytes():
    assert R.window_anchor_words("run", "2025-11") == "the run's start in November 2025"
    assert R.window_anchor_words("reading", "2026-07-01") == "this reading's own date in July 2026"
    assert R.window_anchor_words("peak", "2026-07") == "" and R.window_anchor_words("run", "") == ""
    st = types.SimpleNamespace(run={"since_date": "2025-11-01", "direction": "up", "length": 3})
    assert R._anchor_words(st, "2025-11-01") == "the run's start in November 2025"          # HEAD's literal
    assert R._anchor_words(st, "2026-07") == "this reading's own date in July 2026"          # HEAD's literal
    assert R._anchor_words(st, "") == "an anchor this card dates by no calendar period this board can place"


def test_P14_the_scope_field_is_absent_when_empty_and_its_clause_is_the_books():
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="psd_ending_stock_su_ratio", commodity="cotton", country="United States"),
                       status="ok", table="silver_psd", metric="ending_stocks_su_ratio", cadence="annual", unit="%",
                       narrate_unit="%", level=240.0, level_date="2026", asof=ASOF)
    assert "scope_resolution" not in st.to_dict()
    row = B.NodeRow(contract="cotton", driver_id="ending_stocks_su_ratio", state=st, sign="-")
    line0, _ = R.sb_state(1, row, asof=ASOF)
    st.scope_resolution = "home_for_global"
    assert st.to_dict()["scope_resolution"] == "home_for_global"
    line1, _ = R.sb_state(1, row, asof=ASOF)
    words = L.load_conventions()["scope_words"]["home_for_global"]
    assert words not in line0 and words in line1


# ── R-5 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_R5_every_new_row_word_is_declared_once_and_graded_by_clause_18(monkeypatch):
    assert L._check_row_word_books() == [] and L._check_tail_words() == []
    doc = dict(L.load_conventions())
    for book in L.ROW_WORD_BOOKS:
        assert isinstance(doc.get(book), dict) and doc[book], book
    # no book word is a literal in render.py -- the producers read the book
    src = inspect.getsource(R)
    for book in ("positioning_words", "regime_words", "scope_words", "slot_words", "window_anchor_words"):
        for w in doc[book].values():
            assert str(w).replace("{month}", "").replace("%s", "")[:40] not in src, (book, w)
    # the period joins moved out of rows.py into the book, read through one lazy map
    assert dict(ROWS.PERIOD_TOKEN_JOINS) == doc["period_joins"]
    assert ROWS.figure_token("325", unit="Million Bushels", period_words="2025/26",
                             period_kind="marketing_year") == "325 Million Bushels for 2025/26"
    # the clause bites: a digit, the same words on both sides, an instrument word, a missing book, a bad key
    bad = dict(doc)
    bad["positioning_words"] = {"same_way": "one row", "other_way": "one row", "record_extreme_lead": "x 2"}
    bad["direction_words"] = {"not_a_convention": {"up": "up", "down": "up"}}
    bad.pop("slot_words")
    monkeypatch.setattr(L, "load_conventions", lambda: bad)
    errs = L._check_row_word_books()
    assert any("same words" in e for e in errs) and any("digit" in e for e in errs)
    assert any("desk-register" in e for e in errs) and any("slot_words" in e and "missing" in e for e in errs)
    assert any("not_a_convention" in e for e in errs)
    assert L.check_state_board.__code__.co_names.count("_check_tail_words") == 1
