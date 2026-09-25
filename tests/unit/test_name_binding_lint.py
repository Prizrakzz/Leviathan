"""09-24 FIX ROUND 2 -- LANE A: THE ROW'S IDENTITY REACHES THE SENTENCE, AND THE SEAMS STOP WRITING FALSE WORDS.

What this deck pins, each on the 09-24 re-smoke's OWN served sentences (verbatim spans of the ten pages under
scratchpad/resmoke_0924/answers/, ASCII-folded) with the rows they cited rebuilt as the call records the
producers read -- the real `citations.call_identity` (lane C) and the real `verify.bind_figures` (lane V),
never a stand-in:

  K4   the name-binding lint's corrections (routing name, commodity, unit family, period) and its refusals
       (A-1: never a correct noun; a phrase that binds no ONE row is left and counted);
  K17  the superlative seam binds a CLAIM, never a denominator (the 2024 TL;DR), and still corrects a real
       record claim (A-2's miss side);
  29   the post-verify splice never prints a figure its clause already carries (A-8);
  28d  the footer emits a declared ledger row only when the page cites it (O-15, DM3);
  K1   the ledger threading (the seam kwargs, the chunk kwarg) and K20's three stamps' shapes;
  K8   the ask rows (a pair question only, the seat's calculator rows) and the ask / horizon clauses
       (A-7: the clause names HANDLES, never a figure);
  K19  the cascade mandates' register-worded variants (A-6: clause for clause, only the table's words);
  K9   the chain backstop prints a chain on the question's own markets, never `chains[0]` blind;
  9    the recency rows: the newest document is a MAX, the oldest number reads the seat's calls.

Every behaviour change here rides GRAPHRAG_STATE_BOARD / STATE_CHAIN / DESK_REGISTER or is a declared DM3
correction (items 28d, 29). Nothing here reads an environment variable except through `monkeypatch`.
"""
from __future__ import annotations

import inspect
import types

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import register as reg
from leviathan.graphrag import verify as vf
from leviathan.graphrag.state import narration as N

EMPTY = {"query": {"table": "silver_psd", "metric": "production_mt"}, "rows": [], "status": "ok"}


def _pad(n: int, calls: dict) -> list:
    """A positional call list of length ``n`` with ``calls`` at their 1-based [N] addresses."""
    out = [dict(EMPTY) for _ in range(n)]
    for i, c in calls.items():
        out[i - 1] = c
    return out


def _seat(table, metric, value, unit, *, commodity=None, country=None, period=None, known="2026-09-11"):
    q = {"table": table, "metric": metric, "commodity": commodity, "country": country, "period": period,
         "asof": "2026-09-24"}
    return {"query": q, "rows": [{"value": value, "unit": unit, "knowledge_date": known}], "status": "ok"}


def _board(table, metric, value, unit, *, row_id, commodity=None, country=None, period=None, routing="",
           stat="", known="2026-09-11", series_short="", commodity_words=None, route_is_series=False):
    c = _seat(table, metric, value, unit, commodity=commodity, country=country, period=period, known=known)
    c["_sb"] = True
    c["_row_id"] = row_id
    # FIXER PASS (REVIEW_RA M1): the identity the BLOCK printed rides the SB-1 call row (lane R's stamps)
    if series_short:
        c["rows"][0]["series_short"] = series_short
    if commodity_words is not None:
        c["rows"][0]["commodity_words"] = commodity_words
    if route_is_series:
        c["rows"][0]["route_is_series"] = True
    if routing:
        c["routing"] = routing
        c["rows"][0]["routing"] = routing
    if stat:
        c["rows"][0]["stat"] = stat
    return c


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# K4 -- THE NAME-BINDING LINT
# ══════════════════════════════════════════════════════════════════════════════════════════════════
RICE = ("The price-supportive export-restriction pattern counts the India export ban [N70], deliverable "
        "stocks [N172] and the stocks-to-use ratio [N169] against a threshold of three.")
SOYOIL = ("One shared price-pressuring driver sits on both: Russian sunflower production for 2026/27 at "
          "7.81 MMT [N31], the 99th percentile of its record [N33] -- declared to move palm, DCE olein and "
          "DCE soyoil in the opposite direction.")
CORNWHEAT = ("the two-sided part is that corn's own drivers lean both ways -- the largest US corn harvested "
             "area in 98 years' standing of its own record [N51][N53] and a warm-phase Pacific reading past "
             "the strong line [N18] both point lower.")


def _rice_calls():
    rid = "rough_rice_cbot|India_export_ban|export|rough_rice_cbot|India"
    return _pad(172, {70: _board("silver_psd", "exports_mt", 25.0, "MMT", row_id=rid,
                                 commodity="rough_rice_cbot", country="India", period="2026",
                                 routing="India export ban", series_short="exports for India",
                                 commodity_words="")})


def _soyoil_calls():
    rid = "malaysian_crude_palm_oil_cme|russia_sunoil_supply|sunflower_oil_supply|sunflower_oil|Russia"
    return _pad(33, {31: _board("silver_psd", "production_mt", 7.806, "MMT", row_id=rid,
                                commodity="sunflower_oil", country="Russia", period="2026",
                                routing="russia sunoil supply"),
                     33: _board("silver_psd", "production_mt", 99, "percentile", row_id=rid,
                                commodity="sunflower_oil", country="Russia", period="2026",
                                routing="russia sunoil supply")})


def _cw_calls():
    rid = "corn_cbot|area|psd_area|corn_cbot|United States"
    return _pad(53, {51: _board("silver_psd", "area_harvested", 35.8, "M ha", row_id=rid,
                                commodity="corn_cbot", country="United States", period="2026"),
                     53: _board("silver_psd", "area_harvested", 98, "percentile", row_id=rid,
                                commodity="corn_cbot", country="United States", period="2026")})


def test_K4_the_rice_routing_name_is_replaced_by_the_rows_own_short_name():
    """RICE, 09-24: "counts the India export ban [N70]" over `[N70] USDA PSD exports CBOT rice India MY2026
    = 25 MMT` -- a record EXPORTS FLOW named by the driver the block routed it for ("read here for India
    export ban"). The row's own short name replaces the driver's; the handle, the digits and every other
    word stay."""
    st = {"tldr": "", "mechanism": RICE}
    cen = an._name_binding_lint(st, _rice_calls())
    assert cen["outcome"] == "ok" and cen["routing_corrected"] == 1, cen
    assert "India export ban" not in st["mechanism"]
    # FIXER PASS (REVIEW_RA M1): the replacement is the name the BLOCK printed for the row (R's stamp)
    assert "the exports for India [N70]" in st["mechanism"], st["mechanism"]
    assert st["mechanism"].replace("the exports for India [N70]",
                                   "the India export ban [N70]") == RICE        # nothing else moved


def test_K4_the_soyoil_commodity_cut_gets_its_product_word_back():
    """SOYOIL/PALM, 09-24: "Russian sunflower production ... [N31]" over SUNFLOWER OIL production (the
    footer: "production sunflower oil Russia"). The series' commodity node ("sunflower oil", the hierarchy's
    own name) strictly contains the word the writer used; the rest is inserted, nothing removed."""
    st = {"tldr": "", "mechanism": SOYOIL}
    cen = an._name_binding_lint(st, _soyoil_calls())
    assert cen["commodity_corrected"] == 1, cen
    assert "Russian sunflower oil production for 2026/27 at 7.81 MMT [N31]" in st["mechanism"]
    assert len(st["mechanism"]) == len(SOYOIL) + len(" oil")


def test_K4_a_percentile_written_as_a_duration_is_rewritten_in_the_rows_own_form():
    """CORN/WHEAT, 09-24: "98 years' standing of its own record [N51][N53]" -- 98 is [N53]'s 98th
    PERCENTILE, and V bound it there with the unit family `duration` written. The figure is rewritten in the
    row's printed form (the ordinal), same number."""
    st = {"tldr": CORNWHEAT, "mechanism": ""}
    cen = an._name_binding_lint(st, _cw_calls())
    assert cen["unit_corrected"] == 1, cen
    assert "98th percentile" in st["tldr"] and "98 years'" not in st["tldr"]
    assert "[N51][N53]" in st["tldr"]


def test_K4_the_period_bound_to_the_handle_is_the_rows_own():
    """TARIFF, 09-24: "879.05 thousand MT [N3] over the two weeks to 10 September 2026" over ONE week's
    gross new sales (the newest of a two-row read). A COUNT of two periods of the row's own kind, bound to
    the handle by the citation grammar (written right after it), is replaced by the row's period words.
    The identity here states the observation week, as CONTRACT K4 spells `period_words` ("week to 3
    September 2026") -- see BUILD_A blockers for the seat-call half that lane C owns."""
    call = _seat("silver_esr", "gross_new_sales_1000mt", 879.05, "1000 MT", commodity="soybeans_cbot",
                 country="China", period="2026")
    calls = _pad(3, {3: call})
    sent = "Weekly sales were 879.05 thousand MT [N3] over the two weeks to 10 September 2026."
    ident = dict(cit.call_identity(call), period_words="week to 10 September 2026", period_kind="week")
    orig = cit.call_identity
    try:
        cit.call_identity = lambda c: ident if c is call else orig(c)
        st = {"tldr": "", "mechanism": sent}
        cen = an._name_binding_lint(st, calls)
    finally:
        cit.call_identity = orig
    assert cen["period_corrected"] == 1, cen
    assert st["mechanism"] == "Weekly sales were 879.05 thousand MT [N3] over the week to 10 September 2026."


def test_K4_a_horizon_in_the_same_clause_is_never_the_rows_period():
    """THE NEGATIVE CORPUS FOUND THIS (09-23 deep body, before the period rule was narrowed to the handle's
    own appositive): "over the next three months ... the crowd at the 99th percentile of its own record
    [N23]" -- a forward horizon, not the row's period. Only a phrase written right after the figure's own
    handle is its period; this one is left as written."""
    call = _seat("silver_cot", "mm_net", 99, "percentile", commodity="soybeans_cbot", period="2026-09-15")
    calls = _pad(23, {23: call})
    sent = ("over the next three months the supply-side loosening and the crowd at the 99th percentile of "
            "its own record [N23] are the risks to the tight-balance leg.")
    ident = dict(cit.call_identity(call), period_words="week to 15 September 2026", period_kind="week")
    orig = cit.call_identity
    try:
        cit.call_identity = lambda c: ident if c is call else orig(c)
        st = {"tldr": sent, "mechanism": ""}
        cen = an._name_binding_lint(st, calls)
    finally:
        cit.call_identity = orig
    assert st["tldr"] == sent and cen["period_corrected"] == 0, cen


def test_K4_A1_a_routing_word_that_IS_the_rows_own_name_is_never_corrected():
    """A-1: rice "ending stocks" routed for "ending stocks" -- the driver words are the series' own name,
    so there is nothing to correct and the lint must not touch them."""
    rid = "rough_rice_cbot|ending_stocks|psd_stock|rough_rice_cbot|United States"
    calls = _pad(5, {5: _board("silver_psd", "ending_stocks_mt", 1.283, "MMT", row_id=rid,
                               commodity="rough_rice_cbot", country="United States", period="2026",
                               routing="ending stocks")})
    sent = "US ending stocks are 1.28 MMT [N5], thin for the season."
    st = {"tldr": sent, "mechanism": ""}
    cen = an._name_binding_lint(st, calls)
    assert st["tldr"] == sent and cen["routing_corrected"] == 0, cen


def test_K4_the_lint_is_inert_without_its_producers_and_rides_the_board_flag_on_both_bodies(monkeypatch):
    """Defensive reads (CONTRACT.md's opening law): with V's binder absent the lint edits nothing and says
    so. It is called on BOTH serving bodies, after the verifier and before the register lint, under
    `_state_board_on()` (OWNER DECISION O-2), and its census rides the registered `writer_seam` key."""
    monkeypatch.delattr(vf, "bind_figures")
    st = {"tldr": "", "mechanism": RICE}
    assert an._name_binding_lint(st, _rice_calls())["outcome"] == "producer_absent"
    assert st["mechanism"] == RICE
    monkeypatch.undo()
    src2 = inspect.getsource(an._answer_l2)
    # 09-25 (A-2 / A-3): the served-scalars pool and the turn's as-of ride the board body's call
    assert ("_nbl = (_name_binding_lint(structured, extra_number_calls, board=_board,\n"
            "                                   served_scalars=_served_scalars, asof=asof)") in src2
    assert "if _state_board_on() else None)" in src2
    assert src2.index("_name_binding_lint(") < src2.index("_desk_register_lint(")
    assert 'sg.trace["writer_seam"]["name_binding"] = _nbl' in src2
    src1 = inspect.getsource(an._answer_onehop) if hasattr(an, "_answer_onehop") else inspect.getsource(an)
    assert "_name_binding_lint(structured, extra_number_calls, board=None)" in src1


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# K17 -- THE SUPERLATIVE SEAM BINDS A CLAIM, NEVER A DENOMINATOR
# ══════════════════════════════════════════════════════════════════════════════════════════════════
RID_CRUSH = "soybeans_cbot|crush_margin|cbot_board_crush_margin|_global|"
T2024 = ("Against that, the crush sits at 0.81 USD/bu [N52], the 11th percentile of its record but off its "
         "February bottom at the 3rd percentile [N58], and crude at the 58th percentile gives a modest "
         "demand-side offset.")


def _crush_calls():
    def b(v, u, stat=""):
        return _board("gold_board_crush", "crush_margin_usd_bu", v, u, row_id=RID_CRUSH, country="global",
                      period="2024-02-29", stat=stat, known="2024-03-01")
    return _pad(58, {52: b(0.808, "USD/bu"), 53: b(-1.5, "sigma"), 54: b(11, "percentile"),
                     58: b(3, "percentile", "window_peak_percentile")})


def test_K17_the_2024_denominator_is_never_re_ranked():
    """THE 2024 TL;DR, 09-24: "the 11th percentile of its record but off its February bottom at the 3rd
    percentile [N58]" shipped as "the 11th percentile of its 3rd-percentile" -- `record` read as an
    adjective (the word after it was not on a hand list) and the nearest handle's WINDOW TROUGH read as
    the current rank. The clause already states the row's rank (11th, one of that row's own percentile
    members), so `record` is its denominator and nothing moves."""
    calls = _crush_calls()
    st = {"tldr": T2024, "mechanism": ""}
    rows = an._seam_row_index(calls)
    cen = an._seam_tldr_consistency(st, rows, an._seam_percentiles(rows), number_calls=calls)
    assert st["tldr"] == T2024, st["tldr"]
    assert cen["superlatives_corrected"] == 0 and cen.get("superlatives_rank_written") == 1, cen


def test_K17_A2_a_real_record_claim_is_still_corrected_to_the_rows_CURRENT_rank():
    """A-2's miss side: a superlative that modifies the noun phrase bound to a figure of ONE row, with no
    rank of that row written, IS a claim -- corrected to the row's CURRENT percentile member, never its
    window extreme."""
    calls = _crush_calls()
    sent = "The crush posts a record-high margin of 0.81 USD/bu [N52] this week."
    st = {"tldr": sent, "mechanism": ""}
    rows = an._seam_row_index(calls)
    cen = an._seam_tldr_consistency(st, rows, an._seam_percentiles(rows), number_calls=calls)
    assert cen["superlatives_corrected"] == 1, cen
    assert "an 11th-percentile margin of 0.81 USD/bu [N52]" in st["tldr"], st["tldr"]
    assert "3rd" not in st["tldr"]                                  # never the window's trough


def test_K17_A2_the_09_16_max_TLDR_still_corrects_through_the_structural_branch():
    """A-2's MEASURED true charge, the served 09-16 max TL;DR verbatim with its own rows (the seam deck's
    MAX_ROWS fixture: [N42] the harvested-area level, [N44] its own 91st percentile, seat-shaped calls with
    no `_row_id`, so the rank is the label-head sibling's): "a record-high harvested area of 34.76 M ha
    [N42]" binds the figure 34.76 to [N42], no rank of that row is written in the clause, and it is still
    corrected to the 91st -- the structural branch keeps the true charge the word list used to find."""
    import test_writer_seam_lints as W
    calls = [c if c is not None else dict(EMPTY) for c in W.MAX_ROWS]
    st = {"tldr": W.MAX_TLDR, "mechanism": ""}
    rows = an._seam_row_index(calls)
    cen = an._seam_tldr_consistency(st, rows, an._seam_percentiles(rows), number_calls=calls)
    assert cen["superlatives_corrected"] == 1, cen
    assert "a 91st-percentile harvested area of 34.76 M ha [N42]" in st["tldr"]


def test_K17_a_record_that_binds_no_figure_is_not_a_claim():
    """"the record carries no figure for those scopes" binds no figure and no handle: not a claim, not
    counted as one (the retired noun-next word list is not needed for it)."""
    calls = _crush_calls()
    sent = "Elsewhere the record carries no figure for those scopes, which is a limit of the data."
    st = {"tldr": sent, "mechanism": ""}
    rows = an._seam_row_index(calls)
    cen = an._seam_tldr_consistency(st, rows, an._seam_percentiles(rows), number_calls=calls)
    assert st["tldr"] == sent and cen["superlatives_seen"] == 0, cen


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ITEM 29 -- THE SPLICE NEVER PRINTS A FIGURE TWICE (DM3, both cells)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _tape_calls():
    return _pad(218, {218: _seat("silver_futures_eod", "settle", 99, "percentile", commodity="soybeans_cbot",
                                 period="2026-09-22")})


def test_29_the_99th_percentile_is_not_spliced_a_second_time():
    """DEEP 2026, 09-24: "at the 99th percentile of the window read [N218]" became "... read 99
    percentile [N218]" -- "read" opens a value slot and the adjacency guard sees only a numeral IMMEDIATELY
    beside the handle. V's binding says the figure is already in the handle's own clause: no splice."""
    calls = _tape_calls()
    sent = ("up 176.25 over sixty-three sessions on that same contract and at the 99th percentile of the "
            "window read [N218].")
    st = {"tldr": "", "mechanism": sent}
    cen = an._resolve_number_handles(st, calls)
    assert st["mechanism"] == sent and cen["substituted"] == 0, (st, cen)


def test_29_A8_a_bare_value_slot_is_still_filled():
    """A-8: the stand-in fill the splice exists for is untouched -- a clause that states no figure of its
    own still gets the row's value."""
    calls = _tape_calls()
    st = {"tldr": "", "mechanism": "The front contract's standing in the window read [N218]."}
    cen = an._resolve_number_handles(st, calls)
    assert cen["substituted"] == 1 and "read 99 " in st["mechanism"], st      # the row's own value, once
    assert st["mechanism"].count("99") == 1, st


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ITEM 28d -- THE FOOTER'S OWN CITED-ONLY RULE HOLDS FOR THE DECLARED LEDGER (O-15, DM3)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_28d_a_declared_ledger_row_the_page_never_cites_is_not_emitted():
    """COTTON, 09-24: "[48] USDA FAS GAIN Report -- Cotton (2026-04-03) ..." printed with no E prefix and
    no body citation. A declared, resolved row is emitted only when the prose cites it; the prune reads
    the same walk, so a cited ref keeps its marker and row."""
    v = {"resolved": {"48": {"source": "usda_fas_gain", "date": "2026-04-03", "snippet": "cotton"},
                      "37": {"source": "usda_fas_gain", "date": "2026-04-22", "snippet": "cotton 2"}}}
    d = {"tldr": "", "mechanism": "The newest dated report is 22 April 2026 [E37].",
         "sources": [{"ref": 48, "source": "USDA FAS GAIN", "date": "2026-04-03"},
                     {"ref": 37, "source": "USDA FAS GAIN", "date": "2026-04-22"}]}
    refs = [r for r, _row in an._document_source_rows(d, v)]
    assert refs == ["37"], refs
    assert an._emitted_evidence_refs(d, v) == {"37"}
    # a caller asking about the LEDGER ALONE (no prose field at all) keeps HEAD's rows
    bare = {"sources": d["sources"]}
    assert [r for r, _row in an._document_source_rows(bare, v)] == ["48", "37"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# K1 -- THE LEDGER THREADING; K20 -- THE STAMPS' SHAPES
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_K1_the_seam_takes_the_ledgers_address_and_HEADs_kwargs_otherwise():
    """`evidence_address` REPLACES `e_start` and `evidence_ordinals` when the seam declares it; a seam
    that does not gets HEAD's two kwargs byte for byte, and a kwarg the seam does not declare is never
    passed."""
    uniq = [{"source_key": "a", "text": "x", "source": "s", "date": "2025-01-01"}]
    led = an._evidence_ledger(uniq)
    assert led is not None
    new = types.SimpleNamespace(fill_stage2=lambda bd, *, evidence_address=None, ask_rows=None,
                                extra_kd=None, e_start=1, evidence_ordinals=None: None)
    kw = an._stage2_kwargs(new, ledger=led, uniq=uniq, ask_rows=[("N3", {})], extra_kd=[{"rows": []}])
    assert set(kw) == {"evidence_address", "ask_rows", "extra_kd"}
    assert kw["evidence_address"] == led.address
    old = types.SimpleNamespace(fill_stage2=lambda bd, *, e_start=1, evidence_ordinals=None: None)
    kw0 = an._stage2_kwargs(old, ledger=led, uniq=uniq, ask_rows=[("N3", {})], extra_kd=[{}])
    assert kw0 == {"e_start": 2, "evidence_ordinals": an._evidence_ordinals(uniq)}
    kw1 = an._stage2_kwargs(new, ledger=None, uniq=uniq)
    assert kw1 == {"e_start": 2, "evidence_ordinals": an._evidence_ordinals(uniq)}


def test_K1_the_chunk_kwarg_rides_only_a_ledger_that_issued_an_address():
    """O-10: address-first resolution on board turns only, and only when the ledger issued anything.

    09-25 (VC-2, re-banked by the close-out lane AT): on a turn whose menu PRINTED its ordinals the menu IS
    issued -- an address the reader was handed is an address the ledger vouches for -- so the round-2 premise
    "a fresh ledger issues nothing" holds only where the menu printed none (the dossier lane's override). The
    registered-receipt half is driven on THAT ledger, the one that still starts with nothing issued."""
    uniq = [{"source_key": "a", "text": "x", "source": "s", "date": "2025-01-01"}]
    led = an._evidence_ledger(uniq)                       # the menu printed its ordinal (answer's own decision)
    assert an._evidence_chunks_kw(vf, None) == {}
    assert set(an._evidence_chunks_kw(vf, led)) == {"evidence_chunks"}          # 09-25 VC-2: the menu issues
    with an.handle_menu_override(False):                  # a menu that printed no ordinals issues nothing
        assert an._evidence_chunks_kw(vf, an._evidence_ledger(uniq)) == {}
        led0 = an._evidence_ledger(uniq)
    assert an._evidence_chunks_kw(vf, led0) == {}                    # nothing issued: HEAD's kwargs
    led0.address({"source_key": "b", "text": "y", "source": "t", "date": "2025-02-01"})
    kw = an._evidence_chunks_kw(vf, led0)
    assert set(kw) == {"evidence_chunks"} or "evidence_chunks" not in inspect.signature(
        vf.verify_citations).parameters


def test_K1_A5_a_board_receipt_past_the_menu_keeps_its_marker_and_gets_its_footer_row(monkeypatch):
    """I-1 / A-5, end to end with every producer live: the b40_event fixture board rendered with the ONE
    ledger's `address` (lane R), the ledger's `evidence()` as the verifier's list with its chunk kwarg
    (lane V), then lane A's [E] resolver, prune and footer. The board's receipt is NOT in the two-document
    menu, so it takes address 3; a writer sentence quoting it under [E3] keeps its marker and its footer
    row. Under HEAD's threading (the verifier and the prune see the menu alone) the same marker is pruned
    and the document is served bare -- the deep 2026 E48/E49 and tariff E46 class."""
    from leviathan.graphrag.state import __main__ as M
    from leviathan.graphrag.state import render as R
    monkeypatch.setattr(M, "B40_RECEIPTS", tuple(dict(r, source_key="text/source=b40/%d" % i)
                                                 for i, r in enumerate(M.B40_RECEIPTS)))
    ctx = M.build_scenario("b40_event")
    menu = [{"source_key": "text/source=menu/0", "source": "USDA FAS GAIN", "date": "2026-04-01",
             "text": "palm oil exports eased in the first quarter"},
            {"source_key": "text/source=menu/1", "source": "MPOC", "date": "2026-03-10",
             "text": "stocks built through the first quarter on weak exports"}]
    led = an._evidence_ledger(menu)
    blk = R.render_board(ctx["board"], analogs=ctx["analogs"], watch=ctx["watch"], recency=ctx["recency"],
                         evidence_address=led.address)
    text = blk.text() if callable(getattr(blk, "text", None)) else str(blk)
    ev = led.evidence()
    printed = sorted({int(x) for x in __import__("re").findall(r"\[E(\d+)\]", text)})
    assert printed and all(1 <= k <= len(ev) for k in printed), printed
    uni = cit.unify(ev, [])
    for k in printed:                                            # B15 (i): one numbering everywhere
        c = next(c for c in uni if getattr(c, "id", "") == "E%d" % k)
        assert (getattr(c, "payload", {}) or {}).get("source_key") == ev[k - 1]["source_key"]
    k = max(printed)
    assert k > len(menu)                                         # the receipt is past the menu
    sent = "The blend mandate moved to a forty percent palm basis on the first of May [E%d]." % k

    def served(uniq, kw):
        st = {"tldr": "", "mechanism": sent, "sources": [], "diagram_mermaid": ""}
        rep = vf.verify_citations(st, uniq, [], **kw)
        an._resolve_evidence_handles(st, uniq)
        pruned = an._prune_orphan_evidence_handles(st, rep)
        return st["mechanism"], pruned, an._cited_sources_block(st, rep, [])
    body, pruned, foot = served(ev, an._evidence_chunks_kw(vf, led))
    assert pruned == 0 and ("[E%d]" % k) in body and ("[%d] " % k) in foot, (body, foot)
    body0, pruned0, foot0 = served(list(menu), {})               # HEAD's threading
    assert pruned0 == 1 and ("[E%d]" % k) not in body0 and ("[%d] " % k) not in foot0


def test_K20_the_sources_ledger_is_the_declaration_without_its_snippet():
    st = {"sources": [{"ref": 46, "source": "USDA FAS GAIN", "date": "2025-02-01", "snippet": "long text"},
                      "garbage"]}
    assert an._sources_ledger(st) == [{"ref": 46, "source": "USDA FAS GAIN", "date": "2025-02-01"}]
    assert an._ledger_stamp(None) is None


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# K8 / K21 -- THE ASK AND THE HORIZON REACH THE TL;DR
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _calc(metric, value, unit, **row):
    return {"query": {"table": "compute_stat", "metric": metric},
            "rows": [dict({"value": value, "unit": unit, "knowledge_date": "2026-08-01"}, **row)],
            "status": "ok", "stat_provenance": {"stat": metric, "params": {}}}


def test_K8_the_ask_rows_are_the_seats_calculator_rows_on_a_pair_question():
    """PALM/RAPE, 09-24 (the F1 FATAL): N11-N13 window changes (palm +10,289 MT; China rapeseed oil
    +170,000 MT; US +9,000 MT) and N14 the pair spread (-357 USD/mt) were minted and served, and the
    TL;DR said the opposite. They are the ask rows -- the seat's calculator rows, in seat order -- on a
    question naming two markets; a lookup row is never one; a single-market question has no ask head
    (THREAT R-4), and a row whose own legs name OTHER markets is not the question's."""
    look = _seat("silver_mpob", "closing_stocks_palm_oil_mt", 2814199.0, "MT")
    calls = [look] * 10 + [_calc("window_change", 10289.0, "MT"), _calc("window_change", 170000.0, "MT"),
                           _calc("window_change", 9000.0, "MT"),
                           _calc("pair_spread", -357.0, "USD/mt",
                                 leg_a="silver_pink_sheet.palm_oil_cpo_usd_t[malaysian_crude_palm_oil_cme]",
                                 leg_b="silver_pink_sheet.rapeseed_oil_usd_t[rapeseed_oil_zce]"),
                           _calc("pair_spread", 5.0, "USD/mt", leg_a="x.y[corn_cbot]", leg_b="x.y[wheat_cbot]")]
    named = ("malaysian_crude_palm_oil_cme", "rapeseed_oil_zce")
    got = [h for h, _c in an._ask_rows(calls, named)]
    assert got == ["N11", "N12", "N13", "N14"], got
    assert an._ask_rows(calls, ("malaysian_crude_palm_oil_cme",)) == []
    # THE GATE READS LANE R's OWN ROW CLASS (SB-ASK): the head's rows and the tape spread, never the horizon
    block = ("STATE OF THE WORLD at 2026-09-23\nASKED ROW [N14] palm minus rapeseed oil: -357 USD/mt\n"
             "ASKED ROW [N11] palm closing stocks, change: +10,289 MT\nASKED SPREAD [N200] a minus b: +180.5\n"
             "ASKED HORIZON 3 months: the chain answers it\n- [N201] x")
    assert an._ask_head_printed(an._ask_rows(calls, named), block) == ("[N14]", "[N11]", "[N200]")
    assert an._ask_head_printed(an._ask_rows(calls, named), "STATE OF THE WORLD at x\n- [N14] x") == ()


def test_K8_A7_the_ask_clause_names_handles_and_no_figure_and_rides_the_board_only():
    base = an._system(state_board=True)
    lit = an._system(state_board=True, ask_head=("[N14]", "[N11]"))
    assert lit != base and "[N14] and [N11]" in lit
    clause = N.ask_head_mandate(("[N14]", "[N11]"))
    assert clause in lit
    assert not any(ch.isdigit() for ch in clause.replace("[N14]", "").replace("[N11]", ""))   # A-7
    assert an._system(ask_head=("[N14]",)) == an._system()           # a board-less turn cannot see it
    assert an._system(state_board=True, ask_head=()) == base          # an empty head ships nothing
    assert reg.count_desk_register(clause) == 0 and reg.count_desk_register(N.MANDATE_HORIZON_ROW) == 0
    hz = an._system(state_board=True, horizon_row=True)
    assert N.MANDATE_HORIZON_ROW in hz and N.MANDATE_HORIZON_ROW not in base


def test_K21_the_horizon_clause_is_gated_on_the_row_the_block_carries(monkeypatch):
    """With lane R's SB-ASK class the gate is the "ASKED HORIZON" line itself; a render that declares no
    such class falls back to the board facts that row is printed from."""
    assert an._horizon_row_on(None, "STATE OF THE WORLD at x\nASKED HORIZON 3 months: the chain answers it")
    assert not an._horizon_row_on(None, "STATE OF THE WORLD at x\nASKED ROW [N3] x: 1 MT")
    from leviathan.graphrag.state import render as R
    monkeypatch.setattr(R, "ROW_CLASSES", {k: v for k, v in R.ROW_CLASSES.items() if k != "SB-ASK"})
    ch = types.SimpleNamespace(rendered=True, slot_fits=("horizon",), rank=1,
                               outcome={"words": "two of the eight past times carry a price reading"})
    bd = types.SimpleNamespace(horizon_months=3, chain_counts={"slot_state": {"horizon": "answered_by_rank"}},
                               chains=(ch,))
    assert an._horizon_row_on(bd, "STATE OF THE WORLD ...") is True
    assert an._horizon_row_on(bd, "") is False                                   # no block, no clause
    bd.horizon_months = None
    assert an._horizon_row_on(bd, "x") is False                                  # no horizon asked
    bd.horizon_months = 3
    ch.outcome = {"words": ""}
    assert an._horizon_row_on(bd, "x") is False                                  # no outcome row to state


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# K19 -- THE MANDATES SPEAK THE REGISTER TABLE'S WORDS
# ══════════════════════════════════════════════════════════════════════════════════════════════════
#: The cascade block's own LINE MARKERS (numbers/cascade.py's line classes): the writer finds the lines by
#: them, so they stay spelled as the block prints them and are masked before the register count.
_MARKERS = ("CONSEQUENCE HOP", "CONSEQUENCE READ", "CONSEQUENCE ABSENCE", "CONSEQUENCE CONTEXT",
            "EXCHANGE RATE", "CONTEXT")


@pytest.mark.parametrize("head", list(getattr(an, "_CASCADE_DESK_VARIANTS", None) or ["<no variant map>"]))
def test_K19_every_desk_variant_is_clause_for_clause_in_the_tables_own_words(head):
    """A-6: the variant adds no content word the register table's replacement column does not teach
    (`_desk_allowed_stems`, the rewrite guard's own rule), carries no "firing" and no "the block", and
    scores ZERO on the extended table once the producer's line markers are masked."""
    assert isinstance(getattr(an, "_CASCADE_DESK_VARIANTS", None), dict), "no K19 variant map"
    var = an._CASCADE_DESK_VARIANTS[head]
    added = an._desk_content(var) - an._desk_content(head) - an._desk_allowed_stems()
    assert added <= {"episode", "page", "link", "market"}, added   # every one a table phrase's own word
    for w in sorted(added):
        assert any(w in an._desk_content(p) or w + "s" in an._desk_content(p)
                   for _n, _p, p in reg.DESK_REGISTER_TOKENS) or w == "page", w
    masked = var
    for mk in _MARKERS:
        masked = masked.replace(mk, " ")
    assert reg.count_desk_register(masked) == 0, reg.desk_register_hits(masked)
    assert "firing" not in var.lower() and "the block" not in var.lower()
    assert an._cascade_literal(head, False) is head                  # flag off: HEAD's object (B3)
    assert an._cascade_literal(head, True) == var


def test_K19_the_state_mandate_names_the_record_the_way_the_boards_rows_do():
    """"the other chain the block puts forward" (tariff) was the chain movement's own "the chains the block
    puts first". Under the desk register the mandate says "this page" -- the name the block's own rows give
    the record ("CHAIN the one this page carries") -- and with the register off it is HEAD's object."""
    from leviathan.graphrag.state import render as R
    # the NAME is the rows' own: the render's absence reasons speak of the record as "this page"
    _why = " ".join(str(v) for v in R.ABSENCE_WHY.values())
    assert _why.count(N.MANDATE_BLOCK_READER_NAME) >= 3, _why[:200]
    desk = N.state_board_mandate(nonobvious=True, chain=True, desk=True)
    # 09-25 (A-5): the movement names the record's LEADING chains, never the page's own verb
    assert "the block" not in desk and "take this page's leading chains" in desk
    assert N.state_board_mandate() is N.SYSTEM_STATE_BOARD_MANDATE
    assert N.check_literals() == []


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# K9 -- THE BACKSTOP PRINTS A CHAIN ON THE QUESTION'S OWN MARKETS
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_K9_the_backstop_takes_the_best_rendered_chain_on_a_question_market(monkeypatch):
    """COCOA / RICE, 09-24: the rank-1 rendered chain was Brazilian arabica into robusta -- on neither
    question's markets. The backstop reads the turn's own routed contracts; a board rendering ONLY foreign
    chains gets no backstop sentence and the refusal is counted."""
    from leviathan.graphrag.state import render as R
    foreign = types.SimpleNamespace(rendered=True, rank=1, contract="brazilian_arabica_coffee",
                                    terminal="robusta_coffee", hops=())
    home = types.SimpleNamespace(rendered=True, rank=2, contract="cocoa", terminal="cocoa", hops=())
    seen = []
    monkeypatch.setattr(R, "chain_referenced_in", lambda c, s, hop_handles=(): False)
    monkeypatch.setattr(R, "chain_page_sentence", lambda ch, h: seen.append(ch) or "One chain runs here.")
    bd = types.SimpleNamespace(chains=(foreign, home))
    st = {"tldr": "", "mechanism": "## Mechanism\nText."}
    cen = an._chain_backstop(st, bd, [], coverage={"chain_referenced": 0}, row_handles={},
                             page_markets=("cocoa",))
    assert cen["backstop_appended"] == 1 and seen == [home]
    bd2 = types.SimpleNamespace(chains=(foreign,))
    st2 = {"tldr": "", "mechanism": "## Mechanism\nText."}
    cen2 = an._chain_backstop(st2, bd2, [], coverage={"chain_referenced": 0}, row_handles={},
                              page_markets=("cocoa",))
    assert cen2["backstop_appended"] == 0 and cen2.get("backstop_off_question") == 1
    # R's adjacent-link count is the told-chain guard where the coverage carries it
    st3 = {"tldr": "", "mechanism": "## Mechanism\nText."}
    cen3 = an._chain_backstop(st3, bd, [], coverage={"chain_referenced": 1, "chain_referenced_adjacent": 0},
                              row_handles={}, page_markets=("cocoa",))
    assert cen3["backstop_appended"] == 1


def test_K12_the_lint_verifies_a_hop_against_the_name_the_block_printed_with_the_questions_markets(
        monkeypatch):
    """K9 / K12: lane R prefixes an off-question hop's board label when the seam is handed the question's
    distance-0 contracts ("MATIF rapeseed the stocks-to-use ratio ..." on the palm/rape board, measured on
    the trace's own EU hop). The L2 body threads `page_markets` to the seam AND to the chain lints, so the
    positional identity check compares the printed line with the SAME name; without it the hop would be
    identity-less and every correction on it would fail closed."""
    from leviathan.graphrag.state import render as R

    def name(h, *, page_markets=()):
        pre = "MATIF rapeseed " if page_markets and h.contract not in page_markets else ""
        return pre + "the stocks-to-use ratio for European Union"
    monkeypatch.setattr(R, "chain_hop_name", name)
    monkeypatch.setattr(R, "chain_hop_reader_names", lambda h, *, page_markets=(): (name(h, page_markets=page_markets),))
    hop = types.SimpleNamespace(contract="french_rapeseed_matif", driver_id="ending_stocks_su_ratio",
                                series_key="psd_ending_stock_su_ratio|french_rapeseed_matif|European Union",
                                measured=True)
    ch = types.SimpleNamespace(rendered=True, rank=1, hops=(hop,), contract="french_rapeseed_matif",
                               terminal="malaysian_crude_palm_oil_cme")
    pm = ("malaysian_crude_palm_oil_cme",)
    bd = types.SimpleNamespace(rendered_rows=({"role": "chain_hop", "rank": 1,
                                               "line": R.CHAIN_SUB_PREFIX + name(hop, page_markets=pm)
                                               + " [N1]: (reading)"},),
                               chains=(ch,), anchor_slugs=pm, rows=())
    calls = [_seat("silver_psd", "su_ratio", 9.417, "%", commodity="french_rapeseed_matif",
                   country="European Union", period="2026")]
    got = an._chain_hop_rows(bd, calls, pm)
    assert got and got[0]["contract"] == "french_rapeseed_matif", got
    assert an._chain_hop_rows(bd, calls)[0]["contract"] == ""          # unthreaded: identity-less (HEAD)
    src = inspect.getsource(an._answer_l2)
    assert "page_markets=_page_markets" in src and "_page_markets: tuple = tuple(getattr(sg, \"seeds\"" in src


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ITEM 9 (narration half) -- THE RECENCY FACTS EQUAL THE PAGE'S OWN EXTREMES
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_9_the_newest_document_is_a_max_and_nothing_wins_it_by_position():
    """SOYOIL/PALM, 09-24: "the newest dated document behind this answer is 17 March 2022" beside its own
    [E2] of 2024-04-05 -- the board's receipt edge won over the menu's record_through by POSITION."""
    bd = types.SimpleNamespace(recency={"text": "2022-03-17", "numbers": "2026-09-10"}, series={},
                               asof="2026-09-23")
    rows = N.recency_rows(bd, record_through="2024-04-05", tape_edge="2026-09-22")
    assert rows["text"].endswith("2024-04-05"), rows["text"]
    rows2 = N.recency_rows(bd, record_through="2021-01-01", tape_edge="2026-09-22")
    assert rows2["text"].endswith("2022-03-17")                  # the board's edge when IT is the newest


def test_9_the_oldest_number_reads_the_seats_served_calls_through_the_footers_own_date():
    """COCOA / RICE / MAX / CORN-WHEAT / TARIFF, 09-24: "the oldest ..." was the BOARD's oldest only --
    a served SEAT call is read through `citations.from_number(call).date`, the date its footer stamps."""
    bd = types.SimpleNamespace(recency={"numbers": "2026-09-10"}, series={}, asof="2026-09-23")
    old = _seat("silver_psd", "production_mt", 1.0, "MMT", commodity="cocoa", period="2026", known="2026-05-01")
    new, oldest = N.knowledge_edges(bd, [old])
    assert oldest == "2026-05-01" and new == "2026-09-10", (new, oldest)


# == FIXER PASS (fix round 2) -- the name lint reads IDENTITIES, never strings, and binds no wider than the
#    row's own noun. Every sentence below is the review's own probe (REVIEW_RA M1 / REVIEW_VC M3 / M1). ========
def _one(k, call, sent, *, field="tldr"):
    calls = _pad(k, {k: call})
    st = {"tldr": sent if field == "tldr" else "", "mechanism": sent if field == "mechanism" else ""}
    cen = an._name_binding_lint(st, calls)
    return st[field], cen


def test_fixer_RA_M1_the_replacement_is_the_name_the_block_printed_never_a_second_derivation():
    oni = _board("silver_noaa_oni", "oni_anom", 0.98, "degC", row_id="palm|El_Nino|oni_climate|_global|",
                 commodity="_global", period="2026-08", routing="El Nino",
                 series_short="the tropical Pacific sea-surface temperature anomaly", commodity_words="")
    out, cen = _one(1, oni, "El Nino reads 0.98 degC [N1].")
    assert out == "The tropical Pacific sea-surface temperature anomaly reads 0.98 degC [N1].", out
    assert "global" not in out and cen["routing_corrected"] == 1


def test_fixer_RA_M1_a_routing_driver_that_IS_the_series_is_never_rewritten():
    fx = _board("silver_fred_fx", "idr_usd", 97.29, "IDR per USD", row_id="palm|IDR_USD|fx|_global|",
                commodity="_global", period="2026-09-18", routing="IDR USD",
                series_short="IDR/USD exchange rate", commodity_words="", route_is_series=True)
    sent = "IDR/USD sits at 97.29 [N41], a weaker rupiah."
    out, cen = _one(41, fx, sent)
    assert out == sent and cen["routing_corrected"] == 0


def test_fixer_RA_M1_a_modifier_the_printed_name_carries_is_absorbed_never_doubled():
    mpob = _board("silver_mpob", "closing_stocks_palm_oil_mt", 2814199.0, "MT",
                  row_id="palm|ending_stocks|mpob|palm|", commodity="malaysian_crude_palm_oil_cme",
                  period="2026-08", routing="ending stocks",
                  series_short="Malaysian closing palm oil stocks", commodity_words="")
    out, cen = _one(5, mpob, "Malaysian ending stocks rose to 2,814,199 MT [N5].")
    assert out == "Malaysian closing palm oil stocks rose to 2,814,199 MT [N5].", out


def test_fixer_VC_M3_words_that_are_not_the_rows_own_noun_are_left_as_written():
    """REVIEW_VC M3, the reviewer's own two probes: the routing words and the commodity word sit in the
    clause but are not the noun bound to the figure (the writer names the exports after the ban, and the
    harvest is the seed crop, not the oil row) -- left as written."""
    rice = _rice_calls()[69]
    s1 = "The India export ban ended in 2024 and Indian exports now stand at 22,500,000 MT [N70]."
    out1, cen1 = _one(70, rice, s1)
    assert out1 == s1 and cen1["routing_corrected"] == 0, out1
    sun = _soyoil_calls()[30]
    s2 = "The Russian sunflower harvest was poor and production reached 7,806,000 MT [N31]."
    out2, cen2 = _one(31, sun, s2)
    assert out2 == s2 and cen2["commodity_corrected"] == 0, out2


def test_fixer_VC_M1_the_real_seat_week_and_this_marketing_year_are_corrected():
    """REVIEW_VC M1 / RA M8, on the REAL identity (no stand-in): the ESR seat call's period is its headline
    row's WEEK, so "over the two weeks" after the handle and "this marketing year" before the figure are
    both corrected to the row's own week; a run written before a handle ("in each of the last two weeks
    [N241]") is never the row's period."""
    call = {"query": {"table": "silver_esr", "metric": "gross_new_sales_1000mt", "commodity": "soybeans_cbot",
                      "country": "China", "period": "2026", "asof": "2026-09-24"},
            "rows": [{"value": 0.0, "unit": "1000 MT", "period": "2027", "data_date": "2026-09-03",
                      "knowledge_date": "2026-09-10", "country": "China"},
                     {"value": 879.05, "unit": "1000 MT", "period": "2027", "data_date": "2026-09-10",
                      "knowledge_date": "2026-09-17", "country": "China"}], "status": "ok"}
    s = "Gross new sales to China were 879.05 thousand MT [N3] over the two weeks to 10 September 2026."
    out, cen = _one(3, call, s, field="mechanism")
    assert out == "Gross new sales to China were 879.05 thousand MT [N3] over the week to 10 September 2026.", out
    wk = dict(call, query=dict(call["query"], metric="weekly_exports_1000mt"),
              rows=[dict(call["rows"][1], value=0.0)])
    s1 = "Chinese purchases of US beans this marketing year read 0 thousand MT of weekly exports [N1]."
    out1, cen1 = _one(1, wk, s1)
    assert out1 == ("Chinese purchases of US beans this week to 10 September 2026 read 0 thousand MT of "
                    "weekly exports [N1]."), out1
    s2 = "Sales have risen in each of the last two weeks [N241], by 191."
    run = dict(wk, rows=[dict(call["rows"][1], value=191.0)])
    out2, _c2 = _one(241, run, s2)
    assert out2 == s2


def test_fixer_B20_a_routing_word_inside_the_rows_own_printed_name_is_the_row_named():
    """FIXER SELF-REFUTATION (B20 hand classification of the 09-24 corpus): deep soybeans 2026 wrote "US
    harvested area at 34.76 M ha [N176]" over the row printed "CBOT soybeans area harvested for United States",
    read here for the driver "area". Every routing word is a word of the row's own printed name, so the writer
    NAMED THE ROW and the lint leaves it -- the first cut rewrote it to "US CBOT soybeans area harvested for
    United States at ...". A routing phrase with a word the printed name lacks is still corrected (the rice
    pin above)."""
    rid = "soybeans_cbot|area|area|soybeans_cbot|United States"
    area = _board("silver_psd", "area_harvested_1000ha", 34.76, "M ha", row_id=rid, commodity="soybeans_cbot",
                  country="United States", period="2026", routing="area",
                  series_short="CBOT soybeans area harvested for United States", commodity_words="CBOT soybeans")
    sent = ("US harvested area at 34.76 M ha is the 91st percentile of its own record [N176], also loosening "
            "on a two-to-four-quarter clock")
    out, cen = _one(176, area, sent, field="mechanism")
    assert out == sent and cen["routing_corrected"] == 0, out
    assert an._nbl_words_within("area", "CBOT soybeans area harvested for United States")
    assert not an._nbl_words_within("India export ban", "exports for India")
    # the containment reads the name the block PRINTED, never C's derivation: "drought" is in C's "drought
    # z-score" but not in the printed "the longest dry-day run in the month, as a z-score ...", so a drought
    # routing name on that row is still corrected
    dry = _board("gold_weather_z", "dry_run_z", 0.79, "sigma", row_id="palm|drought|wx|_basin|",
                 commodity="malaysian_crude_palm_oil_cme", period="2026-08", routing="drought",
                 series_short="the longest dry-day run in the month, as a z-score for SE Asia Palm Belt",
                 commodity_words="")
    out2, cen2 = _one(34, dry, "Drought reads 0.79 sigma [N34].")
    assert out2 == ("The longest dry-day run in the month, as a z-score for SE Asia Palm Belt reads 0.79 sigma "
                    "[N34]."), out2
    # every word counts, short ones included: "crude oil" is not a word-subset of the printed Brent name
    assert not an._nbl_words_within("crude oil", "the Brent crude price against its own five-year record")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 09-25 FIX ROUND 3 (lane A, items A-2 / A-3) -- CORRECTION 4 NEVER TOUCHES A DURATION THE ROW BACKS
# The served 09-25 sentences, verbatim (ASCII-folded), over board calls of the shipped shape: the lint wrote
# "rising December 2023 straight", "falling week to 20 February 2024 running", "falling 2026/27" and "about a
# 20 August 2026 before the data" -- nine period corrections on seven pages, all nine false.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
RID_ONI = "soybeans_cbot|La_Nina|oni_climate|_global|"
RID_COT = "soybeans_cbot|cot_mm_positioning|cot_mm_positioning|soybeans_cbot|"
RID_CRUSH25 = "soybeans_cbot|soybean_crush_margin|cbot_board_crush_margin|_global|"
ONI_2024 = ("Warm-phase Pacific +1.99 degC, December 2023 [N16], +2.0 sigma on ten years [N17], rising fourteen "
            "months straight.")
COT_2024 = ("Managed money on beans -126,674 contracts in the week to 20 February 2024 [N10], -3.4 sigma [N11], "
            "falling eight weeks running; on meal -27,990 contracts [N13], the 2nd percentile of its own record "
            "[N15].")
CRUSH_MAX = ("The crush reading is read through 21 August 2026, about a month before the data as of 25 "
             "September 2026 [N138].")


def _asof(c, asof):
    c["query"]["asof"] = asof
    return c


def _oni_calls():
    return _pad(17, {16: _asof(_board("silver_noaa_oni", "oni_anom", 1.99, "degC", row_id=RID_ONI,
                                      commodity="_global", period="2023-12", known="2024-02-05"), "2024-03-01"),
                     17: _asof(_board("silver_noaa_oni", "oni_anom", 2.0, "sigma", row_id=RID_ONI,
                                      commodity="_global", period="2023-12", stat="sigma",
                                      known="2024-02-05"), "2024-03-01")})


def _cot_calls():
    return _pad(15, {10: _asof(_board("silver_cot", "mm_net", -126674.0, "contracts", row_id=RID_COT,
                                      commodity="soybeans_cbot", period="2024-02-20", known="2024-02-26"),
                               "2024-03-01"),
                     11: _asof(_board("silver_cot", "mm_net", -3.4, "sigma", row_id=RID_COT,
                                      commodity="soybeans_cbot", period="2024-02-20", stat="sigma",
                                      known="2024-02-26"), "2024-03-01")})


def test_0925_A2_a_run_the_block_printed_is_never_rewritten_as_the_rows_period():
    """THE 2024 PAGE (A-2): "rising fourteen months straight" is the ONI row's run of fourteen and "falling eight
    weeks running" the COT row's run of eight -- both TRUE, both run members the block printed (the served-
    scalars pool's `run_length` of the same `_row_id`). HEAD replaced each with the row's period words. The
    tree leaves both as written and counts them `period_duration_kept`; the figures and handles never move."""
    pool = [{"value": 14.0, "unit": "months", "kind": "run_length", "row_id": RID_ONI, "handle": None, "text": ""},
            {"value": 8.0, "unit": "weeks", "kind": "run_length", "row_id": RID_COT, "handle": None, "text": ""}]
    for sent, calls in ((ONI_2024, _oni_calls()), (COT_2024, _cot_calls())):
        st = {"tldr": "", "mechanism": sent}
        cen = an._name_binding_lint(st, calls, served_scalars=pool, asof="2024-03-01")
        assert st["mechanism"] == sent, st["mechanism"]
        assert cen["period_corrected"] == 0 and cen["period_duration_kept"] == 1, cen


def test_0925_A2_the_row_counts_are_the_run_and_the_window_the_block_printed_and_nothing_else():
    """The members are read off the served-scalars pool (C4's transport) by the call's own `_row_id`: the run
    and the sigma window -- both counts of the row's own observations -- and never another scalar kind. No
    pool and no board -> no member, never a guess."""
    assert an._nbl_row_runs(None, None) == {}
    pool = [{"value": 14.0, "kind": "run_length", "row_id": RID_ONI},
            {"value": 60, "kind": "window_length", "row_id": RID_ONI},
            {"value": 3.0, "kind": "percentile", "row_id": RID_ONI},
            {"value": 5.0, "kind": "run_length", "row_id": None}]
    assert an._nbl_row_runs(pool) == {RID_ONI: {14, 60}}


def test_0925_A3_an_age_the_row_backs_is_never_rewritten_as_the_rows_period():
    """THE MAX PAGE (A-3): "about a month before the data as of 25 September 2026 [N138]" -- the crush row was
    known 21 August, 35 days before the as-of: one month by the age clause's own arithmetic
    (`narration.age_in_periods`). HEAD read "a month" as a LONGER kind than the row's day and printed "about a
    20 August 2026 before the data". Left as written, counted `period_duration_kept`."""
    cr = _asof(_board("gold_board_crush", "crush_margin_usd_bu", 2.6, "USD/bu", row_id=RID_CRUSH25,
                      country="global", period="2026-08-20", known="2026-08-21"), "2026-09-25")
    st = {"tldr": "", "mechanism": CRUSH_MAX}
    cen = an._name_binding_lint(st, _pad(138, {138: cr}), asof="2026-09-25")
    assert st["mechanism"] == CRUSH_MAX, st["mechanism"]
    assert cen["period_corrected"] == 0 and cen["period_duration_kept"] == 1, cen
    assert N.age_in_periods("2026-08-21", "2026-09-25") == {
        "marketing_year": (0, 0), "crop_season": (0, 0), "month": (1, 1), "week": (5, 5), "day": (35, 35)}


def test_0925_A3_a_bare_count_the_row_does_not_back_is_left_as_written_and_counted():
    """THE GRAMMAR GUARD: the replacement is a period NAME ("December 2023"), so it may stand only where the
    writer wrote a period NAME -- a count DATED by its own end ("the two weeks to 10 September 2026", the
    K4 pin above, still corrected). A bare count the row does not back ("seven months" over a run of
    fourteen) is a LENGTH: putting a name in its slot is the broken English the 09-25 pages printed. It is
    left as written and counted `period_unanchored`, never rewritten."""
    sent = ONI_2024.replace("fourteen", "seven")
    pool = [{"value": 14.0, "kind": "run_length", "row_id": RID_ONI}]
    st = {"tldr": "", "mechanism": sent}
    cen = an._name_binding_lint(st, _oni_calls(), served_scalars=pool, asof="2024-03-01")
    assert st["mechanism"] == sent and cen["period_corrected"] == 0, (cen, st["mechanism"])
    assert cen["period_unanchored"] == 1 and cen["period_duration_kept"] == 0, cen


def test_0925_the_age_clause_prints_HEADs_words_through_the_one_age_arithmetic():
    """`age_clause` now reads `age_span` -- one arithmetic for the words the block prints and the age the
    lint compares against. Its output is HEAD's, byte for byte, on both unit branches and on a fresh row."""
    assert N.age_clause("2026-08-21", "2026-09-25", "daily") == \
        "read through 2026-08-21, 1-month span to this as-of"
    assert N.age_clause("2026-09-01", "2026-09-25", "daily") == \
        "read through 2026-09-01, 24-day span to this as-of"
    assert N.age_clause("2020-01-15", "2026-09-25", "monthly") == \
        "read through 2020-01-15, 6-year span to this as-of"
    assert N.age_clause("2026-09-20", "2026-09-25", "daily") == ""
    assert N.age_clause("not a date", "2026-09-25", "daily") == ""
    assert N.age_span("2026-08-21", "2026-09-25") == {"days": 35, "months": 1, "from": "2026-08-21",
                                                      "to": "2026-09-25"}



# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 09-25 CLOSE-OUT (lane AT, item AT-4; VERIFY MINOR-3 / RT-7) -- THE FORK CLAUSE AND THE DESK TABLE SPEAK ONE
# VOCABULARY
# ══════════════════════════════════════════════════════════════════════════════════════════════════
#: The served 09-25 cocoa sentence (raw draft, '## Where the record disagrees'), verbatim.
_COCOA_TIER = ("The two readings of the same season's cushion differ by trust tier: the ICCO's published "
               "2024/25 stocks-to-grindings is 29.2% [E7], while the series read here gives 28.52% [N1].")


def test_0925_AT4_the_fork_clause_is_the_register_tables_own_words_under_the_register_and_HEADs_off_it(
        monkeypatch):
    """MEASURED: the cocoa page named two RELEASES of one ICCO series "trust tier" -- the persona's own fork
    clause ("sources of different trust tiers that disagree") -- while, with GRAPHRAG_DESK_REGISTER lit, the
    desk table (RT-7) charges exactly that phrase: one prompt taught it and charged it. Under the register
    the clause is COMPOSED from the table row's own replacement column; with the register off every persona
    byte is HEAD's (B1). The clause is keyed on its ONE definition (`response_contracts.FORK_SOURCES_CLAUSE`),
    which both needles and the persona carry."""
    from leviathan.graphrag import response_contracts as rc
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")          # the persona alone (the B1 cell)
    clause = rc.FORK_SOURCES_CLAUSE
    for text in (an._SYSTEM_MENTOR, rc.NEEDLE_STRUCTURE, rc._DISAGREES_RULE):
        assert text.count(clause) == 1                             # the ONE needle every copy carries
    # the served sentence IS charged by the table, and so is the clause that taught it...
    assert [n for n, _s in reg.desk_register_hits(_COCOA_TIER)] == ["trust tier"]
    assert [n for n, _s in reg.desk_register_hits(clause)] == ["trust tier"]
    # ...and the register's variant is composed of the row's own three phrases, adds no content word the
    # table does not teach, and is charged nothing
    var = an._DESK_FORK_CLAUSE
    for k in range(3):
        assert reg.desk_phrase("trust tier", k) in var, k
    assert an._desk_content(var) - an._desk_content(clause) - an._desk_allowed_stems() == set()
    assert reg.desk_register_hits(var) == [] and reg.count_desk_register(var) == 0
    # FLAG OFF: HEAD's object, on every contract
    assert an._system() is an._SYSTEM_MENTOR
    for name in sorted(rc.CONTRACTS):
        assert an._system(response_contract=name, desk_register=False) == an._system(response_contract=name)
    # FLAG ON: the persona's clause speaks the register on every contract whose plan carries the fork heading;
    # a plan without the heading carries no fork rule to correct
    for name in sorted(rc.CONTRACTS):
        lit = an._system(response_contract=name, desk_register=True)
        has_fork = rc.DISAGREES in rc.CONTRACTS[name].sections
        assert clause not in lit, name
        assert lit.count(var) == (1 if has_fork else 0), name
    # ...and it is the ONE substitution the leg adds to the persona: the rest is the pure append
    assert an._system(desk_register=True) == an._desk_fork_words(an._system()) + N.desk_register_mandate()
    base = an._system(state_board=True)
    assert an._system(state_board=True, desk_register=True) == an._desk_fork_words(
        base.replace(N.state_board_mandate(), N.state_board_mandate(desk=True))) \
        + N.desk_register_mandate(state_board=True)
    assert "trust tier" in {n for n, _s in reg.desk_register_hits(an._SYSTEM_MENTOR)}           # HEAD's taught it
    assert "trust tier" not in {n for n, _s in reg.desk_register_hits(an._desk_fork_words(an._SYSTEM_MENTOR))}


def test_0925_AT4_the_fork_detector_counts_one_publishers_releases_as_one_tier():
    """The detector half, pinned where it stands (no code moved): `_fork_basis`'s `tier_mixed` is read off
    the DOCUMENTS the prompt showed -- never off a served row -- so two releases of one publisher are one
    tier, and the served ICCO row is not an input at all. The 09-25 cocoa turn's `tier_mixed` came from two
    PUBLISHERS the writer itself declared (the ICCO bulletin, T3, and the World Bank outlook, T4). Documents
    as the served cocoa ledger declared them (source ids from the store's own cocoa families)."""
    feb = {"source": "icco_qbcs_summary", "date": "2026-02-27", "text": "2024/25 stocks-to-grindings 29.2%"}
    aug = {"source": "icco_qbcs_summary", "date": "2025-08-31", "text": "2023/24 stocks-to-grindings 26.4%"}
    ewg = {"source": "icco_ewg_stocks", "date": "2025-06-01", "text": "end-season stocks"}
    wb = {"source": "wb_cmo_outlook", "date": "1996-08-01", "text": "cocoa prices"}
    one_publisher = an._fork_basis(None, [], [feb, aug, ewg], {})
    assert one_publisher["tier_mixed"] is False                    # a revision is never a second tier
    assert an._fork_basis(None, [], [feb, aug, wb], {})["tier_mixed"] is True     # another publisher is
    assert "served" not in inspect.signature(an._fork_basis).parameters   # no served row reaches it
