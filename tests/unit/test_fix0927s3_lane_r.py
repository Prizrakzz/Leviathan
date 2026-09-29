"""THE 09-27 FIX SITTING 3, LANE R -- render / rows / seam / register / the row-word books.

TWO LAWS (owner, 2026-09-27): a fix SERVES the writer -- it adds a FACT the writer reasons over, never a sentence it
must repeat -- and every item is proved OPEN on HEAD before it is built (the stale-note law). Each pin below names the
FACT its item adds and, where lane V reads it, the CHECK that fact makes possible.

U-3  (Z5)  the pair's relation as a served row: the spread's own standing and EACH declared edge between the legs.
U-4  (Z6)  every printed desk line registers the statistic it JUDGES and that figure's own handle.
U-7  (Z4)  the ask head carries the netting facts beside the lean, each with its own handle.
U-10 (Z8)  one splice producer (``rows.splice``) keeps the slot's grammar and leaves no doubled separator.
U-12 (Z9)  the header states the block is the panel the writer reads; the block's sentences ride the trace.
S2 M-3 (Z16) the numbers ledger decides every board handle; V-3 (Z18) the watch line registers what it formatted;
I2-a counts carry their kind; P1-i a whole record names where it ends; Z10 / Z20 / Z21 / Z22 the book's words for an
unread condition, an absence reason, a held row and the then-current line; OI-2 (Z24) the register table.
DROPPED by the stale-note law (THREAT_MODEL sec 1, re-proved in BUILD_R.md): U-1 (closed by sitting 2 N-L4 and
``walk.fan_identity``), U-9's row half (lane T by file), U-12's M1 whole-name join (closed by sitting 2 N-L1).

Every pin is offline and $0: the shipped cards, graph and conventions, the harness fixture board, and the arm-A served
sentences quoted verbatim where a pin reads prose.
"""
from __future__ import annotations

import inspect
import types

from leviathan.graphrag import graph as G
from leviathan.graphrag import register as REG
from leviathan.graphrag.numbers import agent as AG
from leviathan.graphrag.state import __main__ as M
from leviathan.graphrag.state import lint as L
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import rows as ROWS
from leviathan.graphrag.state import seam as S
from leviathan.graphrag.state import walk as W

GRAPH = G.CausalGraph(G.load_contracts(), silver=set(), version="harness")
DOC = L.load_conventions() or {}


def _fields(w: str) -> str:
    """A template with its ``{placeholder}`` fields removed -- the words clause 18 grades."""
    import re
    return re.sub(r"\{[a-z]+\}", "", str(w))


# ══ THE BOOKS (every new entry graded by clause 18's own grader) ══════════════════════════════════════════════
NEW_BOOKS = ("panel_words", "pair_standing_words", "pair_relation_words", "threshold_words", "splice_heads",
             "ask_netting_words", "absence_reason_words", "then_current_words", "fx_words")


def test_every_new_book_entry_is_clause_18_clean():
    for book in NEW_BOOKS:
        v = DOC.get(book)
        assert v, book
        items = v.items() if isinstance(v, dict) else enumerate(v)
        for k, w in items:
            for member in (w if isinstance(w, list) else [w]):
                assert L._row_word_errs(f"{book}.{k}", _fields(member), "") == [], (book, k, member)
    for k in ("regime_action_unread", "held_as_last_revised"):
        w = DOC["quorum_words"][k]
        assert L._row_word_errs(f"quorum_words.{k}", w, "") == []
        for verdict in ("met", "in force", "at or past", "short of", "fires"):     # count words only (N2-b)
            assert verdict not in f" {w} ", (k, verdict)


def test_Z20_the_absence_reason_book_covers_exactly_the_seats_reasons():
    assert set(DOC["absence_reason_words"]) == set(AG.ABSENCE_REASONS)


def test_Z9_the_panel_words_are_one_copy_and_carry_no_copy_order():
    pw = DOC["panel_words"]
    assert set(pw) == {"head", "mandate"} and R.PANEL_HEAD == pw["head"]
    for w in pw.values():
        assert "exactly as" not in w and "copy" not in w.replace("not the text you print", "")


# ══ U-10 (Z8): ONE SPLICE PRODUCER ════════════════════════════════════════════════════════════════════════════════
def _apply(text, start, end, name=""):
    a, b, rep = ROWS.splice(text, start, end, name)
    return text[:a] + rep + text[b:]


# the three measured sites (U-10 stale drive), verbatim
SOYOIL_MECH = ("Within palm's own drivers: the high-confidence stocks reading [N100] and the high-confidence drought "
               "reading [N24] point opposite ways.")
PALM_BELT = "the longest dry-day run in the month, as a z-score for SE Asia Palm Belt"
RICE_TLDR = "while India's exportable supply sits at an all-time-wide 25 MMT [N63]"
TARIFF = ("Lag and aftermath in the 2018 case: duties spring 2018 [E1], [E4], with WASDE registering the trade "
          "effect by 12 July 2018 [E3].")


def test_U10_b_a_name_with_its_own_commas_enters_in_apposition_after_the_slots_own_head():
    i = SOYOIL_MECH.index("drought")
    out = _apply(SOYOIL_MECH, i, i + len("drought"), PALM_BELT)
    assert "the high-confidence reading (the longest dry-day run in the month, as a z-score for SE Asia Palm Belt) " \
           "[N24]" in out
    assert "the high-confidence the" not in out                       # the measured doubled determiner
    assert out.count("[N24]") == 1 and out.count("[N100]") == 1        # no handle moved


def _apply_head(text, start, end, name):
    a, b, rep = ROWS.splice(text, start, end, name, head=True)
    return text[:a] + rep + text[b:]


def test_U10_c_the_slots_verb_keeps_its_agreement_through_the_number_neutral_head():
    i = RICE_TLDR.index("exportable supply")
    # the noun correction's span ends at the slot's head noun (the lint's own construction): the caller says so
    out = _apply_head(RICE_TLDR, i, i + len("exportable supply"), "exports")
    assert "India's exports series sits at an all-time-wide 25 MMT [N63]" in out
    assert "exports sits" not in out                                  # the measured agreement failure
    # without the caller's statement the name takes the span's place (HEAD's substitution): the producer never
    # guesses a head from the word after the span (b54: "the board series crush margin" in five of nine)
    assert "India's exports sits" in _apply(RICE_TLDR, i, i + len("exportable supply"), "exports")
    # the head is the book's first, the number-neutral noun: no morphology rule decides it
    assert DOC["splice_heads"][0] == "series"
    src = inspect.getsource(ROWS.splice)
    assert 'endswith("s")' not in src and "[-1] == \"s\"" not in src


def test_U10_a_a_strike_leaves_one_separator_and_never_touches_a_figure_or_a_handle_group():
    for sp in (" [E4]", "[E4]"):
        i = TARIFF.index(sp)
        out = _apply(TARIFF, i, i + len(sp))
        assert "[E1], with WASDE" in out and ",," not in out, out
    assert _apply("sits [E4] at", 5, 9) == "sits at"
    assert _apply("sits [E4].", 5, 9) == "sits."
    t = "A [E1], B [E2], C"
    assert _apply(t, t.index("[E2]"), t.index("[E2]") + 4) == "A [E1], B, C"
    assert _apply("1,[E4],100", 2, 6) == "1,,100"                      # a thousands comma is never a separator
    assert _apply("see [N1, N2] now", 9, 11) == "see [N1, ] now"       # never re-joined inside [..]


# two of HEAD's own corrections on the fifty (b54_splice.py), verbatim: a following NOUN is never read as a verb
SOY_CRUSH = "is the soybean crush margin [N68], which prints every session"
SUNFLOWER = "sits on both: Russian sunflower production for 2026/27 at 7.81 MMT [N31]"


def test_U10_a_routing_or_commodity_correction_keeps_heads_substitution_and_drops_a_doubled_article():
    i = SOY_CRUSH.index("the soybean crush margin")
    assert _apply(SOY_CRUSH, i, i + len("the soybean crush margin"), "the board crush margin") ==         "is the board crush margin [N68], which prints every session"
    i = SUNFLOWER.index("sunflower")
    assert _apply(SUNFLOWER, i, i + len("sunflower"), "sunflower oil") ==         "sits on both: Russian sunflower oil production for 2026/27 at 7.81 MMT [N31]"
    t = "the high-confidence drought [N24] points"
    i = t.index("drought")
    assert _apply(t, i, i + len("drought"), "the longest dry-day run") ==         "the high-confidence longest dry-day run [N24] points"         # the slot supplies the determiner


def test_U10_a_sentence_start_keeps_its_capital_and_no_book_is_heads_plain_substitution():
    assert _apply_head("Exportable supply sits at 25 MMT.", 0, 17, "exports") == "Exports series sits at 25 MMT."
    a, b, rep = ROWS.splice("the drought reading", 4, 11, "exports", book=())
    assert (a, b, rep) == (4, 11, "exports")


# ══ P1-i: A WHOLE RECORD NAMES WHERE IT ENDS ═════════════════════════════════════════════════════════════════════
def test_P1i_a_whole_record_rank_names_its_last_period_and_a_window_keeps_heads_words():
    whole = {"first": "2011/12", "last": "2020/21", "n": 10, "whole": True, "basis": "series"}
    assert ROWS.population_words(whole) == "of its own record through 2020/21"
    whole_m = {"first": "1950-01-01", "last": "2026-07-01", "n": 919, "whole": True, "basis": "series"}
    assert ROWS.population_words(whole_m) == "of its own record through July 2026"
    window = {"first": "2015-08-01", "last": "2026-07-01", "n": 131, "whole": False, "basis": "window"}
    assert ROWS.population_words(window) == "of its record since August 2015"
    # a population with no last period prints nothing, and the row keeps HEAD's words
    assert ROWS.population_words({"first": "1950-01-01", "whole": True}) == ""
    st = types.SimpleNamespace(population={"first": "1950-01-01", "whole": True})
    assert R.population_clause(st) == "of its own record"


# ══ U-3 (Z5): THE PAIR RELATION ═══════════════════════════════════════════════════════════════════════════════════
def _pair_board(a="corn_cbot", b="soft_red_winter_wheat_cbot"):
    edges = []
    for slug in (a, b):
        edges.extend(W.cross_edges(GRAPH, slug, ("forward",)))
    return types.SimpleNamespace(edges=edges, tape={})


CORN_WHEAT = {"kind": "tape_spread", "legs": ["corn_cbot", "soft_red_winter_wheat_cbot"], "declined": False,
              "value": -179.5, "unit": "US cents/bushel", "date": "2026-09-24"}


def test_U3_the_corn_wheat_relation_is_the_spreads_standing_and_both_declared_edges_never_reconciled():
    rel = R.pair_relation(_pair_board(), dict(CORN_WHEAT, handle=15))
    assert rel["standing"] == "under" and rel["sign"] == -1 and rel["leg_order"] == "corn_cbot minus " \
                                                                                     "soft_red_winter_wheat_cbot"
    edges = {(e["from"], e["onto"], e["relation"], e["sign"]) for e in rel["edges"]}
    # corn's card: wheat substitutes_for '-'; SRW's card: corn competes_with '+' -- each with its own sign
    assert ("soft_red_winter_wheat_cbot", "corn_cbot", "substitutes_for", "-") in edges
    assert ("corn_cbot", "soft_red_winter_wheat_cbot", "competes_with", "+") in edges
    wheat = next(e for e in rel["edges"] if e["onto"] == "corn_cbot")
    assert wheat["declared"] == "wheat" and wheat["class"] is True      # declared for the class, joined through it
    blk = R.Block(start=1)
    line = R.sb_pair_relation(rel, None, block=blk)
    assert line.startswith(R.PAIR_RELATION_LEAD + " on [N15]: CBOT corn is under CBOT srw wheat")
    assert "in the opposite direction" in line and "in the same direction" in line
    assert R.classify(line) == ("SB-ASK",)
    assert "[N" not in line.split("]:", 1)[1]                           # it cites the spread and mints nothing
    blk.add(line, label="pair relation")
    sc = [s for s in blk.served_scalars() if s["kind"] == "pair_relation"]
    assert len(sc) == 1 and sc[0]["handle"] == 15 and sc[0]["standing"] == "under"
    assert set(sc[0]["standing_words"]) == {"under", "over", "level"}
    assert sc[0]["standing_words"]["under"][0] == "under"


def test_U3_no_relation_over_a_refused_spread_and_a_zero_spread_is_level():
    assert R.pair_relation(_pair_board(), dict(CORN_WHEAT, declined=True, value=None, handle=15)) is None
    assert R.pair_relation(_pair_board(), None) is None
    assert R.pair_relation(_pair_board(), dict(CORN_WHEAT, value=0.0, handle=15))["standing"] == "level"
    assert R.pair_relation(_pair_board(), dict(CORN_WHEAT, value=12.0, handle=15))["standing"] == "over"


def test_U3_an_edge_joins_only_through_the_graph_or_the_hierarchy_never_a_label():
    assert R._edge_joins("wheat", "", "soft_red_winter_wheat_cbot") == (True, True)
    assert R._edge_joins("corn_cbot", "corn_cbot", "corn_cbot") == (True, False)
    assert R._edge_joins("soybeans", "soybeans_cbot", "corn_cbot") == (False, False)
    src = inspect.getsource(R._edge_joins) + inspect.getsource(R.pair_relation)
    assert "board_label" not in src and ".lower()" not in src


# ══ U-4 (Z6): THE THRESHOLD FACT ══════════════════════════════════════════════════════════════════════════════════
def _drought_row():
    """The soyoil/palm arm-A palm-belt row (trace: drought_z level 1.249, the board's own z 2.665, 96.6th pct)."""
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="drought_z", commodity="malaysian_crude_palm_oil_cme",
                                          country="SE Asia Palm Belt"),
                       status="ok", table="gold_weather_z", metric="drought_z", cadence="monthly", unit="z",
                       narrate_unit="z", scale=1.0, level=1.2491708897603446, level_date="2026-08",
                       knowledge_date="2026-09-25", asof="2026-09-26")
    st.z = {"value": 2.6650948688736418, "window_n": 120}
    st.percentile = {"value": 96.5909090909091}
    from leviathan.graphrag.state import feeders as F
    st.convention = F._convention_label(DOC["conventions"]["drought_z"], st, {}, st.key.label(), [])
    return types.SimpleNamespace(contract="malaysian_crude_palm_oil_cme", driver_id="drought", state=st,
                                 context_only=False, sign="+", lag_band=None, confidence="high", legs={"loud": True},
                                 series_key=st.key.label(), key=("malaysian_crude_palm_oil_cme", "drought"))


def test_U4_the_line_judges_the_boards_own_z_and_names_its_handle_not_the_level():
    row = _drought_row()
    assert row.state.convention["matched"] and row.state.convention["label"] == "severe"
    assert R.judged_statistic(row.state) == ("z", row.state.z["value"])
    blk = R.Block(start=24)
    line, _calls = R.sb_state(24, row, asof="2026-09-26", block=blk)
    blk.add(line, _calls)
    assert "past the line the desk convention calls severe" in line   # the printed words are HEAD's
    th = [s for s in blk.served_scalars() if s["kind"] == "card_threshold"]
    assert len(th) == 1
    t = th[0]
    assert t["judged"] == "z" and t["judged_handle"] == 25 and t["relation"] == "past" and t["line"] == 2.0
    assert t["label"] == "severe" and "past" in t["relation_words"]["past"]
    assert t["threshold_row_id"] == t["row_id"]


def test_U4_a_reading_equal_to_two_statistics_names_none_and_an_unlabelled_row_registers_nothing():
    row = _drought_row()
    row.state.z = {"value": row.state.level}
    row.state.convention = dict(row.state.convention, reading=row.state.level)
    assert R.judged_statistic(row.state)[0] == ""
    row.state.convention = None
    blk = R.Block(start=1)
    line, calls = R.sb_state(1, row, asof="2026-09-26", block=blk)
    blk.add(line, calls)
    assert not [s for s in blk.served_scalars() if s["kind"] == "card_threshold"]


# ══ U-7 (Z4) + S2 M-3 (Z16) + U-12 (Z9) + I2-a + Z21: ON THE HARNESS FIXTURE BOARD ═════════════════════════════════
def _fixture_board(mode="deep", named=("soybeans_cbot",)):
    sg = types.SimpleNamespace(seeds=list(named), nodes=[], trace={})
    q = "what is the situation on soybeans now?"
    bd = S.fill_stage1(graph=GRAPH, sg=sg, asof=M.ASOF, mode=mode, query=q,
                       state_fn=M.fixture_state_fn(M.ASOF), named=tuple(named))
    S.fill_stage2(bd, graph=GRAPH, sg=sg, state_fn=M.fixture_state_fn(M.ASOF))
    R.attach_tape(bd, {s: M.fixture_tape(s, M.ASOF) for s in named}, reads_each=0)
    return bd


def test_U12_the_header_states_the_panel_once_and_the_block_sentences_carry_their_class():
    bd = _fixture_board()
    blk = R.render_board(bd)
    assert blk.lines[0].startswith(R.SB_MARKER_PREFIX) and blk.lines[0].endswith(R.PANEL_HEAD)
    assert R.classify(blk.lines[0]) == ("SB-H",)
    assert sum(1 for ln in blk.lines if R.PANEL_HEAD in ln) == 1
    bs = R.block_sentences(blk)
    assert bs and {"cls", "text"} <= set(bs[0]) and bs[0]["cls"] == "SB-H"
    assert {x["cls"] for x in bs} <= set(R.ROW_CLASSES)


def test_U7_the_netting_facts_ride_the_asked_sides_clause_each_with_its_own_handle():
    bd = _fixture_board()
    blk = R.render_board(bd)
    tape_lines = [ln for ln in blk.lines if R.ASK_SIDES_LEAD in ln]
    if not tape_lines:                                  # no settled side on the fixture: no clause, no netting
        assert blk.ask_netting == {}
        return
    nf = blk.ask_netting.get("soybeans_cbot") or {}
    lead = R.book_words("ask_netting_words", "lead")
    assert lead in tape_lines[0]
    for x in nf.get("opposing") or ():
        assert "[N%d]" % x["handle"] in tape_lines[0]
    if nf.get("tape"):
        assert "[N%d]" % nf["tape"]["handle"] in tape_lines[0]
    net = [s for s in blk.served_scalars() if s["kind"] == "netting"]
    assert {s["part"] for s in net} <= {"opposing", "event", "tape"}


def test_U7_netting_none_is_heads_clause_and_a_held_or_stale_row_is_never_the_opposing_reading():
    sides = {"for": 3, "against": 1, "unsettled": 0}
    assert R.sb_ask_sides(sides, {"front": True}) == R.sb_ask_sides(sides, {"front": True}, netting=None)
    assert R.sb_ask_sides(sides, {"front": True}, netting={}) == R.sb_ask_sides(sides, {"front": True})
    row = _drought_row()
    row.state.period_behind = {"held": "2020/21", "why": "last_revised"}
    bd = types.SimpleNamespace(row=lambda c, d: row)
    blk = types.SimpleNamespace(rows_meta=[{"role": "state", "row_key": row.key, "side": "for", "handles": (5,),
                                            "rank": 0},
                                           {"role": "state", "row_key": row.key, "side": "against",
                                            "handles": (9,), "rank": 1}])
    nf = R.ask_netting_facts(bd, blk, slug=row.contract)
    assert "opposing" not in nf and nf["skipped"]


def test_U7_the_open_event_on_the_market_is_a_netting_fact_with_its_declared_side_and_both_handles():
    row = _drought_row()
    row.sign = "-"
    bd = types.SimpleNamespace(row=lambda c, d: row)
    blk = types.SimpleNamespace(rows_meta=[
        {"role": "state", "row_key": row.key, "side": "for", "handles": (5,), "rank": 0},
        {"role": "event_open", "row_key": row.key, "e_handle": 3, "hop_handle": 5}])
    nf = R.ask_netting_facts(bd, blk, slug=row.contract)
    assert nf["event"]["sign"] == "-" and nf["event"]["e_handle"] == 3 and nf["event"]["handle"] == 5
    clause = R._netting_clause(nf)
    assert R.book_words("ask_sides_words", "against") in clause and "[E3] [N5]" in clause
    # a closed event window is history, never the open event a lean is netted against
    blk.rows_meta[1]["role"] = "event_closed"
    assert "event" not in R.ask_netting_facts(bd, blk, slug=row.contract)


def test_Z16_a_board_call_equal_to_a_seat_call_cites_the_seats_handle_and_mints_nothing():
    from leviathan.graphrag import citations as CIT
    bd = _fixture_board()
    head = R.render_board(bd, start=2)
    seat = dict(head.calls[0])
    bd2 = _fixture_board()
    led = CIT.NumbersLedger([seat], n_start=1)
    tree = R.render_board(bd2, start=2, numbers_ledger=led)
    assert len(tree.calls) == len(head.calls) - led.stamp()["reused"]
    assert any("[N1]" in ln for ln in tree.lines) and not any("[N1]" in ln for ln in head.lines)
    assert all(c is not seat for c in tree.calls)                     # the seat's call is never re-minted


def test_Z16_the_numbers_ledger_decides_every_board_handle_and_none_keeps_heads_block():
    from leviathan.graphrag import citations as CIT
    bd = _fixture_board()
    head = R.render_board(bd)
    bd2 = _fixture_board()
    led = CIT.NumbersLedger((), n_start=1)
    tree = R.render_board(bd2, numbers_ledger=led)
    assert len(tree.calls) <= len(head.calls)
    st = led.stamp()
    assert st["issued"] == len(tree.calls)
    assert st["reused"] == len(head.calls) - len(tree.calls)
    used = {int(x) for ln in tree.lines for x in __import__("re").findall(r"\[N(\d+)\]", ln)}
    assert used <= set(range(1, 1 + len(tree.calls)))                   # every printed handle resolves to a call
    if not st["reused"]:
        assert tree.lines == head.lines


def test_I2a_Z21_the_counts_carry_their_kind_and_held_rows_ride_the_trace_shape():
    blk = R.Block(start=1)
    blk.scalar(3, unit="markets", kind="fan_count", text="three")
    blk.scalar(3, unit="markets", kind="count", text="three")
    blk.add("CROSS-COMMODITY: x", label="x")
    kinds = {(c["noun"], c["value"], c["kind"]) for c in R.served_counts(blk)}
    assert kinds == {("markets", 3, "fan_count"), ("markets", 3, "count")}
    row = _drought_row()
    row.state.period_behind = {"held": "2020/21", "why": "last_revised"}
    b2 = types.SimpleNamespace(rows_meta=[{"role": "state", "row_key": row.key, "handles": (24, 25, 26)}],
                               row_handles={row.key: {"level": 24}})
    bd = types.SimpleNamespace(row=lambda c, d: row)
    held = R.held_rows_of(b2, bd)
    assert held == [{"handle": 24, "row_id": R.row_identity_for(row).row_id}]


def test_Z18_the_watch_line_registers_exactly_the_counts_its_template_formatted():
    blk = R.Block(start=1)
    blk.add("- WATCH a line naming three markets and two paths", role="watch")
    w = {"row": (), "formatted_counts": [[3, "markets"]], "fan": {"n": 3}, "paths": {"n": 2}}
    R._stamp_watch_row(blk, types.SimpleNamespace(convergence=[]), w, {})
    counts = [(s["value"], s["unit"]) for s in blk.served_scalars() if s["kind"] == "count"]
    assert counts == [(3.0, "markets")]                                 # "two" paths is NOT registered: not formatted


# ══ Z10: THE QUORUM NAMES WHY A CONDITION IS UNREAD ════════════════════════════════════════════════════════════════
def test_Z10_an_unread_reason_is_named_in_its_own_clause_and_never_counted():
    row = {"contract": "rough_rice_cbot", "name": "export_restriction_squeeze", "threshold": 3, "n_declared": 6,
           "n_with_band": 0, "matched_measured": ["buyer_tender_demand"],
           "matched_unmeasured": ["India_export_ban", "carry_in"],
           "unread_reason": {"India_export_ban": "regime_action_unread"}}
    line = R.sb_convergence(row)
    assert DOC["quorum_words"]["regime_action_unread"] in line and "(India export ban)" in line
    assert DOC["quorum_words"]["unread"] in line and "(carry in)" in line
    assert "one is counted here" in line
    base = dict(row)
    base.pop("unread_reason")
    assert DOC["quorum_words"]["regime_action_unread"] not in R.sb_convergence(base)
    # the drive's own finding (resmoke 0923 2024 soybeans): with every condition unread and one of them READ as a
    # series, HEAD's "none of those drivers has a series read here" would be false of it -- the book's words instead
    tw = {"contract": "soybeans_cbot", "name": "trade_war_demand_loss", "threshold": 2, "n_declared": 4,
          "n_with_band": 0, "matched_measured": [], "matched_unmeasured": ["China_import_tariff", "China_state_reserves"],
          "unread_reason": {"China_state_reserves": "regime_action_unread"}}
    line = R.sb_convergence(tw)
    assert "none of those drivers has a series read here" not in line
    assert "(%s)" % DOC["quorum_words"]["none_counted"] in line


# ══ Z22: THE THEN-CURRENT LINE AS ITS OWN ROW ════════════════════════════════════════════════════════════════════
def test_Z22_the_then_current_line_prints_as_its_own_row_with_the_books_role_words(monkeypatch):
    from leviathan.graphrag.state import feeders as F
    row = _drought_row()
    wasde = ROWS.StateRow(key=ROWS.SeriesKey(ref="silver_wasde", commodity="soybeans", country="United States"),
                          status="ok", table="silver_wasde", metric="ending_stocks", cadence="monthly",
                          unit="million bushels", narrate_unit="million bushels", scale=1.0, level=315.0,
                          level_date="2023/24", knowledge_date="2024-02-08", asof="2024-03-01")
    monkeypatch.setattr(F, "then_current_state", lambda st, asof="": wasde, raising=False)
    import dataclasses

    @dataclasses.dataclass
    class _Row:
        contract: str
        driver_id: str
        state: object
        series_key: str = ""
        sign: str = "+"
        context_only: bool = False
        lag_band: object = None
        confidence: str = "high"

        @property
        def key(self):
            return (self.contract, self.driver_id)

    blk = R.Block(start=1)
    got = R._then_current_line(blk, types.SimpleNamespace(asof="2024-03-01"), _Row(row.contract, row.driver_id,
                                                                                  row.state), row.state)
    assert got is not None
    line, calls = got
    assert DOC["then_current_words"]["role"] in line and R.classify(line) == ("SB-1",)
    assert calls and calls[0]["query"]["table"] == "silver_wasde"
    monkeypatch.setattr(F, "then_current_state", lambda st, asof="": None, raising=False)
    assert R._then_current_line(blk, types.SimpleNamespace(asof="2024-03-01"),
                                _Row(row.contract, row.driver_id, row.state), row.state) is None


# ══ U-8 (Z13): THE CALL SITE PASSES THE TAPES' OWN RATES, AND PRINTS THE ENGINE'S CONVERSION ═══════════════════════
def test_Z13_the_spread_line_states_the_conversion_the_engine_made_and_heads_line_without_one():
    t_a = types.SimpleNamespace(contract_month="2026-11")
    bd = types.SimpleNamespace(tape={"french_rapeseed_matif": t_a, "malaysian_crude_palm_oil_cme": t_a},
                               asof="2026-09-26")
    sp = {"legs": ("french_rapeseed_matif", "malaysian_crude_palm_oil_cme"), "value": -357.0,
          "unit": "USD/metric ton", "date": "2026-09-24",
          "converted": {"a": {"from": "EUR", "rate": 0.8547, "rate_date": "2026-09-24", "rate_unit": "EUR per USD",
                              "metric": "eur_usd"}}}
    blk = R.Block(start=14)
    line, calls = R.sb_tape_spread(14, sp, bd, block=blk)
    # the rate prints through the ONE precision producer (the FX card declares no decimals: two), and the call and the
    # registered scalar keep the engine's full rate
    assert "converted at 0.85 EUR per USD, the exchange rate of 2026-09-24" in line
    assert calls[0]["rows"][0]["converted"]["a"]["rate"] == 0.8547
    blk.add(line, calls)
    fx = [s for s in blk.served_scalars() if s["kind"] == "fx_rate"][0]
    assert fx["handle"] == 14 and fx["value"] == 0.8547 and fx["text"] == "0.85"
    plain = dict(sp)
    plain.pop("converted")
    line2, calls2 = R.sb_tape_spread(14, plain, bd)
    assert "converted" not in line2 and "converted" not in calls2[0]["rows"][0]


# ══ THE SEAM (Z4 / Z9 / Z16 / Z21 / Z12 / Z13 call sites) ═════════════════════════════════════════════════════════
def test_the_seam_takes_the_ledger_at_its_tail_and_its_trace_payloads_are_omitted_when_empty():
    ps = list(inspect.signature(S.fill_stage2).parameters)
    assert ps[-1] == "numbers_ledger"
    assert list(inspect.signature(R.render_board).parameters)[-1] == "numbers_ledger"
    empty = R.Block(start=1)
    assert S._sitting3_trace(R, empty, types.SimpleNamespace(row=lambda c, d: None)) == {}
    bd = _fixture_board()
    got = S.fill_stage2(bd, graph=GRAPH, sg=types.SimpleNamespace(seeds=["soybeans_cbot"], nodes=[], trace={}),
                        state_fn=M.fixture_state_fn(M.ASOF))
    tr = got.get("trace") or {}
    assert tr.get("block_sentences") and "numbers_ledger" not in tr


def test_the_seams_front_fn_rides_only_the_chain_flag_and_heads_call_without_the_producer(monkeypatch):
    from leviathan.graphrag.state import feeders as F
    bd = types.SimpleNamespace(asof="2026-09-26")
    got = S._front_fn_kw(bd, qfn=lambda *a, **k: [])
    if got:                                              # lane W's producer and walk keyword are in this tree
        fn = got["front_fn"]
        assert fn.func is F.front_moves and fn.keywords["asof"] == "2026-09-26" and callable(fn.keywords["qfn"])
    monkeypatch.setattr(F, "front_moves", None, raising=False)
    assert S._front_fn_kw(bd) == {}


def test_Z13_the_seam_reads_a_rate_only_for_the_non_usd_leg_of_a_two_currency_pair(monkeypatch):
    from leviathan.graphrag.state import feeders as F
    asked = []

    def _fx(currencies, asof, *, qfn, on_or_before):
        asked.append((tuple(currencies), on_or_before))
        return {c: {"metric": "eur_usd", "rate": 0.85, "date": on_or_before, "unit": "EUR per USD", "status": "ok"}
                for c in currencies}
    monkeypatch.setattr(F, "fx_rows", _fx, raising=False)
    eur = ROWS.TapeState(slug="french_rapeseed_matif", currency="EUR", level_date="2026-09-24")
    usd = ROWS.TapeState(slug="malaysian_crude_palm_oil_cme", currency="USD", level_date="2026-09-24")
    bd = types.SimpleNamespace(asof="2026-09-26", anchors=(
        types.SimpleNamespace(contract="french_rapeseed_matif", named=True, source="named"),
        types.SimpleNamespace(contract="malaysian_crude_palm_oil_cme", named=True, source="named")))
    tape = {"french_rapeseed_matif": eur, "malaysian_crude_palm_oil_cme": usd}
    S._attach_fx(bd, tape)
    assert asked == [(("EUR",), "2026-09-24")] and eur.fx["rate"] == 0.85 and usd.fx == {}
    asked.clear()
    usd2 = ROWS.TapeState(slug="soybean_oil_cbot", currency="USD", level_date="2026-09-24")
    S._attach_fx(types.SimpleNamespace(asof="2026-09-26", anchors=(
        types.SimpleNamespace(contract="malaysian_crude_palm_oil_cme", named=True, source="named"),
        types.SimpleNamespace(contract="soybean_oil_cbot", named=True, source="named"))),
        {"malaysian_crude_palm_oil_cme": usd, "soybean_oil_cbot": usd2})
    assert asked == []                                   # one currency: nothing is read


def test_Z13_the_pair_spread_hands_the_calculator_the_tapes_own_rates_only_where_it_takes_them(monkeypatch):
    from leviathan.graphrag.numbers import stats as ST
    seen = {}

    def _pls(va, da, ua, vb, db, ub, *, currency_a=None, currency_b=None, label_a="", label_b="", fx_a=None,
             fx_b=None):
        seen.update(fx_a=fx_a, fx_b=fx_b)
        return {"declined": True, "reason": "x"}
    monkeypatch.setattr(ST, "pair_level_spread", _pls)
    eur = ROWS.TapeState(slug="french_rapeseed_matif", currency="EUR", level_date="2026-09-24", status="ok",
                         fx={"rate": 0.85, "status": "ok"})
    usd = ROWS.TapeState(slug="malaysian_crude_palm_oil_cme", currency="USD", level_date="2026-09-24", status="ok")
    bd = types.SimpleNamespace(tape={"french_rapeseed_matif": eur, "malaysian_crude_palm_oil_cme": usd}, anchors=(
        types.SimpleNamespace(contract="french_rapeseed_matif", named=True, source="named"),
        types.SimpleNamespace(contract="malaysian_crude_palm_oil_cme", named=True, source="named")))
    R.tape_pair_spread(bd)
    assert seen == {"fx_a": {"rate": 0.85, "status": "ok"}, "fx_b": None}


# ══ OI-2 (Z24): THE REGISTER TABLE ════════════════════════════════════════════════════════════════════════════════
# the recon's measured page-talk sentences, verbatim from the fifty served pages (arm A treatment cells)
RECON = ("Nothing else on this page cleared the bar for cotton.",
         "Three items cleared the bar on this market; the rest of the nominated list sat on corn and rapeseed meal and "
         "I have left it there.",
         "The managed-money reading is declared same-direction on thirteen other markets this estate tracks.",
         "the newest dated document behind this page is 2025-03-31")


def test_OI2_the_recons_page_talk_is_charged_and_every_replacement_is_clean():
    names = {n for n, _p, _r in REG.DESK_REGISTER_TOKENS}
    assert {"this page", "cleared the bar", "nominated", "this estate"} <= names
    hit = {n for s in RECON for n, _ctx in REG.desk_register_hits(s)}
    assert {"this page", "cleared the bar", "nominated", "this estate"} <= hit
    for n, _p, r in REG.DESK_REGISTER_TOKENS:
        assert REG.count_desk_register(r) == 0, n
        assert "page" not in r and "like this" not in r, (n, r)
    assert REG.DESK_REGISTER_V1_NAMES == ("board", "row", "the graph", "loud", "knowledge date", "convention",
                                          "state read", "receipt", "node", "series key", "the walk")
    assert REG.check_desk_exempt_table() == []


def test_OI2_F_N2_the_firing_rows_second_phrase_names_a_dated_window_never_a_likeness():
    p = REG.desk_phrase("firing", 1)
    assert "like" not in p and "window" in p
