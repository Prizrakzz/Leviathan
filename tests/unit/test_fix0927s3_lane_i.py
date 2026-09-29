"""FIX SITTING 3 (2026-09-27 plan), LANE I -- THE U-7 AND U-12 INSTRUMENT HALVES, THE HELD ROWS' TL;DR HALF AND
THE COUNT'S KIND (CONTRACT Z21 / Z23 / R-I2a).

Every pin runs on REAL banked seat output: the committed arm-A fixture (tests/fixtures/instrument_census_0926/,
both cells, reduced from the six baselines). The producer keys these rows read are minted this sitting by lanes
R and A (`state_board.ask_netting`, `state_board.block_sentences`, `state_board.held_rows`, `served_counts[].kind`,
`writer_seam.mandate_census`) and are on no banked record, so a pin that needs one COPIES a fixture record and
adds that ONE contracted key -- labelled at the site; every other field is the banked page's own. The block
sentences a furniture pin adds are the render's OWN text at HEAD 26618aa0 (the board rebuilt from that page's
trace, fix_sitting_3_0927/verify/stale/board_head_s3_all.json), never words written for the pin.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from leviathan.graphrag import eval as gev

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "instrument_census_0926"
#: THE ROSTER AT HEAD 26618aa0, in order: the census APPENDS, never sorts or inserts.
_HEAD_ROSTER = ("n_sections", "intent_ok", "tldr_direction", "tldr_direction.agree [producer]", "watch_cited",
                "coverage.watch_cited [producer]", "coverage.watch_referenced [producer]",
                "coverage.events_referenced [producer]", "register_leaks", "desk_register_hits",
                "count_mismatches", "desk_register_hits.v1", "tldr_direction.declared", "tldr_direction.basis",
                "absence_binding", "prose_ceiling", "duplicate_handles", "esr_national_rows",
                "held_rows_in_claims", "window_draw")
_Z23 = ("netting_present", "furniture_count", "mandate_census.words", "mandate_census.asks",
        "mandate_census.exactly_as")


def _docs() -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(_FIX.glob("*_2026*.json"))]


def _cell(cell: str) -> list:
    return [r for d in _docs() if d["cell"] == cell for r in d["per_answer"]]


def _rec(cell: str, rid: str, mode: str = "deep") -> dict:
    for d in _docs():
        if d["cell"] == cell and d["mode"] == mode:
            for r in d["per_answer"]:
                if r["id"] == rid:
                    return copy.deepcopy(r)
    raise KeyError((cell, rid, mode))


# -- 0. THE ROSTER: FIVE ROWS APPENDED IN THE CONTRACT'S ORDER -------------------------------------------------
def test_the_five_z23_rows_are_appended_after_heads_roster_in_the_contracts_order():
    names = tuple(n for n, _k, _p in gev._INSTRUMENTS)
    assert names == _HEAD_ROSTER + _Z23
    kinds = {n: k for n, k, _p in gev._INSTRUMENTS}
    assert all(kinds[n] == "count" for n in _Z23)


def test_on_every_banked_page_the_new_rows_read_absent_never_zero_and_are_never_quoted():
    """THREAT I12-a: no banked record carries a Z23 producer key, so each new row is ABSENT on all twenty pages
    (both cells) -- never a 0 that a report could quote -- and the quoted / vacuous sets stay sitting 2's."""
    for cell in ("control", "treatment"):
        cen = gev.instrument_census(_cell(cell))
        for name in _Z23:
            c = cen["census"][name]
            assert (c["n"], c["value"], c["vacuous"], c["quoted"]) == (0, None, None, False), (cell, name)
            assert name not in cen["quoted"] and name not in cen["vacuous"]
        assert cen["census"]["netting_present"]["absent"] == {
            "state_board.ask_netting absent (no netting fact on the ask head)": 10}
        assert cen["census"]["furniture_count"]["absent"] == {
            "state_board.block_sentences absent (the block's sentences are not on the record)": 10}
        assert cen["census"]["mandate_census.words"]["absent"] == {
            "writer_seam.mandate_census absent (no board mandate census on the page)": 10}
        for k in ("netting_pages", "furniture_found", "count_kind_bound"):
            assert k not in cen                               # omitted when empty (the contract's law)
        rep = gev.instrument_report(cen)
        for name in _Z23:
            line = next(x for x in rep if x.startswith(f"- {name}:"))
            assert "ABSENT on every page" in line and "n=0)" in line, line


# -- 1. NETTING PRESENT (U-7): the TL;DR's own addresses, part by part -----------------------------------------
def test_netting_reads_each_part_the_tldr_cites_by_its_own_handle():
    """The rice treatment page's own TL;DR cites [N63] (India's exports, the reading against the warm-phase
    lean) and [N141] (the tape's top-of-window) and NOT [E39] (the 2024 export-rule document, cited only in
    the body). CONTRACT Z4's key (the only synthetic field): opposing [N63], event [E39], tape [N141]."""
    rec = _rec("treatment", "state_rice_2026_09")
    rec["state_board"]["ask_netting"] = {"opposing": [63], "event": {"handle": None, "e_handle": 39},
                                         "tape": 141}
    got = gev._netting_read(rec, None, gev._instrument_texts(rec, None)[1][0])
    assert (got["v"], got["d"]) == (2, 3)
    assert got["_page"] == {"printed": ["opposing", "event", "tape"], "netted": ["opposing", "tape"]}
    assert got["x"]["event"] == {"printed": 1, "netted": 0, "readings": 1, "readings_cited": 0,
                                 "cited_on_page": 1}                  # netted in the body, never in the TL;DR
    assert got["src"].startswith("raw_draft.postverify_tldr")


def test_a_part_of_two_readings_is_netted_only_when_the_tldr_cites_both():
    """UNDER-CLAIM: a balanced board's opposing part is the loudest reading on EACH side; citing one of them
    is not netting against both. The rice TL;DR cites [N63] and not [N51] (India's carry-in, body only)."""
    rec = _rec("treatment", "state_rice_2026_09")
    rec["state_board"]["ask_netting"] = {"opposing": [63, 51]}         # CONTRACT Z4 (synthetic key)
    got = gev._netting_read(rec, None, None)
    assert (got["v"], got["d"]) == (0, 1)
    assert got["x"]["opposing"]["readings"] == 2 and got["x"]["opposing"]["readings_cited"] == 1


def test_a_part_named_without_its_handle_is_never_credited():
    """The rice TL;DR NAMES India's carry-in ("record Indian carry-in") without its handle [N51]: the trace names
    each part by handle only, and a name the trace does not carry is never guessed -- not credited."""
    rec = _rec("treatment", "state_rice_2026_09")
    assert "carry-in" in rec["raw_draft"]["postverify_tldr"] and "[N51]" not in rec["raw_draft"]["postverify_tldr"]
    rec["state_board"]["ask_netting"] = {"opposing": [51]}              # CONTRACT Z4 (synthetic key)
    assert gev._netting_read(rec, None, None)["v"] == 0


def test_netting_reads_every_handle_spelling_the_contract_allows():
    """A handle may arrive as an int, "N63", "[N141]" or a part dict carrying the render's own `handle` /
    `e_handle` (CONTRACT Z4's render shape); a key the contract does not name is never read."""
    rec = _rec("treatment", "state_rice_2026_09")
    rec["state_board"]["ask_netting"] = {                              # CONTRACT Z4 (synthetic key)
        "opposing": [{"handle": "N63", "row_id": "x", "side": "against"}],
        "tape": "[N141]",
        "event": {"handle": None, "e_handle": "E39", "sign": "+", "row_id": "y"},
        "not_a_part": [16]}
    got = gev._netting_read(rec, None, None)
    assert (got["v"], got["d"]) == (2, 3)
    assert got["_page"]["printed"] == ["opposing", "event", "tape"]


def test_a_grouped_or_ranged_token_cites_every_member_through_the_one_handle_parser():
    """`[N62-N64]` cites 62, 63 and 64; `[N141, E39]` cites N141 and E39 (verify._handle_members) -- a writer that
    grouped its handles is credited with each, never with none."""
    rec = {"id": "g", "state_board": {"ask_netting": {"opposing": [63], "event": {"handle": None, "e_handle": 39},
                                                      "tape": 141}},                  # CONTRACT Z4 (synthetic)
           "raw_draft": {"postverify_tldr": "The lean holds against the export flow [N62-N64] and the tape and the "
                                            "rule change [N141, E39]."}}
    got = gev._netting_read(rec, None, None)
    assert (got["v"], got["d"]) == (3, 3)
    assert gev._cited_addresses("[N62-N64]") == {("N", 62), ("N", 63), ("N", 64)}


def test_netting_is_absent_where_there_is_no_part_or_no_tldr():
    rec = _rec("treatment", "state_rice_2026_09")
    rec["state_board"]["ask_netting"] = {"opposing": [], "event": {"handle": None, "e_handle": None}}
    assert gev._netting_read(rec, None, None) == {"v": None, "d": 0, "src": None,
                                                  "why": "no netting part carries a printed handle"}
    rec["state_board"]["ask_netting"] = {"tape": 141}
    rec["raw_draft"] = {}
    got = gev._netting_read(rec, None, None)
    assert got["v"] is None and got["d"] == 1 and got["why"] == "no TL;DR on the record"


def test_netting_reads_a_live_rows_post_verify_tldr_and_never_the_footer():
    body = "**TL;DR.** Lean up [N2].\n\n## Mechanism\nx [N9].\n\n## Sources\n[N9] footer label"
    live = {"q": {"id": "l1"}, "out": {"answer": body, "structured": {"tldr": "Lean up [N2].", "mechanism": "x [N9]."},
                                       "trace": {}}}
    rec = {"id": "l1", "state_board": {"ask_netting": {"opposing": [9], "tape": 2}}}   # CONTRACT Z4 (synthetic)
    got = gev._netting_read(rec, live, "Lean up [N2].\nx [N9].")
    assert (got["v"], got["d"], got["src"]) == (1, 2, "post-verify structured tldr")
    assert got["x"]["opposing"]["cited_on_page"] == 1 and got["x"]["opposing"]["netted"] == 0


# -- 2. THE FURNITURE COUNT (U-12) ------------------------------------------------------------------------------
#: THE RENDER'S OWN SENTENCES for the arm-A treatment 2024 page, at HEAD (the board rebuilt from its trace).
_BLOCK_2024 = (
    ("SB-A", "the front price here does not reach back to the past times this reading sat this far out, so the "
             "record gives no price range for the horizon"),
    ("SB-1", "[N16] 95th percentile of its own record;"),
    ("SB-1", "[N19] 95th percentile of its own record;"),
    ("SB-K", "they reach eighteen markets this question did not name;"),
    ("SB-K", "one dated action older than the lag the model allows for it."),
    ("SB-K", "CHAIN first of two, from the tropical Pacific sea-surface temperature anomaly to DCE palm olein."),
    ("SB-K", "  chain price record: the front price here does not reach back to those past times."),
    ("SB-K", "  chain price record: the front price here does not reach back to those past times."),
    ("SB-K", "  chain sides: every chain carried here points lower for this market, and none points the other way;"),
)


def _with_block(rec: dict, block=_BLOCK_2024) -> dict:
    rec["state_board"]["block_sentences"] = [{"cls": c, "text": t} for c, t in block]   # CONTRACT Z9 (synthetic)
    return rec


def test_furniture_finds_the_one_off_sentences_the_writer_carried_over_and_nothing_else():
    """The 2024 treatment page's TL;DR carries the price-record sentence reordered ("for the three-month horizon
    itself the record gives no price range, because the front price does not reach back to the past times
    this reading sat this far out") and its body "Every chain carried here points lower for this market and
    none the other way". A stock phrase inside the writer's own sentence ("the lag the model allows for it",
    "a market this question did not name") is NOT found."""
    rec = _with_block(_rec("treatment", "rv_soybeans_state_2024_03_01"))
    (body, bsrc), _p = gev._instrument_texts(rec, None)
    got = gev._furniture_read(rec, body, bsrc)
    assert [(f["cls"], f["share"]) for f in got["_found"]] == [("SB-A", 0.65), ("SB-K", 0.67)]
    assert got["_found"][0]["page"].startswith("for the three-month horizon itself the record gives no price")
    # nine sentences -> eight forms (the price record printed twice is ONE form); the percentile clause and
    # the chain price record are the block's ROW GRAMMAR (printed twice) -- counted apart, never furniture
    assert got["x"] == {"sentences": 9, "forms": 7, "untestable": 0, "row_grammar": 2, "row_grammar_found": 1,
                        "by_class": {"SB-A": 1, "SB-K": 1}}
    assert (got["v"], got["d"]) == (2, 5)


def test_a_row_clause_the_block_prints_on_several_rows_is_one_form_and_row_grammar():
    """THE FIGURES-AND-WORDS LAW: "95th percentile of its own record" is the clause every row prints beside its
    own figure; the page's "the 0th percentile of its own record [N16]" states a served figure with its words.
    The two block sentences differ only by handle and figure -> one form, row grammar, never furniture."""
    rec = _with_block(_rec("treatment", "rv_soybeans_state_2024_03_01"), _BLOCK_2024[1:3] + _BLOCK_2024[4:5])
    (body, bsrc), _p = gev._instrument_texts(rec, None)
    got = gev._furniture_read(rec, body, bsrc)
    assert gev._content_tokens(_BLOCK_2024[1][1]) == gev._content_tokens(_BLOCK_2024[2][1]) == (
        "percentile", "of", "its", "own", "record")
    assert (got["v"], got["d"], got["x"]["row_grammar"], got["x"]["row_grammar_found"]) == (0, 1, 1, 1)


def test_the_tokenizer_masks_handles_figures_dates_counts_and_a_bracket_cut_by_the_split():
    ct = gev._content_tokens
    assert ct("[N27] +1.8 degC in July 2026, 93rd percentile; three hundred twenty-six chains") == (
        "degc", "in", "july", "percentile", "chains")
    assert ct("rising in each of the last eight months [series: CBOT rice;") == (
        "rising", "in", "each", "of", "the", "last", "months")
    assert ct("CBOT corn; ICE canola] falling over the last week") == ("falling", "over", "the", "last", "week")
    assert ct("[N12] 1.8 degC;") == ("degc",) and gev._grams(ct("[N12] 1.8 degC;")) == frozenset()


def test_the_sources_footer_is_never_the_page_and_a_cut_text_drops_its_partial_word():
    body = ("**TL;DR.** A plain sentence of the writer's own.\n\n## Sources\n[N1] the front price here does not "
            "reach back to the past times this reading sat this far out")
    rec = {"state_board": {"block_sentences": [{"cls": "SB-A", "text": _BLOCK_2024[0][1]}]}}      # Z9 (synthetic)
    assert gev._furniture_read(rec, body, "served body")["v"] == 0       # found only in the footer: not found
    cut = _BLOCK_2024[0][1][:-3]                                  # "... for the hori": cut mid-word
    page = _BLOCK_2024[0][1] + "."
    whole = gev._furniture_read({"state_board": {"block_sentences": [{"cls": "SB-A", "text": cut}]}}, page, "b")
    assert whole["_found"][0]["share"] == 0.96                    # the partial word "hori" matches nothing
    rec = {"state_board": {"block_sentences": [{"cls": "SB-A", "text": cut, "sha": "0123456789ab"}]}}  # Z9 sha form
    got = gev._furniture_read(rec, page, "b")
    assert (got["v"], got["_found"][0]["share"]) == (1, 1.0)      # Z9's cut text: its partial last word dropped


def test_furniture_is_absent_where_no_block_sentence_or_no_page_is_on_the_record():
    rec = _rec("treatment", "rv_soybeans_state_2024_03_01")
    assert gev._furniture_read(rec, "x", "b")["why"].startswith("state_board.block_sentences absent")
    rec["state_board"]["block_sentences"] = []
    assert gev._furniture_read(rec, "x", "b") == {"v": None, "d": 0, "src": None,
                                                  "why": "no block sentence on the record"}
    _with_block(rec)
    assert gev._furniture_read(rec, None, None)["why"] == "no page text on the record"


def test_the_census_lists_what_furniture_and_netting_counted_and_the_report_prints_it():
    recs = _cell("treatment")
    for r in recs:
        if r["id"] == "rv_soybeans_state_2024_03_01":
            _with_block(r)
        if r["id"] == "state_rice_2026_09":
            r["state_board"]["ask_netting"] = {"opposing": [63], "tape": 141}      # CONTRACT Z4 (synthetic)
    cen = gev.instrument_census(recs)
    f, n = cen["census"]["furniture_count"], cen["census"]["netting_present"]
    assert (f["value"], f["denominator"], f["n"]) == (2, 5, 1) and f["quoted"] is False
    assert (n["value"], n["denominator"], n["n"]) == (2, 2, 1)
    assert [m["id"] for m in cen["furniture_found"]] == ["rv_soybeans_state_2024_03_01"] * 2
    assert cen["netting_pages"] == [{"id": "state_rice_2026_09", "printed": ["opposing", "tape"],
                                     "netted": ["opposing", "tape"]}]
    rep = gev.instrument_report(cen)
    assert any(x.startswith("- furniture_count: 2 of 5 (population:") and "UNTESTED, NOT A RESULT" in x
               for x in rep)
    assert any(x.startswith("  - furniture `rv_soybeans_state_2024_03_01` (SB-A, 0.65): block") for x in rep)
    assert any(x.startswith("  - netting `state_rice_2026_09`: the TL;DR netted 2 of the 2 part(s)") for x in rep)
    det = cen["details"]["furniture_count"]["totals"]
    assert det["row_grammar"] == 2 and det["by_class.SB-A"] == 1


# -- 3. THE MANDATE CENSUS (U-12, Z1's stamp) --------------------------------------------------------------------
def test_the_mandate_census_rows_read_the_stamp_and_a_constant_zero_is_named_vacuous():
    """CONTRACT Z1's `writer_seam.mandate_census` on the ten treatment pages (synthetic key, the words varied per
    page): `exactly_as` reads 0 on all ten -- the census names it VACUOUS and prints the constant, never
    quotes it; `words` varies and is quoted; `asks` carries facts required + rules as its denominator."""
    recs = _cell("treatment")
    for i, r in enumerate(recs):
        r["writer_seam"]["mandate_census"] = {"words": 900 + 10 * i, "sentences": 40, "asks": 12,
                                              "facts_required": 8, "rules": 4, "exactly_as": 0,
                                              "by_part": {"state_board": 600, "ask_call": 50}}
    cen = gev.instrument_census(recs)
    w, a, e = (cen["census"][f"mandate_census.{k}"] for k in ("words", "asks", "exactly_as"))
    assert (w["value"], w["n"], w["quoted"]) == (sum(900 + 10 * i for i in range(10)), 10, True)
    assert (a["value"], a["denominator"], a["vacuous"]) == (120, 120, True)
    assert (e["value"], e["vacuous"], e["constant"], e["quoted"]) == (0, True, 0, False)
    assert cen["details"]["mandate_census.words"]["totals"]["by_part.state_board"] == 6000
    rep = gev.instrument_report(cen)
    assert any(x.startswith("- mandate_census.exactly_as: NOT QUOTED -- VACUOUS, it read 0") for x in rep)


def test_the_mandate_census_is_absent_on_a_page_whose_seam_stamped_no_census():
    rec = _rec("treatment", "state_rice_2026_09")
    assert gev._mandate_census_read(rec, "words")["why"].startswith("writer_seam.mandate_census absent")
    rec["writer_seam"]["mandate_census"] = {"words": 10}                   # a partial stamp (synthetic)
    assert gev._mandate_census_read(rec, "asks")["why"] == "writer_seam.mandate_census.asks absent"


# -- 4. THE HELD ROWS' TL;DR HALF (Z21) --------------------------------------------------------------------------
def test_the_held_rows_tldr_half_reads_the_level_handles_where_the_key_lands():
    rec = _rec("treatment", "state_rice_2026_09")
    rec["state_board"]["retention"] = {"read": True, "keys": 3, "stamped": 2, "ms": 40}   # Y5's key (synthetic)
    head = gev._held_rows_read(rec)
    assert head["v"] is None and head["d"] == 2 and "no trace key maps a held row" in head["why"]   # HEAD's read
    rec["state_board"]["held_rows"] = [{"handle": 63, "row_id": "a"}, {"handle": 51, "row_id": "b"},
                                       {"handle": None, "row_id": "c"}]                  # CONTRACT Z21 (synthetic)
    got = gev._held_rows_read(rec)
    assert (got["v"], got["d"]) == (1, 2)                     # [N63] is in the TL;DR, [N51] only in the body
    assert got["x"] == {"held_rows": 3, "with_handle": 2, "cited_in_tldr": 1}
    rec["state_board"]["held_rows"] = [{"handle": None, "row_id": "c"}]
    assert gev._held_rows_read(rec)["why"] == "no held row carries a handle (state_board.held_rows)"


# -- 5. THE COUNT'S KIND (R-I2a) ----------------------------------------------------------------------------------
def test_without_a_kind_the_count_check_returns_heads_two_keys_byte_for_byte():
    rec = _rec("treatment", "state_rice_2026_09")
    prose = rec["raw_draft"]["postverify_mechanism"]
    pool = gev._count_pool(rec["state_board"])
    assert set(gev._count_check(prose, pool)) == {"checked", "mismatches"}
    assert gev._count_kinds(rec["state_board"]) == {}                      # banked served_counts carry no kind


def test_a_count_passed_on_one_kind_alone_under_a_shared_noun_is_listed_never_a_mismatch():
    """THE I2-a CLASS, READ: the rice draft prints "three other markets here", "thirty-four other markets" and
    "these three markets"; the block registers 3 (the chain line's markets, kind `count`) and 34 (the fan's
    markets, kind `fan_count`) under ONE noun (lane R's served_counts with `kind`, the synthetic field). Every
    such pass is listed with the kind that backed it -- the census cannot say which count the writer meant --
    and the mismatches are exactly the kind-blind check's."""
    rec = _rec("treatment", "state_rice_2026_09")
    prose = rec["raw_draft"]["postverify_mechanism"]
    sb = dict(rec["state_board"], served_counts=[{"noun": "markets", "value": 3, "text": "three", "kind": "count"},
                                                 {"noun": "markets", "value": 34, "text": "thirty-four",
                                                  "kind": "fan_count"}])
    pool = gev._count_pool(sb)
    kinds = gev._count_kinds(sb)
    assert kinds == {"market": {3: {"count"}, 34: {"fan_count"}}}
    counters = gev._count_pool({c: sb[c] for c in gev._COUNT_CONTAINERS if c in sb})
    got = gev._count_check(prose, pool, kinds=kinds, counters=counters)
    assert got["mismatches"] == gev._count_check(prose, pool)["mismatches"]
    bound = sorted((m["printed"], m["kind"]) for m in got["kind_bound"])
    assert (34, "fan_count") in bound and (3, "count") in bound
    assert all(m["noun_kinds"] == ["count", "fan_count"] for m in got["kind_bound"])
    row = gev._instrument_row(dict(rec, state_board=sb))
    assert row["count_mismatches"]["x"]["kind_bound_passes"] == len(got["kind_bound"])


# -- 6. REPORT-ONLY ------------------------------------------------------------------------------------------------
def test_the_per_answer_record_keeps_its_columns_and_the_census_rides_its_one_key():
    rec = _rec("treatment", "state_rice_2026_09")
    rec["state_board"]["ask_netting"] = {"opposing": [63]}                 # CONTRACT Z4 (synthetic)
    row = gev._instrument_row(rec)
    assert row["netting_present"]["v"] == 1
    assert "netting_present" not in rec and "furniture_count" not in rec    # never a per-answer column
