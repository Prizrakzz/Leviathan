"""LANE E -- THE WRITER SEAM: what leaves the writer is CORRECTED, never deleted.

WHAT THIS DECK HOLDS, in the two halves every dark-lane deck in this estate holds:

  FLAG OFF  -- `_system()` renders HEAD's bytes on every cell this lane can reach, `render()` and
               `_cited_sources_block()` take HEAD's branch with their new kwargs defaulted, and
               `_document_source_rows` still yields the 2-tuple two other decks unpack. No lint runs,
               no trace key is written, no model call is made (there is none to make: every pass here
               is deterministic).

  FLAG ON    -- every correction is asserted ON THE SMOKE'S OWN SENTENCES. The fixtures below are
               verbatim spans of the five served bodies of the 2026-09-16 in-VPC pre-arm smoke
               (`prearm_smoke_0916/answers/`), which is real-seat prose no rule here was designed
               against sentence by sentence -- the rules were written from the graders' quoted defects
               and then run over all ten documents (five served + five `raw_draft`), where they made
               ZERO false corrections. A hand-built case appears only as an ADVERSARIAL twin beside a
               real one, never as the only evidence for a rule.

THE LAW THIS DECK EXISTS TO PIN, above every individual correction: NOTHING HERE DELETES. Every pass
either substitutes a span for the cited row's own words or inserts a clause, so on any input no field
may get shorter, no `[N]`/`[E]` handle may be lost and no digit may be lost. That is asserted over the
whole fixture corpus in one place (`test_no_pass_ever_shortens_a_field_or_loses_a_handle_or_a_digit`).

NOTHING HERE READS OR WRITES AN ENVIRONMENT VARIABLE except through `monkeypatch`, and every flag-off
assertion asserts the DEFAULT, so a runner with GRAPHRAG_STATE_BOARD set cannot green them.
"""
from __future__ import annotations

import inspect
import itertools
import re

from leviathan.graphrag import answer as an
from leviathan.graphrag import register as reg
from leviathan.graphrag import response_contracts as rc

ASOF = "2026-09-16"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# fixtures -- verbatim spans of the five served bodies, and the rows they cite
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _call(table, metric, commodity, country, period, value, unit, known, asof=ASOF):
    """One numbers-agent call record in the shape `cit.from_number` renders the footer from."""
    return {"query": {"table": table, "metric": metric, "commodity": commodity,
                      "country": country, "period": period, "asof": asof},
            "rows": [{"value": value, "unit": unit, "knowledge_date": known}], "status": "ok"}


def _psd(commodity, period, value, unit, known):
    return _call("silver_psd", "area harvested", commodity, "United States", period, value, unit, known)


#: the max turn's harvested-area pair: [N42] the level, [N44] its own percentile. Their rendered label
#: HEADS are byte-identical, which is the join `_seam_percentiles` keys on.
MAX_ROWS = [None] * 44
MAX_ROWS[41] = _psd("soybeans_cbot", "MY2026", 34.755, "M ha", "2026-09-11")          # [N42]
MAX_ROWS[43] = _psd("soybeans_cbot", "MY2026", 91, "percentile", "2026-09-11")        # [N44]
MAX_ROWS[32] = _call("silver_psd", "stocks to use", "soybeans_cbot", "United States",  # [N33]
                     "MY2026", 10.72, "%", "2026-09-11")
MAX_ROWS[34] = _call("silver_psd", "stocks to use", "soybeans_cbot", "United States",  # [N35]
                     "MY2026", 23, "percentile", "2026-09-11")

#: the corn/wheat turn's [N42] -- a SOFT RED WINTER row the TL;DR called spring wheat.
CW_ROWS = [None] * 42
CW_ROWS[41] = _psd("srw wheat", "MY2026", 1, "percentile", "2026-09-11")               # [N42]

#: the palm/rape turn's MPOB closing-stocks row, 77 days stale at this as-of.
MPOB_ROWS = [None] * 61
MPOB_ROWS[60] = _call("silver_mpob", "closing stocks", "palm oil", None, None,         # [N61]
                      2.62832, "MMT", "2026-07-01")

#: the ONI row: FRESH by vintage (known 2026-09-05) and a JULY reading -- the grader's "the January
#: ONI printed undated" class, where the knowledge date alone says nothing is wrong.
ONI_ROWS = [None] * 23
ONI_ROWS[22] = _call("silver_noaa_oni", "ONI anomaly", None, "global", "MY2026-07",    # [N23]
                     1.8, "degC", "2026-09-05")


def _rows(calls):
    return an._seam_row_index(calls)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1. THE FLAG-OFF ARM -- HEAD's bytes, on every surface this lane touches
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_persona_leg_rides_state_board_and_no_flag_off_cell_carries_it():
    """THE CENSUS, not a spot check: over every combination of the legs this lane can reach, a cell
    with all four board-lane flags OFF renders WITHOUT the writer-seam mandate and is identical to the
    same cell with `prose_mode` unset -- so the new keyword cannot move one byte of a control turn."""
    lit = an._SYSTEM_WRITER_SEAM.split("{ceiling}")[0][-60:]
    assert lit and lit in an._system_writer_seam_mandate("quick")
    cells = off = on = 0
    for ep, rec, out_, h, prov, cw, sb, dr, ws, rl, pm in itertools.product(
            (None, True, False), (False, True), (False, True), (False, True), (False, True),
            (False, True), (False, True), (False, True), (False, True), (False, True),
            (None, "quick", "max")):
        s = an._system(episodes=ep, recency=rec, outlook=out_, handles=h, provenance=prov,
                       cascade_walk=cw, state_board=sb, desk_register=dr, watch_selection=ws,
                       register_licence=rl, prose_mode=pm)
        cells += 1
        if not any((sb, dr, ws, rl)):
            off += 1
            assert lit not in s
            assert s == an._system(episodes=ep, recency=rec, outlook=out_, handles=h,
                                   provenance=prov, cascade_walk=cw)      # `prose_mode` is inert
        else:
            on += 1
            assert (lit in s) is bool(sb)                                 # rides the BOARD's flag
    assert cells == 4608 and off == 288 and on == 4320


def test_the_leg_is_a_pure_append_after_the_board_mandate_and_before_the_other_two():
    """POSITION IS PINNED IN THREE DECKS AND THEREFORE HERE. `test_state_narration` asserts the desk
    leg is a pure append onto `_system(state_board=True)` and `test_state_seam` asserts the same shape
    for the selection clause, so a leg landing AFTER either would red both with no defect behind it."""
    from leviathan.graphrag.state import narration as sn
    from leviathan.graphrag.state import watch as sw
    base = an._system(state_board=True)
    assert base.endswith(an._system_writer_seam_mandate(None) + rc.directive(None, state_board=True))
    # RE-BANKED 09-24 (CONTRACT K19, declared B1 cell): under the register the board's own mandate
    # speaks the record's reader-facing name ("this page") -- the leg is otherwise the same pure append.
    # RE-BANKED 09-25 (close-out lane AT, AT-4 -- declared B1 move): the persona's fork clause speaks the
    # register table's words (`answer._desk_fork_words`), the one substitution the register leg makes.
    assert an._system(state_board=True, desk_register=True) == \
        an._desk_fork_words(base.replace(sn.state_board_mandate(), sn.state_board_mandate(desk=True))) \
        + sn.desk_register_mandate(state_board=True)
    assert (an._system(state_board=True, watch_selection=True)
            == base.replace(sn.MANDATE_WATCH_HEAD_RX, sn.MANDATE_WATCH_NONOBVIOUS)
            + sw.WATCH_SELECTION_CLAUSE)
    # ...and it sits ABOVE `_SYSTEM_HANDLES`, which keeps the last word because it NARROWS number rules
    both = an._system(state_board=True, handles=True)
    assert both.index(an._SYSTEM_WRITER_SEAM.split("{ceiling}")[0][-60:]) < both.index(an._SYSTEM_HANDLES)


def test_the_mandate_literal_is_graded_exactly_as_the_boards_own_is():
    """A shipped literal's register trip must be a BUILD failure here and never a stripped answer at
    serve time -- `state/lint.py`'s own reason for grading the board mandate, applied to this one."""
    from leviathan.graphrag.state import narration as sn
    for mode in (None, "quick", "deep", "max", "standard", "esc_r", "quick_hp"):
        m = an._system_writer_seam_mandate(mode)
        m.encode("ascii")                                    # ASCII-only; the console is cp1252
        assert "{" not in m and "}" not in m                 # the slot is filled by the producer
        assert reg.register_leaks(m) == []
        assert reg.count_flow_words(m) == 0
        assert reg.count_valuation_words(m) == 0
        assert not reg._LANE_B_ADJ.search(m)
        assert sn.BANNED_RECENCY_PHRASE not in m
        # A BAN WITH NO REPLACEMENT IS HOW A WRITER LOSES A FACT RATHER THAN A WORD (the desk mandate's
        # own doctrine): this leg must not teach the instrument vocabulary the desk lint charges.
        assert reg.count_desk_register(m) == 0, reg.desk_register_hits(m)


def test_render_and_the_footer_take_HEADs_branch_with_the_kwarg_off():
    """Both new kwargs DEFAULT FALSE and both are keyword-only, so every existing caller -- the FE
    render, the dossier lane, the eval replays, both serving bodies with the board flag off -- is
    byte-identical without being edited."""
    for fn, name in ((an.render, "seam_lints"), (an._cited_sources_block, "seam_lints")):
        p = inspect.signature(fn).parameters[name]
        assert p.default is False and p.kind is inspect.Parameter.KEYWORD_ONLY
    d = {"tldr": "Corn is thin [N1].", "mechanism": "## Mechanism\nBody [N2].\n\n## Cross-commodity\n"}
    assert an.render(dict(d), include_ledger=False) == \
        an.render(dict(d), include_ledger=False, seam_lints=False)
    assert an.render(dict(d), include_ledger=False).startswith("**TL;DR.** Corn is thin [N1].\n\n"
                                                               "**Why.** ## Mechanism")
    v = {"enabled": True, "resolved": {"4": {"source": "USDA WASDE", "date": "2021-05-12",
                                             "snippet": "Lower supplies."}}}
    dd = {"tldr": "A [E4] and [N1].", "mechanism": "B.", "sources": [{"ref": 4}]}
    calls = [_call("silver_wasde", "average farm price", "soybeans", "united_states",
                   "MY2026/27", 12, "$/bu", "2026-09-11")]
    assert an._cited_sources_block(dict(dd), v, calls) == \
        an._cited_sources_block(dict(dd), v, calls, seam_lints=False)
    assert "[4] USDA WASDE (2021-05-12)" in an._cited_sources_block(dict(dd), v, calls)
    assert "= 12 $/bu" in an._cited_sources_block(dict(dd), v, calls)


def test_document_source_rows_still_yields_the_two_tuple_two_other_decks_unpack():
    """`keys=True` is opt-in. `test_cycle10_no_rewrites` and `test_dhp_renderer` unpack `(ref, row)`,
    and CYCLE-10 FIX 3's ONE-walk rule means this function must keep serving all three readers."""
    p = inspect.signature(an._document_source_rows).parameters["keys"]
    assert p.default is False and p.kind is inspect.Parameter.KEYWORD_ONLY
    v = {"enabled": True, "resolved": {"4": {"source": "USDA WASDE", "date": "2021-05-12",
                                             "snippet": "Lower supplies."}}}
    d = {"tldr": "A [E4].", "mechanism": "B.", "sources": [{"ref": 4}]}
    two = an._document_source_rows(d, v)
    four = an._document_source_rows(d, v, keys=True)
    assert [len(t) for t in two] == [2] and [len(t) for t in four] == [4]
    assert [t[:2] for t in four] == two                       # the emission decision does not move
    assert an._emitted_evidence_refs(d, v) == {"4"}           # ...and the prune's keys do not either


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2. THE TL;DR -- the only line a PM forwards
# ══════════════════════════════════════════════════════════════════════════════════════════════════
#: VERBATIM, the max turn's served TL;DR (`max_rv_soybeans_state_2026_09_07.md`, line 5).
MAX_TLDR = ("Reading the data as of 2026-09-16, the soybean balance tilts modestly toward higher "
            "prices over the next three months: the US stocks-to-use buffer sits at 10.72% [N33], "
            "past the line the desk calls tight and falling three marketing years running, and the "
            "crush is bidding hard at 2.6 USD/bu [N36] - but a record-high harvested area of 34.76 M "
            "ha [N42] and an export pace in the 6th percentile of its own record [N29] are the "
            "offsetting legs, and the export leg is the one that can flip the read.")


def test_the_superlative_is_replaced_by_the_rank_its_OWN_cited_row_carries():
    """THE SMOKE CASE, and a grader's words: "a record-high harvested area of 34.76 M ha [N42]" --
    where [N42]'s own sibling row [N44] reads `= 91 percentile`."""
    d = {"tldr": MAX_TLDR, "mechanism": ""}
    rows = _rows(MAX_ROWS)
    cen = an._seam_tldr_consistency(d, rows, an._seam_percentiles(rows))
    assert cen["superlatives_corrected"] == 1 and cen["superlatives_seen"] == 1
    assert "a 91st-percentile harvested area of 34.76 M ha [N42]" in d["tldr"]
    assert "record-high" not in d["tldr"]
    # ...and NOTHING ELSE MOVED: same handles, same digits, same length but for the substitution.
    assert re.findall(r"\[N\d+\]", d["tldr"]) == re.findall(r"\[N\d+\]", MAX_TLDR)
    assert "10.72%" in d["tldr"] and "2.6 USD/bu" in d["tldr"] and "6th percentile" in d["tldr"]


def test_the_rank_is_bound_by_PROXIMITY_and_not_by_the_first_handle_in_the_line():
    """THE REGRESSION FOR A MEASURED FALSE CORRECTION. The first cut of this rule took "the first
    cited handle in the sentence"; this TL;DR is ONE sentence carrying four handles, and it printed
    "a 23rd-percentile harvested area" -- the STOCKS-TO-USE rank, sixty words earlier, on the
    harvested-area claim. A correction that names the wrong row is worse than the word it replaced."""
    d = {"tldr": MAX_TLDR, "mechanism": ""}
    rows = _rows(MAX_ROWS)
    assert an._seam_percentiles(rows)[rows[33]["head"]] == 23      # the decoy IS on the page
    an._seam_tldr_consistency(d, rows, an._seam_percentiles(rows))
    assert "23rd-percentile" not in d["tldr"]
    # and the binder itself, stated directly: forward first from the claim, backward for a lag
    line = "Area [N42], 91st percentile [N44], loosens supply with a lag. Sales [N27] fell."
    assert an._seam_bound(line, line.index("loosens"))[0] == 27
    assert an._seam_bound(line, line.index("loosens"), forward=False)[0] == 44


def test_a_reading_that_really_is_at_its_record_keeps_its_word():
    """The fence CORRECTS a contradiction and is silent otherwise: the max turn's own fund length is
    at the 100th percentile and its superlative stands. Under-claiming is the only safe direction."""
    rows = _rows(MAX_ROWS + [_psd("soybeans_cbot", "MY2026", 100, "percentile", "2026-09-11")])
    d = {"tldr": "Fund length is at a record high [N45].", "mechanism": ""}
    cen = an._seam_tldr_consistency(d, rows, an._seam_percentiles(rows))
    assert cen["superlatives_seen"] == 1 and cen["superlatives_corrected"] == 0
    assert d["tldr"] == "Fund length is at a record high [N45]."
    # ...and with no rank on the page at all, nothing happens either
    d2 = {"tldr": "A record-high area [N42].", "mechanism": ""}
    an._seam_tldr_consistency(d2, _rows([MAX_ROWS[41]] + [None] * 41), {})
    assert d2["tldr"] == "A record-high area [N42]."


def test_the_estates_own_house_phrasing_is_never_charged_as_a_superlative():
    """`record` is the estate's own word for a series' history and appears 38 times across the ten
    smoke documents WITHOUT ONE superlative claim. A bare `record` is therefore never charged; only
    the four shapes that can only be a maximum are."""
    rows = _rows(MAX_ROWS)
    pcts = an._seam_percentiles(rows)
    for clean in ("the 91st percentile of its own record [N42]",
                  "92nd percentile of its own 250-session record [N42]",
                  "the record carries no figure for those scopes [N42]",
                  "the record does not settle it [N42]",
                  "top decile of their own record and falling [N42]"):
        d = {"tldr": clean, "mechanism": ""}
        cen = an._seam_tldr_consistency(d, rows, pcts)
        assert cen["superlatives_seen"] == 0, clean
        assert d["tldr"] == clean


def test_the_class_word_is_replaced_by_the_class_the_row_names():
    """THE SECOND SMOKE CASE, verbatim from `quick_rv_corn_wheat.md`: "a spring wheat area reading at
    the 1st percentile of its own record [N42]", where [N42]'s head reads `... CBOT srw wheat ...`.
    The body of that same answer had it right four lines down; the TL;DR is the line that travels."""
    tl = ("but the wheat balance sheet itself, plus a spring wheat area reading at the 1st percentile "
          "of its own record [N42], leaves wheat the follower, not the leader.")
    d = {"tldr": tl, "mechanism": ""}
    rows = _rows(CW_ROWS)
    cen = an._seam_tldr_consistency(d, rows, an._seam_percentiles(rows))
    assert cen["classes_corrected"] == 1
    assert "a soft red winter wheat area reading at the 1st percentile" in d["tldr"]
    assert "spring wheat" not in d["tldr"]
    # AN UNKNOWN CLASS ON EITHER SIDE CHANGES NOTHING -- the closed table is the whole fence
    d2 = {"tldr": "a barley area reading [N42]", "mechanism": ""}
    an._seam_tldr_consistency(d2, rows, an._seam_percentiles(rows))
    assert d2["tldr"] == "a barley area reading [N42]"
    # ...and a TL;DR that already agrees with its row is untouched
    d3 = {"tldr": "soft red winter wheat area [N42]", "mechanism": ""}
    assert an._seam_tldr_consistency(d3, rows, an._seam_percentiles(rows))["classes_corrected"] == 0
    # ...and "hard red spring wheat" is never read as the substring "spring wheat"
    assert an._seam_class_of("hard red spring wheat area")[0] == "hard red spring wheat"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3. STALENESS -- two clocks, one clause
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_MPOB_case_a_stale_row_spoken_as_a_current_movement_gets_its_read_date():
    """A grader's words: "Malaysian closing stocks are building" on a 2026-07-01 row. Verbatim span of
    `quick_rv_palm_rapeoil.md`."""
    s = ("Malaysian closing stocks were 2.62832 MMT [N61] and rising in each of the last 4 months")
    d = {"tldr": "", "mechanism": s}
    cen = an._seam_stale_figures(d, _rows(MPOB_ROWS), ASOF)
    assert cen["stale_rows_dated"] == 1 and cen["stale_sentences"] == 1
    # RE-BANKED 09-23 FIX ROUND -- D3 known-date + period correction (09-23 recon palm_rapeoil F2; FIX.md O-3): the
    # July MPOB print is a data_date card read, known 2026-08-13 (+43-day lag), and its month clause now rides.
    assert d["mechanism"].endswith("(the 2026-07 reading, read 2026-08-13)")
    assert "2.62832 MMT [N61]" in d["mechanism"]


def test_the_ONI_case_a_fresh_VINTAGE_on_a_stale_MONTH_is_dated_by_its_reading():
    """The second clock, and the grader's "the January ONI printed undated": the row is fresh by
    vintage (known 2026-09-05, eleven days) and is a JULY reading. The knowledge date alone says
    nothing is wrong, so the clause names the month FIRST and the vintage second."""
    d = {"tldr": "", "mechanism": "Tropical Pacific +1.8 degC [N23], rising eight months running"}
    cen = an._seam_stale_figures(d, _rows(ONI_ROWS), ASOF)
    assert cen["stale_rows_dated"] == 1
    assert d["mechanism"].endswith("(the 2026-07 reading, read 2026-09-05)")


def test_a_dated_line_a_copula_and_a_row_already_read_are_all_left_alone():
    """THE THREE LEGS, each falsified on its own. A line that carries its own date needs no
    correction; a sentence with no movement verb is not a currency claim; and a row is dated ONCE per
    page, not once per sentence that mentions it."""
    rows = _rows(MPOB_ROWS)
    # (1) the LINE carries a date -- and the unit is the LINE, not the `_SENT_KEEP` chunk, so a unit
    #     that opens on a heading and runs into a dated bullet is still dated
    d = {"tldr": "", "mechanism": "## The record\n- Stocks 2.62832 MMT [N61] rising, read 2026-07-01."}
    assert an._seam_stale_figures(d, rows, ASOF)["stale_sentences"] == 0
    # (2) no movement verb: the copula is ordinary English for stating a fact, not a claim about NOW
    d2 = {"tldr": "", "mechanism": "Closing stocks are 2.62832 MMT [N61]"}
    assert an._seam_stale_figures(d2, rows, ASOF)["stale_sentences"] == 0
    # (3) ONCE PER ROW across the page
    d3 = {"tldr": "", "mechanism": "Stocks [N61] rising. Stocks [N61] building. Stocks [N61] easing."}
    assert an._seam_stale_figures(d3, rows, ASOF)["stale_rows_dated"] == 1
    # RE-BANKED 09-23 FIX ROUND -- D3 known-date + period correction (09-23 recon palm_rapeoil F2; FIX.md O-3): the
    # July MPOB print is a data_date card read, known 2026-08-13 (+43-day lag), and its month clause now rides.
    assert d3["mechanism"].count("(the 2026-07 reading, read 2026-08-13)") == 1


def test_a_fresh_weekly_row_is_never_dated_and_an_annual_row_always_is():
    """21 days for a weekly or monthly series (the per-layer recency window); ZERO for an annual one,
    which is never "current" in a present-tense sentence by construction."""
    fresh = [_call("silver_esr", "shipments", "soybeans", "US", None, 311.85, "1000 MT", "2026-09-10")]
    d = {"tldr": "", "mechanism": "Shipments 311.85 [N1] falling"}
    assert an._seam_stale_figures(d, _rows(fresh), ASOF)["stale_rows_dated"] == 0
    annual = [_call("silver_psd", "stocks to use", "corn_cbot", "US", "MY2026", 0.12, "ratio",
                    "2026-09-11")]
    d2 = {"tldr": "", "mechanism": "The ratio [N1] is tightening"}
    assert an._seam_stale_figures(d2, _rows(annual), ASOF)["stale_rows_dated"] == 1


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 4. THE LAG WINDOW vs THE HORIZON
# ══════════════════════════════════════════════════════════════════════════════════════════════════
#: VERBATIM, the max turn's loosening-legs bullet.
LAG_LINE = ("- **The loosening legs.** Harvested area of 34.76 M ha [N42], 91st percentile of its own "
            "record [N44], loosens supply with a two-to-four-quarter lag, and its window (June to "
            "December 2026) is inside the horizon.")


def test_the_declared_lag_window_is_computed_from_the_rows_own_date():
    """The smoke's own sentence, on a row known 2026-09-11: two quarters out is 2027-03-11 and four is
    2027-09-11, so the window opens three months AFTER a three-month horizon closes."""
    d = {"tldr": "", "mechanism": LAG_LINE}
    cen = an._seam_lag_windows(d, _rows(MAX_ROWS), ASOF, 3)
    assert cen["lag_windows_checked"] == 1 and cen["lag_windows_corrected"] == 1
    assert ("(the declared two-to-four-quarter lag counted from 2026-09-11 runs March to September "
            "2027)") in d["mechanism"]
    # ROUND 2 (review MINOR-3): THE WORD IS CORRECTED, not contradicted. The first cut appended the
    # computed window beside the writer's own verdict and left the served sentence asserting BOTH.
    assert "is outside the horizon" in d["mechanism"]
    assert "is inside the horizon" not in d["mechanism"]
    # ...and the CLAUSE, the FIGURES and the HANDLES are all still there: one word moved, nothing went
    assert "Harvested area of 34.76 M ha [N42], 91st percentile of its own record [N44]" in d["mechanism"]
    assert "(June to December 2026)" in d["mechanism"]
    assert re.findall(r"\[N\d+\]", d["mechanism"]) == re.findall(r"\[N\d+\]", LAG_LINE)


def test_the_lag_rule_is_silent_when_the_prose_has_it_right_and_when_it_has_no_horizon():
    """A fence that annotated every correct sentence would be padding, which is what the persona's own
    anti-padding rule exists to stop. And with no horizon asked for there is no assertion to check."""
    ok = LAG_LINE.replace("a two-to-four-quarter lag", "a zero-to-one-quarter lag")
    d = {"tldr": "", "mechanism": ok}
    cen = an._seam_lag_windows(d, _rows(MAX_ROWS), ASOF, 3)
    assert cen["lag_windows_checked"] == 1 and cen["lag_windows_corrected"] == 0
    assert d["mechanism"] == ok
    d2 = {"tldr": "", "mechanism": LAG_LINE}
    assert an._seam_lag_windows(d2, _rows(MAX_ROWS), ASOF, None)["lag_windows_checked"] == 0
    assert d2["mechanism"] == LAG_LINE
    # ...and the OTHER direction is corrected too
    d3 = {"tldr": "", "mechanism": ok.replace("is inside the horizon", "is outside the horizon")}
    assert an._seam_lag_windows(d3, _rows(MAX_ROWS), ASOF, 3)["lag_windows_corrected"] == 1
    assert "is inside the horizon" in d3["mechanism"] and "is outside" not in d3["mechanism"]
    assert "runs September to December 2026)" in d3["mechanism"]


def test_a_quarter_is_three_calendar_months_and_never_ninety_days():
    import datetime as dt
    d = dt.date(2026, 9, 11)
    assert an._seam_add_months(d, 6) == dt.date(2027, 3, 11)
    assert an._seam_add_months(d, 12) == dt.date(2027, 9, 11)
    assert an._seam_add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)   # clamps, never raises
    assert an._seam_window_words(dt.date(2027, 3, 1), dt.date(2027, 9, 1)) == "March to September 2027"
    assert an._seam_window_words(dt.date(2026, 12, 1), dt.date(2027, 3, 1)) == "December 2026 to March 2027"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 5. THE DECLINE -- about OUR record, never about the world
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_precoverage_decline_stops_being_a_false_statement_about_the_world():
    """All three spellings are verbatim from three different smoke answers, and MATIF rapeseed traded
    in every window all three declined. The verb phrase moves; the sentence, its handles, its figures
    and its closing clause do not."""
    for src, want in (
        ("MATIF rapeseed and CME palm oil each have no figure on this window because it predates "
         "those boards' own price history - a stated limit, not a zero.",
         "because it reaches back before our own price history for those markets - a stated limit"),
        ("The MATIF rapeseed leg cannot be read at all: that window predates that market's own price "
         "history - a stated limit, not a zero.",
         "that window reaches back before our own price history for that market - a stated limit"),
        ("For the MATIF rapeseed leg the window predates that board's own price history, so there is "
         "no figure.",
         "the window reaches back before our own price history for that market, so there is no figure"),
    ):
        d = {"tldr": "", "mechanism": src}
        assert an._seam_precoverage_words(d)["decline_words_corrected"] == 1, src
        assert want in d["mechanism"], d["mechanism"]
        assert "predates" not in d["mechanism"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 6. THE WATCH BULLET CONTRACT
# ══════════════════════════════════════════════════════════════════════════════════════════════════
WATCH_SECTION = (
    "## Mechanism\nBody.\n\n## What to watch\n"
    "- **Harvested area** [N42] - top decile. Reads wrong if the next print returns the series to the "
    "middle of its own record.\n"
    "- **The buffer** [N33] - 10.72 %, window 2026-08-20 to 2026-11-20. It reads wrong if the next "
    "print turns back inside that line.\n")


def test_a_bullet_with_no_printed_figure_gains_its_OWN_cited_rows_figure():
    """A grader's count: 5 of 16 watch bullets carried no figure at all. The one element this seam can
    supply with certainty is the figure, because the bullet names the handle itself."""
    d = {"tldr": "", "mechanism": WATCH_SECTION}
    cen = an._seam_watch_bullets(d, _rows(MAX_ROWS), "max")
    assert cen["watch_bullets"] == 2 and cen["watch_no_figure"] == 1
    assert cen["watch_figures_added"] == 1
    assert "**Harvested area** [N42] (34.755 M ha, read 2026-09-11) - top decile." in d["mechanism"]
    assert "**The buffer** [N33] - 10.72 %" in d["mechanism"]      # already had one; untouched


def test_the_missing_window_and_falsifier_are_STAMPED_and_never_invented():
    """The window and the next print come from the NOMINATION and the release calendar -- `state/`
    products this seam is not handed. A window this seam composed would be a window it invented, so
    the counters ride the trace and the mandate demands all four in the writer's own hand."""
    d = {"tldr": "", "mechanism": WATCH_SECTION}
    cen = an._seam_watch_bullets(d, _rows(MAX_ROWS), "max")
    assert cen["watch_no_window"] == 1 and cen["watch_no_falsifier"] == 0
    assert "window" not in d["mechanism"].split("\n")[4]           # nothing invented on bullet 1


def test_the_ceiling_is_read_from_the_producer_the_selection_clause_states():
    """`watch.nonobvious_k` is the SAME producer the writer's selection clause names, so the count and
    the instruction can never disagree -- and NOTHING IS DELETED for being over it."""
    from leviathan.graphrag.state import watch as sw
    assert (sw.nonobvious_k("quick"), sw.nonobvious_k("deep"), sw.nonobvious_k("max")) == (3, 5, 7)
    four = WATCH_SECTION + "- **A** [N42] 1 x.\n- **B** [N33] 2 y.\n"
    d = {"tldr": "", "mechanism": four}
    cen = an._seam_watch_bullets(d, _rows(MAX_ROWS), "quick")
    assert cen["watch_bullets"] == 4 and cen["watch_over_ceiling"] == 1
    assert d["mechanism"].count("- **") == 4                       # the fourth bullet still ships
    assert an._seam_watch_bullets({"tldr": "", "mechanism": four}, _rows(MAX_ROWS),
                                  "max")["watch_over_ceiling"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 7. THE SCAFFOLD SEAMS
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_bolded_lead_stops_colliding_with_the_H2():
    """`**Why.** ## Mechanism` shipped on 5 of 5 smoke turns. It is not cosmetic: an ATX heading is
    only a heading at the START of a line, so the section the whole response contract is built on was
    literal text to every markdown reader on the page."""
    d = {"tldr": "T.", "mechanism": "## Mechanism\nBody."}
    assert an.render(dict(d), include_ledger=False) == "**TL;DR.** T.\n\n**Why.** ## Mechanism\nBody."
    assert an.render(dict(d), include_ledger=False, seam_lints=True) == \
        "**TL;DR.** T.\n\n**Why.**\n\n## Mechanism\nBody."
    # a mechanism that does NOT open with a heading keeps the inline label, both ways
    d2 = {"tldr": "T.", "mechanism": "Plain prose."}
    assert an.render(dict(d2), include_ledger=False, seam_lints=True) == \
        an.render(dict(d2), include_ledger=False)


def test_a_section_header_with_nothing_under_it_is_not_emitted():
    """The CYCLE-5 TIDY-3 rule -- "a header with nothing under it is not a summary, it is a promise
    the page cannot keep" -- applied to the MODEL's own headings. Scoped to the EMPTY case exactly as
    TIDY-3 is: a section carrying one word is untouched."""
    assert an._drop_empty_sections("## A\ntext\n\n## B\n\n## C\nmore") == "## A\ntext\n\n## C\nmore"
    assert an._drop_empty_sections("## A\ntext\n\n## B\n") == "## A\ntext"
    keep = "## A\ntext\n\n## B\nx"
    assert an._drop_empty_sections(keep) == keep
    assert an._drop_empty_sections("no headings at all") == "no headings at all"
    # ...and through render, where it is gated
    d = {"tldr": "T.", "mechanism": "## Mechanism\nBody.\n\n## Cross-commodity\n"}
    assert "## Cross-commodity" in an.render(dict(d), include_ledger=False)
    assert "## Cross-commodity" not in an.render(dict(d), include_ledger=False, seam_lints=True)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 8. THE FOOTER
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_one_row_per_distinct_document_carrying_every_handle_that_cites_it():
    """A grader's words: "source footer is mostly eleven copies of one 2021 paragraph, and the handles
    do not match the body". Eleven refs resolved to ONE WASDE sentence on the deep turn."""
    snip = ("The 2021/22 outlook for U.S. soybeans is for lower supplies, lower exports, higher "
            "crush, and higher ending stocks compared with 2020/21.")
    d = {"tldr": "A [E4] and [E7].", "mechanism": "More [E8]. Also [E39].",
         "sources": [{"ref": 4}, {"ref": 7}, {"ref": 8}, {"ref": 39}]}
    v = {"enabled": True, "resolved": {
        r: {"source": "USDA WASDE", "date": "2021-05-12", "snippet": snip} for r in ("4", "7", "8")}}
    v["resolved"]["39"] = {"source": "USDA FAS GAIN Report - Palm Oil", "date": "2026-04-17",
                           "snippet": "Soybean oil values are trending higher."}
    head = an._cited_sources_block(dict(d), v, [], seam_lints=True)
    assert head.count("USDA WASDE (2021-05-12)") == 1
    assert "[E4][E7][E8] USDA WASDE (2021-05-12)" in head
    assert "[E39] USDA FAS GAIN Report - Palm Oil (2026-04-17)" in head      # a DIFFERENT document
    # the OFF branch is HEAD's three rows under the body's own foreign spelling
    off = an._cited_sources_block(dict(d), v, [])
    assert off.count("USDA WASDE (2021-05-12)") == 3 and "[4] USDA WASDE" in off
    # a body that writes the BARE spelling keeps it: the footer answers the page, not a convention
    d2 = {"tldr": "A [4].", "mechanism": "", "sources": [{"ref": 4}]}
    assert "[4] USDA WASDE" in an._cited_sources_block(d2, v, [], seam_lints=True)


def test_a_money_figure_is_printed_as_its_currency_and_amount_together():
    """`= 12 $/bu` -- and the writer copied the footer's spelling into the body. The NUMBER does not
    move: two decimals are a spelling of 12, not a rounding of it."""
    assert an._seam_money_units("x = 12 $/bu") == "x = $12.00/bu"
    assert an._seam_money_units("x = 10.5 USD/bu") == "x = $10.50/bu"
    assert an._seam_money_units("x = 1,328 US cents/bushel") == "x = 1,328 US cents/bushel"
    assert an._seam_money_units("x = 0.51 z") == "x = 0.51 z"
    d = {"tldr": "P [N1].", "mechanism": "", "sources": []}
    calls = [_call("silver_wasde", "average farm price", "soybeans", "united_states", "MY2026/27",
                   12, "$/bu", "2026-09-11")]
    assert "= $12.00/bu" in an._cited_sources_block(dict(d), {"enabled": True}, calls, seam_lints=True)
    assert "= 12 $/bu" in an._cited_sources_block(dict(d), {"enabled": True}, calls)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 9. LENGTH -- a stamp, and never a cut
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_ceiling_has_ONE_producer_for_the_prompt_and_for_the_stamp():
    """Two derivations of one number is how a ceiling comes to mean two things: the sentence the writer
    reads and the number `prose_over_budget` is measured against are the same call."""
    assert (rc.prose_ceiling("quick"), rc.prose_ceiling("deep"), rc.prose_ceiling("max")) == \
        (450, 900, 1200)
    for m, want in (("quick_hp", 450), ("quick_n3", 450), ("deep_hp", 900), ("deep_cc1", 900),
                    ("esc", 900), ("esc_r", 900), ("max_c0", 1200), ("max_cc1", 1200),
                    ("standard", 900), ("", 900), (None, 900), ("nonsense", 900)):
        assert rc.prose_ceiling(m) == want, m
    for m in ("quick", "deep", "max"):
        assert f"at most {rc.prose_ceiling(m)} words" in an._system_writer_seam_mandate(m)


def test_the_length_rule_is_a_stamp_and_cuts_nothing():
    body = " ".join(["word"] * 1500)
    d = {"tldr": "T.", "mechanism": body}
    cen = an._writer_seam_lints(d, [], asof=ASOF, mode="quick")
    assert cen["prose_ceiling"] == 450 and cen["prose_words"] >= 1500
    assert cen["prose_over_budget"] == cen["prose_words"] - 450
    assert d["mechanism"] == body                              # NOT ONE WORD CUT
    assert an._writer_seam_lints({"tldr": "a b c", "mechanism": ""}, [], asof=ASOF,
                                 mode="max")["prose_over_budget"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 10. THE LAW: nothing here deletes
# ══════════════════════════════════════════════════════════════════════════════════════════════════
_CORPUS = [
    ({"tldr": MAX_TLDR, "mechanism": LAG_LINE + "\n\n" + WATCH_SECTION}, MAX_ROWS, "max"),
    ({"tldr": "a spring wheat area reading at the 1st percentile of its own record [N42]",
      "mechanism": "## Mechanism\nCorn's ratio [N42] is tightening.\n\n## What to watch\n- **X** [N42] y."},
     CW_ROWS, "quick"),
    ({"tldr": "", "mechanism": "Malaysian closing stocks were 2.62832 MMT [N61] and rising."},
     MPOB_ROWS, "quick"),
    ({"tldr": "", "mechanism": "Tropical Pacific +1.8 degC [N23], rising eight months running."},
     ONI_ROWS, "deep"),
    ({"tldr": "", "mechanism": "That window predates that market's own price history."}, [], "deep"),
    ({"tldr": "", "mechanism": ""}, [], "quick"),
    ({"tldr": None, "mechanism": 17}, None, ""),               # the malformed arm: belted, never raised
]


def test_no_pass_ever_shortens_a_field_or_loses_a_handle_or_a_digit():
    """THE LAW OF THIS WHOLE LANE, asserted in one place over every fixture: each pass either
    substitutes a span for the cited row's own words or inserts a clause, so no field may get shorter
    and no handle and no digit may be lost. A fence that removed a sentence or left an orphan clause
    is FATAL in this estate's review, and this is the test that would find it."""
    for st, calls, mode in _CORPUS:
        before = dict(st)
        cen = an._writer_seam_lints(st, calls, asof=ASOF, mode=mode, horizon_months=3)
        assert isinstance(cen, dict) and "outcome" in cen
        for f in ("tldr", "mechanism"):
            a, b = before.get(f), st.get(f)
            if not isinstance(a, str):
                assert a == b                                   # untouched when it is not prose
                continue
            assert len(b) >= len(a), (f, a, b)
            assert re.findall(r"\[[EN]\d+[^\]]*\]", a) == re.findall(r"\[[EN]\d+[^\]]*\]", b)
            assert len(re.findall(r"\d", a)) <= len(re.findall(r"\d", b))
            for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", a):    # every figure survives verbatim
                assert tok in b, (f, tok)


def test_a_broken_instrument_is_stamped_and_never_raised_onward():
    """An instrument must never be the thing that breaks the answer it measures."""
    assert an._writer_seam_lints(None, [], asof=ASOF)["outcome"] == "bad_shape"
    assert an._writer_seam_lints("not a dict", [])["outcome"] == "bad_shape"
    d = {"tldr": "x [N1].", "mechanism": "y"}
    assert an._writer_seam_lints(d, [{"bad": "shape"}], asof="not-a-date", mode="quick")["outcome"] \
        == "ok"
    assert an._writer_seam_lints({"tldr": "x", "mechanism": "y"}, None,
                                 asof=ASOF)["outcome"] == "ok"


def test_the_seam_is_gated_on_one_resolved_bool_in_BOTH_serving_bodies():
    """ONE read per body, threaded to all three consumers -- the `_bar_licence` discipline, and for the
    same measured reason (WP-A4's own repair): a switch read twice is how a charge and its remedy come
    to disagree on the lane where one of the two reads is stale."""
    for body in (an._answer_l2, an.answer):
        src = inspect.getsource(body)
        assert src.count('_wseam_on = bool(_state_board_on() and verifier.get("enabled"))') == 1, \
            body.__name__
        assert src.count("seam_lints=_wseam_on") == 2, body.__name__     # render + the footer
        assert "_writer_seam_lints(" in src, body.__name__
    # ...and the lint pass reads NO environment of its own
    for fn in (an._writer_seam_lints, an._seam_tldr_consistency, an._seam_stale_figures,
               an._seam_lag_windows, an._seam_watch_bullets, an._seam_precoverage_words,
               an._drop_empty_sections, an._seam_money_units):
        assert "os.environ" not in inspect.getsource(fn), fn.__name__


def test_the_figure_is_not_appended_on_the_handle_prose_lane_where_another_pass_fills_the_slot():
    """ONE PRODUCER, not a safety fence: on a `*_hp` preset `_resolve_number_handles` runs immediately
    after this pass and SUBSTITUTES the row's own value into the slot the bare handle stands in --
    exactly the figure this pass would otherwise add. Two producers filling one slot is how a bullet
    comes to read "34.755 M ha [N42] (34.755 M ha, read 2026-09-11)". The COUNTERS still ride."""
    d = {"tldr": "", "mechanism": WATCH_SECTION}
    cen = an._seam_watch_bullets(d, _rows(MAX_ROWS), "max", handle_prose=True)
    assert cen["watch_no_figure"] == 1 and cen["watch_figures_added"] == 0
    assert cen["watch_bullets"] == 2 and cen["watch_no_window"] == 1
    assert d["mechanism"] == WATCH_SECTION                   # not one byte
    assert inspect.signature(an._writer_seam_lints).parameters["handle_prose"].default is False
    for body in (an._answer_l2, an.answer):
        assert "handle_prose=_handles" in inspect.getsource(body), body.__name__


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 12. ROUND 2 -- the review's FATAL, its six MAJORS, its minors, and the five ROUND2_DOCKET items
#
# Every pin below is the REVIEWER'S OWN PROBE or the READ PANEL'S OWN QUOTE, re-run against the fix.
# Where a fixture is hand-built it stands beside the real-seat sentence it abstracts, never alone, and
# the real-seat MEASUREMENT lives in `prearm_fix_r2/E/{measure.py,augment.py}` (the corpus is a
# session scratchpad and no repo deck may depend on it).
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_FATAL_a_section_whose_body_sits_under_a_SUB_HEADING_is_never_dropped():
    """THE REVIEW'S FATAL, in its own shape. `_drop_empty_sections` closed a section at the next
    heading of ANY level, so a `##` with a `###` under it read as EMPTY: the label was deleted and its
    content orphaned under a parentless sub-heading. A section is empty only when nothing but
    whitespace sits before the next heading of the SAME OR SHALLOWER level, and a heading with content
    at ANY DEPTH is never removed."""
    mech = ("## Episodes\n### The 2015-16 window\n- it settled nothing [N1].\n\n"
            "## What to watch\n- x [N2].\n")
    out = an._drop_empty_sections(mech)
    assert out.startswith("## Episodes")                       # the parent KEEPS its line
    assert "### The 2015-16 window" in out and "- it settled nothing [N1]." in out
    assert out == mech.strip()                                 # ...and NOT ONE BYTE moved
    # three levels deep, with the content only at the bottom
    deep = "## A\n### B\n#### C\n- reading [N1].\n\n## D\n- y [N2].\n"
    assert an._drop_empty_sections(deep) == deep.strip()
    # THE EMPTY CASE STILL GOES, which is the rule's whole job
    assert an._drop_empty_sections("## Empty\n\n## Real\n- x [N2].\n") == "## Real\n- x [N2]."
    # ...and it CASCADES: an empty sub-heading takes its now-empty parent with it
    assert an._drop_empty_sections("## A\n### B\n\n## Real\n- x.\n") == "## Real\n- x."
    # A `#` INSIDE A FENCE IS NOT A HEADING (every sibling walk in this file is fence-aware)
    fenced = "## Cascade\n```mermaid\nflowchart TD\nA --> B\n```\n\n## Next\n- x.\n"
    assert an._drop_empty_sections(fenced) == fenced.strip()


def test_MAJOR1_the_rank_comes_off_the_NEAREST_handles_own_row_or_nowhere():
    """THE REVIEWER'S PROBE B, verbatim. The first cut walked four candidates and broke on the first
    one THAT HAD A PERCENTILE, so a claim whose own handle carries no rank reached past it and printed
    a DIFFERENT SERIES' percentile -- the identical false correction `_seam_bound` exists to close."""
    rows = an._seam_row_index([_psd("soybeans_cbot", "MY2026", 34.755, "M ha", "2026-09-11"),   # [N1]
                               _call("silver_psd", "stocks to use", "soybeans_cbot", "United States",
                                     "MY2026", 23, "percentile", "2026-09-11")])                # [N2]
    tl = "A record-high harvested area of 34.76 M ha [N1] on a thin buffer [N2]."
    d = {"tldr": tl, "mechanism": ""}
    cen = an._seam_tldr_consistency(d, rows, an._seam_percentiles(rows))
    assert d["tldr"] == tl                                     # NOT ONE BYTE
    assert cen["superlatives_seen"] == 1 and cen["superlatives_corrected"] == 0
    assert cen["superlatives_unbound"] == 1                    # ...and the miss is STAMPED, not hidden
    assert an._seam_percentiles(rows)[rows[2]["head"]] == 23   # the decoy IS on the page: the REACH went
    # ...and the smoke's own case, where the nearest handle DOES carry the rank, still corrects
    d2 = {"tldr": MAX_TLDR, "mechanism": ""}
    r2 = _rows(MAX_ROWS)
    assert an._seam_tldr_consistency(d2, r2, an._seam_percentiles(r2))["superlatives_corrected"] == 1
    assert "a 91st-percentile harvested area of 34.76 M ha [N42]" in d2["tldr"]


def test_MAJOR2_the_class_fence_may_never_rename_the_COMMODITY():
    """THE REVIEWER'S PROBE A, verbatim: a spring-wheat claim whose own handle is not in the row index
    was re-labelled WHITE MAIZE off a row two handles away. A class is corrected only inside ONE
    commodity, and only from the sentence's own nearest handle."""
    rows = an._seam_row_index([None] * 49 + [
        _call("silver_psd", "production white maize", "maize_jse", "South Africa", "MY2026", 12,
              "MMT", "2026-09-11")])                            # [N50]
    tl = "A spring wheat area reading [N99] beside the maize sheet [N50]."
    d = {"tldr": tl, "mechanism": ""}
    cen = an._seam_tldr_consistency(d, rows, an._seam_percentiles(rows))
    assert d["tldr"] == tl                                      # the crop KEEPS ITS NAME
    assert cen["classes_corrected"] == 0 and cen["classes_unbound"] == 1
    # ...and even bound DIRECTLY to the maize row, a wheat claim is never made maize
    d2 = {"tldr": "A spring wheat area reading [N50].", "mechanism": ""}
    assert an._seam_tldr_consistency(d2, rows, {})["classes_corrected"] == 0
    assert "spring wheat" in d2["tldr"] and "maize" not in d2["tldr"]
    # ...while WHEAT-TO-WHEAT, the smoke's own case, still corrects
    d3 = {"tldr": "a spring wheat area reading at the 1st percentile [N42]", "mechanism": ""}
    assert an._seam_tldr_consistency(d3, _rows(CW_ROWS), {})["classes_corrected"] == 1
    assert "soft red winter wheat" in d3["tldr"]


#: VERBATIM, the DEEP turn's price-pressuring bullet -- the sentence finding (8) was FILED ON, and the
#: one the round-1 rule never fired on (`lag_windows_checked: 0` on the served deep body).
DEEP_LAG_BULLET = (
    "- **Export pace and acreage, price-pressuring.** A slow US sales pace signals weak demand and "
    "rebuilds carryout (high confidence, zero to one quarter); larger area loosens supply with a "
    "two-to-four-quarter lag, and that acreage window sits inside the three-month horizon.")


def test_MAJOR3_the_lag_rule_fires_on_the_DEEP_bullet_it_was_built_for():
    """The bullet carries NO `[N]` handle anywhere on its line, so the handle binder returned nothing
    and the pass went silent on the very finding it closes. It still NAMES ITS SERIES IN WORDS
    ("larger AREA", "that ACREAGE window"), and the row is on the page: `[N59] USDA PSD area harvested
    ... [known 2026-09-11]`."""
    rows = an._seam_row_index([None] * 58 + [
        _psd("soybeans_cbot", "MY2026", 34.755, "M ha", "2026-09-11"),            # [N59]
        None,
        _psd("soybeans_cbot", "MY2026", 91, "percentile", "2026-09-11"),          # [N61]
    ])
    d = {"tldr": "", "mechanism": DEEP_LAG_BULLET}
    cen = an._seam_lag_windows(d, rows, ASOF, 3)
    assert cen["lag_windows_checked"] == 1 and cen["lag_windows_corrected"] == 1
    assert cen["lag_windows_subject_bound"] == 1
    assert "sits outside the three-month horizon" in d["mechanism"]
    assert ("(the declared two-to-four-quarter lag counted from 2026-09-11 runs March to September "
            "2027)") in d["mechanism"]
    assert "A slow US sales pace signals weak demand" in d["mechanism"]     # nothing removed
    # THE SUBJECT BIND IS FAIL-CLOSED: two heads winning the overlap, or none at all, say nothing
    two_heads = an._seam_row_index([
        _psd("soybeans_cbot", "MY2026", 34.755, "M ha", "2026-09-11"),
        _call("silver_psd", "acreage planted", "corn_cbot", "Brazil", "MY2026", 20, "M ha",
              "2026-08-01")])
    d2 = {"tldr": "", "mechanism": DEEP_LAG_BULLET}
    assert an._seam_lag_windows(d2, two_heads, ASOF, 3)["lag_windows_checked"] == 0
    assert d2["mechanism"] == DEEP_LAG_BULLET
    d3 = {"tldr": "", "mechanism": DEEP_LAG_BULLET}
    assert an._seam_lag_windows(d3, {}, ASOF, 3)["lag_windows_checked"] == 0
    assert d3["mechanism"] == DEEP_LAG_BULLET
    # ...and ONE HEAD AT TWO VINTAGES is refused too
    two_dates = an._seam_row_index([
        _psd("soybeans_cbot", "MY2026", 34.755, "M ha", "2026-09-11"),
        _psd("soybeans_cbot", "MY2026", 91, "percentile", "2026-08-01")])
    d4 = {"tldr": "", "mechanism": DEEP_LAG_BULLET}
    assert an._seam_lag_windows(d4, two_dates, ASOF, 3)["lag_windows_checked"] == 0


def test_MAJOR4_a_COT_week_and_an_ESR_week_are_not_ANNUAL_ROWS():
    """`_SEAM_ANNUAL_RX` matched the estate's `MY` PERIOD PREFIX, which EVERY period carries: a COT
    week is `MY2026-09-01` and an ESR week is `MY2026-08-27`. Both took the annual clock (window
    ZERO), so both read "stale" nine and twelve days after they were read -- 8 of the round's 13
    stale clauses, on rows younger than the 21-day window."""
    for period in ("MY2026-09-01", "MY2026-08-27", "MY2026-07"):
        assert not an._SEAM_ANNUAL_RX.search(f"COT managed-money net position CBOT soybeans {period}"), \
            period
    for period in ("MY2026", "MY2026/27", "MY 2026"):
        assert an._SEAM_ANNUAL_RX.search(f"USDA WASDE ending stocks soybeans united_states {period}"), \
            period
    # THE COT WEEK, END TO END: nine days old, spoken as a rising movement, and NOT dated
    cot = [_call("silver_cot", "managed-money net position", "soybeans_cbot", None, "MY2026-09-01",
                 234920, "contracts", "2026-09-07")]
    d = {"tldr": "", "mechanism": "Managed money [N1] is rising three weeks running"}
    assert an._seam_stale_figures(d, _rows(cot), ASOF)["stale_rows_dated"] == 0
    # ...and the ESR week, twelve days old, carrying the source's UNDASHED stamp
    esr = [_call("silver_esr", "weekly exports", "soybeans_cbot", None, "MY2026-08-27", 311.846,
                 "1000 MT", "20260904")]
    d2 = {"tldr": "", "mechanism": "Shipments [N1] falling on the week"}
    assert an._seam_stale_figures(d2, _rows(esr), ASOF)["stale_rows_dated"] == 0
    assert _rows(esr)[1]["known"] == "2026-09-04"        # the stamp is ISO before any rule reads it
    # THE CARD'S OWN CADENCE is the other half of the ruling, and it wins whatever the period spells
    ann = _call("silver_psd", "stocks to use", "corn_cbot", "US", "2026", 0.12, "ratio", "2026-09-11")
    ann["cadence"] = "annual"
    d3 = {"tldr": "", "mechanism": "The ratio [N1] is tightening"}
    assert an._seam_stale_figures(d3, _rows([ann]), ASOF)["stale_rows_dated"] == 1
    # ...and a sentence that SCOPES ITS OWN MOVEMENT to a marketing year is not a currency claim
    annual = [_call("silver_psd", "stocks to use", "corn_cbot", "US", "MY2026", 0.12, "ratio",
                    "2026-09-11")]
    d4 = {"tldr": "", "mechanism": "The buffer [N1] is falling three consecutive marketing years"}
    assert an._seam_stale_figures(d4, _rows(annual), ASOF)["stale_rows_dated"] == 0
    # ...while the MPOB case the rule was built for is still charged (77 days, no scope words)
    d5 = {"tldr": "", "mechanism": "Malaysian closing stocks 2.62832 MMT [N61] are building"}
    assert an._seam_stale_figures(d5, _rows(MPOB_ROWS), ASOF)["stale_rows_dated"] == 1


def test_MAJOR5_the_watch_figure_is_spelled_the_way_THE_PAGE_already_spelled_it():
    """The soyoil body prints `stocks-to-use 5.67 % [N41]` and the bullet came back
    `[N41] (5.66691 %, read 2026-09-11)` -- one handle, two spellings of one figure, on one judged
    page. The BODY'S OWN TOKEN is used, and only when it IS this row's value."""
    rows = an._seam_row_index([_call("silver_psd", "stocks to use", "soyoil_cbot", "United States",
                                     "MY2026", 5.66691, "%", "2026-09-11")])
    body = ("## Mechanism\nSoyoil stocks-to-use reads 5.67 % [N1] on the year.\n\n"
            "## What to watch\n- **Soyoil stocks-to-use** [N1] - already past the very-tight line.\n")
    d = {"tldr": "", "mechanism": body}
    cen = an._seam_watch_bullets(d, rows, "quick")
    assert cen["watch_figures_added"] == 1 and cen["watch_figures_rounded"] == 1
    assert "[N1] (5.67 %, read 2026-09-11)" in d["mechanism"]
    assert "5.66691" not in d["mechanism"]
    # ...and with NO body spelling the raw value stands: the seam never invents a precision
    d2 = {"tldr": "", "mechanism": "## What to watch\n- **Soyoil stocks-to-use** [N1] - past it.\n"}
    cen2 = an._seam_watch_bullets(d2, rows, "quick")
    assert cen2["watch_figures_rounded"] == 0 and "(5.66691 %, read 2026-09-11)" in d2["mechanism"]
    # ...and a numeral beside the handle that is NOT this row's value is never borrowed
    d3 = {"tldr": "", "mechanism": ("## Mechanism\nA 92 percentile print [N1].\n\n"
                                    "## What to watch\n- **Buffer** [N1] - past it.\n")}
    an._seam_watch_bullets(d3, rows, "quick")
    assert "(5.66691 %, read 2026-09-11)" in d3["mechanism"]


def test_MAJOR6_a_multi_row_stale_sentence_attaches_each_DATE_to_its_HANDLE():
    """The reviewer's probe 5b: "(the 2026-01 reading, read 2026-05-01; read 2026-06-02)" -- the
    reader cannot tell which date belongs to which row. An unattributed date is an attribution this
    seam invented, which is the one thing the lane's own argument forbids."""
    rows = an._seam_row_index([
        _call("silver_psd", "beginning stocks", "soybeans_cbot", "US", "MY2026", 1, "z",
              "2026-05-01"),                                                          # [N1]
        _call("silver_psd", "beginning stocks", "corn_cbot", "US", "MY2026", 2, "z",
              "2026-06-02")])                                                         # [N2]
    d = {"tldr": "", "mechanism": "A reads 1 z [N1] and B reads 2 z [N2], both rising"}
    cen = an._seam_stale_figures(d, rows, ASOF)
    assert cen["stale_rows_dated"] == 2
    assert d["mechanism"].endswith("(N1 read 2026-05-01; N2 read 2026-06-02)")
    # ROWS THAT SHARE ONE DATE ARE NAMED TOGETHER, not stamped once each -- the palm/rape shape
    same = an._seam_row_index([
        _call("silver_mpob", "closing stocks", "palm oil", None, None, 2.6, "MMT", "2026-07-01"),
        _call("silver_mpob", "month change", "palm oil", None, None, 0.08, "MMT", "2026-07-01"),
        _call("silver_mpob", "build months", "palm oil", None, None, 4, "months", "2026-07-01")])
    d2 = {"tldr": "", "mechanism": "Stocks 2.6 MMT [N1], up 0.08 MMT [N2] and rising 4 months [N3]"}
    assert an._seam_stale_figures(d2, same, ASOF)["stale_rows_dated"] == 3
    # RE-BANKED 09-23 FIX ROUND -- D3 known-date + period correction (09-23 recon palm_rapeoil F2; FIX.md O-3): the
    # July MPOB print is a data_date card read, known 2026-08-13 (+43-day lag), and its month clause now rides.
    assert d2["mechanism"].endswith("(N1, N2, N3 the 2026-07 reading, read 2026-08-13)")
    # ...and a ONE-HANDLE sentence has no ambiguity to resolve and keeps the bare form
    d3 = {"tldr": "", "mechanism": "Stocks 2.62832 MMT [N61] and rising in each of the last 4 months"}
    an._seam_stale_figures(d3, _rows(MPOB_ROWS), ASOF)
    # RE-BANKED 09-23 FIX ROUND -- D3 known-date + period correction (09-23 recon palm_rapeoil F2; FIX.md O-3): the
    # July MPOB print is a data_date card read, known 2026-08-13 (+43-day lag), and its month clause now rides.
    assert d3["mechanism"].endswith("(the 2026-07 reading, read 2026-08-13)")


def test_MAJOR7_the_watch_walk_accepts_every_spelling_its_SIBLING_WALKS_accept():
    """The first cut matched one strict literal -- the ONE heading walk in this file that was neither
    fence-aware nor normalised -- and it failed SILENTLY TO ZERO, indistinguishable in the trace from
    "no defects found" on three counters the arm reads."""
    tail = "\n- **The buffer** [N33] - past the tight line.\n"
    for head in ("## What to watch", "### What to watch", "## What to watch ", "##  What to watch",
                 "## What to watch (3)", "## What To Watch", "#### WHAT TO WATCH"):
        d = {"tldr": "", "mechanism": "## Mechanism\nBody.\n\n" + head + tail}
        cen = an._seam_watch_bullets(d, _rows(MAX_ROWS), "max")
        assert cen["watch_section_seen"] == 1 and cen["watch_bullets"] == 1, head
    # NO SECTION is a ZERO the trace can tell apart from NO DEFECTS
    d0 = {"tldr": "", "mechanism": "## Mechanism\nBody.\n"}
    assert an._seam_watch_bullets(d0, _rows(MAX_ROWS), "max")["watch_section_seen"] == 0
    # the next heading of the same or a shallower level closes it, and a DEEPER one does not
    d1 = {"tldr": "", "mechanism": "## What to watch" + tail + "\n### Detail\n- **Area** [N42] - x.\n"}
    assert an._seam_watch_bullets(d1, _rows(MAX_ROWS), "max")["watch_bullets"] == 2
    d2 = {"tldr": "", "mechanism": "## What to watch" + tail + "\n## Sources\n- not a bullet [N42].\n"}
    assert an._seam_watch_bullets(d2, _rows(MAX_ROWS), "max")["watch_bullets"] == 1
    # a heading inside a FENCE closes nothing and opens nothing
    d3 = {"tldr": "", "mechanism": "## What to watch\n```\n## Sources\n```" + tail}
    assert an._seam_watch_bullets(d3, _rows(MAX_ROWS), "max")["watch_bullets"] == 1


def test_MINOR_an_ambiguous_percentile_no_longer_breaks_EVERY_correction_on_the_turn():
    """`abs(None - v)` raised `TypeError` on a head carrying A/B/A, the belt stamped
    `lint_failed:TypeError`, and ALL SEVEN corrections went off while the page shipped the defects."""
    rows = an._seam_row_index([
        _psd("soybeans_cbot", "MY2026", 91, "percentile", "2026-09-11"),
        _psd("soybeans_cbot", "MY2026", 23, "percentile", "2026-09-11"),
        _psd("soybeans_cbot", "MY2026", 91, "percentile", "2026-09-11")])
    assert an._seam_percentiles(rows) == {}                    # ambiguous: never corrected from
    cen = an._writer_seam_lints({"tldr": "A record-high area [N1].", "mechanism": ""},
                                [_psd("soybeans_cbot", "MY2026", 91, "percentile", "2026-09-11")],
                                asof=ASOF, mode="max")
    assert cen["outcome"] == "ok"


def test_MINOR_the_article_the_substitution_leaves_behind_is_corrected_with_it():
    """"An unprecedented ..." must not become "An 23rd-percentile ...". The article is a word of the
    writer's own sentence and correcting it is the same class of correction as the rank itself."""
    rows = an._seam_row_index([_psd("soybeans_cbot", "MY2026", 34.755, "M ha", "2026-09-11"),
                               _psd("soybeans_cbot", "MY2026", 8, "percentile", "2026-09-11")])
    d = {"tldr": "A record-high harvested area [N1].", "mechanism": ""}
    cen = an._seam_tldr_consistency(d, rows, an._seam_percentiles(rows))
    assert d["tldr"] == "An 8th-percentile harvested area [N1]."
    assert cen["superlative_articles_fixed"] == 1
    rows2 = an._seam_row_index([_psd("soybeans_cbot", "MY2026", 34.755, "M ha", "2026-09-11"),
                                _psd("soybeans_cbot", "MY2026", 23, "percentile", "2026-09-11")])
    d2 = {"tldr": "An unprecedented harvested area [N1].", "mechanism": ""}
    an._seam_tldr_consistency(d2, rows2, an._seam_percentiles(rows2))
    assert d2["tldr"] == "A 23rd-percentile harvested area [N1]."


def test_MINOR_a_date_is_not_a_figure_and_a_negative_price_keeps_its_sign_outside():
    d = {"tldr": "", "mechanism": "## What to watch\n- **Area** [N42] - read 2026-09-11.\n"}
    assert an._seam_watch_bullets(d, _rows(MAX_ROWS), "max")["watch_no_figure"] == 1
    assert an._seam_money_units("x = -3 $/bu") == "x = -$3.00/bu"
    assert an._seam_money_units("x = 12 $/bu") == "x = $12.00/bu"
    assert an._seam_iso_date("20260904") == "2026-09-04"
    assert an._seam_iso_date("2026-09-04") == "2026-09-04" and an._seam_iso_date("") == ""
    assert an._seam_iso_date("2026") == "2026" and an._seam_iso_date("20261332") == "20261332"


def test_MINOR_a_grouped_handle_names_the_member_whose_figure_it_appends():
    """"**A pair** [N41, N42] (5.66691 %, read ...)" took the FIRST member's figure and attributed it
    to neither. The member is named, the same grammar the staleness clause uses."""
    d = {"tldr": "", "mechanism": "## What to watch\n- **A pair** [N42, N44] - top decile.\n"}
    cen = an._seam_watch_bullets(d, _rows(MAX_ROWS), "max")
    assert cen["watch_figures_added"] == 1
    assert "[N42, N44] (N42 34.755 M ha, read 2026-09-11)" in d["mechanism"]


def test_DOCKET9_the_citations_own_label_wins_in_prose():
    """ROUND2_DOCKET #9, the max turn's own sentence over its own row: an ESR SHIPMENTS row sold to
    the reader as the SALES series, on the leg the note twice calls decisive."""
    rows = an._seam_row_index([None] * 26 + [
        _call("silver_esr", "weekly exports", "soybeans_cbot", None, "MY2026-08-27", 311.846,
              "1000 MT", "20260904")])                                   # [N27]
    d = {"tldr": "", "mechanism": ("Weekly export sales at 311.85 thousand MT [N27], 6th percentile, "
                                   "is a high-confidence channel.")}
    cen = an._seam_metric_labels(d, rows)
    assert cen["metric_labels_corrected"] == 1
    assert d["mechanism"].startswith("Weekly exports at 311.85 thousand MT [N27]")
    # the ADJECTIVAL shape the same turn shipped as a bullet title
    d2 = {"tldr": "", "mechanism": "- **Export sales pace** [N27] - bottom decile."}
    assert an._seam_metric_labels(d2, rows)["metric_labels_corrected"] == 1
    assert "**Export pace** [N27]" in d2["mechanism"]
    # A GENUINE WEEKLY-SALES ROW IS NEVER REWRITTEN -- the guard is the METRIC words, never the SOURCE
    # name, which is itself "Export Sales (ESR)"
    sales = an._seam_row_index([None] * 26 + [
        _call("silver_esr", "weekly export sales", "soybeans_cbot", None, "MY2026-08-27", 500,
              "1000 MT", "2026-09-04")])
    d3 = {"tldr": "", "mechanism": "Weekly export sales at 500 thousand MT [N27]."}
    assert an._seam_metric_labels(d3, sales)["metric_labels_corrected"] == 0
    assert d3["mechanism"] == "Weekly export sales at 500 thousand MT [N27]."


def _routed(call: dict, driver_words: str, row_id: str) -> dict:
    """A BOARD call as the board mints it: the row identity that minted it (C3 `_row_id`) and the driver
    words the block printed as "read here for <driver>" on that row (lane R's `routing`, which
    `citations.call_identity` reads back as `routing_words`)."""
    c = dict(call, _row_id=row_id, _sb=True)
    c["rows"] = [dict(c["rows"][0], routing=driver_words)] if c.get("rows") else []
    c["routing"] = driver_words
    return c


def test_DOCKET10_an_asserted_absence_is_checked_against_the_rows_the_turn_SERVED():
    """ROUND2_DOCKET #10 with the max turn's own sentence and its own unread row: `[N48]
    silver_psd.exports_mt Argentina = 6.45 MMT [known 2026-09-11]`, served and flagged
    `coverage.missed.loud`, under "have no series this page could read".

    RE-BANKED 09-24 (fix round 2, lane A, CONTRACT K16 -- declared): the row is appended IFF the board
    ROUTES the claim's driver to it -- the SB-1 row carries "read here for Argentine selling incentives"
    -- and never because a capitalised word of the claim stems onto a row head (the retired bind: it put
    a 2016 yuan move on a 2025 tariff link and an empty read on a true absence, 09-24)."""
    ex = _call("silver_psd", "exports", "soybeans_cbot", "Argentina", "MY2026", 6.45, "MMT", "2026-09-11")
    calls = [None] * 47 + [_routed(ex, "Argentine selling incentives",
                                   "soybeans_cbot|Argentine_selling_incentives|psd_exports|soybeans_cbot|AR")]
    rows = an._seam_row_index(calls)                                     # [N48]
    sent = ("The model's price-pressuring supply-glut pattern needs three of its five drivers, and "
            "two of its legs (Argentine selling incentives, the dollar) have no series this page "
            "could read.")
    d = {"tldr": "", "mechanism": sent}
    cen = an._seam_absence_claims(d, rows, number_calls=calls)
    assert cen["absence_claims_checked"] == 1 and cen["absence_rows_appended"] == 1, cen
    assert "(a served reading bears on this: [N48] = 6.45 MMT, read 2026-09-11)" in d["mechanism"]
    assert d["mechanism"].startswith(sent[:-1])               # the CLAIM IS NOT REMOVED
    # IDEMPOTENT: a second run appends nothing twice
    again = dict(d)
    assert an._seam_absence_claims(again, rows, number_calls=calls)["absence_rows_appended"] == 0
    assert again == d
    # NOTHING IS APPENDED WHEN NOTHING WAS SERVED FOR THAT SUBJECT
    d2 = {"tldr": "", "mechanism": sent}
    assert an._seam_absence_claims(d2, {})["absence_rows_appended"] == 0
    assert d2["mechanism"] == sent
    # ...nor when the sentence ALREADY CITES the row it is calling absent
    d3 = {"tldr": "", "mechanism": "Argentine selling incentives [N48] have no series this page could read."}
    assert an._seam_absence_claims(d3, rows, number_calls=calls)["absence_rows_appended"] == 0
    # ...nor when the SAME CAPITALISED WORD sits on a row the board did NOT route to that driver: the
    # stem bind is retired, so an unrouted Argentine row is no referent at all (K16)
    unrouted = [None] * 47 + [ex]
    d4 = {"tldr": "", "mechanism": sent}
    c4 = an._seam_absence_claims(d4, an._seam_row_index(unrouted), number_calls=unrouted)
    assert c4["absence_rows_appended"] == 0 and c4.get("absence_unbound") == 1, c4
    assert d4["mechanism"] == sent
    # ...and on the handle-prose lane the FIGURE is left to the one producer that fills that slot
    d5 = {"tldr": "", "mechanism": sent}
    an._seam_absence_claims(d5, rows, handle_prose=True, number_calls=calls)
    assert "(a served reading bears on this: [N48], read 2026-09-11)" in d5["mechanism"]


def test_K16_the_two_09_24_false_appends_are_gone_and_a_true_absence_is_left_true():
    """THE TWO MEASURED FALSE APPENDS (09-24, `writer_seam.absence_rows_appended` 2, both false), on the
    served pages' own sentences and the rows that were stemmed onto them:
      * deep 2026 -- "... none with a readable next print" got "(a Chinese series was read: [N252] = 4
        percent change in Chinese yuan per US dollar, read 2016-06-17)": a 2016 yuan move on a 2025 tariff
        link, bound by the capitalised word "Chinese";
      * palm/rape -- "the record carries no figure for Bangladeshi rapeseed-oil stocks at all" got "(a
        Bangladeshi series was read: = NO ROWS RETURNED)": an EMPTY READ appended to a TRUE absence.
    Neither claim names a structural referent with a served row, so both ship as written. A referent
    HOP the board read no series for makes the absence TRUE (`absence_true`)."""
    yuan = _call("silver_fx", "percent change", None, "China", "2016-06-17", 4, "percent change in "
                 "Chinese yuan per US dollar", "2016-06-17")
    deep_calls = [None] * 251 + [yuan]
    deep = ("The second chain, from Chinese import tariffs through export shipments to the same ratio, is "
            "unquantified at its first link (no series served) and its record is thin -- three prior "
            "occasions, none with a readable next print.")
    d = {"tldr": "", "mechanism": deep}
    cen = an._seam_absence_claims(d, an._seam_row_index(deep_calls), number_calls=deep_calls)
    assert cen["absence_rows_appended"] == 0 and d["mechanism"] == deep, d["mechanism"]
    empty = {"query": {"table": "silver_fas_psd", "metric": "ending stocks", "commodity": "rapeseed_oil_zce",
                       "country": "Bangladesh", "period": "MY2026", "asof": ASOF},
             "rows": [], "status": "ok"}
    palm_calls = [None] * 9 + [_routed(empty, "Bangladeshi rapeseed-oil stocks",
                                       "rapeseed_oil_zce|bd_stocks|fas_psd|rapeseed_oil_zce|BD")]
    palm = "- World prices: the record carries no figure for Bangladeshi rapeseed-oil stocks at all."
    d2 = {"tldr": "", "mechanism": palm}
    rows2 = an._seam_row_index(palm_calls)
    cen2 = an._seam_absence_claims(d2, rows2, number_calls=palm_calls)
    assert cen2["absence_rows_appended"] == 0 and d2["mechanism"] == palm   # an EMPTY read never appends
    assert "NO ROWS RETURNED" not in d2["mechanism"]
    # A TRUE ABSENCE: the claim names a rendered hop the board read NO series for -> nothing appended.
    import types
    from leviathan.graphrag.state import render as R
    hop = types.SimpleNamespace(contract="soybeans_cbot", driver_id="China_import_tariff", series_key="",
                                measured=False)
    board = types.SimpleNamespace(rows=(), chains=(types.SimpleNamespace(rendered=True, hops=(hop,)),))
    names = list(R.chain_hop_reader_names(hop))
    assert names, "the render names the hop for a reader"
    sent3 = "The %s link has no series this page could read." % names[0]
    d3 = {"tldr": "", "mechanism": sent3}
    cen3 = an._seam_absence_claims(d3, an._seam_row_index(deep_calls), number_calls=deep_calls,
                                   board=board)
    assert cen3["absence_rows_appended"] == 0 and d3["mechanism"] == sent3
    assert cen3.get("absence_true") == 1, cen3


def test_DOCKET7_the_same_row_served_twice_is_COUNTED_where_it_cannot_yet_be_deduped():
    """ROUND2_DOCKET #7, on the max turn's own payloads: `gold_board_crush` reached the writer TWICE,
    N36/N37/N38 == N39/N40/N41, and the note then counted it as two legs of a pattern quorum. The [N]
    index space is minted inside `numbers/cascade.quantify` against the PROMPT BLOCK the writer read,
    so the dedupe belongs to the producer (handed over in HANDOFF_E_writer.md); what this seam owes is
    a number the arm can see."""
    crush = _call("gold_board_crush", "board crush margin", None, "global", "MY2026-08-20", 2.6038,
                  "USD/bu", "2026-08-21")
    sig = _call("gold_board_crush", "board crush margin", None, "global", "MY2026-08-20", 0.6,
                "sigma", "2026-08-21")
    pct = _call("gold_board_crush", "board crush margin", None, "global", "MY2026-08-20", 92,
                "percentile", "2026-08-21")
    calls = [None] * 35 + [crush, sig, pct, crush, sig, pct]
    cen = an._seam_served_duplicates(an._seam_row_index(calls))
    assert cen["served_row_duplicate_groups"] == 3 and cen["served_rows_duplicated"] == 3
    assert an._seam_served_duplicates(an._seam_row_index([crush, sig, pct])) == \
        {"served_row_duplicate_groups": 0, "served_rows_duplicated": 0}
    # it is a COUNT and never a rewrite: the census key rides, the prose does not move
    d = {"tldr": "T [N36].", "mechanism": "Crush [N36] and crush [N39]."}
    before = dict(d)
    cen2 = an._writer_seam_lints(d, calls, asof=ASOF, mode="max")
    assert cen2["served_row_duplicate_groups"] == 3 and d == before


def test_DOCKET11_one_handle_grammar_in_the_BODY_and_the_FOOTER():
    """ROUND2_DOCKET #11, the max turn's own collision: the body cites `[E23]`/`[E18]`/`[E28]`, the
    footer printed `[23]`/`[18]`/`[28]`, and the same block ALSO carries `[N18]` -- so a reader
    resolving [N18] met `[18] USDA WASDE (2021-05-12)` beside it."""
    d = {"tldr": "China imposed a tariff [E23]; the 2021/22 outlook [E18]; Argentina [E28].",
         "mechanism": "ONI reads 1.8 degC [N18].",
         "sources": [{"ref": 23}, {"ref": 18}, {"ref": 28}]}
    v = {"enabled": True, "resolved": {
        "23": {"source": "USDA FAS GAIN Report - Soybeans", "date": "2025-03-19", "snippet": "China."},
        "18": {"source": "USDA WASDE", "date": "2021-05-12", "snippet": "The 2021/22 outlook."},
        "28": {"source": "USDA FAS GAIN Report - Soybeans", "date": "2023-04-14", "snippet": "April."}}}
    calls = [None] * 17 + [_call("silver_noaa_oni", "ONI anomaly", None, "global", "MY2026-07",
                                 1.8, "degC", "2026-09-05")]
    out = an._cited_sources_block(dict(d), v, calls, seam_lints=True)
    for tok in ("[E23]", "[E18]", "[E28]", "[N18]"):
        assert tok in out, tok
    assert re.search(r"^\[18\]", out, re.M) is None            # the COLLIDING bare spelling is gone
    # ...and HEAD's branch is untouched, collision and all
    off = an._cited_sources_block(dict(d), v, calls)
    assert re.search(r"^\[18\] USDA WASDE", off, re.M) is not None


def test_DOCKET8_the_recency_ledger_reads_the_rows_this_turn_SERVED_and_spells_them_ISO(monkeypatch):
    """ROUND2_DOCKET #8 / H-E-2. The max turn told the writer "the newest knowledge date on a number
    row 20260904" while its own `## Sources` carried `[known 2026-09-14]` -- seven days newer, and
    undashed where every other date on that page is ISO. Two graders filed it. Note WHY the ISO
    spelling is load-bearing rather than cosmetic: sorted against `2026-09-11`, the string `20260904`
    lands FIRST, which is exactly how the oldest-looking stamp in the set became the 'newest'.

    ROUND 3 RE-ANCHOR, AND THIS PIN USED TO ASSERT THE BUG. Its name said "the rows the FOOTER
    renders" and its last two lines pinned the seam's UNGATED `number_calls=extra_number_calls,`
    while calling the pair byte-identical flag-off. Both were wrong, and the second was the census's
    BLOCKER-1: the kwarg is consumed behind `GRAPHRAG_RECENCY_FACTS`, which `arm_env_base.yaml` sets
    to `on` in `copy_from_taskdef` -- the block BOTH arm-A cells inherit -- so with the board DARK the
    control cell's writer was handed a range HEAD's control cell is not (measured: the sentence moved
    on 112 of 112 banked turns, and 0 of 112 with the gate below). The name is corrected too: the
    served menu is a SUPERSET of the footer's set and cannot be anything else at prompt-build time."""
    class _B:
        series = {"esr": type("S", (), {"knowledge_date": "20260904"})()}
        tape: dict = {}
    calls = [_call("silver_esr", "weekly exports", "soybeans_cbot", None, "MY2026-08-27", 311.846,
                   "1000 MT", "20260904"),
             _call("futures_eod", "settlement price", "soybeans_cbot", None, "2027-03", 1328,
                   "US cents/bushel", "2026-09-14"),
             _call("silver_wasde", "ending stocks", "soybeans", "united_states", "MY2026/27", 310,
                   "Million Bushels", "2026-09-11")]
    kw = an._board_ledger_kwargs(_B(), calls)
    assert kw["kd_max"] == "2026-09-14" and kw["kd_min"] == "2026-09-04"
    assert an._board_ledger_kwargs(None, calls) == {}          # no board -> phase 0s's own string
    # with NO calls the board's own series is the fallback, ISO-spelled
    assert an._board_ledger_kwargs(_B(), [])["kd_max"] == "2026-09-04"
    assert an._board_ledger_kwargs(_B(), None)["kd_min"] == "2026-09-04"
    # ...and the SENTENCE ITSELF, through the producer both serving bodies call: the rows win over the
    # board's own series, and they ride their OWN kwarg because `**_board_ledger_kwargs(_board))` is
    # pinned BY SOURCE TEXT in a deck this lane does not own.
    assert an._ledger_row_dates(calls) == ("2026-09-14", "2026-09-04")
    assert an._ledger_row_dates([]) == ("", "") and an._ledger_row_dates(None) == ("", "")
    # ══ THE GATE (round 3, census BLOCKER-1) ═══════════════════════════════════════════════════════
    # THE SOURCE TEXT: the rows kwarg is GATED on the board at the one seam that threads it.
    src = inspect.getsource(an._answer_l2)
    blk = src[src.index("_ledger_line += _recency_ledger_suffix("):][:400]
    assert "number_calls=(extra_number_calls if _board is not None else None)," in blk
    assert "number_calls=extra_number_calls," not in blk        # the ungated spelling is GONE
    assert src.count("**_board_ledger_kwargs(_board))") == 1
    # ...AND THE BYTES, which is what the source text is only a proxy for. With the board off and
    # `GRAPHRAG_RECENCY_FACTS` ON -- the arm's CONTROL cell, and serving rev 133 -- the suffix the seam
    # builds is phase 0s's own string: no row range, and identical to the call that passes no rows at
    # all. There was no assertion of this anywhere in the estate before round 3.
    monkeypatch.setenv("GRAPHRAG_RECENCY_STAMP", "on")
    monkeypatch.setenv("GRAPHRAG_RECENCY_FACTS", "on")
    monkeypatch.delenv("GRAPHRAG_STATE_BOARD", raising=False)
    _board = None                                              # the control cell's own value
    off = an._recency_ledger_suffix("2026-03-14", asof="2026-09-07", n_rows=9,
                                    number_calls=(calls if _board is not None else None),
                                    **an._board_ledger_kwargs(_board))
    assert off == an._recency_ledger_suffix("2026-03-14", asof="2026-09-07", n_rows=9)
    assert off == (" The number rows on this page are read as of 2026-09-07, and each row carries its "
                   "own knowledge date. The newest dated document behind this answer is 2026-03-14 "
                   "(reported dates). Each of those is a fact about the layer it names, and none "
                   "dates the others.")
    assert "the newest is" not in off and "the oldest" not in off
    # ...and with the board PRESENT the rows still win over its series, which is docket #8's own fix.
    on = an._recency_ledger_suffix("2026-03-14", asof="2026-09-07", n_rows=9,
                                   number_calls=calls, **an._board_ledger_kwargs(_B()))
    assert "the newest is 2026-09-14 and the oldest 2026-09-04" in on


def test_NEW3_a_NEGATED_claim_is_left_exactly_as_written_by_BOTH_substituting_fences():
    """ROUND-3 REVIEW NEW-3, the reviewer's own four inputs, on the SMOKE'S OWN ROWS.

    Both fences replace the reader's verdict word IN PLACE, and both read the claim as if it were
    asserted -- so on a NEGATED sentence, which is the same words with the opposite truth value, the
    correction turned a TRUE sentence into a FALSE one. Measured before the guard, verbatim:

        "... its window (June to December 2026) does not sit inside the horizon."      (TRUE)
          -> "... does not sit outside the horizon (the declared two-to-four-quarter lag ...)"  FALSE
        "... is nowhere near inside the horizon."   -> "... is nowhere near outside ..."        FALSE
        "This is not a record-high harvested area of 34.76 M ha [N42]."                (TRUE)
          -> "This is not a 91st-percentile harvested area of 34.76 M ha [N42]."                FALSE
        "Harvested area is nowhere near a record high [N42]."
          -> "Harvested area is nowhere near a 91st-percentile [N42]."                          FALSE

    Incidence on every corpus this lane holds -- 112 banked answers, 5 served bodies, 5 drafts, 1,004
    sentences -- is 0, and the banked replay is byte-identical with the guard on and off (no census
    key moves). It is guarded anyway because these two rules rewrite the TL;DR and the mechanism's
    verdict and the shapes above are ordinary English. THE MISS IS STAMPED, never silent."""
    rows = _rows(MAX_ROWS)
    pcts = an._seam_percentiles(rows)
    # ROUND-3 REVIEW MAJOR-1: the CONTRACTED form ("isn't") must be guarded too -- the `n't` branch used to sit
    # under the lookbehind and could never match, so this case was green on a dead branch.
    for txt in (LAG_LINE.replace("is inside the horizon", "does not sit inside the horizon"),
                LAG_LINE.replace("is inside the horizon", "is nowhere near inside the horizon"),
                LAG_LINE.replace("is inside the horizon", "isn't inside the horizon")):
        d = {"tldr": "", "mechanism": txt}
        cen = an._seam_lag_windows(d, rows, ASOF, 3)
        assert d["mechanism"] == txt                           # NOT ONE BYTE
        assert cen["lag_windows_negated"] == 1 and cen["lag_windows_corrected"] == 0
        assert cen["lag_windows_checked"] == 0                 # the row was never read
    for txt in ("This is not a record-high harvested area of 34.76 M ha [N42].",
                "Harvested area is nowhere near a record high [N42].",
                "This isn't a record-high harvested area of 34.76 M ha [N42]."):
        d = {"tldr": txt, "mechanism": ""}
        cen = an._seam_tldr_consistency(d, rows, pcts)
        assert d["tldr"] == txt                                # NOT ONE BYTE
        assert cen["superlatives_negated"] == 1 and cen["superlatives_corrected"] == 0
    # ══ THE POSITIVE CONTROLS: the two corrections round 2 shipped still fire, unchanged ═══════════
    d = {"tldr": "", "mechanism": LAG_LINE}
    assert an._seam_lag_windows(d, rows, ASOF, 3)["lag_windows_corrected"] == 1
    assert "is outside the horizon" in d["mechanism"] and "is inside the horizon" not in d["mechanism"]
    d2 = {"tldr": MAX_TLDR, "mechanism": ""}
    assert an._seam_tldr_consistency(d2, rows, pcts)["superlatives_corrected"] == 1
    assert "a 91st-percentile harvested area of 34.76 M ha [N42]" in d2["tldr"]
    # ══ THE GUARD ITSELF: ONE helper, and a negation binds ITS OWN CLAUSE ═══════════════════════════
    # "Stocks are not tight, and the lag window sits inside the horizon" is an assertion ABOUT THE
    # WINDOW: the negation is in the clause before it and must not reach across the comma.
    carried = ("- Stocks are not tight [N42], and that window, on a two-to-four-quarter lag, sits "
               "inside the horizon.")
    d3 = {"tldr": "", "mechanism": carried}
    cen3 = an._seam_lag_windows(d3, rows, ASOF, 3)
    assert cen3["lag_windows_negated"] == 0 and cen3["lag_windows_corrected"] == 1
    assert an._seam_negated("This is not a record high", len("This is not a ")) is True
    assert an._seam_negated("Stocks are not tight, and area is a record high", 40) is False
    assert an._seam_negated("A record high", 2) is False
    assert an._seam_negated("", 5) is False and an._seam_negated("abc", -1) is False
    # the direction words are NOT negations: they are the lag fence's own vocabulary (the matched span)
    assert an._seam_negated("the window sits outside and ", 28) is False


def test_the_round_2_rules_are_APPEND_ONLY_and_IDEMPOTENT():
    """The lane's own law re-run after round 2, plus the property a correcting lint owes a replay:
    running the whole pass TWICE changes nothing the second time."""
    for st, calls, mode in _CORPUS:
        one = dict(st)
        an._writer_seam_lints(one, calls, asof=ASOF, mode=mode, horizon_months=3)
        two = dict(one)
        an._writer_seam_lints(two, calls, asof=ASOF, mode=mode, horizon_months=3)
        for f in ("tldr", "mechanism"):
            assert two.get(f) == one.get(f), (mode, f, "NOT IDEMPOTENT")
