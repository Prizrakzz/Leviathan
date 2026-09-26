"""LANE A -- the post-arm-A fix sitting (2026-09-26): A-1 the noun licence, A-2 the trailing run and the
markup-aware capital, A-3 the backstop's guard over addressed links (+ P11's `cited`), A-4 the record-extreme
mandate clause, A-5 the chain paragraph's subject order.

Every served sentence below is quoted VERBATIM from the arm-A drafts (scratchpad arm_a_0926/answers, the
post-verify raw drafts the served name-binding lint read); every card text is the curated card's own words.
The negative corpus is not here: it is the eighty's served prose, driven in BUILD_A.md sec 1 (0 false
corrections), never this deck's own list (the 09-15 law)."""
from __future__ import annotations

import ast
import inspect
import re
import textwrap
import types

import pytest

from leviathan.graphrag import answer as an
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R

EMPTY = {"query": {"table": "silver_psd", "metric": "production_mt"}, "rows": [], "status": "ok"}


def _pad(n: int, calls: dict) -> list:
    out = [dict(EMPTY) for _ in range(n)]
    for i, c in calls.items():
        out[i - 1] = c
    return out


def _board_call(table, metric, value, unit, *, row_id, commodity, country=None, period="2026", routing="",
                series_short="", known="2026-09-11"):
    q = {"table": table, "metric": metric, "commodity": commodity, "period": period, "asof": "2026-09-26"}
    if country:
        q["country"] = country
    row = {"value": value, "unit": unit, "knowledge_date": known, "stat": "level"}
    if routing:
        row["routing"] = routing
    if series_short:
        row["series_short"] = series_short
        row["commodity_words"] = ""
    c = {"query": q, "rows": [row], "status": "ok", "_sb": True, "_row_id": row_id}
    if routing:
        c["routing"] = routing
    return c


# THE CURATED CARD TEXTS the routing nodes carry (configs/graphrag/causal/rough_rice_cbot.yaml, as served) --
# handed to the lint as the board rows the served turn carried (`NodeRow.mechanism` / `blurb`).
_CARDS = {
    ("rough_rice_cbot", "tenderable_collapse"): (
        "A drop in deliverable US long-grain stocks against CBOT specs causes the thin contract to squeeze and "
        "detach from cash.",
        "Drop in deliverable US long-grain stocks squeezes thin contract, detaching it from cash."),
    ("rough_rice_cbot", "India_export_ban"): (
        "India banning/curtailing non-basmati and broken rice exports removes ~40% of world trade overnight, "
        "spiking global and CBOT-linked prices.",
        "India's rice export restrictions spike global prices by removing 40% of world supply."),
}


def _rice_board():
    rows = [types.SimpleNamespace(contract=c, driver_id=d, mechanism=m, blurb=b) for (c, d), (m, b) in
            _CARDS.items()]
    return types.SimpleNamespace(rows=rows)


def _rice_calls():
    return _pad(130, {
        51: _board_call("silver_psd", "beginning_stocks_mt", 58.5, "MMT", commodity="rough_rice_cbot",
                        country="India", routing="India state reserves",
                        series_short="carry-in stocks, all holders for India",
                        row_id="rough_rice_cbot|India_state_reserves|beginning_stock_region|rough_rice_cbot|India"),
        63: _board_call("silver_psd", "exports_mt", 25.0, "MMT", commodity="rough_rice_cbot", country="India",
                        routing="India export ban", series_short="exports for India",
                        row_id="rough_rice_cbot|India_export_ban|export|rough_rice_cbot|India"),
        130: _board_call("silver_psd", "ending_stocks_mt", 1.283, "MMT", commodity="rough_rice_cbot",
                         country="United States", routing="tenderable collapse",
                         series_short="ending stocks for United States",
                         row_id="rough_rice_cbot|tenderable_collapse|stock|rough_rice_cbot|United States"),
    })


# arm A rice, post-verify raw draft (the two FATAL sentences, verbatim)
RICE_N130 = ("A thinner buffer is what makes the response convex: with the stocks-to-use ratio at 27.31% versus "
             "35.56% a year earlier, the same size supply shock moves price more than it did last year, and "
             "deliverable US long-grain stocks at 1.28 MMT [N130] are the channel the model names for a thin "
             "contract detaching from cash.")
RICE_N63 = ("The fatter tail is on the export/policy side, while India's exportable supply sits at an "
            "all-time-wide 25 MMT [N63] -- an offsetting cap, not a confirmation.")
RICE_OK = ("The offsetting leg is real and same-market: India's carry-in stands at 58.5 MMT [N51], and Indian "
           "exports at 25 MMT [N63] are also near the top of their record.")


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# A-1 THE NOUN LICENCE
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_A1_the_rice_card_phrase_carrying_another_class_is_replaced_by_the_rows_printed_name():
    """RICE FATAL F-1: USDA PSD US ending stocks, ALL CLASSES, milled, printed as "deliverable US long-grain
    stocks" -- the tenderable_collapse card's own noun phrase. "long-grain" is a class the rice family's own
    sheets declare for ANOTHER class (silver_wasde `serves: long-grain rice`), so the card phrase is proven to
    name another thing; the whole phrase becomes the name the block printed for the row."""
    st = {"tldr": "", "mechanism": RICE_N130}
    cen = an._name_binding_lint(st, _rice_calls(), board=_rice_board())
    assert "and ending stocks for United States at 1.28 MMT [N130] are the channel" in st["mechanism"], st
    assert "deliverable" not in st["mechanism"] and "long-grain" not in st["mechanism"]
    assert cen.get("noun_corrected") == 1 and cen["routing_corrected"] == 0, cen
    # only the phrase moved: the handle, the digits and every other word stay
    assert st["mechanism"].replace("ending stocks for United States at 1.28",
                                   "deliverable US long-grain stocks at 1.28") == RICE_N130


def test_A1_indias_exports_named_by_the_routing_cards_supply_noun_is_the_rows_label():
    """RICE FATAL F-2: PSD India EXPORTS (a flow) printed as "India's exportable supply" -- an unlicensed noun
    phrase headed by the routing card's own noun ("... removing 40% of world supply"), in a span that never
    names the row. The run becomes the card's declared label; the writer's possessive and verb stay."""
    st = {"tldr": RICE_N63, "mechanism": ""}
    cen = an._name_binding_lint(st, _rice_calls(), board=_rice_board())
    assert "while India's exports sits at an all-time-wide 25 MMT [N63]" in st["tldr"], st
    assert cen.get("noun_corrected") == 1, cen


def test_A1_the_rows_own_words_and_a_paraphrase_are_left_as_written():
    """"India's carry-in" is the card's own desc ("carry-in stocks"); "Indian exports" names the row. No
    contradiction -> nothing moves, and the census keeps HEAD's shape (the noun keys ride only when non-zero)."""
    st = {"tldr": RICE_OK, "mechanism": ""}
    cen = an._name_binding_lint(st, _rice_calls(), board=_rice_board())
    assert st["tldr"] == RICE_OK
    assert "noun_corrected" not in cen and "noun_overlap_skipped" not in cen, cen


def test_A1_the_licence_is_read_off_the_cards_never_typed():
    """The licence's vocabularies are card declarations: the metric's label / desc, the family's class rule
    and the class qualifiers its sheets declare, the sibling LABELS whole, the routing node's card text."""
    calls = _rice_calls()
    from leviathan.graphrag import citations as cit
    L = an._noun_licence(calls[129], cit.call_identity(calls[129]), board=_rice_board())
    assert {"ending", "stocks", "carry", "milled", "classes"} <= set(L["licensed"]), L["licensed"]
    assert L["class"]["own"] == R.family_class_words("silver_psd", "rough_rice_cbot")      # the ONE producer
    assert ("long", "grain") in L["class"]["other"]
    assert ("production",) in L["siblings"] and ("ending", "stocks") not in L["siblings"]
    assert L["replacement"] == "ending stocks for United States" and L["label"] == "ending stocks"
    assert any("deliverable" in t for t in L["routing"])
    # a call that served no row licenses nothing
    assert not an._noun_licence(EMPTY, cit.call_identity(EMPTY))["licensed"]


def test_A1_the_causal_node_fallback_reads_the_curated_card_or_nothing():
    """board None (a replay): the routing node's mechanism / blurb come off its own curated card -- the card's
    text where the card is on disk, ("", "") where it is not; never a raise, never a guessed text."""
    got = an._nbl_causal_node("rough_rice_cbot", "tenderable_collapse")
    assert got in (("", ""), _CARDS[("rough_rice_cbot", "tenderable_collapse")]), got
    assert an._nbl_causal_node("no_such_contract", "x") == ("", "")


def test_A1_the_gates_G1_G2_and_the_compound_edge():
    """G1: a figure whose own tail names the row ("at the 16th percentile ...") reads nothing before it; G2: a
    span naming the row itself gets no CONCEPT (b) / KIND edit; a run cut inside the writer's own hyphenated
    compound is never replaced."""
    lic = {"licensed": frozenset({"exports", "india"}), "named": frozenset({"exports", "percentile"}),
           "routing": ("removing world supply",), "replacement": "exports for India", "label": "exports",
           "siblings": (("production",),), "class": {"own": "", "other": ()}, "basis": {"own": "", "other": ()}}
    s = "while the exportable supply sits at 25 MMT [N1]"
    noun = (0, s.index("25"))
    assert an._nbl_noun_edits(s, noun, lic)                                      # fires
    t = s.replace("25 MMT", "25th percentile of its own record")
    assert an._nbl_noun_edits(t, noun, lic, tail=(t.index("25") + 2, t.index("[N1]"))) == []   # G1
    u = "while the exportable supply of exports sits at 25 MMT [N1]"
    assert an._nbl_noun_edits(u, (0, u.index("25")), lic) == []                 # G2
    v = "while the dry-supply sits at 25 MMT [N1]"
    assert an._nbl_compound_edge(v, v.index("supply"), v.index("supply") + len("supply"))


def test_A1_a_card_phrase_without_a_contradiction_inside_is_the_row_paraphrased():
    """"a record Brazilian export line at 118 MMT [N54]" over Brazil's PSD exports, routed by the Brazil export
    tax card ("Periodic Brazilian export levy/registration changes reduce exportable supply ..."): the card's
    phrase with no class / basis / kind contradiction inside it is the row paraphrased, and is left."""
    rid = "soybeans_cbot|Brazil_export_tax|export|soybeans_cbot|Brazil"
    calls = _pad(54, {54: _board_call("silver_psd", "exports_mt", 118.0, "MMT", commodity="soybeans_cbot",
                                      country="Brazil", routing="Brazil export tax",
                                      series_short="exports for Brazil", row_id=rid)})
    board = types.SimpleNamespace(rows=[types.SimpleNamespace(
        contract="soybeans_cbot", driver_id="Brazil_export_tax",
        mechanism=("Periodic Brazilian export levy/registration changes reduce exportable supply, firming "
                   "global FOB and supporting CBOT."),
        blurb="Brazilian export levies reduce supply, raising global prices and supporting CBOT futures.")])
    text = "alongside a record Brazilian export line at 118 MMT [N54] and a crowd at the top of its record."
    st = {"tldr": text, "mechanism": ""}
    cen = an._name_binding_lint(st, calls, board=board)
    assert st["tldr"] == text and "noun_corrected" not in cen, (st, cen)


def test_A1_corrections_one_to_four_win_an_overlap_and_the_skip_is_counted():
    cen: dict = {}
    kept = an._nbl_free_noun_edits([(10, 20, "x", "routing_corrected")],
                                   [(15, 25, "y", "noun_corrected"), (30, 35, "z", "noun_corrected")], cen)
    assert kept == [(30, 35, "z", "noun_corrected")] and cen == {"noun_overlap_skipped": 1}


def test_A1_no_domain_noun_is_typed_in_the_licence():
    """THE REJECTED LEXICAL FORM, pinned at source: no string constant in the licence's code names a domain
    noun (the docstrings may quote the measured defect; the code may not act on a word)."""
    banned = {"deliverable", "exportable", "supply", "long-grain", "long", "grain", "tenderable", "surplus"}
    for fn in (an._noun_licence, an._nbl_noun_edits, an._nbl_family_class_vocab, an._nbl_routing_texts,
               an._nbl_trailing_end, an._nbl_sentence_start):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        first = tree.body[0].body[0]
        doc = first.value if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)) else None
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node is not doc:
                words = set(re.findall(r"[a-z-]+", node.value.lower()))
                assert not (words & banned), (fn.__name__, node.value)


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# A-2 THE TRAILING RUN AND THE MARKUP-AWARE CAPITAL
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
DEEP_N119 = ("**The crush demand-pull leg.** Crude oil against its own five-year record reads 0.51 z, August "
             "2026 [N119]; the model expects it to lift the board crush margin, and the readings agree.")


def _brent_calls():
    return _pad(119, {119: _board_call(
        "silver_pink_sheet", "brent_crude_usd_bbl_zscore_5yr", 0.5072943423080404, "z", commodity="_global",
        period="2026-08-01", routing="crude oil", known="2026-09-10",
        series_short="the Brent crude price against its own five-year record",
        row_id="soybeans_cbot|crude_oil|brent_crude_z|_global|")})


def test_A2_the_writers_copy_of_the_printed_basis_is_absorbed_and_the_head_takes_its_capital():
    """deep:12 (D10): HEAD printed "the Brent crude price against its own five-year record against its own
    five-year record reads", lower-case after the bold head. One printed name, one capital."""
    st = {"tldr": "", "mechanism": DEEP_N119}
    cen = an._name_binding_lint(st, _brent_calls())
    assert st["mechanism"].startswith("**The crush demand-pull leg.** The Brent crude price against its own "
                                      "five-year record reads 0.51 z, August 2026 [N119];"), st["mechanism"]
    assert st["mechanism"].count("against its own five-year record") == 1
    assert cen["routing_corrected"] == 1, cen


def test_A2_the_trailing_run_must_close_the_printed_name_and_be_a_run():
    short = "the Brent crude price against its own five-year record"
    s = "Crude oil against its own five-year record reads 0.51 z"
    e = s.index(" against")
    assert an._nbl_trailing_end(s, e, s.index("0.51"), short) == s.index(" reads")
    t = "Crude oil record highs at 95"                      # one shared word is no copy of the name
    assert an._nbl_trailing_end(t, t.index(" record"), t.index("95"), short) == t.index(" record")
    u = "Crude oil against its own five-year highs at 95"   # a run that stops short of the name's end
    assert an._nbl_trailing_end(u, u.index(" against"), u.index("95"), short) == u.index(" against")


def test_A2_the_capital_is_read_through_the_markup():
    s = "**The crush demand-pull leg.** crude"
    assert an._nbl_sentence_start(s, s.index("crude")) is True
    s = "**Crude:** crude"
    assert an._nbl_sentence_start(s, s.index("crude", 3)) is False               # a bold label and a colon
    assert an._nbl_sentence_start("- crude", 2) is True                             # HEAD's arm, kept
    assert an._nbl_sentence_start("the view on crude", 12) is False


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# A-3 THE BACKSTOP'S GUARD OVER ADDRESSED LINKS (+ P11)
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
def _chain(contract, terminal, ids, rank=1):
    hops = tuple(types.SimpleNamespace(contract=contract, driver_id=i, key=(contract, i)) for i in ids)
    return types.SimpleNamespace(contract=contract, terminal=terminal, hops=hops, rank=rank, rendered=True)


def _backstop_board():
    c1 = _chain("cotton", "rough_rice_cbot", ("El_Nino", "IOD_positive", "drought"), rank=1)
    c2 = _chain("corn_cbot", "cotton", ("export_pace", "ending_stocks_su_ratio"), rank=2)
    rows = ({"role": "chain", "rank": 1, "line": "CHAIN"},
            {"role": "chain_document", "rank": 1, "hop_index": 2, "line": "  the document [E36]"},
            {"role": "chain_receipt", "rank": 2, "hop_index": 0, "line": "  receipt [E7][E9]"},
            {"role": "chain_receipt", "rank": 2, "line": "  receipt with no hop [E11]"})
    return types.SimpleNamespace(chains=[c1, c2], rendered_rows=rows, rows=[], anchor_slugs=("cotton",))


def test_A3_the_hop_receipts_are_the_blocks_own_E_addresses_by_rank_and_hop():
    bd = _backstop_board()
    assert an._chain_hop_receipts(bd, bd.chains) == [[(), (), (36,)], [(7, 9), ()]]
    assert an._chain_hop_receipts(types.SimpleNamespace(), bd.chains) == [[(), (), ()], [(), ()]]


def test_A3_guard_three_withholds_on_either_reading_and_threads_the_addressed_inputs(monkeypatch):
    seen: dict = {}

    def any_order(ch, sents, hop_handles=None, **kw):
        seen.setdefault("any", []).append(kw)
        return False

    def adjacent(ch, sents, hop_handles=None, *, page_markets=(), hop_receipts=None, peer_chains=()):
        seen.setdefault("adj", []).append({"receipts": hop_receipts, "peers": peer_chains,
                                           "markets": page_markets})
        return ch.contract == "corn_cbot"                          # the second chain was told in order
    monkeypatch.setattr(R, "chain_referenced_in", any_order)
    monkeypatch.setattr(R, "chain_referenced_adjacent_in", adjacent)
    monkeypatch.setattr(R, "chain_page_sentence", lambda ch, rh, **kw: "One chain the data carries runs x.")
    bd = _backstop_board()
    st = {"tldr": "", "mechanism": "The writer's words."}
    cen = an._chain_backstop(st, bd, [], coverage={"chain_referenced_adjacent": 0}, row_handles={},
                             page_markets=("cotton",))
    assert not cen["backstop_appended"] and st["mechanism"] == "The writer's words."
    assert seen["any"] == [{}, {}]                                   # HEAD's any-order call shape, kept
    assert [x["receipts"] for x in seen["adj"]] == [[(), (), (36,)], [(7, 9), ()]]
    assert all(tuple(x["peers"]) == tuple(bd.chains) and x["markets"] == ("cotton",) for x in seen["adj"])


def test_A3_a_render_without_the_P3_kwarg_gets_HEADs_guard_exactly(monkeypatch):
    calls: list = []
    monkeypatch.setattr(R, "chain_referenced_in", lambda ch, sents, hop_handles=None: calls.append(1) or False)
    monkeypatch.setattr(R, "chain_referenced_adjacent_in",
                        lambda ch, sents, hop_handles=None, *, page_markets=(): pytest.fail("not HEAD's guard"))
    monkeypatch.setattr(R, "chain_page_sentence", lambda ch, rh: "One chain the data carries runs x.")
    bd = _backstop_board()
    st = {"tldr": "", "mechanism": "The writer's words."}
    cen = an._chain_backstop(st, bd, [], coverage={"chain_referenced_adjacent": 0}, row_handles={},
                             page_markets=("cotton",))
    assert cen["backstop_appended"] == 1 and len(calls) == 2
    assert st["mechanism"].endswith("One chain the data carries runs x.")


def test_P11_the_prose_cited_handles_reach_the_board_sentence_only_where_declared(monkeypatch):
    got: dict = {}
    monkeypatch.setattr(R, "chain_referenced_in", lambda *a, **k: False)
    monkeypatch.setattr(R, "chain_referenced_adjacent_in", lambda *a, **k: False)

    def sentence(ch, rh, *, page_markets=(), cited=()):
        got["cited"] = cited
        return "One chain the data carries runs x."
    monkeypatch.setattr(R, "chain_page_sentence", sentence)
    bd = _backstop_board()
    st = {"tldr": "Stocks at 5.67 % [N46], the 1st percentile [N48].", "mechanism": "Crush [N12][N14]."}
    an._chain_backstop(st, bd, [], coverage={"chain_referenced_adjacent": 0}, row_handles={},
                       page_markets=("cotton",))
    assert got["cited"] == (12, 14, 46, 48)


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# A-4 THE RECORD EXTREME'S OWN WORDS (the mandate half)
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_A4_the_clause_ships_only_with_the_blocks_handles_and_only_on_a_board_turn():
    h = ("[N14]", "[N15]", "[N16]")
    base = an._system(state_board=True)
    assert an._system(state_board=True, positioning_asymmetry=h) == \
        base + " " + N.positioning_asymmetry_mandate(h)
    assert an._system(positioning_asymmetry=h) == an._system()                    # board-less: invisible
    assert an._system(state_board=True, positioning_asymmetry=()) == base         # no line printed: nothing
    assert list(inspect.signature(an._system).parameters)[-1] == "positioning_asymmetry"


def test_A4_the_gate_reads_the_lead_R_prints_and_nothing_else(monkeypatch):
    lead = "at the end of its own record, and the positioning card reads an extreme position this way:"
    block = ("STATE OF THE WORLD\n"
             "- [N14] managed-money net position ...: -126,674 contracts, -3.4 sigma [N15], 0th percentile "
             "[N16], %s Large managed-money net length amplifies and can overextend price moves, while extreme "
             "positioning flags reversal risk\n- [N20] other row [N21]\n" % lead)
    monkeypatch.setattr(R, "POSITIONING_ASYMMETRY_LEAD", lead, raising=False)
    assert an._positioning_asymmetry_printed(block) == ("[N14]", "[N15]", "[N16]")
    assert an._positioning_asymmetry_printed(block.replace(lead, "")) == ()
    monkeypatch.setattr(R, "POSITIONING_ASYMMETRY_LEAD", "", raising=False)
    assert an._positioning_asymmetry_printed(block) == ()                        # no producer word, no clause


def test_A4_the_mandate_carries_no_figure_no_direction_and_is_graded_as_it_ships():
    lit = N.positioning_asymmetry_mandate(("[N14]",))
    assert not re.findall(r"\d", re.sub(r"\[N\d+\]", "", lit)), lit
    assert N.positioning_asymmetry_mandate(()) == ""
    assert "{handles}" in N.MANDATE_POSITIONING_ASYMMETRY
    assert N.check_literals() == []


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# A-5 THE CHAIN PARAGRAPH'S SUBJECT
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
_ORDER = "Make a market or a reading the subject of every sentence here"


def test_A5_the_chain_movement_names_its_subject_once_and_the_flag_off_mandate_is_heads():
    for kw in ({"chain": True}, {"chain": True, "nonobvious": True}, {"chain": True, "desk": True}):
        assert N.state_board_mandate(**kw).count(_ORDER) == 1, kw
    assert "never this page itself" in N.state_board_mandate(chain=True, desk=True)
    for kw in ({}, {"nonobvious": True}, {"desk": True}):
        assert _ORDER not in N.state_board_mandate(**kw), kw
    assert N.state_board_mandate() is N.SYSTEM_STATE_BOARD_MANDATE
    # the count line keeps its one plain clause (A5-c)
    assert "give it one plain clause" in N.MANDATE_CHAIN_MOVEMENT
    assert N.check_literals() == []
