"""THE 09-26 FIX SITTING 2, LANE N -- narration / render / seam / board (C-I3b) / cascade (SAFP) / the books.

N-1  THE PAGE NARRATES ITS OWN MACHINERY: the mandate and the board literals speak in the reader's objects -- the
     record's reader name is "the market record", the watch close names what was weighed and left, the recency
     clause names the layers, the fan names "the markets this service covers" -- and every literal is graded at
     build by the desk detector as well as the four register detectors (CONTRACT Y16, scoped: see the pin).
N-2  THE QUORUM: four populations, four clauses, only the read-and-sided one is COUNTED; no comparison verdict.
N-4  the chain COUNT line prints once, at the head of the chains, with the further count as its own figure; the
     season-average price pair names its own window where it is not the read's.
N-5  ``render.movement_ranks`` -- the board's own rank per printed [N]; the never-cut rows at 0.
N-6 / N-7  the counts minted as served figures (C-I6 ``served_counts``), ``watch_rows`` (C-I4) on the watched
     reading's LEVEL handle, the settled sides (C-I3b) on the counters and on every rendered row state.
LEFTOVERS  N-L1 (hyphen-insensitive name join), N-L2 (the page's receipt pool through the walk's identity rule),
     N-L3 (the record end by the row's own n), N-L4 (the other pole's far edge named as that pole's), m2 (the
     backstop cap on the short names), m4 (the like-state opening reads its own two populations).
CONTRACT halves  Y8 (the population words), Y9 (the next print as a window), Y11 (the recency layers named),
     Y13 (the settled sides beside the front price + the call mandate), Y23 (the rows producer's separator).

Every pin is offline and $0: the shipped cards and conventions, hand-built walk objects in the producers' shapes,
the harness fixture board through the serving seam, and the arm-A pages' own measured quotes.
"""
from __future__ import annotations

import ast
import functools
import pathlib
import types

from leviathan.graphrag import graph as G
from leviathan.graphrag import register as REG
from leviathan.graphrag.numbers import cascade as C
from leviathan.graphrag.state import __main__ as M
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import lint as L
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import rows as ROWS
from leviathan.graphrag.state import seam as S
from leviathan.graphrag.state import walk as W

SRC = pathlib.Path(R.__file__).resolve().parent


# ── the harness board, built ONCE per process (the serving seam over the fixture state) ─────────────────────────
@functools.lru_cache(maxsize=4)
def _board(mode: str = "deep", chain: bool = True, anchor: str = "soybeans_cbot"):
    g = G.CausalGraph(G.load_contracts(), silver=set(), version="harness")
    q = "what is the situation on soybeans now? how is it looking 3 months from now?"
    sg = types.SimpleNamespace(seeds=[anchor], nodes=[], trace={})
    bd = S.fill_stage1(graph=g, sg=sg, asof=M.ASOF, mode=mode, query=q,
                       state_fn=M.fixture_state_fn(M.ASOF), named=(anchor,))
    got = S.fill_stage2(bd, graph=g, sg=sg, state_fn=M.fixture_state_fn(M.ASOF),
                        **({"state_chain": True} if chain else {}))
    return bd, got


# ═══ N-1 ══════════════════════════════════════════════════════════════════════════════════════════════════════
#: THE MEASURED QUOTES (recon N-5, the arm-A treatment pages): each phrase a writer copied, traced to the literal
#: that taught it. A REGRESSION PIN ON THOSE LITERALS -- never a list a writer is told to avoid, and never a fence
#: at serve time: the detector population that would carry these words is register.py's (OI-2, not this lane's).
_TAUGHT = {
    "cleared the bar": ("narration.MANDATE_WATCH_NONOBVIOUS", "render.ABSENCE_WHY watch_floor_unmet"),
    "nominates": ("narration.MANDATE_WATCH_NONOBVIOUS",),
    "this page": ("narration.MANDATE_BLOCK_READER_NAME", "narration.DESK_REGISTER_RECENCY_CLAUSE",
                  "narration.MANDATE_ASK_HEAD"),
    "this estate": ("render.sb_fan", "render.ABSENCE_WHY anchor_none"),
    "behind the page": ("narration._T_SYSTEM_STATE_BOARD_MANDATE movement (2)",),
    "the page carries": ("render.sb_chain_head", "render.sb_chain_one_line"),
}


def _shipped_literals() -> dict:
    """Every narration literal as it SHIPS on a desk turn with every board flag lit, plus the rewritten render
    literals -- the texts the writer is handed."""
    return {
        "mandate[nonobvious+chain+desk]": N.state_board_mandate(nonobvious=True, chain=True, desk=True),
        # the desk mandate's OWN words (its {table} slot is register.py's replacement column, OI-2 -- see BUILD_N)
        "desk+recency": N.SYSTEM_DESK_REGISTER_MANDATE.replace("{table}", "") + N.DESK_REGISTER_RECENCY_CLAUSE,
        "ask": N.ask_head_mandate(("[N11]", "[N14]")),
        "horizon": N.MANDATE_HORIZON_ROW,
        "positioning": N.positioning_asymmetry_mandate(("[N14]",)),
        "call": N.ask_call_mandate(("[N21]",)),
        "call_balanced": N.ask_call_mandate(("[N21]",), balanced=True),
        "ledger": N.RECENCY_LEDGER_SENTENCE,
        "absence_why": " ".join(R.ABSENCE_WHY.values()),
        "leg_absence": R.sb_analog_leg_absence(""),
        "join_tied": R.sb_phase_pair(["IDR USD", "MYR USD"], "CME palm oil", opposed=True, keep_tied=True),
        "join_alias": R.sb_phase_pair(["crush margin", "board crush"], "CBOT soybeans", opposed=False,
                                      keep="crush margin", alias=("board crush",)),
        "chain_head": R.sb_chain_head(W.Chain(contract="corn_cbot", hops=(W.ChainHop(
            contract="corn_cbot", driver_id="npk_fertilizer_z"),), terminal="corn_cbot"), i=1, n=1),
        "fan": R.sb_fan({"driver_id": "El_Nino", "contract": "c", "far": [
            {"contract": "cotton_ice", "sign": "-", "confidence": "high", "lag_band": None},
            {"contract": "rough_rice_cbot", "sign": "+", "confidence": "high", "lag_band": None}]}),
    }


def test_N1_the_measured_page_talk_is_gone_from_the_literals_that_taught_it():
    lits = _shipped_literals()
    for phrase, sources in _TAUGHT.items():
        for name, text in lits.items():
            assert phrase not in text.lower(), (phrase, name, sources)
    assert N.MANDATE_BLOCK_READER_NAME == "the market record"
    desk = lits["mandate[nonobvious+chain+desk]"]
    assert N.MANDATE_BLOCK_READER_NAME in desk and N.MANDATE_BLOCK_SELF_NAME not in desk
    # the reader's objects, positively: what was weighed and left; the layers by name; the service's markets.
    # RE-BANKED 09-27 (fix sitting 3, lane A, U-12 (a) -- declared DM4): the watch close asks for the FACT ("the
    # readings you weighed and left and why"), and the layers are named by the board mandate's own EVIDENCE clause
    # in the reader's words (the desk half keeps only the tape's exempt name) -- the claims kept: both are the
    # reader's objects, never the page.
    assert "the readings you weighed and left" in desk
    assert ("the newest date its figures were known, the newest dated document behind this answer, the session "
            "the board price tape runs through") in desk
    assert "markets this service covers" in lits["fan"]


def test_N1_the_rewritten_literals_are_desk_clean_and_register_clean_as_they_ship():
    """Y16, scoped to what this lane rewrote: each literal AS IT SHIPS scores zero on the desk detector and the
    register leak detector. The base mandate keeps HEAD's block-facing words (its CROSS-COMMODITY needles are
    config_check's, a file this lane does not own) and rides the ratchet below."""
    shipped = {
        "watch": N._T_MANDATE_WATCH_NONOBVIOUS.format(record=N.MANDATE_BLOCK_READER_NAME),
        "recency": N.DESK_REGISTER_RECENCY_CLAUSE,
        "chain": N._T_MANDATE_CHAIN_MOVEMENT.format(record=N.MANDATE_BLOCK_READER_NAME),
        "ask": N.ask_head_mandate(("[N11]",)), "horizon": N.MANDATE_HORIZON_ROW,
        "positioning": N.positioning_asymmetry_mandate(("[N14]",)),
        "call": N.ask_call_mandate(("[N21]",)), "call_balanced": N.ask_call_mandate(("[N21]",), balanced=True),
        "ledger": N.RECENCY_LEDGER_SENTENCE, "not_carried": N.RECENCY_NOT_CARRIED,
        "reader_name": N.MANDATE_BLOCK_READER_NAME, "one_chain": R.CHAIN_ONE_WORDS,
        "amplifier_note": R.AMPLIFIER_NOTE_REPLACED, "amplifier_unknown": R.AMPLIFIER_EFFECT_UNKNOWN,
        "fold_unreconciled": R.FOLD_RELATION_WORDS["unreconciled"],
        **{f"absence[{k}]": v for k, v in R.ABSENCE_WHY.items()},
        **{f"one_line[{k}]": v for k, v in R.CHAIN_ONE_LINE_WORDS.items()},
    }
    for name, text in shipped.items():
        # "the board price tape" is the one exempt market phrase the recency clause is TOLD to carry
        assert REG.desk_register_hits(text) == [], (name, REG.desk_register_hits(text))
        assert REG.register_leaks(text) == [], (name, REG.register_leaks(text))
        assert R.register_hits(text) == [], (name, R.register_hits(text))
    assert N.check_literals() == []


#: THE RATCHET (Y16's module-wide half): the desk-register hits each module-level string constant of the two
#: modules carries, BANKED at this build. A ceiling may only fall; a constant not listed must be desk-clean.
#: The residual is named, never hidden: block-facing class markers ("BOARD ABSENCE"), scorer vocabularies
#: (`_RECENCY_LAYER_WORDS`), ban lists, section keys, and the base mandate whose needles config_check owns.
#: RE-BANKED 09-27 (fix sitting 3, lane A, U-12 -- declared): the board-turn literals are COMPOSED from the declared
#: clause tuples, so their words now live in `MANDATE_FACTS` / `MANDATE_RULES` and the composed constants carry no
#: string of their own. The ratchet's claim is kept and measured module-wide: narration's desk-register hits over
#: every module-level constant fall 47 -> 12 (HEAD 27 + 12 + 2 + 3 + 1 + 2; tree 3 + 3 + 3 + 1 + 2) -- the residue is
#: the block's own class markers ("BOARD JOIN", "BOARD ABSENCE"), config_check's CROSS-COMMODITY needle ("no
#: stocks-to-use rows") and the register's own exemption words ("commodity board").
_DESK_CEILING = {
    ("narration", "MANDATE_FACTS"): 3, ("narration", "MANDATE_RULES"): 3,
    ("narration", "SYSTEM_RECENCY_CLAUSE"): 3,
    ("narration", "BANNED_RECENCY_PHRASE"): 1, ("narration", "CHAIN_MOVEMENT_BANNED_WORDS"): 2,
    ("render", "ROW_CLASSES"): 7, ("render", "BLOCK_ORDER"): 1, ("render", "RENDER_CAPS"): 3,
    ("render", "_RECENCY_LAYER_WORDS"): 3, ("render", "CHAIN_ONE_LINE_WORDS"): 1,
}


def _module_string_constants(mod: str) -> dict:
    tree = ast.parse((SRC / f"{mod}.py").read_text(encoding="utf-8"))
    out: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names, val = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, val = [node.target.id], node.value
        else:
            continue
        if val is None:
            continue
        strs = [s.value for s in ast.walk(val) if isinstance(s, ast.Constant) and isinstance(s.value, str)]
        for n in names:
            out.setdefault(n, []).extend(strs)
    return out


def test_literals_speak_in_the_readers_objects():
    """CONTRACT Y16 -- every module-level string constant of narration.py and render.py returns
    ``register_leaks == []``; its desk-register hits stay at or under the banked ceiling (and a constant with no
    ceiling is desk-clean). BLOCKED HALF, stated: the recon's own nouns ("page", "estate", "the bar",
    "nominated") are not in ``register.DESK_REGISTER_TOKENS`` (OI-2, register.py is not this lane's file), so
    the detector cannot see them; the measured phrases are pinned on their literals above instead."""
    for mod in ("narration", "render"):
        for name, strs in _module_string_constants(mod).items():
            hits = sum(len(REG.desk_register_hits(s)) for s in strs)
            leaks = [s[:60] for s in strs if REG.register_leaks(s)]
            assert not leaks, (mod, name, leaks)
            assert hits <= _DESK_CEILING.get((mod, name), 0), (mod, name, hits)


def test_the_new_books_are_graded_like_clause_18():
    """Each book this lane adds is held to clause 18's rules through the lint's own grader (``lint.ROW_WORD_BOOKS``
    does not list them yet -- that table is lint.py's, the orchestrator's to extend)."""
    doc = L.load_conventions()
    ph = {"population_words": {"window": "{month}", "contract_life": "{day}"}, "window_words": "{span}",
          "like_state_words": "{month}", "pole_edge_words": "{pole}"}
    assert doc["like_state_words"]["ranked"].count("{ordinal}") == 1        # the seat's own ordinal, once
    for book in ("quorum_words", "population_words", "window_words", "ask_sides_words", "like_state_words",
                 "pole_edge_words", "regime_words"):
        assert isinstance(doc.get(book), dict) and doc[book], book
        for k, w in doc[book].items():
            p = ph.get(book, "")
            p = p.get(k, "") if isinstance(p, dict) else p
            if book == "regime_words":
                p = "%s"
            assert L._row_word_errs(f"{book}.{k}", str(w), p) == [], (book, k)
    # the quorum's words carry no verdict (N2-b)
    for w in doc["quorum_words"].values():
        for verdict in ("met", "in force", "at or past", "short of", "fires"):
            assert verdict not in f" {w} ", (w, verdict)
    assert "this page" not in doc["regime_words"]["ledger"]


def test_N1_flag_off_the_mandate_constant_is_the_function_and_the_self_name_holds():
    assert N.state_board_mandate() is N.SYSTEM_STATE_BOARD_MANDATE
    assert N.state_board_mandate(chain=False) is N.SYSTEM_STATE_BOARD_MANDATE
    assert N.MANDATE_BLOCK_SELF_NAME == "the block"


# ═══ N-2 ══════════════════════════════════════════════════════════════════════════════════════════════════════
def _glut(measured=("El_Nino", "China_state_reserves"), unread=("USD_index",), against=(), unsided=()):
    """The cotton 09-26 N-b shape (bearish_glut asks 3 of 7): two read conditions, one loud with no series."""
    return {"contract": "cotton_ice", "name": "bearish_glut", "direction": "-", "threshold": 3,
            "drivers": ("El_Nino", "USD_index", "China_state_reserves", "a", "b", "c", "d"),
            "matched": tuple(measured) + tuple(unread), "n_matched": len(measured) + len(unread),
            "matched_measured": tuple(measured), "matched_unmeasured": tuple(unread), "n_declared": 7,
            "loud_k": 16, "n_with_band": 0, "interactions": (), "against": tuple(against),
            "unsided": tuple(unsided)}


def test_N2_an_unread_condition_is_named_in_its_own_clause_and_never_counted():
    row = _glut()
    cnt = R.pattern_count(row)
    assert cnt["n_distinct"] == cnt["n_measured"] == 2 and cnt["n_unread"] == 1
    line = R.sb_convergence(row)
    assert "two of the seven conditions it names are showing here" in line
    assert "one more is named by the pattern with no series read here, so not counted (USD index)" in line
    assert "it asks for three, and two are counted here" in line
    assert R.classify(line) == ("SB-C",)


def test_N2_the_line_states_two_numbers_and_no_comparison_verdict():
    for row in (_glut(), _glut(measured=("El_Nino", "China_state_reserves", "a")), _glut(measured=())):
        line = R.sb_convergence(row)
        for verdict in ("at or past", "short of", "in force", " met", "fires"):
            assert verdict not in line, (verdict, line)
    assert "and none of them is counted here" in R.sb_convergence(_glut(measured=()))


def test_N2_four_populations_partition_the_declared_conditions():
    """Y17's pin: counted (+ folded aliases) + against + unsided + phase-opposed + unread + not-among-the-largest
    == the pattern's declared conditions, on a row carrying every population."""
    row = _glut(measured=("El_Nino",), unread=("USD_index",), against=("a",), unsided=("b",))
    row["matched"] = ("El_Nino", "USD_index")
    cnt = R.pattern_count(row)
    fold = cnt["fold"]
    counted = set(fold["keep"]) | {a for _k, al, _r in fold["groups"] for a in al}
    parts = [counted, set(fold["phase_opposed"]), set(row["against"]), set(row["unsided"]), set(cnt["unread"])]
    named = set().union(*parts)
    assert sum(len(p) for p in parts) == len(named)                      # disjoint
    rest = set(row["drivers"]) - named
    assert len(named) + len(rest) == row["n_declared"]
    line = R.sb_convergence(row)
    assert "one of them reads in the tail opposite" in line and "no committed direction" in line
    assert "it asks for three, and one is counted here" in line


def test_N2_the_quorum_registers_its_counts_as_served_figures():
    blk = R.Block(start=1)
    blk.add(R.sb_convergence(_glut(), block=blk))
    counts = R.served_counts(blk)
    # RE-BANKED 09-27 FIX SITTING 3, LANE R (LEFTOVERS I2-a; DECLARED in BUILD_R): each entry also carries the KIND it
    # was registered under (a quorum's counts are `count`); the claim kept: the quorum's own counts are served figures.
    assert {"noun": "conditions", "value": 2, "text": "two", "kind": "count"} in counts
    assert {"noun": "conditions", "value": 3, "text": "three", "kind": "count"} in counts


# ═══ N-4 ══════════════════════════════════════════════════════════════════════════════════════════════════════
def test_N4_the_count_line_prints_the_further_count_itself():
    line = R.sb_chain_count({"distinct_sequences": 194, "total": 500, "distinct_unnamed_markets": 2}, k=2,
                            anchor_label="CBOT corn, CBOT wheat",
                            carried_seqs=(("corn", ("a", "b")), ("corn", ("c",))))
    # corn/wheat F10: "Beyond those, one hundred ninety-four chains" -- 194 INCLUDED the two carried
    assert "one hundred ninety-four chains of cause" in line
    assert "the other one hundred ninety-two are counted here" in line
    assert "the two carried below are followed link by link" in line
    # the carried sequences are the walk's own identity: two chains on ONE sequence are one carried sequence
    one = R.sb_chain_count({"distinct_sequences": 5, "total": 9}, k=2, anchor_label="ICE cocoa",
                           carried_seqs=(("c", ("a",)), ("c", ("a",))))
    assert "the other four are counted here" in one
    assert R.sb_chain_count({"distinct_sequences": 1, "total": 1}, k=1, anchor_label="ICE cocoa").endswith(
        "and no further chain runs into it.")


def test_N4_the_count_line_prints_once_at_the_head_of_the_chains():
    bd, got = _board("deep", True)
    lines = got["block"].splitlines()
    counts = [i for i, ln in enumerate(lines) if ln.startswith(R.CHAIN_HEAD_PREFIX + "COUNT")]
    heads = [i for i, ln in enumerate(lines) if ln.startswith(R.CHAIN_HEAD_PREFIX)
             and not ln.startswith(R.CHAIN_HEAD_PREFIX + "COUNT")]
    assert len(counts) == 1 and heads and counts[0] < min(heads)
    sc = [c for c in (got.get("trace") or {}).get("served_counts") or () if c["noun"] == "chains"]
    assert len(sc) >= 2


def _price_fixture(asof):
    """`_price_pair` over a fake seat: the 2018 tariff episode window, both endpoints served."""
    rows = {"2017/18": 9.33, "2018/19": 8.48, "2025/26": 10.1, "2026/27": 10.5}

    def qfn(spec):
        v = rows.get(spec.get("period"))
        return {"status": "ok", "rows": [{"value": v, "unit": "USD/bu", "marketing_year": spec.get("period"),
                                          "release_date": "2020-04-09"}]}
    return qfn


def test_N4_the_price_pair_names_its_own_window_only_under_the_display_key(monkeypatch):
    monkeypatch.setattr(C, "_xc_focus_windows", lambda *a, **k: [("2018-03-01", "2018-12-31")])
    monkeypatch.setattr(C, "_run_one", lambda qfn, s, **k: qfn(s))
    calls: list = []
    req = {"focus_contract": "soybeans_cbot"}
    head, _t = C._price_pair(req, None, None, [], _price_fixture("2026-09-26"), "2026-09-26", None, calls, 0)
    calls2: list = []
    lit, _t2 = C._price_pair(req, None, None, [], _price_fixture("2026-09-26"), "2026-09-26", None, calls2, 0,
                             display="analyst")
    assert head and lit and head[:2] == lit[:2]                          # the two level lines never move
    assert head[2].startswith("PRICE-RESPONSE on avg_farm_price: ")      # HEAD's line, flag-off
    assert lit[2].startswith("PRICE-RESPONSE on avg_farm_price, over the past episode's own marketing years, "
                             "MY2017/18 to MY2018/19")
    assert lit[2].split(": ", 1)[1] == head[2].split(": ", 1)[1]         # figures, handles, words after: unchanged
    # a pair whose years cover the read's own marketing year prints HEAD's line even under the key
    monkeypatch.setattr(C, "_xc_focus_windows", lambda *a, **k: [("2025-10-01", "2026-09-20")])
    now, _t3 = C._price_pair(req, None, None, [], _price_fixture("2026-09-26"), "2026-09-26", None, [], 0,
                             display="analyst")
    assert now[2].startswith("PRICE-RESPONSE on avg_farm_price: ")


# ═══ N-5 / N-6 / N-7 ═══════════════════════════════════════════════════════════════════════════════════════════
def test_N5_movement_ranks_follow_the_boards_own_order_and_hold_the_never_cut_rows_at_zero():
    bd, _got = _board("deep", True)
    ranks = R.movement_ranks(bd)
    meta = list(bd.rendered_rows)
    states = [m for m in meta if m.get("role") == "state" and m.get("handles")]
    assert states and all(ranks[m["handles"][0]] == int(m["rank"]) + 1 for m in states)
    for m in meta:
        if m.get("handles") and (m.get("role") in ("ask", "watch", "tape", "cited_state")
                                 or str(m.get("role") or "").startswith("chain")):
            assert all(ranks[h] == 0 for h in m["handles"]), m.get("role")


def test_N7_the_settled_sides_ride_the_counters_and_every_rendered_row_state():
    bd, got = _board("deep", True)
    cnt = got["counters"]
    sides = [m["side"] for m in bd.rendered_rows if m.get("role") in ("state", "cited_state") and m.get("side")]
    assert sides and cnt["BoardSidesFor"] == sides.count("for")
    assert cnt["BoardSidesAgainst"] == sides.count("against")
    assert cnt["BoardSidesUnsettled"] == sides.count("unsettled")
    rs = got["trace"]["row_states"]
    rendered = {tuple(m["row_key"]) for m in bd.rendered_rows if m.get("role") in ("state", "cited_state")}
    for r in rs:
        k = (r["contract"], r["driver_id"])
        assert ("side" in r) == (k in rendered and bool(getattr(bd.row(*k), "board_side", ""))), k
        if "side" in r:
            assert r["side"] in ("for", "against", "unsettled")


def test_N7_a_side_is_the_walks_own_rule_on_the_rows_own_hop():
    bd, _got = _board("deep", True)
    checked = 0
    for m in bd.rendered_rows:
        if m.get("side"):
            checked += 1
            row = bd.row(*m["row_key"])
            if row.context_only:                                        # D18: positioning settles nothing
                assert m["side"] == "unsettled"
                continue
            hop = W.chain_hop(bd, row)
            ch = W.Chain(contract=row.contract, hops=(hop,), declared_sign=W.chain_declared_sign((hop,)))
            assert W._chain_direction(ch)[1] == m["side"]
    # NOT VACUOUS (the self-refutation: on HEAD no row carries a side and the loop above checked nothing)
    assert checked >= 1 and checked == sum(1 for m in bd.rendered_rows if m.get("role") == "state"), checked


def test_N7_watch_rows_carry_the_watched_readings_level_handle():
    bd, got = _board("deep", True)
    wr = got["trace"].get("watch_rows") or []
    assert wr and len(wr) == sum(1 for m in bd.rendered_rows if m.get("role") == "watch")
    levels = {m["handles"][0] for m in bd.rendered_rows if m.get("role") in ("state", "cited_state")
              and m.get("handles")}
    assert all(w["handle"] is None or w["handle"] in levels for w in wr)
    assert any(w["handle"] for w in wr)


def test_N7_watch_cited_reads_the_level_handle_the_writer_cites():
    bd, _got = _board("deep", True)
    wr = [w for w in R.watch_rows_of(bd.rendered_rows) if w["handle"]]
    prose = "The watched reading sits at its record [N%d]." % wr[0]["handle"]
    cov = R.board_coverage(bd, prose)
    # every watch line whose watched reading is the cited one counts; no other line does
    assert cov["watch_cited"] == sum(1 for w in wr if w["handle"] == wr[0]["handle"]) >= 1
    assert R.board_coverage(bd, "No handle cited here.")["watch_cited"] == 0


def test_N6_served_counts_are_the_blocks_own_count_scalars_and_nothing_else():
    bd, got = _board("deep", True)
    sc = got["trace"]["served_counts"]
    pool = {(s["unit"], int(s["value"])) for s in got["served_scalars"] if s["kind"] in R.COUNT_SCALAR_KINDS}
    assert sc and {(c["noun"], c["value"]) for c in sc} == pool
    assert {c["noun"] for c in sc} >= {"chains"}


def test_N7_absent_is_never_zero_a_board_with_no_rendered_side_carries_no_side_key():
    bd = types.SimpleNamespace(rendered_rows=(), rows=[], legs={"board": {"outcome": "fired"}},
                               ledger=types.SimpleNamespace(waves={}, tape_reads=0, budget_capped=0,
                                                            pool_declined=0, evidence_borrows=0,
                                                            replay_labelled=0),
                               net_reads=lambda: 0, stage_ms={}, subject={})
    assert not [k for k in S.counters(bd) if k.startswith("BoardSides")]
    row = B.NodeRow(contract="c", driver_id="d")
    assert "side" not in B.Board._row_state(row)
    row.board_side = "for"
    assert B.Board._row_state(row)["side"] == "for"
    assert list(B.Board._row_state(row))[-1] == "side"                   # appended LAST


# ═══ LEFTOVERS ════════════════════════════════════════════════════════════════════════════════════════════════
def test_NL1_a_names_own_words_join_across_a_hyphen_and_only_its_own():
    rx = R._token_rx("rubber area substitution")
    assert rx.search("the rubber-area substitution effect") and rx.search("rubber area substitution")
    assert not rx.search("rubber area-price substitution")
    assert R._token_rx("2026-05-01").pattern.endswith(r"2026\-05\-01(?![0-9a-z])")


def test_NL2_the_page_receipt_pool_reads_through_the_walks_identity_rule():
    hop = W.ChainHop(contract="cocoa_ice", driver_id="El_Nino", routed_read=True,
                     routed_on=frozenset({("gain_cocoa", "a")}))
    good = {"prop_id": "p-cocoa", "date": "2026-04-09", "source_key": "gain_cocoa", "text": "a"}
    bad = {"prop_id": "p-coffee", "date": "2026-05-20", "source_key": "gain_coffee", "text": "b"}
    ref: list = []
    got = R._pool_admitted([good, bad], hop, ref)
    assert got == [good] and ref == [("2026-05-20", "gain_coffee")]
    # the routing unread (every offline instrument): HEAD's admission, nothing refused
    ref2: list = []
    assert R._pool_admitted([good, bad], W.ChainHop(contract="cocoa_ice", driver_id="El_Nino"), ref2) == [good, bad]
    assert ref2 == []


def test_NL3_the_record_end_reads_the_rows_own_population():
    assert R.at_record_end({"value": 100.0 * 399.5 / 400, "n": 400})
    assert R.at_record_end({"value": 100.0 * 0.5 / 400, "n": 400})
    assert not R.at_record_end({"value": 99.7, "n": 400})               # printed "100th", not the record's end
    assert R.at_record_end({"value": 99.7})                             # no population: HEAD's printed test


def test_NL4_the_other_poles_far_edge_is_named_as_that_poles():
    bd, _got = _board("deep", False)
    seen = 0
    for r in bd.rows:
        if r.state is None:
            continue
        ph = W.hop_phase(r.driver_id, r.state)
        other = bool(ph.get("phase_driver") and ph.get("phase_in_force_driver")
                     and ph["phase_in_force_driver"] != ph["phase_driver"])
        cl = R.fan_pole_clause(r)
        assert bool(cl) == other, (r.driver_id, ph, cl)
        if cl:
            seen += 1
            assert cl.endswith("which is not the phase this reading puts in force") and "phase" in cl
    assert R.fan_pole_clause(None) == ""


def test_m2_the_backstop_cap_counts_the_short_names():
    ch = W.Chain(contract="soybean_oil_cbot",
                 hops=(W.ChainHop(contract="soybean_oil_cbot", driver_id="drought", measured=True,
                                  series_key="drought_z|soybean_oil_cbot|"),
                       W.ChainHop(contract="soybean_oil_cbot", driver_id="psd_ending_stock_su_ratio", measured=True,
                                  series_key="psd_ending_stock_su_ratio|soybean_oil_cbot|United States"),
                       W.ChainHop(contract="soybean_oil_cbot", driver_id="cot_mm_positioning", measured=True,
                                  series_key="cot_mm_positioning|soybean_oil_cbot|")),
                 terminal="soybean_meal_cbot", agreements=("undetermined", "aligned", "undetermined"))
    rh = {("soybean_oil_cbot", "drought"): {"level": 24}, ("soybean_oil_cbot", "psd_ending_stock_su_ratio"):
          {"level": 46}, ("soybean_oil_cbot", "cot_mm_positioning"): {"level": 36}}
    s = R.chain_page_sentence(ch, rh, page_markets=("malaysian_crude_palm_oil_cme",), cited=(46,))
    assert "[N46]" in s and s.startswith("One chain the data carries runs through the stocks-to-use ratio")
    # nothing cited: HEAD's own forms, byte for byte
    head = R.chain_page_sentence(ch, rh, page_markets=("malaysian_crude_palm_oil_cme",))
    assert "[N46]" not in head and head.startswith("One chain the data carries runs from")


def test_m4_the_like_state_opening_reads_its_own_two_populations():
    a = {"contract": "soybeans_cbot", "driver_id": "El_Nino", "date": "2024-01-31", "asof": "2026-09-26",
         "n_candidates": 131, "n_candidates_head": 0, "pool_rank": 1, "dims_seen": 2, "dims_declared": 3,
         "floor_year": 2015}
    nearest = R.sb_analog_header(a)
    assert "the nearest past state of this series is January 2024" in nearest and "sat like this" not in nearest
    member = R.sb_analog_header(dict(a, n_candidates_head=3, dims_seen=3))
    assert "the series sat like this in January 2024" in member
    # a header that counts like states keeps HEAD's opening, whatever the pick's own coverage
    assert "the series sat like this in January 2024" in R.sb_analog_header(dict(a, n_candidates_head=3))
    # THE SEAT IS THE POOL'S OWN (``pool_rank``, the rarity clause's fact): only the first pick is the nearest --
    # a max stanza pair renders both, and the second must not say it is (test_state_seam's two-sided pin)
    second = R.sb_analog_header(dict(a, pool_rank=2))
    assert "the second nearest past state of this series is January 2024" in second
    assert "the nearest" not in second and "sat like this" not in second
    unseated = dict(a)
    unseated.pop("pool_rank")
    assert "a past state of this series compared with it is January 2024" in R.sb_analog_header(unseated)
    hand = dict(a)
    hand.pop("n_candidates_head")
    assert "the series sat like this in January 2024" in R.sb_analog_header(hand)   # a hand-built row: HEAD


# ═══ CONTRACT HALVES ══════════════════════════════════════════════════════════════════════════════════════════
def test_Y9_a_release_window_prints_as_one():
    w = {"kind_words": "the next scheduled print", "label": "the Pacific anomaly", "what": "x",
         "next_print": "2026-10-01"}
    assert R.sb_watch(w).endswith("; next print 2026-10-01")
    w2 = dict(w, next_print_opens="2026-10-01", next_print_closes="2026-10-05")
    assert R.sb_watch(w2).endswith("; next print between 2026-10-01 and 2026-10-05")


def test_Y8_the_percentile_names_its_population_through_the_rows_producer(monkeypatch):
    st = types.SimpleNamespace(population={"first": "2015-08-01", "basis": "window", "whole": False, "n": 131})
    assert R.population_clause(types.SimpleNamespace()) == "of its own record"
    monkeypatch.setattr(ROWS, "population_words", lambda pop, book=None: "of its record since August 2015",
                        raising=False)
    assert R.population_clause(st) == "of its record since August 2015"
    assert R.population_clause(types.SimpleNamespace(population={})) == "of its own record"


def test_Y11_the_recency_line_names_its_population_and_the_page_layers_when_handed():
    bd, _got = _board("deep", False)
    head = N.recency_rows(bd, record_through="2026-03-14", tape_edge="2026-09-04")
    assert head["numbers"].startswith("read as of ") and head["numbers"].endswith("across the current readings")
    assert "the newest number here is known" in head["numbers"]              # lint's SB-L sample words lead
    lay = N.recency_rows(bd, record_through="2026-03-14", tape_edge="2026-09-04",
                         layers={"rows": ("2011-04-30", "2026-09-25", 42), "docs": ("2018-03-15", "2026-03-14", 12)})
    assert "across the forty-two figures served for this answer, the newest number was known 2026-09-25" in \
        lay["numbers"]
    assert "across the twelve dated documents" in lay["text"]
    empty = N.recency_rows(types.SimpleNamespace(recency={}, series={}, asof="2026-09-26"))
    assert "on this page" not in " ".join(empty.values())


def test_Y13_the_settled_sides_ride_the_front_price_line_and_the_call_clause():
    clause = R.sb_ask_sides({"for": 3, "against": 1, "unsettled": 2}, {"front": True})
    assert clause.startswith(R.ASK_SIDES_LEAD + ": of the readings on this market above, three toward a higher")
    assert R.sb_ask_sides({"for": 0, "against": 0, "unsettled": 4}, {}) == ""
    bd, got = _board("deep", True)
    tape = [ln for ln in got["block"].splitlines() if R.ASK_SIDES_LEAD in ln]
    assert len(tape) <= 1 and all(R.classify(ln) == ("SB-T",) for ln in tape)
    assert N.ask_call_mandate(()) == "" and "{handles}" not in N.ask_call_mandate(("[N3]",))


def test_the_new_render_keys_ride_inside_the_one_registered_key():
    from leviathan.graphrag import tracekeys as TK
    assert "watch_rows" not in TK.TRACE_RECORD_KEYS and "served_counts" not in TK.TRACE_RECORD_KEYS
