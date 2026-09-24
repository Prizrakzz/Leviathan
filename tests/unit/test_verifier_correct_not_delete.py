"""THE CITATION VERIFIER CORRECTS, IT DOES NOT DELETE -- the D-EC pre-arm amendment, pinned.

Every fixture below is VERBATIM from the in-VPC pre-arm smoke of 2026-09-16 (five real-seat turns at
commit 17fed3e4, `prearm_smoke_0916/answers/*.trace.json`, fields `strip_audit` and `raw_draft`) or from
the fourteen banked real-seat answers that smoke's window rule was measured against. The row values come
from each answer's own rendered Sources footer. Nothing here is a hand-built case standing alone.

WHAT THE SMOKE MEASURED, and what these pins hold:
  * 15 charges over five turns: number_mismatch 7, number_unbacked 5, no_lexical_overlap 3.
  * 12 of the 15 are VERIFIER FALSE POSITIVES in two classes, and 0 are writer misquotes.
      - number_mismatch x7: a handle cited for a WORDED restatement of its own row, convicted by its
        NEIGHBOURS' digits, in a sentence too rich for the one-numeral sibling rescue. FOUR READING
        SENTENCES WERE DELETED, one of them the whole counter-leg of the deep TL;DR.
      - number_unbacked x5: a WINDOW LENGTH ("120 months", "250-session record") read as a claim figure,
        which took the handles OFF two sentences and served seven correct figures BARE.
      - no_lexical_overlap x3: an [E]-handle rule on one dated-documents bullet. OUT OF SCOPE here and
        docketed; it is named so the count of 15 is accounted for in full.
  * one deletion left the lowercase orphan "... on confidence alone. planted area at the 98th percentile
    [N69] points toward lower", which a PM grader called "the tell that a fence deleted the bull half".
  * FOUR sentences were charged two or three times and wrote the same audit row two or three times: the
    15 rows are EIGHT distinct (rule, field, sentence) triples.
"""
from __future__ import annotations

import os

import pytest
from leviathan.graphrag import verify as vf

_EM = chr(0x2014)                       # the writer's em dash, spelled so this source stays ASCII

# -- the smoke sentences, verbatim (em dash built with chr() so this source stays ASCII) ----------------------
S_DEEP_TLDR = ("Against it sit a slack export program in the bottom decile of its own record [N40] and US "
               "area at 34.76 M ha [N59], and the ocean signal at +1.8 degC [N23] is an El Nino-phase "
               "reading that the driver model signs as price-pressuring on beans, so this is a genuinely "
               "two-sided board with the tighter-balance-plus-crush leg ahead on confidence.")
S_DEEP_ENSO = ("- Tropical Pacific +1.8 degC [N23], +2.4 sigma on 120 months [N24], 93rd percentile [N25], "
               "rising eight months running.")
S_DEEP_WATCH = ("- **US weekly export shipments, 311.85 thousand MT [N38]** " + _EM + " bottom decile [N40] and "
                "past the desk's own line for a lagging pace.")
S_MAX_CRUSH = ("The board crush reads 2.6 USD/bu [N36], 92nd percentile of its own 250-session record "
               "[N38], and is one reading printed under two names (board crush and crush margin), so it is "
               "one source of support, not two.")
S_CORN_SU = ("The tight stocks-to-use ratio [N79], at the 16th percentile of its own record [N81] and past "
             "the desk's tight line, and feed demand at the 95th percentile [N66] both point toward higher "
             "prices;")
S_RAPE = ("On rapeseed the record is more one-sided " + _EM + " record Black Sea seed [N5][N14] and softening "
          "crush [N11] both loosen " + _EM + " with the EU growing-season moisture reading, at -0.51 z [N32], "
          "20th percentile [N31], the one leg that could turn it;")
S_SOYOIL = ("Indonesia's palm-belt drought reads 0.16 z [N62], +0.7 sigma on its own ten-year window [N63], "
            "and the ocean index reads -0.39 degC [N71], on the cool side of its record [N73] " + _EM + " the "
            "two-to-four-quarter yield channel is not yet a supply shock.")


def _calls(rows: dict, unit: str | None = None) -> list:
    """number_calls long enough for the highest cited [N]; a listed index carries exactly ONE row, and
    `shown` is that row (the `_mismatch_pool` binding every served turn has)."""
    out = []
    for i in range(1, max(rows) + 1):
        if i in rows:
            r = {"value": str(rows[i])}
            if unit:
                r["unit"] = unit
            out.append({"query": {"metric": "m%d" % i}, "rows": [r], "shown": [rows[i]]})
        else:
            out.append({"query": {"metric": "m%d" % i}, "rows": []})
    return out


# The served rows, read off each answer's own `## Sources` footer. Handles the verifier STRIPPED are
# absent from the footer (it renders surviving citations only) and are filled from the SAME metric's
# triple elsewhere in the estate's own footers -- each one named in the comment beside it.
C_DEEP = _calls({23: 1.8,          # [N23] NOAA ONI ONI anomaly global MY2026-07 = 1.8 degC
                 24: 2.4,          # ONI sigma; corn/wheat [N44] + max [N19] print "vs 120 points = 2.4 sigma"
                 25: 93.0,         # its percentile leg
                 38: 311.846,      # [N38] ESR weekly exports = 311.846 1000 MT
                 40: 6.0,          # [N40] ESR weekly exports = 6 percentile   <- the 'bottom decile' handle
                 59: 34.755})      # [N59] PSD area harvested United States MY2026 = 34.755 M ha
C_MAX = _calls({36: 2.6038,        # [N36] GOLD BOARD CRUSH board crush margin = 2.6038 USD/bu
                38: 92.0})         # its percentile leg; deep [N52] prints 92 percentile
C_CORN = _calls({66: 95.0,         # feed-use percentile leg
                 79: 0.121393,     # corn stocks-to-use ratio; [N27] prints 0.121393 on this same turn
                 81: 16.0})        # its percentile leg
C_RAPE = _calls({5: 7.0,           # [N5] PSD production MATIF rapeseed Russia MY2026 = 7 MMT
                 11: 25.1,         # [N11] PSD ATTRIBUTES crush European Union MY2026 = 25.1 MMT
                 14: 4.35,         # [N14] PSD production MATIF rapeseed Ukraine MY2026 = 4.35 MMT
                 31: 20.0,         # EU-belt drought percentile leg
                 32: -0.505799})   # [N32] GOLD WEATHER Z drought z-score EU Belt MY2026-07 = -0.505799 z
C_SOYOIL = _calls({62: 0.15831,    # [N62] GOLD WEATHER Z drought z-score SE Asia Palm Belt = 0.15831 z
                   63: 0.7,        # its sigma leg
                   71: -0.39,      # ONI 2026-01; [N74] prints -0.39 degC on this same turn
                   73: 35.0})      # its percentile leg; palm/rape [N52] prints 35 percentile


def _run(prose: str, calls: list, field: str = "tldr") -> tuple[dict, dict]:
    st = {"tldr": prose if field == "tldr" else "", "mechanism": prose if field == "mechanism" else "",
          "sources": []}
    rep = vf.verify_citations(st, [], calls)
    return st, rep


# ======================================================================================================
# (1) REPAIR, NEVER DELETE -- the four sentences the smoke deleted, each recovered with its figures
# ======================================================================================================

@pytest.mark.parametrize("prose,calls,charged,kept_handles,figures", [
    # deep TL;DR -- the whole counter-leg of the answer. [N40] is the 6th-percentile row cited for the
    # WORDS "bottom decile"; 34.76 is [N59]'s own 34.755 and +1.8 is [N23]'s own row.
    (S_DEEP_TLDR, C_DEEP, ["[N40]"], ["[N59]", "[N23]"], ["34.76", "+1.8"]),
    # quick corn/wheat -- [N79] is the 0.121393 ratio cited for the WORDS "The tight stocks-to-use ratio".
    (S_CORN_SU, C_CORN, ["[N79]"], ["[N81]", "[N66]"], ["16th", "95th"]),
    # quick palm/rape -- THREE handles cited for words ("record Black Sea seed", "softening crush").
    (S_RAPE, C_RAPE, ["[N5]", "[N14]", "[N11]"], ["[N32]", "[N31]"], ["-0.51", "20th"]),
    # quick soyoil -- [N73] cited for "on the cool side of its record".
    (S_SOYOIL, C_SOYOIL, ["[N73]"], ["[N62]", "[N63]", "[N71]"], ["0.16", "+0.7", "-0.39"]),
])
def test_the_four_deleted_sentences_keep_every_figure_and_lose_only_the_mis_citing_handle(
        prose, calls, charged, kept_handles, figures):
    """THE MEASURED DEFECT. Each of these was charged number_mismatch on a handle cited for a WORDED
    restatement of its own row, and HEAD deleted the sentence whole because `_sibling_backed` demanded
    EXACTLY ONE claim numeral and these carry two or three. Every figure in every one of them is right --
    the proof is that each one is materialized by another [N] in the same sentence."""
    # 09-23 FIX ROUND (lane V) -- AMENDED, OWNER-VISIBLE: the handle cited for WORDS is no longer charged.
    # `verify._unbound_handle` reads the binding the writer wrote ("figure [N]"): this handle binds no figure
    # and every figure in the sentence is backed by the handle it binds to, so no figure can contradict it --
    # exactly as the same handle in a digit-free sentence is never charged. The 09-23 fact graders scored
    # HEAD's handle drop on this class a verifier FALSE POSITIVE (tariff 12/12, palm/rape 5/5).
    st, rep = _run(prose, calls)
    out = st["tldr"]
    assert out == prose, "the sentence must survive whole: %r" % out
    for h in charged + kept_handles:
        assert h in out, "a handle that binds no figure it contradicts stays: %s" % h
    for f in figures:
        assert f in out, "the figure must stay on the page: %s" % f
    assert rep["by_rule"] == {}
    assert rep["repaired"] == 0 and rep["repairs"] == []   # CYCLE-10 holds: nothing is REWRITTEN


@pytest.mark.parametrize("prose,calls,swap", [
    (S_DEEP_TLDR, C_DEEP, ("34.76 M ha", "99.99 M ha")),
    (S_CORN_SU, C_CORN, ("16th percentile", "41st percentile")),
    (S_RAPE, C_RAPE, ("-0.51 z", "-3.44 z")),
    (S_SOYOIL, C_SOYOIL, ("0.16 z", "7.77 z")),
])
def test_the_adversarial_twin_of_each_still_dies_whole(prose, calls, swap):
    """THE FAIL-CLOSED RATIONALE, UNMOVED. The rescue fires only when EVERY claim numeral in the sentence
    is materialized by a sibling handle. Fabricate ONE of them and the sentence dies exactly as at HEAD --
    a fabricated number must never survive the loss of its handle."""
    bad = prose.replace(*swap)
    assert bad != prose
    st, rep = _run(bad, calls)
    assert st["tldr"] == ""                                # the whole sentence, as today
    assert rep["by_rule"].get("number_mismatch", 0) >= 1


def test_the_one_numeral_rescue_is_byte_identical_the_export_watch_bullet():
    """THE SHAPE THAT ALREADY WORKED, AND MUST NOT MOVE. deep's export-watch bullet carries ONE claim
    numeral (311.85) backed by [N38], so HEAD's rescue already fired and dropped [N40] alone. The widened
    predicate answers the same question on the same sentence."""
    # 09-23 FIX ROUND (lane V) -- AMENDED, OWNER-VISIBLE: the handle cited for WORDS is no longer charged.
    # `verify._unbound_handle` reads the binding the writer wrote ("figure [N]"): this handle binds no figure
    # and every figure in the sentence is backed by the handle it binds to, so no figure can contradict it --
    # exactly as the same handle in a digit-free sentence is never charged. The 09-23 fact graders scored
    # HEAD's handle drop on this class a verifier FALSE POSITIVE (tariff 12/12, palm/rape 5/5).
    st, rep = _run(S_DEEP_WATCH, C_DEEP, field="mechanism")
    assert st["mechanism"] == S_DEEP_WATCH
    assert rep["by_rule"] == {}
    assert vf._sibling_backed(S_DEEP_WATCH, 40, C_DEEP) is True          # the predicate itself is unmoved


def test_a_sentence_whose_figure_no_sibling_carries_still_dies():
    """The residual class, stated as a pin: two numerals, one handle, nothing corroborating either."""
    assert vf._sibling_backed("Stocks ran 10.72 % [N1] against a 2.6 crush.", 1,
                              _calls({1: 44.0})) is False
    st, rep = _run("Stocks ran 10.72 % [N1] against a 2.6 crush.", _calls({1: 44.0}))
    assert st["tldr"] == "" and rep["by_rule"].get("number_mismatch") == 1


def test_a_sentence_with_no_other_handle_can_never_be_rescued():
    """A solitary handle has no sibling to materialize anything, so the drop stands -- HEAD's behaviour
    on the single-handle transcription fabrications (`test_verify.py`'s judge fixtures) is untouched."""
    assert vf._sibling_backed("The index sat at -0.693675 z [N14].", 14, _calls({14: -2.1035})) is False


# ======================================================================================================
# (2) A WINDOW LENGTH IS NEVER A CLAIM FIGURE -- rule (h)
# ======================================================================================================

def test_the_two_charged_smoke_sentences_stop_charging_their_window_length():
    """VERBATIM from the smoke's two `number_unbacked` sentences. `120` is the ONI's own observation
    window (its citation line prints "vs 120 points of its own history = 2.4 sigma") and `250` is the
    board crush's; neither can be a row value. HEAD read them as claim magnitudes, found no row, and
    stripped EVERY handle off both sentences -- five handles, seven correct figures left bare."""
    assert vf._claim_numbers_in(vf._HANDLE.sub("", S_DEEP_ENSO)) == [1.8, 2.4, 93.0]
    assert vf._claim_numbers_in(vf._HANDLE.sub("", S_MAX_CRUSH)) == [2.6, 92.0]


def test_the_two_charged_smoke_sentences_keep_every_handle_end_to_end():
    st, rep = _run(S_DEEP_ENSO, C_DEEP, field="mechanism")
    assert st["mechanism"] == S_DEEP_ENSO and rep["by_rule"] == {}
    st2, rep2 = _run(S_MAX_CRUSH, C_MAX, field="mechanism")
    assert st2["mechanism"] == S_MAX_CRUSH and rep2["by_rule"] == {}


@pytest.mark.parametrize("sent,want", [
    # the nine de-charged numerals in the FOURTEEN BANKED real-seat answers -- an UNSEEN corpus: this rule
    # was written from the five smoke answers alone and only then run over these.
    ("crush margin 2.6 USD/bu [N4], +0.6 sigma on 250 sessions [N5], past the desk's high line", [2.6, 0.6]),
    ("board crush at 1.06 USD per bushel [N7], +0.9 sigma on 250 sessions [N8], 75th percentile [N9]",
     [1.06, 0.9, 75.0]),
    ("export sales at 664.8 thousand MT [N2], -1.0 sigma on 52 weeks [N3], 13th percentile [N4]",
     [664.8, 1.0, 13.0]),
    ("funds held 31584 contracts [N25], -0.8 sigma on 156 weeks [N26], 28th percentile [N27]",
     [31584.0, 0.8, 28.0]),
    ("MY2026M11 settled 486.69 USD/t [N1], 29th percentile of the 320-session window read [N2]",
     [486.69, 29.0]),
    ("at the 29th percentile of the 320-session window [N2].", [29.0]),
    # ...and the two spellings the banked corpus writes in WORDS, which were never charged and must not move
    ("-1.3 sigma on fifty-two weeks [N39]", [1.3]),
    ("+2.4 sigma on its own ten-year window [N19]", [2.4]),
])
def test_the_unseen_banked_window_shapes(sent, want):
    assert vf._claim_numbers_in(vf._HANDLE.sub("", sent)) == want


@pytest.mark.parametrize("sent,want", [
    # THE EIGHT CYCLE-8 HEAD-POSITION COUNTER-EXAMPLES, re-asserted against the new rule. Not one flips.
    ("prices have risen for 5 months in a row [N10]", 5.0),
    ("ending stocks cover 21 days of use [N6]", 21.0),
    ("US corn is 12 days ahead of the pace [N4]", 12.0),
    ("the crush ran 3 weeks behind schedule [N5]", 3.0),
    ("exports rose in each of the last 5 months of the marketing year [N1]", 5.0),
    ("(10 days before the as-of date)", 10.0),
    ("published within 6 days prior to the 2026-08-07 as-of", 6.0),
    ("stocks are 12 months of use [N8]", 12.0),
    # ...and the rest of the cycle-8 head-position pin
    ("the harvest is running 10 days behind the average [N2]", 10.0),
    ("stocks cover 45 days of demand [N3]", 45.0),
    ("the CNY has moved only marginally over the past 90 days [N7]", 90.0),
    ("risen for 5 consecutive months", 5.0),
    # THE CLASS THE THREAT MODEL'S OWN PROPOSAL WOULD HAVE LOST. Putting `point`/`session` straight into
    # `_DURATION_NOUN` arms rule (f)'s hyphen branch for ANY following word; requiring a WINDOW HEAD NOUN
    # keeps these magnitudes, and they are magnitudes.
    ("a 12-point drop [N3]", 12.0),
    ("a 5-point move in the index [N1]", 5.0),
    ("the index fell 30 points [N2]", 30.0),
    ("a 3-session rally [N4]", 3.0),
    ("the 2-reading average was beaten by 4 prints [N6]", 4.0),
])
def test_head_position_and_magnitude_shapes_are_still_claims(sent, want):
    assert want in vf._claim_numbers_in(sent), sent


def test_rule_h_needs_a_statistic_lead_for_the_space_spelling():
    """The LEFT context is the whole fence on the space spelling: a window preposition alone is not it."""
    assert vf._claim_numbers_in("stocks fell over 120 months [N1]") == [120.0]
    assert vf._claim_numbers_in("a target of 120 months [N1]") == [120.0]
    assert vf._claim_numbers_in("+2.4 sigma on 120 months [N1]") == [2.4]


def test_rule_h_needs_a_window_head_noun_for_the_hyphen_spelling():
    assert vf._claim_numbers_in("its own 250-session record [N1]") == []
    assert vf._claim_numbers_in("its own 250-session rally [N1]") == [250.0]


def test_the_frozen_pre_amendment_view_does_not_move():
    """B.6: `_claim_number_spans(s, cycle8=False)` is HEAD's own extractor and rules (e)-(h) are all
    gated on the flag, so the frozen off-view must still see every window length as a claim."""
    for sent in (S_DEEP_ENSO, S_MAX_CRUSH, "at the 29th percentile of the 320-session window [N2]."):
        masked = vf._mask_handles(sent)
        frozen = [v for _a, _b, v in vf._claim_number_spans(masked, cycle8=False)]
        shipped = [v for _a, _b, v in vf._claim_number_spans(masked)]
        assert len(frozen) > len(shipped), sent
    assert [v for _a, _b, v in
            vf._claim_number_spans("+2.4 sigma on 120 months", cycle8=False)] == [2.4, 120.0]


def test_the_window_exemption_reverts_with_the_frozen_flag_and_never_adds_a_claim():
    """One-sidedness, stated as a property: on every smoke sentence the new extractor returns a SUBSET of
    HEAD's spans. Rule (h) can remove a claim; it can never mint one."""
    for sent in (S_DEEP_TLDR, S_DEEP_ENSO, S_DEEP_WATCH, S_MAX_CRUSH, S_CORN_SU, S_RAPE, S_SOYOIL):
        masked = vf._mask_handles(sent)
        new = {(a, b) for a, b, _v in vf._claim_number_spans(masked)}
        old = {(a, b) for a, b, _v in vf._claim_number_spans(masked, cycle8=False)}
        assert new <= old, sent


# ======================================================================================================
# (3) TOLERANCE -- the four restatement classes the smoke writes, each MATCHING its row
# ======================================================================================================
# NO CODE MOVED FOR THIS SECTION. Cycle-6's reader-precision arm and `_num_matches`' scale set already
# clear every measured case, and the threat model rejected loosening `_num_matches` for exactly that
# reason ("the headline check must be tight"). These are REGRESSION pins on the smoke's own sentences so
# that a future amendment cannot quietly re-open the class.

@pytest.mark.parametrize("prose,row,label", [
    # a z / sigma printed to 2 dp
    ("the EU growing-season moisture reading, at -0.51 z [N1]", -0.505799, "z at 2 dp"),
    ("Indonesia's palm-belt drought reads 0.16 z [N1]", 0.15831, "z at 2 dp"),
    ("the ocean index reads -0.39 degC [N1]", -0.39, "degC exact"),
    # a percentile printed as an integer ordinal
    ("at the 16th percentile of its own record [N1]", 16.0, "percentile ordinal"),
    ("20th percentile [N1]", 20.0, "percentile ordinal"),
    ("92nd percentile [N1]", 92.0, "percentile ordinal"),
    # a value rounded to the printed precision
    ("US area at 34.76 M ha [N1]", 34.755, "rounded to 2 dp"),
    ("US weekly export shipments, 311.85 thousand MT [N1]", 311.846, "rounded to 2 dp"),
    ("The board crush reads 2.6 USD/bu [N1]", 2.6038, "rounded to 1 dp"),
    # a ratio printed as percent, and a percent printed as itself
    ("the soyoil carryout ratio at 5.67 % [N1]", 0.0567, "ratio served as a fraction"),
    ("the soyoil carryout ratio at 5.67 % [N1]", 5.66691, "ratio served as a percent"),
    ("stocks-to-use at 12.1% [N1]", 0.121393, "ratio served as a fraction"),
])
def test_a_correct_restatement_matches_its_row(prose, row, label):
    assert vf._check_number_handle(prose, 1, _calls({1: row})) is None, label


@pytest.mark.parametrize("prose,row", [
    ("the moisture reading, at -0.62 z [N1]", -0.505799),      # 2 dp, but not this row's rounding
    ("US area at 44.76 M ha [N1]", 34.755),
    ("at the 41st percentile of its own record [N1]", 16.0),
])
def test_a_wrong_restatement_still_charges(prose, row):
    assert vf._check_number_handle(prose, 1, _calls({1: row})) == "number_mismatch"


# ======================================================================================================
# (4) THE ORPHAN LINT -- no strip may leave a sentence opening lowercase
# ======================================================================================================

_ORPHAN_FIELD = ("Corn's own high-confidence rows point opposite ways and neither dominates on confidence "
                 "alone. The tight stocks-to-use ratio [N79] at 41 percent, at the 16th percentile of its "
                 "own record [N81]; planted area at the 98th percentile [N69] points toward lower.")


def test_the_measured_orphan_the_smoke_shipped_is_refused_and_stamped():
    """THE MEASURED DEFECT. `_BOUND` ends a unit on ';' as well as on '.', so a fail-closed whole-sentence
    drop cut a semicolon-joined clause out of the MIDDLE of a reader's sentence and the smoke served
    "... on confidence alone. planted area at the 98th percentile [N69] points toward lower." Here the
    clause carries an unbackable 41, so the rescue CANNOT save it -- and the drop is refused anyway.

    ROUND 2 (2026-09-17), MAJOR-1: refusing the drop is only half the remedy. Round 1 kept the sentence
    and removed [N79], which served "41 percent" with NOTHING behind it -- the shape this estate's
    doctrine calls worse than a deletion. The figure now goes with the citation and the WORDS stay, and
    [N81] is kept because it is the only thing left backing "16th"."""
    calls = _calls({69: 98.0, 79: 0.121393, 81: 16.0})
    st, rep = _run(_ORPHAN_FIELD, calls, field="mechanism")
    out = st["mechanism"]
    assert "planted area at the 98th percentile [N69]" in out
    assert "alone. planted area" not in out                   # the orphan the PM grader named
    assert "[N79]" not in out                                 # the mis-citing handle alone is removed
    assert "41 percent" not in out                            # ...and its unbackable figure with it
    assert "a level this page could not back" in out          # the words stay: words are free
    assert "at the 16th percentile of its own record [N81]" in out     # the last backer is never dropped
    assert rep["orphan_kept"] == 1 and rep["backer_kept"] == 1
    assert rep["by_rule"].get("number_mismatch") == 1
    with_audit = _audit_rules(_ORPHAN_FIELD, calls)
    assert "number_mismatch_orphan_figure_cut" in with_audit   # stamped, never silent


def _audit_rules(prose, calls):
    os.environ["GRAPHRAG_STRIP_AUDIT"] = "on"
    try:
        _st, rep = _run(prose, calls, field="mechanism")
        return [e["rule"] for e in rep["strip_audit"]]
    finally:
        os.environ.pop("GRAPHRAG_STRIP_AUDIT", None)


def test_a_drop_that_orphans_nothing_is_still_taken_whole():
    """The lint is NARROW: a sentence followed by an uppercase opening drops exactly as at HEAD."""
    field = ("The index sat at -0.693675 z [N14]. Stocks are comfortable and the board is two-sided.")
    st, rep = _run(field, _calls({14: -2.1035}), field="mechanism")
    assert st["mechanism"] == "Stocks are comfortable and the board is two-sided."
    assert "orphan_kept" not in rep
    assert rep["by_rule"] == {"number_mismatch": 1}


def test_the_lint_reads_PROMOTION_not_lowercase():
    """A clause that was ALREADY mid-sentence stays mid-sentence AND is followed by a lowercase
    continuation on the same line, so the cut leaves the reader's punctuation exactly as written ("A; B;
    c." -> "A; c.") and the drop is taken. This is the one ';'-interior shape the round-2 MIRROR arm
    still admits, and it is admitted because nothing is stranded on either side."""
    text = "Stocks are ample; the index sat at -0.693675 z [N14]; the board is two-sided."
    st, rep = _run(text, _calls({14: -2.1035}), field="mechanism")
    assert "-0.693675" not in st["mechanism"]
    assert st["mechanism"] == "Stocks are ample; the board is two-sided."
    assert rep["by_rule"] == {"number_mismatch": 1} and "orphan_kept" not in rep


def test_orphan_kept_is_absent_when_nothing_orphans():
    """OFF-ARM CLEAN: the key is minted only when the lint fires. A key present and always zero is a
    column that says 'measured' when nothing measured it."""
    _st, rep = _run(S_DEEP_TLDR, C_DEEP)
    assert "orphan_kept" not in rep


# ======================================================================================================
# (5) ONE SENTENCE, ONE AUDIT ENTRY
# ======================================================================================================

def test_the_triple_charged_rapeseed_sentence_writes_one_audit_row():
    """MEASURED: the smoke's five answers wrote 15 audit rows over EIGHT distinct (rule, field, sentence)
    triples -- deep's ENSO bullet x3, max's crush sentence x2, palm/rape's rapeseed sentence x3 and its
    dated-documents bullet x3. A reader counting rows read '15 charges' where the verifier had touched
    eight sentences, and the smoke report did exactly that."""
    # 09-23 FIX ROUND (lane V) -- AMENDED, OWNER-VISIBLE: the handle cited for WORDS is no longer charged.
    # `verify._unbound_handle` reads the binding the writer wrote ("figure [N]"): this handle binds no figure
    # and every figure in the sentence is backed by the handle it binds to, so no figure can contradict it --
    # exactly as the same handle in a digit-free sentence is never charged. The 09-23 fact graders scored
    # HEAD's handle drop on this class a verifier FALSE POSITIVE (tariff 12/12, palm/rape 5/5).
    # The three-handle conviction is re-pinned on a sentence whose handles a figure DOES bind to (900,
    # backed by no row), since S_RAPE's word-cited handles are no longer charged at all.
    three = "Stocks are ample; record Black Sea seed [N1], softening crush [N2] and oil [N3] all read 900."
    rules = _audit_rules(three, _calls({1: 7.0, 2: 25.1, 3: 4.35}))
    assert rules == ["number_mismatch_orphan_figure_cut"]     # three offending handles, ONE row


def test_the_counters_keep_their_per_handle_semantics():
    """SCOPE, DELIBERATELY NARROW: the de-duplication is the AUDIT's. `stripped` and `by_rule` are the
    estate's standing strip counters and every banked number is denominated in them, so they are NOT
    redefined on the eve of an arm."""
    three = "Stocks are ample; record Black Sea seed [N1], softening crush [N2] and oil [N3] all read 900."
    _st, rep = _run(three, _calls({1: 7.0, 2: 25.1, 3: 4.35}), field="mechanism")
    assert rep["by_rule"]["number_mismatch"] == 3 and rep["stripped"] == 3


def test_two_DIFFERENT_sentences_under_one_rule_still_write_two_rows():
    """The de-duplication is keyed on (rule, field, sentence) -- it can never merge two sentences."""
    field = ("The index sat at -0.693675 z [N1]. It later printed -1.78323 z [N2].")
    rules = _audit_rules(field, _calls({1: -2.1035, 2: -1.4097}))
    assert rules == ["number_mismatch", "number_mismatch"]


# ======================================================================================================
# (6) THE BYTE-IDENTICAL SET -- a sentence that was CORRECT under the old rule renders identically
# ======================================================================================================

@pytest.mark.parametrize("prose,calls", [
    ("Record corn prices occurred in August 2012 [N1].", _calls({1: 31400000.0})),
    ("US ending stocks are 31.4 million MT [N1].", _calls({1: 31400000.0})),
    ("currently below the 5-year mean [N1] at 0.34 USD [N2]", _calls({1: 0.344931, 2: 0.34})),
    ("prices have risen for 5 months in a row [N1]", _calls({1: 5.0})),
    ("feed use at 154,947 (1000 MT) [N1]", [{"query": {"metric": "feed"},
                                             "rows": [{"value": "154947", "unit": "1000 MT"}],
                                             "shown": [154947.0]}]),
    (S_DEEP_ENSO, C_DEEP),
    (S_MAX_CRUSH, C_MAX),
])
def test_a_clean_sentence_is_untouched(prose, calls):
    st, rep = _run(prose, calls, field="mechanism")
    assert st["mechanism"] == prose
    assert rep["stripped"] == 0 and rep["by_rule"] == {}


def test_the_verifier_kill_switch_and_the_handle_mode_rollback_are_unmoved():
    os.environ["GRAPHRAG_VERIFY_NUM_MODE"] = "handle"
    try:
        # 09-23 (lane V): S_CORN_SU's [N79] is no longer charged (it binds no figure); the handle-mode
        # rollback is pinned on a sentence the rule still charges.
        st, rep = _run("Stocks ran 10.72 % [N1] against a 2.6 crush.", _calls({1: 44.0}), field="mechanism")
        assert "[N1]" not in st["mechanism"] and "10.72 %" in st["mechanism"]
        assert rep["by_rule"].get("number_mismatch") == 1
    finally:
        os.environ.pop("GRAPHRAG_VERIFY_NUM_MODE", None)
    os.environ["GRAPHRAG_VERIFY"] = "off"
    try:
        st, rep = _run(S_CORN_SU, C_CORN, field="mechanism")
        assert st["mechanism"] == S_CORN_SU and rep["enabled"] is False
    finally:
        os.environ.pop("GRAPHRAG_VERIFY", None)


# ======================================================================================================
# ROUND 2 (2026-09-17) -- THE ADVERSARIAL REVIEW'S FOUR MAJORS AND THE SYNTHESIZER'S FOUR DOCKET ITEMS.
#
# Every fixture in this section is VERBATIM from the 112-answer banked replay the round-1 reviewer ran
# (`data/batch_runs/*.json`, fields `raw_draft.preverify_*` and `served_rows`) or from the reviewer's own
# probes, quoted in `prearm_fix_r1/B_verifier_REVIEW.md`. The pools are each call's OWN rows.
# ======================================================================================================

def _pool(rows: dict) -> list:
    """number_calls whose listed indices carry a REAL multi-row pool (the banked shape: a window call
    holds its whole window, and `shown` is dropped by the artifact projection)."""
    out = []
    for i in range(1, max(rows) + 1):
        vals = rows.get(i)
        out.append({"query": {"metric": "m%d" % i},
                    "rows": [{"value": str(v)} for v in (vals or [])]})
    return out


# -- the banked orphan-lint population, verbatim ------------------------------------------------------
B_CANOLA = ("- Canadian canola stocks-to-use was 16.8472% at this as-of [N23] -- a thin cushion, so a "
            "seed-side supply shock is right-tailed while a big crop is capped by the same low carry.\n"
            "- Canadian canola production was last read at 22,500,000 MT [N14]; the MY2025 Canadian read "
            "was 22,000,000 MT [N13].")
B_CANOLA_CALLS = _pool({13: [22000000.0], 14: [300000.0, 513000.0, 585000.0, 560000.0, 440000.0,
                                               758000.0, 1638000.0, 2155000.0],
                        23: [16.84722222222222]})
B_RAPEMEAL = ("On the numbers actually served, the two halves of the rapeseed crush are NOT symmetric: "
              "the Chinese rapeseed-oil stocks-to-use read stands at 0.1036 [N17] against a year-on-year "
              "change of -0.0451033 [N19] " + _EM + " i.e. the oil side of the Chinese sheet drew down "
              + _EM + " while the corresponding Chinese rapeseed-meal reads are 0 [N18] with a change of "
              "0 [N20], which on its face is not a symmetric crush.")
B_RAPEMEAL_CALLS = _pool({17: [0.0] * 8, 18: [0.0] * 8, 19: [0.0] * 8, 20: [0.0] * 8})
B_SOYOIL_STRESS = ("- Balance sheet, this year: US soybean oil stocks-to-use is 6.05994% [N32], below "
                   "both the 2018/19-era readings of 7.75829% [N24] and 8.29876% [N25]. US soyoil ending "
                   "stocks for MY2025 are 1,552,000 MT [N20]; the palm row is a different scope entirely "
                   + _EM + " 4,091,000 MT of CME palm oil ending stocks for MY2025 [N21] " + _EM + " and "
                   "tonnage levels across two different commodities are not comparable, so that pair does "
                   "not answer your question.")
B_SOYOIL_CALLS = _pool({20: [0.0] * 8, 21: [309000.0, 208000.0, 140000.0, 123000.0, 106000.0, 92000.0,
                             76000.0, 75000.0],
                        24: [7.7582883577486506], 25: [8.29875518672199], 32: [6.0599447111887095]})


def _unbacked_served(text: str, calls: list) -> list:
    """Every claim numeral the SERVED text prints that NO surviving [N] handle in its own sentence
    materializes -- the MAJOR-1 invariant, asked of the output directly."""
    bad = []
    for s in vf.sentences(text):
        ms = vf._mask_handles(s)
        spans = vf._claim_number_spans(ms)
        if not spans:
            continue
        pools = []
        for m in vf._HANDLE.finditer(s):
            for k, j in vf._handle_members(m.group(0)):
                if k == "N" and 1 <= j <= len(calls):
                    pools.append(vf._mismatch_pool(calls[j - 1], vf._row_vals(calls[j - 1])))
        for a, b, v in spans:
            d = [vf._token_decimals(ms[a:b])]
            if not any(vf._num_matches([v], p, d) for p in pools):
                bad.append(ms[a:b])
    return bad


# ======================================================================================================
# MAJOR-1 -- A KEPT SENTENCE NEVER SERVES A FIGURE WITH NOTHING BEHIND IT
# ======================================================================================================

@pytest.mark.parametrize("field,calls,gone,kept", [
    # ROUND 1 SERVED: "- Canadian canola production was last read at 22,500,000 MT;"  -- one figure,
    # no citation. The pool is an eight-row window two orders of magnitude away, so no row figure can be
    # established for the slot and the FIGURE goes with the words kept.
    (B_CANOLA, B_CANOLA_CALLS, ["22,500,000 MT"], ["[N14]", "[N13]", "[N23]", "22,000,000 MT"]),
    # ROUND 1 SERVED: "... stands at 0.1036 against a year-on-year change of -0.0451033 ..." -- TWO
    # figures, no citation, against all-zero rows.
    (B_RAPEMEAL, B_RAPEMEAL_CALLS, ["0.1036", "-0.0451033"], ["the oil side of the Chinese sheet"]),
    # ROUND 1 SERVED: "US soyoil ending stocks for MY2025 are 1,552,000 MT;" and the palm clause with it.
    (B_SOYOIL_STRESS, B_SOYOIL_CALLS, ["1,552,000 MT", "4,091,000 MT"],
     ["[N20]", "[N21]", "6.05994% [N32]", "7.75829% [N24]", "8.29876% [N25]"]),
])
def test_a_sentence_the_orphan_lint_keeps_never_serves_an_unbacked_figure(field, calls, gone, kept):
    """THE ROUND-2 REVIEW'S MAJOR-1, ON ITS OWN MEASURED POPULATION. All seven banked sentences the
    round-1 lint saved shipped a printed figure with NO [N] handle at all. The sentence still stands,
    the words still stand, and what leaves is the figure the page cannot back."""
    st, rep = _run(field, calls, field="mechanism")
    out = st["mechanism"]
    for g in gone:
        assert g not in out, g
    for k in kept:
        assert k in out, k
    assert "a level this page could not back" in out
    assert _unbacked_served(out, calls) == []                 # THE INVARIANT
    assert rep["orphan_kept"] >= 1


def test_the_repair_substitutes_the_cited_rows_own_figure_at_the_pages_precision():
    """Step (2) of the ladder: where the slot IS unambiguous -- one handle, one unbacked numeral, one row
    value, same sign, same order of magnitude, no direction word -- the CITED ROW'S OWN FIGURE is written
    at the precision the page used, and the handle STAYS, so the reader can check it."""
    text = "Stocks are ample; the ratio reads 0.50 [N1]."
    st, rep = _run(text, _calls({1: 0.9134}), field="mechanism")
    assert st["mechanism"] == "Stocks are ample; the ratio reads 0.91 [N1]."   # two decimals: the page's
    assert rep["repairs"] == [{"field": "mechanism", "rule": "number_mismatch_orphan_repaired",
                               "from": "0.50", "to": "0.91"}]
    assert rep["repaired"] == 1 and rep["orphan_kept"] == 1


def test_the_repair_keeps_the_pages_own_thousands_spelling():
    text = "Stocks are ample; production was 22,500,000 MT [N1]."
    st, _rep = _run(text, _calls({1: 21000000.0}), field="mechanism")
    assert st["mechanism"] == "Stocks are ample; production was 21,000,000 MT [N1]."


@pytest.mark.parametrize("text,calls,why", [
    # (a) SOLE ROW -- an eight-row window cannot say which row this slot meant (gate-6 COV1's shape).
    ("Stocks are ample; production was 22,500,000 MT [N1].",
     _pool({1: [300000.0, 513000.0, 585000.0]}), "multi-row pool"),
    # (b) LIVE ROW -- the 0/1 flag row that wrote "is at 1 degC" over a correct 0.98 in gate-6 COV2.
    ("Stocks are ample; the anomaly is at 0.98 degC [N1].", _calls({1: 0.0}), "a zero row"),
    # (c) ORDER OF MAGNITUDE -- a scale apart is not a precision fix.
    ("Stocks are ample; production was 22,500,000 MT [N1].", _calls({1: 300000.0}), "two orders apart"),
    # (d) SIGN -- THE GATE-7 OP THAT ENDED THE REPAIR PATH: "roughly 0.6 z higher [N3]" vs a -0.6267 row.
    ("The pace held; the reading was roughly 0.6 z [N1].", _calls({1: -0.6267}), "opposite signs"),
    # (e) RANGE and SCIENTIFIC NOTATION -- neither half of a written span is a value.
    ("Stocks are ample; the change was -7.61887e-05 [N1].", _calls({1: -0.0002}), "an exponent"),
    # (f) DIRECTION -- the slot's own word already carries what the row's signed value carries again.
    ("The pace held; the reading was roughly 0.6 z higher [N1].", _calls({1: 0.9}), "a direction word"),
])
def test_every_repair_fence_refuses_and_falls_to_the_figure_cut(text, calls, why):
    """CYCLE-10's verdict, kept: a row value may only be written where nothing can be mistaken. Each
    fence is a RECORDED corruption, and a refusal is never a deletion -- the figure cut takes the slot."""
    st, rep = _run(text, calls, field="mechanism")
    assert [r["rule"] for r in rep["repairs"]] == ["number_mismatch_orphan_figure_cut"], why
    assert "a level this page could not back" in st["mechanism"], why
    assert _unbacked_served(st["mechanism"], calls) == [], why


def test_the_gate7_corruption_can_not_be_minted_by_the_orphan_ladder_either():
    """The op that ended the repair path, run through the ladder on a sentence the lint SAVES. The
    corruption is unreachable and the reader keeps the sentence."""
    text = ("The drought-z score most recently reads 0.940889 z [N2]; one month prior the reading was "
            "roughly 0.6 z higher [N3], meaning the pace of drying moderated.")
    calls = _calls({2: 0.940889, 3: -0.6267})
    st, rep = _run(text, calls, field="mechanism")
    assert "-0.6267" not in st["mechanism"]
    assert "one month prior the reading was" in st["mechanism"]        # the sentence is NOT deleted
    assert "0.940889 z [N2]" in st["mechanism"]
    assert [r["rule"] for r in rep["repairs"]] == ["number_mismatch_orphan_figure_cut"]


def test_scientific_notation_is_one_literal_and_one_cut():
    """MEASURED, and it cost a corruption to find: the banked `v25_baseline_control/rv_beans_meal` line
    came back as "change a level this page could not backea level this page could not back [N20]" when
    the mantissa and the exponent were cut as two figures."""
    text = "- Meal: stocks-to-use 0.0103033 [N17]; change -7.61887e-05 [N20] - essentially flat."
    calls = _pool({17: [0.0103033], 20: [0.0] * 4})
    st, rep = _run(text, calls, field="mechanism")
    assert "backea level" not in st["mechanism"]
    assert st["mechanism"].count("a level this page could not back") == 1
    assert [r["from"] for r in rep["repairs"]] == ["-7.61887e-05"]
    assert "0.0103033 [N17]" in st["mechanism"]


def test_a_range_is_one_cut_not_two():
    text = "Stocks are ample; the band ran 18.75-19.25 [N1] on the newest reading."
    st, rep = _run(text, _pool({1: [0.0, 0.0, 0.0]}), field="mechanism")
    assert st["mechanism"].count("a level this page could not back") == 1
    assert [r["from"] for r in rep["repairs"]] == ["18.75-19.25"]


def test_a_numeral_glued_into_a_word_is_a_name_and_is_never_cut():
    """`tier-1`, `COVID-19`, `top-3`: claim numerals no row can ever back, and cutting one would serve
    "the tier- a level this page could not back material". 1.90% of 85,133 unseen real-seat sentences
    carry the shape."""
    text = "Stocks are ample; the tier-1 material [N1] sides with oil leading the margin."
    st, rep = _run(text, _calls({1: 0.9}), field="mechanism")
    assert "tier-1 material" in st["mechanism"]
    assert "a level this page could not back" not in st["mechanism"]
    assert rep["repairs"] == []


def test_the_orphan_repair_rollback_restores_the_cut_only_ladder():
    """GRAPHRAG_VERIFY_ORPHAN_REPAIR=off: no row value can reach the page by any route, which is
    CYCLE-10's guarantee restored by one environment variable. The sentence still survives."""
    text = "Stocks are ample; the ratio reads 0.50 [N1]."
    os.environ["GRAPHRAG_VERIFY_ORPHAN_REPAIR"] = "off"
    try:
        st, rep = _run(text, _calls({1: 0.9134}), field="mechanism")
    finally:
        os.environ.pop("GRAPHRAG_VERIFY_ORPHAN_REPAIR", None)
    assert "0.91" not in st["mechanism"] and "Stocks are ample;" in st["mechanism"]
    assert [r["rule"] for r in rep["repairs"]] == ["number_mismatch_orphan_figure_cut"]


def test_the_last_backer_is_never_dropped_even_when_it_is_charged():
    """The arm that protects the WIDENED SIBLING RESCUE from the cost round 1 stated in writing: "a
    sentence that attributes the RIGHT figures to the WRONG handles now keeps its figures and loses both
    handles". A charged handle whose own pool is the only thing materializing a printed numeral stays."""
    text = ("Stocks are ample; US soybean meal stocks-to-use ran 0.900012 % [N1] to 0.904064 % [N2], "
            "+0.00405229 [N3].")
    calls = _pool({1: [0.900012], 2: [0.904064], 3: [0.77]})
    st, rep = _run(text, calls, field="mechanism")
    assert "0.900012 % [N1]" in st["mechanism"]                # the last backer of 0.900012
    assert "a level this page could not back" in st["mechanism"]
    assert rep.get("backer_kept", 0) >= 1
    assert _unbacked_served(st["mechanism"], calls) == []


# ======================================================================================================
# MAJOR-2 -- THE LINT IS TWO-SIDED: NEITHER SIDE OF A ';' CUT MAY BE LEFT AS A FRAGMENT
# ======================================================================================================

def test_the_mirror_probe_a_the_lead_clause_is_never_stranded_on_a_bare_semicolon():
    """REVIEWER PROBE A, verbatim: round 1 served "Stocks are ample;" and nothing else."""
    text = "Stocks are ample; the index sat at -0.693675 z [N1]."
    st, rep = _run(text, _calls({1: 0.5}), field="mechanism")
    assert not st["mechanism"].strip().endswith(";")
    assert "the index sat at" in st["mechanism"] and "-0.693675" not in st["mechanism"]
    assert rep["orphan_kept"] == 1


def test_the_mirror_probe_b_a_new_sentence_is_never_welded_onto_a_semicolon():
    """REVIEWER PROBE B, verbatim: round 1 served "Corn is tight; Wheat is loose."."""
    text = "Corn is tight; the ratio reads 0.5 [N1]. Wheat is loose."
    st, rep = _run(text, _pool({1: [0.9, 0.8]}), field="mechanism")
    assert "; Wheat is loose." not in st["mechanism"]
    assert "the ratio reads" in st["mechanism"] and "Wheat is loose." in st["mechanism"]
    assert rep["orphan_kept"] == 1


def test_the_lint_is_asked_before_the_sentence_can_be_killed_by_another_handle():
    """ROUND-2 MAJOR-2 root cause, second half: round 1 asked the lint per HANDLE and AFTER the sibling
    test, so one un-rescuable handle in a ';'-joined clause still took the cut. The verdict belongs to the
    SENTENCE SPAN, so an un-rescuable handle cannot re-open a cut the lint has refused."""
    text = "Stocks are ample; the ratio reads 900 [N1] and the pace ran 800 [N2]."
    st, rep = _run(text, _calls({1: 0.5, 2: 0.6}), field="mechanism")
    assert not st["mechanism"].strip().endswith(";")           # round 1 served "Stocks are ample;"
    assert st["mechanism"].startswith("Stocks are ample; the ratio reads")
    assert "900" not in st["mechanism"] and "800" not in st["mechanism"]
    assert rep["by_rule"]["number_mismatch"] == 2 and rep["orphan_kept"] == 1


# ======================================================================================================
# MAJOR-4 -- THE COUNTERS COUNT WHAT THEY ARE NAMED FOR
# ======================================================================================================

def test_orphan_kept_counts_ORPHANS_not_handles():
    """MEASURED on the banked replay: round 1 read `orphan_kept` 8 where the lint had saved 7 sentences,
    because the counter sat in the PER-OFFENDING-HANDLE loop. Here one sentence, three charged handles."""
    text = "Stocks are ample; record Black Sea seed [N1], softening crush [N2] and oil [N3] all read 900."
    calls = _calls({1: 7.0, 2: 25.1, 3: 4.35})
    _st, rep = _run(text, calls, field="mechanism")
    assert rep["by_rule"]["number_mismatch"] == 3             # three offending handles, unmoved
    assert rep["orphan_kept"] == 1                            # ONE orphan


def test_a_sibling_backed_handle_is_labelled_as_such_even_inside_an_orphan_sentence():
    """MAJOR-4's second half. Round 1 stamped every surviving handle of an orphan sentence
    `number_mismatch_orphan_kept`, including one the SIBLING RESCUE had backed -- an event that was not
    an orphan refusal at all. The label is now read off the HANDLE's own verdict."""
    # 09-23 (lane V): the word-cited [N3] of HEAD's fixture binds no figure and is no longer charged; the
    # sibling-backed conviction is re-pinned on [N3] ADJACENT to [N1], where +1.8 binds to both.
    text = ("Stocks are ample; the ocean signal at +1.8 degC [N1] [N3], +2.4 sigma [N2] all point one "
            "way.")
    calls = _calls({1: 1.8, 2: 2.4, 3: 6.0})
    rules = _audit_rules(text, calls)
    assert "number_mismatch" in rules                          # the sibling-backed handle
    assert "number_mismatch_orphan_kept" not in rules


# ======================================================================================================
# THE ROUND-2 DOCKET (the read panel's synthesizer, confirmed against the traces)
# ======================================================================================================

@pytest.mark.parametrize("prose,calls,charged,figures", [
    (S_DEEP_TLDR, C_DEEP, "[N40]", ["34.76", "+1.8"]),
    (S_CORN_SU, C_CORN, "[N79]", ["16th", "95th"]),
    (S_RAPE, C_RAPE, "[N5]", ["-0.51", "20th"]),
    (S_SOYOIL, C_SOYOIL, "[N73]", ["0.16", "+0.7", "-0.39"]),
    (S_DEEP_WATCH, C_DEEP, "[N40]", ["311.85"]),
])
def test_docket_B1_a_wordless_citation_is_never_charged_by_a_neighbours_numerals(
        prose, calls, charged, figures):
    """DOCKET B-1, pinned with the five smoke sentences VERBATIM. A handle cited for a WORDLESS clause
    ("in the bottom decile of its own record" [N40] = 6 percentile) was charged by its NEIGHBOURS'
    numerals -- 7 of the smoke's 15 charges, 5 of its 8 sentences -- and the round-1 rescue was scoped to
    ONE numeral, so the blast radius was decided by how many figures the writer put in the sentence.
    FOUR of these five carry TWO OR THREE claim numerals: the widened rescue covers them all, the
    sentence survives, every figure keeps its own handle and only the wordless citation goes."""
    # 09-23 FIX ROUND (lane V) -- AMENDED, OWNER-VISIBLE: the handle cited for WORDS is no longer charged.
    # `verify._unbound_handle` reads the binding the writer wrote ("figure [N]"): this handle binds no figure
    # and every figure in the sentence is backed by the handle it binds to, so no figure can contradict it --
    # exactly as the same handle in a digit-free sentence is never charged. The 09-23 fact graders scored
    # HEAD's handle drop on this class a verifier FALSE POSITIVE (tariff 12/12, palm/rape 5/5).
    assert len(vf._claim_number_spans(vf._mask_handles(prose))) >= 1
    st, rep = _run(prose, calls, field="mechanism")
    out = st["mechanism"]
    assert charged in out and out == prose and rep["by_rule"] == {}
    for f in figures:
        assert f in out, f
    assert out.strip() and rep["by_rule"].get("number_unbacked") is None
    assert _unbacked_served(out, calls) == []


@pytest.mark.parametrize("sent,gone", [
    # the row's OWN citation line, which the writer copies verbatim
    ("[N44] NOAA ONI ONI anomaly global MY2026-07 vs 120 points of its own history = 2.4 sigma", 120.0),
    ("Against 36 points of its own history the level is 1.26937 sigma above the mean", 36.0),
    # CADENCE_HISTORY_WINDOW daily = 250, in all three spellings
    ("The board crush reads 2.6 USD/bu, 92nd percentile of its own 250-session record", 250.0),
    ("Board crush 2.6 USD/bu, +0.9 sigma on 250 sessions", 250.0),
    ("the newest of 250 rows covering 2025-09-04..2026-09-04", 250.0),
    # the banked rv_meal_oil sentence that served three figures bare at HEAD
    ("- The window series shows meal at 7.1236 USD/bushel [N5] and oil at 7.8452 USD/bushel [N6] as the "
     "newest of 53 rows covering 2026-06-01..2026-08-20.", 53.0),
])
def test_docket_B2_a_window_or_record_LENGTH_is_never_a_claim_figure(sent, gone):
    assert gone not in [v for _a, _b, v in vf._claim_number_spans(sent)]


@pytest.mark.parametrize("sent", [
    "prices have risen for 5 months in a row [N10]",
    "ending stocks cover 21 days of use [N6]",
    "US corn is 12 days ahead of the pace [N4]",
    "the crush ran 3 weeks behind schedule [N5]",
    "exports rose in each of the last 5 months of the marketing year [N1]",
    "stocks are 12 months of use [N8]",
    "the front spread traded in a 12-point range and then a 5-point move",
    "corn was planted in 30-inch rows across the belt",
])
def test_docket_B2_the_head_position_counter_examples_are_still_claims(sent):
    """The (h-iii) `of` spelling admits OBSERVATION units only, and only in front of a window HEAD noun
    or a window continuation -- so every cycle-8 head-position sentence stays a claim, and so does an
    agronomic 'rows'. 0 numerals were ADDED and 61 de-charged across 110,298 HEAD claim numerals on
    85,133 unseen real-seat sentences; every one of the 61 is a window or record length."""
    assert vf._claim_number_spans(sent)


def test_docket_B3_a_date_that_equals_the_citations_own_date_is_overlap_by_construction():
    """DOCKET B-3, the smoke sentence VERBATIM (quick_rv_palm_rapeoil, 3 of its 15 charges and 3 of 3
    outside the number lane). The sentence is ABOUT the documents' dates, so it shares no word with their
    PROSE by construction and all three handles were stripped -- a recency-honesty sentence stripped of
    exactly the handles that make it honest. E3/E1/E11's own dates are 2026-03-31, 2023-03-13,
    2022-03-15, recorded in the turn's `citation_resolved` and PRINTED in its footer."""
    sent = ("- Dated documents are thin and old for this pair: the newest behind this answer is "
            "2026-03-31 [E3], and the substitution mechanics I lean on date to 2023 [E1] and 2022 [E11].")
    ev = [{"source": "usda_gain_soybean_oil", "date": "2026-03-31",
           "text": "Palm oil has risen to second place in Mexican domestic vegetable oil consumption."},
          {"source": "mpoc", "date": "2023-03-13",
           "text": "The filling of the sunflower seed oil gap by rapeseed oil will give more room."},
          {"source": "mpoc", "date": "2022-03-15",
           "text": "If palm oil prices remain high, rapeseed oil used as biodiesel would strengthen."}]
    ledger = [{"ref": 3, "source": "usda_gain_soybean_oil", "date": "2026-03-31"},
              {"ref": 1, "source": "mpoc", "date": "2023-03-13"},
              {"ref": 11, "source": "mpoc", "date": "2022-03-15"}]
    st = {"tldr": "", "mechanism": sent, "sources": [dict(x) for x in ledger]}
    rep = vf.verify_citations(st, [dict(x) for x in ev], [])
    assert rep["by_rule"].get("no_lexical_overlap") is None
    for h in ("[E3]", "[E1]", "[E11]"):
        assert h in st["mechanism"], h


def test_docket_B3_the_year_arm_needs_a_vintage_word_and_the_full_iso_date_never_does():
    """The fence on the loose arm: a bare year is the commonest numeral in this estate's prose, so it
    backs a handle ONLY beside a vintage word. The full ISO date is self-identifying and always does."""
    ev = [{"source": "mpoc", "date": "2023-03-13", "text": "Palm stocks drew down through the quarter."}]
    assert vf._date_echo("the newest behind this answer is 2023-03-13", ev) is True
    assert vf._date_echo("the mechanics I lean on date to 2023", ev) is True
    assert vf._date_echo("crush margins widened by 2023 cents per bushel", ev) is False
    assert vf._date_echo("the reading is old", [{"source": "mpoc", "date": None}]) is False


def test_docket_B4_strip_sentences_counts_distinct_sentences_and_stripped_does_not_move():
    """DOCKET B-4. `stripped` counts OFFENDING HANDLES and every banked number in this estate is
    denominated in it, so it does NOT move. `strip_sentences` is the honest numerator beside it: the
    smoke's deep turn reported `strips = 5` over THREE distinct sentences and the read panel read five
    findings. It is populated whether or not GRAPHRAG_STRIP_AUDIT is lit."""
    three = "Stocks are ample; record Black Sea seed [N1], softening crush [N2] and oil [N3] all read 900."
    _st, rep = _run(three, _calls({1: 7.0, 2: 25.1, 3: 4.35}), field="mechanism")
    assert rep["stripped"] == 3                               # three offending handles, unmoved
    assert rep["strip_sentences"] == 1                        # ...on ONE sentence
    assert "strip_audit" not in rep                           # the capture is still flag-gated
    clean, rep2 = _run("Stocks are comfortable and the board is two-sided.", C_RAPE, field="mechanism")
    assert clean["mechanism"] and rep2["strip_sentences"] == 0 and rep2["stripped"] == 0


@pytest.mark.parametrize("sent,claim", [
    # ROUND-1 REVIEW MINOR-1 -- an ORTHOGRAPHIC magnitude whose head noun `range`/`span` read as a window
    # head. The numeral IS the quantity, and (h-i) was exempting it.
    ("the front spread traded in a 12-point range [N3]", 12.0),
    ("a 30-point range [N2]", 30.0),
    ("a 40-point span [N9]", 40.0),
    # ROUND-1 REVIEW MINOR-2 -- a CENTRE read OVER a window, not a dispersion statistic read AGAINST one.
    # This is the class CYCLE-8 BLOCKER 2 protects, and (h-ii)'s statistic lead had re-opened a sliver.
    ("Stocks cover an average of 21 days [N6].", 21.0),
    ("Inventory turns at a median of 45 days [N12].", 45.0),
    ("Shipments lag by an average of 6 weeks [N7].", 6.0),
])
def test_round1_review_minors_1_and_2_are_closed_the_numeral_is_still_a_claim(sent, claim):
    """`range` / `span` leave `_WINDOW_HEAD` and `mean|average|median|rank` leave `_WINDOW_STAT`. The
    round-1 reviewer measured 0 instances of either shape in 110,298 real-seat claim numerals, and after
    the tightening the de-charge census over the SAME 85,133 unseen sentences is unchanged at 61 with 0
    numerals added -- so the exemptions cost nothing and the holes were real."""
    assert claim in [v for _a, _b, v in vf._claim_number_spans(sent)]


@pytest.mark.parametrize("sent,gone", [
    ("+2.4 sigma on 120 months [N24]", 120.0),
    ("92nd percentile of its own 250-session record [N38]", 250.0),
    ("at the 29th percentile of the 320-session window read [N30]", 320.0),
    ("vs 120 points of its own history = 2.4 sigma", 120.0),
    ("the newest of 43 rows spanning 2023-01-01..2026-07-01", 43.0),
])
def test_every_measured_window_length_survives_the_minor_tightening(sent, gone):
    assert gone not in [v for _a, _b, v in vf._claim_number_spans(sent)]


# ======================================================================================================
# ROUND 3 (2026-09-17) -- THE ROUND-2 REVIEW'S FOUR NEW MAJORS.
#
# Two of them are SERVED-PROSE CORRUPTIONS the figure cut minted in itself: it wrote its replacement
# words into the middle of an ORDINAL SUFFIX ("the 93rd percentile" -> "the a level this page could not
# backrd percentile") and it DELETED a transitive comparative and stranded its object ("1.31603 sigma
# above its five-year mean" -> "a level this page could not back its five-year mean"). Neither fired on
# the 112 banked answers or the five smoke drafts by luck, not by fence: 0 of the sixteen sentences the
# ladder saves happens to carry either shape, while 543 and 63 claim numerals of the 107,754 in the
# 85,133-sentence unseen real-seat corpus do. Both are closed in `_figure_span`, which can now only ever
# take MORE of a written quantity and LESS of the words around it.
#
# The fixtures are the reviewer's own probes (`prearm_fix_r2/RV2/probe_ordinal_weld.py`), whose wordings
# are taken from this smoke's own answers -- `S_DEEP_ENSO` prints "93rd percentile [N25]",
# `S_CORN_SU` "the 16th percentile of its own record [N81]" and `S_MAX_CRUSH` "92nd percentile of its
# own 250-session record [N38]" -- put in the ';'-joined bullet shape the banked corpus already serves,
# which is the shape the orphan lint saves.
# ======================================================================================================

@pytest.mark.parametrize("text,cut,tail", [
    (("- Tropical Pacific is warm; the ocean signal sits at the 93rd percentile of its own record "
      "[N1]."), "93rd", "percentile of its own record [N1]."),
    ("- Corn is tight; stocks-to-use sits at the 16th percentile of its own record [N1].",
     "16th", "percentile of its own record [N1]."),
    (("- The crush is rich; it prints the 92nd percentile of its own 250-session record [N1]."),
     "92nd", "percentile of its own 250-session record [N1]."),
])
def test_the_figure_cut_takes_the_ORDINAL_SUFFIX_WITH_the_numeral(text, cut, tail):
    """ROUND-2 REVIEW NEW-MAJOR-1. `_claim_number_spans` ends a span at the token CORE by contract, so
    "93rd percentile" handed the cut the span "93" and the replacement words welded onto the live "rd".
    The suffix is part of the numeral and leaves with it; the words around it are untouched."""
    calls = _calls({1: 0.5})
    st, rep = _run(text, calls, field="mechanism")
    out = st["mechanism"]
    for suffix in ("st", "nd", "rd", "th"):
        assert ("could not back" + suffix) not in out, suffix     # the weld, in all four spellings
    assert [r["from"] for r in rep["repairs"]] == [cut]
    assert out.endswith("a level this page could not back " + tail)
    assert _unbacked_served(out, calls) == []


def test_the_cut_span_takes_the_ordinal_AND_the_unit_glued_behind_it():
    """The suffix is taken BEFORE the unit tail, so a percent sign written after an ordinal still leaves
    with the numeral rather than being orphaned onto the replacement words."""
    sent = "it sits at the 93rd % of its own record"
    a = sent.index("93")
    assert vf._figure_span(sent, a, a + 2) == (a, sent.index(" of"))
    assert sent[a:sent.index(" of")] == "93rd %"


def test_a_transitive_comparative_and_its_object_both_survive_the_figure_cut():
    """ROUND-2 REVIEW NEW-MAJOR-2, on verbatim writer prose from the banked corpus. `_FIGCUT_COMP` took
    a one-word comparative whatever followed it, so the DIRECTION WORD was deleted and its object left
    dangling -- "soyoil sits a level this page could not back its five-year mean [N1]". By this estate's
    own doctrine that is the fatal shape at word scale: a fence that removes a word carrying the claim
    and leaves wreckage behind it. Only the numeral is cut now."""
    text = "Positioning is mixed; soyoil sits 1.31603 sigma above its five-year mean [N1]."
    calls = _calls({1: 900.0})
    st, rep = _run(text, calls, field="mechanism")
    assert st["mechanism"] == ("Positioning is mixed; soyoil sits a level this page could not back "
                               "above its five-year mean [N1].")
    assert [r["from"] for r in rep["repairs"]] == ["1.31603 sigma"]
    assert _unbacked_served(st["mechanism"], calls) == []


def test_a_comparative_that_governs_NOTHING_still_rides_with_the_figure():
    """The negative half, and the reason `_FIGCUT_COMP` exists at all: "roughly 0.6 z higher [N3]" must
    not become "roughly a level this page could not back higher". Where the comparative is followed by a
    handle, punctuation or the end of the sentence it has no object to strand, and it leaves."""
    text = "The pace held; the reading was roughly 0.6 z higher [N1]."
    st, rep = _run(text, _calls({1: 0.9}), field="mechanism")
    assert st["mechanism"] == "The pace held; the reading was roughly a level this page could not back [N1]."
    assert [r["from"] for r in rep["repairs"]] == ["0.6 z higher"]


def test_orphan_kept_ACCUMULATES_ACROSS_BOTH_FIELDS():
    """ROUND-2 REVIEW NEW-MAJOR-3. `report["orphan_kept"]` was a per-field ASSIGNMENT inside
    `_verify_field`, which `verify_citations` calls once for `tldr` and once for `mechanism`; `orphaned`
    is that call's own local, so the second field OVERWROTE the first and the answer-level counter read
    the second field alone. `backer_kept` beside it was already an accumulator. A real deep turn carries
    bulleted ';'-joined prose in BOTH fields, and this is the number the handoff asks lane F to print
    per answer as `verifier_orphan_kept`."""
    probe = "Stocks are ample; the index sat at 12.5 [N1]."
    calls = _pool({1: [3.0, 9.0]})
    st = {"tldr": probe, "mechanism": probe, "sources": []}
    rep = vf.verify_citations(st, [], calls)
    assert rep["orphan_kept"] == 2                            # round 2 read 1
    assert rep["stripped"] == 2 and rep["strip_sentences"] == 2
    assert len(rep["repairs"]) == 2
    assert st["tldr"] == st["mechanism"]                      # both fields served, both corrected
    assert "12.5" not in st["tldr"] and "[N1]" in st["tldr"]


@pytest.mark.parametrize("flag,value", [
    ("GRAPHRAG_VERIFY_NUM_POOL", "all"),
    ("GRAPHRAG_CASCADE_QUANT", "off"),
    ("GRAPHRAG_VERIFY_UNIT_VOCAB", "off"),
    ("GRAPHRAG_STRIP_AUDIT", "off"),
])
def test_the_four_ORTHOGONAL_flags_do_not_gate_this_lanes_correction(flag, value):
    """ROUND-2 REVIEW NEW-MAJOR-4, pinned so the byte-identical set can never drift back into prose.
    The round-2 report listed six rollbacks as behaving "exactly as at HEAD". MEASURED over the 112
    banked answers, tree vs HEAD: `GRAPHRAG_VERIFY=off` differs on 0, `GRAPHRAG_VERIFY_NUM_MODE=handle`
    on 1 and these four on 42 each -- because they gate OTHER features and were never rollbacks of this
    lane at all. The correction rides both cells of arm A by charter; what each flag reverts is its own
    feature, and this pin says so in code."""
    text = "- Canadian canola production was last read at 22,500,000 MT [N1]; the read holds."
    calls = _pool({1: [300000.0, 513000.0, 585000.0]})
    os.environ[flag] = value
    try:
        st, _rep = _run(text, calls, field="mechanism")
    finally:
        os.environ.pop(flag, None)
    assert "22,500,000" not in st["mechanism"]
    assert "a level this page could not back [N1]; the read holds." in st["mechanism"]


def test_only_the_kill_switch_reverts_the_served_bytes_to_HEADs_own_remedy():
    """The other half of NEW-MAJOR-4: `GRAPHRAG_VERIFY=off` is the ONE full revert -- the draft is served
    untouched -- and `GRAPHRAG_VERIFY_NUM_MODE=handle` restores HEAD's REMEDY (the handle comes off, the
    sentence stays), which on this sentence means HEAD's own bare figure. That is the documented legacy
    behaviour and it is what `=handle` is for; it is not this lane's output."""
    text = "- Canadian canola production was last read at 22,500,000 MT [N1]; the read holds."
    calls = _pool({1: [300000.0, 513000.0, 585000.0]})
    os.environ["GRAPHRAG_VERIFY"] = "off"
    try:
        st, rep = _run(text, calls, field="mechanism")
    finally:
        os.environ.pop("GRAPHRAG_VERIFY", None)
    assert st["mechanism"] == text and rep["enabled"] is False
    os.environ["GRAPHRAG_VERIFY_NUM_MODE"] = "handle"
    try:
        st, _rep = _run(text, calls, field="mechanism")
    finally:
        os.environ.pop("GRAPHRAG_VERIFY_NUM_MODE", None)
    assert st["mechanism"] == ("- Canadian canola production was last read at 22,500,000 MT; "
                               "the read holds.")


@pytest.mark.parametrize("text,calls,cut", [
    # the eight-row canola window: 40 rows on the banked call, 34 distinct values at the page's own
    # precision. There is no "the cited row" to substitute.
    ("Stocks are ample; Canadian canola production was last read at 22,500,000 MT [N1].",
     _pool({1: [300000.0, 513000.0, 585000.0, 560000.0, 440000.0, 758000.0, 1638000.0, 2155000.0]}),
     "22,500,000 MT"),
    # the ratio slot whose whole pool rounds to "0" at the page's ZERO decimals: fence (a) is cleared by
    # an artefact of precision and fence (c) is the only thing between the reader and "0 ratio".
    ("Stocks are ample; soybean oil stocks-to-use reads 7 ratio [N1] on the newest reading.",
     _pool({1: [0.2631578947368421, 0.060976, 0.041494, 0.0, 0.0, 0.0]}), "7 ratio"),
])
def test_the_narrowing_premise_does_not_hold_the_cut_still_carries_these_slots(text, calls, cut):
    """THE ROUND-3 RULING, REFUTED ON ITS OWN POPULATION AND PINNED SO THE REFUTATION CANNOT ROT.
    "The handle always resolves to a served row" is false here: MEASURED over the 112 banked answers and
    the five smoke drafts, the ladder cuts 21 slots, 8 of them in MULTI-handle sentences (outside the
    ruling's own scope) and every one of the 13 single-handle slots citing a call that carries 40 rows
    taking 4 to 34 distinct values -- 1 exception, the one-row exponent slot, which is half of a written
    literal. Substituting anyway writes "0 ratio" over "7 ratio" out of a six-value window (fence (c)
    refuses it) and "309,000 MT" over "4,091,000 MT" out of a forty-row one (fence (a) refuses it):
    gate-6 COV1 verbatim. Choosing which row a window means is a NEW RULE, and this round adds none."""
    st, rep = _run(text, calls, field="mechanism")
    assert [r["from"] for r in rep["repairs"]] == [cut]
    assert [r["rule"] for r in rep["repairs"]] == ["number_mismatch_orphan_figure_cut"]
    assert _unbacked_served(st["mechanism"], calls) == []
