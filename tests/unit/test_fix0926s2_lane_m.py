"""FIX SITTING 2 (09-26), LANE M -- answer.py (the retrieval / bridge-query seam, the recency line, the absence
seam, and by file the "**Why.**" label, the "[43]" footer, the ceiling cut and the writer-seam literals) and
planner.py (the window draw). One test per threat of THREAT_MODEL sec 2 lane M; every pin states the claim it
keeps. No pg, no AWS, no model call.

  M-1  the evidence menu has a time axis (`planner.node_window`, `_window_draw`; CONTRACT Y10)
  M-2  the recency layers, one producer over the served sets (`_recency_layers`; Y11)
  M-3  the absence seam binds seat reads and their measured reason (`_seam_absence_claims(seat=True)`; Y12)
  M-4  the call weighed against what is priced (`_ask_sides_printed`, `_system(ask_sides=)`; Y13)
  M-5  C-I3a the declared direction (`_answer_tool(declare_direction=)`, `_pop_tldr_direction`; Y14)
  PC-5 the "**Why.**" label only with a body of its own (Y18); PC-6 the footer spells [Ek] (Y26)
  N-5  the ceiling cut, dark by default (`_ceiling_cut`, `CEILING_CUT_APPLIES`; Y20); N-1 the writer-seam
       literals in the reader's objects
  ML-a the TL;DR period re-attach on a `period_behind` row (`_nbl_period_reattach`)
"""
from __future__ import annotations

import inspect
import re

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl
from leviathan.graphrag import register as reg


@pytest.fixture(autouse=True)
def _dark_env(monkeypatch):
    for k in ("GRAPHRAG_BRIDGE_QUERY", "GRAPHRAG_EVIDENCE_BATCH", "EVIDENCE_BACKEND", "GRAPHRAG_RERANK_BACKEND",
              "GRAPHRAG_TLDR_COHERENCE", "GRAPHRAG_RECENCY_STAMP", "GRAPHRAG_RECENCY_FACTS",
              "GRAPHRAG_STATE_BOARD"):
        monkeypatch.delenv(k, raising=False)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
# M-5 (C-I3a) THE DECLARED DIRECTION
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
_HEAD_TOOL = {
    False: {"name": "emit_answer", "description": "Emit the reader-first structured answer.",
            "input_schema": {"type": "object", "properties": {
                "tldr": {"type": "string"}, "mechanism": {"type": "string"},
                "diagram_mermaid": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "object", "properties": {
                    "ref": {"type": "integer"}, "source": {"type": "string"}, "date": {"type": "string"},
                    "note": {"type": "string"}}}}},
                "required": ["tldr", "mechanism", "sources"]}},
}


def test_M5a_the_schema_is_HEADs_byte_for_byte_unless_the_board_turn_asks():
    """M5-a: the property exists only when the caller passes `declare_direction=True` (board turns)."""
    assert an._answer_tool() == _HEAD_TOOL[False]
    assert an._answer_tool(declare_direction=False) == an._answer_tool()
    assert an._answer_tool(handles=True, declare_direction=False) == an._answer_tool(handles=True)
    p = inspect.signature(an._answer_tool).parameters["declare_direction"]
    assert p.default is False and p.kind is inspect.Parameter.KEYWORD_ONLY


def test_M5d_the_enum_sits_after_tldr_and_is_required():
    for h in (False, True):
        t = an._answer_tool(handles=h, declare_direction=True)
        props = list(t["input_schema"]["properties"])
        assert props[props.index("tldr") + 1] == "tldr_direction"            # never first (TTFB, M5-d)
        assert t["input_schema"]["properties"]["tldr_direction"]["enum"] == list(an.TLDR_DIRECTION_ENUM)
        assert "tldr_direction" in t["input_schema"]["required"]
        # everything else is the flag-off schema
        base = an._answer_tool(handles=h)
        rest = {k: v for k, v in t["input_schema"]["properties"].items() if k != "tldr_direction"}
        assert rest == base["input_schema"]["properties"]
    assert an.TLDR_DIRECTION_ENUM == ("higher", "lower", "two_sided", "none")


def test_M5b_M5c_the_value_is_popped_verbatim_and_never_reaches_structured():
    st = {"tldr": "x", "tldr_direction": "higher", "mechanism": "y"}
    assert an._pop_tldr_direction(st) == "higher" and "tldr_direction" not in st
    st2 = {"tldr": "x", "tldr_direction": "Sideways-ish "}
    assert an._pop_tldr_direction(st2) == "Sideways-ish "                 # off-enum: verbatim (eval: ABSENT)
    assert an._pop_tldr_direction({"tldr": "x"}) is None
    st3 = {"tldr_direction": 3}
    assert an._pop_tldr_direction(st3) is None and "tldr_direction" not in st3
    assert an._pop_tldr_direction(None) is None


def test_M5e_declared_is_appended_at_the_tail_and_basis_tldr_agree_are_HEADs(monkeypatch):
    gr = g.CausalGraph({}, silver=set())
    assert an._tldr_direction_trace({"tldr": "x"}, gr, [], declared="higher") == {}      # flag off: nothing
    monkeypatch.setenv("GRAPHRAG_TLDR_COHERENCE", "on")
    head = an._tldr_direction_trace({"tldr": "points toward higher prices"}, gr, [])
    got = an._tldr_direction_trace({"tldr": "points toward higher prices"}, gr, [], declared="lower")
    assert list(head["tldr_direction"]) == ["basis", "tldr", "agree"]
    assert list(got["tldr_direction"]) == ["basis", "tldr", "agree", "declared"]
    assert {k: got["tldr_direction"][k] for k in ("basis", "tldr", "agree")} == head["tldr_direction"]
    assert got["tldr_direction"]["declared"] == "lower"                    # copied, never re-derived


def test_M5_both_bodies_pop_before_the_verifier_and_the_board_gate_is_the_block_marker():
    src = inspect.getsource(an._answer_l2)
    # beside the plan pop, whose position before `verify_citations` HEAD's own D-HP-7 pin (c) holds
    a, b = src.index("_plan_tok = _plan_tokens(_pop_plan(structured))"), src.index("_pop_tldr_direction(structured)")
    assert 0 < b - a < 400
    assert b < src.index("vf.verify_citations(structured")
    assert '_dd_tool_kw = {"declare_direction": True} if _state_board_block_on(vp) else {}' in src
    one = inspect.getsource(an)
    assert one.count("_declared_dir = _pop_tldr_direction(structured)") == 2


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
# PC-5 THE "**Why.**" LABEL; PC-6 THE FOOTER SPELLING
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
def test_PC5_the_label_is_printed_only_with_a_body_of_its_own_in_both_cells():
    d = {"tldr": "T.", "mechanism": "## Mechanism\nBody."}
    for sl in (False, True):
        out = an.render(dict(d), include_ledger=False, seam_lints=sl)
        assert "**Why.**" not in out and "\n## Mechanism\nBody." in out
        assert out.split("\n")[2] == "## Mechanism"                          # the heading starts its line
    plain = {"tldr": "T.", "mechanism": "Plain prose [N1]."}
    for sl in (False, True):
        assert an.render(dict(plain), include_ledger=False, seam_lints=sl) == \
            "**TL;DR.** T.\n\n**Why.** Plain prose [N1]."                   # HEAD's rule, unchanged
    # a '#' that is not the estate's heading grammar is prose, and keeps the label
    tag = {"tldr": "T.", "mechanism": "#hashtag is not a heading."}
    assert "**Why.** #hashtag" in an.render(dict(tag), include_ledger=False)


def test_PC6_the_flag_off_footer_spells_the_handle_the_body_spells():
    v = {"enabled": True, "resolved": {"4": {"source": "USDA WASDE", "date": "2021-05-12", "snippet": "Lower."},
                                       "7": {"source": "USDA WASDE", "date": "2022-05-12", "snippet": "Higher."}}}
    d = {"tldr": "A [E4].", "mechanism": "B [7].", "sources": [{"ref": 4}, {"ref": 7}]}
    foot = an._cited_sources_block(dict(d), v, [])
    assert "\n[E4] USDA WASDE (2021-05-12)" in foot                          # the body wrote [E4]
    assert "\n[7] USDA WASDE (2022-05-12)" in foot                           # the body wrote [7]: kept
    assert "\n[4] " not in foot


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
# M-4 THE CALL AND WHAT IS PRICED
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
def test_M4c_the_gate_reads_the_lead_N_prints_and_nothing_else(monkeypatch):
    from leviathan.graphrag.state import render as R
    lead = "SIDES ON THIS BOARD:"
    block = ("STATE OF THE WORLD\n- ASK [N3] soybeans 1,050 cents\n"
             f"- {lead} for [N40], against [N41], unsettled [N42]; front [N3]\n- [N9] x\n")
    monkeypatch.setattr(R, "ASK_SIDES_LEAD", lead, raising=False)
    assert an._ask_sides_printed(block) == ("[N40]", "[N41]", "[N42]", "[N3]")
    monkeypatch.setattr(R, "ASK_SIDES_LEAD", "", raising=False)
    assert an._ask_sides_printed(block) == ()
    monkeypatch.delattr(R, "ASK_SIDES_LEAD", raising=False)
    assert an._ask_sides_printed(block) == ()


def test_M4a_a_level_count_is_balanced_and_an_unread_count_carries_no_clause():
    assert an._ask_sides_balanced({"counters": {"BoardSidesFor": 3, "BoardSidesAgainst": 3}}) is True
    assert an._ask_sides_balanced({"counters": {"BoardSidesFor": 0, "BoardSidesAgainst": 0}}) is True
    assert an._ask_sides_balanced({"counters": {"BoardSidesFor": 4, "BoardSidesAgainst": 1}}) is False
    assert an._ask_sides_balanced({"counters": {}}) is None                  # unread: the caller adds no clause
    assert an._ask_sides_balanced(None) is None
    assert an._ask_sides_balanced({"counters": {"BoardSidesFor": True, "BoardSidesAgainst": 1}}) is None
    src = inspect.getsource(an._answer_l2)
    assert "if _sides_bal is not None else ()" in src


def test_M4d_the_clause_rides_the_board_branch_only_and_needs_its_producer(monkeypatch):
    from leviathan.graphrag.state import narration as N
    base = an._system()
    assert an._system(ask_sides=("[N3]",)) == base                           # board-less: invisible
    sb = an._system(state_board=True)
    assert an._system(state_board=True, ask_sides=()) == sb                   # no line printed: nothing
    got = {}

    def acm(handles, *, balanced):
        got["a"] = (handles, balanced)
        return "CALL CLAUSE."
    monkeypatch.setattr(N, "ask_call_mandate", acm, raising=False)
    assert an._system(state_board=True, ask_sides=("[N40]",), ask_sides_balanced=False) == sb + " CALL CLAUSE."
    assert got["a"] == (("[N40]",), False)
    monkeypatch.delattr(N, "ask_call_mandate", raising=False)
    assert an._system(state_board=True, ask_sides=("[N40]",)) == sb          # producer absent: no clause


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
# M-2 THE RECENCY LAYERS
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
def _call(table, metric, commodity, country, value, unit, known, period="2026/27", **extra):
    c = {"query": {"table": table, "metric": metric, "commodity": commodity, "country": country,
                   "period": period},
         "rows": [{"period": period, "value": value, "unit": unit, "knowledge_date": known}], "status": "ok"}
    c.update(extra)
    return c


def test_M2_one_producer_over_the_served_sets_each_part_omitted_when_empty():
    menu = [{"date": "2023-03-13"}, {"date": "2026-04-17"}, {"date": "1970-01-01"}, {"date": None}, "junk"]
    calls = [_call("silver_wasde", "production", "soybeans", "united_states", 1.0, "MMT", "2026-09-11"),
             _call("silver_wasde", "exports", "soybeans", "united_states", 2.0, "MMT", "2011-04-08")]
    lay = an._recency_layers(menu, calls, tape_edge="2026-09-24")
    assert lay["docs"] == ("2023-03-13", "2026-04-17", 2)
    assert lay["rows"][0] <= lay["rows"][1] and lay["rows"][2] == 2
    assert lay["tape"] == "2026-09-24"
    assert an._recency_layers([], None) == {}
    assert set(an._recency_layers(menu, None)) == {"docs"}
    # the ledger's own row range is the SAME walk (one producer)
    assert an._ledger_row_dates(calls) == (lay["rows"][1], lay["rows"][0])
    # B14: a served row whose OWN stamp falls after the as-of leaves the range and is counted, never clipped
    late = an._recency_layers(menu, calls, asof="2026-01-01")
    assert late["rows"] == ("2011-04-08", "2011-04-08", 1) and late["rows_after_asof"] == 1
    assert "rows_after_asof" not in an._recency_layers(menu, calls, asof="2026-12-31")


def test_M2c_the_flag_off_and_board_off_suffix_is_HEADs(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_RECENCY_STAMP", "on")
    head_off = an._recency_ledger_suffix("2026-03-14", asof="2026-09-07")
    assert an._recency_ledger_suffix("2026-03-14", asof="2026-09-07", layers=None) == head_off
    monkeypatch.setenv("GRAPHRAG_RECENCY_FACTS", "on")
    facts = an._recency_ledger_suffix("2026-03-14", asof="2026-09-07", n_rows=9)
    assert an._recency_ledger_suffix("2026-03-14", asof="2026-09-07", n_rows=9, layers=None) == facts
    assert an._recency_ledger_suffix("2026-03-14", asof="2026-09-07", n_rows=9, layers={}) == facts
    monkeypatch.delenv("GRAPHRAG_RECENCY_FACTS")
    lay = {"docs": ("2011-04-08", "2026-04-17", 40)}
    assert an._recency_ledger_suffix("2026-03-14", layers=lay) == head_off.replace("2026-09-07", "2026-09-07")


def test_M2a_M2b_each_board_turn_sentence_names_its_population(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_RECENCY_STAMP", "on")
    monkeypatch.setenv("GRAPHRAG_RECENCY_FACTS", "on")
    lay = {"docs": ("2011-04-08", "2026-04-17", 40), "rows": ("2011-04-01", "2026-09-25", 117),
           "tape": "2026-09-24"}
    s = an._recency_ledger_suffix("2026-04-17", asof="2026-09-26", layers=lay)
    assert "the newest was known 2026-09-25 and the oldest 2011-04-01" in s
    assert "The dated documents this answer was handed run from 2011-04-08 to 2026-04-17" in s
    assert "The price tape runs through 2026-09-24." in s
    assert s.endswith("none dates the others.")
    assert "117" not in s and "40" not in s.replace("2011-04-08", "")          # counts stay off the sentence
    assert "page" not in s and "board" not in s and "numbers here" not in s
    assert reg.register_leaks(s) == [] and reg.count_flow_words(s) == 0 and s.isascii()
    assert reg.desk_register_hits(s) == []
    one = an._recency_ledger_suffix("2026-04-17", layers={"docs": ("2026-04-17", "2026-04-17", 1)})
    assert "Each of those" not in one                                        # one layer is not a set to close
    wd = an._recency_ledger_suffix("2026-04-17", layers={"docs": lay["docs"]}, window_draw={"added": 3})
    assert "lag window" in wd and reg.desk_register_hits(wd) == []


def test_M2_the_stage2_seam_gets_the_layers_only_when_it_declares_them():
    class _Seam:
        @staticmethod
        def fill_stage2(board, *, e_start=1, evidence_ordinals=None, recency_layers=None):
            return {}

    class _Old:
        @staticmethod
        def fill_stage2(board, *, e_start=1, evidence_ordinals=None):
            return {}
    lay = an._recency_layers([{"date": "2026-01-02"}], None)
    assert an._stage2_kwargs(_Seam, ledger=None, uniq=[], recency_layers=lay)["recency_layers"] == lay
    assert "recency_layers" not in an._stage2_kwargs(_Old, ledger=None, uniq=[], recency_layers=lay)
    assert "recency_layers" not in an._stage2_kwargs(_Seam, ledger=None, uniq=[], recency_layers={})


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
# M-3 THE ABSENCE SEAM BINDS SEAT READS AND THEIR REASON
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
_DT_2024 = "US total domestic use for 2023/24 was not yet published at this as-of; the record carries no figure for it."


def _seat_calls(reason=None):
    empty = {"query": {"table": "silver_wasde", "metric": "domestic_total", "commodity": "soybeans",
                       "country": "united_states", "period": "2023"}, "rows": [], "status": "not_known"}
    if reason is not None:
        empty["absence_reason"] = reason
    served = _call("silver_wasde", "domestic_total", "soybeans", "united_states", 62.96, "MMT", "2024-02-08",
                   period="2022/23")
    prod = _call("silver_wasde", "production", "soybeans", "united_states", 4165.0, "Million Bushels",
                 "2024-02-08", period="2023/24")
    return [prod, empty, served]


def test_M3_seat_off_is_HEADs_seam():
    calls = _seat_calls("store_gap")
    rows = an._seam_row_index(calls)
    st = {"tldr": "", "mechanism": _DT_2024}
    cen = an._seam_absence_claims(st, rows, number_calls=calls)
    assert st["mechanism"] == _DT_2024
    assert cen == {"absence_claims_checked": 1, "absence_rows_appended": 0, "absence_unbound": 1}


def test_M3_E11_a_name_that_names_two_series_names_nothing():
    calls = [_call("silver_psd", "ending_stocks", "soybeans", "united_states", 1.0, "MMT", "2026-09-11"),
             _call("silver_psd", "ending_stocks", "soybeans", "brazil", 2.0, "MMT", "2026-09-11"),
             _call("silver_wasde", "domestic_total", "soybeans", "united_states", 3.0, "MMT", "2026-09-11")]
    refs = an._absence_seat_referents(calls)
    names = {n for n, _s, _i in refs}
    assert all("ending stocks" not in n for n in names)                      # two countries: dropped
    assert any("domestic use" in n for n in names)
    board_minted = dict(calls[2], _row_id="soybeans_cbot|x|y")
    assert not an._absence_seat_referents([board_minted])                     # a board call is not a seat read


def test_M3a_M3d_the_timing_phrase_is_corrected_only_against_a_measured_other_reason(monkeypatch):
    from leviathan.graphrag.numbers import agent as ag
    words = dict(ag._NO_ROWS_WHY)
    words["store_gap"] = "held in this store only under a later revision"
    monkeypatch.setattr(ag, "_NO_ROWS_WHY", words)
    for reason, expect_corrected in (("store_gap", True), ("not_yet_published", False), (None, False)):
        calls = _seat_calls(reason)
        rows = an._seam_row_index(calls)
        st = {"tldr": "", "mechanism": _DT_2024}
        cen = an._seam_absence_claims(st, rows, number_calls=calls, seat=True)
        assert cen.get("absence_bound_seat", 0) >= 1, cen
        assert cen["absence_rows_appended"] == 0                              # an empty read: TRUE, no append
        if expect_corrected:
            assert cen.get("absence_reason_corrected") == 1
            # RE-BANKED 09-27 (fix sitting 3, lane A, S2 V-2 / CONTRACT Z20 -- declared DM1): the correction writes
            # the BOOK's reader words for the measured reason (`absence_reason_words`, lane R), never the seat's
            # model-facing note; the seat's table is read only where the book declares nothing. The claim kept:
            # the timing words are corrected only against a measured OTHER reason, and only there.
            from leviathan.graphrag.state import render as _R
            _why = _R.book_words("absence_reason_words", "store_gap") or words["store_gap"]
            assert st["mechanism"] == _DT_2024.replace(
                "not yet published at this as-of", "absent from our record (%s)" % _why)
        else:
            assert st["mechanism"] == _DT_2024                                # M3-a / unread: as written
            assert cen.get("absence_reason_corrected") is None
            if reason is None:
                assert cen.get("absence_reason_unread") == 1
    # a reason the seat declares no words for: left as written, counted unread
    calls = _seat_calls("no_series_words_undeclared")
    st = {"tldr": "", "mechanism": _DT_2024}
    cen = an._seam_absence_claims(st, an._seam_row_index(calls), number_calls=calls, seat=True)
    assert st["mechanism"] == _DT_2024 and cen.get("absence_reason_unread") == 1


def test_M3_the_head_of_the_served_words_is_still_the_served_words():
    phrase = "not yet published at this as-of"
    seg = "Total domestic use is not yet published for 2026/27"
    a, b = an._absence_timing_span(seg, phrase)
    assert seg[a:b] == "not yet published"
    assert an._absence_timing_span("the figure is not yet out", phrase) is None   # 'published' missing
    assert an._absence_timing_span("unpublished yet", phrase) is None


def test_M3c_a_served_only_series_appends_its_row_only_where_the_claim_names_its_scope():
    calls = [_call("silver_psd", "production", "soybeans", "Brazil", 169.0, "MMT", "2026-09-11")]
    rows = an._seam_row_index(calls)
    st = {"tldr": "", "mechanism": "There is no figure for Brazil production this season."}
    cen = an._seam_absence_claims(st, rows, number_calls=calls, seat=True)
    assert cen["absence_rows_appended"] == 1 and "[N1]" in st["mechanism"]
    again = dict(st)
    assert an._seam_absence_claims(again, rows, number_calls=calls, seat=True)["absence_rows_appended"] == 0
    # M3-b: the one production row the page served is Brazil's -- a claim about ANOTHER scope never gets it
    other = {"tldr": "", "mechanism": "There is no figure for Argentine production this season."}
    cen2 = an._seam_absence_claims(other, rows, number_calls=calls, seat=True)
    assert cen2["absence_rows_appended"] == 0 and "[N1]" not in other["mechanism"]


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
# N-5 THE CEILING CUT (dark by default, O-S2-1) AND N-1 THE WRITER-SEAM LITERALS
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
def _long(n, h):
    return " ".join(["word"] * n) + f" [N{h}]."


def test_N5_the_cut_never_touches_the_protected_and_reports_by_default():
    mech = "\n\n".join(["## Mechanism", _long(40, 1), _long(40, 2), _long(40, 3), "- watch [N9] a bullet",
                        _long(40, 4), "no handle " * 20])
    st = {"tldr": "Call [N1].", "mechanism": mech}
    ranks = {"[N1]": 1, "[N2]": 5, "[N3]": 9, "[N4]": 0, "[N9]": 3}
    res = an._ceiling_cut(dict(st), ranks, 60, tldr_handles=(1,))
    assert res["ceiling_cut_paragraphs"] >= 1
    assert 3 in res["ceiling_cut_handles"]                                    # worst rank goes first
    assert 1 not in res["ceiling_cut_handles"]                                # the ONLY citation of a TL;DR row
    assert 4 not in res["ceiling_cut_handles"]                                # rank 0: never
    assert 9 not in res["ceiling_cut_handles"]                                # a list: never
    s2 = dict(st)
    an._ceiling_cut(s2, ranks, 60, tldr_handles=(1,))
    assert s2["mechanism"] == mech                                            # apply=False: nothing moves
    s3 = dict(st)
    got = an._ceiling_cut(s3, ranks, 60, tldr_handles=(1,), apply=True)
    assert s3["mechanism"] != mech and got["ceiling_cut_paragraphs"] >= 1
    kept = [p for p in mech.split("\n\n") if p in s3["mechanism"]]
    assert "\n\n".join(kept) == s3["mechanism"]                              # survivors byte-identical
    assert "## Mechanism" in s3["mechanism"] and "- watch [N9]" in s3["mechanism"]
    under = an._ceiling_cut(dict(st), ranks, 10_000)
    assert under["ceiling_cut_paragraphs"] == 0


def test_N5_the_build_default_is_report_only_and_the_mandate_says_so():
    assert an.CEILING_CUT_APPLIES is False
    for mode in (None, "quick", "deep", "max"):
        m = an._system_writer_seam_mandate(mode)
        assert an._WRITER_SEAM_NO_CUT in m and an._WRITER_SEAM_CUT not in m
        assert "HARD BOUND" in m and "nothing is ever cut" not in m.lower()
    ws = {"tldr": "Call [N1].", "mechanism": "\n\n".join([_long(300, 2), _long(300, 3)])}
    cen = an._ceiling_census(dict(ws), {"[N2]": 2, "[N3]": 7}, 450)
    assert "ceiling_cut_paragraphs" not in cen and cen.get("ceiling_cut_proposed_paragraphs") == 1


def test_N1_the_writer_seam_literals_speak_in_the_readers_objects():
    """Graded as the board's own literals are: register-clean, ASCII, and none of the four machinery nouns the
    completeness recon measured the writer copying ("page", "estate", "the bar", "nominated")."""
    for mode in (None, "quick", "deep", "max", "standard"):
        m = an._system_writer_seam_mandate(mode)
        assert m.isascii() and reg.register_leaks(m) == [] and reg.desk_register_hits(m) == []
        low = m.lower()
        for w in ("page", "estate", "the bar", "nominated"):
            assert not re.search(r"\b" + w + r"\b", low), w


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
# ML-a THE TL;DR PERIOD RE-ATTACH ON A `period_behind` ROW
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
class _Row:
    def __init__(self, rid, pb):
        self.contract, self.driver_id, self.series_key = rid.split("|")
        self.period_behind = pb


class _Board:
    def __init__(self, rows):
        self.rows = rows


def test_MLa_only_a_stamped_row_is_dated_and_only_when_its_period_is_unsaid(monkeypatch):
    from leviathan.graphrag.state import render as R

    class _Ident:
        def __init__(self, r):
            self.row_id = f"{r.contract}|{r.driver_id}|{r.series_key}"
    monkeypatch.setattr(R, "row_identity_for", lambda r: _Ident(r))
    rid = "soybeans_cbot|psd_su|psd.su"
    stale = _call("silver_psd", "su_ratio", "soybeans", "united_states", 11.412, "% of domestic use",
                  "2024-01-12", period="2020/21", _row_id=rid)
    fresh = _call("silver_wasde", "ending_stocks", "soybeans", "united_states", 315.0, "Million Bushels",
                  "2024-02-08", period="2023/24", _row_id="soybeans_cbot|es|wasde.es")
    board = _Board([_Row(rid, {"held": "2020/21", "newer_on": "USDA WASDE", "newer": "2023/24"}),
                    _Row("soybeans_cbot|es|wasde.es", {})])
    st = {"tldr": "The ratio sits at the 31st percentile and falling [N1]; stocks are 315 [N2].", "mechanism": ""}
    n = an._nbl_period_reattach(st, [stale, fresh], board, {}, asof="2024-03-01")
    assert n == 1
    # the sentence unit is the estate's own (`register._SENT_KEEP`): the clause is appended to the unit that
    # carries the stamped handle, before that unit's own terminator
    assert "falling [N1] (the 2020/21 reading, the newest this series holds as known on 1 March 2024; " \
           "USDA WASDE held 2023/24 by then)" in st["tldr"]
    assert "315 [N2]." in st["tldr"] and st["tldr"].count("2020/21") == 1  # an unstamped row: never dated
    st2 = {"tldr": "The ratio for 2020/21 sits at the 31st percentile [N1].", "mechanism": ""}
    assert an._nbl_period_reattach(st2, [stale], board, {}, asof="2024-03-01") == 0   # already said
    assert an._nbl_period_reattach({"tldr": "x [N1]."}, [stale], None, {}) == 0         # no board: nothing


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
# M-1 THE EVIDENCE MENU HAS A TIME AXIS (planner)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════
QUESTION = "frost substitute"
_KW = ["frost", "substitute", "acreage", "ratio", "damage", "demand"]


def _embed(texts, **k):
    return [[1.0 if kw in t.lower() else 0.0 for kw in _KW] for t in texts]


def _graph():
    def _d(id_, mech, lag):
        return cs.Driver(id=id_, type="hazard", sign="+", mechanism=mech, lag=lag)
    alpha = cs.CausalContract(contract="alpha", aliases=["alpha"],
                              drivers=[_d("frost", "frost damage", "0-2 quarters"),
                                       _d("acreage", "substitute acreage damage", "1-3 quarters")],
                              inter_commodity=[cs.InterCommodityEdge(driver_commodity="beta", relation="competes_with",
                                                                     sign="+", mechanism="frost substitute demand",
                                                                     lag="0-1 quarters")])
    beta = cs.CausalContract(contract="beta", aliases=["beta"],
                             drivers=[_d("demand", "demand rises", "0-1 quarters")])
    return g.CausalGraph({"alpha": alpha, "beta": beta}, silver=set())


class _Store:
    """A fake store the window draw can bound: `date_floor` is DECLARED, so the draw uses it. The first draw
    returns an old row per slice; a floored draw returns the store's rows inside [date_floor, asof]."""

    def __init__(self, docs):
        self.docs = docs
        self.calls: list = []

    def __call__(self, query, slice_, *, k, asof=None, near=None, date_floor=None):
        self.calls.append({"query": query, "slice": slice_, "floor": date_floor, "asof": asof})
        if date_floor is None:
            return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{slice_}/old",
                     "text": f"{slice_} old row"}]
        pool = [d for d in self.docs.get(slice_, []) if date_floor <= d["date"] <= str(asof)[:10]]
        return pool[:k]


_ASOF = "2026-09-26"


def _grounded(store, *, bridge=True, asof=_ASOF):
    gr = _graph()
    sg = pl.grounded_subgraph(QUESTION, gr, embed=_embed, route_fn=lambda q, graph: ["alpha"], tau=0.35, depth=1)
    pl.ground(sg, QUESTION, gr, retrieve=store, silver_lookup=None, driver_slices={"frost", "acreage", "demand"},
              probe_cap=0, asof=asof, bridge_query=bridge)
    return sg, gr


def test_M1e_the_window_is_the_nodes_own_band_and_the_floor_its_cards_print(monkeypatch):
    gr = _graph()
    seed = pl.GroundedNode(kind="contract", id="alpha", contract="alpha", depth=0, relevance=1.0)
    w = pl.node_window(seed, gr, asof=_ASOF)
    # the seed's width is the LOWER MEDIAN of its drivers' declared far edges ([6, 9] months -> 6), never the
    # widest (a single slow driver would make every document about the market read as current)
    assert w["opens"] == "2026-03-26" and w["band_months"] == 6 and w["basis"] == "lag_band"
    drv = pl.GroundedNode(kind="driver", id="frost", contract="alpha", depth=1, relevance=0.9)
    drv.prior = pl._prior(gr, drv)
    monkeypatch.setattr(pl, "_node_cadence_days", lambda n, reg=None: 365.0 / 12.0)
    w2 = pl.node_window(drv, gr, asof=_ASOF)
    assert w2["opens"] == "2026-03-26" and w2["floor_days"] == 31 and w2["basis"] == "card_cadence"
    monkeypatch.setattr(pl, "_node_cadence_days", lambda n, reg=None: None)
    w3 = pl.node_window(drv, gr, asof=_ASOF)
    assert w3["basis"] == "lag_band" and w3["opens"] == "2026-03-26" and w3["floor_days"] == 184
    none_node = pl.GroundedNode(kind="driver", id="x", contract="alpha", depth=1, relevance=0.5)
    none_node.prior = {"lag": "not a band"}
    assert pl.node_window(none_node, gr, asof=_ASOF) == {}                   # neither: counted, never typed
    assert pl.node_window(seed, gr, asof="") == {}


def test_M1_a_stale_seed_gains_its_window_rows_after_its_own(monkeypatch):
    monkeypatch.setattr(pl, "_node_cadence_days", lambda n, reg=None: None)
    docs = {"alpha": [{"date": "2026-04-17", "source": "USDA FAS GAIN", "source_key": "text/source=usda_gain/"
                       "country=MY/publication_date=20260417/x", "text": "the Malaysia oilseeds annual"},
                      {"date": "2026-09-01", "source": "WB", "source_key": "text/source=wb_cmo/release=2026-09/x",
                       "text": "a month-floored outlook", "date_kind": "key_month"}]}
    store = _Store(docs)
    sg, _gr = _grounded(store)
    seed = next(n for n in sg.nodes if n.depth == 0)
    assert seed.evidence[0]["source_key"] == "s3://alpha/old"                # the first draw keeps its place
    keys = [h["source_key"] for h in seed.evidence]
    assert any("20260417" in k for k in keys)                                # M1-f: the seed is in the population
    assert not any("release=2026-09" in k for k in keys)                     # M1-a: a month floor not yet closed
    wd = sg.trace["bridge_query"]["window_draw"]
    assert set(wd) >= {"nodes", "stale", "added", "statements", "ms", "floor_unknown", "per_node"}
    assert wd["added"] >= 1 and wd["stale"] >= 1
    assert any(c["floor"] for c in store.calls) and all(c["query"] for c in store.calls)
    # the SAME query text per node on both draws (M1-c)
    first = {c["slice"]: c["query"] for c in store.calls if c["floor"] is None}
    for c in store.calls:
        if c["floor"] is not None:
            assert c["query"] == first[c["slice"]]


def test_M1b_nothing_is_removed_or_reordered_and_duplicates_are_not_added(monkeypatch):
    monkeypatch.setattr(pl, "_node_cadence_days", lambda n, reg=None: None)
    dup = {"date": "2021-07-20", "source": "GAIN", "source_key": "s3://alpha/old", "text": "alpha old row"}
    store = _Store({"alpha": [dup]})
    sg, _ = _grounded(store, asof="2021-08-01")
    seed = next(n for n in sg.nodes if n.depth == 0)
    assert [h["source_key"] for h in seed.evidence] == ["s3://alpha/old"]     # a window row already held: not added


def test_M1g_flag_off_and_a_retriever_that_cannot_bound_the_axis_move_nothing(monkeypatch):
    monkeypatch.setattr(pl, "_node_cadence_days", lambda n, reg=None: None)
    store = _Store({"alpha": [{"date": "2026-04-17", "source": "x", "source_key": "k", "text": "t"}]})
    sg, _ = _grounded(store, bridge=False)
    assert "bridge_query" not in sg.trace and all(c["floor"] is None for c in store.calls)

    class _NoFloor:
        def __call__(self, query, slice_, *, k, asof=None, near=None):
            return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{slice_}", "text": slice_}]
    sg2, _ = _grounded(_NoFloor())
    assert "window_draw" not in sg2.trace["bridge_query"]                    # no seam: no draw, no stamp


def test_M1_the_fetcher_takes_only_a_declared_floor():
    def a(query, slice_, *, k, asof=None, near=None, date_floor=None):
        return []

    def b(query, slice_, *, k, asof=None, near=None, **kw):
        return []
    assert pl._window_fetcher(a)[0] == "retriever"
    assert pl._window_fetcher(b) == (None, "no_floor_seam")                  # a catch-all is not a declaration
