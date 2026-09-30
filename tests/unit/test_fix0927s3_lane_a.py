"""THE 09-27 FIX SITTING 3, LANE A -- answer.py + state/narration.py (CONTRACT Z1 / Z2 / Z3 / Z4 / Z16 / Z20).

U-12  REQUIRED LINES BECOME REQUIRED FACTS: every clause the board-turn mandates ship is DECLARED once
      (`narration.MANDATE_FACTS` / `MANDATE_RULES`) and the literals are COMPOSED from them; no clause says
      "exactly as"; the census (`narration.mandate_census`) counts words, sentences, asks, facts required, rules
      and the words no declared clause covers, and rides `writer_seam.mandate_census`; the ceiling is DERIVED
      (asks <= facts required + rules; 0 undeclared words; fewer words than HEAD on the same cell); the three
      append seams (L1, the absence append, the chain backstop) are withheld where the page already carries the
      fact by its ledger address or a whole name (`answer._fact_told`), and every withhold is COUNTED.
U-5   THE METRIC'S NAME WINS OVER A PART ITS CARD DECLARES INSIDE IT ("Corn's ethanol-channel use, 176.66 MMT"
      over food, seed and industrial use), the noun span read across the ONE separator before the figure.
U-7   THE CALL'S NETTING FACTS: the ASKED SIDES line's printed netting parts, each by handle, and one question.
S2    V-4 (the balanced choice reads the line's own counts), V-2 (the absence correction speaks the book's reader
      words), M-3 (the numbers ledger at the seam's call site), U-10 seam half (name corrections through the one
      splice producer).

Every pin is offline and $0, on the shipped cards, conventions and producers, the fixture board, and the arm-A
pages' own measured sentences.
"""
from __future__ import annotations

import inspect
import itertools
import pathlib
import re

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import register as REG
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R

SRC = pathlib.Path(an.__file__).resolve().parent
W = re.compile(r"[A-Za-z][A-Za-z'-]*")

#: HEAD 26618aa0's board-turn mandate WORDS per cell (nonobvious, chain, desk, tldr, balanced), the watch
#: selection clause (lane AN's constant, a foreign part) excluded -- MEASURED by B48
#: (`fix_sitting_3_0927/a_work/drive_b48_dump.py` over head_s3, `b48_head.json`), never typed as a ceiling:
#: the pin reads the tree's census on the SAME cell and asks only that it be smaller.
HEAD_WORDS = {(0, 0, 0, 0, 0): 1110, (0, 0, 0, 1, 0): 1411, (0, 0, 0, 1, 1): 1408, (0, 0, 1, 0, 0): 2046,
              (0, 0, 1, 1, 0): 2347, (0, 0, 1, 1, 1): 2344, (0, 1, 0, 0, 0): 1610, (0, 1, 0, 1, 0): 1911,
              (0, 1, 0, 1, 1): 1908, (0, 1, 1, 0, 0): 2558, (0, 1, 1, 1, 0): 2859, (0, 1, 1, 1, 1): 2856,
              (1, 0, 0, 0, 0): 1191, (1, 0, 0, 1, 0): 1492, (1, 0, 0, 1, 1): 1489, (1, 0, 1, 0, 0): 2129,
              (1, 0, 1, 1, 0): 2430, (1, 0, 1, 1, 1): 2427, (1, 1, 0, 0, 0): 1691, (1, 1, 0, 1, 0): 1992,
              (1, 1, 0, 1, 1): 1989, (1, 1, 1, 0, 0): 2641, (1, 1, 1, 1, 0): 2942, (1, 1, 1, 1, 1): 2939}
NETTING = {"opposing": ("[N5]",), "event": ("[E3]",), "tape": ("[N9]",)}


def _legs(nob, chain, desk, tldr, bal, net=False):
    return an._mandate_parts(state_board=True, prose_mode=None, watch_selection=bool(nob), state_chain=bool(chain),
                             desk_register=bool(desk), ask_head=(("[N11]", "[N14]") if tldr else ()),
                             horizon_row=bool(tldr), positioning_asymmetry=(("[N15]",) if tldr else ()),
                             ask_sides=(("[N21]",) if tldr else ()), ask_sides_balanced=bool(bal),
                             ask_netting=(NETTING if net else ()))


def _cells():
    for nob, chain, desk, tldr, bal in itertools.product((0, 1), (0, 1), (0, 1), (0, 1), (0, 1)):
        if bal and not tldr:
            continue
        yield (nob, chain, desk, tldr, bal)


# ═══ U-12 (a)(b) -- THE MANDATE AS DECLARED FACTS, AND ITS CENSUS ════════════════════════════════════════════
def test_U12_every_clause_is_declared_once_with_what_it_rides_or_protects():
    keys = [k for k, _h, _c in N.MANDATE_FACTS + N.MANDATE_RULES]
    assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]
    for k, h, c in N.MANDATE_FACTS + N.MANDATE_RULES:
        assert str(h).strip() and str(c).strip(), k
        c.encode("ascii")
    # every declared clause is composed into at least one literal a board turn can ship (no orphan clause)
    shipped = " ".join(t for cell in _cells() for _n, t in _legs(*cell, net=True))
    shipped += an._system_writer_seam_mandate("quick").replace(an._WRITER_SEAM_NO_CUT, an._WRITER_SEAM_CUT)
    orphans = [k for k, _h, c in N.MANDATE_FACTS + N.MANDATE_RULES if not N._clause_rx(c).search(shipped)]
    assert orphans == [], orphans
    assert N.check_literals() == []


def test_U12_no_mandate_clause_and_no_treatment_literal_says_exactly_as():
    """THE OWNER'S PIN: a required LINE was spelled "state each of them exactly as printed" (five of them on the
    widest board cell). Scoped as CONTRACT Z1 scopes it -- every literal that ships ONLY under a treatment flag:
    the narration mandates, `_SYSTEM_WRITER_SEAM`, the `_*_DESK` persona variants. The flag-off persona literals
    are COUNTED and left (OWNER DECISION O-S3-4): a flag-off prompt byte is the owner's to move."""
    for k, _h, c in N.MANDATE_FACTS + N.MANDATE_RULES:
        assert not re.search(r"exactly as", c, re.I), k
    for cell in _cells():
        for name, text in _legs(*cell, net=True):
            assert not re.search(r"exactly as", text, re.I), (cell, name)
    for lit in (an._SYSTEM_WRITER_SEAM, an._SYSTEM_CASCADE_WALK_DESK, an._SYSTEM_CASCADE_WALK_MANDATE_DESK,
                an._SYSTEM_CASCADE_CONTEXT_DESK, an._SYSTEM_CASCADE_DEEP_DESK, an._SYSTEM_CASCADE_XCCY_DESK,
                N.desk_register_mandate(), N.desk_register_mandate(state_board=True)):
        assert not re.search(r"exactly as", lit, re.I), lit[:80]
    # O-S3-4: the flag-off twins keep HEAD's words (counted, not edited)
    assert len(re.findall(r"exactly as", an._SYSTEM_CASCADE_WALK_MANDATE)) == 4
    assert an._cascade_literal(an._SYSTEM_CASCADE_WALK_MANDATE, False) is an._SYSTEM_CASCADE_WALK_MANDATE


@pytest.mark.parametrize("cell", list(_cells()))
def test_U12_the_census_ceiling_is_derived_from_the_facts_required(cell):
    """On every board flag cell: every ask is a declared clause (asks <= facts required + rules, and 0 words
    outside a declared clause, a movement enumerator or the book's panel sentence), no "exactly as", and fewer
    words than HEAD's own mandates on the same cell (B48's measurement, the watch clause excluded as foreign)."""
    for net in (False, True):
        if net and not cell[3]:
            continue
        legs = _legs(*cell, net=net)
        c = an._mandate_census(legs)
        assert c["asks"] <= c["facts_required"] + c["rules"], c
        assert c["undeclared_words"] == 0, c
        assert c["exactly_as"] == 0
        assert c["words"] - c["foreign_words"] < HEAD_WORDS[cell], (cell, net, c["words"], c["foreign_words"])
        assert set(c["by_part"]) == {n for n, _t in legs}


def test_U12_an_undeclared_imperative_is_a_number_not_a_hope():
    """The census BITES: a sentence added outside the two tuples is counted as undeclared words."""
    legs = _legs(1, 1, 1, 1, 0)
    base = an._mandate_census(legs)
    bad = [(n, t + (" Always restate the block line by line." if n == "state_board_mandate" else ""))
           for n, t in legs]
    worse = an._mandate_census(bad)
    assert worse["undeclared_words"] == base["undeclared_words"] + 7
    assert N.mandate_census({"x": "Copy the recency line exactly as printed."})["exactly_as"] == 1


def test_U12_mandate_parts_is_the_one_producer_of_the_board_legs_system_appends():
    for cell in _cells():
        nob, chain, desk, tldr, bal = cell
        legs = _legs(*cell)
        sysp = an._system(state_board=True, watch_selection=bool(nob), state_chain=bool(chain),
                          desk_register=bool(desk), ask_head=(("[N11]", "[N14]") if tldr else ()),
                          horizon_row=bool(tldr), positioning_asymmetry=(("[N15]",) if tldr else ()),
                          ask_sides=(("[N21]",) if tldr else ()), ask_sides_balanced=bool(bal))
        assert "".join(t for _n, t in legs) in sysp, cell
    # nothing lit -> nothing emitted -> `_system` is HEAD's object (the `is` pins)
    assert an._mandate_parts() == [] and an._mandate_census([]) is None
    assert an._system(state_board=False) == an._system()


def test_U12_the_panel_sentence_is_the_books_and_rides_the_board_leg_only():
    """U-12 (b): the block is the PANEL the writer reads, not the text it prints -- ONE declaration (lane R's
    `panel_words.mandate`, CONTRACT Z9), read by the mandate and never typed in narration.py."""
    panel = R.book_words("panel_words", "mandate")
    legs = dict(_legs(0, 0, 0, 0, 0))
    # MOVED 09-29 (fix sitting 4, lane A, A4-4 panel reach / CONTRACT C4-17 -- declared): the leg ships the book
    # sentence's DECLARATION (up to its own clause separator); its use-or-say-why-not half is `facts_owed`'s, scoped to
    # the mandate's facts. The claim kept: the sentence is the BOOK's, read by the mandate, never typed in narration.
    decl = (panel.split(": ", 1)[0].rstrip(" ,;") + ".") if (panel and ": " in panel) else panel
    if panel:
        assert legs["panel"].strip() == decl
        assert decl not in (SRC / "state" / "narration.py").read_text(encoding="utf-8")
        assert decl not in an._system() and decl not in an._system(desk_register=True)
    else:
        assert "panel" not in legs                   # the producer not landed: no sentence, never a typed copy
    assert N.panel_mandate() == decl.strip()


def test_U12_the_census_rides_writer_seam_and_no_trace_key_moves():
    from leviathan.graphrag import tracekeys as TK
    assert "mandate_census" not in TK.TRACE_RECORD_KEYS
    src = inspect.getsource(an._answer_l2)
    assert 'sg.trace["writer_seam"]["mandate_census"] = _mcensus' in src
    # the census is computed through the SAME producer `_system` appends from
    assert "_mandate_census(_mandate_parts(" in src


def test_U12_the_facts_HEAD_required_are_each_asked_for_by_a_clause():
    """THE FACT-COVERAGE MAP (B48), its tree half: every fact HEAD's mandates required is named by a declared
    clause that ships on the cell HEAD shipped it on (the HEAD half -- each needle found in HEAD's own text -- is
    the drive's, over head_s3)."""
    fact_cells = {"direction_read": (0, 0, 0, 0, 0), "shock_or_mechanism": (0, 0, 0, 0, 0),
                  "driver_figures": (0, 0, 0, 0, 0), "like_state_outcome": (0, 0, 0, 0, 0),
                  "recency_layers": (0, 0, 0, 0, 0), "spillover_signs": (0, 0, 0, 0, 0),
                  "cross_commodity_markets": (0, 0, 0, 0, 0), "watch_items": (0, 0, 0, 0, 0),
                  "absence_reason": (0, 0, 0, 0, 0), "watch_forward": (1, 0, 0, 0, 0),
                  "watch_weighed_left": (1, 0, 0, 0, 0),
                  "chain_links": (0, 1, 0, 0, 0), "chain_link_facts": (0, 1, 0, 0, 0),
                  "chain_receipt": (0, 1, 0, 0, 0), "chain_history": (0, 1, 0, 0, 0), "pair_call": (0, 1, 0, 0, 0),
                  "chain_count": (0, 1, 0, 0, 0), "one_line_chain": (0, 1, 0, 0, 0), "chain_scope": (0, 1, 0, 0, 0),
                  "like_state_chain": (0, 1, 0, 0, 0), "ask_figures": (0, 0, 0, 1, 0),
                  "horizon_range": (0, 0, 0, 1, 0), "positioning_reading": (0, 0, 0, 1, 0),
                  "ask_call": (0, 0, 0, 1, 0), "ask_call_balanced": (0, 0, 0, 1, 1),
                  "watch_four_facts": (0, 0, 0, 0, 0), "cross_market_hypothesis": (0, 0, 0, 0, 0),
                  "decline_record": (0, 0, 0, 0, 0), "pattern_conditions": (0, 0, 1, 0, 0)}
    rule_cells = {"headings": (0, 0, 0, 0, 0), "cross_commodity_scope": (0, 0, 0, 0, 0),
                  "cross_commodity_su": (0, 0, 0, 0, 0), "projection": (0, 0, 0, 0, 0), "base_rates": (0, 0, 0, 0, 0),
                  "no_then_now": (0, 0, 0, 0, 0), "chain_selection": (0, 1, 0, 0, 0), "no_restate": (0, 1, 0, 0, 0),
                  "length": (0, 0, 0, 0, 0), "no_cut": (0, 0, 0, 0, 0), "tldr_consistency": (0, 0, 0, 0, 0),
                  "register_ban": (0, 0, 1, 0, 0), "register_exempt": (0, 0, 1, 0, 0),
                  "register_handles": (0, 0, 1, 0, 0), "date_spelling": (0, 0, 1, 0, 0),
                  "register_recency": (0, 0, 1, 0, 0),
                  # MOVED 09-29 (fix sitting 4, lane A, A4-3 / CONTRACT C4-17 -- declared): `scheduled_prints` is a
                  # RULE now (it protects the watch draw's ban; no sentence is owed), shipped on the SAME cell
                  "scheduled_prints": (1, 0, 0, 0, 0)}
    for key, cell in fact_cells.items():
        assert key in N.mandate_asks(dict(_legs(*cell)))["facts"], key
    for key, cell in rule_cells.items():
        assert key in N.mandate_asks(dict(_legs(*cell)))["rules"], key


def test_U12_the_facts_stay_required_and_figures_stay_the_rows_own():
    """Threats A12-a / A12-b / A12-c: 'in your own words' never makes a fact optional (use-or-say-why-not rides
    every board turn), the figure law survives the loss of "exactly as" (a figure as its row prints it, with its
    handle, never computed), and the chain count / recency dates are served facts, never the writer's arithmetic."""
    m = N.state_board_mandate(nonobvious=True, chain=True, desk=True)
    assert N._CLAUSE["facts_owed"] in m
    assert "or say in one clause why you leave it out" in m
    assert "never from a figure you compute" in m
    assert "in DIGITS as printed" in an._SYSTEM_CASCADE_WALK_MANDATE_DESK
    assert "the number of further chains it counts" in m and "as it prints it" not in m
    assert "give each layer its own plain sentence" not in m and "own plain sentence" not in N.SYSTEM_STATE_BOARD_MANDATE
    # the two TEMPLATES the writer seam handed the writer to copy are gone; the facts they carried stay
    ws = an._system_writer_seam_mandate("deep")
    assert "'our price history for that market does not reach that window'" not in ws
    assert "substitutes should move in opposite directions; both rose" not in ws
    assert "what we hold and from when" in ws and "the declared relation with its sign" in ws


def test_U12d_the_desk_register_keeps_its_token_ban_and_drops_its_phrasing_rules():
    m = N.desk_register_mandate()
    assert REG.desk_register_table() in m                   # the TOKEN ban, one producer with the lint
    for gone in ("Where two listings are in play", "on each board", "THAT IS A RULE ABOUT SCORING MACHINERY",
                 "Everything else the blocks name", "the crush margin is wide and the meal basis is firm"):
        assert gone not in m, gone
    for kept in ("The ban leaves the market's own names alone", "never as in force or met",
                 "never the year, the month and the day run together",
                 "A changed word never moves a citation handle or changes a figure"):
        assert kept in m, kept
    board = N.desk_register_mandate(state_board=True)
    assert "RECENCY" in board and "board price tape" in board and "RECENCY" not in m
    assert "the sentence you are told to write" not in board
    assert len(W.findall(m)) < 588 + len(W.findall(REG.desk_register_table()))   # HEAD's 588 beside its table


# ═══ U-12 (c) -- THE APPEND SEAMS FIRE ONLY ON AN UNTOLD FACT ════════════════════════════════════════════════
def test_U12c_fact_told_reads_addresses_and_whole_names_never_a_token():
    assert an._fact_told("the ratio [N12] is tight", handles=(12,))
    assert an._fact_told("both [N12, N14] read low", handles=("N14",))
    assert an._fact_told("both [N12-14] read low", handles=("[N13]",))
    assert an._fact_told("dated 2018 [E3].", handles=("[E3]",))
    assert not an._fact_told("dated 2018 [E3].", handles=(3,))            # an [N3] is not the [E3]
    assert an._fact_told("through rubber area substitution", names=("Rubber-Area Substitution",))   # N-L1 joint
    # a single word of a whole name is never the name (sitting 1 M1's rejected form)
    assert not an._fact_told("the Indian monsoon was weak", names=("Indian Ocean dipole",))
    assert not an._fact_told("", handles=(1,)) and not an._fact_told("x", handles=(), names=())
    assert an._fact_told("stocks at 0.117 S/U ratio in May", names=("0.117 S/U ratio",))


def test_U12c_the_absence_append_is_withheld_where_the_page_carries_the_reading():
    ex = {"query": {"table": "silver_psd", "metric": "exports", "commodity": "soybeans_cbot",
                    "country": "Argentina", "period": "MY2026", "asof": "2026-09-16"},
          "rows": [{"value": 6.45, "unit": "MMT", "knowledge_date": "2026-09-11",
                    "routing": "Argentine selling incentives"}], "status": "ok",
          "_row_id": "soybeans_cbot|Argentine_selling_incentives|psd_exports|soybeans_cbot|AR", "_sb": True,
          "routing": "Argentine selling incentives"}
    calls = [None] * 47 + [ex]
    rows = an._seam_row_index(calls)
    sent = ("The supply-glut pattern needs three of its five drivers, and two of its legs (Argentine selling "
            "incentives, the dollar) have no series this page could read.")
    # HEAD's append, where the page does not carry the reading
    d = {"tldr": "", "mechanism": sent}
    c = an._seam_absence_claims(d, rows, number_calls=calls)
    assert c["absence_rows_appended"] == 1 and "append_withheld_told" not in c
    # the page already carries [N48] elsewhere -> withheld and COUNTED; the claim is left as written
    d2 = {"tldr": "Argentine exports stand at 6.45 MMT [N48].", "mechanism": sent}
    c2 = an._seam_absence_claims(d2, rows, number_calls=calls)
    assert c2["absence_rows_appended"] == 0 and c2["append_withheld_told"] == 1, c2
    assert d2["mechanism"] == sent
    # ...or its printed figure, the reading's whole printed name
    d3 = {"tldr": "Argentine exports stand at 6.45 MMT.", "mechanism": sent}
    assert an._seam_absence_claims(d3, rows, number_calls=calls)["append_withheld_told"] == 1


def test_U12c_the_backstop_counts_the_withhold_the_chains_own_addresses_decide():
    st = {"tldr": "", "mechanism": "x"}
    c = an._chain_backstop(st, None, [], coverage={"chain_referenced_adjacent": 1})
    assert c == {"backstop_appended": 0, "backstop_withheld": 0, "append_withheld_told": 1}
    assert an._chain_backstop(st, None, [], coverage={"chain_referenced_adjacent": 0}) == \
        {"backstop_appended": 0, "backstop_withheld": 0}
    # the LINK-level told test is lane R's producers', read and never re-implemented here
    src = inspect.getsource(an._chain_backstop)
    assert "chain_referenced_in" in src and "chain_referenced_adjacent_in" in src


@pytest.fixture(scope="module")
def chain_cell():
    from leviathan.graphrag import graph as G
    from leviathan.graphrag.numbers import cascade as CAS
    from leviathan.graphrag.state import __main__ as H
    from leviathan.graphrag.state import analogs as A
    from leviathan.graphrag.state import board as B
    from leviathan.graphrag.state import walk as WK
    from leviathan.graphrag.state import watch as WA
    asof = "2026-09-16"
    q = "what is the situation on soybeans now? how is it looking 3 months from now?"
    graph = G.CausalGraph(G.load_contracts(), silver=set(), version="deck")
    curated = list(CAS.load_chain_map()) + list(CAS.load_transmission_map())
    bd = WK.walk(graph=graph, asof=asof, mode="max", anchors=WK.resolve_anchors(named=("soybeans_cbot",)),
                 question=q, state_fn=H.fixture_state_fn(asof), key_fn=None, receipts={},
                 knobs=B.board_knobs_of("max"), width=2, legb_on=False, stage2=False)
    tape = {slug: H.fixture_tape(slug, asof) for slug in bd.anchor_slugs}
    WK.stage2(bd, graph, state_fn=H.fixture_state_fn(asof), receipts={}, width=2, legb_on=False,
              chains=curated, state_chain=True)
    R.attach_tape(bd, tape, reads_each=0)
    ana = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn(), receipt_fn=None)
    A.analog_leg(bd, ana)
    wr = WA.watch_rows(bd, analogs=ana)
    WA.watch_leg(bd, wr)
    rec = N.recency_rows(bd, tape_edge=next((t.level_date for t in tape.values() if t.level_date), ""))
    blk = R.render_board(bd, analogs=ana, watch=wr, recency=rec, age_clauses={}, chain_receipts=None,
                         anchor_label=", ".join(R.board_label(s) for s in bd.anchor_slugs))
    return bd, list(blk.calls)


#: DESIGN B.6's first named target sentence, verbatim from the 2026-09-16 served deep note (test_chain_lints T1)
T1 = ("This is the single clearest counterweight to the tight-balance read, and the model places it "
      "one hop upstream of both the stocks-to-use ratio and the WASDE revision that re-prices the sheet.")


def test_U12c_L1_appends_a_reading_only_where_the_page_does_not_carry_it(chain_cell):
    bd, calls = chain_cell
    hop = next(h for h in an._chain_hop_rows(bd, calls) if "the stocks to use ratio" in h["names"])
    st = {"tldr": "", "mechanism": T1}
    c = an._chain_lints(st, calls, bd)
    assert c["corrected"] == 1 and "append_withheld_told" not in c          # HEAD's L1, where untold
    told = {"tldr": "The balance is tight: %s [N%d]." % (hop["figure"], hop["n"]), "mechanism": T1}
    c2 = an._chain_lints(told, calls, bd)
    assert c2.get("append_withheld_told") == 1 and c2["corrected"] == 0, c2
    assert told["mechanism"] == T1                                          # nothing appended, nothing cut
    # the hop's NAME alone never tells its reading: the name is what made the sentence a chain sentence
    named = {"tldr": "The stocks-to-use ratio matters here.", "mechanism": T1}
    assert an._chain_lints(named, calls, bd)["corrected"] == 1


# ═══ U-5 -- THE METRIC'S NAME WINS OVER A PART ITS CARD DECLARES INSIDE IT ═══════════════════════════════════
def _fsi_call(value=176.665):
    basis = "food, seed and industrial use -- any ethanol grind is inside it and is not separable"
    return {"query": {"table": "silver_psd_attributes", "metric": "FSI Consumption", "country": "United States",
                      "commodity": "corn_cbot", "period": "2026", "asof": "2026-09-26"},
            "rows": [{"value": value, "unit": "MMT", "knowledge_date": "2026-09-11", "stat": "level",
                      "routing": "ethanol demand", "series_short": "food, seed and industrial use for United States",
                      "commodity_words": "", "basis": basis, "axis_scope": "United States"}],
            "status": "ok", "_row_id": "corn_cbot|ethanol_demand|psd_fsi_use|corn_cbot|United States",
            "_sb": True, "routing": "ethanol demand"}


def _lint(text, calls):
    st = {"tldr": "", "mechanism": text}
    cen = an._name_binding_lint(st, calls, board=None, served_scalars=[], asof="2026-09-26")
    return st["mechanism"], cen


def test_U5_the_tariff_sentence_is_corrected_to_the_metrics_own_name():
    calls = [{}] * 69 + [_fsi_call()]
    raw = ("- Corn's ethanol-channel use, 176.66 MMT for 2026/27 [N70], top decile, price-supportive for corn "
           "and relevant here through the acreage competition.")
    out, cen = _lint(raw, calls)
    assert out.startswith("- Corn's food, seed and industrial use, 176.66 MMT for 2026/27 [N70], top decile")
    assert cen.get("noun_corrected") == 1
    # the figure, its handle and every other word stay the writer's
    assert out.endswith(raw[raw.index(", 176.66"):])
    # IDEMPOTENT: the corrected sentence is left as written on a second run
    again, cen2 = _lint(out, calls)
    assert again == out and not cen2.get("noun_corrected")


def test_U5_the_rule_speaks_only_where_the_card_declares_a_part_inside_the_figure():
    lic = an._noun_licence(_fsi_call(), an.cit.call_identity(_fsi_call()))
    assert "ethanol" in lic["basis_clause"] and "ethanol" not in lic["metric_words"]
    assert {"food", "seed", "industrial", "use"} <= set(lic["metric_words"])
    # the second measured case (09-24 corn/wheat): "ethanol-bearing industrial use" over the same FSI row
    out, _c = _lint("against ethanol-bearing industrial use 176.66 MMT [N54] and the tight buffer.",
                    [{}] * 53 + [_fsi_call()])
    assert out == "against food, seed and industrial use 176.66 MMT [N54] and the tight buffer."
    # the writer's own correct name, and a scope / possessive, are left as written
    for ok in ("- Corn's food, seed and industrial use, 176.66 MMT for 2026/27 [N70].",
               "- US food, seed and industrial use, 176.66 MMT [N70].",
               "- FSI use, 176.66 MMT [N70]."):
        assert _lint(ok, [{}] * 69 + [_fsi_call()])[0] == ok, ok
    # a card with NO basis clause is never read for a channel: su_ratio's basis is all name
    su = {"query": {"table": "silver_psd", "metric": "su_ratio", "country": "United States",
                    "commodity": "soybeans_cbot", "period": "MY2026", "asof": "2026-09-26"},
          "rows": [{"value": 0.1072, "unit": "ratio", "knowledge_date": "2026-09-11"}], "status": "ok"}
    lic2 = an._noun_licence(su, an.cit.call_identity(su))
    assert lic2["basis_clause"] == frozenset()


def test_U5_the_noun_span_crosses_one_separator_and_never_a_terminator():
    s = "- Corn's ethanol-channel use, 176.66 MMT [N70]"
    a, b = an._nbl_noun_across_sep(s, s.index("176.66"))
    assert s[a:b].strip() == "- Corn's ethanol-channel use"
    s2 = "Corn use fell. 176.66 MMT [N70]"
    assert an._nbl_noun_across_sep(s2, s2.index("176.66")) is None       # a sentence terminator is never crossed
    s3 = "Corn use; 176.66 MMT [N70]"
    assert an._nbl_noun_across_sep(s3, s3.index("176.66")) is None       # nor a clause terminator
    s4 = "Corn use 176.66 MMT [N70]"
    assert an._nbl_noun_across_sep(s4, s4.index("176.66")) is None       # no separator: V's own span stands


# ═══ U-10 seam half -- THE NAME CORRECTIONS GO THROUGH THE ONE SPLICE PRODUCER ══════════════════════════════
def test_U10_name_corrections_splice_through_rows_splice(monkeypatch):
    from leviathan.graphrag.state import rows as ROWS
    # the replacement already carries the slot's head noun -> the writer's verb agreement is kept as is
    t = "and deliverable US long-grain stocks at 1.28 MMT"
    a, e = t.index("deliverable"), t.index(" at")
    assert an._nbl_splice(t, a, e, "ending stocks for United States") == (a, e, "ending stocks for United States")
    # otherwise the ONE producer decides the slot (rice U-10 (c): "India's exports sits" never again), with the
    # lint's own statement that a noun run ends ON the phrase's head (lane R's `head=` kwarg, read defensively)
    t2 = "while India's exportable supply sits at 25 MMT"
    a2, e2 = t2.index("exportable"), t2.index(" sits")
    fn = getattr(ROWS, "splice", None)
    if callable(fn):
        _hk = {"head": True} if "head" in inspect.signature(fn).parameters else {}
        assert an._nbl_splice(t2, a2, e2, "exports", head=True) == fn(t2, a2, e2, "exports", **_hk)
        _hk0 = {"head": False} if _hk else {}
        assert an._nbl_splice(t2, a2, e2, "exports") == fn(t2, a2, e2, "exports", **_hk0)
    monkeypatch.setattr(ROWS, "splice", None, raising=False)
    assert an._nbl_splice(t2, a2, e2, "exports", head=True) == (a2, e2, "exports")   # no producer: HEAD's
    src = inspect.getsource(an._name_binding_lint)
    assert '"routing_corrected", "noun_corrected", _NBL_NOUN_AT_HEAD' in src
    assert "_nbl_splice(new, a, e, rep, head=(counter == _NBL_NOUN_AT_HEAD))" in src


# ═══ U-7 -- THE CALL'S NETTING FACTS ═════════════════════════════════════════════════════════════════════════
HEAD_ASK_CALL = ("THE CALL AGAINST WHAT IS PRICED: the ASKED SIDES line under [N21] counts the readings on this "
                 "market that settle each side and prints the front price beside them. In the TL;DR, state the "
                 "lean those counts give, weighed against that front price and its standing, or say in one "
                 "clause why they settle no lean.")


def test_U7_the_clause_names_each_printed_part_by_handle_and_asks_one_question():
    assert N.ask_call_mandate(("[N21]",)) == HEAD_ASK_CALL                       # () -> HEAD, byte for byte
    assert N.ask_call_mandate(("[N21]",), netting=()) == HEAD_ASK_CALL
    lit = N.ask_call_mandate(("[N21]",), netting=NETTING)
    assert lit.startswith(HEAD_ASK_CALL + " ")
    tail = lit[len(HEAD_ASK_CALL):]
    for h in ("[N5]", "[E3]", "[N9]"):
        assert h in tail
    assert "net the lean against each of them, or say in one clause why not" in tail
    # no figure, no direction word, no register charge (threat A7-b)
    assert re.sub(r"\[[NE]\d+\]", "", tail).strip() and not re.search(r"\d", re.sub(r"\[[NE]\d+\]", "", tail))
    assert REG.count_flow_words(tail) == 0 and REG.count_desk_register(tail) == 0
    for w in ("higher", "lower", "rise", "fall", "up", "down", "bullish", "bearish"):
        assert not re.search(r"\b%s\b" % w, tail, re.I), w
    # a part the line printed no handle for is never named (threat A7-a)
    only_tape = N.ask_call_mandate(("[N21]",), netting={"opposing": (), "tape": ("[N9]",)})
    assert "the tape's move ([N9])" in only_tape and "set against" not in only_tape
    assert "the reading leading each side ([N5])" in N.ask_call_mandate(("[N21]",), balanced=True,
                                                                       netting={"opposing": ("[N5]",)})


def test_U7_the_netting_reader_takes_only_handles_the_asked_sides_line_printed():
    lead = R.ASK_SIDES_LEAD
    block = ("- [N20] CBOT soybeans, the nearest listed delivery, November 2026, settle on 2026-09-16: 1,021 US "
             "cents/bushel; %s: of the readings on this market above, two toward a higher price, one toward a "
             "lower price and zero settling neither way, beside the front price; the facts a lean is weighed "
             "against: the reading furthest from its own record on the other side [N5], the dated action on this "
             "market [E3] [N7] and the front price over its longest window [N9]\n- [N30] another line [N31]" % lead)
    pool = [{"kind": "netting", "part": "opposing", "handle": 5, "value": 1.0},
            {"kind": "netting", "part": "event", "handle": 7, "e_handle": 3, "value": 2.0},
            {"kind": "netting", "part": "tape", "handle": 9, "value": 3.0},
            {"kind": "netting", "part": "tape", "handle": 31, "value": 4.0}]     # not on the ASKED SIDES line
    got = an._ask_netting_printed(block, served_scalars=pool)
    assert got == {"opposing": ("[N5]",), "event": ("[N7]", "[E3]"), "tape": ("[N9]",)}
    # the seam's trace record is read the same way (a part whose handle the line did not print is dropped)
    assert an._ask_netting_printed(block, netting_trace={"opposing": [5, 44], "event_e": 3, "tape": 9}) == \
        {"opposing": ("[N5]",), "event": ("[E3]",), "tape": ("[N9]",)}
    assert an._ask_netting_printed("no such line [N5]", served_scalars=pool) == {}
    assert an._ask_netting_printed(block) == {}


def test_U7_system_threads_the_netting_only_inside_the_call_clause():
    h = ("[N21]",)
    base = an._system(state_board=True, ask_sides=h, ask_sides_balanced=False)
    both = an._system(state_board=True, ask_sides=h, ask_sides_balanced=False, ask_netting=NETTING)
    assert base in both.replace(" " + N._CLAUSE["netting"].format(parts=N.netting_parts_words(NETTING)), "")
    assert N.netting_parts_words(NETTING) in both
    # the balanced call names the reading leading EACH side (R's balanced netting: the loudest on each side)
    bal = an._system(state_board=True, ask_sides=h, ask_netting=NETTING)
    assert N.netting_parts_words(NETTING, balanced=True) in bal
    assert an._system(state_board=True, ask_netting=NETTING) == an._system(state_board=True)   # no call line
    assert an._system(ask_sides=h, ask_netting=NETTING) == an._system()                          # board-less
    _p = list(inspect.signature(an._system).parameters)
    # MOVED 09-29 (fix sitting 4, lane A, A4-4 / CONTRACT C4-17 -- declared): `ask_sides_lines` is appended after
    # `ask_netting`; the claim kept -- `ask_netting` is a tail append (now the second-last) whose default is `()`.
    assert _p[-2:] == ["ask_netting", "ask_sides_lines"]
    assert inspect.signature(an._system).parameters["ask_netting"].default == ()


# ═══ S2 V-4 -- THE BALANCED / LEAN CHOICE READS THE LINE'S OWN COUNTS ════════════════════════════════════════
def _sides_block(pairs):
    lines, pool = [], []
    for i, (f, a) in enumerate(pairs):
        b = R.Block(start=20 + 10 * i)
        clause = R.sb_ask_sides({"for": f, "against": a, "unsettled": 0}, {"front": True}, block=b)
        line = ("- [N%d] CBOT soybeans, the nearest listed delivery, November 2026, settle on 2026-09-16: 1,021 "
                "US cents/bushel; %s" % (20 + 10 * i, clause))
        assert R.classify(line) == ("SB-T",), R.classify(line)
        for sc in b._pending:
            pool.append(dict(sc, cls="SB-T"))
        lines.append(line)
    return "\n".join(lines), pool


def test_V4_the_choice_reads_the_asked_sides_lines_own_count_scalars():
    block, pool = _sides_block([(2, 2)])
    assert an._ask_sides_line_counts(block, pool) == [(2, 2)]
    assert an._ask_sides_line_balanced(block, pool) is True
    block2, pool2 = _sides_block([(3, 1), (1, 1)])
    assert an._ask_sides_line_counts(block2, pool2) == [(3, 1), (1, 1)]
    assert an._ask_sides_line_balanced(block2, pool2) is False           # one line leans: never "as many"
    # a count the line does not carry (misaligned pool) is UNREAD -> the caller falls back to HEAD's counters
    assert an._ask_sides_line_counts(block2, pool2[:4]) is None
    bad = [dict(s, text="seven") if i == 0 else s for i, s in enumerate(pool)]
    assert an._ask_sides_line_counts(block, bad) is None
    assert an._ask_sides_line_balanced("no line", pool) is None
    src = inspect.getsource(an._answer_l2)
    assert "_ask_sides_line_balanced(_sb.get(\"block\"), _sb.get(\"served_scalars\"))" in src


# ═══ S2 V-2 -- THE ABSENCE CORRECTION SPEAKS THE BOOK'S READER WORDS ═════════════════════════════════════════
def test_V2_the_reason_words_are_the_books_never_the_seats_model_note(monkeypatch):
    from leviathan.graphrag.numbers import agent as AG
    # the book's words WIN over the seat's model-facing note wherever the book declares them (a sentinel book entry
    # proves the read, whatever the shipped book holds today)
    _real = R.book_words
    monkeypatch.setattr(R, "book_words", lambda name, key: ("SENTINEL reader words" if
                                                            (name, key) == ("absence_reason_words", "store_gap")
                                                            else _real(name, key)))
    assert an._absence_reason_words("store_gap") == "SENTINEL reader words"
    monkeypatch.setattr(R, "book_words", _real)
    for reason in AG.ABSENCE_REASONS:
        book = R.book_words("absence_reason_words", reason)
        got = an._absence_reason_words(reason)
        if book:
            assert got == book, reason
        else:
            assert got == str(AG._NO_ROWS_WHY.get(reason) or ""), reason   # no book entry: HEAD's words


# ═══ S2 M-3 -- THE NUMBERS LEDGER AT THE SEAM'S CALL SITE ════════════════════════════════════════════════════
def test_M3_the_ledger_is_seeded_by_the_seat_and_issues_the_boards_first_handle():
    calls = [{"query": {"table": "t", "metric": "m"}, "rows": [{"value": 1.0}]},
             {"query": {"table": "t", "metric": "n"}, "rows": [{"value": 2.0}]}]
    led = an._numbers_ledger(calls, 3)
    assert led is not None and led.address({"query": {"table": "t", "metric": "z"}, "rows": [{"value": 9.0}]}) == \
        (3, False)
    assert an._numbers_ledger(calls, 4) is None                        # a start that does not follow: HEAD's
    assert an._numbers_ledger([], 1) is not None

    class _Seam:
        @staticmethod
        def fill_stage2(bd, *, numbers_ledger=None, e_start=1, evidence_ordinals=None):
            return {}

    class _Old:
        @staticmethod
        def fill_stage2(bd, *, e_start=1, evidence_ordinals=None):
            return {}

    assert an._stage2_kwargs(_Seam, ledger=None, uniq=[], numbers_ledger=led)["numbers_ledger"] is led
    assert "numbers_ledger" not in an._stage2_kwargs(_Old, ledger=None, uniq=[], numbers_ledger=led)
    assert "numbers_ledger" not in an._stage2_kwargs(_Seam, ledger=None, uniq=[], numbers_ledger=None)
